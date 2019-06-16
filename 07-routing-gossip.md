# BOLT #7: P2P Node and Channel Discovery

This specification describes simple node discovery, channel discovery, and channel update mechanisms that do not rely on a third-party to disseminate the information.

Node and channel discovery serve two different purposes:

 - Channel discovery allows the creation and maintenance of a local view of the network's topology, so that a node can discover routes to desired destinations.
 - Node discovery allows nodes to broadcast their ID, host, and port, so that other nodes can open connections and establish payment channels with them.

To support channel discovery, three *gossip messages* are supported.   Peers in the network exchange
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
  * [Query Messages](#query-messages)
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

The standard human readable format for `short_channel_id` is created
by printing the above components, in the order:
block height, transaction index, and output index.
Each component is printed as a decimal number,
and separated from each other by the small letter `x`.
For example, a `short_channel_id` might be written as `539268x845x1`,
indicating a channel on the output 1 of the transaction at index 845
of the block at height 539268.

A node:
  - if the `open_channel` message has the `announce_channel` bit set AND a `shutdown` message has not been sent:
    - MUST send the `announcement_signatures` message.
      - MUST NOT send `announcement_signatures` messages until `funding_locked`
      has been sent and received AND the funding transaction has at least six confirmations.
  - otherwise:
    - MUST NOT send the `announcement_signatures` message.
  - upon reconnection (once the above timing requirements have been met):
    - MUST respond to the first `announcement_signatures` message with its own
    `announcement_signatures` message.
    - if it has NOT received an `announcement_signatures` message:
      - SHOULD retransmit the `announcement_signatures` message.

A recipient node:
  - if the `node_signature` OR the `bitcoin_signature` is NOT correct:
    - MAY fail the channel.
  - if it has sent AND received a valid `announcement_signatures` message:
    - SHOULD queue the `channel_announcement` message for its peers.
  - if it has not sent funding_locked:
    - MAY defer handling the announcement_signatures until after it has sent funding_locked
    - otherwise:
      - MUST ignore it.


### Rationale

The reason for allowing deferring of a premature announcement_signatures is
that an earlier version of the spec did not require waiting for receipt of
funding locked: deferring rather than ignoring it allows compatibility with
this behavior.

The `short_channel_id` human readable format is designed
so that double-clicking or double-tapping it will select the entire ID
on most systems.
Humans prefer decimal when reading numbers,
so the ID components are written in decimal.
The small letter `x` is used since on most fonts,
the `x` is visibly smaller than decimal digits,
making it easy to visibly group each component of the ID.

## The `channel_announcement` Message

This gossip message contains ownership information regarding a channel. It ties
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
      - MUST set `chain_hash` value (encoded in hex) equal to `6fe28c0ab6f1b372c1a6a246ae63f74f931e8365e15a089c68d6190000000000`.
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

The receiving node:
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

This gossip message allows a node to indicate extra data associated with it, in
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
    - Note: the first byte of `rgb_color` is the red value, the second byte is the
    green value, and the last byte is the blue value.
  - MUST set `alias` to a valid UTF-8 string, with any `alias` trailing-bytes
  equal to 0.
  - SHOULD fill `addresses` with an address descriptor for each public network
  address that expects incoming connections.
  - MUST set `addrlen` to the number of bytes in `addresses`.
  - MUST place address descriptors in ascending order.
  - SHOULD NOT place any zero-typed address descriptors anywhere.
  - SHOULD use placement only for aligning fields that follow `addresses`.
  - MUST NOT create a `type 1` OR `type 2` address descriptor with `port` equal
  to 0.
  - SHOULD ensure `ipv4_addr` AND `ipv6_addr` are routable addresses.
  - MUST NOT include more than one `address descriptor` of the same type.
  - SHOULD set `flen` to the minimum length required to hold the `features`
  bits it sets.

The receiving node:
  - if `node_id` is NOT a valid compressed public key:
    - SHOULD fail the connection.
    - MUST NOT process the message further.
  - if `signature` is NOT a valid signature (using `node_id` of the
  double-SHA256 of the entire message following the `signature` field, including
any future fields appended to the end):
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
`channel_announcement` and the 1-bit `channel_flags` field to indicate which end of the
channel it's on (origin or final). A node can do this multiple times, in
order to change fees.

Note that the `channel_update` gossip message is only useful in the context
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
    * [`1`:`message_flags`]
    * [`1`:`channel_flags`]
    * [`2`:`cltv_expiry_delta`]
    * [`8`:`htlc_minimum_msat`]
    * [`4`:`fee_base_msat`]
    * [`4`:`fee_proportional_millionths`]
    * [`8`:`htlc_maximum_msat`] (option_channel_htlc_max)

The `channel_flags` bitfield is used to indicate the direction of the channel: it
identifies the node that this update originated from and signals various options
concerning the channel. The following table specifies the meaning of its
individual bits:

| Bit Position  | Name        | Meaning                          |
| ------------- | ----------- | -------------------------------- |
| 0             | `direction` | Direction this update refers to. |
| 1             | `disable`   | Disable the channel.             |

The `message_flags` bitfield is used to indicate the presence of optional
fields in the `channel_update` message:

| Bit Position  | Name                      | Field                            |
| ------------- | ------------------------- | -------------------------------- |
| 0             | `option_channel_htlc_max` | `htlc_maximum_msat`              |

Note that the `htlc_maximum_msat` field is static in the current
protocol over the life of the channel: it is *not* designed to be
indicative of real-time channel capacity in each direction, which
would be both a massive data leak and uselessly spam the network (it
takes an average of 30 seconds for gossip to propagate each hop).

The `node_id` for the signature verification is taken from the corresponding
`channel_announcement`: `node_id_1` if the least-significant bit of flags is 0
or `node_id_2` otherwise.

### Requirements

The origin node:
  - MAY create a `channel_update` to communicate the channel parameters to the
  channel peer, even though the channel has not yet been announced (i.e. the
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
    - MUST set the `direction` bit of `channel_flags` to 0.
  - otherwise:
    - MUST set the `direction` bit of `channel_flags` to 1.
  - if the `htlc_maximum_msat` field is present:
	- MUST set the `option_channel_htlc_max` bit of `message_flags` to 1.
	- MUST set `htlc_maximum_msat` to the maximum value it will send through this channel for a single HTLC.
		- MUST set this to less than or equal to the channel capacity.
		- MUST set this to less than or equal to `max_htlc_value_in_flight_msat`
		  it received from the peer.
        - for channels with `chain_hash` identifying the Bitcoin blockchain:
          - MUST set this to less than 2^32.
  - otherwise:
	- MUST set the `option_channel_htlc_max` bit of `message_flags` to 0.
  - MUST set bits in `channel_flags` and `message_flags `that are not assigned a meaning to 0.
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
  that the channel peer will accept.
  - MUST set `fee_base_msat` to the base fee (in millisatoshi) it will charge
  for any HTLC.
  - MUST set `fee_proportional_millionths` to the amount (in millionths of a
  satoshi) it will charge per transferred satoshi.
  - SHOULD NOT create redundant `channel_update`s

The receiving node:
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
  - if `timestamp` is NOT greater than OR equal to that of the last-received
  `channel_update` for this `short_channel_id` AND for `node_id`:
    - SHOULD ignore the message.
  - otherwise:
    - if the `timestamp` is equal to the last-received `channel_update` for this
    `short_channel_id` AND `node_id`, AND the fields below `timestamp` differ:
      - MAY blacklist this `node_id`.
      - MAY forget all channels associated with it.
  - if the `timestamp` is unreasonably far in the future:
    - MAY discard the `channel_update`.
  - otherwise:
    - SHOULD queue the message for rebroadcasting.
    - MAY choose NOT to for messages longer than the minimum expected length.
  - if the `option_channel_htlc_max` bit of `message_flags` is 0:
    - MUST consider `htlc_maximum_msat` not to be present.
  - otherwise:
    - if `htlc_maximum_msat` is not present or greater than channel capacity:
	  - MAY blacklist this `node_id`
	  - SHOULD ignore this channel during route considerations.
	- otherwise:
	  - SHOULD consider the `htlc_maximum_msat` when routing.

### Rationale

The `timestamp` field is used by nodes for pruning `channel_update`s that are
either too far in the future or have not been updated in two weeks; so it
makes sense to have it be a UNIX timestamp (i.e. seconds since UTC
1970-01-01). This cannot be a hard requirement, however, given the possible case
of two `channel_update`s within a single second.

It is assumed that more than one `channel_update` message changing the channel 
parameters in the same second is a DoS attempt, and therefore, the node responsible 
for signing such messages ought to be blacklisted. However, a node can send a same 
`channel_update` message with a different signature (changing the nonce in signature 
signing), and hence fields apart from signature are checked to see if the channel 
parameters have changed for the same timestamp.

The explicit `option_channel_htlc_max` flag to indicate the presence
of `htlc_maximum_msat` (rather than having `htlc_maximum_msat` implied
by the message length) allows us to extend the `channel_update`
with different fields in future.  Since channels are limited to 2^32-1
millisatoshis in Bitcoin, the `htlc_maximum_msat` has the same restriction.

The recommendation against redundant `channel_update`s minimizes spamming the network,
however it is sometimes inevitable.  For example, a channel with a
peer which is unreachable will eventually cause a `channel_update` to
indicate that the channel is disabled, with another update re-enabling
the channel when the peer reestablishes contact.  Because gossip
messages are batched and replace previous ones, the result may be a
single seemingly-redundant update.

## Query Messages

Negotiating the `gossip_queries` option via `init` enables a number
of extended queries for gossip synchronization.  These explicitly
request what gossip should be received.

There are several messages which contain a long array of
`short_channel_id`s (called `encoded_short_ids`) so we utilize a
simple compression scheme: the first byte indicates the encoding, the
rest contains the data.

Encoding types:
* `0`: uncompressed array of `short_channel_id` types, in ascending order.
* `1`: array of `short_channel_id` types, in ascending order, compressed with zlib deflate<sup>[1](#reference-1)</sup>

Note that a 65535-byte zlib message can decompress into 67632120
bytes<sup>[2](#reference-2)</sup>, but since the only valid contents
are unique 8-byte values, no more than 14 bytes can be duplicated
across the stream: as each duplicate takes at least 2 bits, no valid
contents could decompress to more then 3669960 bytes.

### The `query_short_channel_ids`/`reply_short_channel_ids_end` Messages

1. type: 261 (`query_short_channel_ids`) (`gossip_queries`)
2. data:
    * [`32`:`chain_hash`]
    * [`2`:`len`]
    * [`len`:`encoded_short_ids`]

1. type: 262 (`reply_short_channel_ids_end`) (`gossip_queries`)
2. data:
    * [`32`:`chain_hash`]
    * [`1`:`complete`]

This is a general mechanism which lets a node query for the
`channel_announcement` and `channel_update` messages for specific channels
(identified via `short_channel_id`s). This is usually used either because
a node sees a `channel_update` for which it has no `channel_announcement` or
because it has obtained previously unknown `short_channel_id`s
from `reply_channel_range`.

#### Requirements

The sender:
  - MUST NOT send `query_short_channel_ids` if it has sent a previous `query_short_channel_ids` to this peer and not received `reply_short_channel_ids_end`.
  - MUST set `chain_hash` to the 32-byte hash that uniquely identifies the chain
  that the `short_channel_id`s refer to.
  - MUST set the first byte of `encoded_short_ids` to the encoding type.
  - MUST encode a whole number of `short_channel_id`s to `encoded_short_ids`
  - MAY send this if it receives a `channel_update` for a
   `short_channel_id` for which it has no `channel_announcement`.
  - SHOULD NOT send this if the channel referred to is not an unspent output.

The receiver:
  - if the first byte of `encoded_short_ids` is not a known encoding type:
    - MAY fail the connection
  - if `encoded_short_ids` does not decode into a whole number of `short_channel_id`:
    - MAY fail the connection.
  - if it has not sent `reply_short_channel_ids_end` to a previously received `query_short_channel_ids` from this sender:
    - MAY fail the connection.
  - MUST respond to each known `short_channel_id` with a `channel_announcement`
    and the latest `channel_update` for each end
	- SHOULD NOT wait for the next outgoing gossip flush to send these.
  - MUST follow with any `node_announcement`s for each `channel_announcement`
	- SHOULD avoid sending duplicate `node_announcements` in response to a single `query_short_channel_ids`.
  - MUST follow these responses with `reply_short_channel_ids_end`.
  - if does not maintain up-to-date channel information for `chain_hash`:
	- MUST set `complete` to 0.
  - otherwise:
	- SHOULD set `complete` to 1.

#### Rationale

Future nodes may not have complete information; they certainly won't have
complete information on unknown `chain_hash` chains.  While this `complete`
field cannot be trusted, a 0 does indicate that the sender should search
elsewhere for additional data.

The explicit `reply_short_channel_ids_end` message means that the receiver can
indicate it doesn't know anything, and the sender doesn't need to rely on
timeouts.  It also causes a natural ratelimiting of queries.

### The `query_channel_range` and `reply_channel_range` Messages

1. type: 263 (`query_channel_range`) (`gossip_queries`)
2. data:
    * [`32`:`chain_hash`]
    * [`4`:`first_blocknum`]
    * [`4`:`number_of_blocks`]

1. type: 264 (`reply_channel_range`) (`gossip_queries`)
2. data:
    * [`32`:`chain_hash`]
    * [`4`:`first_blocknum`]
    * [`4`:`number_of_blocks`]
    * [`1`:`complete`]
    * [`2`:`len`]
    * [`len`:`encoded_short_ids`]

This allows a query for channels within specific blocks.

#### Requirements

The sender of `query_channel_range`:
  - MUST NOT send this if it has sent a previous `query_channel_range` to this peer and not received all `reply_channel_range` replies.
  - MUST set `chain_hash` to the 32-byte hash that uniquely identifies the chain
  that it wants the `reply_channel_range` to refer to
  - MUST set `first_blocknum` to the first block it wants to know channels for
  - MUST set `number_of_blocks` to 1 or greater.

The receiver of `query_channel_range`:
  - if it has not sent all `reply_channel_range` to a previously received `query_channel_range` from this sender:
    - MAY fail the connection.
  - MUST respond with one or more `reply_channel_range` whose combined range
	cover the requested `first_blocknum` to `first_blocknum` plus
	`number_of_blocks` minus one.
  - For each `reply_channel_range`:
    - MUST set with `chain_hash` equal to that of `query_channel_range`,
    - MUST encode a `short_channel_id` for every open channel it knows in blocks `first_blocknum` to `first_blocknum` plus `number_of_blocks` minus one.
    - MUST limit `number_of_blocks` to the maximum number of blocks whose
      results could fit in `encoded_short_ids`
    - if does not maintain up-to-date channel information for `chain_hash`:
      - MUST set `complete` to 0.
    - otherwise:
      - SHOULD set `complete` to 1.

#### Rationale

A single response might be too large for a single packet, and also a peer can
store canned results for (say) 1000-block ranges, and simply offer each reply
which overlaps the ranges of the request.

### The `gossip_timestamp_filter` Message

1. type: 265 (`gossip_timestamp_filter`) (`gossip_queries`)
2. data:
    * [`32`:`chain_hash`]
    * [`4`:`first_timestamp`]
    * [`4`:`timestamp_range`]

This message allows a node to constrain future gossip messages to
a specific range.  A node which wants any gossip messages would have
to send this, otherwise `gossip_queries` negotiation means no gossip
messages would be received.

Note that this filter replaces any previous one, so it can be used
multiple times to change the gossip from a peer.

#### Requirements

The sender:
  - MUST set `chain_hash` to the 32-byte hash that uniquely identifies the chain
  that it wants the gossip to refer to.

The receiver:
  - SHOULD send all gossip messages whose `timestamp` is greater or
    equal to `first_timestamp`, and less than `first_timestamp` plus
    `timestamp_range`.
	- MAY wait for the next outgoing gossip flush to send these.
  - SHOULD restrict future gossip messages to those whose `timestamp`
    is greater or equal to `first_timestamp`, and less than
    `first_timestamp` plus `timestamp_range`.
  - If a `channel_announcement` has no corresponding `channel_update`s:
	- MUST NOT send the `channel_announcement`.
  - Otherwise:
	  - MUST consider the `timestamp` of the `channel_announcement` to be the `timestamp` of a corresponding `channel_update`.
	  - MUST consider whether to send the `channel_announcement` after receiving the first corresponding `channel_update`.
  - If a `channel_announcement` is sent:
	  - MUST send the `channel_announcement` prior to any corresponding `channel_update`s and `node_announcement`s.

#### Rationale

Since `channel_announcement` doesn't have a timestamp, we generate a likely
one.  If there's no `channel_update` then it is not sent at all, which is most
likely in the case of pruned channels.

Otherwise the `channel_announcement` is usually followed immediately by a
`channel_update`. Ideally we would specify that the first (oldest) `channel_update`'s
timestamp is to be used as the time of the `channel_announcement`, but new nodes on
the network will not have this, and further would require the first `channel_update`
timestamp to be stored. Instead, we allow any update to be used, which
is simple to implement.

In the case where the `channel_announcement` is nonetheless missed,
`query_short_channel_ids` can be used to retrieve it.

## Initial Sync

If a node requires an initial sync of gossip messages, it will be flagged
in the `init` message, via a feature flag ([BOLT #9](09-features.md#assigned-localfeatures-flags)).

Note that the `initial_routing_sync` feature is overridden (and should
be considered equal to 0) by the `gossip_queries` feature if the
latter is negotiated via `init`.

Note that `gossip_queries` does not work with older nodes, so the
value of `initial_routing_sync` is still important to control
interactions with them.

### Requirements

A node:
  - if the `gossip_queries` feature is negotiated:
	- MUST NOT relay any gossip messages unless explicitly requested.
  - otherwise:
    - if it requires a full copy of the peer's routing state:
      - SHOULD set the `initial_routing_sync` flag to 1.
    - upon receiving an `init` message with the `initial_routing_sync` flag set to
    1:
      - SHOULD send gossip messages for all known channels and nodes, as if they were just
      received.
    - if the `initial_routing_sync` flag is set to 0, OR if the initial sync was
    completed:
      - SHOULD resume normal operation, as specified in the following
      [Rebroadcasting](#rebroadcasting) section.

## Rebroadcasting

### Requirements

A receiving node:
  - upon receiving a new `channel_announcement` or a `channel_update` or
  `node_announcement` with an updated `timestamp`:
    - SHOULD update its local view of the network's topology accordingly.
  - after applying the changes from the announcement:
    - if there are no channels associated with the corresponding origin node:
      - MAY purge the origin node from its set of known nodes.
    - otherwise:
      - SHOULD update the appropriate metadata AND store the signature
      associated with the announcement.
        - Note: this will later allow the node to rebuild the announcement
        for its peers.

A node:
  - if the `gossip_queries` feature is negotiated:
	- MUST not send gossip until it receives `gossip_timestamp_range`.
  - SHOULD flush outgoing gossip messages once every 60 seconds, independently of
  the arrival times of the messages.
    - Note: this results in staggered announcements that are unique (not
    duplicated).
  - MAY re-announce its channels regularly.
    - Note: this is discouraged, in order to keep the resource requirements low.
  - upon connection establishment:
    - SHOULD send all `channel_announcement` messages, followed by the latest
    `node_announcement` AND `channel_update` messages.

### Rationale

Once the gossip message has been processed, it's added to a list of outgoing
messages, destined for the processing node's peers, replacing any older
updates from the origin node. This list of gossip messages will be flushed at
regular intervals; such a store-and-delayed-forward broadcast is called a
_staggered broadcast_. Also, such batching forms a natural rate
limit with low overhead.

The sending of all gossip on reconnection is naive, but simple,
and allows bootstrapping for new nodes as well as updating for nodes that
have been offline for some time.  The `gossip_queries` option
allows for more refined synchronization.

## HTLC Fees

### Requirements

The origin node:
  - SHOULD accept HTLCs that pay a fee equal to or greater than:
    - fee_base_msat + ( amount_to_forward * fee_proportional_millionths / 1000000 )
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

A node:
  - if a channel's latest `channel_update`s `timestamp` is older than two weeks
  (1209600 seconds):
    - MAY prune the channel.
    - MAY ignore the channel.
    - Note: this is an individual node policy and MUST NOT be enforced by
    forwarding peers, e.g. by closing channels when receiving outdated gossip
    messages.

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
per [HTLC Fees](#htlc-fees):

        fee_base_msat + ( amount_to_forward * fee_proportional_millionths / 1000000 )

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

1. <a id="reference-1">[RFC 1950 "ZLIB Compressed Data Format Specification version 3.3](https://www.ietf.org/rfc/rfc1950.txt)</a>
2. <a id="reference-2">[Maximum Compression Factor](https://zlib.net/zlib_tech.html)</a>

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
