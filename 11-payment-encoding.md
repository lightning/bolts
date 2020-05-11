# BOLT #11: Invoice Protocol for Lightning Payments

A simple, extendable, QR-code-ready protocol for requesting payments
over Lightning.

# Table of Contents

  * [Encoding Overview](#encoding-overview)
  * [Human-Readable Part](#human-readable-part)
  * [Data Part](#data-part)
    * [Tagged Fields](#tagged-fields)
    * [Feature Bits](#feature-bits)
  * [Payer / Payee Interactions](#payer--payee-interactions)
    * [Payer / Payee Requirements](#payer--payee-requirements)
  * [Implementation](#implementation)
  * [Examples](#examples)
  * [Authors](#authors)

# Encoding Overview

The format for a Lightning invoice uses
[bech32 encoding](https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki),
which is already used for Bitcoin Segregated Witness. It can be
simply reused for Lightning invoices even though its 6-character checksum is optimized
for manual entry, which is unlikely to happen often given the length
of Lightning invoices.

If a URI scheme is desired, the current recommendation is to either
use 'lightning:' as a prefix before the BOLT-11 encoding (note: not
'lightning://'), or for fallback to Bitcoin payments, to use 'bitcoin:',
as per BIP-21, with the key 'lightning' and the value equal to the BOLT-11
encoding.

## Requirements

A writer:
   - MUST encode the payment request in Bech32 (see BIP-0173)
   - MAY exceed the 90-character limit specified in BIP-0173.

A reader:
  - MUST parse the address as Bech32, as specified in BIP-0173 (also without the character limit).
  - if the checksum is incorrect:
    - MUST fail the payment.

# Human-Readable Part

The human-readable part of a Lightning invoice consists of two sections:
1. `prefix`: `ln` + BIP-0173 currency prefix (e.g. `lnbc` for Bitcoin mainnet,
   `lntb` for Bitcoin testnet, and `lnbcrt` for Bitcoin regtest)
1. `amount`: optional number in that currency, followed by an optional
   `multiplier` letter. The unit encoded here is the 'social' convention of a payment unit -- in the case of Bitcoin the unit is 'bitcoin' NOT satoshis.

The following `multiplier` letters are defined:

* `m` (milli): multiply by 0.001
* `u` (micro): multiply by 0.000001
* `n` (nano): multiply by 0.000000001
* `p` (pico): multiply by 0.000000000001

## Requirements

A writer:
  - MUST encode `prefix` using the currency required for successful payment.
  - if a specific minimum `amount` is required for successful payment:
	  - MUST include that `amount`.
	- MUST encode `amount` as a positive decimal integer with no leading 0s.
	- If the `p` multiplier is used the last decimal of `amount` MUST be `0`.
	- SHOULD use the shortest representation possible, by using the largest
	  multiplier or omitting the multiplier.

A reader:
  - if it does NOT understand the `prefix`:
    - MUST fail the payment.
  - if the `amount` is empty:
	  - SHOULD indicate to the payer that amount is unspecified.
  - otherwise:
    - if `amount` contains a non-digit OR is followed by anything except
    a `multiplier` (see table above):
  	  - MUST fail the payment.
    - if the `multiplier` is present:
	  - MUST multiply `amount` by the `multiplier` value to derive the
      amount required for payment.
      - if multiplier is `p` and the last decimal of `amount` is not 0:
	    - MUST fail the payment.

## Rationale

The `amount` is encoded into the human readable part, as it's fairly
readable and a useful indicator of how much is being requested.

Donation addresses often don't have an associated amount, so `amount`
is optional in that case. Usually a minimum payment is required for
whatever is being offered in return.

The `p` multiplier would allow to specify sub-millisatoshi amounts, which cannot be transferred on the network, since HTLCs are denominated in millisatoshis.
Requiring a trailing `0` decimal ensures that the `amount` represents an integer number of millisatoshis.

# Data Part

The data part of a Lightning invoice consists of multiple sections:

1. `timestamp`: seconds-since-1970 (35 bits, big-endian)
1. zero or more tagged parts
1. `signature`: Bitcoin-style signature of above (520 bits)

## Requirements

A writer:
  - MUST set `timestamp` to the number of seconds since Midnight 1 January 1970, UTC in
  big-endian.
  - MUST set `signature` to a valid 512-bit secp256k1 signature of the SHA2 256-bit hash of the
  human-readable part, represented as UTF-8 bytes, concatenated with the
  data part (excluding the signature) with 0 bits appended to pad the
  data to the next byte boundary, with a trailing byte containing
  the recovery ID (0, 1, 2, or 3).

A reader:
  - MUST check that the `signature` is valid (see the `n` tagged field specified below).

## Rationale

`signature` covers an exact number of bytes even though the SHA2
standard actually supports hashing in bit boundaries, because it's not widely
implemented. The recovery ID allows public-key recovery, so the
identity of the payee node can be implied.

## Tagged Fields

Each Tagged Field is of the form:

1. `type` (5 bits)
1. `data_length` (10 bits, big-endian)
1. `data` (`data_length` x 5 bits)

Currently defined tagged fields are:

* `p` (1): `data_length` 52. 256-bit SHA256 payment_hash. Preimage of this provides proof of payment.
* `s` (16): `data_length` 52. This 256-bit secret prevents forwarding nodes from probing the payment recipient.
* `d` (13): `data_length` variable. Short description of purpose of payment (UTF-8), e.g. '1 cup of coffee' or 'ナンセンス 1杯'
* `n` (19): `data_length` 53. 33-byte public key of the payee node
* `h` (23): `data_length` 52. 256-bit description of purpose of payment (SHA256). This is used to commit to an associated description that is over 639 bytes, but the transport mechanism for the description in that case is transport specific and not defined here.
* `x` (6): `data_length` variable. `expiry` time in seconds (big-endian). Default is 3600 (1 hour) if not specified.
* `c` (24): `data_length` variable. `min_final_cltv_expiry` to use for the last HTLC in the route. Default is 9 if not specified.
* `f` (9): `data_length` variable, depending on version. Fallback on-chain address: for Bitcoin, this starts with a 5-bit `version` and contains a witness program or P2PKH or P2SH address.
* `r` (3): `data_length` variable. One or more entries containing extra routing information for a private route; there may be more than one `r` field
   * `pubkey` (264 bits)
   * `short_channel_id` (64 bits)
   * `fee_base_msat` (32 bits, big-endian)
   * `fee_proportional_millionths` (32 bits, big-endian)
   * `cltv_expiry_delta` (16 bits, big-endian)
* `9` (5): `data_length` variable. One or more 5-bit values containing features
  supported or required for receiving this payment.
  See [Feature Bits](#feature-bits).

### Requirements

A writer:
  - MUST include exactly one `p` field.
  - If the `payment_secret` feature is set, MUST include exactly one `s` field.
  - MUST set `payment_hash` to the SHA2 256-bit hash of the `payment_preimage`
  that will be given in return for payment.
  - MUST include either exactly one `d` or exactly one `h` field.
    - if `d` is included:
      - MUST set `d` to a valid UTF-8 string.
      - SHOULD use a complete description of the purpose of the payment.
    - if `h` is included:
      - MUST make the preimage of the hashed description in `h` available
      through some unspecified means.
        - SHOULD use a complete description of the purpose of the payment.
  - MAY include one `x` field.
    - if `x` is included:
      - SHOULD use the minimum `data_length` possible.
  - MAY include one `c` field.
    - MUST set `c` to the minimum `cltv_expiry` it will accept for the last
    HTLC in the route.
    - if `c` is included:
      - SHOULD use the minimum `data_length` possible.
  - MAY include one `n` field. (Otherwise performing signature recovery is required)
    - MUST set `n` to the public key used to create the `signature`.
  - MAY include one or more `f` fields.
    - for Bitcoin payments:
      - MUST set an `f` field to a valid witness version and program, OR to `17`
      followed by a public key hash, OR to `18` followed by a script hash.
  - if there is NOT a public channel associated with its public key:
    - MUST include at least one `r` field.
      - `r` field MUST contain one or more ordered entries, indicating the forward route from
      a public node to the final destination.
        - Note: for each entry, the `pubkey` is the node ID of the start of the channel;
        `short_channel_id` is the short channel ID field to identify the channel; and
        `fee_base_msat`, `fee_proportional_millionths`, and `cltv_expiry_delta` are as
        specified in [BOLT #7](07-routing-gossip.md#the-channel_update-message).
    - MAY include more than one `r` field to provide multiple routing options.
  - if `9` contains non-zero bits:
    - SHOULD use the minimum `data_length` possible.
  - otherwise:
    - MUST omit the `9` field altogether.
  - MUST pad field data to a multiple of 5 bits, using 0s.
  - if a writer offers more than one of any field type, it:
    - MUST specify the most-preferred field first, followed by less-preferred fields, in order.

A reader:
  - MUST skip over unknown fields, OR an `f` field with unknown `version`, OR  `p`, `h`, `s` or
  `n` fields that do NOT have `data_length`s of 52, 52, 52 or 53, respectively.
  - if the `9` field contains unknown _odd_ bits that are non-zero:
    - MUST ignore the bit.
  - if the `9` field contains unknown _even_ bits that are non-zero:
    - MUST fail the payment.
	- SHOULD indicate the unknown bit to the user.
  - MUST check that the SHA2 256-bit hash in the `h` field exactly matches the hashed
  description.
  - if a valid `n` field is provided:
    - MUST use the `n` field to validate the signature instead of performing signature recovery.
  - if there is a valid `s` field:
    - MUST use that as [`payment_secret`](04-onion-routing.md#tlv_payload-payload-format)

### Rationale

The type-and-length format allows future extensions to be backward
compatible. `data_length` is always a multiple of 5 bits, for easy
encoding and decoding. Readers also ignore fields of different length,
for fields that are expected may change.

The `p` field supports the current 256-bit payment hash, but future
specs could add a new variant of different length: in which case,
writers could support both old and new variants, and old readers would
ignore the variant not the correct length.

The `d` field allows inline descriptions, but may be insufficient for
complex orders. Thus, the `h` field allows a summary: though the method
by which the description is served is as-yet unspecified and will
probably be transport dependent. The `h` format could change in the future,
by changing the length, so readers ignore it if it's not 256 bits.

The `n` field can be used to explicitly specify the destination node ID,
instead of requiring signature recovery.

The `x` field gives warning as to when a payment will be
refused: mainly to avoid confusion. The default was chosen
to be reasonable for most payments and to allow sufficient time for
on-chain payment, if necessary.

The `c` field allows a way for the destination node to require a specific
minimum CLTV expiry for its incoming HTLC. Destination nodes may use this
to require a higher, more conservative value than the default one (depending
on their fee estimation policy and their sensitivity to time locks). Note
that remote nodes in the route specify their required `cltv_expiry_delta`
in the `channel_update` message, which they can update at all times.

The `f` field allows on-chain fallback; however, this may not make sense for
tiny or time-sensitive payments. It's possible that new
address forms will appear; thus, multiple `f` fields (in an implied
preferred order) help with transition, and `f` fields with versions 19-31
will be ignored by readers.

The `r` field allows limited routing assistance: as specified, it only
allows minimum information to use private channels, however, it could also
assist in future partial-knowledge routing.

### Security Considerations for Payment Descriptions

Payment descriptions are user-defined and provide a potential avenue for
injection attacks: during the processes of both rendering and persistence.

Payment descriptions should always be sanitized before being displayed in
HTML/Javascript contexts (or any other dynamically interpreted rendering
frameworks). Implementers should be extra perceptive to the possibility of
reflected XSS attacks, when decoding and displaying payment descriptions. Avoid
optimistically rendering the contents of the payment request until all
validation, verification, and sanitization processes have been successfully
completed.

Furthermore, consider using prepared statements, input validation, and/or
escaping, to protect against injection vulnerabilities in persistence
engines that support SQL or other dynamically interpreted querying languages.

* [Stored and Reflected XSS Prevention](https://www.owasp.org/index.php/XSS_(Cross_Site_Scripting)_Prevention_Cheat_Sheet)
* [DOM-based XSS Prevention](https://www.owasp.org/index.php/DOM_based_XSS_Prevention_Cheat_Sheet)
* [SQL Injection Prevention](https://www.owasp.org/index.php/SQL_Injection_Prevention_Cheat_Sheet)

Don't be like the school of [Little Bobby Tables](https://xkcd.com/327/).

## Feature Bits

Feature bits allow forward and backward compatibility, and follow the
_it's ok to be odd_ rule.  Features appropriate for use in the `9` field
are marked in [BOLT 9](09-features.md).

The field is big-endian.  The least-significant bit is numbered 0,
which is _even_, and the next most significant bit is numbered 1,
which is _odd_.

Note that the `payment_secret` feature prevents probing attacks from nodes
along the path, but only if made compulsory: yet doing so will break
older clients which do not understand the feature.  It is compulsory
for `basic_mpp` however, as that is also a recent feature, and makes
nodes more vulnerable to probing attacks as there is no lower-bound
on the amount sent.

### Requirements

A writer:
  - MUST set the `9` field to a feature vector compliant with the
    [BOLT 9 origin node requirements](09-features.md#requirements).
  - MUST set an `s` field if and only if the `payment_secret` feature is set.

A reader:
  - if the feature vector does not set all known, transitive feature dependencies:
    - MUST NOT attempt the payment.
  - if the `basic_mpp` feature is offered in the invoice:
    - MAY pay using [Basic multi-part payments](04-onion-routing.md#basic-multi-part-payments).
  - otherwise:
    - MUST NOT use [Basic multi-part payments](04-onion-routing.md#basic-multi-part-payments).


# Payer / Payee Interactions

These are generally defined by the rest of the Lightning BOLT series,
but it's worth noting that [BOLT #4](04-onion-routing.md#requirements-2) specifies that the payee SHOULD
accept up to twice the expected `amount`, so the payer can make
payments harder to track by adding small variations.

The intent is that the payer recovers the payee's node ID from the
signature, and after checking that conditions such as fees,
expiry, and block timeout are acceptable, attempts a payment. It can use `r` fields to
augment its routing information, if necessary to reach the final node.

If the payment succeeds but there is a later dispute, the payer can
prove both the signed offer from the payee and the successful
payment.

## Payer / Payee Requirements

A payer:
  - after the `timestamp` plus `expiry` has passed:
    - SHOULD NOT attempt a payment.
  - otherwise:
    - if a Lightning payment fails:
      - MAY attempt to use the address given in the first `f` field that it
      understands for payment.
  - MAY use the sequence of channels, specified by the `r` field, to route to the payee.
  - SHOULD consider the fee amount and payment timeout before initiating payment.
  - SHOULD use the first `p` field that it did NOT skip as the payment hash.

A payee:
  - after the `timestamp` plus `expiry` has passed:
    - SHOULD NOT accept a payment.

# Implementation

https://github.com/rustyrussell/lightning-payencode

# Examples

NB: all the following examples are signed with `priv_key`=`e126f68f7eafcc8b74f54d269fe206be715000f94dac067d1c04a8ca3b2db734`.  Also, the first 9 examples are legacy: modern invoices have an `s` field. 

> ### Please make a donation of any amount using payment_hash 0001020304050607080900010203040506070809000102030405060708090102 to me @03e7156ae33b0a208d0744199163177e909e80176e55d97a2f221ede0f934dd9ad
> lnbc1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdpl2pkx2ctnv5sxxmmwwd5kgetjypeh2ursdae8g6twvus8g6rfwvs8qun0dfjkxaq8rkx3yf5tcsyz3d73gafnh3cax9rn449d9p5uxz9ezhhypd0elx87sjle52x86fux2ypatgddc6k63n7erqz25le42c4u4ecky03ylcqca784w

Breakdown:

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash
  * `p5`: `data_length` (`p` = 1, `5` = 20; 1 * 32 + 20 == 52)
  * `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: payment hash 0001020304050607080900010203040506070809000102030405060708090102
* `d`: short description
  * `pl`: `data_length` (`p` = 1, `l` = 31; 1 * 32 + 31 == 63)
  * `2pkx2ctnv5sxxmmwwd5kgetjypeh2ursdae8g6twvus8g6rfwvs8qun0dfjkxaq`: 'Please consider supporting this project'
* `8rkx3yf5tcsyz3d73gafnh3cax9rn449d9p5uxz9ezhhypd0elx87sjle52x86fux2ypatgddc6k63n7erqz25le42c4u4ecky03ylcq`: signature
* `ca784w`: Bech32 checksum
* Signature breakdown:
  * `38ec6891345e204145be8a3a99de38e98a39d6a569434e1845c8af7205afcfcc7f425fcd1463e93c32881ead0d6e356d467ec8c02553f9aab15e5738b11f127f` hex of signature data (32-byte r, 32-byte s)
  * `0` (int) recovery flag contained in `signature`
  * `6c6e62630b25fe64410d00004080c1014181c20240004080c1014181c20240004080c1014181c202404081a1fa83632b0b9b29031b7b739b4b232b91039bab83837b93a34b733903a3434b990383937b532b1ba0` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `c3d4e83f646fa79a393d75277b1d858db1d1f7ab7137dcb7835db2ecd518e1c9` hex of SHA256 of the preimage

> ### Please send $3 for a cup of coffee to the same peer, within one minute
> lnbc2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpuaztrnwngzn3kdzw5hydlzf03qdgm2hdq27cqv3agm2awhz5se903vruatfhq77w3ls4evs3ch9zw97j25emudupq63nyw24cg27h2rspfj9srp

Breakdown:

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `2500u`: amount (2500 micro-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `d`: short description
  * `q5`: `data_length` (`q` = 0, `5` = 20; 0 * 32 + 20 == 20)
  * `xysxxatsyp3k7enxv4js`: '1 cup coffee'
* `x`: expiry time
  * `qz`: `data_length` (`q` = 0, `z` = 2; 0 * 32 + 2 == 2)
  * `pu`: 60 seconds (`p` = 1, `u` = 28; 1 * 32 + 28 == 60)
* `aztrnwngzn3kdzw5hydlzf03qdgm2hdq27cqv3agm2awhz5se903vruatfhq77w3ls4evs3ch9zw97j25emudupq63nyw24cg27h2rsp`: signature
* `fj9srp`: Bech32 checksum
* Signature breakdown:
  * `e89639ba6814e36689d4b91bf125f10351b55da057b00647a8dabaeb8a90c95f160f9d5a6e0f79d1fc2b964238b944e2fa4aa677c6f020d466472ab842bd750e` hex of signature data (32-byte r, 32-byte s)
  * `1` (int) recovery flag contained in `signature`
  * `6c6e626332353030750b25fe64410d00004080c1014181c20240004080c1014181c20240004080c1014181c202404081a0a189031bab81031b7b33332b2818020f00` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `3cd6ef07744040556e01be64f68fd9e1565fb47d78c42308b1ee005aca5a0d86` hex of SHA256 of the preimage

> ### Please send 0.0025 BTC for a cup of nonsense (ナンセンス 1杯) to the same peer, within one minute
> lnbc2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdpquwpc4curk03c9wlrswe78q4eyqc7d8d0xqzpuyk0sg5g70me25alkluzd2x62aysf2pyy8edtjeevuv4p2d5p76r4zkmneet7uvyakky2zr4cusd45tftc9c5fh0nnqpnl2jfll544esqchsrny

Breakdown:

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `2500u`: amount (2500 micro-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `d`: short description
  * `pq`: `data_length` (`p` = 1, `q` = 0; 1 * 32 + 0 == 32)
  * `uwpc4curk03c9wlrswe78q4eyqc7d8d0`: 'ナンセンス 1杯'
* `x`: expiry time
  * `qz`: `data_length` (`q` = 0, `z` = 2; 0 * 32 + 2 == 2)
  * `pu`: 60 seconds (`p` = 1, `u` = 28; 1 * 32 + 28 == 60)
* `yk0sg5g70me25alkluzd2x62aysf2pyy8edtjeevuv4p2d5p76r4zkmneet7uvyakky2zr4cusd45tftc9c5fh0nnqpnl2jfll544esq`: signature
* `chsrny`: Bech32 checksum
* Signature breakdown:
  * `259f04511e7ef2aa77f6ff04d51b4ae9209504843e5ab9672ce32a153681f687515b73ce57ee309db588a10eb8e41b5a2d2bc17144ddf398033faa49ffe95ae6` hex of signature data (32-byte r, 32-byte s)
  * `0` (int) recovery flag contained in `signature`
  * `6c6e626332353030750b25fe64410d00004080c1014181c20240004080c1014181c20240004080c1014181c202404081a1071c1c571c1d9f1c15df1c1d9f1c15c9018f34ed798020f0` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `197a3061f4f333d86669b8054592222b488f3c657a9d3e74f34f586fb3e7931c` hex of SHA256 of the preimage

> ### Now send $24 for an entire list of things (hashed)
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqscc6gd6ql3jrc5yzme8v4ntcewwz5cnw92tz0pc8qcuufvq7khhr8wpald05e92xw006sq94mg8v2ndf4sefvf9sygkshp5zfem29trqq2yxxz7

Breakdown:

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `h`: tagged field: hash of description
  * `p5`: `data_length` (`p` = 1, `5` = 20; 1 * 32 + 20 == 52)
  * `8yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqs`: SHA256 of 'One piece of chocolate cake, one icecream cone, one pickle, one slice of swiss cheese, one slice of salami, one lollypop, one piece of cherry pie, one sausage, one cupcake, and one slice of watermelon'
* `cc6gd6ql3jrc5yzme8v4ntcewwz5cnw92tz0pc8qcuufvq7khhr8wpald05e92xw006sq94mg8v2ndf4sefvf9sygkshp5zfem29trqq`: signature
* `2yxxz7`: Bech32 checksum
* Signature breakdown:
  * `c63486e81f8c878a105bc9d959af1973854c4dc552c4f0e0e0c7389603d6bdc67707bf6be992a8ce7bf50016bb41d8a9b5358652c4960445a170d049ced4558c` hex of signature data (32-byte r, 32-byte s)
  * `0` (int) recovery flag contained in `signature`
  * `6c6e626332306d0b25fe64410d00004080c1014181c20240004080c1014181c20240004080c1014181c202404082e1a1c92db7b3f161a001b7689049eea2701b46f8db7513629edf2408fac7eaedc60800` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `b6025e8a10539dddbcbe6840a9650707ae3f147b8dcfda338561ada710508916` hex of SHA256 of the preimage

> ### The same, on testnet, with a fallback address mk2QpYatsKicvFVuTAQLBryyccRXMUaGHP
> lntb20m1pvjluezhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfpp3x9et2e20v6pu37c5d9vax37wxq72un98kmzzhznpurw9sgl2v0nklu2g4d0keph5t7tj9tcqd8rexnd07ux4uv2cjvcqwaxgj7v4uwn5wmypjd5n69z2xm3xgksg28nwht7f6zspwp3f9t

Breakdown:

* `lntb`: prefix, Lightning on Bitcoin testnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `h`: tagged field: hash of description...
* `p`: payment hash...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1; 1 * 32 + 1 == 33)
  * `3` = 17, so P2PKH address
  * `x9et2e20v6pu37c5d9vax37wxq72un98`: 160-bit P2PKH address
* `kmzzhznpurw9sgl2v0nklu2g4d0keph5t7tj9tcqd8rexnd07ux4uv2cjvcqwaxgj7v4uwn5wmypjd5n69z2xm3xgksg28nwht7f6zsp`: signature
* `wp3f9t`: Bech32 checksum
* Signature breakdown:
  * `b6c42b8a61e0dc5823ea63e76ff148ab5f6c86f45f9722af0069c7934daff70d5e315893300774c897995e3a7476c8193693d144a36e2645a0851e6ebafc9d0a` hex of signature data (32-byte r, 32-byte s)
  * `1` (int) recovery flag contained in `signature`
  * `6c6e746232306d0b25fe64570d0e496dbd9f8b0d000dbb44824f751380da37c6dba89b14f6f92047d63f576e304021a000081018202830384048000810182028303840480008101820283038404808102421898b95ab2a7b341e47d8a34ace9a3e7181e5726538` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `00c17b39642becc064615ef196a6cc0cce262f1d8dde7b3c23694aeeda473abe` hex of SHA256 of the preimage

> ### On mainnet, with fallback address 1RustyRX2oai4EYYDpQGWvEL62BBGqN9T with extra routing info to go via nodes 029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255 then 039e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqsfpp3qjmp7lwpagxun9pygexvgpjdc4jdj85fr9yq20q82gphp2nflc7jtzrcazrra7wwgzxqc8u7754cdlpfrmccae92qgzqvzq2ps8pqqqqqqpqqqqq9qqqvpeuqafqxu92d8lr6fvg0r5gv0heeeqgcrqlnm6jhphu9y00rrhy4grqszsvpcgpy9qqqqqqgqqqqq7qqzqj9n4evl6mr5aj9f58zp6fyjzup6ywn3x6sk8akg5v4tgn2q8g4fhx05wf6juaxu9760yp46454gpg5mtzgerlzezqcqvjnhjh8z3g2qqdhhwkj

Breakdown:

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `h`: tagged field: hash of description...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1; 1 * 32 + 1 == 33)
  * `3` = 17, so P2PKH address
  * `qjmp7lwpagxun9pygexvgpjdc4jdj85f`: 160-bit P2PKH address
* `r`: tagged field: route information
  * `9y`: `data_length` (`9` = 5, `y` = 4; 5 * 32 + 4 == 164)
    * `q20q82gphp2nflc7jtzrcazrra7wwgzxqc8u7754cdlpfrmccae92qgzqvzq2ps8pqqqqqqpqqqqq9qqqvpeuqafqxu92d8lr6fvg0r5gv0heeeqgcrqlnm6jhphu9y00rrhy4grqszsvpcgpy9qqqqqqgqqqqq7qqzq`:
      * pubkey: `029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255`
      * `short_channel_id`: 0102030405060708
      * `fee_base_msat`: 1 millisatoshi
      * `fee_proportional_millionths`: 20
      * `cltv_expiry_delta`: 3
      * pubkey: `039e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255`
      * `short_channel_id`: 030405060708090a
      * `fee_base_msat`: 2 millisatoshi
      * `fee_proportional_millionths`: 30
      * `cltv_expiry_delta`: 4
* `j9n4evl6mr5aj9f58zp6fyjzup6ywn3x6sk8akg5v4tgn2q8g4fhx05wf6juaxu9760yp46454gpg5mtzgerlzezqcqvjnhjh8z3g2qq`: signature
* `dhhwkj`: Bech32 checksum
* Signature breakdown:
  * `91675cb3fad8e9d915343883a49242e074474e26d42c7ed914655689a8074553733e8e4ea5ce9b85f69e40d755a55014536b12323f8b220600c94ef2b9c51428` hex of signature data (32-byte r, 32-byte s)
  * `0` (int) recovery flag contained in `signature`
  * `6c6e626332306d0b25fe64410d00004080c1014181c20240004080c1014181c20240004080c1014181c202404082e1a1c92db7b3f161a001b7689049eea2701b46f8db7513629edf2408fac7eaedc60824218825b0fbee0f506e4ca122326620326e2b26c8f448ca4029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255010203040506070800000001000000140003039e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255030405060708090a000000020000001e00040` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `ff68246c5ad4b48c90cf8ff3b33b5cea61e62f08d0e67910ffdce1edecade71b` hex of SHA256 of the preimage

> ### On mainnet, with fallback (P2SH) address 3EktnHQD7RiAE6uzMj2ZifT9YgRrkSgzQX
> lnbc20m1pvjluezhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfppj3a24vwu6r8ejrss3axul8rxldph2q7z9kmrgvr7xlaqm47apw3d48zm203kzcq357a4ls9al2ea73r8jcceyjtya6fu5wzzpe50zrge6ulk4nvjcpxlekvmxl6qcs9j3tz0469gq5g658y

Breakdown:

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `h`: tagged field: hash of description...
* `p`: payment hash...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1; 1 * 32 + 1 == 33)
  * `j` = 18, so P2SH address
  * `3a24vwu6r8ejrss3axul8rxldph2q7z9`:  160-bit P2SH address
* `kmrgvr7xlaqm47apw3d48zm203kzcq357a4ls9al2ea73r8jcceyjtya6fu5wzzpe50zrge6ulk4nvjcpxlekvmxl6qcs9j3tz0469gq`: signature
* `5g658y`: Bech32 checksum
* Signature breakdown:
  * `b6c6860fc6ff41bafba1745b538b6a7c6c2c0234f76bf817bf567be88cf2c632492c9dd279470841cd1e21a33ae7ed59b25809bf9b3366fe81881651589f5d15` hex of signature data (32-byte r, 32-byte s)
  * `0` (int) recovery flag contained in `signature`
  * `6c6e626332306d0b25fe64570d0e496dbd9f8b0d000dbb44824f751380da37c6dba89b14f6f92047d63f576e304021a000081018202830384048000810182028303840480008101820283038404808102421947aaab1dcd0cf990e108f4dcf9c66fb437503c228` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `64f1ff500bcc62a1b211cd6db84a1d93d1f77c6a132904465b6ff912420176be` hex of SHA256 of the preimage

> ### On mainnet, with fallback (P2WPKH) address bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4
> lnbc20m1pvjluezhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfppqw508d6qejxtdg4y5r3zarvary0c5xw7kepvrhrm9s57hejg0p662ur5j5cr03890fa7k2pypgttmh4897d3raaq85a293e9jpuqwl0rnfuwzam7yr8e690nd2ypcq9hlkdwdvycqa0qza8

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `h`: tagged field: hash of description...
* `p`: payment hash...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1; 1 * 32 + 1 == 33)
  * `q`: 0, so witness version 0
  * `w508d6qejxtdg4y5r3zarvary0c5xw7k`: 160 bits = P2WPKH.
* `epvrhrm9s57hejg0p662ur5j5cr03890fa7k2pypgttmh4897d3raaq85a293e9jpuqwl0rnfuwzam7yr8e690nd2ypcq9hlkdwdvycq`: signature
* `a0qza8`: Bech32 checksum
* Signature breakdown:
  * `c8583b8f65853d7cc90f0eb4ae0e92a606f89caf4f7d65048142d7bbd4e5f3623ef407a75458e4b20f00efbc734f1c2eefc419f3a2be6d51038016ffb35cd613` hex of signature data (32-byte r, 32-byte s)
  * `0` (int) recovery flag contained in `signature`
  * `6c6e626332306d0b25fe64570d0e496dbd9f8b0d000dbb44824f751380da37c6dba89b14f6f92047d63f576e304021a00008101820283038404800081018202830384048000810182028303840480810242103a8f3b740cc8cb6a2a4a0e22e8d9d191f8a19deb0` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `b3df27aaa01d891cc9de272e7609557bdf4bd6fd836775e4470502f71307b627` hex of SHA256 of the preimage

> ### On mainnet, with fallback (P2WSH) address bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3
> lnbc20m1pvjluezhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfp4qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q28j0v3rwgy9pvjnd48ee2pl8xrpxysd5g44td63g6xcjcu003j3qe8878hluqlvl3km8rm92f5stamd3jw763n3hck0ct7p8wwj463cql26ava

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `h`: tagged field: hash of description...
* `p`: payment hash...
* `f`: tagged field: fallback address
  * `p4`: `data_length` (`p` = 1, `4` = 21; 1 * 32 + 21 == 53)
  * `q`: 0, so witness version 0
  * `rp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q`: 260 bits = P2WSH.
* `28j0v3rwgy9pvjnd48ee2pl8xrpxysd5g44td63g6xcjcu003j3qe8878hluqlvl3km8rm92f5stamd3jw763n3hck0ct7p8wwj463cq`: signature
* `l26ava`: Bech32 checksum
* Signature breakdown:
  * `51e4f6446e410a164a6da9f39507e730c26241b4456ab6ea28d1b12c71ef8ca20c9cfe3dffc07d9f8db671ecaa4d20beedb193bda8ce37c59f85f82773a55d47` hex of signature data (32-byte r, 32-byte s)
  * `0` (int) recovery flag contained in `signature`
  * `6c6e626332306d0b25fe64570d0e496dbd9f8b0d000dbb44824f751380da37c6dba89b14f6f92047d63f576e304021a00008101820283038404800081018202830384048000810182028303840480810243500c318a1e0a628b34025e8c9019ab6d09b64c2b3c66a693d0dc63194b02481931000` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `399a8b167029fda8564fd2e99912236b0b8017e7d17e416ae17307812c92cf42` hex of SHA256 of the preimage

> ### Please send 0.00967878534 BTC for a list of items within one week, amount in pico-BTC
> lnbc9678785340p1pwmna7lpp5gc3xfm08u9qy06djf8dfflhugl6p7lgza6dsjxq454gxhj9t7a0sd8dgfkx7cmtwd68yetpd5s9xar0wfjn5gpc8qhrsdfq24f5ggrxdaezqsnvda3kkum5wfjkzmfqf3jkgem9wgsyuctwdus9xgrcyqcjcgpzgfskx6eqf9hzqnteypzxz7fzypfhg6trddjhygrcyqezcgpzfysywmm5ypxxjemgw3hxjmn8yptk7untd9hxwg3q2d6xjcmtv4ezq7pqxgsxzmnyyqcjqmt0wfjjq6t5v4khxxqyjw5qcqp2rzjq0gxwkzc8w6323m55m4jyxcjwmy7stt9hwkwe2qxmy8zpsgg7jcuwz87fcqqeuqqqyqqqqlgqqqqn3qq9qn07ytgrxxzad9hc4xt3mawjjt8znfv8xzscs7007v9gh9j569lencxa8xeujzkxs0uamak9aln6ez02uunw6rd2ht2sqe4hz8thcdagpleym0j

Breakdown:

* `lnbc`: prefix, Lightning on bitcoin mainnet
* `9678785340p`: amount (9678785340 pico-bitcoin = 967878534 milli satoshi)
* `1`: Bech32 separator
* `pwmna7l`: timestamp (1572468703)
* `p`: payment hash.
  * `p5`: `data_length` (`p` = 1, `5` = 20; 1 * 32 + 20 == 52)
  * `gc3xfm08u9qy06djf8dfflhugl6p7lgza6dsjxq454gxhj9t7a0s`: payment hash 462264ede7e14047e9b249da94fefc47f41f7d02ee9b091815a5506bc8abf75f
* `d`: short description
  * `8d`: `data_length` (`8` = 7, `d` = 13; 7 * 32 + 13 == 237)
  * `gfkx7cmtwd68yetpd5s9xar0wfjn5gpc8qhrsdfq24f5ggrxdaezqsnvda3kkum5wfjkzmfqf3jkgem9wgsyuctwdus9xgrcyqcjcgpzgfskx6eqf9hzqnteypzxz7fzypfhg6trddjhygrcyqezcgpzfysywmm5ypxxjemgw3hxjmn8yptk7untd9hxwg3q2d6xjcmtv4ezq7pqxgsxzmnyyqcjqmt0wfjjq6t5v4khx`: 'Blockstream Store: 88.85 USD for Blockstream Ledger Nano S x 1, \"Back In My Day\" Sticker x 2, \"I Got Lightning Working\" Sticker x 2 and 1 more items'
* `x`: expiry time
  * `qy`: `data_length` (`q` = 0, `y` = 2; 0 * 32 + 4 == 4)
  * `jw5q`: 604800 seconds (`j` = 18, `w` = 14, `5` = 20, `q` = 0; 18 * 32^3 + 14 * 32^2 + 20 * 32 + 0 == 604800)
* `c`: `min_final_cltv_expiry`
  * `qp`: `data_length` (`q` = 0, `p` = 1; 0 * 32 + 1 == 1)
  * `2`: min_final_cltv_expiry = 10
* `r`: tagged field: route information
  * `zj`: `data_length` (`z` = 2, `j` = 18; 2 * 32 + 18 == 82)
  * `q0gxwkzc8w6323m55m4jyxcjwmy7stt9hwkwe2qxmy8zpsgg7jcuwz87fcqqeuqqqyqqqqlgqqqqn3qq9q`:
    * pubkey: 03d06758583bb5154774a6eb221b1276c9e82d65bbaceca806d90e20c108f4b1c7
    * short_channel_id: 589390x3312x1
    * fee_base_msat = 1000
    * fee_proportional_millionths = 2500
    * cltv_expiry_delta = 40
* `n07ytgrxxzad9hc4xt3mawjjt8znfv8xzscs7007v9gh9j569lencxa8xeujzkxs0uamak9aln6ez02uunw6rd2ht2sqe4hz8thcdagp`: signature
* `leym0j`: Bech32 checksum

> ### Please send $30 for coffee beans to the same peer, which supports features 9, 15 and 99, using secret 0x1111111111111111111111111111111111111111111111111111111111111111
> lnbc25m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5vdhkven9v5sxyetpdeessp5zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygs9q5sqqqqqqqqqqqqqqqpqsq67gye39hfg3zd8rgc80k32tvy9xk2xunwm5lzexnvpx6fd77en8qaq424dxgt56cag2dpt359k3ssyhetktkpqh24jqnjyw6uqd08sgptq44qu

Breakdown:

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `25m`: amount (25 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `d`: short description
  * `q5`: `data_length` (`q` = 0, `5` = 20; 0 * 32 + 20 == 20)
  * `vdhkven9v5sxyetpdees`: 'coffee beans'
* `s`: payment secret
  * `p5`: `data_length` (`p` = 1, `5` = 20; 1 * 32 + 20 == 52)
  * `zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygs`: 0x1111111111111111111111111111111111111111111111111111111111111111
* `9`: features
  * `q5`: `data_length` (`q` = 0, `5` = 20; 0 * 32 + 20 == 20)
  * `sqqqqqqqqqqqqqqqpqsq`: b1000....00001000001000000000
* `67gye39hfg3zd8rgc8032tvy9xk2xunwm5lzexnvpx6fd77en8qaq424dxgt56cag2dpt359k3ssyhetktkpqh24jqnjyw6uqd08sgp`: signature
* `tq44qu`: Bech32 checksum

> ### Same, but all upper case.
> LNBC25M1PVJLUEZPP5QQQSYQCYQ5RQWZQFQQQSYQCYQ5RQWZQFQQQSYQCYQ5RQWZQFQYPQDQ5VDHKVEN9V5SXYETPDEESSP5ZYG3ZYG3ZYG3ZYG3ZYG3ZYG3ZYG3ZYG3ZYG3ZYG3ZYG3ZYG3ZYGS9Q5SQQQQQQQQQQQQQQQPQSQ67GYE39HFG3ZD8RGC80K32TVY9XK2XUNWM5LZEXNVPX6FD77EN8QAQ424DXGT56CAG2DPT359K3SSYHETKTKPQH24JQNJYW6UQD08SGPTQ44QU

> ### Same, but including fields which must be ignored.
> lnbc25m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5vdhkven9v5sxyetpdeessp5zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygs9q5sqqqqqqqqqqqqqqqpqsq2qrqqqfppnqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqppnqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpp4qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqhpnqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqhp4qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqspnqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqsp4qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqnp5qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqnpkqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq2jxxfsnucm4jf4zwtznpaxphce606fvhvje5x7d4gw7n73994hgs7nteqvenq8a4ml8aqtchv5d9pf7l558889hp4yyrqv6a7zpq9fgpskqhza

Breakdown:

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `25m`: amount (25 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `d`: short description
  * `q5`: `data_length` (`q` = 0, `5` = 20; 0 * 32 + 20 == 20)
  * `vdhkven9v5sxyetpdees`: 'coffee beans'
* `s`: payment secret
  * `p5`: `data_length` (`p` = 1, `5` = 20; 1 * 32 + 20 == 52)
  * `zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygs`: 0x1111111111111111111111111111111111111111111111111111111111111111
* `9`: features
  * `q5`: `data_length` (`q` = 0, `5` = 20; 0 * 32 + 20 == 20)
  * `sqqqqqqqqqqqqqqqpqsq`: b1000....00001000001000000000
* `2`: unknown field
  * `qr`: `data_length` (`q` = 0, `r` = 3; 0 * 32 + 3 == 3)
  * `qqq`: zeroes
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1, `p` = 1; 1 * 32 + 1 == 33)
  * `nqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq`: fallback address type 19 (ignored)
* `p`: payment hash
  * `pn`: `data_length` (`p` = 1, `n` = 19; 1 * 32 + 19 == 51) (ignored)
  * `qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq`
* `p`: payment hash
  * `p4`: `data_length` (`p` = 1, `4` = 21; 1 * 32 + 21 == 53) (ignored)
  * `qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq`
* `h`: hash of description
  * `pn`: `data_length` (`p` = 1, `n` = 19; 1 * 32 + 19 == 51) (ignored)
  * `qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq`
* `h`: hash of description
  * `p4`: `data_length` (`p` = 1, `4` = 21; 1 * 32 + 21 == 53) (ignored)
  * `qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq`
* `s`: payment secret
  * `pn`: `data_length` (`p` = 1, `n` = 19; 1 * 32 + 19 == 51) (ignored)
  * `qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq`
* `s`: payment secret
  * `p4`: `data_length` (`p` = 1, `4` = 21; 1 * 32 + 21 == 53) (ignored)
  * `qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq`
* `n`: node id
  * `p5`: `data_length` (`p` = 1, `5` = 20; 1 * 32 + 20 == 52) (ignored)
  * `qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq`
* `n`: node id
  * `pk`: `data_length` (`p` = 1, `k` = 22; 1 * 32 + 22 == 54) (ignored)
  * `qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq`
* `2jxxfsnucm4jf4zwtznpaxphce606fvhvje5x7d4gw7n73994hgs7nteqvenq8a4ml8aqtchv5d9pf7l558889hp4yyrqv6a7zpq9fgp`: signature
* `skqhza`: Bech32 checksum

# Examples of Invalid Invoices

> # Same, but adding invalid unknown feature 100
> lnbc25m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5vdhkven9v5sxyetpdeessp5zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygs9q4psqqqqqqqqqqqqqqqpqsqq40wa3khl49yue3zsgm26jrepqr2eghqlx86rttutve3ugd05em86nsefzh4pfurpd9ek9w2vp95zxqnfe2u7ckudyahsa52q66tgzcp6t2dyk

Breakdown:

* `lnbc`: prefix, Lightning on Bitcoin mainnet
* `25m`: amount (25 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `d`: short description
  * `q5`: `data_length` (`q` = 0, `5` = 20; 0 * 32 + 20 == 20)
  * `vdhkven9v5sxyetpdees`: 'coffee beans'
* `s`: payment secret
  * `p5`: `data_length` (`p` = 1, `5` = 20; 1 * 32 + 20 == 52)
  * `zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygs`: 0x1111111111111111111111111111111111111111111111111111111111111111
* `9`: features
  * `q4`: `data_length` (`q` = 0, `4` = 21; 0 * 32 + 21 == 21)
  * `psqqqqqqqqqqqqqqqpqsqq`: b000011000....00001000001000000000
* `40wa3khl49yue3zsgm26jrepqr2eghqlx86rttutve3ugd05em86nsefzh4pfurpd9ek9w2vp95zxqnfe2u7ckudyahsa52q66tgzcp`: signature
* `6t2dyk`: Bech32 checksum

> ### Bech32 checksum is invalid.
> lnbc2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdpquwpc4curk03c9wlrswe78q4eyqc7d8d0xqzpuyk0sg5g70me25alkluzd2x62aysf2pyy8edtjeevuv4p2d5p76r4zkmneet7uvyakky2zr4cusd45tftc9c5fh0nnqpnl2jfll544esqchsrnt

> ### Malformed bech32 string (no 1)
> pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdpquwpc4curk03c9wlrswe78q4eyqc7d8d0xqzpuyk0sg5g70me25alkluzd2x62aysf2pyy8edtjeevuv4p2d5p76r4zkmneet7uvyakky2zr4cusd45tftc9c5fh0nnqpnl2jfll544esqchsrny

> ### Malformed bech32 string (mixed case)
> LNBC2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdpquwpc4curk03c9wlrswe78q4eyqc7d8d0xqzpuyk0sg5g70me25alkluzd2x62aysf2pyy8edtjeevuv4p2d5p76r4zkmneet7uvyakky2zr4cusd45tftc9c5fh0nnqpnl2jfll544esqchsrny

> ### Signature is not recoverable.
> lnbc2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpuaxtrnwngzn3kdzw5hydlzf03qdgm2hdq27cqv3agm2awhz5se903vruatfhq77w3ls4evs3ch9zw97j25emudupq63nyw24cg27h2rspk28uwq

> ### String is too short.
> lnbc1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdpl2pkx2ctnv5sxxmmwwd5kgetjypeh2ursdae8g6na6hlh

> ### Invalid multiplier
> lnbc2500x1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpujr6jxr9gq9pv6g46y7d20jfkegkg4gljz2ea2a3m9lmvvr95tq2s0kvu70u3axgelz3kyvtp2ywwt0y8hkx2869zq5dll9nelr83zzqqpgl2zg

> ### Invalid sub-millisatoshi precision.
> lnbc2500000001p1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpu7hqtk93pkf7sw55rdv4k9z2vj050rxdr6za9ekfs3nlt5lr89jqpdmxsmlj9urqumg0h9wzpqecw7th56tdms40p2ny9q4ddvjsedzcplva53s

# Authors

[ FIXME: ]

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
