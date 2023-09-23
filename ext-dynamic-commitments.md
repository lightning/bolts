# Extension Bolt ZZZ: Dynamic Commitments

Authors:
  * Keagan McClelland <keagan@lightning.engineering>
  * Olaoluwa Osuntokun <roasbeef@lightning.engineering>
  * Eugene Siegel <eugene@lightning.engineering>

Created: TODO

# Table of Contents

TODO

# Introduction
## Abstract
This document describes a protocol for changing channel parameters that were
negotiated at the conception of the channel. Implementation of the protocol
described in this document will enable channel peers to re-negotiate channel
terms as if the channel was being opened for the first time while avoiding UTXO
churn whenever possible and therefore preserving the continuity of identity for
the channel whose terms are being changed.

## Motivation
It is well understood that closing channels is a costly thing to do. Not only is
it costly from a chain fees perspective where we pay for moving the funds from
the channel UTXO back to the main wallet collection, it is also costly from a
service availability and reputation perspective.

After channels are closed they are no longer usable for forwarding HTLC traffic
and even if we were to immediately replace the channel with another equally
capable one, the closure event is visible to the entire network. Since routes
are computed by the source, the network-wide visibility of channel closures
directly impacts whether or not the sender will be able to use a channel.

Beyond that, one of the pathfinding heuristics that is broadly used to assess
channel reliability is the length of time a channel has existed. The longevity
of a channel is therefore a key asset that any running Lightning node should
want to preserve, if possible.

It follows from the above that we should try to minimize channel closure events
when we can manage to do so. This motivates part of this proposal. Prior to this
extension BOLT, there is no way to change some of the channel parameters
established in the `{open|accept}_channel` messages without resorting to a full
channel closure. This limitation can be remediated by introducing a protocol to
renegotiate these parameters.

Notable in particular is that one of the channel parameters that we wish to
renegotiate is the the `channel_type` itself. With the advent of Simple Taproot
Channels (STCs), we have the opportunity to take advantage of the cost savings
and privacy capabilities afforded by the 2021 Taproot Soft Fork. With further
aspirations to be able to deploy Point Time-Lock Contracts (PTLCs) to the
Lightning Network, the sooner that network participants can upgrade to STCs the
more we will have the necessary network infrastructure to be able to make
effective PTLCs when the protocols for them are specified.

Due to the design of STCs and the fact that they are designed to make full use
of the capabilities afforded by Schnorr Signatures, there is no way to construct
a valid `channel_announcement` message that references the output corresponding
to the nodes' joint public key. As such, even if we were to directly spend an
existing channel point to a new STC channel point, and even with the provision
in BOLT 7 to delay graph pruning by 12 blocks after the channel point is spent,
we have no way to make the STC known to the network at the time of writing of
this proposal.

Concurrently with this proposal is a proposal for a new gossip system that is
capable of understanding announcements of the new STCs. However, in an effort to
allow nodes to upgrade to STCs without impacting the rest of the network, the
rest of the network would already need to be capable of understanding messages
from this new gossip system, the pervasive deployment of which remains far in
the future. To remove this disincentive of these channel upgrades to the
involved parties, this proposal to enable the change of these channel parameters
(including channel types) without requiring channel closure and reopening is
submitted.

## Preliminaries
This proposal includes a detailed section on the preliminaries to document to
reviewers and posterity some of the rationale for the design that is presented
later. If you are a Bitcoin and Lightning Network protocol expert or you are
uninterested in the thought process behind what is presented here, you may wish
to skip to the Design Overview section to save time

### Channel Opening Parameters
As described in BOLT 2, during the channel opening procedure there are a number
of parameters specified in the `open_channel` and `accept_channel` messages that
remain static over the lifetime of the channel. A subset of these are updatable
using other messages defined in the protocol. However, after accounting for the
channel parameters that can be changed there is a list of parameters which
remain unchangeable, which we list below.

- dust_limit_satoshis
- max_htlc_value_in_flight_msat
- channel_reserve_satoshis
- htlc_minimum_msat
- to_self_delay
- max_accepted_htlcs
- funding_pubkey
- revocation_basepoint
- payment_basepoint
- delayed_payment_basepoint
- htlc_basepoint
- first_per_commitment_point
- channel_flags
- upfront_shutdown
- channel_type

After some analysis during the development of this proposal, we determined that
many of the basepoint values don't make sense to rotate. There is no obvious
value in doing so and it carries additional administrative costs to rotate them.
Finally, changing the upfront_shutdown script over the lifetime of the channel
is self-defeating and so we exclude it as well. The list of channel parameters
remaining after we filter out these values is thus.

- dust_limit_satoshis
- max_htlc_value_in_flight_msat
- channel_reserve_satoshis
- htlc_minimum_msat
- to_self_delay
- max_accepted_htlcs
- funding_pubkey
- channel_flags
- channel_type

The design presented later is intended to allow for arbitrary changes to these
values that currently have no facilities for change in any other way.

### Gossip Verification
It is at this point that we need to take a brief detour and review how the
broader Lightning Network comes to discover and verify the existence of public
channels. When the funding transaction for a channel has confirmed, the
participating parties will jointly produce a message that attests to their
ownership of the UTXO and its viability as a routing edge for payment senders.

BOLT 7 details all of the specifics of this message and how it is computed but
one of the notable aspects of this process is that the receivers of these gossip
messages verify that the UTXO being referenced for underwriting the existence of
a channel must be a P2WSH output with a pre-defined script using the
participants' public keys, specified in BOLT 3. This will present issues for us
which will become clearer in the next section.

While alternative Gossip systems are being designed, they have not been deployed
in any known implementation of the Lightning Network Protocol and even if they
were there will be a prolonged period of time wherein some nodes on the network
will remain unable to process messages of this variety, rendering useless any
channels that are confined to being announced in this manner.

### Taproot
This brings us to talking about what channel constructions are actually
inexpressible by the existing gossip system. As we alluded to earlier, Taproot
channels cannot be discovered using the existing gossip message structure and
interpretation.

In November of 2021 the "Taproot" upgrade was activated on Bitcoin's mainnet,
creating a new output type that is subsequently useful to higher layer protocols
such as the Lightning Network. Since then, the Lightning Network protocol
designers have offered a proposal for a channel construction that makes use of
the Taproot output type. It is beyond the scope of this document to make a
thorough case for why such a channel construction is useful but we assume that
it is for our purposes here.

While Taproot channels are useful, they present some novel challenges with
respect to network-wide interoperability. Notably, a useful Taproot channel
construction must by definition make use of the new Taproot output type, which
is not and cannot be a P2WSH output of the format detailed in BOLT 3 for the
funding output. Pairing this fact with what we described in the previous
section, it is necessarily the case that the funding output of a Taproot channel
cannot be properly announced by the current gossip system.

With this background out of the way we are finally fully primed to understand
the nuances of the design.

## Design Overview
The main goal of this proposal is to be able to change all of the historically
"static" channel parameters, including the channel type, which includes channels
built off of output types that our gossip system currently doesn't understand,
in a world where we are trying to preserve the channel identity of the original
channel. This is a tall order.

Most of these parameters can be changed by simply expressing the desire to
change them, and should the recipient agree, we apply these changes, and
exchange new commitment transactions making any necessary adjustments implied
by the channel parameter changes.

The exception to this is certain changes to the channel type. As detailed in the
preliminaries, the funding output of a Taproot transaction is fundamentally
different from the funding output of the other channel types that are currently
defined. This means that we conceptually must spend the funding output of the
original channel into a new Taproot output before we have a functioning Taproot
channel.

The key insight in this design is that we extend the conception of a commitment
transaction to include the possibility of a pair of transactions wherein we have
a "kickoff transaction" that is comprised of a single input (the original
funding output) and a single output (the new funding output) and then building
the new commitment transaction off of the new funding output in whatever manner
is detailed in the specification for the target channel type. This may not
always be necessary, but it is certainly necessary for using this proposal to
convert existing channels into Taproot channels.

# Specification
There are two phases to this channel upgrade process: proposal and execution.
During the proposal phase the only goal is to agree on a set of updates to the
current channel state machine. During the execution phase, we apply the updates
to the channel state machine, exchanging the necessary information to be able
to apply those updates

## Proposal Phase

### Proposal Messages

Three new messages are introduced that are common to all dynamic commitment
flows. They let each side propose what they want to change about the channel.

#### `dyn_begin_propose`

This message is sent when a node wants to begin the dynamic commitment
negotiation process. This is a signaling message, similar to `shutdown` in the
cooperative close flow.

1. type: 111 (`dyn_begin_propose`)
2. data:
   * [`32*byte`:`channel_id`]
   * [`byte`: `begin_propose_flags`]

Only the least-significant-bit of `begin_propose_flags` is defined, the `reject`
bit.

##### Requirements

The sending node:
  - MUST set `channel_id` to a valid channel they have with the recipient.
  - MUST set undefined bits in `begin_propose_flags` to 0.
  - MUST set the `reject` bit in `begin_propose_flags` if they are rejecting the
    dynamic commitment negotiation request.
  - MUST NOT send `update_add_htlc` messages after sending this unless one of
    the following is true:
    - dynamic commitment negotiation has finished
    - a `dyn_begin_propose` with the `reject` bit has been received.
    - a reconnection has occurred.
  - MUST only send one `dyn_begin_propose` during a single negotiation.
  - MUST fail to forward additional incoming HTLCs from the peer.

The receiving node:
  - if `channel_id` does not match an existing channel it has with the peer:
    - MUST close the connection.
  - if the `reject` bit is set, but it hasn't sent a `dyn_begin_propose`:
    - MUST send an `error` and fail the channel.
  - if an `update_add_htlc` is received after this point and negotiation hasn't
    finished or terminated:
    - MUST send an `error` and fail the channel.
  - if it has not already sent `dyn_begin_propose` in this round of negotiation:
    - MUST reply with `dyn_begin_propose` either rejecting or accepting the
      negotiation request.

##### Rationale

This has similar semantics to the `shutdown` message where the channel comes to
a state where updates may only be removed.  Since, for simplicity, we require
there to be no outstanding HTLCs on the commitment during the following
negotiation, we must first signal that no new HTLCs may be added. The `reject`
bit is necessary to avoid having to reconnect in order to have a useable channel
state again.

#### `dyn_propose`

This message is sent when neither side owes the other either a `revoke_and_ack`
or `commitment_signed` message and each side's commitment has no HTLCs. For now,
only the `recipients_new_self_delay` parameter is defined in negotiation. After
negotiation completes, commitment signatures will use these parameters. The
overall message flow looks like this:

        +-------+                               +-------+
        |       |--(1)---dyn_begin_propose ---->|       |
        |       |                               |       |
        |       |<-(2)---dyn_begin_propose------|       |
        |       |                               |       |
        |       |--(3)----- dyn_propose ------->|       |
        |   A   |                               |   B   |
        |       |<-(4)----- dyn_propose --------|       |
        |       |                               |       |
        |       |--(5)--- dyn_propose_reply --->|       |
        |       |                               |       |
        |       |<-(6)--- dyn_propose_reply ----|       |
        +-------+                               +-------+

1. type: 113 (`dyn_propose`)
2. data:
   * [`32*byte`:`channel_id`]
   * [`dyn_propose_tlvs`:`tlvs`]

1. `tlv_stream`: `dyn_propose_tlvs`
2. types:
    1. type: 0 (`dust_limit_satoshis`)
    2. data:
        * [`u64`:`dust_limit_satoshis`]
    1. type: 2 (`max_htlc_value_in_flight_msat`)
    2. data:
        * [`u64`:`senders_max_htlc_value_in_flight_msat`]
    1. type: 4 (`channel_reserve_satoshis`)
    2. data:
        * [`u64`:`recipients_channel_reserve_satoshis`]
    1. type: 6 (`htlc_minimum_msat`)
    2. data:
        * [`u64`:`senders_htlc_minimum_msat`]
    1. type: 8 (`to_self_delay`)
    2. data:
        * [`u16`:`recipients_to_self_delay`]
    1. type: 10 (`max_accepted_htlcs`)
    2. data:
        * [`u16`:`senders_max_accepted_htlcs`]
    1. type: 12 (`funding_pubkey`)
    2. data:
        * [`point`:`senders_funding_pubkey`]
    1. type: 14 (`channel_type`)
    2. data:
        * [`...*byte`:`channel_type`]
    1. type: 16 (`kickoff_feerate`)
    2. data:
        * [`...*u32`:`kickoff_feerate_per_kw`]

##### Requirements

The sending node:
  - MUST set `channel_id` to an existing one it has with the recipient.
  - MUST NOT send a `dyn_propose` if a prior one is waiting for
    `dyn_propose_reply`.
  - MUST remember its last sent `dyn_propose` parameters.
  - MUST send this message as soon as both side's commitment transaction is free
    of any HTLCs and both sides have sent `dyn_begin_propose`.

The receiving node:
  - if `channel_id` does not match an existing channel it has with the sender:
    - MUST send an `error` and close the connection.
  - if it does not agree with a parameter:
    - MUST send a `dyn_propose_reply` with the `reject` bit set.
  - else:
    - MUST send a `dyn_propose_reply` without the `reject` bit set.

##### Rationale

The requirement to not allow trimming outputs is just to make the dynamic
commitment flow as uninvasive as possible to the commitment transaction. A
similar requirement should be added for any new parameter such as the
`channel_reserve`.

The requirement for a node to remember what it last _sent_ and for it to
remember what it _accepted_ is necessary to recover on reestablish. See the
reestablish section for more details.

#### `dyn_propose_reply`

This message is sent in response to a `dyn_propose`. It may either accept or
reject the `dyn_propose`. If it rejects a `dyn_propose`, it allows the
counterparty to send another `dyn_propose` to try again. If for some reason,
negotiation is taking too long, it is possible to exit this phase by
reconnecting as long as the exiting node hasn't sent `dyn_propose_reply` without
the `reject` bit.

1. type: 115 (`dyn_propose_reply`)
2. data:
   * [`32*byte`:`channel_id`]
   * [`byte`: `propose_reply_flags`]

The least-significant bit of `propose_reply_flags` is defined as the `reject`
bit.

##### Requirements

The sending node:
  - MUST set `channel_id` to a valid channel they have with the recipient.
  - MUST set undefined bits in `propose_reply_flags` to 0.
  - MUST set the `reject` bit in `propose_reply_flags` if they are rejecting the
    newest `dyn_propose`.
  - MUST NOT send this message if there is no outstanding `dyn_propose` from the
    counterparty.
  - if the `reject` bit is not set:
    - MUST remember the related `dyn_propose` parameters and the local and
      remote commitment heights for the next `propose_height`.

The receiving node:
  - if `channel_id` does not match an existing channel it has with the peer:
    - MUST close the connection.
  - if there isn't an outstanding `dyn_propose` it has sent:
    - MUST send an `error` and fail the channel.
  - if the `reject` bit was set:
    - MUST forget its last sent `dyn_propose` parameters.

A node:
  - once it has both sent and received `dyn_propose_reply` without the `reject`
    bit set:
    - MUST increment their `propose_height`.

##### Rationale

The `propose_height` starts at 0 for a channel and is incremented by 1 every
time the dynamic commitment proposal phase completes for a channel. See the
reestablish section for why this is needed.

## Reestablish

### `channel_reestablish`

A new TLV that denotes the node's current `propose_height` is included.

1. `tlv_stream`: `channel_reestablish_tlvs`
2. types:
    1. type: 20 (`propose_height`)
    2. data:
        * [`u64`:`propose_height`]

#### Requirements

The sending node:
  - MUST set `propose_height` to the number of dynamic proposal negotiations it
    has completed. The point at which it is incremented is described in the
    `dyn_propose_reply` section.

The receiving node:
  - if the received `propose_height` equals its own `propose_height`:
    - MUST forget any stored proposal state for `propose_height`+1 in case
      negotiation didn't complete. Can continue using the channel.
    - SHOULD forget any state that is unnecessary for heights <=
      `propose_height`.
  - if the received `propose_height` is 1 greater than its own `propose_height`:
    - if it does not have any remote parameters stored for the received
      `propose_height`:
      - MUST send an `error` and fail the channel. The remote node is either
        lying about the `propose_height` or the recipient has lost data since
        its not possible to advance the height without the recipient storing the
        remote's parameters.
    - resume using the channel with its last-sent `dyn_propose` and the stored
      `dyn_propose` parameters and increment its `propose_height`.
  - if the received `propose_height` is 1 less than its own `propose_height`:
    - resume using the channel with the new parameters.
  - else:
    - MUST send an `error` and fail the channel. State was lost.

#### Rationale

If both sides have sent and received `dyn_propose_reply` without the `reject`
bit before the connection closed, it is simple to continue. If one side has sent
and received `dyn_propose_reply` without the `reject` bit and the other side has
only sent `dyn_propose_reply`, the flow is recoverable on reconnection as the
side that hasn't received `dyn_propose_reply` knows that the other side accepted
their last sent `dyn_propose` based on the `propose_height` in the reestablish
message.

## Musig2 Taproot

This section describes how dynamic commitments can upgrade regular channels to
simple taproot channels. The regular dynamic proposal phase is executed followed
by a signing phase. A `channel_type` of `option_taproot` will be included in
`dyn_propose` and both sides must agree on it. The funder of the channel will
also propose a set of feerates to use for an intermediate "kickoff" transaction.

### Extensions to `dyn_propose`:

1. `tlv_stream`: `dyn_propose_tlvs`
2. types:
    1. type: 2 (`channel_type`)
    2. data:
        * [`...*byte`:`type`]
    1. type: 4 (`kickoff_feerates`)
    2. data:
        * [`...u32`:`kickoff_feerate_per_kw`]
    1. type: 6 (`taproot_funding_key`)
    2. data:
        * [`point`:`funding_key`]

#### Requirements

The sending node:
  - if it is the funder:
    - MUST only send `kickoff_feerate` if they can pay for each kickoff
      transaction fee and the anchor outputs, while adhering to the
      `channel_reserve` restriction.
  - MUST set `taproot_funding_key` to a valid secp256k1 compressed public key.
  - SHOULD use a sufficient number of `kickoff_feerates` to be prepared for
    worst-case fee environment scenarios.

The receiving node:
  - if it is the fundee:
    - MUST reject the `dyn_propose` if the funder cannot pay for each kickoff
      transaction fee and the anchor outputs.
    - MUST reject the `dyn_propose` if, after calculating the amount of the new
      funding output, the new commmitment transaction would not be able to pay
      for any outputs at the current commitment feerate.
  - MUST reject the `dyn_propose` if `taproot_funding_key` is not a valid
    secp256k1 compressed public key.
  - MAY reject the `dyn_propose` if it does not agree with the `channel_type`
  - MAY reject the `dyn_propose` if there are too many `kickoff_feerates` such
    that it would be a burden to track the potential confirmation of each
    kickoff and commitment transaction pair.

#### Rationale

The `dyn_propose` renegotiates the funding keys as otherwise signatures for the
funding keys would be exchanged in both the ECDSA and Schnorr contexts. This can
lead to an attack outlined in [BIP340](https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki#alternative-signing).
Renegotiating funding keys avoids this issue. Note that the various basepoints
exchanged in `open_channel` and `accept_channel` are not renegotiated. Because
the private keys _change_ with each commitment transaction they sign due to the
`per_commitment_point` construction, the basepoints can be used in both ECDSA
and Schnorr contexts.

The funder sends multiple fee-rates in order to be deal with high-fee
environments. Without this, the channel may not be able to upgrade commitment
types until the fee environment changes.

### Extensions to `dyn_propose_reply`:

1. `tlv_stream`: `dyn_propose_reply_tlvs`
2. types:
    1. type: 0 (`local_musig2_pubnonce`)
    2. data:
        * [`66*byte`:`nonces`]

#### Requirements

The sending node:
  - if it is accepting a `channel_type` of `simple_taproot_channel`:
    - MUST set `local_musig2_pubnonce` to the nonce that it will use to verify
      local commitments.

The receiving node:
  - MUST send an `error` and fail the channel if `local_musig2_pubnonce` cannot
    be parsed as two compressed secp256k1 points.

### Signing Phase

The signing phase is after the negotiation phase. The original funding output
spends to an intermediate transaction that pays to a v1 witness script with an
aggregated musig2 key derived from both parties `taproot_funding_key` sent in
`dyn_propose`. As in the simple-taproot-channels proposal, the
`commitment_signed`, `revoke_and_ack`, and `channel_reestablish` messages
include nonces.

#### Commitment Transaction

* version: 2
* locktime: upper 8 bits are 0x20, lower 24 bits are the lower 24 bits of the
  obscured commitment number
* txin count: 1
  * `txin[0]` outpoint: the matching kickoff transaction's musig2 funding
    outpoint.
  * `txin[0]` sequence: upper 8 bits are 0x80, lower 24 bits are upper 24 bits
    of the obscured commitment number
  * `txin[0]` script bytes: 0
  * `txin[0]` witness: `<key_path_sig>`

The 48-bit commitment number is computed by `XOR` as described in BOLT#03.

#### Commitment Transaction Construction

1. Initialize the commitment transaction version and locktime.
2. Initialize the commitment transaction input.
3. Calculate which committed HTLCs need to be trimmed.
4. Calculate the commitment transaction fee via
  commitment feerate * `commitment_transaction_weight`/1000, making sure to
  round down. Subtract this from the funder's output.
5. Subtract four times the fixed anchor size of 330 satoshis from the funder's
  output. Two of the anchors are from the commitment transaction and two are
  from the kickoff transaction.
6. Subtract the matching kickoff transaction's fee from the funder's output.
7. For every offered HTLC, if it is not trimmed, add an offered HTLC output.
8. For every received HTLC, if it is not trimmed, add a received HTLC output.
9. If the `to_local` output is greater or equal to the dust limit, add a
  `to_local` output.
10. If the `to_remote` output is greater or equal to the dust limit, add a
  `to_remote` output.
11. If `to_local` exists or there are untrimmed HTLCs, add a `to_local_anchor`.
12. If `to_remote` exists or there are untrimmed HTLCs, add a
  `to_remote_anchor`. The `to_remote_anchor` uses the remote party's
  `taproot_funding_key`.
13. Sort the outputs into BIP 69+CLTV order.

#### commitment_signed

The `commitment_signed` message does not change, but adds a nonce in the TLV
section per the simple-taproot-channels proposal. It changes what it signs in
the following ways:

1. `tlv_stream`: `commit_sig_tlvs`
2. types:
    1. type: 2 (`partial_signature_with_nonce`)
    2. data:
        * [`98*byte`:`partial_signature || public_nonce`]
    1. type: 4 (`local_musig2_pubnonce`)
    2. data:
        * [`66*byte`: `nonces`]

##### Requirements

The sending node:
  - MUST NOT increment the commitment number when signing.
  - MUST sign for any negotiated parameters that modified the commitment
    transaction (e.g. `to_self_delay`).

The receiving node:
  - MUST send an `error` and fail the channel if the signature does not sign the
    commitment transaction as constructed above.
  - MUST send an `error` and fail the channel if `partial_signature` is not a
    valid Schnorr signature.
  - MUST send an `error` and fail the channel if `public_nonce` cannot be parsed
    as two compressed secp256k1 points.
  - MUST send an `error` and fail the chanel if `local_musig2_pubnonce` cannot
    be parsed as two compressed secp256k1 points.

##### Rationale

The commitment number is not incremented while signing because if there are N
kickoff transactions and the N-2 kickoff transaction confirms, then
implementations will need to rewind their commitment number to N-2. We avoid
this complexity by keeping the commitment numbers static until the signing phase
is complete.

A set of local nonces is included because each signed commitment transaction
shares the same commitment number as the pre-dynamic-commitment commitment
transaction. For this reason, `revoke_and_ack` is omitted and thus local nonces
need to be sent in `commitment_signed`.

#### Kickoff Transaction(s)

* version: 2
* locktime: 0
* txin count: 1
  * `txin[0]` outpoint: `txid` and `output_index` from `funding_created` message
  * `txin[0]` sequence: 0xfffffffd
  * `txin[0]` script bytes: 0
  * `txin[0]` witness: `0 <signature_for_pubkey1> <signature_for_pubkey2>`
* txout count: 3
  * `txout[0]`: `anchor_output_1` or `anchor_output_2`
  * `txout[1]`: `anchor_output_1` or `anchor_output_2`
  * `txout[2]`: `p2tr_funding_output`

The anchor outputs have a value of 330 satoshis. They are encumbered by a
version 1 witness script:
* `OP_1 anchor_output_key`
* where:
  * `anchor_internal_key = original_local_funding_pubkey/original_remote_funding_pubkey`
  * `anchor_output_key = anchor_internal_key + tagged_hash("TapTweak", anchor_internal_key || anchor_script_root)`
  * `anchor_script_root = tapscript_root([anchor_script])`
  * `anchor_script`:
        ```
        OP_16 OP_CHECKSEQUENCEVERIFY
        ```

The new funding output has a value of the original funding output minus the sum
of 660 satoshis and this kickoff transaction's fee. It is encumbered by a
version 1 witness script where `taproot_funding_key1/taproot_funding_key2` are
from `dyn_propose_reply`:
* `OP_1 funding_key`
* where:
  * `funding_key = combined_funding_key + tagged_hash("TapTweak", combined_funding_key)*G`
  * `combined_funding_key = musig2.KeyAgg(musig2.KeySort(taproot_funding_key1, taproot_funding_key2))`

#### Kickoff Transaction Construction

1. Initialize the commitment transaction version and locktime.
2. Initialize the commitment transaction input.
3. Calculate this kickoff transaction's fee via `kickoff_feerate_per_kw`*
  `kickoff_transaction_weight`/1000, making sure to round down. Subtract this
  value from the new funding output.
5. Subtract two times the fixed anchor size of 330 satoshis from the new funding
  output.
6. Add a funding output with the new funding amount.
7. Add an anchor output for each party.
8. Sort the outputs into BIP 69+CLTV order.

#### kickoff_sig

The kickoff_sig is a message containing a signature that the fundee sends to the
funder who then combines it with their own signature to spend from the original
funding outpoint into the new musig2 output. To keep things simple, no
additional inputs are added to the intermediate transaction. An anchor output is
attached to either side for fee-bumping.

![Cannot display image](./dynamic-commits/kickoff%20tx.png "Kickoff transaction")

1. type: 777 (`kickoff_sig`)
2. data:
   * [`32*byte`:`channel_id`]
   * [`signature`:`signature`]

##### Requirements

The sending node (the fundee):
  - MUST set `channel_id` to a valid channel they have with the recipient.
  - MUST NOT send this message before receiving the peer's `commitment_signed`.

The receiving node (the funder):
  - MUST send an `error` and fail the channel if `channel_id` does not match an
    existing channel it has with the sender.
  - MUST send an `error` and fail the channel if `signature` is not valid for
    the kickoff transaction as constructed above OR non-compliant with the
    LOW-S-standard rule. <sup>[LOWS](https://github.com/bitcoin/bitcoin/pull/6769)</sup>

##### Rationale

To avoid the fundee griefing the funder by broadcasting the highest-fee kickoff
transaction, only the fundee sends `kickoff_sig`. This ensures that only the
funder can broadcast the kickoff transaction.

Even though only the funder is able to broadcast the kickoff transaction, we
include anchors such that the fundee can broadcast fee-bumping transactions if
they notice any of the kickoff transactions in the mempool.

#### Message flow to upgrade a channel to simple-taproot:

        +-------+                               +-------+
        |       |--(1)---- commit_signed------->|       |
        |       |                               |       |
        |   A   |<-(2)---- commit_signed -------|   B   |
        |       |<-(3)----- kickoff_sig --------|       |
        |       |                               |       |
        |       |--(4)---- commit_signed------->|       |
        |       |<-(5)---- commit_signed -------|       |
        |       |<-(6)----- kickoff_sig --------|       |
        +-------+                               +-------+

The above message ordering is important. If `kickoff_sig` is sent before
`commit_sig`, a griefing attack is possible:

        +-------+                               +-------+
        |   A   |<-(1)----- kickoff_sig --------|   B   |
        +-------+                               +-------+

Here, A stops sending messages and instead immediately broadcasts the kickoff
transaction.  Since neither side has exchanged `commitment_signed`, the new
funding output is unclaimable and is effectively burned. The majority of the
channel could be in B's outputs, making the loss of funds disproportionately on
B's side.

### Reestablish during simple-taproot upgrade

#### channel_reestablish

The `channel_reestablish` message does not change, but adds a nonce in the TLV
section per the simple-taproot-channels proposal.

1. `tlv_stream`: `channel_reestablish_tlvs`
2. types:
    1. type: 4 (`next_local_nonce`)
    2. data:
        * [`66*byte`:`public_nonce`]
    1. type: 6 (`num_sent_commit_sigs`)
    2. data:
        * [`u16`:`num_sigs`]
    1. type: 8 (`num_recv_commit_sigs`)
    2. data:
        * [`u16`:`num_sigs`]
    1. type: 10 (`num_kickoff_sigs`)
    2. data:
        * [`u16`:`num_sigs`]

The sending node:
  - MUST set `next_local_nonce` if the sender sees it has persisted a
    `channel_type` of `option_simple_taproot` from the `dyn_propose` /
    `dyn_propose_reply` negotiation steps.
  - MUST set `num_sent_commit_sigs` to the number of `commitment_signed` it has
    sent for this negotiation session.
  - MUST set `num_recv_commit_sigs` to the number of `commitment_signed` it has
    received for this negotiation session.
  - if it is the funder:
    - MUST set `num_kickoff_sigs` to the number of `kickoff_sig` messages it has
      received.
  - otherwise (it is the fundee):
    - MUST set `num_kickoff_sigs` to the number of `kickoff_sig` messages it has
      sent.

The receiving node:
  - MUST send an `error` and fail the channel if `next_local_nonce` cannot be
    parsed as two compressed secp256k1 points.
  - if its sent `num_sent_commit_sigs` is one greater than the received
    `num_recv_commit_sigs`:
    - MUST retransmit the missing `commitment_signed`.
  - if it is the fundee:
    - if its sent `num_kickoff_sigs` is one greater than the received
      `num_kickoff_sigs`:
      - MUST retransmit the missing `kickoff_sig`.
  - if messages were retransmitted:
    - MUST continue with the rest of the signing flow until a `kickoff_sig` has
      been sent for each fee-rate in `kickoff_feerates`.

The signing phase is complete when the funder's sent `num_kickoff_sigs` is equal
to the fundee's sent `num_kickoff_sigs` and is also equal to the number of
fee-rates in `kickoff_feerates` from the persisted `dyn_propose` parameters.

# Appendix

## Pinning

![Cannot display image](./dynamic-commits/kickoff%20pinning.png "Kickoff transaction pinned")

Originally, Bitcoin Core's default mempool settings allowed an unconfirmed
transaction to have up to 25 decendants in the mempool. Past this limit, any
descendants would be rejected. This was used as a DoS mitigation in Bitcoin Core
and affected the security of LN channels. Before the anchors commitment type was
introduced, pinning in the LN was where a counterparty broadcasted the
commitment transaction and created a chain of 25 descendants spending from one
of the commitment's outputs. The time-sensitive commitment transaction could be
"pinned" to the bottom of the mempool.  This was addressed with a change to
Bitcoin Core called CPFP Carve-out.

### CPFP Carve-out

CPFP Carve-out was introduced to Bitcoin Core in
https://github.com/bitcoin/bitcoin/pull/15681. If a Bitcoin node receives a
transaction that is rejected due to any of the mempool size or
ancestor/descendant restrictions being hit, it will try to accept the
transaction again. This second try will succeed only if:
  - the transaction is 40kWU or less
  - it has only one ancestor in the mempool

This change, in conjunction with the anchor commitment type, decreases the
efficacy of the pinning attack since the honest party can still attach an anchor
despite the descendant size limit being hit.

### Dynamic Commitments & CPFP Carve-out

The safety guarantees of CPFP Carve-out break due to the structure of the
kickoff transaction.  The kickoff transaction contains 3 spendable outputs: the
local party's anchor, the remote party's anchor, and the new funding output. All
three of these outputs can be spent immediately.  A malicious counterparty can
pin the kickoff transaction by:
  - spending from their anchor output to create a descendant chain of 25
    transactions
  - then spending from the new funding output, "using up" the CPFP Carve-out
    slot designated for the honest party.

Depending on fee conditions, it may not be possible for the honest party to get
these transactions confirmed until the mempool clears up.

If we were to get rid of the kickoff transaction's anchor outputs, the problem
still arises. A malicious counterparty could still pin the kickoff transaction
by:
  - broadcasting the commitment transaction
  - spending from their anchor output and creating a descendant chain of 25
    transactions

The honest party is unable to use their anchor on the commitment transaction as:
  - the descendant limit of 25 transactions has been hit
  - the anchor spend would have 2 ancestors (the commitment and kickoff
    transactions)

### Reducing Risk

The above pinning scenarios highlight the complexity of second-layer protocols
and mempool restrictions. In this proposal, pinning is _still_ possible, but
risk is mitigated because:
  - the kickoff transaction MUST confirm before HTLCs can be added to the
    commitment transaction
  - no HTLCs exist on the commitment transaction while the kickoff transaction
    is unconfirmed

If we allowed adding HTLCs _before_ the kickoff transaction confirmed on-chain,
the pinning attack would now have a tangible benefit: the ability to steal the
value of an HTLC. The second requirement above is very similar to the first
requirement: by disallowing HTLCs when `dyn_propose` is sent, we ensure that the
counterparty has no incentive to pin the kickoff transaction.

## Weights

Since DER-encoded signatures vary in size, we assume a worst-case signature size
of 73 bytes to keep things simple. The kickoff transaction has an
_expected weight_ of 944WU and the commitment transaction has an
_expected weight_ of 960WU.

General weights:
  * p2tr: 34 bytes
      - OP_1: 1 byte
      - OP_DATA: 1 byte (witness_script_SHA256 length)
      - witness_script_SHA256: 32 bytes

  * witness_header: 2 bytes
      - flag: 1 byte
      - marker: 1 byte

### Kickoff Transaction Weights
  * funding_output_script: 71 bytes
    - OP_2: 1 byte
    - OP_DATA: 1 byte (pub_key_alice length)
    - pub_key_alice: 33 bytes
    - OP_DATA: 1 byte (pub_key_bob length)
    - pub_key_bob: 33 bytes
    - OP_2: 1 byte
    - OP_CHECKMULTISIG: 1 byte

  * funding_input_witness: 222 bytes
    - number_of_witness_elements: 1 byte
    - nil_length: 1 byte
    - sig_alice_length: 1 byte
    - sig_alice: 73 bytes
    - sig_bob_length: 1 byte
    - sig_bob: 73 bytes
    - witness_script_length: 1 byte
    - witness_script: 71 bytes (funding_output_script)

  * kickoff_txin_0: 41 bytes (excl. witness)
    - previous_out_point: 36 bytes
      - hash: 32 bytes
      - index: 4 bytes
    - var_int: 1 byte (script_sig length)
    - script_sig: 0 bytes
    - witness: <---- part of the witness data
    - sequence: 4 bytes

  * musig2_funding_output: 43 bytes
    - value: 8 bytes
    - var_int: 1 byte (pk_script length)
    - pk_script (p2tr): 34 bytes

  * anchor_output: 43 bytes
    - value: 8 bytes
    - var_int: 1 byte (pk_script length)
    - pk_script (p2tr): 34 bytes

  * kickoff_transaction: 180 bytes (excl. witness)
    - version: 4 bytes
    - witness_header: <---- part of the witness data
    - count_tx_in: 1 byte
    - tx_in: 41 bytes
      - kickoff_txin_0: 41 bytes
    - count_tx_out: 1 byte
    - tx_out: 129 bytes
      - musig2_funding_output: 43 bytes
      - anchor_output_local: 43 bytes
      - anchor_output_remote: 43 bytes
    - lock_time: 4 bytes

  - Multiplying non-witness data by 4 gives a weight of:
    - kickoff_transaction_weight = 180vbytes * 4 = 720WU
  - Adding the witness data:
    - kickoff_transaction_weight += (funding_input_witness + witness_header)
    - kickoff_transaction_weight = 944WU

### Commitment Transaction Weights
Here we assume that both parties have an output on the commitment transaction.
This is to keep the weight consistent across potentially different commitment
transactions.

  * musig2_funding_input_witness: 66 bytes
    - number_of_witness_elements: 1 byte
    - musig2_signature_length: 1 byte
    - musig2_signature: 64 bytes

  * commitment_txin_0: 41 bytes (excl. witness)
    - previous_out_point: 36 bytes
      - hash: 32 bytes
      - index: 4 bytes
    - var_int: 1 byte (script_sig length)
    - script_sig: 0 bytes
    - witness: <---- part of the witness data
    - sequence: 4 bytes

  * to_local: 43 bytes
    - value: 8 bytes
    - var_int: 1 byte (pk_script length)
    - pk_script (p2tr): 34 bytes

  * to_remote: 43 bytes
    - value: 8 bytes
    - var_int: 1 byte (pk_script length)
    - pk_script (p2tr): 34 bytes

  * to_local_anchor: 43 bytes
    - value: 8 bytes
    - var_int: 1 byte (pk_script length)
    - pk_script (p2tr): 34 bytes

  * to_remote_anchor: 43 bytes
    - value: 8 bytes
    - var_int: 1 byte (pk_script length)
    - pk_script (p2tr): 34 bytes

  * commitment_transaction: 225 bytes (excl. witness)
    - version: 4 bytes
    - witness_header: <---- part of the witness data
    - count_tx_in: 1 byte
    - tx_in: 41 bytes
      - commitment_txin_0: 41 bytes
    - count_tx_out: 3 byte
    - tx_out: 172 bytes
      - to_local: 43 bytes
      - to_remote: 43 bytes
      - to_local_anchor: 43 bytes
      - to_remote_anchor: 43 bytes
    - lock_time: 4 bytes
  
  - Multiplying non-witness data by 4 gives a weight of:
    - commitment_transaction_weight = 223vbytes * 4 = 892WU
  - Adding the witness data:
    - commitment_transaction_weight += (musig2_funding_input_witness + witness_header)
    - commitment_transaction_weight = 960WU
