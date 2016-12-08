# BOLT #1: Base Protocol

## Overview
This protocol assumes an underlying authenticated and ordered transport mechanism that takes care of framing individual messages.
[BOLT #8](08-transport.md) specifies the canonical transport layer used in Lightning, though it can be replaced by any transport that fulfills the above guarantees.

The default TCP port is 9735. This corresponds to hexadecimal `0x2607`, the unicode code point for LIGHTNING.<sup>[2](#reference-2)</sup>

All data fields are big-endian unless otherwise specified.

## Table of Contents
  * [Lightning Message Format](#lightning-message-format)
  * [Setup Messages](#setup-messages)
    * [The `init` message](#the-init-message)
    * [The `error` message](#the-error-message)
  * [Acknowledgements](#acknowledgements)
  * [References](#references)
  * [Authors](#authors)

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

 - Setup & signalling (types `0`-`31`): messages related to supported features and error reporting. These are described below.
 - Channel (types `32`-`127`): comprises messages used to setup and tear down micropayment channels. These are described in [BOLT #2](02-peer-protocol.md).
 - Commitment (types `128`-`255`: comprises messages related to updating the current commitment transaction, which includes adding, revoking, and settling HTLCs, as well as updating fees and exchanging signatures. These are described in [BOLT #2](02-peer-protocol.md).
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

Once authentication is complete, the first message reveals the features supported or required by this node.
Odd features are optional, even features are compulsory (_it's OK to be odd_).
The meaning of these bits will be defined in the future.

1. type: 16 (`init`)
2. data:
   * [2:gflen]
   * [gflen:globalfeatures]
   * [2:lflen]
   * [lflen:localfeatures]

The 2 byte `gflen` and `lflen` fields indicate the number of bytes in the immediately following field.

#### Requirements

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
   * [8:channel-id]
   * [2:len]
   * [len:data]

The 2-byte `len` field indicates the number of bytes in the immediately following field.

#### Requirements

A node SHOULD send `error` for protocol violations or internal
errors which make channels unusable or further communication unusable.
A node MAY send an empty [data] field.  A node sending `error` MUST
fail the channel referred to by the `channel-id`, or if `channel-id`
is `0xFFFFFFFFFFFFFFFF` it MUST fail all channels and MUST close the connection.
A node MUST NOT set `len` to greater than the data length.

A node receiving `error` MUST fail the channel referred to by
`channel-id`, or if `channel-id` is `0xFFFFFFFFFFFFFFFF` it MUST fail
all channels and MUST close the connection.  A receiving node MUST truncate
`len` to the remainder of the packet if it is larger.

A receiving node SHOULD only print out `data` verbatim if it is a
valid string.

#### Rationale

There are unrecoverable errors which require an abort of conversations;
if the connection is simply dropped then the peer may retry the
connection.  It's also useful to describe protocol violations for
diagnosis, as it indicates that one peer has a bug.

It may be wise not to distinguish errors in production settings, lest
it leak information, thus the optional data field.

## Acknowledgements

TODO(roasbeef); fin


## References
1. <a id="reference-1">https://en.bitcoin.it/wiki/Secp256k1</a>
2. <a id="reference-2">http://www.unicode.org/charts/PDF/U2600.pdf</a>

## Authors

FIXME

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
