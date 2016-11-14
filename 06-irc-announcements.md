# Interim Node and Channel Discovery

This specification describes the provisorial node and channel discovery using IRC.
It will eventually be superseded by a discovery mechanism that does not rely on a centralized server for communication.

Node and channel discovery serve two different purposes:

 - Channel discovery allows the creation and maintenance of a local view of the network's topology such that the node can discover routes to desired destination.
 - Node discovery allows nodes to broadcast their ID, host and port, such that other nodes can open connections and establish payment.

## Announcements

The current transport of node and channel announcements is IRC. As such implementations MUST currently include a basic IRC implementation as well, though this transport is eventually going to be superseded by a P2P transport.
Please refer to [RFC 1459](https://tools.ietf.org/html/rfc1459) for implementation details of the IRC protocol.
A minimal working implementation MUST include support for the `JOIN`, `PING`/`PONG`, `PRIVMSG`, `USER` and `NICK` messages.
Lightning nodes wishing to discover nodes and channels MUST connect to the *Freenode* IRC network and join the channel `#lightning-nodes`.
All message exchanges among nodes are done using `PRIVMSG`s to the `#lightning-nodes` channel, however nodes MAY also accept direct `PRIVMSG`s directed to them, i.e., `PRIVMSG`s that have their nickname as destination. Using direct `PRIVMSG`s is discouraged in order to keep the load on third party servers minimal.

Announcements are triggered either by a timer or a `JOIN` message on the channel, a long timeout on the node or a change in the node's state.

 - A `JOIN` message starts a random timer between 0 and 60 seconds on the node. Upon expiry of the timer the node MUST send a `NODE` message announcing its contact information, as well as a `CHAN` message for each of its active channels.
 - Nodes schedule regular updates by setting a long timer every 6 hours. Upon expiry of the timer the node announce their node as well as each of their active channels. Notice that an intermediate `JOIN`-triggered announcement MAY reset the timer, so that a single timer MAY be reused for both announcements.
 - Upon changes of the local state the node MUST selectively announce the new information. Local state changes include changes in contact information, i.e., host/port and alias changes, as well as channel state changes, i.e., new channels being added or capacity changes.

### Common Message Format

All messages consist of 4 space separated parts:

 - A *signature* proving the authenticity of the message.
 - A *message type* indicating whether it is a *node announcement* or a *channel announcement*.
 - A compressed *public key* that identifies the sender of the message.
 - A variable number of *arguments* depending on the type of the message.

Parts are separated by a single space (`0x20`).
The signature and the public key are hex-encoded, while the message type is the ASCII string `NODE` in the case of a node announcement and `CHAN` in the case of a channel announcement.

### `NODE` message

The node message is used to announce the presence of a lightning node and signal the that node is accepting incoming connections.
The node message has 2 mandatory arguments and 1 option argument:

 - `host`: the hostname or IP of the node. For IP nodes MUST implement parsing of both IPv4 and IPv6. Nodes that do not support it may discard IPv6 announcements.
 - `port`: the port on which the node is accepting incoming connections.
 - `alias` (optional): a hex encoded UTF-8 string that may be displayed as an alternative to the node's ID. Notice that aliases are not unique and may be freely chosen by the node operators. The alias is limited to 32 bytes, i.e., 64 bytes in hex encoded format.

In addition the node's ID is included in the common format and is used to uniquely identify the node.
Notice that an announcement does not guarantee that the node is actually reachable, e.g., because it is firewalled or on an unroutable network. If a node is was configured not to accept incoming connections or knows that it is unreachable it MAY omit node announcements.

### `CHAN` message

The channel message is used to announce the existence of a channel between two peers in the overlay. The `CHAN` message has the following arguments:

 - `remote_id`: the ID of the remote end of the channel from the point of view of the announcing node.
 - `txid`: the hash of the transaction that funded the channel, i.e., the transaction that created the multisig output this channel is based on.
 - `blockheight`: the block height at which the transaction was first confirmed. The block MUST contain the transaction.
 - `txindex`: the index of the transaction in the above block.
 - `base_fee`: the fixed base fee the node is charging in order to forward payments. This is an absolute amount in millisatoshi.
 - `proportional_fee`: a fee expressed in millisatoshi/satoshi, i.e., a fee that is multiplied by the amount of satoshis transferred and removed from the amount being forwarded.
 - `min_expiry`: the minimum number of blocks this node requires to be added to the expiry of HTLCs. This is a security parameter determined by the node operator.
 
Notice that the `local_id` of the announcing node is already known from the common message format, and was used to verify the authenticity of the message, so it is not present in the arguments.
Channel removal MAY be signaled by setting `blockheight` to 0, otherwise node's MAY expire channels that were not announced for more than 6 hours.

## Processing Announcements

Upon receiving a message a node MUST split the message into signature and body by separating at the first space character.
Any leading or trailing whitespace characters are dropped from the body.
The node then extracts the public key, by searching for the second and third space character in the message.
The node MUST verify that the signature is a valid signature for the body with the public key.
If the signature is invalid the message is dropped and processing ends.

After verifying the signature, the node splits the body into message type, public key and arguments and continues processing depending on the message type. The announcements are used to populate the node's local view of the topology, inserting new channels, and updating existing ones with new parameters.

## Examples

Example of a node announcement without node alias:

~~~
304402202f2b013b51071fe2c066a50d423144a6141cfa91cb0fe2e5b39ed79c9837e596022006b76502a259010b9469a66eabae4190df370bcdbeb6b67aee65680e10dde165 NODE 02ff462faea57d3cf9506193d9c0eb2b1b15bad489bb9e196672bdc5a10a275ab9 2a02:aa16:1105:4a80:2df5:2764:457c:288 6332
~~~

Example of a node announcement with a node alias `Lightning`:

~~~
304402202f2b013b51071fe2c066a50d423144a6141cfa91cb0fe2e5b39ed79c9837e596022006b76502a259010b9469a66eabae4190df370bcdbeb6b67aee65680e10dde165 NODE 02ff462faea57d3cf9506193d9c0eb2b1b15bad489bb9e196672bdc5a10a275ab9 2a02:aa16:1105:4a80:2df5:2764:457c:288 6332 4c696768746e696e67
~~~

Example of a channel announcement:

~~~
3045022100a9caa1fd52bfa9343a2d9d10bae2b825d30bae3895ddeb74cf1161e6c8fedf2702205bc824f8ad0937c6b3a2d6aa9907777be73fb278c8b572911a8561b6da5868f4 CHAN 02915506c736ffec49ad58fc021779600dcd2b7a52ac97690571aea5b4d9be2706 0210c15e84c69bd89fc27cb6d7620a65d2f76a6911f879a2adf13ee479ddcd873c 04c67e8d2d1ac11b17ccf68514de14f62ea16aaaf1fdc47a25b732eae4e28084 1012032 0 1 10 6
~~~
