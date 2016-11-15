# BOLT #7: P2P Node and Channel Discovery

This specification describes a simple initial node and channel discovery mechanism that does not rely on a third-party to disseminate the information.

Node and channel discovery serve two different purposes:

 - Channel discovery allows the creation and maintenance of a local view of the network's topology such that the node can discover routes to desired destination.
 - Node discovery allows nodes to broadcast their ID, host and port, such that other nodes can open connections and establish payment channels.
 
Peers in the network exchange `route_announcement` messages that contain information about a node and about its outgoing channels.
The node creating an announcement is referred to as the _announcing node_.
Announcements MUST have at least one associated channel whose existence can be proven by inspection of the blockchain, i.e., the anchor transaction creating the channel MUST have been confirmed.

Nodes receiving an announcement verify that this is the latest update from the announcing node by comparing the included timestamp and update their local view of the network's topology accordingly.
The receiving node removes all channels that are signaled to be removed or are no longer included in the announcement, adds any new channels and adjusts the parameters of the existing channels.
Notice that this specification does not include any mechanism for differential announcements, i.e., every announcement ships the entire final state for that node.

Once the announcement has been processed it is added to a list of outgoing announcements to the processing node's peers, which will be flushed at regular intervals.
This store and delayed forward broadcast is called a _staggered broadcast_

Notice that each announcement will only announce a single direction of the channel, i.e., the outgoing direction from the point of view of the announcing node.
The other direction will be announced by the other endpoint of the channel.
This reflects the willingness of the announcing node to forward payments over the announced channel.

## Message Format

This specification defines one message type with identifier 256 (`0x00000100`), called a `MSG_ROUTING_UPDATE`.
It comprises both the sending node's identity and contact information as well as all of its outgoing channels.

```
[4:timestamp]
[33:node_id]
[16:ipv6]
[2:port]
[3:rgb_color]
[var:alias]
[4+X*46:channels]
[64:signature]
```

The timestamp is required to be monotonically increasing from one update to another, it MAY correspond to unix timestamp when the sending node created the announcement.
The node ID is a 33 byte compressed public key that uniquely identifies the node in the network and matches the signature.
The IPv6 field is used for both IPv4 and IPv6 addresses, using the IPv4-Mapped IPv6 Address format defined in [RFC 4291 section 2.5.5.2](https://tools.ietf.org/html/rfc4291#section-2.5.5.2):

```
|                80 bits               | 16 |      32 bits        |
+--------------------------------------+--------------------------+
|0000..............................0000|FFFF|    IPv4 address     |
+--------------------------------------+----+---------------------+
```

The alias is a length prefixed UTF-8 encoded string.
The UTF-8 encoded string is prefixed by a 4 byte unsigned int in network byte order, defining the length of the string.
The RGB color and alias MAY be used by the node operator to customize their node's appearance in maps and graphs, and MAY be used to reference nodes in interfaces.
Notice however that there is no collision protection for aliases, hence the node ID MUST be verified before initiating any transfer.

The `channels` field comprises a 4 byte unsigned int count of channels that follow.
Each channel has the following format:

```
[33:destination]
[4:blockheight]
[4:blockindex]
[1:expiry]
[2:fee_base]
[2:fee_proportional]
```

The `destination` field is the node ID of the remote node from the point of view of the announcing node.
Thus the `node_id` from the enclosing announcement and the `destination` identify the two endpoints of the channel.
The `blockheight` and `blockindex` MAY be combined to form a globally unique `channel_id` that MAY be used to identify the channel in future.
The remaining fields determine the minimum timelock difference that HTLCs have to respect (`expiry`) and the fees that the announcing node expected when routing a payment through the announced channel from `node_id` to `destination`.

## Creation and Processing of Announcements

The announcing node creates the message with the node's information and all its channels.
Normal removal of a channel is done by omitting the channel in the `channels` field.
Notice that this does not allow removing a channel if no active channels are left open, since an announcement requires at least one channel in the `channels` field to be valid.
An explicit removal of all channel MAY be signaled by creating an announcement that includes only one last channel to be closed, and setting the `expiry` field of that channel to `0xFF`.

The announcing node serializes the message omitting the `signature` field, and computes the signature on the partial serialized message using the private key matching the `node_id` in the message.
The signature is then serialized and appended to the message, completing the message.

The announcing peer then sends the announcement to its peers, initiating the broadcast.

Upon receiving an announcement the nodes verifies the validity of the announcement.
In order to be valid the following conditions MUST be satisfied:

 - The timestamp MUST be larger than the last valid announcement from the announcing node.
 - The anchor transactions for each channel, identified by the (`blockheight`, `blockindex`)-tuple must have reached at least the configurable minimum number of confirmations.
 - The signature in the announcement MUST be a valid signature from the public key in the `node_id` field for the message up to the signature itself.
 - The announcement MUST have at least on valid channel. The validity of the channel can be verified by inspecting the anchor transaction specified in the announcement.
 - If the `expiry` field of any channel is set to `0xFF` then it MUST be the only channel in the announcement.

If an announcement is not valid, it MUST be discarded, otherwise the node applies it to its local view of the topology:
the receiving node removes all channels from its local view that match the `node_id` as the origin of the channel, i.e., all channels that have been previously announced by that node, and adds all channels in the announcement unless they have an `expiry` field of `0xFF`.

If, after applying the changes from the announcement, there are no channels associated with the announcing node, then the receiving node MAY purge the announcing node from the set of known nodes.
Otherwise the receiving node updates the metadata and stores the signature associated with the announcement.
This will later allow the receiving node to rebuild the announcement for its peers.

After processing the announcement the receiving node adds the announcement to a list of outgoing announcements.
The list of outgoing announcement MUST NOT contain multiple announcements with the same `node_id`, duplicates MUST be removed and announcements with lower `timestamp` fields MUST be replaced.
This list of outgoing announcements is flushed once every 60 seconds, independently of the arrival times of announcements, resulting in a staggered announcement and deduplication of announcements.

Nodes MAY re-announce their channels regularly, however this is discouraged in order to keep the resource requirements low.
In order to bootstrap nodes that were not online at the time of the broadcast nodes will announce all known nodes and their associated channels at the time of connection establishment.
The individual announcements can be reconstructed from the set of known nodes, containing the metadata and signatures for the announcements, and the routing table, containing the channel information.
The broadcast is stopped after the first hop since the peers of the newly joined node already have the announcement and the timestamp check will fail.

## References

 - [RFC 4291](https://tools.ietf.org/html/rfc4291)
