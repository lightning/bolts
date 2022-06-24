# Extension Bolt ZZZ: Dynamic Commitments

Authors:
  * Olaoluwa Osuntokun <roasbeef@lightning.engineering>
  * Eugene Siegel <eugene@lightning.engineering>

Created: 2022-06-24

# Table of Contents

- [Introduction](#introduction)

- [Specification](#specification)
  * [Proposal Messages](#proposal-messages)
    + [`dyn_begin_propose`](#-dyn_begin_propose-)
    + [`dyn_propose`](#-dyn_propose-)
    + [`dyn_propose_reply`](#-dyn_propose_reply-)
  * [Reestablish](#reestablish)
    + [`channel_reestablish`](#-channel_reestablish-)

# Introduction

Dynamic commitments are a way to propose changing some static channel parameters that
are initially set in the `open_channel` and `accept_channel` messages. This document
outlines how this can be done on-the-fly with new messages.

# Specification

## Proposal Messages

Three new messages are introduced that let each side propose what they want to
change about the channel.

### `dyn_begin_propose`

This message is sent when a node wants to begin the dynamic commitment negotiation
process. This is a signaling message, similar to `shutdown` in the cooperative close
flow.

1. type: 111 (`dyn_begin_propose`)
2. data:
   * [`32*byte`:`channel_id`]
   * [`byte`: `begin_propose_flags`]

Only the least-significant-bit of `begin_propose_flags` is defined, the `reject` bit.

#### Requirements

The sending node:
  - MUST set `channel_id` to a valid channel they have with the receipient.
  - MUST set undefined bits in `begin_propose_flags` to 0.
  - MUST set the `reject` bit in `begin_propose_flags` if they are rejecting the dynamic
    commitment negotiation request.
  - MUST NOT send `update_add_htlc` messages after sending this unless one of the following
    is true:
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
  - if an `update_add_htlc` is received after this point and negotiation hasn't finished or
    terminated:
    - MUST send an `error` and fail the channel.

#### Rationale

This has similar semantics to the `shutdown` message where the channel comes to a state
where updates may only be removed. The `reject` bit is necessary to avoid having to reconnect
in order to have a useable channel state again.

### `dyn_propose`

This message is sent when neither side owes the other either a `revoke_and_ack` or
`commitment_signed` message and each side's commitment has no HTLCs. For now, only the
`dust_limit_satoshis` and `recipients_new_self_delay` parameter are defined in negotiation.
After negotiation completes, commitment signatures will use these parameters.

1. type: 113 (`dyn_propose`)
2. data:
   * [`32*byte`:`channel_id`]
   * [`dyn_propose_tlvs`:`tlvs`]

1. `tlv_stream`: `dyn_propose_tlvs`
2. types:
    1. type: 0 (`dust_limit_satoshis`)
    2. data:
        * [`u64`:`senders_new_dust_limit`]
    1. type: 2 (`to_self_delay`)
    2. data:
        * [`u16`:`recipients_new_self_delay`]

#### Requirements

The sending node:
  - MUST set `channel_id` to an existing one it has with the recipient.
  - MUST NOT set `dust_limit_satoshis` to a value that trims any currently untrimmed output
    on the commitment transaction.
  - MUST NOT send a `dyn_propose` if a prior one is waiting for `dyn_propose_reply`.
  - MUST remember its last sent `dyn_propose` parameters.
  - MUST send this message as soon as both side's commitment transaction is free of any HTLCs
    and both sides have sent `dyn_begin_propose`.

The receiving node:
  - if `channel_id` does not match an existing channel it has with the sender:
    - MUST close the connection.
  - if it does not agree with a parameter:
    - MUST send a `dyn_propose_reply` with the `reject` bit set.
  - else:
    - MUST send a `dyn_propose_reply` without the `reject` bit set.

#### Rationale

The requirement to not allow trimming outputs is just to make the dynamic commitment flow as
uninvasive as possible to the commitment transaction. When other fields are introduced, a
similar requirement should be added such that the new fields don't conflict with the current
commitment transaction (i.e. setting the `channel_reserve` too high). 

The requirement for a node to remember what it last _sent_ and for it to remember what it
_accepted_ is necessary to recover on reestablish. See the reestablish section for more
details.

### `dyn_propose_reply`

TODO - tell what params are rejected in tlvs?

This message is sent in response to a `dyn_propose`. It may either accept or reject the
`dyn_propose`. If it rejects a `dyn_propose`, it allows the counterparty to send another
`dyn_propose` to try again. If for some reason, negotiation is taking too long, it is possible
to exit this phase by reconnecting as long as the exiting node hasn't sent `dyn_propose_reply`
without the `reject` bit.

1. type: 115 (`dyn_propose_reply`)
2. data:
   * [`32*byte`:`channel_id`]
   * [`byte`: `propose_reply_flags`]

The least-significant bit of `propose_reply_flags` is defined as the `reject` bit.

#### Requirements

The sending node:
  - MUST set `channel_id` to a valid channel they have with the recipient.
  - MUST set undefined bits in `propose_reply_flags` to 0.
  - MUST set the `reject` bit in `propose_reply_flags` if they are rejecting the newest
    `dyn_propose`.
  - MUST NOT send this message if there is no outstanding `dyn_propose` from the counterparty.
  - if the `reject` bit is not set:
    - MUST remember the related `dyn_propose` parameters.

The receiving node:
  - if `channel_id` does not match an existing channel it has with the peer:
    - MUST close the connection.
  - if there isn't an outstanding `dyn_propose` it has sent:
    - MUST send an `error` and fail the channel.
  - if the `reject` bit was set:
    - MUST forget its last sent `dyn_propose` parameters.

A node:
  - once it has both sent and received `dyn_propose_reply` without the `reject` bit set:
    - MUST increment their `propose_height`.

#### Rationale

The `propose_height` starts at 0 for a channel and is incremented by 1 every time the
dynamic commitment proposal phase completes for a channel. See the reestablish section
for why this is needed.

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
  - MUST set `propose_height` to the number of dynamic proposal negotiations it has
    completed. The point at which it is incremented is described in the `dyn_propose_reply`
    section. 

The receiving node:
  - if the received `propose_height` equals its own `propose_height`:
    - MUST forget any stored proposal state for `propose_height`+1 in case negotiation didn't
      complete. Can continue using the channel.
    - SHOULD forget any state that is unnecessary for heights <= `propose_height`.
  - if the received `propose_height` is 1 greater than its own `propose_height`:
    - if it does not have any remote parameters stored for the received `propose_height`:
      - MUST send an `error` and fail the channel. The remote node is either lying about the
        `propose_height` or the recipient has lost data since its not possible to advance the
        height without the recipient storing the remote's parameters.
    - resume using the channel with its last-sent `dyn_propose` and the stored remote 
      `dyn_propose` parameters and increment its `propose_height`.
  - if the received `propose_height` is 1 less than its own `propose_height`:
    - resume using the channel with the new paramters.
  - else:
    - MUST send an `error` and fail the channel. State was lost.

#### Rationale

If both sides have sent and received `dyn_propose_reply` without the `reject` bit before the
connection closed, it is simple to continue. If one side has sent and received
`dyn_propose_reply` without the `reject` bit and the other side has only sent and not received
`dyn_propose_reply` without the `reject` bit, the flow is recoverable on reconnection. This is
because the side that hasn't received `dyn_propose_reply` has an implicit acknowledgement their
proposal was accepted based on the `propose_height` in the reestablish message.
