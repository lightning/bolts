# BOLT #1: Base Protocol

## Overview
This protocol assumes an underlying authenticated and ordered transport mechanism that takes care of framing individual messages.
[BOLT #8](08-transport.md) specifies the canonical transport layer used in Lightning, though it can be replaced by any transport that fulfills the above guarantees.

The default TCP port is 9735. This corresponds to hexadecimal `0x2607`, the Unicode code point for LIGHTNING.<sup>[1](#reference-1)</sup>

All data fields are big-endian unless otherwise specified.

## Table of Contents
  * [Connection handling and multiplexing](#connection-handling-and-multiplexing)
  * [Lightning Message Format](#lightning-message-format)
  * [Setup Messages](#setup-messages)
    * [The `init` message](#the-init-message)
    * [The `error` message](#the-error-message)
  * [Control Messages](#control-messages)
    * [The `ping` and `pong` messages](#the-ping-and-pong-messages)
  * [Acknowledgments](#acknowledgments)
  * [References](#references)
  * [Authors](#authors)

## Connection handling and multiplexing

Implementations MUST use one connection per peer, channel messages (which include a channel id) being multiplexed over this single connection.


## Lightning Message Format

After decryption, all lightning messages are of the form:

1. `type`: 2 byte big-endian field indicating the type of the message.
2. `payload`: variable length payload. It comprises the remainder of
   the message and conforms to the format matching the `type`.

The `type` field indicates how to interpret the `payload` field.
The format for each individual type is specified in a specification in this repository.
The type follows the _it's ok to be odd_ rule, so nodes MAY send odd-numbered types without ascertaining that the recipient understands it. 
A node MUST NOT send an evenly-typed message not listed here without prior negotiation.
A node MUST ignore a received message of unknown type, if that type is odd.
A node MUST fail the channels if it receives a message of unknown type, if that type is even.

The messages are grouped logically into 4 groups by their most significant set bit:

 - Setup & Control (types `0`-`31`): messages related to connection setup, control, supported features, and error reporting. These are described below.
 - Channel (types `32`-`127`): comprises messages used to setup and tear down micropayment channels. These are described in [BOLT #2](02-peer-protocol.md).
 - Commitment (types `128`-`255`): comprises messages related to updating the current commitment transaction, which includes adding, revoking, and settling HTLCs, as well as updating fees and exchanging signatures. These are described in [BOLT #2](02-peer-protocol.md).
 - Routing (types `256`-`511`): node and channel announcements, as well as any active route exploration. These are described in [BOLT #7](07-routing-gossip.md).

The size of the message is required to fit into a 2 byte unsigned int by the transport layer, therefore the maximum possible size is 65535 bytes.
A node MUST ignore any additional data within a message, beyond the length it expects for that type.
A node MUST fail the channels if it receives a known message with insufficient length for the contents.

### Rationale

The standard endian of `SHA2` and the encoding of Bitcoin public keys
are big endian, thus it would be unusual to use a different endian for
other fields.

Length is limited to 65535 bytes by the cryptographic wrapping, and
messages in the protocol are never more than that length anyway.

The "it's OK to be odd" rule allows for future optional extensions
without negotiation or special coding in clients.  The "ignore
additional data" rule similarly allows for future expansion.

Implementations may prefer to have message data aligned on an 8 byte
boundary (the largest natural alignment requirement of any type here),
but adding a 6 byte padding after the type field was considered
wasteful: alignment may be achieved by decrypting the message into
a buffer with 6 bytes of pre-padding.

## Setup Messages

### The `init` message

Once authentication is complete, the first message reveals the features supported or required by this node, even if this is a reconnection.

[BOLT #9](09-features.md) specifies lists of global and local features. Each feature is represented in `globalfeatures` or `localfeatures` by 2 bits: first one indicates is it feature mandatory (`0b1`) or not(`0b0`), and second one indicates is it feature supported or not. Odd features are optional, even features are compulsory (_it's OK to be odd_).
`globalfeatures` and `localfeatures` fields should be padded to ceil number of bytes.

1. type: 16 (`init`)
2. data:
   * [`2`:`gflen`]
   * [`gflen`:`globalfeatures`]
   * [`2`:`lflen`]
   * [`lflen`:`localfeatures`]

The 2 byte `gflen` and `lflen` fields indicate the number of bytes in the immediately following field.

#### Requirements

The sending node MUST send `init` as the first lightning message for any
connection.
The sending node SHOULD use the minimum lengths required to represent
the feature fields.  The sending node MUST set feature bits
corresponding to features it requires the peer to support, and SHOULD
set feature bits corresponding to features it optionally supports.

The receiving node MUST fail the channels if it receives a
`globalfeatures` or `localfeatures` with an even bit set which it does
not understand.

Each node MUST wait to receive `init` before sending any other messages.

#### Rationale

The even/odd semantic allows future incompatible changes, or backward
compatible changes.  Bits should generally be assigned in pairs, so
that optional features can later become compulsory.

Nodes wait for receipt of the other's features to simplify error
diagnosis where features are incompatible.

The feature masks are split into local features which only affect the
protocol between these two nodes, and global features which can affect
HTLCs and thus are also advertised to other nodes.

### The `error` message

For simplicity of diagnosis, it is often useful to tell the peer that something is incorrect.

1. type: 17 (`error`)
2. data:
   * [`32`:`channel_id`]
   * [`2`:`len`]
   * [`len`:`data`]

The 2-byte `len` field indicates the number of bytes in the immediately following field.

#### Requirements

The channel is referred to by `channel_id` unless `channel_id` is zero (ie. all bytes zero), in which case it refers to all channels.

The funding node MUST use `temporary_channel_id` in lieu of `channel_id` for all error messages sent before (and including) the `funding_created` message. The fundee node MUST use `temporary_channel_id` in lieu of `channel_id` for all error messages sent before (and not including) the `funding_signed` message.

A node SHOULD send `error` for protocol violations or internal
errors which make channels unusable or further communication unusable.
A node MAY send an empty `data` field.  A node sending `error` MUST
fail the channel referred to by the error message, or if `channel_id` is zero, it MUST
fail all channels and MUST close the connection.
A node MUST set `len` equal to the length of `data`.  A node SHOULD include the raw, hex-encoded transaction in reply to a `funding_created`, `funding_signed`, `closing_signed` or `commitment_signed` message when failure was caused by an invalid signature check.

A node receiving `error` MUST fail the channel referred to by the message,
or if `channel_id` is zero, it MUST fail all channels and MUST close the connection.  If no existing channel is referred to by the message, the receiver MUST ignore the message. A receiving node MUST truncate
`len` to the remainder of the packet if it is larger.

A receiving node SHOULD only print out `data` verbatim if the string is composed solely of printable ASCII characters.
For reference, the printable character set includes byte values 32 through 127 inclusive.

#### Rationale

There are unrecoverable errors which require an abort of conversations;
if the connection is simply dropped then the peer may retry the
connection.  It's also useful to describe protocol violations for
diagnosis, as it indicates that one peer has a bug.

It may be wise not to distinguish errors in production settings, lest
it leak information, thus the optional `data` field.

## Control Messages

### The `ping` and `pong` messages

In order to allow for the existence of very long-lived TCP connections, at
times it may be required that both ends keep alive the TCP connection at the
application level.  Such messages also allow obfuscation of traffic patterns.

1. type: 18 (`ping`)
2. data: 
    * [`2`:`num_pong_bytes`]
    * [`2`:`byteslen`]
    * [`byteslen`:`ignored`]

The `pong` message is to be sent whenever a `ping` message is received. It
serves as a reply, and also serves to keep the connection alive while
explicitly notifying the other end that the receiver is still active. Within
the received `ping` message, the sender will specify the number of bytes to be
included within the data payload of the `pong` message

1. type: 19 (`pong`)
2. data:
    * [`2`:`byteslen`]
    * [`byteslen`:`ignored`]

#### Requirements

A node sending `pong` or `ping` SHOULD set `ignored` to zeroes, but MUST NOT
set `ignored` to sensitive data such as secrets, or portions of initialized
memory.

A node SHOULD NOT send `ping` messages more often than once every 30 seconds,
and MAY terminate the network connection if it does not receive a corresponding
`pong`: it MUST NOT fail the channels in this case.

A node receiving a `ping` message SHOULD fail the channels if it has received
significantly in excess of one `ping` per 30 seconds, otherwise if
`num_pong_bytes` is less than 65532 it MUST respond by sending a `pong` message
with `byteslen` equal to `num_pong_bytes`, otherwise it MUST ignore the `ping`.

A node receiving a `pong` message MAY fail the channels if `byteslen` does not
correspond to any `ping` `num_pong_bytes` value it has sent.

### Rationale

The largest possible message is 65535 bytes, thus maximum sensible `byteslen`
is 65531 to account for the type field (`pong`) and `byteslen` itself.  This
gives us a convenient cutoff for `num_pong_bytes` to indicate that no reply
should be sent.

Connections between nodes within the network may be very long lived as payment
channels have an indefinite lifetime. However, it's likely that for a
significant portion of the life-time of a connection, no new data will be
exchanged. Additionally, on several platforms it's possible that Lightning
clients will be put to sleep without prior warning.  As a result, we use a
distinct ping message in order to probe for the liveness of the connection on
the other side, and also to keep the established connection active. 

Additionally, the ability for a sender to request that the receiver send a
response with a particular number of bytes enables nodes on the network to
create _synthetic_ traffic. Such traffic can be used to partially defend
against packet and timing analysis as nodes can fake the traffic patterns of
typical exchanges, without applying any true updates to their respective
channels. 

When combined with the onion routing protocol defined in
[BOLT #4](https://github.com/lightningnetwork/lightning-rfc/blob/master/04-onion-routing.md),
careful statistically driven synthetic traffic can serve to further bolster the
privacy of participants within the network.

Limited precautions are recommended against `ping` flooding, however some
latitude is given because of network delays.  Note that there are other methods
of incoming traffic flooding (eg. sending odd unknown message types, or padding
every message maximally).

Finally, the usage of periodic `ping` messages serves to promote frequent key
rotations as specified within [BOLT #8](https://github.com/lightningnetwork/lightning-rfc/blob/master/08-transport.md).


## Acknowledgments

TODO(roasbeef); fin


## References
1. <a id="reference-2">http://www.unicode.org/charts/PDF/U2600.pdf</a>

## Authors

FIXME

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
