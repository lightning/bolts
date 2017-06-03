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

1. `version`: 0 (5 bits)
1. `timestamp`: seconds-since-1970 (35 bits, big-endian)
1. `payment_hash`: (256 bits + 4 trailing zero bits)
1. Zero or more tagged parts.
1. `signature`: bitcoin-style signature of above. (520 bits)

## Requirements

A writer MUST set `version` to 0, MUST set `timestamp` to the time to
the number of seconds since Midnight 1 January 1970, UTC in
big-endian, and MUST set `payment_hash` to the SHA-2 256-bit hash of
the `payment_preimage` which will be given in return for payment,
followed by four zero bits.  A writer MUST set `signature` to a valid
512-bit secp256k1 signature of the double SHA2 256-bit hash of the
Human Readable Part concatenated with a bytes for each 5 bits of the
Data Part, with a trailing byte containing the recovery ID (0, 1, 2 or
3).

## Rationale

The 5-bit `version` fits neatly into base32 encoding (0 == `q`), and
allows for future incompatible upgrades.  `signature` covers the
pre-base32 encoded data for simplicity, especially since the data part
may not end on an 8-bit boundary.  It also allows public key recovery,
so the identity of the payee node is implied.

## Tagged Fields

Each Tagged Field is of format:

1. `type` (5 bits)
1. `length` (10 bits, big-endian)
1. `data` (length x 5 bits)

Currently defined Tagged Fields are:

* `d` (13): short description of purpose of payment (ASCII),  e.g. '1 cup of coffee'
* `h` (23): 256-bit description of purpose of payment (SHA256).  This is used to commit to an associated description which is too long to fit, such as may be contained in a web page.
* `x` (6): `expiry` time in seconds (big-endian). Default is 3600 (1 hour) if not specified.
* `f` (9): fallback on-chain address.  For bitcoin, this is 5 bits of
      witness version followed by a witness program, with witness
      version `3` (17) meaning P2PKH, `j` (18) meaning [P2SH](https://github.com/bitcoin/bips/blob/master/bip-0016.mediawiki); both are followed by a 20-byte hash value.
* `r` (3): extra routing information.  This should be appended to the route
      to allow routing to non-public nodes; there may be more than one of these.
   * `pubkey` (264 bits)
   * `channel_id` (64 bits)
   * `fee` (64 bits, big-endian)
   * `cltv_expiry_delta` (16 bits, big-endian)

### Requirements

A writer MUST NOT include more than one `d`, `h`, or `x` fields, and
MAY include more then one `f` field.

A writer MUST include either a `d` or `h` field, and MUST NOT include
both.  If included, a writer SHOULD make `d` a complete description of
the purpose of the payment.  If included, a writer MUST make the preimage
of the hashed description in `h` available through some unspecified means,
which SHOULD be a complete description of the purpose of the payment.

A writer SHOULD use the minimum `x` field length possible.

If a writer offers more than one `f` field, it SHOULD specify
preferred addresses first.  For bitcoin payments, a writer MUST set an
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

A writer MUST pad fields to a multiple of 5 bits, using zeroes.

A reader MUST skip over unknown fields, or `f` fields which do not
match the descriptions here.  A reader MAY fail or ignore a known
field which has an unexpected length.  A reader MUST check that the
SHA-2 256 in the `h` field exactly matches the hashed description.

### Rationale

The type-and-length format allows future extensions to be backward
compatible.  Lengths are always a multiple of 5 bits, for easy
encoding and decoding.

The `d` field allows inline descriptions, but may be insufficient for
complex orders; thus the `h` field allows a summary, though the method
by which the description is served is as-yet unspecified, and will
probably be transport-dependent.

The `x` field gives advance warning as to when a payment will be
refused; this is mainly to avoid confusion.  The default was chosen
to be reasonable for most payments, and allow sufficient time for
on-chain payment if necessary.

The `f` field allows on-chain fallback.  This may not make sense for
tiny or very time-sensitive payments, however.  It's possible that new
address forms will appear, and so multiple `f` fields in an implied
preferred order help with transition.

The `r` field allows limited routing assistance: as specified it only
allows minimum information to use private fields, but it could also
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
specified by `r` to route to the payee.  A payee SHOULD consider the
fee amount and payment timeout before initiating payment.

A payee SHOULD NOT accept a payment after `timestamp` plus `expiry`.

# Implementation

https://github.com/rustyrussell/lightning-payencode

# Examples

> ### Please make a donation of any amount using payment hash 0001020304050607080900010203040506070809000102030405060708090102 to me @03e7156ae33b0a208d0744199163177e909e80176e55d97a2f221ede0f934dd9ad
> lnbc1qpvj6chqqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypquuvrkdyhszmjzsa95kuw2mpkkzhn3qmewupphyhtk454mlytc0dn9sqd6n39g79aaf27cydcxm9w2378lf3ap6n4a3hd0tjvugq5fhgpm7ghcn

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `1`: Bech32 separator
* `q`: version (0)
* `pvj6chq`: timestamp (1496146656)
* `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: payment hash
* `uuvrkdyhszmjzsa95kuw2mpkkzhn3qmewupphyhtk454mlytc0dn9sqd6n39g79aaf27cydcxm9w2378lf3ap6n4a3hd0tjvugq5fhgp`: signature
* `m7ghcn`: Bech32 checksum

> ### Please send $3 for a cup of coffee to the same peer, within 1 minute
> lnbc2500u1qpvjlmewqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpue3cr0f2upddj0jf8nh7wesx5lf648kyhv57x5dgc6w5cxlwh4usr4z2sw947flahwrq7u7ps653fxfyvtswkqymu8vy6t3qsxyrmf2cpe23p7k

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `2500u`: amount (2500 micro-bitcoin)
* `1`: Bech32 separator
* `q`: version (0)
* `qpvjlme`: timestamp (1496313646)
* `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: payment hash.
* `d`: short description
  * `q5`: field length (`q` = 0, `5` = 20. 0 * 32 + 20 == 20)
  * `dq5xysxxatsyp3k7enxv4js`: '1 cup coffee'
* `x`: expiry time
  * `qz`: field length (`q` = 0, `z` = 2. 0 * 32 + 2 == 2)
  * `pu`: 60 seconds (`p` = 1, `u` = 28.  1 * 32 + 28 == 60)
* `e3cr0f2upddj0jf8nh7wesx5lf648kyhv57x5dgc6w5cxlwh4usr4z2sw947flahwrq7u7ps653fxfyvtswkqymu8vy6t3qsxyrmf2cp`: signature
* `e23p7k`: Bech32 checksum

> ### Now send $24 for an entire list of things (hashed)
> lnbc20m1qpvj6chqqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqscpt2ld45dqewrllnmf6hj355nfeypurkr6a2d0neyq2e6g9u6ur9tl7e7drhglfrn9yxk2cdujutuqksx2agqv8mphl0mzjrwm6k59qq2mnedn

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `q`: version (0)
* `pvj6chq`: timestamp (1496146656)
* `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: payment hash.
* `h`: tagged field: hash of description
  * `p5`: field length (`p` = 1, `5` = 20. 1 * 32 + 20 == 52)
  * `8yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqs`: SHA256 of 'One piece of chocolate cake, one icecream cone, one pickle, one slice of swiss cheese, one slice of salami, one lollypop, one piece of cherry pie, one sausage, one cupcake, and one slice of watermelon'
* `cpt2ld45dqewrllnmf6hj355nfeypurkr6a2d0neyq2e6g9u6ur9tl7e7drhglfrn9yxk2cdujutuqksx2agqv8mphl0mzjrwm6k59qq`: signature
* `2mnedn`: Bech32 checksum

> ### The same, on testnet, with a fallback address mk2QpYatsKicvFVuTAQLBryyccRXMUaGHP
> lntb20m1qpvj6chqqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfpp3x9et2e20v6pu37c5d9vax37wxq72un98hp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqsqsj75rjv443nrh8gu5xutlyyqyx6ul76m2rx87yxr5gdfagyywn3s6wtpfrl6elncce7rmh6kndvr5nur76w9u7z0k3gq93fyfpu9zqq3jp9as

Breakdown:

* `lntb`: prefix, lightning on bitcoin testnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `q`: version (0)
* `pvj6chq`: timestamp (1496146656)
* `f`: tagged field: fallback address
  * `pp`: field length (`p` = 1. 1 * 32 + 1 == 33)
  * `3x9et2e20v6pu37c5d9vax37wxq72un98`: `3` = 17, so P2PKH address
* `h`: tagged field: hash of description...
* `qsj75rjv443nrh8gu5xutlyyqyx6ul76m2rx87yxr5gdfagyywn3s6wtpfrl6elncce7rmh6kndvr5nur76w9u7z0k3gq93fyfpu9zqq`: signature
* `3jp9as`: Bech32 checksum

> ### On mainnet, with fallback address 1RustyRX2oai4EYYDpQGWvEL62BBGqN9T with extra routing info to get to node 029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255
> lnbc20m1qpvj6chqqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqrz0q20q82gphp2nflc7jtzrcazrra7wwgzxqc8u7754cdlpfrmccae92qgzqvzq2ps8pqqqqqq5qqqqqqcfpp3qjmp7lwpagxun9pygexvgpjdc4jdj85fhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqst7xnzx2sl9rkrc5lgzkcdqs57sj0s0vz8z9g2wk4hucfdrtvupkx93wqjcj8lpejzc95k4p4hw0qrfay5x36def3ret6yd9s0vqwtysqm5z5dw

Breakdown:

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `q`: version (0)
* `pvj6chq`: timestamp (1496146656)
* `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: payment hash.
* `r`: tagged field: route information
  * `z0`: field length (`z` = 2, `0` = 15.  2 * 32 + 15 = 79)
    `q20q82gphp2nflc7jtzrcazrra7wwgzxqc8u7754cdlpfrmccae92qgzqvzq2ps8pqqqqqq5qqqqqqc`: pubkey `029e03a901b85534ff1e92c43c74431f7ce72046060fcf7a95c37e148f78c77255`, `channel_id` 0102030405060708, `fee` 20 millisatoshi, `cltv_expiry_delta` 3.
* `f`: tagged field: fallback address...
* `h`: tagged field: hash of description...
* `t7xnzx2sl9rkrc5lgzkcdqs57sj0s0vz8z9g2wk4hucfdrtvupkx93wqjcj8lpejzc95k4p4hw0qrfay5x36def3ret6yd9s0vqwtysq`: signature
* `m5z5dw`: Bech32 checksum

> ### On mainnet, with fallback (p2sh) address 3EktnHQD7RiAE6uzMj2ZifT9YgRrkSgzQX
> lnbc20m1qpvj6chqqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfppj3a24vwu6r8ejrss3axul8rxldph2q7z9nyustv8ulfckvm84tndurwh2knpspl2m7hwqq7xvhr90lmgzgelktr2wgxnsj9fpmk3cs4waekjkzcmtwl36psn22pvp4pvcr2lsjegqq306hp

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `q`: version (0)
* `pvj6chq`: timestamp (1496146656)
* `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: payment hash.
* `f`: tagged field: fallback address.
  * `pp`: field length (`p` = 1. 1 * 32 + 1 == 33)
  * `j3a24vwu6r8ejrss3axul8rxldph2q7z9`: `j` = 18, so P2SH address
* `nyustv8ulfckvm84tndurwh2knpspl2m7hwqq7xvhr90lmgzgelktr2wgxnsj9fpmk3cs4waekjkzcmtwl36psn22pvp4pvcr2lsjegq`: signature
* `q306hp`: Bech32 checksum

> ### On mainnet, with fallback (p2wpkh) address bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4
> lnbc20m1qpvjmhmtqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfppqw508d6qejxtdg4y5r3zarvary0c5xw7khjkc5aw8qzadf8rmpcjlk9g6yp0pllmy6tjm2c3jy92dkk7kqvjj5lxr43wuyk7ff9flkhcx69pfrcsp8q7m4j60qfhsrv34fts7wlcqq2h2lk

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `q`: version (0)
* `pvjmhmt`: timestamp (1496178539)
* `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: payment hash.
* `f`: tagged field: fallback address.
  * `pp`: field length (`p` = 1. 1 * 32 + 1 == 33)
  * `q`: 0, so witness version 0.  
  * `qw508d6qejxtdg4y5r3zarvary0c5xw7k`: 160 bits = P2WPKH.
* `hjkc5aw8qzadf8rmpcjlk9g6yp0pllmy6tjm2c3jy92dkk7kqvjj5lxr43wuyk7ff9flkhcx69pfrcsp8q7m4j60qfhsrv34fts7wlcq`: signature
* `q2h2lk`: Bech32 checksum

> ### On mainnet, with fallback (p2wsh) address bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3
> lnbc20m1qpvjmc59qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqfp4qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qv0c6exmqzspaqtem5yuec26wu6cjtux030gkne3g445axpk2v9qy8307gp6vhuu33fj8kxer6gf47wfa39jhazfps6406lk9wst5qrqqrqjcx6

* `lnbc`: prefix, lightning on bitcoin mainnet
* `20m`: amount (20 milli-bitcoin)
* `1`: Bech32 separator
* `q`: version (0)
* `pvjmc59`: timestamp (1496179333)
* `qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq`: payment hash.
* `f`: tagged field: fallback address.
  * `p4`: field length (`p` = 1, `4` = 21. 1 * 32 + 21 == 53)
  * `q`: 0, so witness version 0.  
  * `v0c6exmqzspaqtem5yuec26wu6cjtux030gkne3g445axpk2v9qy8307gp6vhuu33fj8kxer6gf47wfa39jhazfps6406lk9wst5qrqqrqjcx6`: 265 bits = P2WPKH + 1 zero bit.
* `v0c6exmqzspaqtem5yuec26wu6cjtux030gkne3g445axpk2v9qy8307gp6vhuu33fj8kxer6gf47wfa39jhazfps6406lk9wst5qrqq`: signature
* `rqjcx6`: Bech32 checksum

# Authors

FIXME

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
