# BOLT #7: P2P Node and Channel Discovery

This specification describes simple node discovery, channel discovery, and channel update mechanisms that do not rely on a third-party to disseminate the information.

Node and channel discovery serve two different purposes:

 - Channel discovery allows the creation and maintenance of a local view of the network's topology, so that a node can discover routes to desired destinations.
 - Node discovery allows nodes to broadcast their ID, host, and port, so that other nodes can open connections and establish payment channels with them.

To support channel discovery, peers in the network exchange
`channel_announcement` messages containing information regarding new
channels between the two nodes. They can also exchange `channel_update`
messages, which update information about a channel. There can only be
one valid `channel_announcement` for any channel, but at least two
`channel_update` messages are expected.

To support node discovery, peers exchange `node_announcement`
messages, which supply additional information about the nodes. There may be
multiple `node_announcement` messages, in order to update the node information.

# Table of Contents

  * [The `announcement_signatures` Message](#the-announcement_signatures-message)
  * [The `channel_announcement` Message](#the-channel_announcement-message)
  * [The `node_announcement` Message](#the-node_announcement-message)
  * [The `channel_update` Message](#the-channel_update-message)
  * [Initial Sync](#initial-sync)
  * [Rebroadcasting](#rebroadcasting)
  * [HTLC Fees](#htlc-fees)
  * [Pruning the Network View](#pruning-the-network-view)
  * [Recommendations for Routing](#recommendations-for-routing)
  * [References](#references)

## The `announcement_signatures` Message

This is a direct message between the two endpoints of a channel and serves as an opt-in mechanism to allow the announcement of the channel to the rest of the network.
It contains the necessary signatures, by the sender, to construct the `channel_announcement` message.

1. type: 259 (`announcement_signatures`)
2. data:
    * [`32`:`channel_id`]
    * [`8`:`short_channel_id`]
    * [`64`:`node_signature`]
    * [`64`:`bitcoin_signature`]

The willingness of the initiating node to announce the channel is signaled during channel opening by setting the `announce_channel` bit in `channel_flags` (see [BOLT #2](02-peer-protocol.md#the-open_channel-message)).

### Requirements

The `announcement_signatures` message is created by constructing a `channel_announcement` message, corresponding to the newly established channel, and signing it with the secrets matching an endpoint's `node_id` and `bitcoin_key`. After it's signed, the
`announcement_signatures` message may be sent.

The `short_channel_id` is the unique description of the funding transaction.
It is constructed as follows:
  1. the most significant 3 bytes: indicating the block height
  2. the next 3 bytes: indicating the transaction index within the block
  3. the least significant 2 bytes: indicating the output index that pays to the channel.

A node:
  - if the `open_channel` message has the `announce_channel` bit set AND a `shutdown` message has not been sent:
    - MUST send the `announcement_signatures` message.
      - MUST NOT send `announcement_signatures` messages until `funding_locked`
      has been sent AND the funding transaction has at least six confirmations.
  - otherwise:
    - MUST NOT send the `announcement_signatures` message.
  - upon reconnection:
    - MUST respond to the first `announcement_signatures` message with its own
    `announcement_signatures` message.
    - if it has NOT received an `announcement_signatures` message:
      - SHOULD retransmit the `announcement_signatures` message.

A recipient node:
  - if the `node_signature` OR the `bitcoin_signature` is NOT correct:
    - MAY fail the channel.
  - if it has sent AND received a valid `announcement_signatures` message:
    - SHOULD queue the `channel_announcement` message for its peers.

## The `channel_announcement` Message

This message contains ownership information regarding a channel. It ties
each on-chain Bitcoin key to the associated Lightning node key, and vice-versa.
The channel is not practically usable until at least one side has announced
its fee levels and expiry, using `channel_update`.

Proving the existence of a channel between `node_1` and `node_2` requires:

1. proving that the funding transaction pays to `bitcoin_key_1` and
   `bitcoin_key_2`
2. proving that `node_1` owns `bitcoin_key_1`
3. proving that `node_2` owns `bitcoin_key_2`

Assuming that all nodes know the unspent transaction outputs, the first proof is
accomplished by a node finding the output given by the `short_channel_id` and
verifying that it is indeed a P2WSH funding transaction output for those keys
specified in [BOLT #3](03-transactions.md#funding-transaction-output).

The last two proofs are accomplished through explicit signatures:
`bitcoin_signature_1` and `bitcoin_signature_2` are generated for each
`bitcoin_key` and each of the corresponding `node_id`s are signed.

It's also necessary to prove that `node_1` and `node_2` both agree on the
announcement message: this is accomplished by having a signature from each
`node_id` (`node_signature_1` and `node_signature_2`) signing the message.

1. type: 256 (`channel_announcement`)
2. data:
    * [`64`:`node_signature_1`]
    * [`64`:`node_signature_2`]
    * [`64`:`bitcoin_signature_1`]
    * [`64`:`bitcoin_signature_2`]
    * [`2`:`len`]
    * [`len`:`features`]
    * [`32`:`chain_hash`]
    * [`8`:`short_channel_id`]
    * [`33`:`node_id_1`]
    * [`33`:`node_id_2`]
    * [`33`:`bitcoin_key_1`]
    * [`33`:`bitcoin_key_2`]

### Requirements

The origin node:
  - MUST set `chain_hash` to the 32-byte hash that uniquely identifies the chain
  that the channel was opened within:
    - for the _Bitcoin blockchain_:
      - MUST set `chain_hash` value (encoded in hex) equal to `000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f`.
  - MUST set `short_channel_id` to refer to the confirmed funding transaction,
  as specified in [BOLT #2](02-peer-protocol.md#the-funding_locked-message).
    - Note: the corresponding output MUST be a P2WSH, as described in [BOLT #3](03-transactions.md#funding-transaction-output).
  - MUST set `node_id_1` and `node_id_2` to the public keys of the two nodes
  operating the channel, such that `node_id_1` is the numerically-lesser of the
  two DER-encoded keys sorted in ascending numerical order.
  - MUST set `bitcoin_key_1` and `bitcoin_key_2` to `node_id_1` and `node_id_2`'s
  respective `funding_pubkey`s.
  - MUST compute the double-SHA256 hash `h` of the message, beginning at offset
  256, up to the end of the message.
    - Note: the hash skips the 4 signatures but hashes the rest of the message,
    including any future fields appended to the end.
  - MUST set `node_signature_1` and `node_signature_2` to valid
    signatures of the hash `h` (using `node_id_1` and `node_id_2`'s respective
    secrets).
  - MUST set `bitcoin_signature_1` and `bitcoin_signature_2` to valid
  signatures of the hash `h` (using `bitcoin_key_1` and `bitcoin_key_2`'s
  respective secrets).
  - SHOULD set `len` to the minimum length required to hold the `features` bits
  it sets.

The final node:
  - MUST verify the integrity AND authenticity of the message by verifying the
  signatures.
  - if there is an unknown even bit in the `features` field:
    - MUST NOT parse the remainder of the message.
    - MUST NOT add the channel to its local network view.
    - SHOULD NOT forward the announcement.
  - if the `short_channel_id`'s output does NOT correspond to a P2WSH (using
    `bitcoin_key_1` and `bitcoin_key_2`, as specified in
    [BOLT #3](03-transactions.md#funding-transaction-output)) OR the output is
    spent:
    - MUST ignore the message.
  - if the specified `chain_hash` is unknown to the receiver:
    - MUST ignore the message.
  - otherwise:
    - if `bitcoin_signature_1`, `bitcoin_signature_2`, `node_signature_1` OR
    `node_signature_2` are invalid OR NOT correct:
      - SHOULD fail the connection.
    - otherwise:
      - if `node_id_1` OR `node_id_2` are blacklisted:
        - SHOULD ignore the message.
      - otherwise:
        - if the transaction referred to was NOT previously announced as a
        channel:
          - SHOULD queue the message for rebroadcasting.
          - MAY choose NOT to for messages longer than the minimum expected
          length.
      - if it has previously received a valid `channel_announcement`, for the
      same transaction, in the same block, but for a different `node_id_1` or
      `node_id_2`:
        - SHOULD blacklist the previous message's `node_id_1` and `node_id_2`,
        as well as this `node_id_1` and `node_id_2` AND forget any channels
        connected to them.
      - otherwise:
        - SHOULD store this `channel_announcement`.
  - once its funding output has been spent OR reorganized out:
    - SHOULD forget a channel.

### Rationale

Both nodes are required to sign to indicate they are willing to route other
payments via this channel (i.e. be part of the public network); requiring their
Bitcoin signatures proves that they control the channel.

The blacklisting of conflicting nodes disallows multiple different
announcements. Such conflicting announcements should never be broadcast by any
node, as this implies that keys have leaked.

While channels should not be advertised before they are sufficiently deep, the
requirement against rebroadcasting only applies if the transaction has not moved
to a different block.

In order to avoid storing excessively large messages, yet still allow for
reasonable future expansion, nodes are permitted to restrict rebroadcasting
(perhaps statistically).

New channel features are possible in the future: backwards compatible (or
optional) features will have _odd_ feature bits, while incompatible features
will have _even_ feature bits
(["It's OK to be odd!"](00-introduction.md#glossary-and-terminology-guide)).
Incompatible features will result in the announcement not being forwarded by
nodes that do not understand them.

## The `node_announcement` Message

This message allows a node to indicate extra data associated with it, in
addition to its public key. To avoid trivial denial of service attacks,
nodes not associated with an already known channel are ignored.

1. type: 257 (`node_announcement`)
2. data:
   * [`64`:`signature`]
   * [`2`:`flen`]
   * [`flen`:`features`]
   * [`4`:`timestamp`]
   * [`33`:`node_id`]
   * [`3`:`rgb_color`]
   * [`32`:`alias`]
   * [`2`:`addrlen`]
   * [`addrlen`:`addresses`]

`timestamp` allows for the ordering of messages, in the case of multiple
announcements. `rgb_color` and `alias` allow intelligence services to assign
nodes colors like black and cool monikers like 'IRATEMONK' and 'WISTFULTOLL'.

`addresses` allows a node to announce its willingness to accept incoming network
connections: it contains a series of `address descriptor`s for connecting to the
node. The first byte describes the address type and is followed by the
appropriate number of bytes for that type.

The following `address descriptor` types are defined:

   * `0`: padding; data = none (length 0)
   * `1`: ipv4; data = `[4:ipv4_addr][2:port]` (length 6)
   * `2`: ipv6; data = `[16:ipv6_addr][2:port]` (length 18)
   * `3`: Tor v2 onion service; data = `[10:onion_addr][2:port]` (length 12)
       * version 2 onion service addresses; Encodes an 80-bit, truncated `SHA-1`
       hash of a 1024-bit `RSA` public key for the onion service (a.k.a. Tor
       hidden service).
   * `4`: Tor v3 onion service; data = `[35:onion_addr][2:port]` (length 37)
       * version 3 ([prop224](https://gitweb.torproject.org/torspec.git/tree/proposals/224-rend-spec-ng.txt))
         onion service addresses; Encodes:
         `[32:32_byte_ed25519_pubkey] || [2:checksum] || [1:version]`, where
         `checksum = sha3(".onion checksum" | pubkey || version)[:2]`.

### Requirements

The origin node:
  - MUST set `timestamp` to be greater than that of any previous
  `node_announcement` it has previously created.
    - MAY base it on a UNIX timestamp.
  - MUST set `signature` to the signature of the double-SHA256 of the entire
  remaining packet after `signature` (using the key given by `node_id`).
  - MAY set `alias` AND `rgb_color` to customize its appearance in maps and
  graphs.
    - Note: the first byte of `rgb` is the red value, the second byte is the
    green value, and the last byte is the blue value.
  - MUST set `alias` to a valid UTF-8 string, with any `alias` trailing-bytes
  equal to 0.
  - SHOULD fill `addresses` with an address descriptor for each public network
  address that expects incoming connections.
  - MUST set `addrlen` to the number of bytes in `addresses`.
  - MUST place non-zero typed address descriptors in ascending order.
  - MAY place any number of zero-typed address descriptors anywhere.
  - SHOULD use placement only for aligning fields that follow `addresses`.
  - MUST NOT create a `type 1` OR `type 2` address descriptor with `port` equal
  to 0.
  - SHOULD ensure `ipv4_addr` AND `ipv6_addr` are routable addresses.
  - MUST NOT include more than one `address descriptor` of the same type.
  - SHOULD set `flen` to the minimum length required to hold the `features`
  bits it sets.

The final node:
  - if `node_id` is NOT a valid compressed public key:
    - SHOULD fail the connection.
    - MUST NOT process the message further.
  - if `signature` is NOT a valid signature (using `node_id` of the
  double-SHA256 of the entire message following the `signature` field, including
  unknown fields following `alias`):
    - SHOULD fail the connection.
    - MUST NOT process the message further.
  - if `features` field contains _unknown even bits_:
    - MUST NOT parse the remainder of the message.
    - MAY discard the message altogether.
    - SHOULD NOT connect to the node.
  - MAY forward `node_announcement`s that contain an _unknown_ `features` _bit_,
  regardless of if it has parsed the announcement or not.
  - SHOULD ignore the first `address descriptor` that does NOT match the types
  defined above.
  - if `addrlen` is insufficient to hold the address descriptors of the
  known types:
    - SHOULD fail the connection.
  - if `port` is equal to 0:
    - SHOULD ignore `ipv6_addr` OR `ipv4_addr`.
  - if `node_id` is NOT previously known from a `channel_announcement` message,
  OR if `timestamp` is NOT greater than the last-received `node_announcement`
  from this `node_id`:
    - SHOULD ignore the message.
  - otherwise:
    - if `timestamp` is greater than the last-received `node_announcement` from
    this `node_id`:
      - SHOULD queue the message for rebroadcasting.
      - MAY choose NOT to queue messages longer than the minimum expected length.
  - MAY use `rgb_color` AND `alias` to reference nodes in interfaces.
    - SHOULD insinuate their self-signed origins.

### Rationale

New node features are possible in the future: backwards compatible (or
optional) ones will have _odd_ `feature` _bits_, incompatible ones will have
_even_ `feature` _bits_. These may be propagated by nodes even if they
cannot process the announcements themselves.

New address types may be added in the future; as address descriptors have
to be ordered in ascending order, unknown ones can be safely ignored.
Additional fields beyond `addresses` may also be added in the future—with
optional padding within `addresses`, if they require certain alignment.

### Security Considerations for Node Aliases

Node aliases are user-defined and provide a potential avenue for injection
attacks, both during the process of rendering and during persistence.

Node aliases should always be sanitized before being displayed in
HTML/Javascript contexts or any other dynamically interpreted rendering
frameworks. Similarly, consider using prepared statements, input validation,
and escaping to protect against injection vulnerabilities and persistence
engines that support SQL or other dynamically interpreted querying languages.

* [Stored and Reflected XSS Prevention](https://www.owasp.org/index.php/XSS_(Cross_Site_Scripting)_Prevention_Cheat_Sheet)
* [DOM-based XSS Prevention](https://www.owasp.org/index.php/DOM_based_XSS_Prevention_Cheat_Sheet)
* [SQL Injection Prevention](https://www.owasp.org/index.php/SQL_Injection_Prevention_Cheat_Sheet)

Don't be like the school of [Little Bobby Tables](https://xkcd.com/327/).

## The `channel_update` Message

After a channel has been initially announced, each side independently
announces the fees and minimum expiry delta it requires to relay HTLCs
through this channel. Each uses the 8-byte channel shortid that matches the
`channel_announcement` and the 1-bit `flags` field to indicate which end of the
channel it's on (origin or final). A node can do this multiple times, in
order to change fees.

Note that the `channel_update` message is only useful in the context
of *relaying* payments, not *sending* payments. When making a payment
 `A` -> `B` -> `C` -> `D`, only the `channel_update`s related to channels
 `B` -> `C` (announced by `B`) and `C` -> `D` (announced by `C`) will
 come into play. When building the route, amounts and expiries for HTLCs need
 to be calculated backward from the destination to the source. The exact initial
 value for `amount_msat` and the minimal value for `cltv_expiry`, to be used for
 the last HTLC in the route, are provided in the payment request
 (see [BOLT #11](11-payment-encoding.md#tagged-fields)).

1. type: 258 (`channel_update`)
2. data:
    * [`64`:`signature`]
    * [`32`:`chain_hash`]
    * [`8`:`short_channel_id`]
    * [`4`:`timestamp`]
    * [`2`:`flags`]
    * [`2`:`cltv_expiry_delta`]
    * [`8`:`htlc_minimum_msat`]
    * [`4`:`fee_base_msat`]
    * [`4`:`fee_proportional_millionths`]

The `flags` bitfield is used to indicate the direction of the channel: it
identifies the node that this update originated from and signals various options
concerning the channel. The following table specifies the meaning of its
individual bits:

| Bit Position  | Name        | Meaning                          |
| ------------- | ----------- | -------------------------------- |
| 0             | `direction` | Direction this update refers to. |
| 1             | `disable`   | Disable the channel.             |

The `node_id` for the signature verification is taken from the corresponding
`channel_announcement`: `node_id_1` if the least-significant bit of flags is 0
or `node_id_2` otherwise.

### Requirements

The origin node:
  - MAY create a `channel_update` to communicate the channel parameters to the
  final node, even though the channel has not yet been announced (i.e. the
  `announce_channel` bit was not set).
    - MUST NOT forward such a `channel_update` to other peers, for privacy
    reasons.
    - Note: such a `channel_update`, one not preceded by a
    `channel_announcement`, is invalid to any other peer and would be discarded.
  - MUST set `signature` to the signature of the double-SHA256 of the entire
  remaining packet after `signature`, using its own `node_id`.
  - MUST set `chain_hash` AND `short_channel_id` to match the 32-byte hash AND
  8-byte channel ID that uniquely identifies the channel specified in the
  `channel_announcement` message.
  - if the origin node is `node_id_1` in the message:
    - MUST set the `direction` bit of `flags` to 0.
  - otherwise:
    - MUST set the `direction` bit of `flags` to 1.
  - MUST set bits that are not assigned a meaning to 0.
  - MAY create and send a `channel_update` with the `disable` bit set to 1, to
  signal a channel's temporary unavailability (e.g. due to a loss of
  connectivity) OR permanent unavailability (e.g. prior to an on-chain
  settlement).
    - MAY sent a subsequent `channel_update` with the `disable` bit  set to 0 to
    re-enable the channel.
  - MUST set `timestamp` to greater than 0, AND to greater than any
  previously-sent `channel_update` for this `short_channel_id`.
    - SHOULD base `timestamp` on a UNIX timestamp.
  - MUST set `cltv_expiry_delta` to the number of blocks it will subtract from
  an incoming HTLC's `cltv_expiry`.
  - MUST set `htlc_minimum_msat` to the minimum HTLC value (in millisatoshi)
  that the final node will accept.
  - MUST set `fee_base_msat` to the base fee (in millisatoshi) it will charge
  for any HTLC.
  - MUST set `fee_proportional_millionths` to the amount (in millionths of a
  satoshi) it will charge per transferred satoshi.

The final node:
  - if the `short_channel_id` does NOT match a previous `channel_announcement`,
  OR if the channel has been closed in the meantime:
    - MUST ignore `channel_update`s that do NOT correspond to one of its own
    channels.
  - SHOULD accept `channel_update`s for its own channels (even if non-public),
  in order to learn the associated origin nodes' forwarding parameters.
  - if `signature` is not a valid signature, using `node_id` of the
  double-SHA256 of the entire message following the `signature` field (including
  unknown fields following `fee_proportional_millionths`):
    - MUST NOT process the message further.
    - SHOULD fail the connection.
  - if the specified `chain_hash` value is unknown (meaning it isn't active on
  the specified chain):
    - MUST ignore the channel update.
  - if `timestamp` is NOT greater than that of the last-received
  `channel_announcement` for this `short_channel_id` AND for `node_id`:
    - SHOULD ignore the message.
  - otherwise:
    - if the `timestamp` is equal to the last-received `channel_announcement`
    AND the fields (other than `signature`) differ:
      - MAY blacklist this `node_id`.
      - MAY forget all channels associated with it.
  - if the `timestamp` is unreasonably far in the future:
    - MAY discard the `channel_announcement`.
  - otherwise:
    - SHOULD queue the message for rebroadcasting.
    - MAY choose NOT to for messages longer than the minimum expected length.

### Rationale

The `timestamp` field is used by nodes for pruning `channel_update`s that are
either too far in the future or have not been updated in two weeks; so it
makes sense to have it be a UNIX timestamp (i.e. seconds since UTC
1970-01-01). This cannot be a hard requirement, however, given the possible case
of two `channel_update`s within a single second.

## Initial Sync

### Requirements

An endpoint node:
  - upon establishing a connection:
    - SHOULD set the `init` message's `initial_routing_sync` flag to 1, to
    negotiate an initial sync.
  - if it requires a full copy of the other endpoint's routing state:
    - SHOULD set the `initial_routing_sync` flag to 1.
  - upon receiving an `init` message with the `initial_routing_sync` flag set to
  1:
    - SHOULD send `channel_announcement`s, `channel_update`s and
    `node_announcement`s for all known channels and nodes, as if they were just
    received.
  - if the `initial_routing_sync` flag is set to 0, OR if the initial sync was
  completed:
    - SHOULD resume normal operation, as specified in the following
    [Rebroadcasting](#rebroadcasting) section.

## Rebroadcasting

### Requirements

The final node:
  - upon receiving a new `channel_announcement` or a `channel_update` or
  `node_announcement` with an updated `timestamp`:
    - SHOULD update its local view of the network's topology accordingly.
  - after applying the changes from the announcement:
    - if there are no channels associated with the corresponding origin node:
      - MAY purge the origin node from its set of known nodes.
    - otherwise:
      - SHOULD update the appropriate metadata AND store the signature
      associated with the announcement.
        - Note: this will later allow the final node to rebuild the announcement
        for its peers.

An endpoint node:
  - SHOULD flush outgoing announcements once every 60 seconds, independently of
  the arrival times of announcements.
    - Note: this results in staggered announcements that are unique (not
    duplicated).
  - MAY re-announce its channels regularly.
    - Note: this is discouraged, in order to keep the resource requirements low.
  - upon connection establishment:
    - SHOULD send all `channel_announcement` messages, followed by the latest
    `node_announcement` AND `channel_update` messages.

### Rationale

Once the announcement has been processed, it's added to a list of outgoing
announcements, destined for the processing node's peers, replacing any older
updates from the origin node. This list of announcements will be flushed at
regular intervals: such a store-and-delayed-forward broadcast is called a
_staggered broadcast_. Also, such batching of announcements forms a natural rate
limit with low overhead.

The sending of all announcements on reconnection is naive, but simple,
and allows bootstrapping for new nodes as well as updating for nodes that
have been offline for some time.

## HTLC Fees

### Requirements

The origin node:
  - SHOULD accept HTLCs that pay a fee equal to or greater than:
    - fee_base_msat + ( amount_msat * fee_proportional_millionths / 1000000 )
  - SHOULD accept HTLCs that pay an older fee, for some reasonable time after
  sending `channel_update`.
    - Note: this allows for any propagation delay.

## Pruning the Network View

### Requirements

A node:
  - SHOULD monitor the funding transactions in the blockchain, to identify
  channels that are being closed.
  - if the funding output of a channel is being spent:
    - SHOULD be removed from the local network view AND be considered closed.
  - if the announced node no longer has any associated open channels:
    - MAY prune nodes added through `node_announcement` messages from their
    local view.
      - Note: this is a direct result of the dependency of a `node_announcement`
      being preceded by a `channel_announcement`.

### Recommendation on Pruning Stale Entries

#### Requirements

An endpoint node:
  - if a channel's latest `channel_update`s `timestamp` is older than two weeks
  (1209600 seconds):
    - MAY prune the channel.
    - MAY ignore the channel.
    - Note: this is an endpoint node policy and MUST NOT be enforced by
    forwarding peers, e.g. by closing channels when receiving outdated gossip
    messages. [ FIXME: is this intended meaning? ]

#### Rationale

Several scenarios may result in channels becoming unusable and its endpoints
becoming unable to send updates for these channels. For example, this occurs if
both endpoints lose access to their private keys and can neither sign
`channel_update`s nor close the channel on-chain. In this case, the channels are
unlikely to be part of a computed route, since they would be partitioned off
from the rest of the network; however, they would remain in the local network
view would be forwarded to other peers indefinitely.

## Recommendations for Routing

When calculating a route for an HTLC, both the `cltv_expiry_delta` and the fee
need to be considered: the `cltv_expiry_delta` contributes to the time that
funds will be unavailable in the event of a worst-case failure. The relationship
between these two attributes is unclear, as it depends on the reliability of the
nodes involved.

If a route is computed by simply routing to the intended recipient and summing
the `cltv_expiry_delta`s, then it's possible for intermediate nodes to guess
their position in the route. Knowing the CLTV of the HTLC, the surrounding
network topology, and the `cltv_expiry_delta`s gives an attacker a way to guess
the intended recipient. Therefore, it's highly desirable to add a random offset
to the CLTV that the intended recipient will receive, which bumps all CLTVs
along the route.

In order to create a plausible offset, the origin node MAY start a limited
random walk on the graph, starting from the intended recipient and summing the
`cltv_expiry_delta`s, and use the resulting sum as the offset.
This effectively creates a _shadow route extension_ to the actual route and
provides better protection against this attack vector than simply picking a
random offset would.

Other more advanced considerations involve diversification of route selection,
to avoid single points of failure and detection, and balancing of local
channels.

### Routing Example

Consider four nodes:


```
   B
  / \
 /   \
A     C
 \   /
  \ /
   D
```

Each advertises the following `cltv_expiry_delta` on its end of every
channel:

1. A: 10 blocks
2. B: 20 blocks
3. C: 30 blocks
4. D: 40 blocks

C also uses a `min_final_cltv_expiry` of 9 (the default) when requesting
payments.

Also, each node has a set fee scheme that it uses for each of its
channels:

1. A: 100 base + 1000 millionths
2. B: 200 base + 2000 millionths
3. C: 300 base + 3000 millionths
4. D: 400 base + 4000 millionths

The network will see eight `channel_update` messages:

1. A->B: `cltv_expiry_delta` = 10, `fee_base_msat` = 100, `fee_proportional_millionths` = 1000
1. A->D: `cltv_expiry_delta` = 10, `fee_base_msat` = 100, `fee_proportional_millionths` = 1000
1. B->A: `cltv_expiry_delta` = 20, `fee_base_msat` = 200, `fee_proportional_millionths` = 2000
1. D->A: `cltv_expiry_delta` = 40, `fee_base_msat` = 400, `fee_proportional_millionths` = 4000
1. B->C: `cltv_expiry_delta` = 20, `fee_base_msat` = 200, `fee_proportional_millionths` = 2000
1. D->C: `cltv_expiry_delta` = 40, `fee_base_msat` = 400, `fee_proportional_millionths` = 4000
1. C->B: `cltv_expiry_delta` = 30, `fee_base_msat` = 300, `fee_proportional_millionths` = 3000
1. C->D: `cltv_expiry_delta` = 30, `fee_base_msat` = 300, `fee_proportional_millionths` = 3000

**B->C.** If B were to send 4,999,999 millisatoshi directly to C, it would
neither charge itself a fee nor add its own `cltv_expiry_delta`, so it would
use C's requested `min_final_cltv_expiry` of 9. Presumably it would also add a
_shadow route_ to give an extra CLTV of 42. Additionally, it could add extra
CLTV deltas at other hops, as these values represent a minimum, but chooses not
to do so here, for the sake of simplicity:

   * `amount_msat`: 4999999
   * `cltv_expiry`: current-block-height + 9 + 42
   * `onion_routing_packet`:
     * `amt_to_forward` = 4999999
     * `outgoing_cltv_value` = current-block-height + 9 + 42

**A->B->C.** If A were to send 4,999,999 millisatoshi to C via B, it needs to
pay B the fee it specified in the B->C `channel_update`, calculated as
per [HTLC Fees](#htlc_fees):

        fee_base_msat + ( amount_msat * fee_proportional_millionths / 1000000 )

	200 + ( 4999999 * 2000 / 1000000 ) = 10199

Similarly, it would need to add B->C's `channel_update` `cltv_expiry` (20), C's
requested `min_final_cltv_expiry` (9), and the cost for the _shadow route_ (42).
Thus, A->B's `update_add_htlc` message would be:

   * `amount_msat`: 5010198
   * `cltv_expiry`: current-block-height + 20 + 9 + 42
   * `onion_routing_packet`:
     * `amt_to_forward` = 4999999
     * `outgoing_cltv_value` = current-block-height + 9 + 42

B->C's `update_add_htlc` would be the same as B->C's direct payment above.

**A->D->C.** Finally, if for some reason A chose the more expensive route via D,
A->D's `update_add_htlc` message would be:

   * `amount_msat`: 5020398
   * `cltv_expiry`: current-block-height + 40 + 9 + 42
   * `onion_routing_packet`:
	 * `amt_to_forward` = 4999999
     * `outgoing_cltv_value` = current-block-height + 9 + 42

And D->C's `update_add_htlc` would again be the same as B->C's direct payment
above.

## References

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
