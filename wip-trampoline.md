# Trampoline Onion Routing

This file contains the whole proposal to simplify reviewers life.
Once we make progress towards standardization, we may move these sections and
include them in the existing bolts.

## Table of Contents

* [Features](#features)
* [Packet Structure](#packet-structure)
  * [Trampoline Onion](#trampoline-onion)
  * [Paying via trampoline nodes](#paying-via-trampoline-nodes)
  * [Failure messages](#failure-messages)
* [Multi-Part Trampoline](#multi-part-trampoline)
* [Routing Gossip](#routing-gossip)
  * [The `node_update` Message](#the-node_update-message)
  * [Filtering gossip messages](#filtering-gossip-messages)
* [Fees and CLTV requirements](#fees-and-cltv-requirements)
* [Appendix A: Examples](#appendix-a-examples)
  * [Merchant supporting trampoline payments](#merchant-supporting-trampoline-payments)

## Features

Trampoline routing uses the following `features` flags:

| Bits  | Name                 | Description                                        | Context | Link |
|-------|----------------------|----------------------------------------------------|---------|------|
| 50/51 | `trampoline_routing` | This node requires/supports trampoline routing     | IN9     |      |
| 52/53 | `gossip_filters`     | This node requires/supports gossip message filters | IN      |      |

Feature flags are assigned in pairs, but the mandatory value may not be applicable here.

## Packet Structure

### Trampoline Onion

The trampoline onion is a fixed-size tlv packet with the following structure:

1. type: 14 (`trampoline_onion_packet`)
2. data:
   * [`byte`:`version`]
   * [`point`:`public_key`]
   * [`400*byte`:`hop_payloads`]
   * [`32*byte`:`hmac`]

This results in a `466`-bytes fixed-size tlv where the value has exactly the same format as the `onion_packet` with
a smaller `hop_payloads` (`400` bytes instead of `1300`).

Trampoline `hop_payload`s may contain the following fields:

1. tlvs: `trampoline_payload`
2. types:
    * type: 2 (`amt_to_forward`)
    * data:
        * [`tu64`:`amt_to_forward`]
    * type: 4 (`outgoing_cltv_value`)
    * data:
        * [`tu32`:`outgoing_cltv_value`]
    * type: 8 (`payment_data`)
        * [`32*byte`:`payment_secret`]
        * [`tu64`:`total_msat`]
    * type: 10 (`outgoing_node_id`)
    * data:
        * [`point`:`outgoing_node_id`]

### Paying via trampoline nodes

A recipient can signal support for receiving trampoline payments by setting the `trampoline_routing` feature bit in
invoices. A sender that wants to pay that invoice may then rely on trampoline nodes to relay the payment by adding a
`trampoline_onion_packet` in the `hop_payload` of the _last_ hop of a normal `onion_packet`:

1. type: `onion_packet`
2. data:
   * [`byte`:`version`]
   * [`point`:`public_key`]
   * [`n1*byte`:`hop_payload`] (normal hop payload)
   * [`n2*byte`:`hop_payload`] (normal hop payload)
   * ...
   * [`nn*byte`:`hop_payload`] (hop payload containing a `trampoline_onion_packet`)
   * `filler`
   * [`32*byte`:`hmac`]

### Failure messages

The following new `failure_code`s are defined:

1. type: NODE|51 (`trampoline_fee_insufficient`)
2. data:
   * [`u16`:`len`]
   * [`len*byte`:`node_update`]

The fee amount was below that required by the processing node to forward to the next node.

1. type: NODE|52 (`trampoline_expiry_too_soon`)
2. data:
   * [`u16`:`len`]
   * [`len*byte`:`node_update`]

The `outgoing_cltv_value` was too close to the incoming `cltv_expiry` to safely forward to the next node.

Question: should we define a new flag similar to `UPDATE` that implies that a `node_update` is enclosed?
Or extend the `UPDATE` flag?

### Requirements

A sending node:

* If the invoice doesn't support the `trampoline_routing` feature:
  * MUST NOT use trampoline routing to pay that invoice
* MUST verify that each hop in the `trampoline_onion_packet` supports `trampoline_routing`
* MUST encrypt the `trampoline_onion_packet` with the same construction as `onion_packet`
* MUST use a different `session_key` for the `trampoline_onion_packet` and the `onion_packet`
* MAY include additional tlv types in `trampoline_payload`s
* MUST include the `trampoline_onion_packet` tlv in the _last_ hop's payload of the `onion_packet`

When processing a `trampoline_onion_packet`, a receiving node:

* If it doesn't support `trampoline_routing`:
  * MUST report a route failure to the origin node
* MUST process the `trampoline_onion_packet` as an `onion_packet`
* If it encounters an unknown _even_ tlv type inside the `trampoline_onion_packet`:
  * MUST report a route failure to the origin node
* If it doesn't have enough data to locate the next hop:
  * MUST report a route failure to the origin node
* MUST compute a route to the next trampoline hop:
  * If it cannot find a route that satisfies `cltv` requirements:
    * MUST report a route failure to the origin node using the `trampoline_expiry_too_soon` error
  * If it cannot find a route that satisfies `fees` requirements:
    * MUST report a route failure to the origin node using the `trampoline_fee_insufficient` error
  * Otherwise:
    * MUST include the peeled `trampoline_onion_packet` in the last `hop_payload`
* MUST return errors as specified in Bolt 4's [error handling section](https://github.com/lightningnetwork/lightning-rfc/blob/master/04-onion-routing.md#returning-errors)

### Rationale

This construction allows nodes with an incomplete view of the network to delegate the construction of parts of the
route to trampoline nodes.

The origin node only needs to select a set of trampoline nodes and to know a route to the first trampoline node.
Each trampoline node is responsible for finding its own route to the next trampoline node.
Trampoline nodes only learn the previous node (which may or may not be a trampoline node) and the next trampoline node,
which guarantees the same anonymity as normal payments.

The `trampoline_onion_packet` has a fixed size to prevent trampoline nodes from inferring the number of trampoline hops
used. It uses the same onion construction as the `onion_packet`.

Trampoline nodes are free to use as many hops as they want between themselves as long as they are able to create a
route that satisfies the `cltv` and `fees` requirements. This includes doing a single-hop payment to the next
trampoline node if they have a suitable channel available.

The `trampoline_payload` may use the `outgoing_node_id`, `amt_to_forward` and `outgoing_cltv_value` tlv types to
specify the data necessary to create a payment to the next trampoline node. It is not mandatory to use these types:
another encoding may be used (e.g. if a more compact way of addressing a node than its `outgoing_node_id` is available).

## Multi-Part Trampoline

Trampoline routing combines nicely with multi-part payments. When multi-part payment is used, we can let trampoline
nodes combine all the incoming partial payments before forwarding. Once the totality of the payment is received, the
trampoline node can choose the most efficient way to re-split it to reach the next trampoline node.

### Requirements

A sending node:

* MUST include the final recipient's `payment_secret` (e.g. from a Bolt 11 invoice) in the trampoline onion
* MUST generate a different `payment_secret` to use in the outer onion

A processing node:

* MAY aggregate the incoming multi-part payment before forwarding
* If it uses a multi-part payment to forward to the next node:
  * MUST generate a different `payment_secret` to use in the outer onion

## Routing Gossip

Trampoline nodes advertise the `fee` and `cltv_expiry_delta` that would allow
them to route to other trampoline nodes via a `node_update` message.

### The `node_update` Message

The `node_update` message has the following structure:

1. type: 267 (`node_update`)
2. types:
    * type: 2 (`node_id`)
    * data:
        * [`point`:`node_id`]
    * type: 4 (`node_signature`)
    * data:
        * [`signature`:`node_signature`]
    * type: 6 (`chain_hash`)
    * data:
        * [`chain_hash`:`chain_hash`]
    * type: 8 (`update_data`)
    * data:
        * [`u32`:`timestamp`]
        * [`u16`:`cltv_expiry_delta`]
        * [`u32`:`fee_base_msat`]
        * [`u32`:`fee_proportional_millionths`]

It has a structure similar to the `channel_update` message but is channel agnostic.
`Node_update`s should be relayed the same way `channel_update`s are relayed (staggered broadcast).

### Filtering gossip messages

In order to reduce bandwidth consumption, nodes negotiate gossip filters during
`init`. These filters are applied before forwarding gossip messages (announcements
and updates).

TODO: detail `init` phase, filter negotiation and message format if we have a concept ack.

## Fees and CLTV requirements

Sending a payment using trampoline routing requires that every trampoline node receives high enough `fees` and `cltv`
to route to the next trampoline node.

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

Let's assume that Alice wants to send a payment of `5000` satoshis to T3 with a randomized cltv expiry of 42.

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

T2 may advertise the following values for routing trampoline payments which allows it to use either of these routes:

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

T1 may advertise the following values for routing trampoline payments which allows it to use either of these routes:

* `fees`: 900 base + 9500 millionths
* `cltv_expiry_delta`: 90 blocks

T1->T2 then requires the following trampoline values:

* `amount_msat` = 5063700 + 900 + ( 9500 * 5063700 / 1000000 ) = 5112706
* `cltv_expiry` = current-block-height + 90 + 120 + 42 + 9
* `trampoline_onion_packet`:
  * `amt_to_forward` = 5063700
  * `outgoing_cltv_value` = current-block-height + 120 + 42 + 9

## Appendix A: Examples

### Merchant supporting trampoline payments

Bob is a merchant that supports trampoline payments. Bob creates an invoice for `5000` satoshis and includes in the
invoice three of his neighbors that support trampoline routing (TB1, TB2 and TB3).

Alice wants to pay this invoice using trampoline routing. Alice selects a first trampoline node to which she knows a
route (TA1). She then selects another trampoline node TA2 (that may or may not be in her neighborhood) and one of
the trampoline nodes from the invoice (e.g. TB3).

The trampoline route is:

```text
Alice -> TA1 -> TA2 -> TB3 -> Bob
```

TA1's latest `node_update` advertised `cltv_expiry_delta=20` and `fee=3000` msat.
TA2's latest `node_update` advertised `cltv_expiry_delta=15` and `fee=2000` msat.
TB3's details in the invoice specified `cltv_expiry_delta=30` and `fee=1000` msat.

Note: for simplicity we act as if the fee was a single fixed value.

Alice creates the following `trampoline_onion_packet` (encryption omitted for clarity):

* [`1`:`0x0e`] (`type`)
* [`3`:`0xfd01d2`] (`length`)
* [`1`:`version`]
* [`33`:`public_key`]
* [`76`:`hop_payload`] (payload for TA1)
  * [`1`:`0x4b`] (`length`)
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x03`] (`length`)
  * [`3`:`5003000`] (`amt_to_forward`)
  * [`1`:`0x04`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`70`] (`outgoing_cltv_value`)
  * [`1`:`0x0a`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`TA2_node_id`]
  * [`32`:`hmac`]
* [`76`:`hop_payload`] (payload for TA2)
  * [`1`:`0x4b`] (`length`)
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x03`] (`length`)
  * [`3`:`5001000`] (`amt_to_forward`)
  * [`1`:`0x04`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`55`] (`outgoing_cltv_value`)
  * [`1`:`0x0a`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`TB3_node_id`]
  * [`32`:`hmac`]
* [`76`:`hop_payload`] (payload for TB3)
  * [`1`:`0x4b`] (`length`)
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x03`] (`length`)
  * [`3`:`5000000`] (`amt_to_forward`)
  * [`1`:`0x04`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`25`] (`outgoing_cltv_value`)
  * [`1`:`0x0a`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`Bob_node_id`]
  * [`32`:`hmac`]
* [`76`:`hop_payload`] (payload for Bob)
  * [`1`:`0x4b`] (`length`)
  * [`1`:`0x02`] (`type`)
  * [`1`:`0x03`] (`length`)
  * [`3`:`5000000`] (`payment_amt`)
  * [`1`:`0x04`] (`type`)
  * [`1`:`0x01`] (`length`)
  * [`1`:`25`] (`final_cltv_expiry`)
  * [`1`:`0x0a`] (`type`)
  * [`1`:`0x21`] (`length`)
  * [`33`:`Bob_node_id`]
  * [`32`:`hmac`] (`0x00...00`)
* [`96`:`filler`]
* [`32`:`hmac`]

Alice finds a route to TA1 thanks to her view of her neighborhood:

```text
Alice -> H1 -> H2 -> TA1
```

For simplicity, we assume that all intermediate nodes `Hi` advertise a fixed `500` msat `fee` and `cltv_expiry_delta=5`.

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
* [`505`:`hop_payload`] (payload for TA1)
  * [`3`:`0xfd01d6`] (`length`)
  * [`470`:`trampoline_onion_packet`]
  * [`32`:`hmac`] (`0x00...00`)
* [`665`:`filler`]
* [`32`:`hmac`]

H1 and H2 forward the `onion_packet` like any other `onion_packet` and do not know that it is destined for trampoline
routing.

TA1 receives the `onion_packet` and discovers a `trampoline_onion_packet` tlv. TA1 is able to peel one layer of the
`trampoline_onion_packet` and discover the next trampoline hop (TA2).

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
* [`505`:`hop_payload`] (payload for TA2)
  * [`3`:`0xfd01d6`] (`length`)
  * [`470`:`trampoline_onion_packet`] (with the TA1 layer peeled)
  * [`32`:`hmac`] (`0x00...00`)
* [`665`:`filler`]
* [`32`:`hmac`]

TA1 has effectively earned a fee of `2000` msat (`3000` msat received and `1000` msat payed to route to TA2).

H3 and H4 forward the `onion_packet` like any other `onion_packet` and do not know that it is destined for trampoline
routing.

TA2 receives the `onion_packet` and discovers a `trampoline_onion_packet` tlv. TA2 is able to peel one layer of the
`trampoline_onion_packet` and discover the next trampoline hop (TB3).

TA2 has a channel to TB3, so it creates the following `onion_packet` (encryption omitted for clarity):

* [`1`:`0x00`] (`version`)
* [`33`:`public_key`]
* [`505`:`hop_payload`] (payload for TB3)
  * [`3`:`0xfd01d6`] (`length`)
  * [`470`:`trampoline_onion_packet`] (with the TA2 layer peeled)
  * [`32`:`hmac`] (`0x00...00`)
* [`895`:`filler`]
* [`32`:`hmac`]

TA2 has effectively earned a fee of `2000` msat (`2000` msat received and no additional routing cost since it has a
channel to TB3).

TB3 receives the `onion_packet` and discovers a `trampoline_onion_packet` tlv. TB3 is able to peel one layer of the
`trampoline_onion_packet` and discover the next trampoline hop (Bob). TB3 doesn't know that Bob is the final recipient.

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
* [`505`:`hop_payload`] (payload for Bob)
  * [`3`:`0xfd01d6`] (`length`)
  * [`470`:`trampoline_onion_packet`] (with the TB3 layer peeled)
  * [`32`:`hmac`] (`0x00...00`)
* [`830`:`filler`]
* [`32`:`hmac`]

TB3 has effectively earned a fee of `500` msat (`1000` msat received and `500` msat payed to route to Bob).

Bob receives the `onion_packet` and discovers a `trampoline_onion_packet` tlv. Bob is able to peel one layer of the
`trampoline_onion_packet` and discover that he is the recipient of the payment (because the hmac is `0x00...00`).

The effective payment route is:

```text
        +--> H1 --> H2 --+          +--> H3 --> H4 --+                  +--> H5 --+
        |                |          |                |                  |         |
        |                |          |                |                  |         |
Alice --+                +--> TA1 --+                +--> TA2 --> TB3 --+         +--> Bob
```
