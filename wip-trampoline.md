# Trampoline Onion Routing

This document describes the additions we make to the existing onion routing to
enable the use of trampoline hops.

As the network grows, more bandwidth and storage will be required to keep an
up-to-date view of the whole network. Finding a payment path will also require
more computing power, making it unsustainable for constrained devices.

Constrained devices should only keep a view of a small part of the network and
leverage trampoline nodes to route payments. This proposal still uses an onion
created by the payer so it doesn't sacrifice anonymity (in most cases it will
even provide a bigger anonymity set).

Nodes that keep track of the whole network should advertise support for
`option_trampoline_routing`. This is an opportunity for them to earn more fees
than with the default onion routing.

A payer selects a few trampoline nodes and builds a corresponding trampoline
onion TLV. It then embeds that trampoline onion in the last `per_hop` payload
of an `onion_packet` destined to the first trampoline node. Computing routes
between trampoline nodes is deferred to the trampoline nodes themselves.

Merchants may include a few trampoline nodes that are close to them in their
invoice to help payers select a good last trampoline node. This is optional and
payers aren't required to use this routing hint.

An interesting side-effect is that trampoline routing combines nicely with
rendezvous routing. With a simple new TLV type and more data in the invoice,
rendezvous routing can easily work on top of trampoline routing, with a
construction similar to what is described [here][rendezvous].

## Table of Contents

* [Packet Structure](#packet-structure)
  * [Trampoline Onion](#trampoline-onion)
  * [Usage](#usage)
  * [Paying to non-trampoline nodes](#paying-to-non-trampoline-nodes)
* [Fees and CLTV requirements](#fees-and-cltv-requirements)
* [Network Pruning](#network-pruning)
  * [The `node_update` Message](#the-node_update-message)
  * [Fees and CLTV estimation](#fees-and-cltv-estimation)
  * [Filtering gossip messages](#filtering-gossip-messages)
* [Examples](#examples)
  * [Merchant supporting trampoline payments](#merchant-supporting-trampoline-payments)
  * [Merchant without trampoline support](#merchant-without-trampoline-support)
* [References](#references)

## Packet Structure

### Trampoline Onion

The trampoline onion is a fixed-size TLV packet with the following structure:

1. type: `trampoline_onion_packet`
2. data:
   * [`1`:`0x08`] (`type`)
   * [`3`:`0xfde202`] (`length`)
   * [`1`:`version`]
   * [`33`:`public_key`]
   * [`672`:`trampoline_hops_data`]
   * [`32`:`hmac`]

This results in a `742`-bytes fixed-size packet where the value has exactly the
same format as the `onion_packet` with a smaller `hops_data`.

The `trampoline_hops_data` field is a list of `trampoline_hop_payload`s. A
`trampoline_hop_payload` is a structure that holds obfuscations of the next
trampoline hop's address, transfer information, and its associated HMAC. It
uses the same format as the `onion_packet`'s variable-size `per_hop` payload,
meaning that it can contain an arbitrary TLV stream:

1. type: `trampoline_hops_data`
2. data:
   * [`n1`:`trampoline_hop_payload`]
   * [`n2`:`trampoline_hop_payload`]
   * ...
   * `filler`

Each `trampoline_hop_payload` has the following structure:

1. type: `trampoline_hop_payload`
2. data:
   * [`var_int`:`length`]
   * [`length`:`tlv_stream`]
   * [`32`:`hmac`]

The `tlv_stream` contains data necessary to route to the next trampoline hop.
The following types MAY be used to encode that data:

* type: `node_id`
* data:
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`node_id`]
* type: `amount_msat`
* data:
  * [`1`:`0x04`] (`type`)
  * [`1`:`length`]
  * [`length`:`amount_msat_value`]
* type: `cltv`
* data:
  * [`1`:`0x06`] (`type`)
  * [`1`:`length`]
  * [`length`:`cltv_value`]

### Usage

A node that wants to rely on trampoline nodes to relay payments may use a
`trampoline_onion_packet` in the TLV stream of the _last_ hop of an
`onion_packet`:

1. type: `onion_packet`
2. data:
   * [`1`:`version`]
   * [`33`:`public_key`]
   * [`n1`:`hop_payload`] (normal hop payload)
   * [`n2`:`hop_payload`] (normal hop payload)
   * ...
   * [`n`:`hop_payload`] (hop payload containing a `trampoline_onion_packet`)
   * `filler`
   * [`32`:`hmac`]

The structure of the _last_ `hop_payload` is:

1. type: `hop_payload`
2. data:
   * [`var_int`:`length`]
   * [`742`:`trampoline_onion_packet`]
   * `optional TLVs can be added here`
   * [`32`:`hmac`]

### Paying to non-trampoline nodes

If the recipient of the payment doesn't support trampoline routing, we rely on
the last trampoline node to convert the last hop to a standard onion payment.

The last `trampoline_hop_payload` must contain a `recipient_info` TLV packet
with the following structure:

1. type: `recipient_info`
2. data:
   * [`1`:`0x0a`] (`type`)
   * [`1`:`0x01`] (`length`)
   * [`1`:`0x00`] (`option_trampoline_routing`)

Note that it reveals the identity of the recipient and the amount paid to the
last trampoline node (but it doesn't reveal the identity of the payer).
This can be avoided if the recipient uses rendezvous routing to hide its
identity. Otherwise recipients should support `option_trampoline_routing` to
preserve their anonymity (and can advertise a high `fee` if they don't want to
route too many payments).

### Requirements

A sending node:

* MUST verify that each hop in the `trampoline_onion_packet` supports `option_trampoline_routing`
* MUST include a `recipient_info` with `option_trampoline_routing` set to `0x00` TLV if the recipient doesn't support `option_trampoline_routing`
* MUST encrypt the `trampoline_onion_packet` with the same construction as `onion_packet`
* MUST use a different `session_key` for the `trampoline_onion_packet` and the `onion_packet`
* MAY use other TLV types than `node_id`, `amount_msat` and `cltv` in the `trampoline_hop_payload`
* MAY include additional TLV types in `trampoline_hop_payload`s
* MUST put the `trampoline_onion_packet` in the _last_ hop's payload of the `onion_packet`

When processing a `trampoline_onion_packet`, a receiving node:

* If it doesn't support `option_trampoline_routing`:
  * MUST report a route failure to the origin node
* MUST process the `trampoline_onion_packet` as an `onion_packet`
* If it encounters an unknown _even_ TLV type inside the `trampoline_onion_packet`:
  * MUST report a route failure to the origin node
* If it doesn't have enough data to locate the next hop:
  * MUST report a route failure to the origin node
* MUST compute a route to the next trampoline hop:
  * If it cannot find a route that satisfies `cltv` requirements:
    * MUST report a route failure to the origin node
  * If it cannot find a route that satisfies `fees` requirements:
    * MUST report a route failure to the origin node
  * If it has a channel open with the next trampoline hop:
    * MAY use that channel to build a single-hop route
  * If a `recipient_info` TLV is received with `option_trampoline_routing` set to `0x00`:
    * MUST convert the peeled `trampoline_onion_packet` to an `onion_packet`
  * Otherwise:
    * MUST include the peeled `trampoline_onion_packet` in the last `hop_payload`
* SHOULD return errors as specified in the [error handling section](#returning-errors)

### Rationale

This construction allows nodes with an incomplete view of the network to
delegate the construction of parts of the route to trampoline nodes.

The origin node only needs to select a set of trampoline nodes and to know a
route to the first trampoline node. Each trampoline node is responsible for
finding its own route to the next trampoline node. Trampoline nodes only know
the previous node (which may or may not be a trampoline node) and the next
trampoline node, which guarantees payment anonymity.

The `trampoline_onion_packet` has a fixed size to prevent trampoline nodes from
inferring the number of trampolines used. It uses the same onion construction
as the `onion_packet`.

Trampoline nodes are free to use as many hops as they want between themselves
as long as they are able to create a route that satisfies the `cltv` and `fees`
requirements. This includes doing a single-hop payment to the next trampoline
node if they have a suitable channel available.

The `trampoline_hop_payload` may use the `node_id`, `amount_msat` and `cltv`
types to specify the data necessary to create a payment to the next trampoline
node.
It is not mandatory to use these types: another encoding may be used (e.g. if a
more compact way of addressing a node than its `node_id` is available).

The packet size was chosen to allow up to 8 intermediate trampoline nodes and
up to 10 intermediate nodes between trampoline nodes.

## Fees and CLTV requirements

Sending a payment using trampoline routing requires that every trampoline node
receives high enough `fees` and `cltv` to route to the next trampoline node.

Consider the following nodes and channels:

```text
   H1 -- H2    H4
  /        \  /  \
T1          T2    T3
  \        /  \  /
   `---- H3    H5
```

Each advertises the following `cltv_expiry_delta` on its end of every channel:

* H1: 10 blocks
* H2: 20 blocks
* H3: 30 blocks
* H4: 40 blocks
* H5: 50 blocks
* T1: 60 blocks
* T2: 70 blocks
* T3: 80 blocks

T3 also uses a `min_final_cltv_expiry` of 9 (the default) when requesting payments.

Also, each node has a set fee scheme that it uses for each of its channels:

* H1: 100 base + 1000 millionths
* H2: 200 base + 2000 millionths
* H3: 300 base + 3000 millionths
* H4: 400 base + 4000 millionths
* H5: 500 base + 5000 millionths
* T1: 600 base + 6000 millionths
* T2: 700 base + 7000 millionths
* T3: 800 base + 8000 millionths

Let's assume that Alice wants to send a payment of `5000` satoshis to T3 with a
randomized cltv expiry of 42.

**T2->T3:**

T2 has two routes to T3, either via H4 or H5.

Routing via H4 requires the following values:

* H4:
  * `amount_msat` = 5000000 + 400 + ( 4000 * 5000000 / 1000000 ) = 5020400
  * `cltv_expiry` = current-block-height + 40 + 42 + 9
  * `onion_packet`:
    * `amt_to_forward` = 5000000
    * `outgoing_cltv_value` = current-block-height + 42 + 9
* T2:
  * `amount_msat` = 5020400 + 700 + ( 7000 * 5020400 / 1000000 ) = 5056243
  * `cltv_expiry` = current-block-height + 70 + 40 + 42 + 9
  * `onion_packet`:
    * `amt_to_forward` = 5020400
    * `outgoing_cltv_value` = current-block-height + 40 + 42 + 9

Routing via H5 requires the following values:

* H5:
  * `amount_msat` = 5000000 + 500 + ( 5000 * 5000000 / 1000000 ) = 5025500
  * `cltv_expiry` = current-block-height + 50 + 42 + 9
  * `onion_packet`:
    * `amt_to_forward` = 5000000
    * `outgoing_cltv_value` = current-block-height + 42 + 9
* T2:
  * `amount_msat` = 5025500 + 700 + ( 7000 * 5025500 / 1000000 ) = 5061379
  * `cltv_expiry` = current-block-height + 70 + 50 + 42 + 9
  * `onion_packet`:
    * `amt_to_forward` = 5025500
    * `outgoing_cltv_value` = current-block-height + 50 + 42 + 9

T2 may advertise the following values for routing trampoline payments which
allows it to use either of these routes:

* `fees`: 1200 base + 12500 millionths
* `cltv_expiry_delta`: 120 blocks

T2->T3 then requires the following trampoline values:

* `amount_msat` = 5000000 + 1200 + ( 12500 * 5000000 / 1000000 ) = 5063700
* `cltv_expiry` = current-block-height + 120 + 42 + 9
* `trampoline_onion_packet`:
  * `amt_to_forward` = 5000000
  * `outgoing_cltv_value` = current-block-height + 42 + 9

**T1->T2:**

T1 has two routes to T2, either via H1 then H2 or via H3.

Routing via H1 then H2 requires the following values:

* H2:
  * `amount_msat` = 5063700 + 200 + ( 2000 * 5063700 / 1000000 ) = 5074028
  * `cltv_expiry` = current-block-height + 20 + 120 + 42 + 9
  * `onion_packet`:
    * `amt_to_forward` = 5063700
    * `outgoing_cltv_value` = current-block-height + 120 + 42 + 9
* H1:
  * `amount_msat` = 5074028 + 100 + ( 1000 * 5074028 / 1000000 ) = 5079203
  * `cltv_expiry` = current-block-height + 10 + 20 + 120 + 42 + 9
  * `onion_packet`:
    * `amt_to_forward` = 5074028
    * `outgoing_cltv_value` = current-block-height + 20 + 120 + 42 + 9
* T1:
  * `amount_msat` = 5079203 + 600 + ( 6000 * 5079203 / 1000000 ) = 5110279
  * `cltv_expiry` = current-block-height + 60 + 10 + 20 + 120 + 42 + 9
  * `onion_packet`:
    * `amt_to_forward` = 5079203
    * `outgoing_cltv_value` = current-block-height + 10 + 20 + 120 + 42 + 9

Routing via H3 requires the following values:

* H3:
  * `amount_msat` = 5063700 + 300 + ( 3000 * 5063700 / 1000000 ) = 5079192
  * `cltv_expiry` = current-block-height + 30 + 120 + 42 + 9
  * `onion_packet`:
    * `amt_to_forward` = 5063700
    * `outgoing_cltv_value` = current-block-height + 120 + 42 + 9
* T1:
  * `amount_msat` = 5079192 + 600 + ( 6000 * 5079192 / 1000000 ) = 5110268
  * `cltv_expiry` = current-block-height + 60 + 30 + 120 + 42 + 9
  * `onion_packet`:
    * `amt_to_forward` = 5079192
    * `outgoing_cltv_value` = current-block-height + 30 + 120 + 42 + 9

T1 may advertise the following values for routing trampoline payments which
allows it to use either of these routes:

* `fees`: 900 base + 9500 millionths
* `cltv_expiry_delta`: 90 blocks

T1->T2 then requires the following trampoline values:

* `amount_msat` = 5063700 + 900 + ( 9500 * 5063700 / 1000000 ) = 5112706
* `cltv_expiry` = current-block-height + 90 + 120 + 42 + 9
* `trampoline_onion_packet`:
  * `amt_to_forward` = 5063700
  * `outgoing_cltv_value` = current-block-height + 120 + 42 + 9

## Network Pruning

TODO: this section is not in spec format at all. It's a draft of the overall
ideas to make sure we agree on the path forward before starting a spec effort.

Nodes running on constrained devices (phones, IoT, etc) should only keep track
of nearby channels (with an `N`-radius heuristic for example). These nearby
channels will be used to build a v0 onion route to a first trampoline node.

Constrained nodes may also choose to ignore channels with a capacity lower than
`min_chan_capacity`. `N` and `min_chan_capacity` are configured by the node and
not advertised to the network.

Constrained nodes would simply ignore `channel_announcement`s that don't meet
those requirements.

Constrained nodes would also need to store information about nodes that are
outside of their network view to use as trampolines.

Trampoline nodes on the contrary should keep a full view of the network
topology to be able to efficiently route payments.

### The `node_update` Message

We introduce a new optional `node_update` message with the following structure:

1. type: 261 (`node_update`)
2. data:
   * [`varint`:`length`]
   * [`1`:`0x02`] (`type`)
   * [`1`:`0x21`] (`length`)
   * [`33`:`node_id`]
   * [`1`:`0x04`] (`type`)
   * [`1`:`0x40`] (`length`)
   * [`64`:`signature`]
   * [`1`:`0x06`] (`type`)
   * [`1`:`0x20`] (`length`)
   * [`32`:`chain_hash`]
   * [`1`:`0x08`] (`type`)
   * [`1`:`0x1e`] (`length`)
   * [`4`:`timestamp`]
   * [`2`:`cltv_expiry_delta`]
   * [`8`:`htlc_minimum_msat`]
   * [`8`:`htlc_maximum_msat`]
   * [`4`:`fee_base_msat`]
   * [`4`:`fee_proportional_millionths`]

It has a structure similar to the `channel_update` message but is channel
agnostic. `Node_update`s should be relayed the same way `channel_update`s are
relayed (staggered broadcast).

Trampoline nodes should only accept and relay `node_update`s from nodes that
have open channels with inbound and outbound capacity.

If a node is not willing to relay trampoline payments, it will simply never
send a `node_update`. This lets the network discriminate nodes that are able to
relay trampoline payments from nodes that understand the format but use it only
as senders or recipients.

### Fees and CLTV estimation

Trampoline nodes need to estimate a `cltv_expiry_delta` and `fee` that would
allow them to route to any other trampoline node while being competitive with
other nodes. This is a great opportunity to incentivize nodes to open channels
between each other to minimize the cost of trampoline hops. This is also a
great opportunity for nodes to implement smart fee estimation algorithms as
a competitive advantage.

Nodes may be very conservative and advertise their worst case `fee` and
`cltv_expiry_delta`, corresponding to the furthest node they can reach.

On the contrary, nodes may apply statistical analysis of the network to find
a lower `fee` and `cltv_expiry_delta` that would not allow them to reach all
other trampoline nodes but would work for most cases. Such nodes may choose to
route some payments at a loss to keep reliability high, attract more payments
by building a reliability reputation and benefit from an overall gain.

Nodes may include some of their preferred neighbours in `node_update`, implying
that they're able to route cheaply to these nodes. Payers may or may not use
that information.

Trampoline nodes may accept payments with a fee lower than what they advertised
if they're still able to route the payment in an economically viable way
(because they have a direct channel or a low-cost route to the next trampoline
hop for example).

That means that payers may choose to ignore advertised fees entirely if they
think the fee/cltv they're using will still be able to route properly.

See the [Fees and CLTV requirements](#fees-and-clvt-requirements) section for a
detailed example of fees calculation.

### Filtering gossip messages

Constrained nodes should listen to `node_update` messages and store some of
them to be used as trampolines. Nodes are free to choose their own heuristics
for trampoline node selection (some randomness is desired for anonymity).

While this reduces storage requirements on constrained nodes, it doesn't reduce
their bandwidth requirements: constrained nodes still need to listen to
`node_update` and `channel_update` messages (even though they will ignore most
of them).

We introduce gossip filters that should be applied before gossip retransmission.
A constrained node would connect only to remote nodes that support
`option_gossip_filters`. It would then negotiate the filters with that remote
node. When receiving gossip messages, the remote node would apply the filters
and only forward to the local node the entries that match the filter.

Note that the remote node can decide to ignore the filters entirely and forward
every gossip to the local node: in that case the local node may close all its
channels with that remote node, fail the connection and open channels to more
cooperative nodes.

TODO: detail `init` phase and filter negotiation requirements if agree on the
idea.

#### The `channel_update_filter`

The local node may send a `channel_update_filter` to the remote node.
The remote node should apply this filter before forwarding `channel_update`s.
This allows the local node to keep an up-to-date view of only a small portion
of the network.

The filter could simply be a `distance` integer. The remote node should only
forward `channel_update`s of nodes that are at most `distance` hops away from
the remote node itself.

Computing this filter is inexpensive for small `distance`s. The remote node
should reject `distance`s that would be too costly to evaluate.

TODO: detail message format if agree on the idea

#### The `node_update_filter`

The local node may send a `node_update_filter` to the remote node.
The remote node should apply this filter before forwarding `node_update`s.
This allows the local node to only receive `node_update`s it cares about to
periodically refresh its list of trampoline nodes and stay up-to-date with
their fee rate and cltv.

The local node may choose to keep the same set of trampoline nodes if they are
reliable enough. Or the local node may choose to rotate its set of trampoline
nodes regularly to improve anonymity and test new payment paths. This decision
should be configurable by the user / implementation.

A simple heuristic to frequently rotate the set of trampoline nodes would be
to compare their `node_id` to `sha256(local_node_id || latest_block_hash)` and
update this every `N` blocks. The `node_update_filter` could be based on the
distance between these two values. Then the local node chooses which trampoline
nodes to keep depending on their advertised fees/cltv and reliability
reputation (based on historical data if it's possible to collect such data).

TODO: detail message format if agree on the idea

## Examples

### Merchant supporting trampoline payments

Bob is a merchant that supports trampoline payments. Bob creates an invoice for
`5000` satoshis and includes in the invoice three of his neighbours that
support trampoline routing (TB1, TB2 and TB3).

Alice wants to pay this invoice using trampoline routing. Alice selects a first
trampoline node to which she knows a route (TA1). She then selects another
trampoline node TA2 (that may or may not be in her neighbourhood) and one of
the trampoline nodes from the invoice (e.g. TB3).

The trampoline route is:

```text
Alice -> TA1 -> TA2 -> TB3 -> Bob
```

TA1's latest `node_update` advertised `cltv_expiry_delta=20` and `fee=3000` msat.
TA2's latest `node_update` advertised `cltv_expiry_delta=15` and `fee=2000` msat.
TB3's details in the invoice specified `cltv_expiry_delta=30` and `fee=1000` msat.

Note: for simplicity we act as if the fee was a single fixed value.

Alice creates the following `trampoline_onion_packet` (encryption omitted for
clarity):

* [`1`:`0x08`] (`type`)
* [`3`:`0xfde202`] (`length`)
* [`1`:`version`]
* [`33`:`public_key`]
* [`76`:`trampoline_hop_payload`] (payload for TA1)
  * [`1`:`0x4b`] (`length`)
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`TA2_node_id`]
  * [`1`:`0x04`] (`type`)
  * [`1`:`0x03`] (`length`)
  * [`3`:`5003000`] (`amt_to_forward`)
  * [`1`:`0x06`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`70`] (`outgoing_cltv_value`)
  * [`32`:`hmac`]
* [`76`:`trampoline_hop_payload`] (payload for TA2)
  * [`1`:`0x4b`] (`length`)
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`TB3_node_id`]
  * [`1`:`0x04`] (`type`)
  * [`1`:`0x03`] (`length`)
  * [`3`:`5001000`] (`amt_to_forward`)
  * [`1`:`0x06`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`55`] (`outgoing_cltv_value`)
  * [`32`:`hmac`]
* [`76`:`trampoline_hop_payload`] (payload for TB3)
  * [`1`:`0x4b`] (`length`)
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`Bob_node_id`]
  * [`1`:`0x04`] (`type`)
  * [`1`:`0x03`] (`length`)
  * [`3`:`5000000`] (`amt_to_forward`)
  * [`1`:`0x06`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`25`] (`outgoing_cltv_value`)
  * [`32`:`hmac`]
* [`76`:`trampoline_hop_payload`] (payload for Bob)
  * [`1`:`0x4b`] (`length`)
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`Bob_node_id`]
  * [`1`:`0x04`] (`type`)
  * [`1`:`0x03`] (`length`)
  * [`3`:`5000000`] (`payment_amt`)
  * [`1`:`0x06`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`25`] (`final_cltv_expiry`)
  * [`32`:`hmac`] (`0x00...00`)
* [`368`:`filler`]
* [`32`:`hmac`]

Alice finds a route to TA1 thanks to her view of her neighbourhood:

```text
Alice -> H1 -> H2 -> TA1
```

For simplicity, we assume that all intermediate nodes `Hi` advertise a fixed
`500` msat `fee` and `cltv_expiry_delta=5`.

Alice creates the following `onion_packet` (encryption omitted for clarity):

* [`1`:`0x00`] (`version`)
* [`33`:`public_key`]
* [`65`:`hop_payload`] (payload for H1)
  * [`1`:`0x00`] (`realm`)
  * [`8`:`channel_from_H1_to_H2`] (`short_channel_id`)
  * [`8`:`5006500`] (`amt_to_forward`)
  * [`4`:`95`] (`outgoing_cltv_value`)
  * [`12`:`padding`]
  * [`32`:`hmac`]
* [`65`:`hop_payload`] (payload for H2)
  * [`1`:`0x00`] (`realm`)
  * [`8`:`channel_from_H2_to_TA1`] (`short_channel_id`)
  * [`8`:`5006000`] (`amt_to_forward`)
  * [`4`:`90`] (`outgoing_cltv_value`)
  * [`12`:`padding`]
  * [`32`:`hmac`]
* [`777`:`hop_payload`] (payload for TA1)
  * [`3`:`0xfde602`] (`length`)
  * [`742`:`trampoline_onion_packet`]
  * [`32`:`hmac`] (`0x00...00`)
* [`393`:`filler`]
* [`32`:`hmac`]

H1 and H2 forward the `onion_packet` like any other `onion_packet` and do not
know that it is destined for trampoline routing.

TA1 receives the `onion_packet` and discovers a `trampoline_onion_packet` TLV.
TA1 is able to peel one layer of the `trampoline_onion_packet` and discover the
next trampoline hop (TA2).

TA1 finds a route to TA2:

```text
TA1 -> H3 -> H4 -> TA2
```

TA1 creates the following `onion_packet` (encryption omitted for clarity):

* [`1`:`0x00`] (`version`)
* [`33`:`public_key`]
* [`65`:`hop_payload`] (payload for H3)
  * [`1`:`0x00`] (`realm`)
  * [`8`:`channel_from_H3_to_H4`] (`short_channel_id`)
  * [`8`:`5003500`] (`amt_to_forward`)
  * [`4`:`75`] (`outgoing_cltv_value`)
  * [`12`:`padding`]
  * [`32`:`hmac`]
* [`65`:`hop_payload`] (payload for H4)
  * [`1`:`0x00`] (`realm`)
  * [`8`:`channel_from_H4_to_TA2`] (`short_channel_id`)
  * [`8`:`5003000`] (`amt_to_forward`)
  * [`4`:`70`] (`outgoing_cltv_value`)
  * [`12`:`padding`]
  * [`32`:`hmac`]
* [`777`:`hop_payload`] (payload for TA2)
  * [`3`:`0xfde602`] (`length`)
  * [`742`:`trampoline_onion_packet`] (with the TA1 layer peeled)
  * [`32`:`hmac`] (`0x00...00`)
* [`393`:`filler`]
* [`32`:`hmac`]

TA1 has effectively earned a fee of `2000` msat (`3000` msat received and
`1000` msat payed to route to TA2).

H3 and H4 forward the `onion_packet` like any other `onion_packet` and do not
know that it is destined for trampoline routing.

TA2 receives the `onion_packet` and discovers a `trampoline_onion_packet` TLV.
TA2 is able to peel one layer of the `trampoline_onion_packet` and discover the
next trampoline hop (TB3).

TA2 has a channel to TB3, so it creates the following `onion_packet` (encryption
omitted for clarity):

* [`1`:`0x00`] (`version`)
* [`33`:`public_key`]
* [`777`:`hop_payload`] (payload for TB3)
  * [`3`:`0xfde602`] (`length`)
  * [`742`:`trampoline_onion_packet`] (with the TA2 layer peeled)
  * [`32`:`hmac`] (`0x00...00`)
* [`523`:`filler`]
* [`32`:`hmac`]

TA2 has effectively earned a fee of `2000` msat (`2000` msat received and no
additional routing cost since it has a channel to TB3).

TB3 receives the `onion_packet` and discovers a `trampoline_onion_packet` TLV.
TB3 is able to peel one layer of the `trampoline_onion_packet` and discover the
next trampoline hop (Bob). TB3 doesn't know that Bob is the final recipient.

TB3 finds a route to Bob:

```text
TB3 -> H5 -> Bob
```

TB3 creates the following `onion_packet` (encryption omitted for clarity):

* [`1`:`0x00`] (`version`)
* [`33`:`public_key`]
* [`65`:`hop_payload`] (payload for H5)
  * [`1`:`0x00`] (`realm`)
  * [`8`:`channel_from_H5_to_Bob`] (`short_channel_id`)
  * [`8`:`5000000`] (`amt_to_forward`)
  * [`4`:`25`] (`outgoing_cltv_value`)
  * [`12`:`padding`]
  * [`32`:`hmac`]
* [`777`:`hop_payload`] (payload for Bob)
  * [`3`:`0xfde602`] (`length`)
  * [`742`:`trampoline_onion_packet`] (with the TB3 layer peeled)
  * [`32`:`hmac`] (`0x00...00`)
* [`458`:`filler`]
* [`32`:`hmac`]

TB3 has effectively earned a fee of `500` msat (`1000` msat received and `500`
msat payed to route to Bob).

Bob receives the `onion_packet` and discovers a `trampoline_onion_packet` TLV.
Bob is able to peel one layer of the `trampoline_onion_packet` and discover
that he is the recipient of the payment (because the hmac is `0x00...00`).

The effective payment route is:

```text
Alice                 TA1                  TA2 -> TB3         Bob
  |                   ^ |                   ^      |           ^
  |                   | |                   |      |           |
  `---> H1 ---> H2 ---' `---> H3 ---> H4 ---'      `---> H5 ---'
```

### Merchant without trampoline support

Bob is a merchant that doesn't support trampoline payments. Bob creates an
invoice for `5000` satoshis without any routing hint.

Alice wants to pay this invoice using trampoline routing. To make the example
short Alice will select a single trampoline hop T.

The trampoline route is:

```text
Alice -> T -> Bob
```

T's latest `node_update` advertised `cltv_expiry_delta=20` and `fee=3000` msat.

Note: for simplicity we act as if the fee was a single fixed value. We also
assume that all intermediate nodes `Hi` advertise a `500` msat `fee` and
`cltv_expiry_delta=5`.

Alice creates the following `trampoline_onion_packet` (encryption omitted for
clarity):

* [`1`:`0x08`] (`type`)
* [`3`:`0xfde202`] (`length`)
* [`1`:`version`]
* [`33`:`public_key`]
* [`79`:`trampoline_hop_payload`] (payload for T)
  * [`1`:`0x4e`] (`length`)
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`Bob_node_id`]
  * [`1`:`0x04`] (`type`)
  * [`1`:`0x03`] (`length`)
  * [`3`:`5000000`] (`amt_to_forward`)
  * [`1`:`0x06`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`25`] (`outoing_cltv_value`)
  * [`1`:`0x0a`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`0x00`] (`option_trampoline_routing`)
  * [`32`:`hmac`] (`0x00...00`)
* [`593`:`filler`]
* [`32`:`hmac`]

Alice finds a route to T and sends the `trampoline_onion_packet` wrapped inside
an `onion_packet` (see previous example).

T receives the `trampoline_onion_packet` and discovers that Bob is the payment
recipient and doesn't support `option_trampoline_routing`.

T finds a route to Bob:

```text
T -> H1 -> H2 -> Bob
```

T creates the following `onion_packet` (encryption omitted for clarity):

* [`1`:`0x00`] (`version`)
* [`33`:`public_key`]
* [`65`:`hop_payload`] (payload for H1)
  * [`1`:`0x00`] (`realm`)
  * [`8`:`channel_from_H1_to_H2`] (`short_channel_id`)
  * [`8`:`5000500`] (`amt_to_forward`)
  * [`4`:`30`] (`outgoing_cltv_value`)
  * [`12`:`padding`]
  * [`32`:`hmac`]
* [`65`:`hop_payload`] (payload for H2)
  * [`1`:`0x00`] (`realm`)
  * [`8`:`channel_from_H2_to_Bob`] (`short_channel_id`)
  * [`8`:`5000000`] (`amt_to_forward`)
  * [`4`:`25`] (`outgoing_cltv_value`)
  * [`12`:`padding`]
  * [`32`:`hmac`]
* [`65`:`hop_payload`] (payload for Bob)
  * [`1`:`0x00`] (`realm`)
  * [`8`:`0x0000000000000000`] (`short_channel_id`)
  * [`8`:`5000000`] (`payment_amt`)
  * [`4`:`25`] (`final_cltv_expiry`)
  * [`12`:`padding`]
  * [`32`:`hmac`] (`0x00...00`)
* [`1105`:`filler`]
* [`32`:`hmac`]

Bob receives the `onion_packet` and discovers that he is the recipient of the
payment (because the hmac is `0x00...00`). Bob can process the payment and
doesn't know trampoline routing was used.

The effective payment route is:

```text
Alice      T                   Bob
  |       ^ |                   ^
  |       | |                   |
  `-------' `---> H1 ---> H2 ---'
```

## References

[rendezvous]: https://github.com/lightningnetwork/lightning-rfc/wiki/Rendez-vous-mechanism-on-top-of-Sphinx