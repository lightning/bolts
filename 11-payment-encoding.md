# BOLT #11: Invoice Protocol for Lightning Payments

A simple, extensible QR-code-ready protocol for requesting payments
over Lightning.

# Table of Contents

  * [Encoding Overview](#encoding-overview)
  * [Human-Readable Part](#human-readable-part)
  * [Data Part](#data-part)
    * [Tagged Fields](#tagged-fields)
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
'lightning://'), or for fallback to bitcoin payments to use 'bitcoin:',
as per BIP-21, with the key 'lightning' and the value equal to the BOLT-11
encoding.

## Requirements

A writer MUST encode the payment request in Bech32 as specified in
BIP-0173, with the exception that the Bech32 string MAY be longer than
the 90 characters specified there. A reader MUST parse the address as
Bech32 as specified in BIP-0173 (also without the character limit),
and MUST fail if the checksum is incorrect.

# Human-Readable Part

The human-readable part of a Lightning invoice consists of two sections:
1. `prefix`: `ln` + BIP-0173 currency prefix (e.g. `lnbc` for bitcoins or `lntb` for testnet bitcoins)
1. `amount`: optional number in that currency, followed by an optional
   `multiplier` letter

The following `multiplier` letters are defined:

* `m` (milli): multiply by 0.001
* `u` (micro): multiply by 0.000001
* `n` (nano): multiply by 0.000000001
* `p` (pico): multiply by 0.000000000001

## Requirements

A writer MUST include `amount` if payments will be refused if less
than that. A writer MUST encode `amount` as a positive decimal
integer with no leading zeroes and SHOULD use the shortest representation
possible.

A reader MUST fail if it does not understand the `prefix`. A reader
SHOULD fail if `amount` contains a non-digit or is followed by
anything except a `multiplier` in the table above.

A reader SHOULD indicate if amount is unspecified, otherwise it MUST
multiply `amount` by the `multiplier` value (if any) to derive the
amount required for payment.

## Rationale

The `amount` is encoded into the human readable part, as it's fairly
readable and a useful indicator of how much is being requested.

Donation addresses often don't have an associated amount, so `amount`
is optional in that case. Usually a minimum payment is required for
whatever is being offered in return.

# Data Part

The data part of a Lightning invoice consists of multiple sections:

1. `timestamp`: seconds-since-1970 (35 bits, big-endian)
1. zero or more tagged parts
1. `signature`: bitcoin-style signature of above (520 bits)

## Requirements

A writer MUST set `timestamp` to
the number of seconds since Midnight 1 January 1970, UTC in
big-endian. A writer MUST set `signature` to a valid
512-bit secp256k1 signature of the SHA2 256-bit hash of the
human-readable part, represented as UTF-8 bytes, concatenated with the
data part (excluding the signature) with zero bits appended to pad the
data to the next byte boundary, with a trailing byte containing
the recovery ID (0, 1, 2 or 3).

A reader MUST check that the `signature` is valid (see the `n` tagged
field specified below).

## Rationale

`signature` covers an exact number of bytes even though the SHA-2
standard actually supports hashing in bit boundaries, because it's not widely
implemented. The recovery ID allows public-key recovery, so the
identity of the payee node can be implied.

## Tagged Fields

Each Tagged Field is of the form:

1. `type` (5 bits)
1. `data_length` (10 bits, big-endian)
1. `data` (`data_length` x 5 bits)

Currently defined tagged fields are:

* `p` (1): `data_length` 52. 256-bit SHA256 payment_hash. Preimage of this provides proof of payment
* `d` (13): `data_length` variable. Short description of purpose of payment (ASCII),  e.g. '1 cup of coffee'
* `n` (19): `data_length` 53. 33-byte public key of the payee node
* `h` (23): `data_length` 52. 256-bit description of purpose of payment (SHA256). This is used to commit to an associated description that is too long to fit, such as on a web page.
* `x` (6): `data_length` variable. `expiry` time in seconds (big-endian). Default is 3600 (1 hour) if not specified.
* `c` (24): `data_length` variable. `min_final_cltv_expiry` to use for the last HTLC in the route. Default is 9 if not specified.
* `f` (9): `data_length` variable, depending on version. Fallback on-chain address: for bitcoin, this starts with a 5-bit `version` and contains a witness program or P2PKH or P2SH address.
* `r` (3): `data_length` variable. One or more entries containing extra routing information for a private route; there may be more than one `r` field
   * `pubkey` (264 bits)
   * `short_channel_id` (64 bits)
   * `fee_base_msat` (32 bits, big-endian) 
   * `fee_proportional_millionths` (32 bits, big-endian)
   * `cltv_expiry_delta` (16 bits, big-endian)

### Requirements

A writer MUST include exactly one `p` field, and set `payment_hash` to
the SHA-2 256-bit hash of the `payment_preimage` that will be given
in return for payment.

A writer MUST include either exactly one `d` or exactly one `h` field. If included, a 
writer SHOULD make `d` a complete description of
the purpose of the payment. If included, a writer MUST make the preimage
of the hashed description in `h` available through some unspecified means,
which SHOULD be a complete description of the purpose of the payment.

A writer MAY include one `x` field.

A writer MAY include one `c` field, which MUST be set to the minimum `cltv_expiry` it
will accept for the last HTLC in the route.

A writer SHOULD use the minimum `data_length` possible for `x` and `c` fields.

A writer MAY include one `n` field, which MUST be set to the public key
used to create the `signature`.

A writer MAY include one or more `f` fields. For bitcoin payments, a writer MUST set an
`f` field to a valid witness version and program, or `17` followed by
a public key hash, or `18` followed by a script hash.

A writer MUST include at least one `r` field if there is not a
public channel associated with its public key. The `r` field MUST contain
one or more ordered entries, indicating the forward route from a
public node to the final destination. For each entry, the `pubkey` is the
node ID of the start of the channel; `short_channel_id` is the short channel ID
field to identify the channel; and `fee_base_msat`, `fee_proportional_millionths`, and `cltv_expiry_delta` are as specified in [BOLT #7](07-routing-gossip.md#the-channel_update-message). A writer MAY include more than one `r` field to
provide multiple routing options.

A writer MUST pad field data to a multiple of 5 bits, using zeroes.

If a writer offers more than one of any field type, it MUST specify
the most-preferred field first, followed by less-preferred fields in
order.

A reader MUST skip over unknown fields, an `f` field with unknown
`version`, or a `p`, `h`, or `n` field that does not have `data_length` 52,
52, or 53 respectively.

A reader MUST check that the SHA-2 256 in the `h` field exactly
matches the hashed description.

A reader MUST use the `n` field to validate the signature instead of
performing signature recovery if a valid `n` field is provided.

### Rationale

The type-and-length format allows future extensions to be backward
compatible. `data_length` is always a multiple of 5 bits, for easy
encoding and decoding. For fields that we expect may change, readers
also ignore ones of different length.

The `p` field supports the current 256-bit payment hash, but future
specs could add a new variant of different length, in which case
writers could support both old and new, and old readers would ignore
the one not the correct length.

The `d` field allows inline descriptions, but may be insufficient for
complex orders; thus the `h` field allows a summary, though the method
by which the description is served is as-yet unspecified and will
probably be transport dependent. The `h` format could change in future
by changing the length, so readers ignore it if it's not 256 bits.

The `n` field can be used to explicitly specify the destination node ID,
instead of requiring signature recovery.

The `x` field gives advance warning as to when a payment will be
refused; this is mainly to avoid confusion. The default was chosen
to be reasonable for most payments and to allow sufficient time for
on-chain payment if necessary.

The `c` field gives a way for the destination node to require a specific
minimum CLTV expiry for its incoming HTLC. Destination nodes may use this 
to require a higher, more conservative value than the default one, depending
on their fee estimation policy and their sensitivity to time locks. Note 
that remote nodes in the route specify their required `cltv_expiry_delta` 
in the `channel_update` message, which they can update at all times.

The `f` field allows on-chain fallback. This may not make sense for
tiny or very time-sensitive payments, however. It's possible that new
address forms will appear, and so multiple `f` fields in an implied
preferred order help with transition, and `f` fields with versions 19-31
will be ignored by readers.

The `r` field allows limited routing assistance: as specified it only
allows minimum information to use private channels, but it could also
assist in future partial-knowledge routing.

# Payer / Payee Interactions

These are generally defined by the rest of the Lightning BOLT series,
but it's worth noting that [BOLT #5](05-onchain.md) specifies that the payee SHOULD
accept up to twice the expected `amount`, so the payer can make
payments harder to track by adding small variations.

The intent is that the payer recover the payee's node ID from the
signature, and after checking that conditions such as fees,
expiry, and block timeout are acceptable, attempt a payment. It can use `r` fields to
augment its routing information if necessary to reach the final node.

If the payment succeeds but there is a later dispute, the payer can
prove both the signed offer from the payee and the successful
payment.

## Payer / Payee Requirements

A payer SHOULD NOT attempt a payment after the `timestamp` plus
`expiry` has passed. Otherwise, if a Lightning payment fails, a payer
MAY attempt to use the address given in the first `f` field that it
understands for payment. A payer MAY use the sequence of channels
specified by the `r` field to route to the payee. A payer SHOULD consider the
fee amount and payment timeout before initiating payment. A payer
SHOULD use the first `p` field that it did not skip as the payment hash.

A payee SHOULD NOT accept a payment after `timestamp` plus `expiry`.

# Implementation

https://github.com/rustyrussell/lightning-payencode

# Examples

NB: all the following examples are signed with `priv_key`=`e126f68f7eafcc8b74f54d269fe206be715000f94dac067d1c04a8ca3b2db734`.

> ### Please make a donation of any amount using payment_hash 0001020304050607080900010203040506070809000102030405060708090102 to me @03e7156ae33b0a208d0744199163177e909e80176e55d97a2f221ede0f934dd9ad
> lnbc1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdpl2pkx2ctnv5sxxmmwwd5kgetjypeh2ursdae8g6twvus8g6rfwvs8qun0dfjkxaq8rkx3yf5tcsyz3d73gafnh3cax9rn449d9p5uxz9ezhhypd0elx87sjle52x86fux2ypatgddc6k63n7erqz25le42c4u4ecky03ylcqca784w

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
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

> ### Please send $3 for a cup of coffee to the same peer, within 1 minute
> lnbc2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpuaztrnwngzn3kdzw5hydlzf03qdgm2hdq27cqv3agm2awhz5se903vruatfhq77w3ls4evs3ch9zw97j25emudupq63nyw24cg27h2rspfj9srp

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
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

> ### Now send $24 for an entire list of things (hashed)
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqscc6gd6ql3jrc5yzme8v4ntcewwz5cnw92tz0pc8qcuufvq7khhr8wpald05e92xw006sq94mg8v2ndf4sefvf9sygkshp5zfem29trqq2yxxz7

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
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

* `lntb`: prefix, lightning on bitcoin testnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `h`: tagged field: hash of description...
* `p`: payment hash...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1; 1 * 32 + 1 == 33)
  * `3` = 17, so P2PKH address
  * `x9et2e20v6pu37c5d9vax37wxq72un98`: 160 bit P2PKH address
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

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `h`: tagged field: hash of description...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1; 1 * 32 + 1 == 33)
  * `3` = 17, so P2PKH address
  * `qjmp7lwpagxun9pygexvgpjdc4jdj85f`: 160 bit P2PKH address
* `r`: tagged field: route information
  * `9y`: `data_length` (`9` = 5, `y` = 4; 5 * 32 + 4 = 164)
    `q20q82gphp2nflc7jtzrcazrra7wwgzxqc8u7754cdlpfrmccae92qgzqvzq2ps8pqqqqqqqqqqqq9qqqvpeuqafqxu92d8lr6fvg0r5gv0heeeqgcrqlnm6jhphu9y00rrhy4grqszsvpcgpy9qqqqqqqqqqqq7qqzq`: pubkey `029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255`, `short_channel_id` 0102030405060708, `fee_base_msat` 1 millisatoshi, `fee_proportional_millionths` 20, `cltv_expiry_delta` 3. pubkey `039e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255`, `short_channel_id` 030405060708090a, `fee_base_msat` 2 millisatoshi, `fee_proportional_millionths` 30, `cltv_expiry_delta` 4.
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

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `h`: tagged field: hash of description...
* `p`: payment hash...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1; 1 * 32 + 1 == 33)
  * `j` = 18, so P2SH address
  * `3a24vwu6r8ejrss3axul8rxldph2q7z9`:  160 bit P2SH address
* `kmrgvr7xlaqm47apw3d48zm203kzcq357a4ls9al2ea73r8jcceyjtya6fu5wzzpe50zrge6ulk4nvjcpxlekvmxl6qcs9j3tz0469gq`: signature
* `5g658y`: Bech32 checksum
* Signature breakdown:
  * `b6c6860fc6ff41bafba1745b538b6a7c6c2c0234f76bf817bf567be88cf2c632492c9dd279470841cd1e21a33ae7ed59b25809bf9b3366fe81881651589f5d15` hex of signature data (32-byte r, 32-byte s)
  * `0` (int) recovery flag contained in `signature`
  * `6c6e626332306d0b25fe64570d0e496dbd9f8b0d000dbb44824f751380da37c6dba89b14f6f92047d63f576e304021a000081018202830384048000810182028303840480008101820283038404808102421947aaab1dcd0cf990e108f4dcf9c66fb437503c228` hex of data for signing (prefix + data after separator up to the start of the signature)
  * `64f1ff500bcc62a1b211cd6db84a1d93d1f77c6a132904465b6ff912420176be` hex of SHA256 of the preimage

> ### On mainnet, with fallback (P2WPKH) address bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4
> lnbc20m1pvjluezhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfppqw508d6qejxtdg4y5r3zarvary0c5xw7kepvrhrm9s57hejg0p662ur5j5cr03890fa7k2pypgttmh4897d3raaq85a293e9jpuqwl0rnfuwzam7yr8e690nd2ypcq9hlkdwdvycqa0qza8

* `lnbc`: prefix, lightning on bitcoin mainnet
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

* `lnbc`: prefix, lightning on bitcoin mainnet
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

# Authors

[ FIXME: ]

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
