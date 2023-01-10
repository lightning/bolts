# Upfront HTLC Fees

## Table of Contents
* [Proposal](#proposal)
  * [Introduction](#introduction)
  * [Threat Model](#threat-model)
  * [Mitigation](#mitigation)
    * [Quick Jamming Mitigation ](#quick-jamming-mitigation)
    * [Slow Jamming Mitigation](#slow-jamming-mitigation)
    * [Justification](#justification)
* [Network Upgrade](#network-upgrade)
* [FAQ](#faq)
* [References](#references)

## Proposal

### Introduction
Channel jamming is a known denial-of-service attack against the Lightning 
Network. An attacker that controls both ends of a payment route disrupt usage 
of a channel by sending payments that are destined to fail through a target 
route. This attack can exhaust the resources along the target route in two ways, 
though the difference between the two behaviors is not rigorously defined: 
1. Quick Jamming: sending a continuous stream of payments through a route that
   are quickly resolved, but block all of the liquidity or HTLC slots along 
   the route.
2. Slow Jamming: sending a slow stream of payments through a route and only 
   failing them at the latest possible timeout, blocking all of the liquidity
   or HTLC slots along the route for the duration.

Fees are currently only paid to routing nodes on successful completion of a 
payment, so this attack is virtually free - the attacker pays only for the 
costs of running a node, funding channels on-chain and the opportunity cost
of capital committed to the attack.

### Threat Model
Attackers may aim to disrupt a specific set of channels, or the network as a
whole. We consider the following threat model, adapted from [1]: 
* The attacker can quickly set up a set of seemingly unrelated nodes and open
  channels to any public node in the network.
* The attacker has an up to date view of the network's public topology. 
* The attacker is economically rational, meaning that they will pursue an 
  attack with the lowest cost and highest utility (and "seeing the world burn" 
  classifies as utility).
* The attacker has the ability to send slow or quick jams: 
  * Quick jamming attacks will aim to fill all available htlc slots if
    `max_accepted_htlcs` * `htlc_minimum_msat` < `max_htlc_value_in_flight_msat`,
    or otherwise will aim to deplete channel liqudidity.
  * The attacker has a modified LN node implementation that allows them to hold
    HLTCs up until the point of force closure, then release them.
* The attacker may have access to long-lived channels when the attack begins.

### Mitigation
To comprehensively mitigate jamming attacks against the Lightning Network, a
solution needs to address both quick and slow jamming. This proposal has two 
parts, upfront fees to address quick jamming and reputation to address slow
jamming [2].

### Quick Jamming Mitigation
Traffic that is part of a quick jamming attack mimics the behavior of honest 
nodes' failed payments, which makes it difficult to identify. A solution that 
addresses quick jamming therefore *must have a trivial impact on honest 
traffic, but be sufficient to compensate the node(s) under attack*. A solution 
that fails to do this will only magnify an attacker's ability to disrupt the 
network, as they can leverage the jamming mitigation itself to further degrade 
honest traffic.

An upfront fee, paid regardless of the outcome of a payment attempt, is proposed
to economically compensate nodes for providing traffic with access to liquidity
and slots. Simulations in [2] show that a fee of as little as 1% of the success
case fees are sufficient to compensate the opportunity cost of forwarding nodes
in various routing scenarios.

Nodes that advertise `option_upfront_fee` (56/57) will advertise a new TLV in
their `channel_update` which expresses unconditional fees as a percentage of 
their success-case fees advertised in the update: 
```
1. `tlv_stream`: `channel_update_tlvs`
2. types:
    1. type: 1 (`upfront_fee_policy`)
    2. data:
        * [`tu32`:`upfront_fee_base_ppm`]
        * [`tu32`:`upfront_fee_proportional_ppm`]

```

To save the network the bandwidth and storage required to transmit and save
defaults, nodes that advertise `option_upfront_fee` in their node announcement
should be assumed to have a base and proportional fee that is 1% of its success
case fees. Nodes also will not relay and senders will not utilize channels with
a `channel_update` messages where upfront fees are > 10% of their success-case
equivalent. This eliminates the risk of nodes setting these fees so high that
it becomes economically rational for forwarding nodes to fail payments for the
sake of their upfront fees. 

The upfront fee amount should simply be assigned to the receiving party's 
balance when an incoming HTLC is added. These amounts are not expected to be
enforceable on-chain (as they are likely to be dust), so there is no need to 
include an output for them in the channel's commitment transactions.

As with success-case fees, upfront fees are charged on the outgoing link and 
accumulated on the incoming link when payments are accepted for forwarding. The
`update_add_htlc` message is extended with a new TLV which specifies the amount
that must be pushed to the remote peer on addition of the incoming HTLC to its
channel state. 
```
1. `tlv_stream`: `update_add_htlc_tlvs`
2. types:
    1. type: 2 (`upfront_fee_msat`)
    2. data:
        * [`tu64`:`upfront_fee_msat`]
```

The upfront fee that should be sent to the next peer in the route is provided
in the onion's payload. As is currently the case with htlc forwarding amounts, 
the difference between the incoming `upfront_fee_msat` amount in 
`update_add_htlc_tlvs` and the outgoing `upfront_fee_to_forwad` is used to 
validate that sufficient upfront fees are paid to the forwarding node. 
```
1. `tlv_stream`: `payload`
1. type: 2 (`upfront_fee_to_forward`)
    2. data:
        * [`tu64`:`upfront_fee_to_forward`]
```

An upfront fee policy field is added to bolt-11 invoices to allow receiving 
nodes to advertise the upfront fees that it will accept for the final hop 
(since there is no outgoing link for the sender to obtain a policy from). 
```
`u` (17) `data_length` 26:
 * `upfront_base_msat` (32 bits, big-endian)
 * `upfront_proportional_millionths` (32 bits, big-endian)
```

Adding a field to the invoice is chosen rather than allowing sender to select
an arbitrary upfront fee for the final hop, because they have little incentive
to protect the receiver's privacy at their own expense. The receiver must 
include the upfront fees paid across all HTLCs in a set as contributions to 
the total payment amount. This allows receivers to set privacy-preserving 
policies without shifting the cost to the sender.


For example, consider an invoice for 30,000 msat which is paid in multiple 
parts:
- HTLC 1 arrives: amount = 15,000, upfront_fees=100
- HTLC 1 fails with MPPTimeout
- HTLC 2 arrives: amount = 15,000, upfront_fees=100
- HTLC 3 arrives: amount = 14,700, upfront_fees=100

The receiving node should reveal the preimage at this point, because it has
received the total of 30,000 msat from the sender (29,700 paid via HTLCs in the
set and 300 msat through upfront fees).

Sending nodes can factor this upfront fee into the total amount they dispatch:
- Let a be the recipient's chosen `upfront_base_msat`.
- Let b be the recipient's chosen `upfront_proportional_millionths`.
- Let X be the total amount due to be paid. 
- Let Y be the payment amount that the sender should dispatch.

The sender can trivially solve for Y: 
```
X = Y + b + aY
Y=(X-b)/(1+a)
```

To prevent underpayment due to rounding-down, the sender can use integer 
arithmetic to compute ceil(n/m) as (n + m - 1)/m: 
```
Y =(X-b + 1+a - 1)/(1+a)
Y =(X-b+a)/(1+a)
```

### Slow Jamming Mitigation
Slow jamming attacks are easier to identify, because they lock liquidity in 
HTLCs for an atypically long period of time. There are some honest instances
where a HTLC may be held for a longer period of time in the network:
1. Submarine Swaps [3]: the exchange of off-chain liquidity for on-chain funds
   (or the reverse) can lock funds for 3-6 blocks in the optimistic case, and 
    50-100 blocks in failure mode.
2. Offline Nodes: if a forwarding node goes offline, payments that are 
   in-flight along its route can get "stuck" until the route's timeout has 
   elapsed.

Locally tracked reputation is proposed to address this type of jamming. As with 
quick jamming, any mitigation for slow jamming *must have a trivial impact on 
the reputation of honest nodes when they see an atypically long hold time, and 
significantly degrade quality of service for persistent abusers*. 

The full details of this proposal will be covered in a follow up proposal.

### Justification
Any solution that defines a threshold can inevitably be gamed by an attacker 
that determines (through trial and error) the threshold and adjusts their 
behavior to fall just beneath it. Likewise, a solution that charges a trivial 
amount in the isolated event of failure but becomes significant at scale is 
less effective against an attacker that can draw out the efficacy of their 
attack through long holds. By combining upfront fees with local reputation, 
the network can effectively protect against both types of jamming attacks [4].

## Network Upgrade
Introduction of upfront fees requires end-to-end upgrade along a route - every
node along the route needs to be upgraded to understand the new changes to the
protocol for a sender to incorporate upfront fees in a payment.

Routing nodes have no way of knowing whether a sender understands the new 
upfront fee rules, so cannot enforce payment of upfront fees when first 
deployed. We propose an optimistic upgrade path where senders include upfront 
fees _if_ the whole route supports the feature.   
 
## FAQ
1. What about nodes that charge zero fees? 
Nodes that do not charge success-case fees are offering their resources to the
network for free. The opportunity cost of a failed payment is zero because they
have no possible earnings, so their upfront fees should also be zero.

2. How is user experience affected by fees-for-failures?
A user experience concern is that the fees associated with unsuccessful payment 
attempts may discourage users. However, the overall amount of fees paid should 
not increase significantly, even when failed attempts are taken into account. 
This is because the expected number of attempts needed for a payment to go 
through decays exponentially. When the number of attempts is small, the amount 
paid in upfront fees will be low. Wallets can feasibly abstract this detail 
away, and advanced users should understand this mitigation strategy and the 
fact the change to fees in practice is very small.

3. How do upfront fees interact with a possible future extension to the 
   protocol that allows negative success-case fees?
Using negative fees to lure routing algorithms to certain routes can create 
potential vulnerabilities, such as draining upfront fees through failed 
transactions [5]. Other potential risks include the flood and loot attacks, as 
well as privacy breaches. To mitigate these risks, routing algorithms should 
consider factors beyond just routing fees. In particular, they should avoid 
repeatedly attempting routes that have consistently failed in the past - as is
already the case in practice for many implementations.

4. What about Route Blinding/Bolt12?
Blinded routes can be extended to provide information about the upfront fees 
required for the blinded portion of the route, specifically:
* An `upfront_fee` TLV in each hop's `encrypted_data` 
* A `upfront_fee_base_msat` and `upfront_fee_proportional_millionths` in the
  `blinded_payinfo` provided in invoices. 

These proposals are not coupled to prevent unnecessary dependencies, but are 
easily combined. 

*More frequently asked questions will be addressed in this section as they are
frequently asked!*

## References
[1] [Spamming the Lightning Network](https://github.com/t-bast/lightning-docs/blob/master/spam-prevention.md) - Bastien Teinturier

[2] [Unjamming Lightning: A Systematic Approach](https://eprint.iacr.org/2022/1454.pdf) - Clara Shikhelman and Sergei Tikhomirov

[3] [Understanding Submarine Swaps](https://docs.lightning.engineering/the-lightning-network/multihop-payments/understanding-submarine-swaps) - Leo Weese

[4] [Unjamming Lightning: A Summary](https://research.chaincode.com/2022/11/15/unjamming-lightning/) - Clara Shikhelman and Sergei Tikhomirov

[5] [Possible Attack if we add both upfront and negative routing fees](https://lists.linuxfoundation.org/pipermail/lightning-dev/2023-January/003809.html) - René Pickhardt
