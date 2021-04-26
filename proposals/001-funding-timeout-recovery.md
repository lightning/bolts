# Funding Timeout Recovery (KEYOLO)

> "So long, and thanks for all the keys" 
>     -- Hitchhikers guide to Lightning


## Problem description

Due to circumstances it may take considerable time for a funding
transaction to confirm, e.g., the funder chose to attach a fee that is
too low to guarantee timely confirmation. This means the channel
funding may not complete for quite some time, and the specification
thus allows the fundee to forget the channel after 2016 blocks:

>  - SHOULD forget the channel if it does not see the correct funding
>    transaction after a timeout of 2016 blocks.

Since this leaves the funder in a situation where they are forced
to use the commitment transaction, and since the commitment
transaction is using an overestimated feerate, this could end up
costing the funder more than strictly necessary, and the specification
suggests avoiding this situation thus:

> If the fundee forgets the channel before it was confirmed, the
> funder will need to broadcast the commitment transaction to get his
> funds back and open a new channel. To avoid this, the funder should
> ensure the funding transaction confirms in the next 2016 blocks.

However, despite a funder's best efforts to estimate the funding
transaction fee correctly, the estimation may still fail to guarantee
timely confirmation.

This proposal describes a method for a channel to be closed
collaboratively, without going through the commitment transaction with
overestimated feerate, and without encumbering the funder's funds with
the unilateral close timeout.


## Overview

Upon agreeing to open a new channel with a peer, the fundee generates
a new bitcoin private key `funding_privkey` (corresponding to the
`funding_pubkey`) that is used to sign off on the funds in the channel
once the funding is complete, i.e., the funding transaction is
confirmed. This `funding_pubkey` is used exclusively when signing off
on changes to the channel, no unrelated funds are ever secured using
this private key.


It is best practice to use hardened derivation for the
`funding_pubkey` in order to prevent a single private key leaking
resulting in all keys being compromised. If an only if the
`funding_privkey` was derived using hardened derivation, the fundee
can communicate the `funding_key` to the funder, without incurring any
risk of losing funds in the process, since the key, or any key derived
thereof, do not control any of the fundee's funds. After receiving the
fundee's `funding_privkey`, the funder can use it to create a
transaction spending the funding output, without any limit as to the
destination of the funds, the feerate used, and without requiring
further interaction with the fundee. This frees the parties from
having to negotiate a closing transaction fee, since the funder can
simply change the outputs on the closing transaction and sign for both
parties.

The fundee receives the fundee's `funding_privkey` as part of an error
message when attempting to re-establish a connection, allowing them to
build a closing transaction, with arbitrary outputs, e.g., not
encumbering the funder's return output with a timeout.

## Implementation

This proposal is only applicable to single-funded channels, as
dual-funded channels do not suffer from this issue.

The fundee may forget a channel if it hasn't been confirmed after
2016, however it may chose to retain a minimal stub of the channel to
help the funder recover the funds gracefully in case the funding
transaction eventually confirms. In order to do so it must retain the
following information:

 - Information used to derive the `funding_privkey`.
 - The `temporary_channel_id` from the `funding_created` message.

This information is required in order to identify the channel based on
the `channel_reestablish` message and of course the `funding_privkey`
to share with the peer.

A stub MUST NOT be created if the funding transaction confirmed before
the fundee decided to forget the channel and mark it as closed /
forgotten.

Upon forgetting the channel, the fundee has to store the above
information locally in order to retrieve it when required. The fundee
MUST mark the channel as closed, preventing them from signing off on
any future changes, and any re-establishment attempt of the channel
MUST result in an immediate error being returned.

The following steps encompass the funding timeout recovery:

 1. Upon reconnecting the funder sends a `channel_reestablish` message
    as usual.
 2. Upon receiving the `channel_reestablish` the fundee notices that
    it has forgotten the channel, but it has a funding timeout
    recovery stub matching the `channel_id`.
 3. The fundee derives the `funding_privkey` based on the stub for the
    channel.
 4. The `funding_privkey` is sent as part of the `error` message (see
    Error Details change below), as TLV type XXX.
 5. The funder receives the `funding_privkey` and verifies that it
    matches the `funding_pubkey` negotiated during the channel
    creation.
 6. The funder completes the close transaction with the desired
    outputs, and computes both its own signature and the fundee's
    signature using the `funding_privkey`
 7. The close transaction is broadcast, completing the close operation.
 
## Extension: Funding Transaction Alias

Under some circumstances it may happen that the funding transaction is
malleated, and the funding outpoint is no longer the same as
advertised during the negotiation. In this case any commitment
transaction negotiated during the opening will also be invalid, and
the funds are stuck in limbo.

To solve this issue, the funder can provide an alias, i.e., the
malleated outpoint as part of the re-establish. Upon receiving a
re-establish with an alias the fundee MAY mark the channel as closed,
derives the necessary information (detailed above), but replaces the
`funding_outpoint` with the one from the re-establish message and
returns the generated signature as part of the `error` message.

## Safety

The `funding_privkey` is assumed to be unique for every channel. If
this is the case then any signature created using the `funding_privkey` can only ever
be applied to transactions relating to the channel, i.e., signing a
commitment or close transaction for that channel. It is possible with
the extension for a funder to receive a signature for an arbitrary
output, however given the above constraint, it must be either the
funding output for the channel, or the signature doesn't match the
output's spending requirement as it's bound to another public-key or
script.

Notice that in case the `funding_privkey` was not derived using
hardened derivation it is possible for the funder to derive private
keys relating to other channels from the shared `funding_privkey`,
making this scheme insecure, and exposing the fundee to loss of
funds. It is therefore strongly suggested to always use hardened
derivation, which prevents an attacker from deriving other private
keys from a single leaked key.

## Required Changes

The following changes are required to existing messages.


### Error Details

The `error` message is extended with a TLV stream at the end to
include details about the error. This proposal uses this to return the
`funding_privkey` from the fundee to the funder if they forgot the
channel.


### Re-establish TLV

Only required for the funding transaction alias extension. The
`channel_reestablish` message is extended with a TLV stream at the end
to include optional fields. This proposal adds the optional
`funding_transaction_alias` TLV type to be added in this stream.


## Open Questions

 - [ ] Do we want to piggyback the signature on the error message or
       shall we add a new message that preceeds the error message?
 - [ ] Additional safety checks: `next_commitment_number` must be 1.
