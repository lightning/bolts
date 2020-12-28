# Trampoline Onion Routing

This file contains all the low-level details about the proposal in one place to
simplify reviewers life.

Once we make progress towards standardization, we will move these sections and
include them in the existing bolts.

## Table of Contents

* [Features](#features)
* [Packet Structure](#packet-structure)
  * [Trampoline Onion](#trampoline-onion)
  * [Paying via trampoline nodes](#paying-via-trampoline-nodes)
  * [Invoice trampoline hints](#invoice-trampoline-hints)
  * [Failure messages](#failure-messages)
* [Multi-Part Trampoline](#multi-part-trampoline)

## Features

Trampoline routing uses the following `features` flags:

| Bits  | Name                 | Description                           | Context  | Dependencies | Link |
|-------|----------------------|---------------------------------------|----------|--------------|------|
| 26/27 | `trampoline_routing` | This node supports trampoline routing | IN9      | `basic_mpp`  |      |

## Packet Structure

### Trampoline Onion

The trampoline onion is a variable-size tlv field with the following structure:

1. type: 12 (`trampoline_onion_packet`)
2. data:
   * [`byte`:`version`]
   * [`point`:`public_key`]
   * [`...*byte`:`hop_payloads`]
   * [`32*byte`:`hmac`]

It has exactly the same format as the `onion_packet` with a smaller `hop_payloads`.
Unlike the size of the `onion_packet`, the size of the `trampoline_onion_packet`
does not need to be fixed because it cannot be observed on the wire (since it is
always included inside a fixed-size `onion_packet`). Senders are free to choose
the size they want to allocate to the `trampoline_onion_packet` (it's a trade-off
between how much data needs to be transmitted to trampoline nodes and how much
space is left for trampoline nodes to route between themselves).

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

A recipient can signal support for receiving trampoline payments by setting the
`trampoline_routing` feature bit in invoices. A sender that wants to pay that
invoice may then rely on trampoline nodes to relay the payment by adding a
`trampoline_onion_packet` in the `hop_payload` of the _last_ hop of a normal
`onion_packet`:

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

### Invoice trampoline hints

A new Bolt 11 tagged field is defined:

* `t` (11): `data_length` variable. One or more entries containing trampoline
  routing information. There may be more than one `t` field.
  * `trampoline_node_id` (264 bits)
  * `fee_base_msat` (32 bits, big-endian)
  * `fee_proportional_millionths` (32 bits, big-endian)
  * `cltv_expiry_delta` (16 bits, big-endian)

### Failure messages

The following new `failure_code` is defined:

1. type: NODE|24 (`trampoline_fee_expiry_insufficient`)
2. data:
   * [`u32`:`fee_base_msat`]
   * [`u32`:`fee_proportional_millionths`]
   * [`u16`:`cltv_expiry_delta`]

The fee amount or cltv value was below that required by the trampoline node to
forward to the next trampoline node.

Note that when returning errors, trampoline nodes apply two layers of onion
encryption: one with the shared secret from the trampoline onion, then a second
one with the shared secret from the normal onion. This ensures that previous
trampoline nodes cannot decrypt the contents of the error and lets the sender
figure out which trampoline node the error comes from.

### Requirements

A sending node:

* If the invoice doesn't support the `trampoline_routing` feature:
  * MUST NOT use trampoline routing to pay that invoice
* MUST ensure that each hop in the `trampoline_onion_packet` supports `trampoline_routing`
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
  * If it cannot find a route that satisfies fees or cltv requirements:
    * MUST report a route failure to the origin node using the `trampoline_fee_expiry_insufficient` error
  * Otherwise:
    * MUST include the peeled `trampoline_onion_packet` in the last `hop_payload`
* MUST return errors as specified in Bolt 4's [error handling section](https://github.com/lightningnetwork/lightning-rfc/blob/master/04-onion-routing.md#returning-errors)
* MUST apply two layers of onion encryption when returning errors, first with
  the trampoline onion shared secret, then with the normal onion shared secret

### Rationale

This construction allows nodes with an incomplete view of the network to
delegate the construction of parts of the route to trampoline nodes.

The origin node only needs to select a set of trampoline nodes and to know a
route to the first trampoline node. Each trampoline node is responsible for
finding its own route to the next trampoline node. Trampoline nodes only learn
the previous node (which may or may not be a trampoline node) and the next
trampoline node, which guarantees the same anonymity as normal payments.

The `trampoline_onion_packet` has a variable size to allow implementations to
choose their own trade-off between flexibility and privacy. It's recommended to
add trailing filler data to the `trampoline_onion_packet` when using a small
number of hops. It uses the same onion construction as the `onion_packet`.

Trampoline nodes are free to use as many hops as they want between themselves
as long as they are able to create a route that satisfies the `cltv` and `fees`
requirements contained in the onion. This includes doing a single-hop payment
to the next trampoline node if they have suitable channels available.

## Multi-Part Trampoline

Trampoline routing combines nicely with multi-part payments. When multi-part
payment is used, we can let trampoline nodes combine all the incoming partial
payments before forwarding. Once the totality of the payment is received, the
trampoline node can choose the most efficient way to re-split it to reach the
next trampoline node.

### Requirements

A sending node:

* MUST include the final recipient's `payment_secret` (e.g. from a Bolt 11
  invoice) in the last trampoline onion payload
* MUST generate a different `payment_secret` to use in the outer onion

A processing node:

* MAY aggregate the incoming multi-part payment before forwarding
* If it uses a multi-part payment to forward to the next node:
  * MUST generate a different `payment_secret` to use in the outer onion
