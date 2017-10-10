# BOLT #11: Invoice Protocol for Lightning Payments

A simple, extensible QR-code-ready protocol for requesting payments
over Lightning.

# Table of Contents
  
# Encoding Overview

The format for a lightning invoice uses
[bech32 encoding](https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki),
which is already proposed for bitcoin Segregated Witness, and can be
simply reused here even though its 6-character checksum is optimized
for manual entry, which is unlikely to happen often given the length
of lightning invoices.

If a URI scheme is desired, the current recommendation is to either
use 'lightning:' as a prefix before the BOLT-11 encoding (note: not
'lightning://'), or for fallback for bitcoin payments, use 'bitcoin:'
as per BIP-21, with key 'lightning' and value equal to the BOLT-11
encoding.

## Requirements

A writer MUST encode the the payment request in Bech32 as specified in
BIP-0173, with the exception that the Bech32 string MAY be longer than
the 90 characters specified there. A reader MUST parse the address as
Bech32 as specified in BIP-0173 (also without the character limit),
and MUST fail if the checksum is incorrect.

# Human Readable Part

The human readable part consists of two sections:
1. `prefix`: `ln` + BIP-0173 currency prefix (e.g. `lnbc`, `lntb`)
1. `amount`: optional number in that currency, followed by optional
   `multiplier`.

The following `multiplier` letters are defined:

* `m` (milli): multiply by 0.001
* `u` (micro): multiply by 0.000001
* `n` (nano): multiply by 0.000000001
* `p` (pico): multiply by 0.000000000001

## Requirements

A writer MUST include `amount` if payments will be refused if less
than that.  A writer MUST encode `amount` as a positive decimal
integer with no leading zeroes, SHOULD use the shortest representation
possible.

A reader MUST fail if it does not understand the `prefix`.  A reader
SHOULD fail if `amount` contains a non-digit, or is followed by
anything except a `multiplier` in the table above.

A reader SHOULD indicate if amount is unspecified, otherwise it MUST
multiply `amount` by the `multiplier` value (if any) to derive the
amount required for payment.

## Rationale

The `amount` is encoded into the human readable part, as it's fairly
readable and a useful indicator of how much is being requested.

Donation addresses often don't have an associated amount, so `amount`
is optional in that case: usually a minimum payment is required for
whatever is being offered in return.

# Data Part

The data part consists of multiple sections:

1. `timestamp`: seconds-since-1970 (35 bits, big-endian)
1. Zero or more tagged parts.
1. `signature`: bitcoin-style signature of above. (520 bits)

## Requirements

A writer MUST set `timestamp` to the time to
the number of seconds since Midnight 1 January 1970, UTC in
big-endian.  A writer MUST set `signature` to a valid
512-bit secp256k1 signature of the SHA2 256-bit hash of the
Human Readable Part concatenated with the Data Part and zero bits
appended to the next byte boundary, with a trailing byte containing
the recovery ID (0, 1, 2 or 3).

A reader MUST check that the `signature` is valid (see the `n` tagged
field specified below).

## Rationale

`signature` covers an exact number of bytes because although the SHA-2
standard actually supports hashing in bit boundaries, it's not widely
implemented.  The recovery ID allows public key recovery, so the
identity of the payee node can be implied.

## Tagged Fields

Each Tagged Field is of format:

1. `type` (5 bits)
1. `data_length` (10 bits, big-endian)
1. `data` (`data_length` x 5 bits)

Currently defined Tagged Fields are:

* `p` (1): `data_length` 52.  256-bit SHA256 payment_hash: preimage of this provides proof of payment.
* `d` (13): `data_length` variable.  short description of purpose of payment (ASCII),  e.g. '1 cup of coffee'
* `n` (19): `data_length` 53.  The 33-byte public key of the payee node.
* `h` (23): `data_length` 52.  256-bit description of purpose of payment (SHA256).  This is used to commit to an associated description which is too long to fit, such as may be contained in a web page.
* `x` (6): `data_length` variable.  `expiry` time in seconds (big-endian). Default is 3600 (1 hour) if not specified.
* `c` (24): `data_length` (16 bits, big-endian). Minimum `cltv_expiry` to use for the last htlc. Default is 9 if not specified.
* `f` (9): `data_length` variable, depending on version. Fallback on-chain address: for bitcoin, this starts with a 5 bit `version`; a witness program or P2PKH or P2SH address.
* `r` (3): `data_length` variable.  One or more entries containing extra routing information for a private route; there may be more than one `r` field, too.
   * `pubkey` (264 bits)
   * `short_channel_id` (64 bits)
   * `fee` (64 bits, big-endian)
   * `cltv_expiry_delta` (16 bits, big-endian)

### Requirements

A writer MUST include exactly one `p` field, and set `payment_hash` to
the SHA-2 256-bit hash of the `payment_preimage` which will be given
in return for payment.

A writer MUST include either exactly one `d` or exactly one `h` field.  If included, a 
writer SHOULD make `d` a complete description of
the purpose of the payment.  If included, a writer MUST make the preimage
of the hashed description in `h` available through some unspecified means,
which SHOULD be a complete description of the purpose of the payment.

A writer MAY include one `x` field, which SHOULD use the minimum `data_length` 
possible.

A writer MAY include one `c` field, which MUST be set to the minimum `cltv_expiry` it
will accept for the last htlc.

A writer MAY include one `n` field, which MUST be set to the public key
used to create the `signature`.

A writer MAY include one or more `f` fields. For bitcoin payments, a writer MUST set an
`f` field to a valid witness version and program, or `17` followed by
a public key hash, or `18` followed by a script hash.

A writer MUST include at least one `r` field if it does not have a
public channel associated with its public key.  The `r` field MUST contain
one or more ordered entries, indicating the forward route from a
public node to the final destination.  For each entry, the `pubkey` is the
node ID of the start of the channel, `short_channel_id` is the short channel ID
field to identify the channel, `fee` is the total fee required to use
that channel to send `amount` to the final node, specified in 10^-11
currency units, and `cltv_expiry_delta` is the block delta required
by the channel.  A writer MAY include more than one `r` field to
provide multiple routing options.

A writer MUST pad field data to a multiple of 5 bits, using zeroes.

If a writer offers more than one of any field type, it MUST specify
the most-preferred field first, followed by less-preferred fields in
order.

A reader MUST skip over unknown fields, an `f` field with unknown
`version`, or a `p`, `h`, or `n` field which does not have `data_length` 52,
52, or 53 respectively.

A reader MUST check that the SHA-2 256 in the `h` field exactly
matches the hashed description.

A reader MUST use a greater value for the last htlc's `cltv_expiry` than the one
 in the `c` field if provided, and SHOULD follow the [shadow route recommendation](https://github.com/lightningnetwork/lightning-rfc/blob/master/07-routing-gossip.md#recommendations-for-routing)
 on top of that.

A reader MUST use the `n` field to validate the signature instead of
performing signature recovery if a valid `n` field is provided.

### Rationale

The type-and-length format allows future extensions to be backward
compatible.  `data_length` is always a multiple of 5 bits, for easy
encoding and decoding.  For fields we expect may change, readers
also ignore ones of different length.

The `p` field supports the current 256-bit payment hash, but future
specs could add a new variant of different length, in which case
writers could support both old and new, and old readers would ignore
the one not the correct length.

The `d` field allows inline descriptions, but may be insufficient for
complex orders; thus the `h` field allows a summary, though the method
by which the description is served is as-yet unspecified, and will
probably be transport-dependent.  The `h` format could change in future
by changing the length, so readers ignore it if not 256 bits.

The `n` field can be used to explicitly specify the destination node ID,
instead of requiring signature recovery.

The `x` field gives advance warning as to when a payment will be
refused; this is mainly to avoid confusion.  The default was chosen
to be reasonable for most payments, and allow sufficient time for
on-chain payment if necessary.

The `f` field allows on-chain fallback.  This may not make sense for
tiny or very time-sensitive payments, however.  It's possible that new
address forms will appear, and so multiple `f` fields in an implied
preferred order help with transition, and `f` fields with versions 19-31
will be ignored by readers.

The `r` field allows limited routing assistance: as specified it only
allows minimum information to use private channels, but it could also
assist in future partial-knowledge routing.

# Payer / Payee Interactions

These are generally defined by the rest of the lightning BOLT series,
but it's worth noting that BOLT #5 specifies that the payee SHOULD
accept up to twice the expected `amount`, so the payer can make
payments harder to track by adding small variations.

The intent is that the payer recover the payee's node ID from the
signature, and after checking the conditions are acceptable (fees,
expiry, block timeout), attempt a payment.  It can use `r` fields to
augment its routing information if necessary to reach the final node.

If the payment succeeds but there is a later dispute, the payer can
prove both the signed offer from the payee, and the successful
payment.

## Payer / Payee Requirements

A payer SHOULD NOT attempt a payment after the `timestamp` plus
`expiry` has passed.  Otherwise, if a lightning payment fails, a payer
MAY attempt to use the address given the first `f` field it
understands for payment.  A payer MAY use the sequence of channels
specified by `r` to route to the payee.  A payer SHOULD consider the
fee amount and payment timeout before initiating payment.  A payer
SHOULD use the first `p` field did not skip as the payment hash.

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
  * `p5`: `data_length` (`p` = 1, `5` = 20. 1 * 32 + 20 == 52)
  * `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: payment hash 0001020304050607080900010203040506070809000102030405060708090102
* `d`: short description
  * `pl`: `data_length` (`p` = 1, `l` = 31. 1 * 32 + 31 == 63)
  * `2pkx2ctnv5sxxmmwwd5kgetjypeh2ursdae8g6twvus8g6rfwvs8qun0dfjkxaq`: 'Please consider supporting this project'
* `32vjcgqxyuj7nqphl3xmmhls2rkl3t97uan4j0xa87gj5779czc8p0z58zf5wpt9ggem6adl64cvawcxlef9djqwp2jzzfvs272504sp`: signature
* `0lkg3c`: Bech32 checksum

> ### Please send $3 for a cup of coffee to the same peer, within 1 minute
> lnbc2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpuaztrnwngzn3kdzw5hydlzf03qdgm2hdq27cqv3agm2awhz5se903vruatfhq77w3ls4evs3ch9zw97j25emudupq63nyw24cg27h2rspfj9srp

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `2500u`: amount (2500 micro-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `d`: short description
  * `q5`: `data_length` (`q` = 0, `5` = 20. 0 * 32 + 20 == 20)
  * `xysxxatsyp3k7enxv4js`: '1 cup coffee'
* `x`: expiry time
  * `qz`: `data_length` (`q` = 0, `z` = 2. 0 * 32 + 2 == 2)
  * `pu`: 60 seconds (`p` = 1, `u` = 28.  1 * 32 + 28 == 60)
* `azh8qt5w7qeewkmxtv55khqxvdfs9zzradsvj7rcej9knpzdwjykcq8gv4v2dl705pjadhpsc967zhzdpuwn5qzjm0s4hqm2u0vuhhqq`: signature
* `7vc09u`: Bech32 checksum

> ### Now send $24 for an entire list of things (hashed)
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqscc6gd6ql3jrc5yzme8v4ntcewwz5cnw92tz0pc8qcuufvq7khhr8wpald05e92xw006sq94mg8v2ndf4sefvf9sygkshp5zfem29trqq2yxxz7

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `h`: tagged field: hash of description
  * `p5`: `data_length` (`p` = 1, `5` = 20. 1 * 32 + 20 == 52)
  * `8yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqs`: SHA256 of 'One piece of chocolate cake, one icecream cone, one pickle, one slice of swiss cheese, one slice of salami, one lollypop, one piece of cherry pie, one sausage, one cupcake, and one slice of watermelon'
* `vjfls3ljx9e93jkw0kw40yxn4pevgzflf83qh2852esjddv4xk4z70nehrdcxa4fk0t6hlcc6vrxywke6njenk7yzkzw0quqcwxphkcp`: signature
* `vam37w`: Bech32 checksum

> ### The same, on testnet, with a fallback address mk2QpYatsKicvFVuTAQLBryyccRXMUaGHP
> lntb20m1pvjluezhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfpp3x9et2e20v6pu37c5d9vax37wxq72un98kmzzhznpurw9sgl2v0nklu2g4d0keph5t7tj9tcqd8rexnd07ux4uv2cjvcqwaxgj7v4uwn5wmypjd5n69z2xm3xgksg28nwht7f6zspwp3f9t

Breakdown:

* `lntb`: prefix, lightning on bitcoin testnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1. 1 * 32 + 1 == 33)
  * `3x9et2e20v6pu37c5d9vax37wxq72un98`: `3` = 17, so P2PKH address
* `h`: tagged field: hash of description...
* `qh84fmvn2klvglsjxfy0vq2mz6t9kjfzlxfwgljj35w2kwa60qv49k7jlsgx43yhs9nuutllkhhnt090mmenuhp8ue33pv4klmrzlcqp`: signature
* `us2s2r`: Bech32 checksum

> ### On mainnet, with fallback address 1RustyRX2oai4EYYDpQGWvEL62BBGqN9T with extra routing info to go via nodes 029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255 then 039e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqsfpp3qjmp7lwpagxun9pygexvgpjdc4jdj85fr9yq20q82gphp2nflc7jtzrcazrra7wwgzxqc8u7754cdlpfrmccae92qgzqvzq2ps8pqqqqqqqqqqqq9qqqvpeuqafqxu92d8lr6fvg0r5gv0heeeqgcrqlnm6jhphu9y00rrhy4grqszsvpcgpy9qqqqqqqqqqqq7qqzqfnlkwydm8rg30gjku7wmxmk06sevjp53fmvrcfegvwy7d5443jvyhxsel0hulkstws7vqv400q4j3wgpk4crg49682hr4scqvmad43cqd5m7tf

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `h`: tagged field: hash of description...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1. 1 * 32 + 1 == 33)
  * `3qjmp7lwpagxun9pygexvgpjdc4jdj85f`: `3` = 17, so P2PKH address
* `r`: tagged field: route information
  * `9y`: `data_length` (`9` = 5, `y` = 4.  5 * 32 + 4 = 164)
    `q20q82gphp2nflc7jtzrcazrra7wwgzxqc8u7754cdlpfrmccae92qgzqvzq2ps8pqqqqqqqqqqqq9qqqvpeuqafqxu92d8lr6fvg0r5gv0heeeqgcrqlnm6jhphu9y00rrhy4grqszsvpcgpy9qqqqqqqqqqqq7qqzq`: pubkey `029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255`, `short_channel_id` 0102030405060708, `fee` 20 millisatoshi, `cltv_expiry_delta` 3.  pubkey `039e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255`, `short_channel_id` 030405060708090a, `fee` 30 millisatoshi, `cltv_expiry_delta` 4.
* `fnlkwydm8rg30gjku7wmxmk06sevjp53fmvrcfegvwy7d5443jvyhxsel0hulkstws7vqv400q4j3wgpk4crg49682hr4scqvmad43cq`: signature
* `d5m7tf`: Bech32 checksum

> ### On mainnet, with fallback (P2SH) address 3EktnHQD7RiAE6uzMj2ZifT9YgRrkSgzQX
> lnbc20m1pvjluezhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfppj3a24vwu6r8ejrss3axul8rxldph2q7z9kmrgvr7xlaqm47apw3d48zm203kzcq357a4ls9al2ea73r8jcceyjtya6fu5wzzpe50zrge6ulk4nvjcpxlekvmxl6qcs9j3tz0469gq5g658y

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `f`: tagged field: fallback address.
  * `pp`: `data_length` (`p` = 1. 1 * 32 + 1 == 33)
  * `j3a24vwu6r8ejrss3axul8rxldph2q7z9`: `j` = 18, so P2SH address
* `h`: tagged field: hash of description...
* `2jhz8j78lv2jynuzmz6g8ve53he7pheeype33zlja5azae957585uu7x59w0f2l3rugyva6zpu394y4rh093j6wxze0ldsvk757a9msq`: signature
* `mf9swh`: Bech32 checksum

> ### On mainnet, with fallback (P2WPKH) address bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4
> lnbc20m1pvjluezhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfppqw508d6qejxtdg4y5r3zarvary0c5xw7kepvrhrm9s57hejg0p662ur5j5cr03890fa7k2pypgttmh4897d3raaq85a293e9jpuqwl0rnfuwzam7yr8e690nd2ypcq9hlkdwdvycqa0qza8

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `f`: tagged field: fallback address.
  * `pp`: `data_length` (`p` = 1. 1 * 32 + 1 == 33)
  * `q`: 0, so witness version 0.  
  * `qw508d6qejxtdg4y5r3zarvary0c5xw7k`: 160 bits = P2WPKH.
* `h`: tagged field: hash of description...
* `gw6tk8z0p0qdy9ulggx65lvfsg3nxxhqjxuf2fvmkhl9f4jc74gy44d5ua9us509prqz3e7vjxrftn3jnk7nrglvahxf7arye5llphgq`: signature
* `qdtpa4`: Bech32 checksum

> ### On mainnet, with fallback (P2WSH) address bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3
> lnbc20m1pvjluezhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfp4qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q28j0v3rwgy9pvjnd48ee2pl8xrpxysd5g44td63g6xcjcu003j3qe8878hluqlvl3km8rm92f5stamd3jw763n3hck0ct7p8wwj463cql26ava

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment hash...
* `f`: tagged field: fallback address.
  * `p4`: `data_length` (`p` = 1, `4` = 21. 1 * 32 + 21 == 53)
  * `q`: 0, so witness version 0.
  * `rp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q`: 260 bits = P2WSH.
* `h`: tagged field: hash of description...
* `5yps56lmsvgcrf476flet6js02m93kgasews8q3jhtp7d6cqckmh70650maq4u65tk53ypszy77v9ng9h2z3q3eqhtc3ewgmmv2grasp`: signature
* `akvd7y`: Bech32 checksum

# Authors

FIXME

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
