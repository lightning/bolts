# BOLT #7: P2P Node and Channel Discovery

This specification describes simple node discovery, channel discovery and channel update mechanisms which do not rely on a third-party to disseminate the information.

Node and channel discovery serve two different purposes:

 - Channel discovery allows the creation and maintenance of a local view of the network's topology such that the node can discover routes to the desired destination.
 - Node discovery allows nodes to broadcast their ID, host and port, such that other nodes can open connections and establish payment channels.
 
Peers in the network exchange `channel_announcement` messages that contain information about new channels between two nodes.  They can also exchange `node_announcement` messages which supply additional information about nodes, and `channel_update` messages which update information about a channel.

There can only be one valid `channel_announcement` for any channel,
but multiple `node_announcement` messages are possible (to update node
information), and at least two `channel_update` messages are expected.

## The `channel_announcement` message

This message contains ownership information about a channel.  It ties each
on-chain Bitcoin key to the lightning node key, and vice-versa.

The channel is not really usable until at least one side has announced
its fee levels and expiry using `channel_update`.

1. type: 256 (`channel_announcement`)
2. data:
    * [64:node-signature-1]
    * [64:node-signature-2]
    * [8:channel-id]
    * [64:bitcoin-signature-1]
    * [64:bitcoin-signature-2]
    * [33:node-id-1]
    * [33:node-id-2]
    * [33:bitcoin-key-1]
    * [33:bitcoin-key-2]

### Requirements

The creating node MUST set `channel-id` to refer to the confirmed
funding transaction as specified in [BOLT #2](02-peer-protocol.md#the-funding_locked-message).  The corresponding output MUST be a
P2WSH as described in [BOLT #3](03-transactions.md#funding-transaction-output).

The creating node MUST set `node-id-1` and `node-id-2` to the public
keys of the two nodes who are operating the channel, such that
`node-id-1` is the numerically-lesser of the two DER encoded keys.
ascending numerical order, and MUST set `bitcoin-key-1` and
`bitcoin-key-2` to `funding-pubkey`s of `node-id-1` and `node-id-2`
respectively.

The creating node MUST set `bitcoin-signature-1` to the signature of
the double-SHA256 of `node-id-1` using `bitcoin-key-1`, and set
`bitcoin-signature-2` to the signature of the double-SHA256 of
`node-id-2` using `bitcoin-key-2`

The creating node MUST set `node-signature-1` and `node-signature-2`
to the signature of the double-SHA256 of the message after the end of
`node-signature-2`, using `node-id-1` and `node-id-2` as keys respectively.

The receiving node MUST ignore the message if the output specified
by `channel-id` does not
correspond to a P2WSH using `bitcoin-key-1` and `bitcoin-key-2` as
specified in [BOLT #3](03-transactions.md#funding-transaction-output).
The receiving node MUST ignore the message if this output is spent.

Otherwise, the receiving node SHOULD fail the connection if
`bitcoin-signature-1`, `bitcoin-signature-2`, `node-signature-1` or
`node-signature-2` are invalid or not correct.

Otherwise, if `node-id-1` or `node-id-2` are blacklisted, it SHOULD
ignore the message.

Otherwise, if the transaction referred to was not previously announced
as a channel, the receiving node SHOULD queue the message for
rebroadcasting.  If it has previously received a valid
`channel_announcement` for the same transaction in the same block, but
different `node-id-1` or `node-id-2`, it SHOULD blacklist the
previous message's `node-id-1` and `node-id-2` as well as this
`node-id-1` and `node-id-2` and forget channels connected to them,
otherwise it SHOULD store this `channel_announcement`.

The receiving node SHOULD forget a channel once its funding output has
been spent or reorganized out.

## Rationale

Requiring both nodes to sign indicates they are both willing to route
other payments via this node (ie. take part of the public network).
Requiring the Bitcoin signatures proves they control the channel.

The blacklisting of conflicting nodes means that we disallow multiple
different announcements: no node should ever do this, as it implies
that keys have leaked.

While channels shouldn't be advertised before they are sufficiently
deep, the requirement against rebroadcasting only applies if the
transaction hasn't moved to a different block.

## The `node_announcement` message

This allows a node to indicate extra data associated with it, in
addition to its public key.  To avoid trivial denial of service attacks,
nodes for which a channel is not already known are ignored.

1. type: 257 (`node_announcement`)
2. data:
   * [64:signature]
   * [4:timestamp]
   * [16:ipv6]
   * [2:port]
   * [33:node-id]
   * [3:rgb-color]
   * [2:pad]
   * [32:alias]

The `timestamp` allows ordering in the case of multiple announcements;
the `ipv6` and `port` allow the node to announce its willingness to
accept incoming network connections, the `rgb-color` and `alias` allow
intelligence services to give their nodes cool monikers like IRATEMONK
and WISTFULTOLL and use the color black.

### Requirements

The creating node MUST set `timestamp` to be greater than any previous
`node_announcement` it has created.  It MAY base it on a UNIX
timestamp.  It MUST set the `ipv6` and `port` fields to all zeroes, or
a non-zero `port` and `ipv6` set to a valid IPv6 address or an IPv4-Mapped IPv6 Address format as defined in [RFC 4291 section 2.5.5.2](https://tools.ietf.org/html/rfc4291#section-2.5.5.2).  It MUST set `signature` to the signature of
the double-SHA256 of the entire remaining packet after `signature` using the
key given by `node-id`.  It MUST set `pad` to zero.  It MAY set `alias` and `rgb-color` to customize their node's appearance in maps and graphs, where the first byte of `rgb` is the red value, the second byte is the green value and the last byte is the blue value.  It MUST set `alias` to a valid UTF-8 string of up to 21 bytes in length, with all `alias` bytes following equal to zero.

The receiving node SHOULD fail the connection if `signature` is
invalid or incorrect for the entire message including unknown fields
following `alias`, and MUST NOT further process the message.  The
receiving node SHOULD ignore `ipv6` if `port` is zero.  It SHOULD fail
the connection if the final byte of `alias` is not zero.  It MUST ignore
the contents of `pad`.

The receiving node SHOULD ignore the message if `node-id` is not
previously known from a `channel_announcement` message, or if
`timestamp` is not greater than the last-received
`node_announcement` from this `node-id`.  Otherwise, if the
`timestamp` is greater than the last-received `node_announcement` from
this `node-id` the receiving node SHOULD queue the message for
rebroadcasting.

The receiving node MAY use `rgb` and `alias` to reference nodes in interfaces, but SHOULD insinuate their self-signed origin.

### Rationale

RFC 4291 section 2.5.5.2 described IPv4 addresses like so:

```
|                80 bits               | 16 |      32 bits        |
+--------------------------------------+--------------------------+
|0000..............................0000|FFFF|    IPv4 address     |
+--------------------------------------+----+---------------------+
```

## The `channel_update` message

After a channel has been initially announced, each side independently
announces its fees and minimum expiry for HTLCs.  It uses the 8-byte
channel shortid which matches the `channel_announcement` and one byte
to indicate which end this is.  It can do this multiple times, if
it wants to change fees.

1. type: 258 (`channel_update`)
2. data:
    * [64:signature]
    * [8:channel-id]
    * [4:timestamp]
    * [2:flags]
    * [2:expiry]
    * [4:htlc-minimum-msat]
    * [4:fee-base-msat]
    * [4:fee-proportional-millionths]

### Requirements

The creating node MUST set `signature` to the signature of the
double-SHA256 of the entire remaining packet after `signature` using its own `node-id`.

The creating node MUST set `channel-id` to
match those in the already-sent `channel_announcement` message, and MUST set the least-significant bit of `flags` to 0 if the creating node is `node-id-1` in that message, otherwise 1.  It MUST set other bits of `flags` to zero.

The creating node MUST set `timestamp` to greater than zero, and MUST set it to greater than any previously-sent `channel_update` for this channel.

It MUST set `expiry` to the number of blocks it will subtract from an incoming HTLC's `expiry`.  It MUST set `htlc-minimum-msat` to the minimum HTLC value it will accept, in millisatoshi.  It MUST set `fee-base-msat` to the base fee it will charge for any HTLC, in millisatoshi, and `fee-proportional-millionths` to the amount it will charge per millionth of a satoshi.

The receiving node MUST ignore `flags` other than the least significant bit.
The receiving node SHOULD fail
the connection if `signature` is invalid or incorrect for the entire
message including unknown fields following `signature`, and MUST NOT
further process the message.  The receiving node SHOULD ignore `ipv6`
if `port` is zero.  It SHOULD ignore the message if `channel-id`does
not correspond to a previously
known, unspent channel from `channel_announcement`, otherwise the node-id
is taken from the `channel_announcement` `node-id-1` if least-significant bit of flags is 0 or `node-id-2` otherwise.

The receiving node SHOULD ignore the message if `timestamp`
is not greater than than the last-received `channel_announcement` for
this channel and node-id.  Otherwise, if the `timestamp` is equal to
the last-received `channel_announcement` and the fields other than
`signature` differ, the node MAY blacklist this node-id and forget all
channels associated with it.  Otherwise the receiving node SHOULD
queue the message for rebroadcasting.

## Rebroadcasting

Nodes receiving a new `channel_announcement` or a `channel_update` or
`node_update` with an updated timestamp update their local view of the network's topology accordingly.

Once the announcement has been processed it is added to a list of outgoing announcements (perhaps replacing older updates) to the processing node's peers, which will be flushed at regular intervals.
This store and delayed forward broadcast is called a _staggered broadcast_

If, after applying the changes from the announcement, there are no channels associated with the announcing node, then the receiving node MAY purge the announcing node from the set of known nodes.
Otherwise the receiving node updates the metadata and stores the signature associated with the announcement.
This will later allow the receiving node to rebuild the announcement for its peers.

After processing the announcement the receiving node adds the announcement to a list of outgoing announcements.

### Requirements

Each node SHOULD flush outgoing announcements once every 60 seconds, independently of the arrival times of announcements, resulting in a staggered announcement and deduplication of announcements.

Nodes MAY re-announce their channels regularly, however this is discouraged in order to keep the resource requirements low.

Nodes SHOULD send all `channel_announcement` messages followed by the
latest `node_announcement` and `channel_update` messages upon
connection establishment.

### Rationale

Batching announcements form a natural ratelimit with low overhead.

The sending of all announcements on reconnection is naive, but simple,
and allows bootstrap for new nodes as well as updating for nodes which
have been offline for some time.

## HTLC Fees

The node creating `channel_update` SHOULD accept HTLCs which pay a fee equal or greater than:

    fee-base-msat + htlc-amount-msat * fee-proportional-millionths / 1000000

The node creating `channel_update` SHOULD accept HTLCs which pay an
older fee for some time after sending `channel_update` to allow for
propagation delay.

## Recommendations for Routing

As the fee is proportional, it must be calculated backwards from the
destination to the source: only the amount required at the final
destination is known initially.

When calculating a route for an HTLC, the `expiry` and the fee both
need to be considered: the `expiry` contributes to the time that funds
will be unavailable on worst-case failure.  The tradeoff between these
two is unclear, as it depends on the reliability of nodes.

Other more advanced considerations involve diversity of routes to
avoid single points of failure and detection, and channel balance
of local channels.

## References

 - [RFC 4291](https://tools.ietf.org/html/rfc4291)

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
