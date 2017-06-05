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

## Requirements

A writer MUST encode the the payment request in Bech32 as specified in
BIP-0173.  A reader MUST parse the address as Bech32 as specified in
BIP-0173, and MUST fail if the checksum is incorrect.

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
512-bit secp256k1 signature of the double SHA2 256-bit hash of the
Human Readable Part concatenated with a byte for each 5 bits of the
Data Part, with a trailing byte containing the recovery ID (0, 1, 2 or
3).

## Rationale

`signature` covers the pre-base32 encoded data for simplicity,
especially since the data part may not end on an 8-bit boundary.  It
also allows public key recovery, so the identity of the payee node is
implied.

## Tagged Fields

Each Tagged Field is of format:

1. `type` (5 bits)
1. `data_length` (10 bits, big-endian)
1. `data` (`data_length` x 5 bits)

Currently defined Tagged Fields are:

* `p` (1): `data_length` 52.  256-bit SHA256 payment_hash: preimage of this provides proof of payment.
* `d` (13): `data_length` variable.  short description of purpose of payment (ASCII),  e.g. '1 cup of coffee'
* `h` (23): `data_length` 52.  256-bit description of purpose of payment (SHA256).  This is used to commit to an associated description which is too long to fit, such as may be contained in a web page.
* `x` (6): `data_length` variable.  `expiry` time in seconds (big-endian). Default is 3600 (1 hour) if not specified.
* `f` (9): `data_length` variable, depending in version. Fallback on-chain address: for bitcoin, this starts with a 5 bit `version`; a witness program or P2PKH or P2SH address.
* `r` (3): extra routing information.  This should be appended to the route
      to allow routing to non-public nodes; there may be more than one of these.
   * `pubkey` (264 bits)
   * `channel_id` (64 bits)
   * `fee` (64 bits, big-endian)
   * `cltv_expiry_delta` (16 bits, big-endian)

### Requirements

A writer MUST include exactly one `p` field, and set `payment_hash` to
the SHA-2 256-bit hash of the `payment_preimage` which will be given
in return for payment.

A writer MUST NOT include more than one `d`, `h`, or `x` fields, and
MAY include more than one `f` field.

A writer MUST include either a `d` or `h` field, and MUST NOT include
both.  If included, a writer SHOULD make `d` a complete description of
the purpose of the payment.  If included, a writer MUST make the preimage
of the hashed description in `h` available through some unspecified means,
which SHOULD be a complete description of the purpose of the payment.

A writer SHOULD use the minimum `x` `data_length` possible.

If a writer offers more than one of any field type, it MUST specify
the most-preferred field first, followed by less-preferred fields in
order.

For bitcoin payments, a writer MUST set an
`f` field to a valid witness version and program, or `17` followed by
a public key hash, or `18` followed by a script hash.

A writer MUST include at least one `r` field if it does not have a
public channel associated with its public key.  The `pubkey` is the
node ID of the start of the channel, `channel_id` is the channel ID
field to identify the channel, `fee` is the total fee required to use
that channel to send `amount` to the final node, specified in 10^-11
currency units, and `cltv_expiry_delta` is the block delta required
by the channel.  A writer MAY include more than one `r` field to
indicate a sequence of non-public channels to traverse.

A writer MUST pad field data to a multiple of 5 bits, using zeroes.

A reader MUST skip over unknown fields, an `f` field with unknown
`version`, or a `p`, `h` or `r` field which does not have ``data_length`` 52,
52 or 79 respectively.

A reader MUST check that the SHA-2 256 in the `h` field exactly
matches the hashed description.

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
assist in future partial-knowledge routing.  Future formats are
possible by altering the length, too.

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
specified by `r` to route to the payee.  A payee SHOULD consider the
fee amount and payment timeout before initiating payment.  A payee
SHOULD use the first `p` field did not skip as the payment hash.

A payee SHOULD NOT accept a payment after `timestamp` plus `expiry`.

# Implementation

https://github.com/rustyrussell/lightning-payencode

# Examples

> ### Please make a donation of any amount using payment_hash 0001020304050607080900010203040506070809000102030405060708090102 to me @03e7156ae33b0a208d0744199163177e909e80176e55d97a2f221ede0f934dd9ad
> lnbc1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqq7fshvguvjs864g4yj47aedw4y402hdl9g2tqqhyed3nuhr7c908g6uhq9llj7w3s58k3sej3tcg4weqxrxmp3cwxuvy9kfr0uzy8jgpy6uzal

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment preimage
  * `p5`: `data_length` (`p` = 1, `5` = 20. 1 * 32 + 20 == 52)
  * `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: preimage 0001020304050607080900010203040506070809000102030405060708090102
* `q7fshvguvjs864g4yj47aedw4y402hdl9g2tqqhyed3nuhr7c908g6uhq9llj7w3s58k3sej3tcg4weqxrxmp3cwxuvy9kfr0uzy8jgp`: signature
* `y6uzal`: Bech32 checksum

> ### Please send $3 for a cup of coffee to the same peer, within 1 minute
> lnbc2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpuazh8qt5w7qeewkmxtv55khqxvdfs9zzradsvj7rcej9knpzdwjykcq8gv4v2dl705pjadhpsc967zhzdpuwn5qzjm0s4hqm2u0vuhhqq7vc09u

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `2500u`: amount (2500 micro-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment preimage...
* `d`: short description
  * `q5`: `data_length` (`q` = 0, `5` = 20. 0 * 32 + 20 == 20)
  * `dq5xysxxatsyp3k7enxv4js`: '1 cup coffee'
* `x`: expiry time
  * `qz`: `data_length` (`q` = 0, `z` = 2. 0 * 32 + 2 == 2)
  * `pu`: 60 seconds (`p` = 1, `u` = 28.  1 * 32 + 28 == 60)
* `azh8qt5w7qeewkmxtv55khqxvdfs9zzradsvj7rcej9knpzdwjykcq8gv4v2dl705pjadhpsc967zhzdpuwn5qzjm0s4hqm2u0vuhhqq`: signature
* `7vc09u`: Bech32 checksum

> ### Now send $24 for an entire list of things (hashed)
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqsvjfls3ljx9e93jkw0kw40yxn4pevgzflf83qh2852esjddv4xk4z70nehrdcxa4fk0t6hlcc6vrxywke6njenk7yzkzw0quqcwxphkcpvam37w

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment preimage...
* `h`: tagged field: hash of description
  * `p5`: `data_length` (`p` = 1, `5` = 20. 1 * 32 + 20 == 52)
  * `8yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqs`: SHA256 of 'One piece of chocolate cake, one icecream cone, one pickle, one slice of swiss cheese, one slice of salami, one lollypop, one piece of cherry pie, one sausage, one cupcake, and one slice of watermelon'
* `vjfls3ljx9e93jkw0kw40yxn4pevgzflf83qh2852esjddv4xk4z70nehrdcxa4fk0t6hlcc6vrxywke6njenk7yzkzw0quqcwxphkcp`: signature
* `vam37w`: Bech32 checksum

> ### The same, on testnet, with a fallback address mk2QpYatsKicvFVuTAQLBryyccRXMUaGHP
> lntb20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfpp3x9et2e20v6pu37c5d9vax37wxq72un98hp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqsqh84fmvn2klvglsjxfy0vq2mz6t9kjfzlxfwgljj35w2kwa60qv49k7jlsgx43yhs9nuutllkhhnt090mmenuhp8ue33pv4klmrzlcqpus2s2r

Breakdown:

* `lntb`: prefix, lightning on bitcoin testnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment preimage...
* `f`: tagged field: fallback address
  * `pp`: `data_length` (`p` = 1. 1 * 32 + 1 == 33)
  * `3x9et2e20v6pu37c5d9vax37wxq72un98`: `3` = 17, so P2PKH address
* `h`: tagged field: hash of description...
* `hp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqsqh84fmvn2klvglsjxfy0vq2mz6t9kjfzlxfwgljj35w2kwa60qv49k7jlsgx43yhs9nuutllkhhnt090mmenuhp8ue33pv4klmrzlcqp`: signature
* `us2s2r`: Bech32 checksum

> ### On mainnet, with fallback address 1RustyRX2oai4EYYDpQGWvEL62BBGqN9T with extra routing info to get to node 029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqrzjq20q82gphp2nflc7jtzrcazrra7wwgzxqc8u7754cdlpfrmccae92qgzqvzq2ps8pqqqqqqqqqqqq9qqqvfpp3qjmp7lwpagxun9pygexvgpjdc4jdj85fhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqsjtf8rrkd7dujvdvrxhuk5a0tt9x9qh0t95jemn4tpen9y3nn7yt8jrmlyzffjh0hue8edkkq3090hruc8shpfu6wk4chfdvdusakycgpqtn4sp

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment preimage...
* `r`: tagged field: route information
  * `zj`: `data_length` (`z` = 2, `j` = 18.  2 * 32 + 18 = 82)
    `q20q82gphp2nflc7jtzrcazrra7wwgzxqc8u7754cdlpfrmccae92qgzqvzq2ps8pqqqqqqqqqqqq9qqqv`: pubkey `029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255`, `channel_id` 0102030405060708, `fee` 20 millisatoshi, `cltv_expiry_delta` 3.
* `f`: tagged field: fallback address...
* `h`: tagged field: hash of description...
* `jtf8rrkd7dujvdvrxhuk5a0tt9x9qh0t95jemn4tpen9y3nn7yt8jrmlyzffjh0hue8edkkq3090hruc8shpfu6wk4chfdvdusakycgp`: signature
* `qtn4sp`: Bech32 checksum

> ### On mainnet, with fallback (P2SH) address 3EktnHQD7RiAE6uzMj2ZifT9YgRrkSgzQX
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfppj3a24vwu6r8ejrss3axul8rxldph2q7z93xufve9n04786ust96l3dj0cp22fw7wyvcjrdjtg57qws9u96n2kv4xf8x9yu2ja6f00vjgp5y4lvj30xxy0duwqgz8yfqypfmxgjksq00galp

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment preimage...
* `f`: tagged field: fallback address.
  * `pp`: `data_length` (`p` = 1. 1 * 32 + 1 == 33)
  * `j3a24vwu6r8ejrss3axul8rxldph2q7z9`: `j` = 18, so P2SH address
* `3xufve9n04786ust96l3dj0cp22fw7wyvcjrdjtg57qws9u96n2kv4xf8x9yu2ja6f00vjgp5y4lvj30xxy0duwqgz8yfqypfmxgjksq`: signature
* `00galp`: Bech32 checksum

> ### On mainnet, with fallback (P2WPKH) address bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfppqw508d6qejxtdg4y5r3zarvary0c5xw7k2s057u6sfxswv5ysyvmzqemfnxew76stk45gfk0y0azxd8kglwrquhcxcvhww4f7zaxv8kpxwfvxnfdrzu20u56ajnxk3hj3r6p63jqpdsuvna

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment preimage...
* `f`: tagged field: fallback address.
  * `pp`: `data_length` (`p` = 1. 1 * 32 + 1 == 33)
  * `q`: 0, so witness version 0.  
  * `qw508d6qejxtdg4y5r3zarvary0c5xw7k`: 160 bits = P2WPKH.
* `2s057u6sfxswv5ysyvmzqemfnxew76stk45gfk0y0azxd8kglwrquhcxcvhww4f7zaxv8kpxwfvxnfdrzu20u56ajnxk3hj3r6p63jqp`: signature
* `dsuvna`: Bech32 checksum

> ### On mainnet, with fallback (P2WSH) address bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3
> lnbc20m1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfp4qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qhkm9qa8yszl8hqzaz9ctqagexxk2l0fyjcy0xhlsaggveqstwmz8rfc3afujc966fgjk47mzg0zzcrcg8zs89722vp2egxja0j3eucsq38r7dh

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `pvjluez`: timestamp (1496314658)
* `p`: payment preimage...
* `f`: tagged field: fallback address.
  * `p4`: `data_length` (`p` = 1, `4` = 21. 1 * 32 + 21 == 53)
  * `q`: 0, so witness version 0.
  * `rp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q`: 260 bits = P2WSH.
* `hkm9qa8yszl8hqzaz9ctqagexxk2l0fyjcy0xhlsaggveqstwmz8rfc3afujc966fgjk47mzg0zzcrcg8zs89722vp2egxja0j3eucsq`: signature
* `38r7dh`: Bech32 checksum

# Authors

FIXME

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
