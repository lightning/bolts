# Trampoline Onion Routing

## Table of Contents

* [Proposal](#proposal)
  * [Introduction](#introduction)
  * [Overview](#overview)
  * [Trampoline onion](#trampoline-onion)
  * [Gossip](#gossip)
  * [Filtering gossip messages](#filtering-gossip-messages)
    * [The `channel_update_filter`](#the-channel_update_filter)
    * [The `node_update_filter`](#the-node_update_filter)
  * [Privacy](#privacy)
  * [Multi-Part trampoline](#multi-part-trampoline)
* [Open questions](#open-questions)
  * [Building a trampoline route](#building-a-trampoline-route)

## Proposal

### Introduction

As the network grows, more bandwidth and storage will be required to keep an
up-to-date view of the whole network. Finding a payment path will also require
more computing power, making it unsustainable for constrained devices.

Constrained devices should only keep a view of a small part of the network and
leverage trampoline nodes to route payments.

### Overview

Nodes that are able to calculate routes on behalf of other nodes will advertise
support for `trampoline_routing`. This is an opportunity for them to earn more
fees than with the default onion routing.

A payer selects a few trampoline nodes and builds a corresponding trampoline onion.
It then embeds that trampoline onion in the last `hop_payload` of an `onion_packet`
destined to the first trampoline node. Computing routes between trampoline nodes
is deferred to the trampoline nodes themselves.

Note that this construction still uses an onion created by the payer so it doesn't
sacrifice privacy (in most cases it may even provide a bigger anonymity set).

### Trampoline onion

A trampoline onion uses the same construction as normal payment onions but with
a smaller size, to allow embedding it inside a normal payment onion.

For example, Alice may want to pay Carol using trampoline. Alice inserts
trampoline nodes between her and Carol. For this example we use a single
trampoline (Bob) but Alice may use more than one trampoline.

Alice then finds a route to the first trampoline Bob. The complete route is:

```text
        +--> Irvin --> Iris --+          +--> ... --+
        |                     |          |          |
        |                     |          |          |
Alice --+                     +--> Bob --+          +--> Carol
```

The corresponding `update_add_htlc` message would look like:

```text
                        update_add_htlc
+---------------------------------------------------------------------------+
| channel_id                                                                |
+---------------------------------------------------------------------------+
| htlc_id                                                                   |
+---------------------------------------------------------------------------+
| amount_msat                                                               |
+---------------------------------------------------------------------------+
| payment_hash                                                              |
+---------------------------------------------------------------------------+
| cltv_expiry                                                               |
+---------------------------------------------------------------------------+
|               onion_routing_packet                                        |
| +-----------------------------------------------------------------------+ |
| | version                                                               | |
| +-----------------------------------------------------------------------+ |
| | public_key                                                            | |
| +-----------------------------------------------------------------------+ |
| | +--------------------------------------------+----------------------+ | |
| | | amt_to_forward                             |                      | | |
| | +--------------------------------------------+                      | | |
| | | outgoing_cltv_value                        | normal onion payload | | |
| | +--------------------------------------------+ for Irvin            | | |
| | | short_channel_id                           |                      | | |
| | +--------------------------------------------+----------------------+ | |
| | +--------------------------------------------+----------------------+ | |
| | | amt_to_forward                             |                      | | |
| | +--------------------------------------------+                      | | |
| | | outgoing_cltv_value                        | normal onion payload | | |
| | +--------------------------------------------+ for Iris             | | |
| | | short_channel_id                           |                      | | |
| | +--------------------------------------------+----------------------+ | |
| | +--------------------------------------------+----------------------+ | |
| | | amt_to_forward                             |                      | | |
| | +--------------------------------------------+                      | | |
| | | outgoing_cltv_value                        |                      | | |
| | +--------------------------------------------+                      | | |
| | | payment_secret                             |                      | | |
| | +--------------------------------------------+ normal onion payload | | |
| | | total_amount                               | for Bob              | | |
| | +--------------------------------------------+                      | | |
| | |        trampoline_onion                    |                      | | |
| | | +---------------------+--------------------|                      | | |
| | | | amt_to_forward      |                    |                      | | |
| | | +---------------------+ trampoline payload |                      | | |
| | | | outgoing_cltv_value | for Bob            |                      | | |
| | | +---------------------+                    |                      | | |
| | | | outgoing_node_id    |                    |                      | | |
| | | +---------------------+--------------------|                      | | |
| | | +---------------------+--------------------|                      | | |
| | | | amt_to_forward      |                    |                      | | |
| | | +---------------------+ trampoline payload |                      | | |
| | | | outgoing_cltv_value | for Carol (final   |                      | | |
| | | +---------------------+ recipient)         |                      | | |
| | | | payment_secret      |                    |                      | | |
| | | +---------------------+                    |                      | | |
| | | | total_amount        |                    |                      | | |
| | | +---------------------+--------------------|                      | | |
| | +--------------------------------------------+----------------------+ | |
| +-----------------------------------------------------------------------+ |
| | hmac                                                                  | |
| +-----------------------------------------------------------------------+ |
+---------------------------------------------------------------------------+
```

When Bob receives the trampoline onion, he discovers that the next node is Carol.
Bob finds a route to Carol, builds a new payment onion and includes the peeled
trampoline onion in the final payload. This process may repeat with multiple
trampoline hops until we reach the final recipient.

### Gossip

The main goal of trampoline routing is to reduce the amount of gossip that
constrained nodes need to sync.

These nodes should only keep track of nearby channels (with an `N`-radius
heuristic for example). These nearby channels will be used to build an onion
route to a first trampoline node.

These nodes could even choose to ignore channels with a capacity lower than
`min_chan_capacity` to reduce the amount of gossip they need to sync at start-up.

`N` and `min_chan_capacity` are configured by the node and not advertised to
the network.

But these nodes also need to store information about nodes that are outside of
their neighborhood to use as trampoline hops. A solution is to introduce a
`node_update` gossip message containing the information needed to use nodes as
trampoline hops (similar to the `channel_update` message). Constrained nodes would
synchronize a subset of the network's trampoline nodes, based on whatever heuristic
matches their use-case.

Trampoline nodes need to estimate a `cltv_expiry_delta` and `fee` that allows them
to route to any other trampoline node while being competitive with other nodes,
and broadcast this information via the `node_update` message.

This is a great opportunity to incentivize nodes to open channels between each
other to minimize the cost of trampoline hops. This is also a great opportunity
for nodes to implement smart fee estimation algorithms as a competitive advantage.

Nodes may be very conservative and advertise their worst case `fee` and
`cltv_expiry_delta`, corresponding to the furthest node they can reach.

On the contrary, nodes may apply statistical analysis of the network to find a
lower `fee` and `cltv_expiry_delta` that would not allow them to reach all other
trampoline nodes but would work for most cases. Such nodes may choose to route
some payments at a loss to keep reliability high, attract more payments by building
a good reliability reputation and benefit from an overall gain.

Trampoline nodes may accept payments with a fee lower than what they advertised
if they're still able to route the payment in an economically viable way (because
they have a direct channel or a low-cost route to the next trampoline hop for example).

That means that payers may choose to ignore advertised fees entirely if they think
the fee/cltv they're using will still be able to route properly and retry with
a higher fee on route failures. Similarly to the existing `UPDATE` onion errors,
failures could include a `node_update` message containing the fee/ctlv needed to
correctly route the payment.

### Filtering gossip messages

Constrained nodes should listen to `node_update` messages and store some of them
to be used as trampoline hops. Nodes are free to choose their own heuristics for
trampoline node selection (some randomness is desired for anonymity).

While this reduces storage requirements on constrained nodes, it doesn't reduce
their bandwidth requirements: constrained nodes still need to listen to
`node_update` and `channel_update` messages (even though they will ignore most of them).

Nodes can reduce bandwidth usage by applying gossip filters before forwarding
gossip messages. Constrained nodes may require their peers to support a
`gossip_filters` feature. Per-connection filters are negotiated with each peer
after `init`. When receiving gossip messages, the remote node must apply the
negotiated filters and only forward to the local node the messages that match the filter.

Note that the remote node can decide to ignore the filters entirely and forward
every gossip to the local node: in that case the local node may close all channels
with that remote node, fail the connection and open channels to more cooperative nodes.

#### The `channel_update_filter`

The local node may send a `channel_update_filter` to the remote node. The remote
node must apply this filter before forwarding `channel_update`s. This allows the
local node to keep an up-to-date view of only a small portion of the network.

The filter could simply be a `distance` integer. The remote node should only
forward `channel_update`s of nodes that are at most `distance` hops away from
the remote node itself.

Computing this filter is inexpensive for small `distance`s. The remote node should
reject `distance`s that would be too costly to evaluate.

#### The `node_update_filter`

The local node may send a `node_update_filter` to the remote node. The remote
node should apply this filter before forwarding `node_update`s. This allows the
local node to only receive `node_update`s it cares about to periodically refresh
its list of trampoline nodes and stay up-to-date with their fee rate and cltv
requirements.

The local node may choose to keep the same set of trampoline nodes if they are
reliable enough. Or the local node may choose to rotate its set of trampoline
nodes regularly to improve anonymity and test new payment paths. This decision
should be configurable by the user/implementation.

A simple heuristic to frequently rotate the set of trampoline nodes would be to
compare their `node_id` to `sha256(local_node_id || latest_block_hash)` and
update this every `N` blocks. The `node_update_filter` could be based on the
distance between these two values. Then the local node chooses which trampoline
nodes to keep depending on their advertised fees/cltv and reliability reputation
(based on historical data if it's possible to collect such data).

### Privacy

Trampoline routing allows constrained devices to send and receive payments
without sacrificing privacy.

Senders are advised to sync a small portion of the graph (their local neighborhood).
This allows them to insert "normal" hops before the first trampoline node, thus
protecting their privacy with the same guarantees than normal payments.

Receivers may use route-blinding or rendezvous to hide their exact location.
Even without such measures, since the trampoline onion may contain multiple hops,
intermediate trampoline nodes can't know their position in the route and thus
can't tell whether the next node is the final recipient or not.

### Multi-Part Trampoline

Trampoline routing combines nicely with multi-part payments. When multi-part
payment is used, we can let trampoline nodes combine all the incoming partial
payments before forwarding. Once the totality of the payment is received, the
trampoline node can choose the most efficient way to re-split it to reach the
next trampoline node.

For example, Alice could split a payment in 3 parts to reach a trampoline node,
which would then split it in only 2 parts to reach the destination (we use a
ingle hop between trampoline nodes for simplicity, but any number of intermediate
nodes could be used):

```text
                                                     HTLC(1500 msat, 600112 cltv)
                                                    +---------------------------+
                                                    | amount_fwd: 1500 msat     |
                                                    | expiry: 600112            |
            HTLC(1560 msat, 600124 cltv)            | payment_secret: aaaaa     |
             +-----------------------+              | total_amount: 2800 msat   |
             | amount_fwd: 1500 msat |              | trampoline_onion:         |                                                                  HTLC(1100 msat, 600000 cltv)
             | expiry: 600112        |              | +-----------------------+ |                                                                 +-----------------------------+
        +--> | channel_id: 3         | ---> I1 ---> | | amount_fwd: 2500 msat | | --+                                                             | amount_fwd: 1100 msat       |
        |    |-----------------------|              | | expiry: 600000        | |   |                                                             | expiry: 600000              |
        |    |     (encrypted)       |              | | node_id: Bob          | |   |                                                             | payment_secret: xxxxx       |
        |    +-----------------------+              | +-----------------------+ |   |                     HTLC(1150 msat, 600080 cltv)            | total_amount: 2500 msat     |
        |                                           | |      (encrypted)      | |   |                      +-----------------------+              | trampoline_onion:           |
        |                                           | +-----------------------+ |   |                      | amount_fwd: 1100 msat |              | +-------------------------+ |
        |                                           +---------------------------+   |                      | expiry: 600000        |              | | amount_fwd: 2500 msat   | |
        |                                           |             EOF           |   |                 +--> | channel_id: 561       | ---> I4 ---> | | expiry: 600000          | | --+
        |                                           +---------------------------+   |                 |    |-----------------------|              | | total_amount: 2500 msat | |   |
        |                                            HTLC(800 msat, 600112 cltv)    |                 |    |     (encrypted)       |              | | payment_secret: yyyyy   | |   |
        |                                           +---------------------------+   |                 |    +-----------------------+              | +-------------------------+ |   |
        |                                           | amount_fwd: 800 msat      |   |                 |                                           | |         EOF             | |   |
        |                                           | expiry: 600112            |   |                 |                                           | +-------------------------+ |   |
        |   HTLC(820 msat, 600130 cltv)             | payment_secret: aaaaa     |   |                 |                                           +-----------------------------+   |
        |    +-----------------------+              | total_amount: 2800 msat   |   |                 |                                           |             EOF             |   |
        |    | amount_fwd: 800 msat  |              | trampoline_onion:         |   |                 |                                           +-----------------------------+   |
        |    | expiry: 600112        |              | +-----------------------+ |   |                 |                                                                             |
Alice --+--> | channel_id: 5         | ---> I2 ---> | | amount_fwd: 2500 msat | | --+--> Trampoline --+                                                                             +--> Bob
        |    |-----------------------|              | | expiry: 600000        | |   |  (fee 170 msat) |                                            HTLC(1400 msat, 600000 cltv)     |
        |    |     (encrypted)       |              | | node_id: Bob          | |   |    (delta 32)   |                                           +-----------------------------+   |
        |    +-----------------------+              | +-----------------------+ |   |                 |                                           | amount_fwd: 1400 msat       |   |
        |                                           | |      (encrypted)      | |   |                 |                                           | expiry: 600000              |   |
        |                                           | +-----------------------+ |   |                 |                                           | payment_secret: xxxxx       |   |
        |                                           +---------------------------+   |                 |   HTLC(1480 msat, 600065 cltv)            | total_amount: 2500 msat     |   |
        |                                           |             EOF           |   |                 |    +-----------------------+              | trampoline_onion:           |   |
        |                                           +---------------------------+   |                 |    | amount_fwd: 1400 msat |              | +-------------------------+ |   |
        |                                            HTLC(500 msat, 600112 cltv)    |                 |    | expiry: 600000        |              | | amount_fwd: 2500 msat   | |   |
        |                                           +---------------------------+   |                 +--> | channel_id: 1105      | ---> I5 ---> | | expiry: 600000          | | --+
        |                                           | amount_fwd: 500 msat      |   |                      |-----------------------|              | | total_amount: 2500 msat | |
        |                                           | expiry: 600112            |   |                      |     (encrypted)       |              | | payment_secret: yyyyy   | |
        |   HTLC(510 msat, 600120 cltv)             | payment_secret: aaaaa     |   |                      +-----------------------+              | +-------------------------+ |
        |    +-----------------------+              | total_amount: 2800 msat   |   |                                                             | |         EOF             | |
        |    | amount_fwd: 500 msat  |              | trampoline_onion:         |   |                                                             | +-------------------------+ |
        |    | expiry: 600112        |              | +-----------------------+ |   |                                                             +-----------------------------+
        +--> | channel_id: 7         | ---> I3 ---> | | amount_fwd: 2500 msat | | --+                                                             |             EOF             |
             |-----------------------|              | | expiry: 600000        | |                                                                 +-----------------------------+
             |     (encrypted)       |              | | node_id: Bob          | |
             +-----------------------+              | +-----------------------+ |
                                                    | |      (encrypted)      | |
                                                    | +-----------------------+ |
                                                    +---------------------------+
                                                    |             EOF           |
                                                    +---------------------------+
```

## Open questions

### Building a trampoline route

Once a node has a set of trampoline nodes, how does it choose which ones to use
to efficiently reach the final recipient?

The best solution for privacy is to choose them at random as long as the total
fee fits what the payer is ready to accept. This ensures that we are doing a
random walk between the trampoline nodes instead of taking a path that could be
guessed by an attacker. The downside is that the path may be wasteful, but that
is a trade-off that needs to be made between efficiency and privacy.

Another solution would be to have the recipient explicitly provide close trampoline
nodes in the invoice (in the form of a plain `node_id`, a rendezvous onion or a
blinded route hint). The sender then could simply select a first trampoline node
in its neighborhood and let it route towards the invoice hint.

It is also possible to let trampoline nodes include a list of "close" trampoline
nodes in their `node_update`. Senders could use this information to build a more
efficient trampoline route. However this solution may lead to some centralization
if senders all follow these hints and nodes only advertize a small number of
trampoline neighbours.

Senders could also bet on the fact that trampoline nodes will be well connected
to other nodes that have a `node_id` in the same range as their own `node_id`.
This would naturally incentivize the network to group into zones by `node_id`
distance. However this is easy to game: new routing nodes may grind a `node_id`
that's very close to a known, reliable trampoline node to choose their zone, and
in the end we may end up with a single very big zone.
