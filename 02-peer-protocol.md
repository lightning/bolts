# BOLT #2: Peer Protocol for Channel Management

The peer channel protocol has three phases: establishment, normal
operation, and closing.

# Table of Contents
  * [Channel](#channel)
    * [Channel Establishment](#channel-establishment)
      * [The `open_channel` message](#the-open_channel-message)
      * [The `accept_channel` message](#the-accept_channel-message)
      * [The `funding_created` message](#the-funding_created-message)
      * [The `funding_signed` message](#the-funding_signed-message)
      * [The `funding_locked` message](#the-funding_locked-message)
    * [Channel Close](#channel-close)
      * [Closing initiation: `shutdown`](#closing-initiation-shutdown)
      * [Closing negotiation: `closing_signed`](#closing-negotiation-closing_signed)
    * [Normal Operation](#normal-operation)
      * [Forwarding HTLCs](#forwarding-htlcs)
      * [Risks With HTLC Timeouts](#risks-with-htlc-timeouts)
      * [Adding an HTLC: `update_add_htlc`](#adding-an-htlc-update_add_htlc)
      * [Removing an HTLC: `update_fulfill_htlc`, `update_fail_htlc` and `update_fail_malformed_htlc`](#removing-an-htlc-update_fulfill_htlc-update_fail_htlc-and-update_fail_malformed_htlc)
      * [Committing Updates So Far: `commitment_signed`](#committing-updates-so-far-commitment_signed)
      * [Completing the transition to the updated state: `revoke_and_ack`](#completing-the-transition-to-the-updated-state-revoke_and_ack)
      * [Updating Fees: `update_fee`](#updating-fees-update_fee)
    * [Message Retransmission](#message-retransmission)
  * [Authors](#authors)
  
# Channel

## Channel Establishment


Channel establishment begins immediately after authentication, and
consists of the funding node sending an `open_channel` message,
followed by the responding node sending `accept_channel`. With the
channel parameters locked in, the funder is able to create the funding
transaction and both versions of the commitment transaction as described in
[BOLT
03](https://github.com/lightningnetwork/lightning-rfc/blob/master/03-transactions.md#bolt-3-bitcoin-transaction-and-script-formats).
The funder then sends the outpoint of the funding output along with a
signature for the responder's version of the commitment transaction
with the `funding_created` message. Once the responder learns the
funding outpoint, she is able to generate the initiator's commitment
for the commitment transaction, and send it over using the
`funding_signed` message.

Once the channel funder receives the `funding_signed` message, they
must broadcast the funding transaction to the Bitcoin network. After
the `funding_signed` message is sent/received, both sides should wait
for the funding transaction to ensure the blockchain and reach their
specified depth (number of confirmations). After both sides have sent
the `funding_locked` message, the channel is established and can begin
normal operation. The `funding_locked` message includes information
which will be used to construct channel authentication proofs.


        +-------+                              +-------+
        |       |--(1)---  open_channel  ----->|       |
        |       |<-(2)--  accept_channel  -----|       |
        |       |                              |       |
        |   A   |--(3)--  funding_created  --->|   B   |
        |       |<-(4)--  funding_signed  -----|       |
        |       |                              |       |
        |       |--(5)--- funding_locked  ---->|       |
        |       |<-(6)--- funding_locked  -----|       |
        +-------+                              +-------+


If this fails at any stage, or a node decides that the channel terms
offered by the other node are not suitable, the channel establishment
fails.

Note that multiple channels can operate in parallel, as all channel
messages are identified by either a `temporary-channel-id` (before the
funding transaction is created) or `channel-id` derived from the
funding transaction.

### The `open_channel` message


This message contains information about a node, and indicates its
desire to set up a new channel.

1. type: 32 (`open_channel`)
2. data:
   * [32:temporary-channel-id]
   * [8:funding-satoshis]
   * [8:push-msat]
   * [8:dust-limit-satoshis]
   * [8:max-htlc-value-in-flight-msat]
   * [8:channel-reserve-satoshis]
   * [4:htlc-minimum-msat]
   * [4:feerate-per-kw]
   * [2:to-self-delay]
   * [2:max-accepted-htlcs]
   * [33:funding-pubkey]
   * [33:revocation-basepoint]
   * [33:payment-basepoint]
   * [33:delayed-payment-basepoint]
   * [33:first-per-commitment-point]


The `temporary-channel-id` is used to identify this channel until the funding transaction is established. `funding-satoshis` is the amount the sender is putting into the channel.  `dust-limit-satoshis` is the threshold below which output should be generated for this node's commitment or HTLC transaction; ie. HTLCs below this amount plus HTLC transaction fees are not enforceable on-chain.  This reflects the reality that tiny outputs are not considered standard transactions and will not propagate through the Bitcoin network.

`max-htlc-value-in-inflight-msat` is a cap on total value of outstanding HTLCs, which allows a node to limit its exposure to HTLCs; similarly `max-accepted-htlcs` limits the number of outstanding HTLCs the other node can offer. `channel-reserve-satoshis` is the minimum amount that the other node is to keep as a direct payment. `htlc-minimum-msat` indicates the smallest value HTLC this node will accept.

`feerate-per-kw` indicates the initial fee rate by 1000-weight (ie. 4 times by the more normally-used 'feerate per kilobyte') which this side will pay for commitment and HTLC transactions as described in [BOLT #3](03-transactions.md#fee-calculation) (this can be adjusted later with an `update_fee` message).  `to-self-delay` is the number of blocks that the other nodes to-self outputs must be delayed, using `OP_CHECKSEQUENCEVERIFY` delays; this is how long it will have to wait in case of breakdown before redeeming its own funds.

The `funding-pubkey` is the public key in the 2-of-2 multisig script of the funding transaction output.  The `revocation-basepoint` is combined with the revocation preimage for this commitment transaction to generate a unique revocation key for this commitment transaction. The `payment-basepoint` and `delayed-payment-basepoint` are similarly used to generate a series of keys for any payments to this node: `delayed-payment-basepoint` is used to for payments encumbered by a delay.  Varying these keys ensures that the transaction ID of each commitment transaction is unpredictable by an external observer, even if one commitment transaction is seen: this property is very useful for preserving privacy when outsourcing penalty transactions to third parties.

FIXME: Describe Dangerous feature bit for larger channel amounts.


#### Requirements


A sending node MUST ensure `temporary-channel-id` is unique from any other
channel id with the same peer.  The sender MUST set `funding-satoshis`
to less than 2^24 satoshi.  The sender MUST set `push-msat` to
equal or less than to 1000 * `funding-satoshis`.   The sender SHOULD set `to-self-delay` sufficient to ensure the sender
can irreversibly spend a commitment transaction output in case of
misbehavior by the receiver.  The sender SHOULD set `minimum-depth` to
an amount where the sender considers reorganizations to be low risk.
`funding-pubkey`, `revocation-basepoint`, `payment-basepoint` and `delayed-payment-basepoint` MUST be valid DER-encoded
compressed secp256k1 pubkeys. The sender SHOULD set `feerate-per-kw`
to at least the rate it estimates would cause the transaction to be
immediately included in a block.


The sender SHOULD set `dust-limit-satoshis` to a sufficient value to
allow commitment transactions to propagate through the Bitcoin
network.  It SHOULD set `htlc-minimum-msat` to the minimum
amount HTLC it is willing to accept from this peer.

The receiving node MUST accept a new `open-channel` message if the
connection has been re-established after receiving a previous
`open-channel` and before receiving a `funding-created` message.  In
this case, the receiving node MUST discard the previous `open-channel`
message.

The receiving node MUST fail the channel if `to-self-delay` is
unreasonably large.  The receiver MAY fail the channel if
`funding-satoshis` is too small, and MUST fail the channel if
`push-msat` is greater than `funding-amount` * 1000.
The receiving node MAY fail the channel if it considers
`htlc-minimum-msat` too large, `max-htlc-value-in-flight` too small, `channel-reserve-satoshis` too large, or `max-accepted-htlcs` too small.  It MUST fail the channel if `max-accepted-htlcs` is greater than 483.

The receiver MUST fail the channel if it
considers `feerate-per-kw` too small for timely processing, or unreasonably large.  The
receiver MUST fail the channel if `funding-pubkey`, `revocation-basepoint`, `payment-basepoint` or `delayed-payment-basepoint`
are not valid DER-encoded compressed secp256k1 pubkeys.


The receiver MUST NOT consider funds received using `push-msat` to be received until the funding transaction has reached sufficient depth.


#### Rationale


The *channel reserve* is specified by the peer's `channel-reserve-satoshis`; 1% of the channel total is suggested.  Each side of a channel maintains this reserve so it always has something to lose if it were to try to broadcast an old, revoked commitment transaction.  Initially this reserve may not be met, as only one side has funds, but the protocol ensures that progress is always toward it being met, and once met it is maintained.


The sender can unconditionally give initial funds to the receiver using a non-zero `push-msat`, and this is one case where the normal reserve mechanism doesn't apply.  However, like any other on-chain transaction, this payment is not certain until the funding transaction has been confirmed sufficiently (may be double-spent) and may require a separate method to prove payment via on-chain confirmation.

The `feerate-per-kw` is generally only a concern to the sender (who pays the fees), but that is also the feerate paid by HTLC transactions; thus unresonably large fee rates can also penalize the reciepient.

#### Future


It would be easy to have a local feature bit which indicated that a
receiving node was prepared to fund a channel, which would reverse this
protocol.


### The `accept_channel` message


This message contains information about a node, and indicates its
acceptance of the new channel.


1. type: 33 (`accept_channel`)
2. data:
   * [32:temporary-channel-id]
   * [8:dust-limit-satoshis]
   * [8:max-htlc-value-in-flight-msat]
   * [8:channel-reserve-satoshis]
   * [4:minimum-depth]
   * [4:htlc-minimum-msat]
   * [2:to-self-delay]
   * [2:max-accepted-htlcs]
   * [33:funding-pubkey]
   * [33:revocation-basepoint]
   * [33:payment-basepoint]
   * [33:delayed-payment-basepoint]
   * [33:first-per-commitment-point]

#### Requirements


The `temporary-channel-id` MUST be the same as the `temporary-channel-id` in the `open_channel` message.  The sender SHOULD set `minimum-depth` to a number of blocks it considers reasonable to avoid double-spending of the funding transaction.

The receiver MAY reject the `minimum-depth` if it considers it unreasonably large.
Other fields have the same requirements as their counterparts in `open_channel`.


### The `funding_created` message

This message describes the outpoint which the funder has created for
the initial commitment transactions.  After receiving the peer's
signature, it will broadcast the funding transaction.

1. type: 34 (`funding_created`)
2. data:
    * [32:temporary-channel-id]
    * [32:funding-txid]
    * [2:funding-output-index]
    * [64:signature]

#### Requirements

The sender MUST set `temporary-channel-id` the same as the `temporary-channel-id` in the `open_channel` message.  The sender MUST set `funding-txid` to the transaction ID of a non-malleable transaction, which it MUST NOT broadcast, and MUST set `funding-output-index` to the output number of that transaction which corresponds the funding transaction output as defined in [BOLT #3](03-transactions.md#funding-transaction-output), and MUST set `signature` to the valid signature using its `funding-pubkey` for the initial commitment transaction as defined in [BOLT #3](03-transactions.md#commitment-transaction).  The sender SHOULD use only BIP141 (Segregated Witness) inputs when creating the funding transaction.

The recipient MUST fail the channel if `signature` is incorrect.

#### Rationale

The `funding-output-index` can only be 2 bytes, since that's how we'll pack it into the channel-id used throughout the gossip protocol.  The limit of 65535 outputs should not be overly burdensome.

A transaction with all Segregated Witness inputs is not malleable, hence the recommendation for the funding transaction.

### The `funding_signed` message

This message gives the funder the signature they need for the first
commitment transaction, so they can broadcast it knowing they can
redeem their funds if they need to.

This message introduces the `channel-id` which identifies , which is derived from the funding transaction by combining the `funding-txid` and the `funding-output-index` using big-endian exclusive-OR (ie. `funding-output-index` alters the last two bytes).

1. type: 35 (`funding_signed`)
2. data:
    * [32:channel-id]
    * [64:signature]

#### Requirements

The sender MUST set `channel-id` by exclusive-OR of the `funding-txid` and the `funding-output-index` from the `funding_created` message, and MUST set `signature` to the valid signature using its `funding-pubkey` for the initial commitment transaction as defined in [BOLT #3](03-transactions.md#commitment-transaction).

The recipient MUST fail the channel if `signature` is incorrect.

### The `funding_locked` message

This message indicates that the funding transaction has reached the `minimum-depth` asked for in `accept_channel`.  Once both nodes have sent this, the channel enters normal operating mode.

1. type: 36 (`funding_locked`)
2. data:
    * [32:channel-id]
    * [33:next-per-commitment-point]

#### Requirements

The sender MUST wait until the funding transaction has reached
`minimum-depth` before sending this message.

The sender MUST set `next-per-commitment-point` to the
per-commitment point to be used for the following commitment
transaction, derived as specified in
[BOLT #3](03-transactions.md#per-commitment-secret-requirements).

#### Future

We could add an SPV proof, and route block hashes in separate
messages.

## Channel Close

Nodes can negotiate a mutual close for the connection, which unlike a
unilateral close, allows them to access their funds immediately and
can be negotiated with lower fees.

Closing happens in two stages: the first is by one side indicating
that it wants to clear the channel (and thus will accept no new
HTLCs), and once all HTLCs are resolved, the final channel close
negotiation begins.

        +-------+                              +-------+
        |       |--(1)-----  shutdown  ------->|       |
        |       |<-(2)-----  shutdown  --------|       |
        |       |                              |       |
        |       | <complete all pending htlcs> |       |
        |   A   |                 ...          |   B   |
        |       |                              |       |
        |       |<-(3)-- closing_signed  F1----|       |
        |       |--(4)-- closing_signed  F2--->|       |
        |       |              ...             |       |
        |       |--(?)-- closing_signed  Fn--->|       |
        |       |<-(?)-- closing_signed  Fn----|       |
        +-------+                              +-------+


### Closing initiation: `shutdown`

Either node (or both) can send a `shutdown` message to initiate closing,
and indicating the scriptpubkey it wants to be paid to.


1. type: 38 (`shutdown`)
2. data:
   * [32:channel-id]
   * [2:len]
   * [len:scriptpubkey]

#### Requirements

A node MUST NOT send a `shutdown` if there are updates pending
on the receiving node's commitment transaction which are not yet added to the sender's commitment.

A node MUST NOT send an `update_add_htlc` after a `shutdown`,
and MUST NOT send more than one `shutdown`.  A sending node
SHOULD fail to route any HTLC added after it sent `shutdown`.

A sending node MUST set `scriptpubkey` to one of the following forms:

1. `OP_DUP` `OP_HASH160` `20` 20-bytes `OP_EQUALVERIFY` `OP_CHECKSIG`
   (pay to pubkey hash), OR
2. `OP_HASH160` `20` 20-bytes `OP_EQUAL` (pay to script hash), OR
3. `OP_0` `20` 20-bytes (version 0 pay to witness pubkey), OR
4. `OP_0` `32` 32-bytes (version 0 pay to witness script hash)

A receiving node SHOULD fail the connection if the `scriptpubkey` is not one
of those forms.

A receiving node MUST reply to a `shutdown` message with a `shutdown` once there are no outstanding updates on the peer, unless it has already sent a `shutdown`.

#### Rationale

If channel state is always "clean" (no pending changes) when a
shutdown starts, we avoid the question of how to behave if it wasn't;
the sender always send an `update_commit` first.

As shutdown implies a desire to terminate, it implies that no new
HTLCs will be added or accepted.

The `scriptpubkey` forms include only standard forms accepted by the
Bitcoin network, ensuring that the resulting transaction will
propagate to miners.

The `shutdown` response requirement implies that the node sends `update_commit` to commit any outstanding changes before replying, but it could theoretically reconnect instead, which simply erases all outstanding uncommitted changes.

### Closing negotiation: `closing_signed`

Once shutdown is complete and the channel is empty of HTLCs, the final
current commitment transactions will have no HTLCs, and closing fee
negotiation begins.  Each node chooses a fee it thinks is fair, and
signs the close transaction with the `script_pubkey` fields from the
`shutdown` messages and that fee, and sends the signature.  The
process terminates when both agree on the same fee, or one side fails
the channel.

1. type: 39 (`closing_signed`)
2. data:
   * [32:channel-id]
   * [8:fee-satoshis]
   * [64:signature]

#### Requirements

Nodes SHOULD send a `closing_signed` message after `shutdown` has
been received and no HTLCs remain in either commitment transaction.

A sending node MUST set `fee-satoshis` lower than or equal to the
fee of the final commitment transaction.

The sender SHOULD set the initial `fee-satoshis` according to its
estimate of cost of inclusion in a block.

The sender MUST set `signature` to the Bitcoin signature of the close
transaction with the node responsible for paying the bitcoin fee
paying `fee-satoshis`, without populating any output which is below
the receiver's `dust-limit-satoshis`.

The receiver MUST check `signature` is valid for the close transaction
with the given `fee-satoshis` as detailed above, and MUST fail the
connection if it is not.

If the receiver agrees with the fee, it SHOULD reply with a
`closing_signed` with the same `fee-satoshis` value, otherwise it
SHOULD propose a value strictly between the received `fee-satoshis`
and its previously-sent `fee-satoshis`.

Once a node has sent or received a `closing_signed` with matching
`fee-satoshis` it SHOULD close the connection and SHOULD sign and
broadcast the final closing transaction.

#### Rationale

Note that there is limited risk if the closing transaction is
delayed, and it will be broadcast very soon, so there is usually no
reason to pay a premium for rapid processing.

## Normal Operation

Once both nodes have exchanged `funding_locked` (and optionally `announcement_signatures`), the channel can be used to make payments via Hash TimeLocked Contracts.

Changes are sent in batches: one or more `update` messages are sent before a
`commit_sig` message, as in the following diagram:

        +-------+                            +-------+
        |       |--(1)---- add_htlc   ------>|       |
        |       |--(2)---- add_htlc   ------>|       |
        |       |<-(3)---- add_htlc   -------|       |
        |       |                            |       |
        |       |--(4)----   commit   ------>|       |
        |   A   |                            |   B   |
        |       |<-(5)--- revoke_and_ack-----|       |
        |       |<-(6)----   commit   -------|       |
        |       |                            |       |
        |       |--(7)--- revoke_and_ack---->|       |
        +-------+                            +-------+


Counterintuitively, these updates apply to the *other node's*
commitment transaction; the node only adds those updates to its own
commitment transaction when the remote node acknowledges it has
applied them via `revoke_and_ack`.

Thus each update traverses through the following states:

1. Pending on the receiver
2. In the receiver's latest commitment transaction,
3. ... and the receiver's previous commitment transaction has been revoked,
   and the HTLC is pending on the sender.
4. ... and in the sender's latest commitment transaction
5. ... and the sender's previous commitment transaction has been revoked


As the two nodes updates are independent, the two commitment
transactions may be out of sync indefinitely.  This is not concerning:
what matters is whether both sides have irrevocably committed to a
particular HTLC or not (the final state, above).

### Forwarding HTLCs

In general, a node offers HTLCs for two reasons: to initiate a payment of its own, 
or to forward a payment coming from another node. In the forwarding case, care must 
be taken to ensure that the *outgoing* HTLC cannot be redeemed unless the *incoming* 
HTLC can be redeemed; these requirements ensure that is always true.

The addition/removal of an HTLC is considered *irrevocably committed* when:

1. the commitment transaction with/without it it is committed by both nodes, and any 
previous commitment transaction which without/with it has been revoked, OR
2. the commitment transaction with/without it has been irreversibly committed to 
the blockchain.

#### Requirements

A node MUST NOT offer an HTLC (`update_htlc_add`) in response to an incoming HTLC until 
the incoming HTLC has been irrevocably committed.

A node MUST NOT fail an incoming HTLC (`update_fail_htlc`) for which it has committed 
to an outgoing HTLC, until the removal of the outgoing HTLC is irrevocably committed.
 
A node SHOULD fulfill an incoming HTLC for which it has committed to an outgoing HTLC, 
as soon as it receives `update_fulfill_htlc` for the outgoing HTLC.

#### Rationale

In general, we need to complete one side of the exchange before dealing with the other.
Fulfilling an HTLC is different: knowledge of the preimage is by definition irrevocable, 
so we should fulfill the incoming HTLC as soon as we can to reduce latency.


### Risks With HTLC Timeouts


As a result of forwarding an HTLC from node A to node C, B will end up having an incoming
HTLC from A and an outgoing HTLC to C. B will make sure that the incoming HTLC has a greater 
timeout than the outgoing HTLC, so that B can get refunded from C sooner than it has to refund
 A if the payment does not complete.

For example, node A might offer node B an HTLC with a timeout of 3 days, and node B might
offer node C the same HTLC with a timeout of 2 days:

```
    3 days timeout        2 days timeout
A ------------------> B ------------------> C 
```

The difference in timeouts is called `cltv-expiry-delta` in 
[BOLT #7](07-routing-gossip.md).

This difference is important: after 2 days B can try to
remove the offer to C even if C is unresponsive, by broadcasting the
commitment transaction it has with C and spending the HTLC output.
Even though C might race to try to use its payment preimage at that point to
also spend the HTLC, it should be resolved well before the 3 day
deadline so B can either redeem the HTLC off A or close it.


If the timing is too close, there is a risk of "one-sided redemption",
where the payment preimage received from an offered HTLC is too late
to be used for an incoming HTLC, leaving the node with unexpected
liability.


Thus the effective timeout of the HTLC is the `cltv-expiry`, plus some
additional delay for the transaction which redeems the HTLC output to
be irreversibly committed to the blockchain.


Thus a node MUST estimate the deadline for successful redemption for
each HTLC it offers.  A node MUST NOT offer a HTLC after this
deadline, and MUST fail the channel if an HTLC which it offered is in
either node's current commitment transaction past this deadline.


### Adding an HTLC: `update_add_htlc`


Either node can send `update_add_htlc` to offer a HTLC to the other,
which is redeemable in return for a payment preimage.  Amounts are in
millisatoshi, though on-chain enforcement is only possible for whole
satoshi amounts greater than the dust limit: in commitment transactions these are rounded down as
specified in [BOLT #3](03-transactions.md).


The format of the `route` portion, which indicates where the payment
is destined, is described in [BOLT #4](04-onion-routing.md).


1. type: 128 (`update_add_htlc`)
2. data:
   * [32:channel-id]
   * [8:id]
   * [4:amount-msat]
   * [4:cltv-expiry]
   * [32:payment-hash]
   * [1254:onion-routing-packet]


#### Requirements

A sending node MUST NOT offer `amount-msat` it cannot pay for in the
remote commitment transaction at the current `fee-rate` (see "Updating
Fees") while maintaining its channel reserve, and MUST offer
`amount-msat` greater than 0, and MUST NOT offer `amount-msat` below
the receiving node's `htlc-minimum-msat`.

A sending node MUST NOT add an HTLC if it would result in it offering
more than the remote's `max-accepted-htlcs` HTLCs in the remote commitment
transaction, or if the sum of total offered HTLCs would exceed the remote's 
`max-htlc-value-in-flight-msat`.

A sending node MUST set `id` to 0 for the first HTLC it offers, and
increase the value by 1 for each successive offer.

A receiving node SHOULD fail the channel if it receives an
`amount-sat` equal to zero, below its own `htlc-minimum-msat`, or
which the sending node cannot afford at the current `fee-rate` while
maintaining its channel reserve.  A receiving node SHOULD fail the
channel if a sending node adds more than its `max-accepted-htlcs` HTLCs to
its local commitment transaction, or adds more than its `max-htlc-value-in-flight-msat` worth of offered HTLCs to its local commitment transaction.

A receiving node MUST allow multiple HTLCs with the same payment hash.

A receiving node MUST ignore a repeated `id` value after a
reconnection if it has the sender did not previously acknowledge the
commitment of that HTLC.  A receiving node MAY fail the channel if
other `id` violations occur.

The `onion-routing-packet` contains an obfuscated list of hops and instructions for each hop along the path.
It commits to the HTLC by setting the `payment-hash` as associated data, i.e., including the `payment-hash` in the computation of HMACs.
This prevents replay attacks that'd reuse a previous `onion-routing-packet` with a different `payment-hash`.

#### Rationale


Invalid amounts are a clear protocol violation and indicate a
breakdown.


If a node did not accept multiple HTLCs with the same payment hash, an
attacker could probe to see if a node had an existing HTLC.  This
requirement deal with duplicates leads us to using a separate
identifier; we assume a 64 bit counter never wraps.


Retransmissions of unacknowledged updates are explicitly allowed for
reconnection purposes; allowing them at other times simplifies the
recipient code, though strict checking may help debugging.

`max-accepted-htlcs` is limited to 483, to ensure that even if both
sides send the maximum number of HTLCs, the `commit_sig` message will
still be under the maximum message size.  It also ensures that
a single penalty transaction can spend the entire commitment transaction,
as calculated in [BOLT #5](05-onchain.md#penalty-transaction-weight-calculation).

### Removing an HTLC: `update_fulfill_htlc`, `update_fail_htlc` and `update_fail_malformed_htlc`

For simplicity, a node can only remove HTLCs added by the other node.
There are three reasons for removing an HTLC: it has timed out, it has
failed to route, or the payment preimage is supplied.

The `reason` field is an opaque encrypted blob for the benefit of the
original HTLC initiator as defined in [BOLT #4](04-onion-routing.md),
but there's a special malformed failure variant for the case where
our peer couldn't parse it; in this case the current node encrypts
it into a `update_fail_htlc` for relaying.

1. type: 130 (`update_fulfill_htlc`)
2. data:
   * [32:channel-id]
   * [8:id]
   * [32:payment-preimage]

For a timed out or route-failed HTLC:

1. type: 131 (`update_fail_htlc`)
2. data:
   * [32:channel-id]
   * [8:id]
   * [2:len]
   * [len:reason]

For a unparsable HTLC:

1. type: 135 (`update_fail_malformed_htlc`)
2. data:
   * [32:channel-id]
   * [8:id]
   * [32:sha256-of-onion]
   * [2:failure-code]

#### Requirements

A node SHOULD remove an HTLC as soon as it can; in particular, a node
SHOULD fail an HTLC which has timed out.

A node MUST NOT send `update_fulfill_htlc` until an HTLC is
irrevocably committed in both sides' commitment transactions.

A receiving node MUST check that `id` corresponds to an HTLC in its
current commitment transaction, and MUST fail the channel if it does
not.

A receiving node MUST check that the `payment-preimage` value in
`update-fulfill_htlc` SHA256 hashes to the corresponding HTLC
`payment-hash`, and MUST fail the channel if it does not.

A receiving node MUST fail the channel if the `BADONION` bit in
`failure-code` is not set for `update-fail-malformed-htlc`.

A receiving node MAY check the `sha256-of-onion` in
`update-fail-malformed-htlc` and MAY retry or choose an alternate
error response if it does not match the onion it sent.

Otherwise, a receiving node which has an outgoing HTLC canceled by
`update-fail-malformed-htlc` MUST return an error in the
`update-fail-htlc` sent to the link which originally sent the HTLC
using the `failure-code` given and setting the data to
`sha256-of-onion`.

#### Rationale

A node which doesn't time out HTLCs risks channel failure (see
"Risks With HTLC Timeouts").

A node which sends `update_fulfill_htlc` before the sender is also
committed to the HTLC risks losing funds.

If the onion is malformed, the upstream node won't be able to extract
a key to generate a response, hence the special failure message which
makes this node do it.

The node can check that the SHA256 the upstream is complaining about
does match the onion it sent, which may allow it to detect random bit
errors.  Without re-checking the actual encrypted packet sent, however,
it won't know whether the error was its own or on the remote side, so
such detection is left as an option.

### Committing Updates So Far: `commitment_signed`


When a node has changes for the remote commitment, it can apply them,
sign the resulting transaction as defined in [BOLT #3](03-transactions.md) and send a
`commitment_signed` message.


1. type: 132 (`commit_sig`)
2. data:
   * [32:channel-id]
   * [64:signature]
   * [2:num-htlcs]
   * [num-htlcs*64:htlc-signature]

#### Requirements


A node MUST NOT send a `commitment_signed` message which does not include any
updates.  Note that a node MAY send a `commitment_signed` message which only
alters the fee, and MAY send a `commitment_signed` message which doesn't
change the commitment transaction other than the new revocation hash
(due to dust, identical HTLC replacement, or insignificant or multiple
fee changes).  A node MUST include one `htlc-signature` for every HTLC
transaction corresponding to BIP69 lexicographic ordering of the commitment
transaction.


A receiving node MUST fail the channel if `signature` is not valid for
its local commitment transaction once all pending updates are applied.
A receiving node MUST fail the channel if `num-htlcs` is not equal to
the number of HTLC outputs in the local commitment transaction once all
pending updates are applied.  A receiving node MUST fail the channel if
any `htlc-signature` is not valid for the corresponding HTLC transaction.


A receiving node MUST respond with a `revoke_and_ack` message.


#### Rationale


There's little point offering spam updates; it implies a bug.


The `num-htlcs` field is redundant, but makes the packet length check fully self-contained.


### Completing the transition to the updated state: `revoke_and_ack`


Once the recipient of `commitment_signed` checks the signature, it knows that
it has a valid new commitment transaction, replies with the commitment
preimage for the previous commitment transaction in a `revoke_and_ack`
message.


This message also implicitly serves as an acknowledgement of receipt
of the `commitment_signed`, so it's a logical time for the `commitment_signed` sender
to apply to its own commitment, any pending updates it sent before
that `commitment_signed`.


The description of key derivation is in [BOLT #3](03-transactions.md#key-derivation).


1. type: 133 (`revoke_and_ack`)
2. data:
   * [32:channel-id]
   * [32:per-commitment-secret]
   * [33:next-per-commitment-point]

#### Requirements


A sending node MUST set `per-commitment-secret` to the secret used to generate keys for the
previous commitment transaction, MUST set `next-per-commitment-point` to the values for its next commitment transaction, and MUST set `padding` to all zeroes.

A receiving node MUST check that `per-commitment-secret` generates the previous `per-commitment-point`, and MUST fail if it does not. A receiving node MUST ignore the value of `padding`.  A receiving node MAY fail if the `per-commitment-secret` was not generated by the protocol in [BOLT #3](03-transactions.md#per-commitment-secret-requirements).

Nodes MUST NOT broadcast old (revoked) commitment transactions; doing
so will allow the other node to seize all the funds.  Nodes SHOULD NOT
sign commitment transactions unless it is about to broadcast them (due
to a failed connection), to reduce this risk.

### Updating Fees: `update_fee`

An `update_fee` message is sent by the node which is paying the
bitcoin fee.  Like any update, it is first committed to the receiver's
commitment transaction, then (once acknowledged) committed to the
sender's.  Unlike an HTLC, `update_fee` is never closed, simply
replaced.

There is a possibility of a race: the recipient can add new HTLCs
before it receives the `update_fee`, and the sender may not be able to
afford the fee on its own commitment transaction once the `update_fee`
is acknowledged by the recipient.  In this case, the fee will be less
than the fee rate, as described in [BOLT #3](03-transactions.md#fee-payment).

The exact calculation used for deriving the fee from the fee rate is
given in [BOLT #3](03-transactions.md#fee-calculation).


1. type: 134 (`update_fee`)
2. data:
   * [32:channel-id]
   * [4:feerate-per-kw]

#### Requirements

The node which is responsible for paying the bitcoin fee SHOULD send
`update_fee` to ensure the current fee rate is sufficient for
timely processing of the commitment transaction by a significant
margin.

The node which is not responsible for paying the bitcoin fee MUST NOT
send `update_fee`.

A receiving node SHOULD fail the channel if the `update_fee` is too
low for timely processing, or unreasonably large.

A receiving node MUST fail the channel if the sender is not
responsible for paying the bitcoin fee.

A receiving node SHOULD fail the channel if the sender cannot afford
the new fee rate on the receiving node's current commitment
transaction, but it MAY delay this check until the `update_fee` is
committed.

#### Rationale

Bitcoin fees are required for unilateral closes to be effective,
particularly since there is no general method for the node which
broadcasts it to use child-pays-for-parent to increase its effective
fee.

Given the variance in fees, and the fact that the transaction may be
spent in the future, it's a good idea for the fee payer to keep a good
margin, say 5x the expected fee requirement, but differing methods of
fee estimation mean we don't specify an exact value.

Since the fees are currently one-sided (the party which requested the
channel creation always pays the fees for the commitment transaction),
it is simplest to only allow them to set fee levels, but as the same
fee rate applies to HTLC transactions, the receiving node must also
care about the reasonableness of the fee.

## Message Retransmission

Because communication transports are unreliable and may need to be
re-established from time to time, the design of the transport has been
explicitly separated from the protocol.

Nonetheless, we assume that our transport is ordered and reliable;
reconnection introduces doubt as to what has been received, so we
retransmit any channel messages which may not have been.

This is fairly straightforward in the case of channel establishment
and close where messages have an explicit order, but in normal
operation acknowlegements of updates are delayed until the
`commitment_signed` / `revoke_and_ack` exchange, so we cannot assume
the updates have been received.  This also means that the receiving
node only needs to store updates upon receipt of `commitment_signed`.

Note that messages described in [BOLT #7](07-routing-gossip.md) are
independent of particular channels; their transmission requirements
are covered there, and other than being transmitted after `init` (like
any message), they are independent of requirements here.

### Requirements

A node MUST handle continuing a previous channel on a new encrypted
transport.  On disconnection, a node MAY forget nodes which have not
sent or received an `accept_channel` message, and MAY forget nodes
which have not sent `funding_locked` after a reasonable timeout.

On disconnection, a node MUST reverse any uncommitted updates sent by
the other side (ie. all messages beginning with `update_` for which no
`commitment_signed` has been received).  Note that a node MAY have
already use the `payment-preimage` value from the `update_fulfill_htlc`,
so the effects of `update_fulfill_htlc` is not completely reversed.

On reconnection, a node MUST retransmit old messages which may not
have been received, and MUST NOT retransmit old messages which have
been explicitly or implicitly acknowledged.  The following table
lists the acknowledgement conditions for each message:

* `open_channel`: acknowledged by `accept_channel`.
* `accept_channel`: acknowledged by `funding_created`.
* `funding_created`: acknowledged by `funding_signed`.
* `funding_signed`: acknowledged by `funding_locked`.
* `funding_locked`: acknowledged by `update_` messages, `commitment_signed`, `revoke_and_ack` or `shutdown` messages.
* `update_` messages: acknowledged by `revoke_and_ack`.
* `commitment_signed`: acknowledged by `revoke_and_ack`.
* `revoke_and_ack`: acknowledged by `shutdown`, `commitment_signed` or `closing_signed`
* `shutdown`: acknowledged by `closing_signed` or `revoke_and_ack`.

The last `closing_signed` (if any) must always be retransmitted, as there
is no explicit acknowledgement.

Before retransmitting `commitment_signed`, the node MUST send
appropriate `update_` messages (the other node will have forgotten
them, as required above).

A node MAY simply retransmit messages which are identical to the
previous transmission.  A node MUST not assume that
previously-transmitted messages were lost: in particular, if it has
sent a previous `commitment_signed` message, a node MUST handle the
case where the corresponding commitment transaction is broadcast by
the other side at any time.  This is particularly important if a node
does not simply retransmit the exact same `update_` messages as
previously sent.

A receiving node MAY ignore spurious message retransmission, or MAY
fail the channel if they occur.

# Authors

FIXME

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
