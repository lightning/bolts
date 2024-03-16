# Will Fund For Food Proposal
## Liquidity Advertisements

## Problem Description

Sourcing liquidity on the lightning network is a common problem
for any node looking to accept inbound payments.

## Overview

This proposal adds a TLV to the `node_announcement`,
which permits a node to advertise a rate for which they will contribute
funds to an open channel request. Due to the nature of the protocol, these
opens are only possible on the v2 channel protocol.

Any advertised liquidity lease is for a duration of 4032 blocks, or
approximately 28 days.

Any node wishing to take advantage of the offered funding contribution
may send an `open_channel2` request to the `node_announcement` node,
and include a `request_funds` tlv.

The accepter responds to the `open_channel2` by including a `will_fund`
TLV in their `accept_channel2` response, which includes the
fees they're charging for funding an open, the weight of the bytes they'll
add to the funding transaction, the maximum channel-fees
they will charge for moving HTLCs over the channel, and a signature. The
signature can be used by the opener to prove the accepter did not
abide by their channel-fee commitment.

An accepter may refuse to fund (but allow the open to succeed without
their contribution of funds) or decline to participate in a
channel open (fail the negotiation).

In the case that the accepter does not or can not supply the
requested funding amount, they may contribute less than the total
requested amount. They may also offer to contribute more. The lease fee
is calculated using the total amount contributed by the accepter.

Any contributed funds are subject to a funding lease of 4032 blocks. To enforce
this lease, the CSV of the accepter's output on the commitment transaction
is modified to reflect the remaining time left in the lease.

The opener updates the lease expiry by communicating their current blockheight
to the accepter via `update_blockheight` messages. If the opener fails
to update the blockheight (and thus the CSV lock) in a timely manner, the
accepter should fail the channel.

When the funding lease expires, the CSV locks on the accepter's
commitment transaction output reverts to the normal value, and the
fund lease is considered concluded.

## Implementation

This proposal is only applicable to dual-funded channels, as
single-funded channels do not have the capability to permit
the accepter to contribute funds to a channel.

A new TLV is added to both the `open_channel2` and `accept_channel2`.
These allow for the negotiation of the terms and funds for the
contribution.

A new message, `update_blockheight` is added to the Normal Operation of
a channel's lifetime. As with `update_feerate`, only the channel opener
may send this message.

The CSV value for the commitment transaction outputs to the accepter
are modified. They now incorporate the funding lease and time since
the channel has been opened. As blocks are published, the CSV
for the accepter's outputs is decremented. Once the funding lease
has passed, the CSV value outputs return to the 'normal', non-leased values.

The lease fee, which is owed to the accepter from the opener's funding
transaction inputs, is found as:

	- the `funding_fee_base_sat`, plus
	- the accepter's `funding_satoshis` times the
          `funding_fee_proportional_basis` / 1000, plus
	- the weight charge times the `funding_feerate_perkw` / 1000

The lease fee is added to the accepter's output in the commitment transaction.

## Security
The opener should consider implementing a rate limit or routing policy
that curtails the export of the leased funds during the duration of
the lease. This depends on the goals of the opener node.

## Open Questions
TODO
