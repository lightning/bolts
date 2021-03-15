# Funding Timeout Recovery

> "So long, and thanks for all the sigs" 
>     -- Hitchhikers guide to Lightning


## Problem description

Due to circumstances it may take considerable time for a funding
transaction to confirm, e.g., the funder chose to attach a fee that is
too low to guarantee timely confirmation. This means the channel
funding may not complete for quite some time, and the specification
thus allows the fundee to forget the channel after 2016 blocks:

>  - SHOULD forget the channel if it does not see the correct funding
>    transaction after a timeout of 2016 blocks.

Since this leads the __funder__ in a situation where they are forced
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
confirmed. This *funding_pubkey* is used exclusively when signing off
on changes to the channel, no unrelated funds are ever secured using
this private key.

The fundee may therefore sign a collaborative close transaction with
the `funding_privkey` at any time, as long as they remember not to
sign any future commitment transactions. Thus the fundee may provide a
blanked signature for a commitment transaction using `sighash_none`,
signing off whatever the funder intends to do with the funding
outpoint. This frees the parties from having to negotiate a closing
transaction fee, since the funder can simply change the outputs on the
closing transaction without invalidating the fundee's signature.

The fundee receives the blank signature as part of an error message
when attempting to re-establish a connection, allowing them to build a
closing transaction, with arbitrary outputs, e.g., not encumbering the
funder's return output with a timeout.


## Implementation

This proposal is only applicable to single-funded channels, as
dual-funded channels do not suffer from this issue.

The fundee may forget a channel if it hasn't been confirmed after
2016, however it may chose to retain a minimal stub of the channel to
help the funder recover the funds gracefully in case the funding
transaction eventually confirms. In order to do so it must retain the
following information:

 - The `channel_id` that was exchanged during the funding
   sub-protocol.
 - Information used to derive the `funding_privkey`.
 - The `funding_outpoint` from the `funding_created` message.
 - The funder's `funding_pubkey`.
 
This information is required in order to construct a valid closing
transaction without any outputs. The outputs will later be modifiable
by the funder, and committed to by their own signature. The fundee
signs the closing transaction with `sighash_none` to allow these
changes by the funder.

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
 3. The fundee create a closing transaction from the channel stub,
    with `nSequence=0xfffffffd`, sign it with the private key matching
    `fundee_privkey`.
 4. The signature is sent as part of the `error` message (see Error
    Details change below), as TLV type XXX.
 5. The funder receives the signature and verifies that it matches the
    expected close transaction.
 6. The funder completes the close transaction with the desired
    outputs, the fundee signature, and its own signature.
 7. The close transaction is broadcast, completing the close operation.
 
Notice that since the signature from the fundee is a `sighash_none`
signature, it doesn't get invalidated when changing the outputs. This
allows the funder to chose any desired feerate. In addition setting
the `nSequence=0xfffffffd` opts into RBF, allowing the funder to bump
the feerate if desired.


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
this is the case then any signature the fundee provides can only ever
be applied to transactions relating to the channel, i.e., signing a
commitment or close transaction for that channel. It is possible with
the extension for a funder to receive a signature for an arbitrary
output, however given the above constraint, it must be either the
funding output for the channel, or the signature doesn't match the
output's spending requirement as it's bound to another public-key or
script.


## Required Changes

The following changes are required to existing messages.


### Error Details

The `error` message is extended with a TLV stream at the end to
include details about the error. This proposal uses this to return the
blank signature from the fundee to the funder if they forgot the
channel.


### Re-establish TLV

Only required for the funding transaction alias extension. The
`channel_reestablish` message is extended with a TLV stream at the end
to include optional fields. This proposal adds the optional
`funding_transaction_alias` TLV type to be added in this stream.


## Open Questions

 - [ ] The specification appears to not require `funding_pubkey` to be
       unique to the channel. Is anyone reusing their it? Can we
       require it to be unique?
 - [ ] Do we want to piggyback the signature on the error message or
       shall we add a new message that preceeds the error message?
 - [ ] Additional safety checks: `next_commitment_number` must be 1.
