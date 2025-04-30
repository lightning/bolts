
# Path Queries 

### Introduction

To route a payment on the Lightning Network, a sender must find a path to the destination using channels which contain sufficient liquidity and meet certain routing rules (e.g fees). The routing information that's shared within the protocol today is insufficient to reliably find a feasible path, which results in nodes spamming other nodes with failing payments. The purpose of path queries is to enable payment senders to find feasible paths with minimal knowledge of the graph, and to allow routing nodes to respond with dynamic policy. This is done by sharing path information at the peer-level, which can be scaled to a growing network while preserving channel balance privacy and payment anonymity.

### The problem 

#### 1. Liquidity uncertainty

Liquidity is state that is managed between two nodes and the unpredictability of this value for any given node is referred as *liquidity uncertainty*. Without prior knowledge, the uncertainty of unowned channels on the network is only bounded by the capacity of that channel and the aggregate uncertainty grows with the number of channels on the network. Currently, feasible paths are found by trial-and-error, whereby liquidity uncertainty is reduced by sequential payment attempts, but this approach has a host of issues:

1. Pathfinding calculations account for reliability by favoring shorter paths and higher capacity channels. Not only does this effect the payment sender who's more likely to pay extra in fees for reliable liquidity, it's also a centralizing force on the network.

2. Low payment success rates implies a large set of potential routes. When the final route is unknown, routing fees (and other payment details) are more difficult to predict. 

3. Failed payments are a burden to routing nodes in the failing sub-path in the form of locked liquidity, HTLC slots, and wasted computational resources.

Furthermore, trial-and-error is a slow method to discover a feasible path because HTLCs need to be set up and torn down at each hop. HTLCs require multiple rounds of communication between peers, which is wasted time when the payment fails. Furthermore, this process must be executed serially to avoid the delivery of multiple successful payments, which fundamentally limits the rate at which path discovery can occur. To improve the performance of real payments, nodes may choose to 'probe' the network to reduce liquidity uncertainty. Due to it's dynamic nature, liquidity is always regressing to a state of uncertainty, which means nodes must continously monitor the network. As the network grows, this means an exponential growth of failing payments.

#### 2. Graph dependence

To route a payment, the sender needs the latest updates to the graph. This requirement is a burden to the sender, who needs to constantly sync the channel graph, and to routers, who must limit their channel updates. Inputs to routing policy, including liquidity, onchain fees, and even exogenous factors, are extremely dynamic, which means their policy should also be dynamic. Rate limits to `channel_updates` causes advertised policy to differ from desired policy, which reduces control of routing resources (e.g liquidity).   

* * *

### Proposal

This proposal includes the following optional messages which allows nodes to cooperatively construct a path: 

1.  `path_query` 

- source_node_id
    
- destination_node_id
    
- amount
    
2.  `path_reply`

- path

3.  `reject_path_query`

- reason

Upon receiving a `path_query`, a node can choose how it wants to respond, including rejecting or ignoring it. The `path_reply` message helps the requester - either a source or router - deliver a potential payment because it leverages routing information at the queried node. This solves the liquidity uncertainty problem at the queried hop because a node knows it's own balances and can respond accordingly. Compared to payment onions, queries are lightweight and can be made concurrently. A routing node can respond with any routing policy (e.g fees, expiry, etc) it desires, unconstrained by global rate limits.

## Putting into practice

The proposal outlines a basic set of messages and it is for the node to choose their own request & response strategies, including *who* they want to talk to (any subset of nodes), *what* they want to respond to (e.g minimum amounts) and any rate limits (number of requests and replies/paths). While there are innumerable strategies that may evolve, let's walk-through a simple example where where all nodes adopt a PEER_ONLY strategy (i.e nodes interact only with their channel peers):

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

Before attempting the payment, the sender (S) may choose to query any subset of it's channel peers. Alice (A) advertises the lowest routing fees but, since this is a larger payment, the sender decides to make concurrent queries to both Alice and Carol:

- Alice receives a `path_query` message requesting a path from herself (A) to the receiver (R). She sees she does not have the outbound liquidity to Bob (B) to complete payment, so responds with a `reject_path_query` with a reason indicating a temporary failure to find a route.
- Carol (C) receives a `path_query` requesting a path from herself to the receiver (R). She has sufficient outbound liquidity through Dave (D), but before responding to the sender, she decides to query Dave:
    - Dave receives a query from Carol for a path from himself (D) to the receiver. Similar to Alice, Dave responds that he has no route available 
- Upon discovering insufficient liquidity from D -> R, Carol splits the sender amount and concurrently queries Bob (B) and Dave (D) with their respective splits. 
    - Dave receives a new query requesting a path from himself (D) to the receiver, but of a lesser amount. This he does have the liquidity for! Since Dave knows he can route the requested payment, he resonds to Carol with the given path and routing details. 
    - Bob (B) receives a new query requesting a path from himself (B) to the receiver for his split amount. Similar to Dave, he knows he can route the payment, so resonds to Carol with his routing details. 
- Upon receiving the path details from Bob and Dave, Carol can now confidently assemble a MPP from herself to the receiver. She constructs the MPP, adds her own routing details and sends a `path_reply` to the sender. 
- Upon receiving the `path_reply` from Carol, Alice attempts the payment and on her first attempt, the payment succeeded.
  
As you can see, path queries enable nodes to use queries to concurrently probe the network for feasible paths. When chained together, these queries swarm to the destination, reducing liquididity uncertainty at an exponentiall faster rate than failed payments. Each hop knows it's channel balance and can therefore reduce the liquidity uncertainty at their channel in the path. After receiving a `path_reply` a node can prepend itself to the path and back-propogate it to the source. 

While the small example above illustrates the process, it is important to consider the *rate* at which liquidity uncertainty is reduced; trial-and-error may work for a small network like this, but does not scale well with a growing number of nodes.

### Implementing Trampoline via queries

Path queries can be used to accomplish everything trampoline routing proposes, but with reduced complexity at the protocol level. The [trampoline proposal](https://github.com/lightning/bolts/blob/trampoline-routing/proposals/trampoline.md#introduction) states, "The main goal of trampoline routing is to reduce the amount of gossip that constrained nodes need to sync". While trampoline requires constrained devices to "keep a small part of the network and leverage trampoline nodes to route payments," path queries do not need any knowledge of the graph to find a route, but only a connection to a supporting peer(s).

Trampoline pursues this goal while also preserving anonymity for the sender and receiver. This is done by including multiple hops in the trampoline route. By using onion messages (see [Queries via Onions](#queries-via-onions)) to anonymously query a remote node, a source node can attain a comparable anonymity set with only a single trampoline-like hop using the following process: 

1. Select a node with path query support as a 'trampoline' hop (T).  
2. Query channel peer (P) for a path to T. 
3. Query T for a path from T to final destination (D).
4. Send payment using aggregate route 
```
S -> P -> ... -> T -> ... -> D
```

Note that while the pathfinding process is similar to trampoline in that it leverages routing information of other nodes, the final route does not use a special "trampoline route", but rather a regular onion route. This has several advantages:

- Simplicity of the protocol
- Trampoline hops do not know previous trampolines 
- Single-hop trampolines produce a shorter route (more reliable, lower expected fees)

## Expanding the Protocol

#### Queries via Onions

The proposal as described above only supports messages using a *direct* connection between any two peers. This is sufficient for queries between channel peers because it reveals no new information about the source of a payment. However, this reduces anonymity when querying nodes elsewhere on the network, such as querying a trampoline-like hop as described above. To improve anonymity, onions could be used to carry these messages. However, without knowing the query node, responding nodes are vulnerable to spam, and consequentally, potential DoS attacks. This is a similar attack vector to channel jamming, but rather than using onions to consume payment resources (liquidity, HTLCs), a query consumes computational resources instead. To prevent this, nodes can implement their own mitigations, such as a small payment as part of the query.  

#### Adding fields 

The messages defined in this proposal are intentionally bare. Optional message fields can be added to enhance a node's capabilites and to reduce the number of messages between peers. Some examples:

- `path_query`
    - `maximum_fee`, `cltv_expiration` - reduce response messages by providing upfront filters
    - `expiration`. A querying node can define the window of time they're interested in a given path (e.g 1min, 1hr, 1day, always) and get notified with updates.
- `path_reply` 
    - `confidence` (ranged interval) - a score to indicate the expected likelihood of payment delivery; the higher the routing node's confidence, the more a path suggestion behaves like a *quote* for delivery. This may be used by a querying node to weigh the value of a responding nodes offered paths, especially if there's a cost for `path_reply`s, such as onion queries as described above. Unlike forwarding endorsements (e.g [HTLC endorsement](https://github.com/lightning/bolts/pull/1071)), this value would be back-propogated in the `path_reply` messages, so does not leak information about the origin.

## Potential Concerns
#### Privacy Implications

Naturally, any time information is shared, there is a privacy implication. A `path_query` reveals a downstream node - either a hop or the destination - to the prospective routing node. When iterated upon, each node in the path becomes aware of the *queried* destination. Meanwhile, the selected channels in a `path_reply` may reveal some information about channel balances. As so, let's consider channel balance privacy and sender/receiver anonymity:

*Privacy of channel balances*

Path queries differ from trial-and-error (including probing) in the manner that liquidity uncertainty is reduced. Trial-and-error informs the payment *sender* about liquidity *ranges* (i.e lower and upper bound) for channels on an attempted path, while a `path_reply` only provides a set channels that meet liquidity requirements. For example, in our PEER_ONLY strategy described above, the sender (S) gained no information about liquidity on the network other than what was sufficient for the final route. While probing still remains an unsolved problem, path queries enable better information control as nodes can choose *who* they talk to and *how much* information they want to reveal. 

Generally speaking, the more channels a node has, the more difficult it is to infer liquidity based on an offered path. Large routing nodes with many channels may be more liberal in their responses than smaller nodes delivering less frequent payments.

*Sender Anonymity*

While a single query does not tell a routing node about the source of a payment, the number of queries a routing node receives and whom they come from may reduce the anonymity set of the *query* origin. Depending on the nature of the payment, the sender may choose it's own path construction process, including adding trampoline-like hops or opting out of queries altogether.

*Receiver Anonymity*

While the receiver does not have a choice in the sender's routing process, they do get to choose the final sub-path via route blinding. Using path queries, a receiver can construct more reliable paths to itself; the longer the path, the more anonymity from the sender and it's gang of routing nodes. The receiver may also choose to construct the blinded path using trampoline-like hops to prevent routing nodes from inferring full paths.

#### Denial-of-service risks

Nodes may choose their own response strategies, including filtering requests (e.g minimum amount) and setting rate limits. In order to enforce rate limits, a node either needs to know the source of the query or needs to enforce some cost on anonymous queries. 
