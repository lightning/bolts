# Local Resource Conservation

## Table of Contents

- [Introduction](#introduction)
- [Overview](#overview)
- [Local Reputation](#local-reputation)
  - [Recommendations for Reputation Scoring](#recommendations-for-reputation-scoring)
    - [Effective HTLC Fees](#effective-htlc-fees)
    - [Outgoing Channel Reputation](#outgoing-channel-reputation)
    - [In Flight HTLC Risk](#in-flight-htlc-risk)
    - [Incoming Channel Revenue](#incoming-channel-revenue)
- [Resource Bucketing](#resource-bucketing)
  - [General Bucket](#general-bucket)
  - [Congestion Bucket](#congestion-bucket)
  - [Protected Bucket](#protected-bucket)
  - [Forwarding HTLCs](#forwarding-htlcs)
- [Implementation Notes](#implementation-notes)
  - [Decaying Average](#decaying-average)
  - [Revenue Threshold Aggregation](#revenue-threshold-aggregation)
  - [Multiple Channels](#multiple-channels)

## Introduction

Channel jamming is a known denial-of-service attack against the Lightning
Network. An attacker can disrupt regular usage of the network by spamming it
with intentionally failing payments, or simply delaying resolution of (their own or
other honest) payments to consume resources. Fees are currently only paid to
routing nodes on successful completion of a payment, so this attack is virtually
free - the attacker pays only for the costs of running a node, funding channels
on-chain and the opportunity cost of capital committed to the attack.

A channel can be fully jammed by depleting its available HTLC slots by holding
`max_accepted_htlcs` or its available liquidity by holding the
`max_htlc_value_in_flight`. An economically rational attacker will pursue the
attack method with the lowest cost and highest utility. An attack can exhaust
the resources along the target route in two ways, though the difference
between the two behaviors is not rigorously defined:
- Quick Jamming: sending a continuous stream of payments through a route that
  are quickly failed, sent at a rate that continuously consumes all resources
  along the targeted route.
- Slow Jamming: sending a slow stream of payments through a route and only
  failing them at the latest possible timeout, blocking all of the liquidity
  or HTLC slots along the route for the duration.

This document outlines recommendations for implementing local resource
conservation to mitigate slow jamming attacks. It is part of a hybrid solution
to mitigating channel jamming, intended to be followed by the introduction of
unconditional fees to mitigate fast jamming.

## Overview

Local resource conservation combines the following elements to provide nodes
with a mechanism to protect themselves against slow-jamming attacks:

- [Local Reputation](#local-reputation): local tracking of the historical
  forwarding behavior of downstream peers, used to make forwarding decisions.
  Behavior of downstream peers is observed because a malicious downstream peer
  is necessary to perform a slow-jamming attack (the upstream may or may not be
  malicious).
- [HTLC accountability](#../02-peer-protocol.md#adding-an-htlc-update_add_htlc):
  a signal sent in `update_add_htlc` that informs a node whether their reputation
  with the offering node will be held accountable for the fast resolution of the
  HTLC. This signal is originally provided by the recipient, and is propagated
  along the route.
- [Resource Bucketing](#resource-bucketing): restrictions on the amount of
  resources that peers are allowed to consume, determined by their reputation
  and current number of in-flight HTLCs. Implemented as buckets of general,
  congestion and protected resources.

In the steady state when Lightning is being used as expected, there should be
no need for use of protected or congestion resources as channels are not
saturated during regular operation. Should the network come under attack, honest
nodes that have built up reputation over time will still be able to utilize
protected resources to process payments in the network.

## HTLC Accountability

The `accountable` signal indicates that the receiving node's reputation will
be held accountable for the fast resolution of the HTLC. This may only be set
if the final recipient indicates that they are `accountable` in their invoice,
as resolution is ultimately dependent on their hold time. 

The original sender:
- SHOULD NOT set `accountable` in their offered `update_add_htlc`.
- MAY set `accountable` to mimic patterns observed in their forwarded traffic
  if `upgrade_accountability` is set in the recipient's invoice.

The forwarding node:
- If `accountable` is set in the received `update_add_htlc`:
  - MUST set `accountable` in the offered `update_add_htlc` (see [BOLT-02](#../02-peer-protocol.md#adding-an-htlc-update_add_htlc)).
- Otherwise: 
  - If it used `protected` or `congestion` resources to forward the HTLC:
    - SHOULD set `accountable` in its offered `update_add_htlc`.
  - Otherwise:
    - SHOULD NOT set `accountable` in its offered `update_add_htlc`.

### Rationale

Sending node has not used up any scarce resources to send the original HTLC,
so they do not need to use the `accountable` signal. However, they may want to
mimic the pattern they observe in their forwarded traffic to protect their
privacy as the sending node. Once a forwarding node has used scarce resources,
they are at risk of being channel jammed so they should inform their downstream
peer that they are accountable so that the HTLC is carefully handled. If a
forwarding node maliciously drops an `accountable` signal, they risk hurting
their own reputation.

## Local Reputation

### Recommendations for Reputation Scoring

Local reputation is used by forwarding nodes to decide whether it is safe to
forward an `accountable` HTLC to an outgoing channel. Nodes MAY use any metric
of their choosing to classify a peer as having sufficient reputation, though a
poor choice of reputation scoring metric may affect their reputation with their
upstream peers. 

The goal of this reputation metric is to ensure that the cost to obtain
sufficient reputation for an `accountable` HTLC to be forwarded on the outgoing
channel is greater than the damage that a node can inflict by abusing the access
that it is granted to the incoming channel's resources. This algorithm uses
forwarding fees to measure damage, as this value is observable within the
protocol. It is reasonable to expect an adversary to "about turn" - to behave
perfectly to build up reputation, then alter their behavior to abuse it. For
this reason, in-flight HTLCs have a temporary negative impact on reputation
until they are resolved.

If granted full access to a node's liquidity and slots, the maximum amount of
damage that can be inflicted on the targeted node is bounded by the largest
cltv delta from the current block height that it will allow a HTLC to set
before failing it with [expiry_too_far](../04-onion-routing.md#failure-messages).
At the time of writing, the default value in the protocol is 2016 blocks
(~2 weeks).

Upon receipt of `update_add_htlc`, the local node considers the following to
determine whether the outgoing channel has sufficient reputation:
- Incoming channel revenue threshold: the total routing fees over the maximum
  allowed HTLC hold period (~2 weeks) that the incoming channel has earned the
  local node as the incoming forwarding party.
- Outgoing channel reputation: the total routing fees that the outgoing channel
  has earned the local node, considering only outgoing HTLCs forwarded on the
  channel.
- In-flight HTLCs risk: any `accountable` HTLC that the outgoing channel has
  in-flight (across all incoming channels) will negatively affect reputation,
  based on the assumption that they will be held until just before their
  expiry height.

On a per-HTLC basis, the local node will classify the outgoing channel's
reputation for the offered HTLC as follows:
- if `outgoing_channel_reputation - in_flight_risk >= incoming_revenue_threshold`:
  - the outgoing channel is considered to have *sufficient* reputation for the
    offered HTLC.
- otherwise, the outgoing channel is considered to have *insufficient* reputation
  for the offered HTLC.

The sections that follow provide details of how to calculate the components of
the inequality.

#### Effective HTLC Fees

The contribution that the fees paid by a HTLC make to reputation standings is
adjusted by the amount of time that a HTLC took to resolve. By accounting for
the "opportunity cost" of HTLCs that are held for longer periods of time, the
reputation score rewards fast resolving, successful payments and penalizes
slow resolving payments (regardless of successful resolution).

We define the following:
- `resolution_period`: the amount of time a HTLC is allowed to resolve in that
  classifies as "good" behavior, expressed in seconds. The recommended default
  is 90 seconds (given that the protocol allows for a 60 second MPP timeout).
- `resolution_time`: the amount of time elapsed in seconds between a HTLC being
  added to and removed from the local node's commitment transaction.
- `fees`: the fees that are charged by the local node to forward the HTLC,
  expressed in milli-satoshis.

We define the `opportunity_cost` of the time a HTLC takes to resolve:

`opportunity_cost = max(0,  (resolution_time - resolution_period) / resolution_period) * fees`

Given that `resolution_time` will be > 0 in practice, `opportunity_cost` is 0
for HTLCs that resolve within `resolution_period`. For each subsequent
`resolution_period` that the HTLC is held, the `fees` that the forwarding
node could have earned using those resources are counted towards its
`opportunity_cost`.

Each HTLC's contribution to reputation is expressed by its `effective_fee`
which is determined by whether it is `accountable`, resolution time and outcome:
- if `accountable` is present in the offered `update_add_htlc`:
  - if successfully resolved with `update_fulfill_htlc`:
    - `effective_fees` = `fees` - `opportunity_cost`
  - otherwise:
    - `effective_fees` = -`opportunity_cost`
- otherwise:
  - if successfully resolved AND `resolution_time` <= `resolution_period`
    - `effective_fees` = `fees`
  - otherwise: 
    - `effective_fees` = 0

##### Rationale

Reputation relies on the fees charged by the local node rather than the fee
offered by the sender to prevent over-payment of advertised fees from
contributing to reputation. This is unlikely to impact honest senders who will
abide by advertised fee policies, and complicates (but does not prevent)
attempts to artificially inflate reputation through excessive fee payments.
Using local fee policies also prevents an attacker from inflating fees to
increase the damage that they can do to another node's reputation.

Reputation is negatively affected by slow-resolving `accountable` HTLCs
(regardless of whether they are settled or failed) to ensure that reputation
scoring reacts to bad behavior. HTLCs that resolve within a period of time that
is considered reasonable do not decrease reputation, as some rate of failure is
natural in the network.

The resolution of HTLCs with no `accountable` marker set does not have a negative
impact on the outgoing channel's reputation, because they were not informed that
they would be held liable. They are allowed to build reputation when they resolve
successfully within the specified `resolution_period` to allow new nodes in the
network to bootstrap reputation.

#### Outgoing Channel Reputation

Outgoing channel reputation measures the unforgeable history that the outgoing
channel has built with the local node by successfully resolving payments. As
this value aims to capture the contribution of the channel (rather than its
value to the local node), only outgoing HTLCs are considered.

We define the following parameters: 
- `revenue_window`: the largest cltv delta from the current block height that a
node will allow a HTLC to set before failing it with [expiry_too_far](../04-onion-routing.md#failure-messages),
expressed in seconds, assuming 10 minute blocks (default 2 weeks).
- `reputation_multiplier`: a multiplier applied to 
  `revenue_window` to determine the rolling window over which the
  outgoing channel's forwarding history is considered (default 12).

We define the `outgoing_channel_reputation`:
- for each `update_add_htlc` offered on the outgoing channel over
  the rolling window [`now` - `revenue_window` *  `reputation_multiplier`; `now`]:
  - if the HTLC has been resolved:
    - `outgoing_channel_reputation` += `effective_fee(HTLC)`

##### Rationale

Fees are used to accumulate reputation because they are an unforgeable,
in-protocol cost to the attacker. For the outgoing channel, only HTLCs where
the channel has acted as the outgoing party in a forward are counted
because we're interested in their historical actions as an outgoing peer.

#### In Flight HTLC Risk

Whenever a HTLC is forwarded, we assume that it will resolve with the worst
case off-chain resolution time and dock reputation accordingly. This decrease
will be temporary in the case of fast resolution, and preemptively slash
reputation in the case where the HTLC is used as part of a slow jamming attack.

For each offered `update_add_htlc` on the outgoing channel we track the risk
of the corresponding `update_add_htlc` received on the incoming channel, as
this is the HTLC that can be held if the outgoing channel chooses to perform a
slow jamming attack.

The outstanding risk of an `update_add_htlc` is defined as follows:
- `height_added`: the block height at which the incoming HTLC was irrevocably
  committed to by the local node.
- `maximum_hold_seconds` = (`cltv_expiry` - `height_added`) * 10 * 60, the
  longest amount of time that the HTLC can be held on our incoming channel
  (assuming 10 minute blocks).

We define the `in_flight_htlc_risk` for an outgoing channel as:
- for each `update_add_htlc` offered to the outgoing channel:
  - if `accountable` is present:
    - if there is a corresponding incoming `update_add_htlc`
      - `in_flight_htlc_risk` += `opportunity_cost(maximum_hold_seconds, fee)`

##### Rationale

In flight HTLCs are included in reputation scoring to account for sudden changes
in a peer's behavior. Even when sufficient reputation is obtained, each HTLC
choosing to take advantage of that reputation is treated as if it will be used
to inflict maximum damage. The expiry height of each incoming in flight HTLC is
considered so that risk is directly related to the amount of time the HTLC
could be held in the channel. Ten minute blocks are assumed for simplicity.

#### Incoming Channel Revenue

Incoming channel revenue measures the damage to the local node (ie, the loss in
forwarding fees) that a slow jamming attack can incur. For an individual
channel, this is equal to the total revenue generated by forwards received on
the incoming channel over the maximum allowed HTLC hold time.

We define the `incoming_revenue_threshold`: 
- for each `update_add_htlc` received on the incoming channel over the rolling
  window [`now` - `revenue_window`; `now`]:
  - if the HTLC has been resolved: 
    - `incoming_revenue_threshold` += `fee`

##### Rationale

We consider revenue from HTLC forwards received on the incoming channel because
we are accounting for the possible damage that could be inflicted by an outgoing
channel that is able to congest the channel in that direction. In flight HTLCs
have no impact on incoming channel revenue, as their fee contribution is unknown.

## Resource Bucketing

When making the decision to forward a HTLC on its outgoing channel, a node
MAY choose to limit the number of HTLCs that are allowed to accumulate on its
incoming channel.

This may seem counter-intuitive, as HTLCs are already committed on the incoming
channel once it comes time to forward it to the outgoing channel. By basing the
forwarding decision on the saturation of the incoming channel, the node limits
the ability of the outgoing channel to hold onto HTLCs and saturate the incoming
channel.

Resources are divided into three buckets:
- General resources: available to all traffic, with some protections against
  trivial denial of service.
- Congestion resources: available with restrictions when general resources have
  been saturated to outgoing channels that do not have sufficient reputation.
- Protected resources: reserved for outgoing channels with sufficient
  reputation.

A node implementing resource bucketing to protect against channel exhaustion:
- MUST NOT allocate more slots than their local `max_accepted_htlcs` across
  buckets.
- MUST NOT allocate more liquidity than their `max_htlc_value_in_flight_msat`
  across buckets.

Recommended Defaults:
- General: 40% of `max_accepted_htlcs` and `max_htlc_value_in_flight_msat`.
- Congestion: 20% of `max_accepted_htlcs` and `max_htlc_value_in_flight_msat`.
- Protected: 40% of `max_accepted_htlcs` and `max_htlc_value_in_flight_msat`.

### General Bucket

To protect the general bucket from trivial denial of service, each forwarding
pair of channels is restricted to a subset of slots and liquidity.

We define the following:
- `general_bucket_slot_allocation`:
  - If the channel type allows a maximum of 483 HTLCs: 20
  - If the channel type allows a maximum of 114 HTLCs: 5
- `general_bucket_liquidity_allocation` =
  `general bucket capacity * general_bucket_slot_allocation / general bucket slot total`

Each `(incoming scid, outgoing scid)` is deterministically assigned slots:
```
for i = 0; i < general_bucket_slot_allocation {
  slot = sha256(concat(salt, incoming scid, outgoing scid, i)) % general bucket slot total
}
```

Where `salt`:
- MUST be randomly chosen and unique per channel.
- SHOULD be persisted across restarts to restore slot allocations.

A HTLC is eligible to use the general bucket if for its
`(incoming scid, outgoing scid)`'s assigned resources:
- Currently occupied slots < `general_bucket_slot_allocation`
- Currently occupied liquidity + `amt_msat` <= `general_bucket_liquidity_allocation`

#### Rationale

The goal of limiting the resources available to each channel aims to make it
more expensive for an attacker to exhaust resources, as opening a channel incurs
a cost, while still allowing reasonable usage by honest peers. Salting 
resource assignment ensures that the attacker cannot detect which resources
they will be assigned, and thus cannot strategically open new channels to
manipulate assignment.

The default slot allocations provided are chosen such that it it highly
improbable that any two channels are granted the same set of resources, making
it difficult for an attacker to crowd out honest traffic. With these defaults,
an attacker will need to open approximately 50 channels in expectation to gain
access to all general resources.

### Congestion Bucket

The congestion bucket is only used when the general bucket is saturated,
indicating that the channel may be under attack. These resources implement a
"tit-for-tat"-style of permissiveness to allow forwards to outgoing channels
that do not have sufficient reputation.

An outgoing channel is considered eligible to use an incoming channel's
congestion bucket if:
- The outgoing channel does not currently have a HTLC in flight in the
  congestion bucket.
- In the last two weeks, the outgoing channel has not taken more than
  `resolution_period` to resolve a HTLC that utilized the incoming channel's
  congestion bucket.

A HTLC is granted access to the congestion bucket if:
- The outgoing channel is eligible to use the congestion bucket.
- The general bucket's slots or liquidity are saturated.
- The onion packet has `upgrade_accountability` set.
- The incoming `update_add_htlc` does not have `accountable` set.
- The `amount_msat` < `bucket_capacity_msat` / `bucket_slots`.

#### Rationale

If an attacker is able to saturate the general bucket, the congestion bucket
allows honest peers that don't have reputation some chance of having payments
forwarded to them. This access is strictly limited per channel, so that the
cost for an attacker to directly saturate it is high. It is also difficult for
a downstream attacker to sabotage HTLCs that are forwarded in the congestion
bucket, because they are forwarded as `accountable` so will only be forwarded
to channels that have built up reputation.

### Protected Bucket

The protected bucket is reserved for peers with sufficient outgoing reputation.
There are no restrictions on usage so that channels that have built sufficient
reputation can operate as usual during periods of attack. If this bucket is
full, HTLCs that were eligible to use it may utilize any other available 
resources in general or congestion buckets.

#### Rationale

The protected bucket aims to project unrestricted resource access to peers that
have build sufficient reputation. In the unlikely event that the protected
bucket is full and other resources are still available, these peers are allowed
to use any other bucket, but are still subject to their restrictions.

### Forwarding HTLCs

HTLC forwards are assigned resources as follows:
- If `accountable` is set in the received `update_add_htlc`:
  - If the outgoing peer has sufficient reputation:
    - SHOULD forward the HTLC, assigning usage to the protected bucket.
  - Otherwise:
    - MUST fail the HTLC with `temporary_channel_failure`
- Otherwise:
  - If general resources are available:
    - SHOULD forward the HTLC, assigning usage to the general bucket.
  - Otherwise:
    - If the outgoing peer has sufficient reputation:
      - SHOULD forward the HTLC, assigning usage to the protected bucket.
    - Otherwise:
      - If the HTLC is eligible to use congestion resources:
        - SHOULD forward the HTLC, assigning usage to the congestion bucket.
      - Otherwise:
        - SHOULD fail the HTLC with `temporary_channel_failure`.

When forwarding HTLCs, nodes MUST set `accountable` in the offered
`update_add_htlc` as outlined in [HTLC Accountability](#htlc-accountability).

### Rationale

In times of peace when general resources are not saturated, there is no need
for nodes to hold any HTLCs `accountable`. When resources become scarce, it is
only safe to allow nodes that have build reputation to access protected
resources - otherwise any node can trivially consume all of a channel's
resources.

If a HTLC is received with `accountable` already set, this indicates that the
upstream node has already had to use resources to forward it that put it at
risk of being channel jammed. The receiving node is responsible for dropping it
on the upstream node's behalf rather than forwarding it to nodes that do not
have sufficient reputation which may hold the HTLC in an attempt to saturate
its channels. This is in the forwarding node's interest, as it preserves its
reputation with the offering node.

The congestion bucket gives peers without reputation "one shot" to behave
themselves, then penalizes them if they abuse this chance. Setting `accountable`
on offered `update_add_htlc` messages for HTLCs that use the congestion bucket
will ensure that the HTLC will be dropped if it reaches an outgoing channel
that does not have reputation; this means that attackers are forced to build
reputation to abuse these slots (similar to protected resources). HTLCs that
already have `accountable` set by the upstream peer are not accommodated in this
bucket, because forwarding to an outgoing channel that does not have reputation
puts our own reputation at risk.

Upgrading the `accountable` signal only when protected resources are required
ensures that the additional restrictions that need to be applied to 
`accountable` HTLCs only apply when necessary.

## Implementation Notes

### Decaying Average

Rolling windows specified in this write up may be implemented as a decaying
average to minimize the amount of data that needs to be stored per-channel. In
flight HTLCs can be accounted for separately to this calculation, as the node
will already have data for these HTLCs available.

To track a rolling window over the period `window_length_seconds` as a decaying
average, track the following values:
- `last_update`: stores the timestamp of the last update to the decaying
    average, expressed in seconds.
- `decaying_average`: stores the value of the decaying average.
- `decay_rate`: a constant rate of decay based on the rolling window chosen,
  calculated as: `(1/2)^(2/window_length_seconds)`.

To update the `decaying_average` at time `t`:
- `last_update_diff` = `now` - `last_update`.
- `decaying_average` = `decaying_average` * `decay_rate` ^ `last_update_diff`.
- `last_update` = `t`.

When assessing whether a peer has sufficient reputation for a HTLC:
- MUST update `decaying_average` as described above.

When updating the `decaying_average` to add the `effective_fee` of a newly
resolved HTLC at timestamp `t`:
- MUST update `decaying_average` as described above.
- `decaying_average` = `decaying_average` + `effective_fee`

### Revenue Threshold Aggregation

It is recommended to track the average value of `incoming_revenue_threshold`
over `reputation_multiplier` periods to protect these thresholds against
shocks (either naturally occurring, or induced by an attacker). For example,
with a `revenue_window` of 2 weeks and a `reputation_multiplier` of 12, it is
recommended to track `incoming_revenue_threshold` for 12 periods of 2 weeks.

This can be implemented by individually tracking each period's 
`incoming_revenue_threshold`, or by tracking a `decaying_average` over the
full `revenue_window` * `reputation_multiplier` period and dividing the value
by `reputation_multiplier` to get the average value for a single 
`revenue_window`.

### Multiple Channels

If the local node has multiple channels open with the incoming and outgoing
peers:
- SHOULD calculate `outgoing_channel_reputation` for the channel that is selected
  for [non-strict-forwarding](../04-onion-routing.md#non-strict-forwarding)
  forwarding.

## Acknowledgements

Thank you to everyone who contributed to ideas, improvement and review
of this document, including Matt Morehouse, AJ Towns and Thomas Huet.
