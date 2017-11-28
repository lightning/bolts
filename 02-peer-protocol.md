# BOLT #2: Peer Protocol for Channel Management

The peer channel protocol has three phases: establishment, normal
operation, and closing.

# Table of Contents
  * [Channel](#channel)
    * [Channel Establishment](#channel-establishment)
      * [The `open_channel` Message](#the-open_channel-message)
      * [The `accept_channel` Message](#the-accept_channel-message)
      * [The `funding_created` Message](#the-funding_created-message)
      * [The `funding_signed` Message](#the-funding_signed-message)
      * [The `funding_locked` Message](#the-funding_locked-message)
    * [Channel Close](#channel-close)
      * [Closing Initiation: `shutdown`](#closing-initiation-shutdown)
      * [Closing Negotiation: `closing_signed`](#closing-negotiation-closing_signed)
    * [Normal Operation](#normal-operation)
      * [Forwarding HTLCs](#forwarding-htlcs)
      * [`cltv_expiry_delta` Selection](#cltv_expiry_delta-selection)
      * [Adding an HTLC: `update_add_htlc`](#adding-an-htlc-update_add_htlc)
      * [Removing an HTLC: `update_fulfill_htlc`, `update_fail_htlc`, and `update_fail_malformed_htlc`](#removing-an-htlc-update_fulfill_htlc-update_fail_htlc-and-update_fail_malformed_htlc)
      * [Committing Updates So Far: `commitment_signed`](#committing-updates-so-far-commitment_signed)
      * [Completing the Transition to the Updated State: `revoke_and_ack`](#completing-the-transition-to-the-updated-state-revoke_and_ack)
      * [Updating Fees: `update_fee`](#updating-fees-update_fee)
    * [Message Retransmission](#message-retransmission)
  * [Authors](#authors)

# Channel

## Channel Establishment

Channel establishment begins immediately after authentication and
consists of the funding node (funder) sending an `open_channel` message,
followed by the responding node (fundee) sending `accept_channel`. With the
channel parameters locked in, the funder is able to create the funding
transaction and both versions of the commitment transaction, as described in
[BOLT #3](https://github.com/lightningnetwork/lightning-rfc/blob/master/03-transactions.md#bolt-3-bitcoin-transaction-and-script-formats).
The funder then sends the outpoint of the funding output with the `funding_created`
message, along with the signature for the fundee's version of the commitment
transaction. Once the fundee learns the funding outpoint, it's able to
generate the funder's commitment for the commitment transaction and send it
over using the `funding_signed` message.

Once the channel funder receives the `funding_signed` message, it
must broadcast the funding transaction to the Bitcoin network. After
the `funding_signed` message is sent/received, both sides should wait
for the funding transaction to enter the blockchain and reach the
specified depth (number of confirmations). After both sides have sent
the `funding_locked` message, the channel is established and can begin
normal operation. The `funding_locked` message includes information
that will be used to construct channel authentication proofs.


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

        - where node A is 'funder' and node B is 'fundee'

If this fails at any stage, or if one node decides the channel terms
offered by the other node are not suitable, the channel establishment
fails.

Note that multiple channels can operate in parallel, as all channel
messages are identified by either a `temporary_channel_id` (before the
funding transaction is created) or a `channel_id` (derived from the
funding transaction).

### The `open_channel` Message

This message contains information about a node and indicates its
desire to set up a new channel. This is the first step toward creating
the funding transaction and both versions of the commitment transaction.

1. type: 32 (`open_channel`)
2. data:
   * [`32`:`chain_hash`]
   * [`32`:`temporary_channel_id`]
   * [`8`:`funding_satoshis`]
   * [`8`:`push_msat`]
   * [`8`:`dust_limit_satoshis`]
   * [`8`:`max_htlc_value_in_flight_msat`]
   * [`8`:`channel_reserve_satoshis`]
   * [`8`:`htlc_minimum_msat`]
   * [`4`:`feerate_per_kw`]
   * [`2`:`to_self_delay`]
   * [`2`:`max_accepted_htlcs`]
   * [`33`:`funding_pubkey`]
   * [`33`:`revocation_basepoint`]
   * [`33`:`payment_basepoint`]
   * [`33`:`delayed_payment_basepoint`]
   * [`33`:`htlc_basepoint`]
   * [`33`:`first_per_commitment_point`]
   * [`1`:`channel_flags`]
   * [`2`:`shutdown_len`] (`option_upfront_shutdown_script`)
   * [`shutdown_len`: `shutdown_scriptpubkey`] (`option_upfront_shutdown_script`)


The `chain_hash` value denotes the exact blockchain that the opened channel will
reside within. This is usually the genesis hash of the respective blockchain.
The existence of the `chain_hash` allows nodes to open channels
across many distinct blockchains as well as have channels within multiple
blockchains opened to the same peer (if it supports the target chains).

The `temporary_channel_id` is used to identify this channel until the
funding transaction is established. 

`funding_satoshis` is the amount the sender is putting into the
channel. `push_msat` is an amount of initial funds that the sender is
unconditionally giving to the receiver. `dust_limit_satoshis` is the
threshold below which outputs should not be generated for this node's
commitment or HTLC transactions (i.e. HTLCs below this amount plus
HTLC transaction fees are not enforceable on-chain). This reflects the
reality that tiny outputs are not considered standard transactions and
will not propagate through the Bitcoin network. `channel_reserve_satoshis` 
is the minimum amount that the other node is to keep as a direct
payment. `htlc_minimum_msat` indicates the smallest value HTLC this
node will accept.

`max_htlc_value_in_flight_msat` is a cap on total value of outstanding
HTLCs, which allows a node to limit its exposure to HTLCs; similarly,
`max_accepted_htlcs` limits the number of outstanding HTLCs the other
node can offer. 

`feerate_per_kw` indicates the initial fee rate by 1000-weight
(i.e. 1/4 the more normally-used 'feerate per kilobyte') that this
side will pay for commitment and HTLC transactions, as described in
[BOLT #3](03-transactions.md#fee-calculation) (this can be adjusted
later with an `update_fee` message). 

`to_self_delay` is the number of blocks that the other nodes to-self
outputs must be delayed, using `OP_CHECKSEQUENCEVERIFY` delays; this
is how long it will have to wait in case of breakdown before redeeming
its own funds.

`funding_pubkey` is the public key in the 2-of-2 multisig script of
the funding transaction output.

The various `_basepoint` fields are used to [derive unique
keys](03-transactions.md#key-derivation) for each commitment
transaction. Varying these keys ensures that the transaction ID of
each commitment transaction is unpredictable to an external observer,
even if one commitment transaction is seen; this property is very
useful for preserving privacy when outsourcing penalty transactions to
third parties.

`first_per_commitment_point` is the per-commitment point to be used
for the first commitment transaction,

Only the least-significant bit of `channel_flags` is currently
defined: `announce_channel`. This indicates whether the initiator of
the funding flow wishes to advertise this channel publicly to the
network as detailed within [BOLT
#7](https://github.com/lightningnetwork/lightning-rfc/blob/master/07-routing-gossip.md#bolt-7-p2p-node-and-channel-discovery).

The `shutdown_scriptpubkey` allows the sending node to commit to where
funds will go on mutual close, which the remote node should enforce
even if a node is compromised later.

[ FIXME: Describe dangerous feature bit for larger channel amounts. ]

#### Requirements

The sending node:
  - MUST ensure that the `chain_hash` value identifies the chain it wishes to open the channel within.
  - MUST ensure `temporary_channel_id` is unique from any other channel ID with the same peer.
  - MUST set `funding_satoshis` to less than 2^24 satoshi.
  - MUST set `push_msat` to equal or less than 1000 * `funding_satoshis`.
  - MUST set `funding_pubkey`, `revocation_basepoint`, `htlc_basepoint`, `payment_basepoint`, and `delayed_payment_basepoint` to valid DER-encoded, compressed, secp256k1 pubkeys.
  - MUST set `first_per_commitment_point` to the per-commitment point to be used for the initial commitment transaction, derived as specified in [BOLT #3](03-transactions.md#per-commitment-secret-requirements).
  - MUST set undefined bits in `channel_flags` to 0.
  - if both nodes advertised the `option_upfront_shutdown_script` feature:
  - MUST include either a valid `shutdown_scriptpubkey` as required by `shutdown` `scriptpubkey`, or a zero-length `shutdown_scriptpubkey`.
  - otherwise:
  - MAY include a`shutdown_scriptpubkey`.

The sending node SHOULD:
  - set `to_self_delay` sufficient to ensure the sender can irreversibly spend a commitment transaction output, in case of misbehavior by the receiver.
  - set `feerate_per_kw` to at least the rate it estimates would cause the transaction to be immediately included in a block.
  - set `dust_limit_satoshis` to a sufficient value to allow commitment transactions to propagate through the Bitcoin network.
  - set `htlc_minimum_msat` to the minimum value HTLC it is willing to accept from this peer.

The receiving node MUST:
  - ignore undefined bits in `channel_flags`.
  - if the connection has been re-established after receiving a previous
 `open_channel` but before receiving a `funding_created` message:
    - accept a new `open_channel` message.
    - discard the previous `open_channel` message.

The receiving node MAY fail the channel if:
  - `announce_channel` is `false` (`0`), yet it wishes to publicly announce the channel.
  - `funding_satoshis` is too small.
  - it considers `htlc_minimum_msat` too large.
  - it considers `max_htlc_value_in_flight_msat` too small.
  - it considers `channel_reserve_satoshis` too large.
  - it considers `max_accepted_htlcs` too small.

The receiving node MUST fail the channel if:
  - `push_msat` is greater than `funding_satoshis` * 1000.
  - `to_self_delay` is unreasonably large.
  - `max_accepted_htlcs` is greater than 483.
  - it considers `feerate_per_kw` too small for timely processing, or unreasonably large.
  - `funding_pubkey`, `revocation_basepoint`, `htlc_basepoint`, `payment_basepoint`, or `delayed_payment_basepoint`
are not valid DER-encoded compressed secp256k1 pubkeys.

The receiving node MUST NOT:
  - consider funds received using `push_msat` to be received until the funding transaction has reached sufficient depth.

#### Rationale

The *channel reserve* is specified by the peer's `channel_reserve_satoshis`: 1% of the channel total is suggested. Each side of a channel maintains this reserve so it always has something to lose if it were to try to broadcast an old, revoked commitment transaction. Initially, this reserve may not be met, as only one side has funds; but the protocol ensures that there is always progress toward meeting this reserve, and once met, it is maintained.

The sender can unconditionally give initial funds to the receiver using a non-zero `push_msat` — this is one case where the normal reserve mechanism doesn't apply. However, like any other on-chain transaction, this payment is not certain until the funding transaction has been confirmed sufficiently (with a danger of double-spend until that occurs) and may require a separate method to prove payment via on-chain confirmation.

The `feerate_per_kw` is generally only a concern to the sender (who pays the fees), but there is also the feerate paid by HTLC transactions; thus, unreasonably large fee rates can also penalize the recipient.

Separating the `htlc_basepoint` from the `payment_basepoint` improves security: a node needs the secret associated with the `htlc_basepoint` to produce HTLC signatures for the protocol, but the secret for the `payment_basepoint` can be in cold storage.

#### Future

It would be easy to have a local feature bit which indicated that a
receiving node was prepared to fund a channel, which would reverse this
protocol.

### The `accept_channel` Message

This message contains information about a node and indicates its
acceptance of the new channel. This is the second step toward creating the
funding transaction and both versions of the commitment transaction.

1. type: 33 (`accept_channel`)
2. data:
   * [`32`:`temporary_channel_id`]
   * [`8`:`dust_limit_satoshis`]
   * [`8`:`max_htlc_value_in_flight_msat`]
   * [`8`:`channel_reserve_satoshis`]
   * [`8`:`htlc_minimum_msat`]
   * [`4`:`minimum_depth`]
   * [`2`:`to_self_delay`]
   * [`2`:`max_accepted_htlcs`]
   * [`33`:`funding_pubkey`]
   * [`33`:`revocation_basepoint`]
   * [`33`:`payment_basepoint`]
   * [`33`:`delayed_payment_basepoint`]
   * [`33`:`htlc_basepoint`]
   * [`33`:`first_per_commitment_point`]
   * [`2`:`shutdown_len`] (`option_upfront_shutdown_script`)
   * [`shutdown_len`: `shutdown_scriptpubkey`] (`option_upfront_shutdown_script`)

#### Requirements

The `temporary_channel_id` MUST be the same as the `temporary_channel_id` in
the `open_channel` message.

The sender:
  - SHOULD set `minimum_depth` to a number of blocks it considers reasonable to
avoid double-spending of the funding transaction.

The receiver:
  - if the `chain_hash` value within the `open_channel` message is set to a hash
 of a chain unknown to the receiver:
    - MUST reject the channel.
  - if `minimum_depth` is unreasonably large:
    - MAY reject the channel.

Other fields have the same requirements as their counterparts in `open_channel`.

### The `funding_created` Message

This message describes the outpoint which the funder has created for
the initial commitment transactions. After receiving the peer's
signature via `funding_signed`, it will broadcast the funding transaction.

1. type: 34 (`funding_created`)
2. data:
    * [`32`:`temporary_channel_id`]
    * [`32`:`funding_txid`]
    * [`2`:`funding_output_index`]
    * [`64`:`signature`]

#### Requirements

The sender MUST set:
  - `temporary_channel_id` the same as the `temporary_channel_id` in the `open_channel` message.
  - `funding_txid` to the transaction ID of a non-malleable transaction, which it MUST NOT broadcast.
  - `funding_output_index` to the output number of that transaction that corresponds the funding transaction output as defined in [BOLT #3](03-transactions.md#funding-transaction-output).
  - `signature` to the valid signature using its `funding_pubkey` for the initial commitment transaction, as defined in [BOLT #3](03-transactions.md#commitment-transaction).

The sender:
  - when creating the funding transaction:
    - SHOULD use only BIP141 (Segregated Witness) inputs.

The recipient:
  - if `signature` is incorrect:
    - MUST fail the channel.

#### Rationale

The `funding_output_index` can only be 2 bytes, since that's how it's packed into the `channel_id` and used throughout the gossip protocol. The limit of 65535 outputs should not be overly burdensome.

A transaction with all Segregated Witness inputs is not malleable, hence the funding transaction recommendation.

### The `funding_signed` Message

This message gives the funder the signature it needs for the first
commitment transaction, so it can broadcast the signature knowing that funds
can be redeemed, if need be.

This message introduces the `channel_id` to identify the channel. It's derived from the funding transaction by combining the `funding_txid` and the `funding_output_index`, using big-endian exclusive-OR (i.e. `funding_output_index` alters the last 2 bytes).

1. type: 35 (`funding_signed`)
2. data:
    * [`32`:`channel_id`]
    * [`64`:`signature`]

#### Requirements

The sender MUST set:
  - `channel_id` by exclusive-OR of the `funding_txid` and the `funding_output_index` from the `funding_created` message.
  - `signature` to the valid signature, using its `funding_pubkey` for the initial commitment transaction, as defined in [BOLT #3](03-transactions.md#commitment-transaction).

The recipient:
  - if `signature` is incorrect:
    - MUST fail the channel.
  - MUST NOT broadcast the funding transaction before receipt of a valid `funding_signed`.
  - on receipt of a valid `funding_signed`:
    - SHOULD broadcast the funding transaction.

### The `funding_locked` Message

This message indicates that the funding transaction has reached the `minimum_depth` asked for in `accept_channel`. Once both nodes have sent this, the channel enters normal operating mode.

1. type: 36 (`funding_locked`)
2. data:
    * [`32`:`channel_id`]
    * [`33`:`next_per_commitment_point`]

#### Requirements

The sender MUST:
  - wait until the funding transaction has reached
`minimum_depth` before sending this message.
  - set `next_per_commitment_point` to the
per-commitment point to be used for the following commitment
transaction, derived as specified in
[BOLT #3](03-transactions.md#per-commitment-secret-requirements).

A non-funding node (fundee) SHOULD:
  - forget the channel if it does not see the
funding transaction after a reasonable timeout.

From the point of waiting for `funding_locked` onward, either node MAY
fail the channel if it does not receive a required response from the
other node after a reasonable timeout.

#### Rationale

The non-funder can simply forget the channel ever existed, since no
funds are at risk. If the fundee were to remember the channel forever, that would create a Denial of Service risk; therefore, forgetting it is recommended (even if the promise of `push_msat` is significant).

#### Future

An SPV proof could be added and block hashes could be routed in separate
messages.

## Channel Close

Nodes can negotiate a mutual close of the connection, which unlike a
unilateral close, allows them to access their funds immediately and
can be negotiated with lower fees.

Closing happens in two stages: 1) one side indicates it wants to clear the channel
(and thus will accept no new HTLCs) 2) once all HTLCs are resolved, the final channel close
negotiation begins.

        +-------+                              +-------+
        |       |--(1)-----  shutdown  ------->|       |
        |       |<-(2)-----  shutdown  --------|       |
        |       |                              |       |
        |       | <complete all pending HTLCs> |       |
        |   A   |                 ...          |   B   |
        |       |                              |       |
        |       |<-(3)-- closing_signed  F1----|       |
        |       |--(4)-- closing_signed  F2--->|       |
        |       |              ...             |       |
        |       |--(?)-- closing_signed  Fn--->|       |
        |       |<-(?)-- closing_signed  Fn----|       |
        +-------+                              +-------+


### Closing Initiation: `shutdown`

Either node (or both) can send a `shutdown` message to initiate closing,
along with the scriptpubkey it wants to be paid to.


1. type: 38 (`shutdown`)
2. data:
   * [`32`:`channel_id`]
   * [`2`:`len`]
   * [`len`:`scriptpubkey`]

#### Requirements

A sending node:
  - if there are updates pending on the receiving node's commitment transaction:
    - MUST NOT send a `shutdown`.
  - MUST NOT send an `update_add_htlc` after a `shutdown`.
  - SHOULD fail to route any HTLC added after it sent `shutdown`.
  - if it sent a non-zero-length `shutdown_scriptpubkey` in `open_channel` or `accept_channel`:
    - MUST send the same value in `scriptpubkey`.
  - MUST set `scriptpubkey` in one of the following forms:

    1. `OP_DUP` `OP_HASH160` `20` 20-bytes `OP_EQUALVERIFY` `OP_CHECKSIG`
   (pay to pubkey hash), OR
    2. `OP_HASH160` `20` 20-bytes `OP_EQUAL` (pay to script hash), OR
    3. `OP_0` `20` 20-bytes (version 0 pay to witness pubkey), OR
    4. `OP_0` `32` 32-bytes (version 0 pay to witness script hash)

A receiving node:
  - if the `scriptpubkey` is not in one of the above forms:
    - SHOULD fail the connection.
  - once there are no outstanding updates on the peer:
    - MUST reply to a `shutdown` message with a `shutdown`, unless it has already sent a `shutdown`.
  - if both nodes advertised the `option_upfront_shutdown_script` feature, and the receiving node received a non-zero-length `shutdown_scriptpubkey` in `open_channel` or `accept_channel`, and that `shutdown_scriptpubkey` is not equal to `scriptpubkey`:
    - MUST fail the connection.

#### Rationale

If channel state is always "clean" (no pending changes) when a
shutdown starts, the question of how to behave if it wasn't is avoided:
the sender always sends a `commitment_signed` first.

As shutdown implies a desire to terminate, it implies that no new
HTLCs will be added or accepted.

The `scriptpubkey` forms include only standard forms accepted by the
Bitcoin network, which ensures the resulting transaction will
propagate to miners.

The `option_upfront_shutdown_script` feature means that the node
wanted to pre-commit to `shutdown_scriptpubkey` in case it was
compromised somehow.  This is a weak commitment (a malevolent
implementation tends to ignore specifications like this one!), but it
provides an incremental improvement in security by requiring the cooperation
of the receiving node to change the `scriptpubkey`.

The `shutdown` response requirement implies that the node sends `commitment_signed` to commit any outstanding changes before replying; however, it could theoretically reconnect instead, which would simply erase all outstanding uncommitted changes.

### Closing Negotiation: `closing_signed`

Once shutdown is complete and the channel is empty of HTLCs, the final
current commitment transactions will have no HTLCs, and closing fee
negotiation begins. Each node chooses a fee it thinks is fair, and
signs the close transaction with the `scriptpubkey` fields from the
`shutdown` messages (along with its chosen fee) and sends the signature. The
process terminates when both agree on the same fee, or one side fails
the channel.

1. type: 39 (`closing_signed`)
2. data:
   * [`32`:`channel_id`]
   * [`8`:`fee_satoshis`]
   * [`64`:`signature`]

#### Requirements

A sending node:
  - after `shutdown` has been received and no HTLCs remain in either commitment transaction:
    - SHOULD send a `closing_signed` message.
  - MUST set `fee_satoshis` lower than or equal to the
 base fee of the final commitment transaction, as calculated in [BOLT #3](03-transactions.md#fee-calculation).
  - SHOULD set the initial `fee_satoshis` according to its
 estimate of cost of inclusion in a block.
  - MUST set `signature` to the Bitcoin signature of the close
 transaction, as specified in [BOLT #3](03-transactions.md#closing-transaction).

The receiving node:
  - after `shutdown` has been received and no HTLCs remain in either commitment transaction:
    - SHOULD send a `closing_signed` message.
  - if the `signature` is not valid for either variant of close transaction
  specified in [BOLT #3](03-transactions.md#closing-transaction):
    - MUST fail the connection.
  - if `fee_satoshis` is equal to its previously sent `fee_satoshis`:
    - SHOULD sign and broadcast the final closing transaction
    - MAY close the connection.
  - otherwise:
    - MUST fail the connection if `fee_satoshis` is greater than
the base fee of the final commitment transaction as calculated in
[BOLT #3](03-transactions.md#fee-calculation)
  - SHOULD fail the connection if `fee_satoshis` is not strictly
between its last-sent `fee_satoshis` and its previously-received
`fee_satoshis`, unless it has reconnected since then.
  - if the receiver agrees with the fee:
    - SHOULD reply with a `closing_signed` with the same `fee_satoshis` value.
  - otherwise:
    - MUST propose a value "strictly between" the received `fee_satoshis`
  and its previously-sent `fee_satoshis`.

#### Rationale

The "strictly between" requirement ensures that forward
progress is made, even if only by a single satoshi at a time. To avoid
keeping state and to handle the corner case, where fees have shifted
between disconnection and reconnection, negotiation restarts on reconnection.

Note there is limited risk if the closing transaction is
delayed, but it will be broadcast very soon; so there is usually no
reason to pay a premium for rapid processing.

## Normal Operation

Once both nodes have exchanged `funding_locked` (and optionally [`announcement_signatures`](https://github.com/lightningnetwork/lightning-rfc/blob/master/07-routing-gossip.md#the-announcement_signatures-message)), the channel can be used to make payments via Hash TimeLocked Contracts.

Changes are sent in batches: one or more `update_` messages are sent before a
`commitment_signed` message, as in the following diagram:

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


Counter-intuitively, these updates apply to the *other node's*
commitment transaction; the node only adds those updates to its own
commitment transaction when the remote node acknowledges it has
applied them via `revoke_and_ack`.

Thus each update traverses through the following states:

1. Pending on the receiver
2. In the receiver's latest commitment transaction,
3. ... and the receiver's previous commitment transaction has been revoked,
   and the HTLC is pending on the sender.
4. ... and in the sender's latest commitment transaction,
5. ... and the sender's previous commitment transaction has been revoked.


As the two nodes' updates are independent, the two commitment
transactions may be out of sync indefinitely. This is not concerning:
what matters is whether both sides have irrevocably committed to a
particular HTLC or not (the final state, above).

### Forwarding HTLCs

In general, a node offers HTLCs for two reasons: to initiate a payment of its own,
or to forward another node's payment. In the forwarding case, care must
be taken to ensure the *outgoing* HTLC cannot be redeemed unless the *incoming*
HTLC can be redeemed. The following requirements ensure this is always true:

The respective **addition/removal** of an HTLC is considered *irrevocably committed* when:

1. the commitment transaction **with/without** it is committed by both nodes, and any
previous commitment transaction **without/with** it has been revoked, OR
2. the commitment transaction **with/without** it has been irreversibly committed to
the blockchain.

#### Requirements

A node:
  - until the incoming HTLC has been irrevocably committed:
    - MUST NOT offer an HTLC (`update_add_htlc`) in response to an incoming HTLC.
  - until the removal of the outgoing HTLC is irrevocably committed, OR until the outgoing on-chain HTLC output has been spent via the HTLC-timeout transaction (with sufficient depth):
    - MUST NOT fail an incoming HTLC (`update_fail_htlc`) for which it has committed
to an outgoing HTLC.
  - once its `cltv_expiry` has been reached, OR if `cltv_expiry` - `current_height` < `cltv_expiry_delta` for the outgoing channel:
    - MUST fail an incoming HTLC (`update_fail_htlc`).
  - if an incoming HTLC's `cltv_expiry` is unreasonably far in the future:
    - SHOULD fail that incoming HTLC (`update_fail_htlc`).
  - upon receiving an `update_fulfill_htlc` for the outgoing HTLC, OR upon discovering the `payment_preimage` from an on-chain HTLC spend:
    - MUST fulfill an incoming HTLC for which it has committed to an outgoing HTLC.

#### Rationale

In general, one side of the exchange needs to be dealt with before the other.
Fulfilling an HTLC is different: knowledge of the preimage is, by definition,
irrevocable and the incoming HTLC should be fulfilled as soon as possible to
reduce latency.

An HTLC with an unreasonably long expiry is a denial-of-service vector and
therefore is not allowed. Note that the exact value of "unreasonable" is currently unclear
and may depend on network topology.

### `cltv_expiry_delta` Selection

Once an HTLC has timed out, it can either be fulfilled or timed-out;
care must be taken around this transition both for offered and received HTLCs.

Consider the following scenario, where A sends an HTLC to B, who
forwards to C, who delivers the goods as soon as the payment is
received.

1.  C needs to be sure that the HTLC from B cannot time out, even if B becomes
    unresponsive; i.e. C can fulfill the incoming HTLC on-chain before B can
    time it out on-chain.

2.  B needs to be sure that if C fulfills the HTLC from B, it can fulfill the
    incoming HTLC from A; i.e. B can get the preimage from C and fulfill the incoming
    HTLC on-chain before A can time it out on-chain.

The critical settings here are the `cltv_expiry_delta` in
[BOLT #7](07-routing-gossip.md#the-channel_update-message) and the
related
[`min_final_cltv_expiry` in BOLT #11](11-payment-encoding.md#tagged-fields).
`cltv_expiry_delta` is the minimum difference in HTLC CLTV timeouts, in
the forwarding case (B). `min_final_ctlv_expiry` is the minimum difference
between HTLC CLTV timeout and the current block height, for the
terminal case (C).

Note that if this value is too low for a channel, the risk is only to
the node *accepting* the HTLC, not the node offering it. For this
reason, the `cltv_expiry_delta` for the *outgoing* channel is used as
the delta across a node.

The worst-case number of blocks between outgoing and
incoming HTLC resolution can be derived, given a few assumptions:

* A worst-case reorganization depth `R` blocks.
* A grace-period `G` blocks after HTLC timeout before giving up on
  an unresponsive peer and dropping to chain.
* A number of blocks `S` between transaction broadcast and the
  transaction being included in a block.

The worst case is for a forwarding node (B) that takes the longest
possible time to spot the outgoing HTLC fulfillment and also takes
the longest possible time to redeem it on-chain:

1. The B->C HTLC times out at block `N`, and B waits `G` blocks until
   it gives up waiting for C. B or C commits to the blockchain,
   and B spends HTLC, which takes `S` blocks to be included.
2. Bad case: C wins the race (just) and fulfills the HTLC, B only sees
   that transaction when it sees block `N+G+S+1`.
3. Worst case: There's reorganization `R` deep in which C wins and
   fulfills. B only sees transaction at `N+G+S+R`.
4. B now needs to fulfill the incoming A->B HTLC, but A is unresponsive: B waits `G` more
   blocks before giving up waiting for A. A or B commits to the blockchain.
5. Bad case: B sees A's commitment transaction in block `N+G+S+R+G+1` and has
   to spend the HTLC output, which takes `S` blocks to be mined.
6. Worst case: there's another reorganization `R` deep which A uses to
   spend the commitment transaction, so B sees A's commitment
   transaction in block `N+G+S+R+G+R` and has to spend the HTLC output, which
   takes `S` blocks to be mined.
7. B's HTLC spend needs to be at least `R` deep before it times out,
   otherwise another reorganization could allow A to timeout the
   transaction.

Thus, the worst case is `3R+2G+2S` assuming `R` is at least 1. Note that the
chances of three reorganizations in which the other node wins all of them is
low for `R` of 2 or more. Since high fees are used (and HTLC spends can use
almost arbitrary fees), `S` should be small; although, given that block times are
irregular and empty blocks still occur, `S = 2` should be considered a
minimum. Similarly, the grace period `G` can be low (1 or 2), as nodes are
required to timeout or fulfill as soon as possible; but if `G` is too low it increases the
risk of unnecessary channel closure due to networking delays.

There are four values that need be derived:

1. The `cltv_expiry_delta` for channels, `3R+2G+2S`: if in doubt, a
   `cltv_expiry_delta` of 12 is reasonable (R=2, G=1, S=2).

2. The `cltv_expiry_delta` for sent HTLCs: the timeout deadline after which the channel has to be failed
   and timed out on-chain. This is `G` blocks after the HTLC's
   `cltv_expiry`: 1 block is reasonable.

3. The `cltv_expiry_delta` for received HTLCs (with a preimage): the fulfillment deadline after which
the channel has to be failed and the HTLC fulfilled on-chain before its
   `cltv_expiry`. See steps 4-7 above, which imply a deadline of `2R+G+S`
   blocks before `cltv_expiry`: 7 blocks is reasonable.

4. The minimum `cltv_expiry` accepted for terminal payments: the
   worst case for the terminal node C is `2R+G+S` blocks (as, again, steps
   1-3 above don't apply). The default in
   [BOLT #11](11-payment-encoding.md) is 9, which is slightly more
   conservative than the 7 that this calculation suggests.

#### Requirements

An offering node:
  - MUST estimate a timeout deadline for each HTLC it offers.
  - MUST NOT offer an HTLC with a timeout deadline before its `cltv_expiry`.
  - if an HTLC which it offered is in either node's current
  commitment transaction is past this timeout deadline:
    - MUST fail the channel.

A fulfilling node:
  - for each HTLC it is attempting to fulfill:
    - MUST estimate a fulfillment deadline.
  - MUST fail (and not forward) an HTLC whose fulfillment deadline is already past.
  - if a HTLC it has fulfilled is in either node's current commitment
  transaction and is past this fulfillment deadline:
    - MUST fail the connection.

### Adding an HTLC: `update_add_htlc`

Either node can send `update_add_htlc` to offer a HTLC to the other,
which is redeemable in return for a payment preimage. Amounts are in
millisatoshi, though on-chain enforcement is only possible for whole
satoshi amounts greater than the dust limit (in commitment transactions these are rounded down as
specified in [BOLT #3](03-transactions.md)).

The format of the `onion_routing_packet` portion, which indicates where the payment
is destined, is described in [BOLT #4](04-onion-routing.md).

1. type: 128 (`update_add_htlc`)
2. data:
   * [`32`:`channel_id`]
   * [`8`:`id`]
   * [`8`:`amount_msat`]
   * [`32`:`payment_hash`]
   * [`4`:`cltv_expiry`]
   * [`1366`:`onion_routing_packet`]

#### Requirements

A sending node:
  - MUST NOT offer `amount_msat` it cannot pay for in the
remote commitment transaction at the current `feerate_per_kw` (see "Updating
Fees") while maintaining its channel reserve.
  - MUST offer `amount_msat` greater than 0.
  - MUST NOT offer `amount_msat` below the receiving node's `htlc_minimum_msat`
  - MUST set `cltv_expiry` less than 500000000.
  - for channels with `chain_hash` identifying the Bitcoin blockchain:
    - MUST set the four most significant bytes of `amount_msat` to 0.
  - if result would be offering more than the remote's
  `max_accepted_htlcs` HTLCs, in the remote commitment transaction:
    - MUST NOT add an HTLC.
  - if the sum of total offered HTLCs would exceed the remote's
`max_htlc_value_in_flight_msat`:
    - MUST NOT add an HTLC.
  - for the first HTLC it offers:
    - MUST set `id` to 0.
  - MUST increase the value of `id` by 1 for each successive offer.

A receiving node:
  - receiving an `amount_msat` equal to 0, OR less than its own `htlc_minimum_msat`:
    - SHOULD fail the channel.
  - receiving an `amount_msat` that the sending node cannot afford at the current `feerate_per_kw` (while maintaining its channel reserve):
    - SHOULD fail the channel.
  - if a sending node adds more than its `max_accepted_htlcs` HTLCs to
    its local commitment transaction, OR adds more than its `max_htlc_value_in_flight_msat` worth of offered HTLCs to its local commitment transaction:
    - SHOULD fail the channel.
  - if sending node sets `cltv_expiry` to greater or equal to 500000000:
    - SHOULD fail the channel.
  - for channels with `chain_hash` identifying the Bitcoin blockchain, if the four most significant bytes of `amount_msat` are not 0:
    - MUST fail the channel.
  - MUST allow multiple HTLCs with the same `payment_hash`.
  - if the sender did not previously acknowledge the commitment of that HTLC:
    - MUST ignore a repeated `id` value after a reconnection.
  - if other `id` violations occur:
    - MAY fail the channel.

The `onion_routing_packet` contains an obfuscated list of hops and instructions for each hop along the path.
It commits to the HTLC by setting the `payment_hash` as associated data, i.e. includes the `payment_hash` in the computation of HMACs.
This prevents replay attacks that would reuse a previous `onion_routing_packet` with a different `payment_hash`.

#### Rationale

Invalid amounts are a clear protocol violation and indicate a breakdown.

If a node did not accept multiple HTLCs with the same payment hash, an
attacker could probe to see if a node had an existing HTLC. This
requirement, to deal with duplicates, leads us to use a separate
identifier; its assumed a 64-bit counter never wraps.

Retransmissions of unacknowledged updates are explicitly allowed for
reconnection purposes; allowing them at other times simplifies the
recipient code (though strict checking may help debugging).

`max_accepted_htlcs` is limited to 483 to ensure that, even if both
sides send the maximum number of HTLCs, the `commitment_signed` message will
still be under the maximum message size. It also ensures that
a single penalty transaction can spend the entire commitment transaction,
as calculated in [BOLT #5](05-onchain.md#penalty-transaction-weight-calculation).

`cltv_expiry` values equal to or greater than 500000000 would indicate a time in
seconds, and the protocol only supports an expiry in blocks.

`amount_msat` is deliberately limited for this version of the
specification; larger amounts are not necessary, nor wise, during the
bootstrap phase of the network.

### Removing an HTLC: `update_fulfill_htlc`, `update_fail_htlc`, and `update_fail_malformed_htlc`

For simplicity, a node can only remove HTLCs added by the other node.
There are four reasons for removing an HTLC: the payment preimage is supplied,
it has timed out, it has failed to route, or it is malformed.

To supply the preimage:

1. type: 130 (`update_fulfill_htlc`)
2. data:
   * [`32`:`channel_id`]
   * [`8`:`id`]
   * [`32`:`payment_preimage`]

For a timed out or route-failed HTLC:

1. type: 131 (`update_fail_htlc`)
2. data:
   * [`32`:`channel_id`]
   * [`8`:`id`]
   * [`2`:`len`]
   * [`len`:`reason`]

The `reason` field is an opaque encrypted blob for the benefit of the
original HTLC initiator as defined in [BOLT #4](04-onion-routing.md);
however, there's a special malformed failure variant for the case where
our peer couldn't parse it: in this case the current node instead take action, encrypting
it into a `update_fail_htlc` for relaying.

For an unparsable HTLC:

1. type: 135 (`update_fail_malformed_htlc`)
2. data:
   * [`32`:`channel_id`]
   * [`8`:`id`]
   * [`32`:`sha256_of_onion`]
   * [`2`:`failure_code`]

#### Requirements

A node:
  - SHOULD remove an HTLC as soon as it can.
  - SHOULD fail an HTLC which has timed out.
  - until the corresponding HTLC is irrevocably committed in both sides'
  commitment transactions:
    - MUST NOT send an `update_fulfill_htlc`, `update_fail_htlc`, or
`update_fail_malformed_htlc`.

A receiving node:
  - if the `id` does not correspond to an HTLC in its current commitment transaction:
    - MUST fail the channel.
  - if the `payment_preimage` value in `update_fulfill_htlc`
  doesn't SHA256 hash to the corresponding HTLC `payment_hash`:
    - MUST fail the channel.
  - if the `BADONION` bit in `failure_code` is not set for
  `update_fail_malformed_htlc`:
    - MUST fail the channel.
  - if the `sha256_of_onion` in `update_fail_malformed_htlc` doesn't match the
  onion it sent:
    - MAY retry or choose an alternate error response.
  - otherwise, a receiving node which has an outgoing HTLC canceled by `update_fail_malformed_htlc`:
    - MUST return an error in the `update_fail_htlc` sent to the link which
      originally sent the HTLC, using the `failure_code` given and setting the
      data to `sha256_of_onion`.

#### Rationale

A node that doesn't time out HTLCs risks channel failure (see
[`cltv_expiry_delta` Selection](#cltv_expiry_delta-selection)).

A node that sends `update_fulfill_htlc`, before the sender, is also
committed to the HTLC and risks losing funds.

If the onion is malformed, the upstream node won't be able to extract
a key to generate a response — hence the special failure message, which
makes this node do it.

The node can check that the SHA256 that the upstream is complaining about
does match the onion it sent, which may allow it to detect random bit
errors. However, without re-checking the actual encrypted packet sent,
it won't know whether the error was its own or the remote's; so
such detection is left as an option.

### Committing Updates So Far: `commitment_signed`

When a node has changes for the remote commitment, it can apply them,
sign the resulting transaction (as defined in [BOLT #3](03-transactions.md)), and send a
`commitment_signed` message.

1. type: 132 (`commitment_signed`)
2. data:
   * [`32`:`channel_id`]
   * [`64`:`signature`]
   * [`2`:`num_htlcs`]
   * [`num_htlcs*64`:`htlc_signature`]

#### Requirements

A sending node:
  - MUST NOT send a `commitment_signed` message that does not include any
updates.
  - MAY send a `commitment_signed` message that only
alters the fee.
  - MAY send a `commitment_signed` message that doesn't
change the commitment transaction aside from the new revocation hash
(due to dust, identical HTLC replacement, or insignificant or multiple
fee changes).
  - MUST include one `htlc_signature` for every HTLC transaction corresponding
  to BIP69 lexicographic ordering of the commitment transaction.

A receiving node:
  - if `signature` is not valid for its local commitment transaction once all
  pending updates are applied:
    - MUST fail the channel.
  - if `num_htlcs` is not equal to the number of HTLC outputs in the local
  commitment transaction once all pending updates are applied:
    - MUST fail the channel.
  - if any `htlc_signature` is not valid for the corresponding HTLC transaction:
    - MUST fail the channel.
  - MUST respond with a `revoke_and_ack` message.

#### Rationale

There's little point offering spam updates: it implies a bug.

The `num_htlcs` field is redundant, but makes the packet length check fully self-contained.

### Completing the Transition to the Updated State: `revoke_and_ack`

Once the recipient of `commitment_signed` checks the signature and knows
it has a valid new commitment transaction, it replies with the commitment
preimage for the previous commitment transaction in a `revoke_and_ack`
message.

This message also implicitly serves as an acknowledgment of receipt
of the `commitment_signed`, so this is a logical time for the `commitment_signed` sender
to apply (to its own commitment) any pending updates it sent before
that `commitment_signed`.

The description of key derivation is in [BOLT #3](03-transactions.md#key-derivation).

1. type: 133 (`revoke_and_ack`)
2. data:
   * [`32`:`channel_id`]
   * [`32`:`per_commitment_secret`]
   * [`33`:`next_per_commitment_point`]

#### Requirements

A sending node:
  - MUST set `per_commitment_secret` to the secret used to generate keys for
  the previous commitment transaction.
  - MUST set `next_per_commitment_point` to the values for its next commitment
  transaction.

A receiving node:
  - if `per_commitment_secret` does not generate the previous `per_commitment_point`:
    - MUST fail the channel.
  - if the `per_commitment_secret` was not generated by the protocol in [BOLT #3](03-transactions.md#per-commitment-secret-requirements):
    - MAY fail the channel.

A node:
  - MUST NOT broadcast old (revoked) commitment transactions: doing
so will allow the other node to seize all channel funds.
  - SHOULD NOT sign commitment transactions, unless it's about to broadcast
  them (due to a failed connection), to reduce the above risk.

### Updating Fees: `update_fee`

An `update_fee` message is sent by the node that is paying the
Bitcoin fee. Like any update, it is first committed to the receiver's
commitment transaction and then (once acknowledged) committed to the
sender's. Unlike an HTLC, `update_fee` is never closed but simply
replaced.

There is a possibility of a race, as the recipient can add new HTLCs
before it receives the `update_fee`. Under this circumstance, the sender may
not be able to afford the fee on its own commitment transaction, once the `update_fee`
is finally acknowledged by the recipient. In this case, the fee will be less
than the fee rate, as described in [BOLT #3](03-transactions.md#fee-payment).

The exact calculation used for deriving the fee from the fee rate is
given in [BOLT #3](03-transactions.md#fee-calculation).

1. type: 134 (`update_fee`)
2. data:
   * [`32`:`channel_id`]
   * [`4`:`feerate_per_kw`]

#### Requirements

The node _responsible_ for paying the Bitcoin fee:
  - SHOULD send `update_fee` to ensure the current fee rate is sufficient (by a
      significant margin) for timely processing of the commitment transaction.

The node _not responsible_ for paying the Bitcoin fee:
  - MUST NOT send `update_fee`.

A receiving node:
  - if the `update_fee` is too low for timely processing, OR is unreasonably large:
    - SHOULD fail the channel.
  - if the sender is not responsible for paying the Bitcoin fee:
    - MUST fail the channel.
  - if the sender cannot afford the new fee rate on the receiving node's
  current commitment transaction:
    - SHOULD fail the channel,
      - but MAY delay this check until the `update_fee` is committed.

#### Rationale

Bitcoin fees are required for unilateral closes to be effective —
particularly since there is no general method for the broadcasting node to use
child-pays-for-parent to increase its effective fee.

Given the variance in fees, and the fact that the transaction may be
spent in the future, it's a good idea for the fee payer to keep a good
margin (say 5x the expected fee requirement); but, due to differing methods of
fee estimation, an exact value is not specified.

Since the fees are currently one-sided (the party which requested the
channel creation always pays the fees for the commitment transaction),
it's simplest to only allow it to set fee levels; however, as the same
fee rate applies to HTLC transactions, the receiving node must also
care about the reasonableness of the fee.

## Message Retransmission

Because communication transports are unreliable, and may need to be
re-established from time to time, the design of the transport has been
explicitly separated from the protocol.

Nonetheless, it's assumed our transport is ordered and reliable.
Reconnection introduces doubt as to what has been received, so there are
explicit acknowledgments at that point.

This is fairly straightforward in the case of channel establishment
and close, where messages have an explicit order, but during normal
operation, acknowledgments of updates are delayed until the
`commitment_signed` / `revoke_and_ack` exchange; so it cannot be assumed
that the updates have been received. This also means that the receiving
node only needs to store updates upon receipt of `commitment_signed`.

Note that messages described in [BOLT #7](07-routing-gossip.md) are
independent of particular channels; their transmission requirements
are covered there, and besides being transmitted after `init` (as all
messages are), they are independent of requirements here.

1. type: 136 (`channel_reestablish`)
2. data:
   * [`32`:`channel_id`]
   * [`8`:`next_local_commitment_number`]
   * [`8`:`next_remote_revocation_number`]
   * [`32`:`your_last_per_commitment_secret`] (option-data-loss-protect)
   * [`33`:`my_current_per_commitment_point`] (option-data-loss-protect)

### Requirements

A funding node:
  - upon disconnection:
    - if it has broadcast the funding transaction:
      - MUST remember the channel for reconnection.
    - otherwise:
      - SHOULD NOT remember the channel for reconnection.

A non-funding node:
  - upon disconnection:
    - if it has sent the `funding_signed` message:
      - MUST remember the channel for reconnection.
    - otherwise:
      - SHOULD NOT remember the channel for reconnection.

A node:
  - MUST handle continuation of a previous channel on a new encrypted transport.
  - upon disconnection:
    - MUST reverse any uncommitted updates sent by the other side (i.e. all
    messages beginning with `update_` for which no `commitment_signed` has
    been received).
      - Note: a node MAY have already use the `payment_preimage` value from
    the `update_fulfill_htlc`, so the effects of `update_fulfill_htlc` are not
    completely reversed.
  - upon reconnection:
    - if a channel is in an error state,
      - SHOULD retransmit the error packet and ignore any other packets for
      that channel.
    - otherwise:
      - MUST transmit `channel_reestablish` for each channel.
      - MUST wait for to receive the other node's `channel_reestablish`
        message before sending any other messages for that channel.

The sending node:
  - MUST set `next_local_commitment_number` to the commitment number of the
  next `commitment_signed` it expects to receive.
  - MUST set `next_remote_revocation_number` to the commitment number of the
  next `revoke_and_ack` message it expects to receive.

A node:
  - if `next_local_commitment_number` is 1 in both the `channel_reestablish` it
  sent and received:
    - MUST retransmit `funding_locked`.
  - otherwise:
    - MUST NOT retransmit `funding_locked`.
  - upon reconnection:
    - MUST ignore any redundant `funding_locked` it receives.
  - if `next_local_commitment_number` is equal to the commitment number of
  the last `commitment_signed` message the receiving node has sent:
    - MUST reuse the same commitment number for its next `commitment_signed`.
  - otherwise, if `next_local_commitment_number` is not 1 greater than the
  commitment number of the last `commitment_signed` message the receiving
  node has sent:
    - SHOULD fail the channel.
  - if `next_remote_revocation_number` is equal to the commitment number of
  the last `revoke_and_ack` the receiving node sent, AND the receiving node
  hasn't already received a `closing_signed`:
    - MUST re-send the `revoke_and_ack`.
  - otherwise:
    - if `next_remote_revocation_number` is not equal to 1 greater than the
    commitment number of the last `revoke_and_ack` the receiving node has sent:
      - SHOULD fail the channel.
    - if it has sent no `revoke_and_ack`, AND `next_remote_revocation_number`
    is equal to 0:
      - SHOULD fail the channel.

 A receiving node:
  - if it supports `option-data-loss-protect`, AND the `option-data-loss-protect`
  fields are present:
    - if `next_remote_revocation_number` is greater than expected above, AND
    `your_last_per_commitment_secret` is correct for that
    `next_remote_revocation_number` minus 1:
      - MUST NOT broadcast its commitment transaction.
      - SHOULD fail the channel.
      - SHOULD store `my_current_per_commitment_point` to retrieve funds
        should the sending node broadcast its commitment transaction onchain.
    - otherwise (`your_last_per_commitment_secret` or `my_current_per_commitment_point`
    do not match the expected values):
      - SHOULD fail the channel.

A node:
  - MUST not assume that previously-transmitted messages were lost,
    - if it has sent a previous `commitment_signed` message:
      - MUST handle the case where the corresponding commitment transaction is
      broadcast by the other side at any time. This is particularly important
      if the node does not simply retransmit the exact `update_` messages
      as previously sent.
  - upon reconnection:
    - if it has sent a previous `closing_signed`:
      - MUST send another `closing_signed`.
    - otherwise, if it has sent a previous `shutdown`:
      - MUST retransmit `shutdown`.

### Rationale

The requirements above ensure that the opening phase is nearly
atomic: if it doesn't complete, it starts again. The only exception
is if the `funding_signed` message is sent but not received. In
this case, the funder will forget the channel, and presumably open
a new one upon reconnection; meanwhile, the other node will eventually forget
the original channel, due to never receiving `funding_locked` or seeing
the funding transaction on-chain.

There's no acknowledgment for `error`, so if a reconnect occurs it's
polite to retransmit before disconnecting again; however, it's not a MUST,
because there are also occasions where a node can simply forget the
channel altogether.

`closing_signed` also has no acknowledgment so must be retransmitted
upon reconnection (though negotiation restarts on reconnection, so it need
not be an exact retransmission).
The only acknowledgment for `shutdown` is `closing_signed`, so one or the other
needs to be retransmitted.

The handling of updates is similarly atomic: if the commit is not
acknowledged (or wasn't sent) the updates are re-sent. However, it's not
insisted they be identical: they could be in a different order,
involve different fees, or even be missing HTLCs which are now too old
to be added. Requiring they be identical would effectively mean a
write to disk by the sender upon each transmission, whereas the scheme
here encourages a single persistent write to disk for each
`commitment_signed` sent or received.

A re-transmittal of `revoke_and_ack` should never be asked for after a
`closing_signed` has been received, since that would imply a shutdown has been
completed — which can only occur after the `revoke_and_ack` has been received
by the remote node.

Note that the `next_local_commitment_number` starts at 1, since
commitment number 0 is created during opening.
`next_remote_revocation_number` will be 0 until the
`commitment_signed` for commitment number 1 is received, at which
point the revocation for commitment number 0 is sent.

`funding_locked` is implicitly acknowledged by the start of normal
operation, which is known to have begun after a `commitment_signed` has been
received — hence, the test for a `next_local_commitment_number` greater
than 1.

A previous draft insisted that the funder "MUST remember ...if it has
broadcast the funding transaction, otherwise it MUST NOT": this was in
fact an impossible requirement; because, a node must either firstly commit to
disk and secondly broadcast the transaction or vice versa. The new
language reflects this reality: it's surely better to remember a
channel which hasn't been broadcast than to forget one which has!
Similarly, for the fundee's `funding_signed` message: it's better to
remember a channel that never opens (and times out) than to let the
funder open it while the fundee has forgotten it.

`option-data-loss-protect` was added to allow a node, which has somehow fallen behind
(e.g. restored from old backup), to detect that it's fallen-behind. A fallen-behind
node must know it cannot broadcast its current commitment transaction — which would lead to
total loss of funds — as the remote node can prove it knows the
revocation preimage. The error returned by the fallen-behind node
(or simply the invalid numbers in the `channel_reestablish` it has
sent) should make the other node drop its current commitment
transaction to the chain. This will, at least, allow the fallen-behind node to recover
non-HTLC funds, if the `my_current_per_commitment_point`
is valid. However, this also means the fallen-behind node has revealed this
fact (though not provably: it could be lying), and the other node could use this to
broadcast a previous state.

# Authors

[ FIXME: Insert Author List ]

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
