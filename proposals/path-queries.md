
# Path Queries 

## Introduction

To route a payment on the Lightning Network, a sender must find a path to the destination using channels which contain sufficient liquidity and meet certain routing rules (e.g fees). The current gossip scheme is insufficient to reliably determine a feasible path and inflexible for routing nodes. The purpose of path queries is to reduce the informational requirements during pathfinding and to allow routers to respond with dynamic policy. By selectively sharing routing information between peers, payment reliability can be scaled to a growing network while preserving channel balance privacy and payment anonymity.

## The problem: Graph Dependence

While finding a feasible path, source-based routing requires information about the network graph. For Lightning, this information typically comes from two sources: gossip messages and the responses of previous payment attempts. Both sources have severe limitations, which ultimately favor larger routing nodes and contribute to routing centralization. 

### Limitations of gossip

The gossip protocol is characterized by it's ability to quickly and reliably deliver a *finite* amount of information across a large distributed system via propagation. However, because these messages are delivered to every node (potentially multiple times), node performance suffers with a growing *quantity* of data; the more data that's shared, the more network and computational resources are required by each node to process those messages. Therefore, the size and frequency of gossip messages must be constrained. Gossip is well-suited for the Bitcoin network because nodes seek *consistency* among each other, which is done by limiting transaction throughput. Data on the Lightning Network, however, is more dynamic and routing a payment does not require consistency among all nodes, which means message limits and standardness rules are unnecessarily restrictive. For example, routing policy (cltv delta, fees, etc) has highly dynamic inputs, including available liquidity, HTLC slots, onchain fees, and even external factors. Existing limits to `channel_update` messages prohibit routing policy from accurately reflecting desired policy. 

### Finding Liquidity

For a payment to succeed, a route requires sufficient liquidity in every channel of the path. From a data perspective, liquidity is state that is managed between two nodes. During pathfinding, the unpredictability of a channel's liquidity is referred to as *liquidity uncertainty*. Without any prior knowledge (i.e high uncertainty), the probability a path is feasible declines with the size of the payment and the number of channels used. Today, feasible paths are found by a process of trial-and-error, whereby liquidity ranges are temporarily narrowed using the results of previous payment attempts, but this approach has a host of issues:

1. When liquidity uncertainty is high, pathfinding calculations increase payment success probabilities by favoring shorter paths and higher capacity channels. Not only does this affect the payment sender who's more likely to pay extra in fees for reliable liquidity, it's also a centralizing force on the network.

2. Lower payment success probabilities implies a larger set of potential routes. When the final route is uncertain, routing fees (and other payment details) are more difficult to predict. 

3. Trial-and-error is a slow discovery process because:

a. HTLCs require multiple message exchanges between peers, with each HTLC addition and removal requiring commitment/revocation cycles.
b. Payments must be attempted serially to avoid the delivery of multiple successful payments.

To improve performance for real payments, nodes may choose to 'probe' the channels of routing nodes using fake payments. However, liquidity is often highly dynamic and is always regressing to a state of uncertainty. To be effective, nodes must actively monitor the network. 

4. Failed payments (both real and fake) are a burden to routing nodes in the failing sub-path in the form of locked liquidity, HTLC slots, and wasted system resources.

Furthermore, each of these problems represent a scaling constraint, as more nodes need to search for liquidity amongst a larger set of channels.

## Proposal

The goal of path queries is to reduce a node's dependence on the graph during pathfinding by leveraging the routing information of other nodes. Specifically, this feature includes the following optional messages which allows nodes to cooperatively construct a path: 

1.  `query_path` 

- source_node_id
    
- destination_node_id
    
- amount
    
2.  `reply_path`

- path

3.  `reject_query_path`

- reason

Upon receiving a `query_path` message, a node can choose how it wants to respond, including rejecting or ignoring it. The `reply_path` message helps the requester - either a source or router - deliver a potential payment because it leverages routing information at the queried node. This resolves the liquidity uncertainty problem at the queried hop because a node knows its own channel balances and can respond accordingly.  A routing node can respond with any routing policy (e.g fees, expiry, etc) it desires, unconstrained by limits to gossip. Compared to payments, queries are lightweight and can be made concurrently.

## Putting into practice

The proposal outlines a basic set of messages, and it is up to each node to choose its own request & response strategies, including *who* they want to talk to (any subset of nodes), *what* they want to respond to (e.g minimum amounts) and any rate limits (number of requests and replies/paths). While there are innumerable strategies that may evolve, let's walk-through a simple example where all nodes adopt a PEER_ONLY strategy. Under this strategy, nodes only send relevant messages to their direct channel peers.

Payment from S -> R
```
               +-------+      +-------+
    +----------|   A   |------|   B   |----------+
    |          +-------+      +-------+          |
    |                             |              |
+-------+                         |           +-----+
|   S   |          ---------------+           |  R  |
+-------+          |                          +-----+
    |              |                             |
    |          +-------+      +-------+          |
    +----------|   C   |------|   D   |----------+
               +-------+      +-------+
```

Before attempting the payment, the sender (S) may choose to query any subset of it's channel peers. Since this is a larger payment, the sender decides to make concurrent queries to both Alice and Carol:

- Alice receives a `query_path` message requesting a path from herself (A) to the receiver (R). She sees she does not have the outbound liquidity to Bob (B) to complete payment, so either responds with a `reject_query_path` with a reason indicating a temporary failure to find a route, or waits for liquidity to become available to respond with a `reply_path`.
- Carol (C) receives a `query_path` requesting a path from herself to the receiver (R). She has sufficient outbound liquidity through Dave (D), but before responding to the sender, she decides to query Dave:
    - Dave receives a query from Carol for a path from himself (D) to the receiver. Similar to Alice, Dave responds that he has no route available 
- Upon discovering insufficient liquidity from D -> R, Carol splits the sender amount and concurrently queries Bob (B) and Dave (D) with their respective splits. 
    - Dave receives a new query requesting a path from himself (D) to the receiver, but of a lesser amount. This he has the liquidity for! Since Dave knows he can route the requested payment, he responds to Carol with the given path and routing details. 
    - Bob (B) receives a new query requesting a path from himself (B) to the receiver for his split amount. Similar to Dave, he knows he can route the payment, so responds to Carol with his routing details. 
- Upon receiving the path details from Bob and Dave, Carol can now confidently assemble a MPP from herself to the receiver. She constructs the MPP, adds her own routing details and sends a `reply_path` to the sender. 
- Upon receiving the `reply_path` from Carol, the sender attempts the payment and on the first attempt, the payment succeeded.
  
As you can see, `query_path` messages concurrently spread amongst prospective routing nodes until a feasible path is discovered. After receiving a `reply_path` a node can prepend itself to the path and either back-propagate it to the source or attempt the payment. Each node knows its channel balances and can therefore reduce the liquidity uncertainty for it's respective channels. 

While the small example above illustrates the process, it is important to consider the *rate* at which liquidity uncertainty is reduced; trial-and-error may work for a small network like this, but does not scale to a growing number of nodes.

## Comparisons to Trampoline 

By querying one or more remote nodes (see [Anonymous queries via Onions](#anonymous-queries-via-onions)), a source node can construct a route similar to that used by trampoline, as demonstrated by the following example: 

1. Select a remote node with path query support as a 'trampoline' hop (T<sub>2</sub>).  
2. Query channel peer (T<sub>1</sub>) for a path to T<sub>2</sub>. 
3. Query T<sub>2</sub> for a path from T<sub>2</sub> to final destination (D).
4. Send payment using aggregate route: S -> T<sub>1</sub> -> ... -> T<sub>2</sub> -> ... -> D

Note that while the pathfinding process is similar to trampoline in that it leverages the pathfinding ability of other nodes, the final route is determined by the sender and a regular onion is used.

Each approach has its own set of trade-offs. By learning the entire route, path queries give the payment sender more control over routing decisions, including the final route and how to handle errors. While using trampoline, many routing decisions are outsourced. For example, errors are returned to the previous trampoline hop and can be retried from that point. This may improve the payment delivery time, but may also produce a sub-optimal route (e.g more fees) from the sender's perspective. For a user with multiple LSPs, path queries give the user the ability to 'shop' for the best route. 

Routing nodes have an economic incentive to support both features in order to maximize routing fees. More importantly, trampoline nodes can employ queries for themselves to find feasible sub-paths, thereby reducing their own dependence on a fully synced and actively probed graph. Graph maintenance is a cost that disproportionately effects nodes with smaller infrastructure and lower payment volume. Reducing these costs allows smaller nodes to be more competitive, which increases the expected distribution of routing.

## Expanding the Protocol

### Anonymous queries via Onions

The proposal as described above only supports messages using a *direct* connection between any two peers. This is sufficient for queries between channel peers because it reveals no new information about the source of a payment. However, this reduces anonymity when querying remote nodes, such as the example described in [Trampoline](#comparisons-to-trampoline) above. To improve anonymity, onions could be used to carry these messages. However, without knowing the query source, responding nodes are vulnerable to spam, and consequentally, potential DoS attacks. This is a similar attack vector to channel jamming, but rather than using onions to consume channel resources (liquidity, HTLCs), query onions consume a node's computational resources instead. To defend against spam, nodes can potentially require a small payment for anonymous recommendations.  

### Adding message fields 

The messages defined in this proposal are intentionally minimal to communicate the core concept while avoiding additional complexity. That said, optional message fields can be added to enhance a node's capabilites and to reduce the number of messages between peers. Some examples:

- `query_path` fields:
    - `maximum_fee`, `cltv_expiration` - reduce response messages by providing upfront filters
    - `query_expiration` - A querying node can define the window of time they're interested in a given path (e.g 1min, 1hr, 1day, always) and get notified with updates.
- `reply_path` fields: 
    - `confidence` (ranged interval) - a score to indicate the expected likelihood of payment delivery; the higher the routing node's confidence, the more a path suggestion behaves like a *quote* for delivery. This may be used by a querying node to weigh the value of a responding nodes offered paths, especially if there's a cost for `reply_path`s, such as onion queries as described above. Unlike forwarding endorsements (e.g [HTLC endorsement](https://github.com/lightning/bolts/pull/1071)), this value would be back-propogated in the `reply_path` messages, so does not leak information about the origin.

## Potential Concerns

### Privacy Implications

Naturally, any time information is shared, there is a privacy implication. A `query_path` reveals a downstream node - either a hop or the destination - to the prospective routing node. When iterated upon, each node in the path becomes aware of the *queried* destination. Meanwhile, the selected channels in a `reply_path` may reveal some information about channel balances. As so, let's consider channel balance privacy and sender/receiver anonymity:

*Privacy of channel balances*

Path queries differ from trial-and-error (including probing) in the manner that liquidity uncertainty is reduced. Trial-and-error informs the payment *sender* about liquidity *ranges* (i.e lower and upper bound) for channels on an attempted path, while a `reply_path` only provides a set channels that meet liquidity requirements. For example, in our PEER_ONLY strategy described above, the sender (S) gained no information about liquidity on the network other than what was sufficient for the final route. While probing still remains an unsolved problem, path queries enable better information control as nodes can choose *who* they talk to and *how much* information they want to reveal. 

Generally speaking, the more channels a node has, the more difficult it is to infer liquidity based on an offered path. Large routing nodes with many channels may be more liberal in their responses than smaller nodes delivering less frequent payments.

*Sender Anonymity*

While a single query does not tell a routing node about the source of a payment, the number of queries a routing node receives and whom they come from may reduce the anonymity set of the *query* origin. Depending on the nature of the payment, the sender may choose its own path construction process, including adding trampoline-like hops or opting out of queries altogether.

*Receiver Anonymity*

While the receiver does not have a choice in the sender's routing process, they do get to choose the final sub-path via route blinding. Using path queries, a receiver can construct more reliable paths to itself; the longer the path, the more anonymity from the sender and its set of routing nodes. The receiver may also choose to construct the blinded path using trampoline-like hops to prevent routing nodes from inferring full paths.

### Denial-of-service risks

Nodes may choose their own response strategies, including filtering requests (e.g minimum amount) and setting rate limits. In order to enforce rate limits, a node either needs to know the source of the query or needs to enforce some cost on anonymous queries. 
