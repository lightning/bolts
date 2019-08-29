# Format for Event-based Test Specifications.

The programmatic test cases for the spec are a tree of events and
expected responses which test various scenarios described in the
specification.  They serve only as guidelines: in some cases a
compliant implementation might produce a different response than that
given here, though that suggests further examination of the testcase,
the implementation, or both.

## General Line Format

FILE := SEQUENCE*

SEQUENCE := SEQUENCE_LINE+
SEQUENCE_LINE := SEQUENCE_STEP OPTION_SPEC* | META_LINE
SEQUENCE_STEP := INDENT4* NUMBER `.` SPACE+ EVENT_OR_SERIES OPTION_SPEC*

EVENT_OR_SERIES := EVENT | `One of:` | `Any order:`
EVENT := INPUT_EVENT | OUTPUT_EVENT | `nothing`

META_LINE := COMMENT | SPACE* | VARSET | INCLUDE

COMMENT := `#` [SPACE|STRING]*
VARSET := IDENTIFIER`=`[SPACE|STRING]* OPTION_SPEC*
INCLUDE := `include` SPACE STRING OPTION_SPEC*

Comment and blank lines are ignored.

Variable lines set variables which can be expanded in any position with
a `$` prefix.  There's currently no scope to variables.

Include lines pull in other files, which is helpful for complex tests.

Other lines are indented by multiples of 4 spaces; a line not indented
by a multiple of 4 is be joined to the previous line (this allows
nicer formatting for long lines).

Each non-comment line indicates something to do to the implementation
(input event) or some response it should give (output event).

Indentation indicates alternative sequences, eg. this reflects two tests,
STEP1->STEP2a->STEP3 and STEP1->STEP2b->STEP3:

    1. STEP1
        1. STEP2a
        1. STEP2b
    2. STEP3

An step must either have NUMBER 1, in which case it follows directly
from the parent, or NUMBER one greater than the previous step at the
same level, in which case it follows the previous.

There must be exactly one top-level `1.` step.

The special marker `Any order:` indicates that the following sequences
starting with distinct output events will occur, but might happen in
any order.  This is useful for gossip messages which can be ordered in
multiple ways:

    1. STEP1
	2. Any order:
	    1. STEP2a
	    1. STEP2b
	    1. STEP2c

This means the test will accept STEP1->STEP2a->STEP2b->STEP2c,
STEP1->STEP2a->STEP2c->STEP2b, STEP1->STEP2b->STEP2a->STEP2c, 
STEP1->STEP2b->STEP2c->STEP2a, STEP1->STEP2c->STEP2a->STEP2b, 
or STEP1->STEP2c->STEP2b->STEP2c.

The special marker `One of:` indicate sequences starting with distinct
output events, only one of which could occur.  This is useful for optional
outputs which are more constrained, eg:

    1. STEP1
	2. One of:
		1. STEP2a
		2. STEP2b
		1. STEP2c
    2. STEP3

This means the test will accept STEP1->STEP2a->STEP2b->STEP3, or
STEP1->STEP2c->STEP3.

## Option specifiers

OPTION_SPEC := SPACE+ [`!`]OPTION_NAME
OPTION_NAME := `opt`IDENTIFIER[`/`ODD_OR_EVEN]
ODD_OR_EVEN := `odd` | `even`

Some individual lines only apply if certain options are (not) supported.
If the implementation does not support the option (or does support the
option and it's preceeded by `!`), the line should be ignored.  This
can be used to set/omit certain fields according to certain options,
or even whole steps.

You can also filter by whether options are optional (`odd`) or
compulsory (`even`).

## Input Events

INPUT_EVENT := CONNECT | RECV | BLOCK | DISCONNECT | OPENCMD

CONNECT := `connect:` SPACE+ CONNECT_OPTS
CONNECT_OPTS := `privkey=` HEX64

RECV := `recv:` [CONNSPEC] SPACE+ `type=` TYPENAME RECV_FIELDSPEC*
TYPENAME := IDENTIFIER|NUMBER
RECV_FIELDSPEC := SPACE+ IDENTIFIER`=`FIELDVALUE
FIELDVALUE := HEX | NUMBER

BLOCK := `block:` `height=`NUMBER SPACE+ `n`=NUMBER SPACE+ [TX*]
TX := `tx=`HEXSTRING

DISCONNECT := `disconnect:` SPACE+ CONNSPEC

FUNDCHANCMD := `fundchannel:` [CONNSPEC] SPACE+ `amount=`NUMBER SPACE+ `utxo=`HEX`/`NUMBER

INVOICECMD := `invoice:` SPACE+ `amount=`NUMBER SPACE+ `preimage=`HEX64

CONNSPEC := SPACE+ `conn=`HEX64

Input events are:
* `connect`: a connection established with another peer.  These examples
  assume a successful cryptographic handshake.  We provide the private key.
* `recv`: an incoming message.  The `type` is one of the message types
  defined in the spec or a raw number.  The other fields, if any, define
  the individual fields: each non-optional field will be specified.  Integer
  fields can be specified as decimal integers, all other fields are hexidecimal
  (note: this is confusing, as bitcoin usually reversed txids, and we don't!)
  Length fields are not specified, but derived from the length of the hexidecimal
  field.  The special (hex) field `extra` indicates additional data to be appended.   The optional `conn` argument allows you to specify which `connect`
  you're referring to.  The default is the last one.
* `block`: a generated block at a given height.  Any `tx` specified
  are to be placed in the (first) block.  If `n` is more than 1, it's a short
  cut for generating additional blocks.
* `disconnect`: a connection closed by a peer.
* `fundchannel`: tell the implementation to initiate the opening of a channel of the given `amount` of satoshis with the specific peer identified by `conn` (default, last `connect`).  The funding comes from a single `utxo`, as specified by txid and output number.
* `invoice`: tell the implementation to accept a payment of `amount` msatoshis, with payment_preimage `preimage`.

## Output Events

OUTPUT_EVENT := EXPECT_SEND | MAYBE_SEND | MUST_NOT_SEND | EXPECT_TX | EXPECT_ERROR

EXPECT_SEND := `expect-send:` [CONNSPEC] SPACE+ `type=` TYPENAME SPACE+ SEND_FIELDSPEC*
SEND_FIELDSPEC := IDENTIFIER`=`SPECVALUE
SPECVALUE := FIELDVALUE | HEX`/`HEX | `absent` | `*`LENGTH_RANGE
LENGTH_RANGE := `*`NUMBER | `*`NUMBER`-`NUMBER

MAYBE_SEND := `maybe-send:` [CONNSPEC] SPACE+ `type=` TYPENAME SEND_FIELDSPEC*

MUST_NOT_SEND := `must-not-send:` [CONNSPEC] SPACE+ `type=` TYPENAME SEND_FIELDSPEC*

EXPECT_TX := `expect-tx:` SPACE+ `tx=`HEX

EXPECT_ERROR := `expect-error:` [CONNSPEC] 

Output events are:
* `expect-send`: a message the implementation is expected to send.  Any field specified must match exactly for the test to pass; the value`/`mask notation is used to compare bits against a mask; the field should be zero-padded for comparison if necessary.  `*` is used to specify a length (in bytes) or a length range.  The special field value `absent` means the (presumably optional) field must not be present.
* `maybe-send`: a message the implementation may send, at any point from now on (until the next `disconnect`)
* `must-not-send`: a message the implementation must not send, at any point from now on (until the next `disconnect`).  This implies waiting at the end of the test (for a gossip flush!) to make sure it doesn't send it.
* `expect-tx`: a transaction the implementation is expected to broadcast.  The transactions here assume deterministic signatures.
* `expect-error`: the implementation is expected to detect an error.  This is generally a `expect-send` of `type=error` but it's legal for it to simply close the connection.  If there's no `expect-error` event, the implementation is expected *not* to have an error.


## Test Node Setup

The peer secret of the test node is assumed 
`0000000000000000000000000000000000000000000000000000000000000001`
which makes its public key
`0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798`.

The `minimum_depth` setting of the test node is assumed to be 3.

The following secrets are used for the first channel (if successive
channels exist in tests, they are only used for gossip test and their
exact configuration is not tested); it's assumed that RFC6979 (using
HMAC-SHA256) is used to generate transaction signatures.

    funding_privkey: 0000000000000000000000000000000000000000000000000000000000000010
	revocation_basepoint_secret: 0000000000000000000000000000000000000000000000000000000000000011
	payment_basepoint_secret: 0000000000000000000000000000000000000000000000000000000000000012
	delayed_payment_basepoint_secret: 0000000000000000000000000000000000000000000000000000000000000013
	htlc_basepoint_secret: 0000000000000000000000000000000000000000000000000000000000000014
	per_commitment_secret_seed: FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF


## Blockchain Setup

The initial blockchain is a bitcoind `regtest` chain, which has the
following initial blocks:

    Block 0 (genesis): 0100000000000000000000000000000000000000000000000000000000000000000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4adae5494dffff7f20020000000101000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4d04ffff001d0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e206272696e6b206f66207365636f6e64206261696c6f757420666f722062616e6b73ffffffff0100f2052a01000000434104678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5fac00000000
    Block 1: 0000002006226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910f7b8705087f9bddd2777021d2a1dfefc2f1c5afa833b5c4ab00ccc8a556d04283f5a1095dffff7f200100000001020000000001010000000000000000000000000000000000000000000000000000000000000000ffffffff03510101ffffffff0200f2052a01000000160014751e76e8199196d454941c45d1b3a323f1433bd60000000000000000266a24aa21a9ede2f61c3f71d1defd3fa999dfa36953755c690689799962b48bebd836974e8cf90120000000000000000000000000000000000000000000000000000000000000000000000000

The coinbase pays 50 BTC to the following key/address:

    privkey: 0000000000000000000000000000000000000000000000000000000000000001
    WIF: cMahea7zqjxrtgAbB7LSGbcQUr1uX1ojuat9jZodMN87JcbXMTcA
    P2WPKH: bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080

A further 100 blocks are generated to allow the 50BTC output to be
spent, so block height is 101.  The file `setup.incl` contains more
helpers for standard setups.
