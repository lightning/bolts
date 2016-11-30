# BOLT #1: Message Format, Encryption, Authentication and Initialization

## Communication Protocols

This protocol is written with TCP in mind, but could use any ordered,
reliable transport.

The default TCP port is `9735`.  This corresponds to hexadecimal `2607`,
the unicode code point for LIGHTNING.<sup>[2](#reference-2)</sup>

All data fields are big-endian unless otherwise specified.

## Future Directions

"Ping" or "noop" messages could be appended to the same output
to max traffic analysis even more difficult.

In order to allow zero-RTT encrypted+authenticated communication, a Noise Pipes
protocol can be adopted which composes two handshakes, potentially falling back
to a full handshake if static public keys have changed.

## Lightning Message Format

After decryption, all lightning messages are of the form:

1. `2-byte` big-endian type.
3. Data bytes as specified by the total packet length.

The maximum size of these messages is `65535-bytes`, so the largest
message data possible is 65533 bytes.  If larger messages are needed
in future, a fragmentation method will be defined.

### Requirements

A node MUST NOT send a message with more than `65533` data
bytes.  A node MUST NOT send an evenly-typed message not listed here
without prior negotiation.

A node MUST ignore a received message of unknown type, if that type is
odd.  A node MUST fail the channels if it receives a message of unknown
type, if that type is even.

A node MUST ignore any additional data within a message, beyond the
length it expects for that type.

A node MUST fail the channels if it receives a known message with
insufficient length for the contents.

### Rationale

The standard endian of `SHA2` and the encoding of bitcoin public keys
are big endian, thus it would be unusual to use a different endian for
other fields.

Length is limited to 65535 bytes by the cryptographic wrapping, and
messages in the protocol are never more than that length anyway.

The "it's OK to be odd" rule allows for future optional extensions
without negotiation or special coding in clients.  The "ignore
additional data" rule similarly allows for future expansion.

Implementations may prefer have message data aligned on an 8-byte
boundary (the largest natural alignment requirement of any type here),
but adding a 6-byte padding after the type field was considered
wasteful: alignment may be achieved by decrypting the message into
a buffer with 6 bytes of pre-padding.

## Initialization Message

Once authentication is complete, the first message reveals the
features supported or required by this node.  Odd features are
optional, even features are compulsory ("it's OK to be odd!").  The
meaning of these bits will be defined in future.

1. type: 16 (`init`)
2. data:
   * [2:gflen]
   * [gflen:globalfeatures]
   * [2:lflen]
   * [lflen:localfeatures]

The 2-byte len fields indicate the number of bytes in the immediately
following field.


### Requirements


The sending node SHOULD use the minimum lengths required to represent
the feature fields.  The sending node MUST set feature bits
corresponding to features it requires the peer to support, and SHOULD
set feature bits corresponding to features it optionally supports.


The receiving node MUST fail the channels if it receives a
`globalfeatures` or `localfeatures` with an even bit set which it does
not understand.


Each node MUST wait to receive `init` before sending any other
messages.


### Rationale


The even/odd semantic allows future incompatible changes, or backward
compatible changes.  Bits should generally be assigned in pairs, so
that optional features can later become compulsory.

Nodes wait for receipt of the other's features to simplify error
diagnosis where features are incompatible.

The feature masks are split into local features which only affect the
protocol between these two nodes, and global features which can affect
HTLCs and thus are also advertised to other nodes.

## Error Message


For simplicity of diagnosis, it is often useful to tell the peer that
something is incorrect.


1. type: 17 (`error`)
2. data:
   * [8:channel-id]
   * [2:len]
   * [len:data]

The 2-byte `len` field indicates the number of bytes in the immediately
following field.


### Requirements


A node SHOULD send `error` for protocol violations or internal
errors which make channels unusable or further communication unusable.
A node MAY send an empty [data] field.  A node sending `error` MUST
fail the channel referred to by the `channel-id`, or if `channel-id`
is 0xFFFFFFFFFFFFFFFF it MUST fail all channels and MUST close the connection.
A node MUST NOT set `len` to greater than the data length.


A node receiving `error` MUST fail the channel referred to by
`channel-id`, or if `channel-id` is 0xFFFFFFFFFFFFFFFF it MUST fail
all channels and MUST close the connection.  A receiving node MUST truncate
`len` to the remainder of the packet if it is larger.


A receiving node SHOULD only print out `data` verbatim if it is a
valid string.


### Rationale


There are unrecoverable errors which require an abort of conversations;
if the connection is simply dropped then the peer may retry the
connection.  It's also useful to describe protocol violations for
diagnosis, as it indicates that one peer has a bug.


It may be wise not to distinguish errors in production settings, lest
it leak information, thus the optional data field.

## Acknowledgements

TODO(roasbeef); fin


# References
1. <a id="reference-1">https://en.bitcoin.it/wiki/Secp256k1</a>
2. <a id="reference-2">http://www.unicode.org/charts/PDF/U2600.pdf</a>

# Authors

FIXME

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
