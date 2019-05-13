# BOLT #4: Onion Routing Protocol

## Overview

This document describes the construction of an onion routed packet that is
used to route a payment from an _origin node_ to a _final node_. The packet
is routed through a number of intermediate nodes, called _hops_.

The routing schema is based on the [Sphinx][sphinx] construction and is
extended with a per-hop payload.

Intermediate nodes forwarding the message can verify the integrity of
the packet and can learn which node they should forward the
packet to. They cannot learn which other nodes, besides their
predecessor or successor, are part of the packet's route; nor can they learn
the length of the route or their position within it. The packet is
obfuscated at each hop, to ensure that a network-level attacker cannot
associate packets belonging to the same route (i.e. packets belonging
to the same route do not share any correlating information). Notice that this
does not preclude the possibility of packet association by an attacker
via traffic analysis.

The route is constructed by the origin node, which knows the public
keys of each intermediate node and of the final node. Knowing each node's public key
allows the origin node to create a shared secret (using ECDH) for each
intermediate node and for the final node. The shared secret is then
used to generate a _pseudo-random stream_ of bytes (which is used to obfuscate
the packet) and a number of _keys_ (which are used to encrypt the payload and
compute the HMACs). The HMACs are then in turn used to ensure the integrity of
the packet at each hop.

Each hop along the route only sees an ephemeral key for the origin node, in
order to hide the sender's identity. The ephemeral key is blinded by each
intermediate hop before forwarding to the next, making the onions unlinkable
along the route.

This specification describes _version 0_ of the packet format and routing
mechanism.

A node:

  - upon receiving a higher version packet than it implements:
    - MUST report a route failure to the origin node.
    - MUST discard the packet.

# Table of Contents

  * [Conventions](#conventions)
  * [Key Generation](#key-generation)
  * [Pseudo Random Byte Stream](#pseudo-random-byte-stream)
  * [Packet Structure](#packet-structure)
    * [Payload for the Last Node](#payload-for-the-last-node)
  * [Shared Secret](#shared-secret)
  * [Blinding Ephemeral Keys](#blinding-ephemeral-keys)
  * [Packet Construction](#packet-construction)
  * [Packet Forwarding](#packet-forwarding)
  * [Filler Generation](#filler-generation)
  * [Returning Errors](#returning-errors)
    * [Failure Messages](#failure-messages)
    * [Receiving Failure Codes](#receiving-failure-codes)
  * [Test Vector](#test-vector)
    * [Packet Creation](#packet-creation)
      * [Parameters](#parameters)
      * [Per-Hop Information](#per-hop-information)
      * [Per-Packet Information](#per-packet-information)
      * [Wrapping the Onion](#wrapping-the-onion)
      * [Final Packet](#final-packet)
    * [Returning Errors](#returning-errors)
  * [References](#references)
  * [Authors](#authors)

# Conventions

There are a number of conventions adhered to throughout this document:

 - HMAC: the integrity verification of the packet is based on Keyed-Hash
   Message Authentication Code, as defined by the [FIPS 198
   Standard][fips198]/[RFC 2104][RFC2104], and using a `SHA256` hashing
   algorithm.
 - Elliptic curve: for all computations involving elliptic curves, the Bitcoin
   curve is used, as specified in [`secp256k1`][sec2]
 - Pseudo-random stream: [`ChaCha20`][rfc7539] is used to generate a
   pseudo-random byte stream. For its generation, a fixed null-nonce
   (`0x0000000000000000`) is used, along with a key derived from a shared
   secret and with a `0x00`-byte stream of the desired output size as the
   message.
 - The terms _origin node_ and _final node_ refer to the initial packet sender
   and the final packet recipient, respectively.
 - The terms _hop_ and _node_ are sometimes used interchangeably, but a _hop_
   usually refers to an intermediate node in the route rather than an end node.
 - The term _processing node_ refers to the specific node along the route that is
   currently processing the forwarded packet.
 - The term _peers_ refers only to hops that are direct neighbors (in the
   overlay network): more specifically, _sending peers_ forward packets
   to_receiving peers_.
 - Route length: the maximum route length is limited to 20 hops.
 - The longest route supported has 20 hops without counting the _origin node_
   and _final node_, thus 19 _intermediate nodes_ and a maximum of 20 channels
   to be traversed.
 - Each hop in the route has a `hop_payload` composed of one or more
   _`frames`_, each having `FRAME_SIZE` bytes of size. `FRAME_SIZE` is 65
   bytes.


# Key Generation

A number of encryption and verification keys are derived from the shared secret:

 - _rho_: used as key when generating the pseudo-random byte stream that is used
   to obfuscate the per-hop information
 - _mu_: used during the HMAC generation
 - _um_: used during error reporting

The key generation function takes a key-type (_rho_=`0x72686F`, _mu_=`0x6d75`,
or _um_=`0x756d`) and a 32-byte secret as inputs and returns a 32-byte key.

Keys are generated by computing an HMAC (with `SHA256` as hashing algorithm)
using the appropriate key-type (i.e. _rho_, _mu_, or _um_) as HMAC-key and the
32-byte shared secret as the message. The resulting HMAC is then returned as the
key.

Notice that the key-type does not include a C-style `0x00`-termination-byte,
e.g. the length of the _rho_ key-type is 3 bytes, not 4.

# Pseudo Random Byte Stream

The pseudo-random byte stream is used to obfuscate the packet at each hop of the
path, so that each hop may only recover the address and HMAC of the next hop.
The pseudo-random byte stream is generated by encrypting (using `ChaCha20`) a
`0x00`-byte stream, of the required length, which is initialized with a key
derived from the shared secret and a zero-nonce (`0x00000000000000`).

The use of a fixed nonce is safe, since the keys are never reused.

# Packet Structure

The packet consists of four sections:

 - a `version` byte
 - a 33-byte compressed `secp256k1` `public_key`, used during the shared secret
   generation
 - a 1300-byte `hops_data` consisting of twenty fixed-size `frame`s
   - One or more consecutive `frame`s constitute a `hop_payload` containing
     information to be used by the processing node during message forwarding
 - a 32-byte `HMAC`, used to verify the packet's integrity

The network format of the packet consists of the individual sections
serialized into one contiguous byte-stream and then transferred to the packet
recipient. Due to the fixed size of the packet, it need not be prefixed by its
length when transferred over a connection.

The overall structure of the packet is as follows:

1. type: `onion_packet`
2. data:
   * [`1`:`version`]
   * [`33`:`public_key`]
   * [`20*FRAME_SIZE`:`hops_data`]
   * [`32`:`hmac`]

For this specification (_version 0_), `version` has a constant value of `0x00`.

The `hops_data` field is list of `hop_payload`s.
A `hop_payload` is a structure that holds obfuscations of the next hop's address, transfer information, and its associated HMAC.
Each `hop_payload` consists of one of more `frame`s to hold the information that the hop should receive.
The total number of `frame`s used by all `hop_payload`s MUST NOT exceed 20, but MAY be less than that, in which case the remaining frames are padded to reach the full 1300 byte length for the `hops_data`.

The `hops_data` has the following structure (`n1` and `n2` being the number of frames used by hops `1` and `2` respectively):

1. type: `hops_data`
2. data:
   * [`n1*FRAME_SIZE`: `hop_payload`]
   * [`n2*FRAME_SIZE`: `hop_payload`]
   * ...
   * `filler`

Where `filler` consists of obfuscated, deterministically-generated padding, as detailed in [Filler Generation](#filler-generation).
Additionally, `hop_payload`s are incrementally obfuscated at each hop.

Each `hop_payload` has the following structure:

1. type: `hop_payload`
2. data:
   * [`1`: `num_frames_and_realm`]
   * [`raw_payload_len`: `raw_payload`]
   * [`padding_len`: `padding`]
   * [`32`: `HMAC`]

Notice that since the `hop_payload` is instantiated once per hop, the subscript `_i` may be used in the remainder of this document to refer to the `hop_payload` and its fields destined for hop `i`.

The `hop_payload` consists of at least one `frame` followed by up to 19 additional `frame`s.
The number of additional frames allocated to the current hop is determined by the 5 most significant bits of `num_frames_and_realm`, while the 3 least significant bits determine the payload format.
Therefore the number of frames allocated to the current hop is given by `num_frames = (num_frames_and_realm >> 3) + 1`.
For simplification we will use `hop_payload_len` to refer to `num_frames * FRAME_SIZE`.

In order to have sufficient space to serialized the `raw_payload` into the `hop_payload` while minimizing the number of used frames the number of frames used for a single `hop_payload` MUST be equal to

> `num_frames = ceil((raw_payload_len + 1 + 32) / FRAME_SIZE)`

The payload format determines how the `raw_payload` should be interpreted (see below for currently defined formats), and how much padding is added.
In order to position the `HMAC` in the last 32 bytes of the `hop` the `raw_payload` MUST be followed by `padding_len = (num_frames * FRAME_SIZE - 1 - raw_payload_len - 32)` `0x00`-bytes.

The `realm` is specified as `num_frames_and_realm & 0x07`.
It determines the format of the `raw_payload` field; the following `realm`s are currently defined.

| `realm` | Payload Format                                             |
|:--------|:-----------------------------------------------------------|
| `0x00`  | [Version 1 `hop_data`](#version-1-hop_data-payload-format) |
| `0x01`  | TLV payload format (to be specified)                       |

Using the `hop_payload` field, the origin node is able to precisely specify the path and structure of the HTLCs forwarded at each hop.
As the `hop_payload` is protected under the packet-wide HMAC, the information it contains is fully authenticated with each pair-wise relationship between the HTLC sender (origin node) and each hop in the path.

Using this end-to-end authentication, each hop is able to cross-check the HTLC parameters with the `hop_payload`'s specified values and to ensure that the sending peer hasn't forwarded an ill-crafted HTLC.

## Version 1 `hop_data` Payload Format

The version 1 `hop_data` payload format has realm `0x00`, and MUST use a single `frame` to encode the payload.

1. type: `per_hop`
2. data:
   * [`8`:`short_channel_id`]
   * [`8`:`amt_to_forward`]
   * [`4`:`outgoing_cltv_value`]
   * [`12`:`padding`]

Field descriptions:

   * `short_channel_id`: The ID of the outgoing channel used to route the 
      message; the receiving peer should operate the other end of this channel.

   * `amt_to_forward`: The amount, in millisatoshis, to forward to the next
     receiving peer specified within the routing information.

     This value amount MUST include the origin node's computed _fee_ for the
     receiving peer. When processing an incoming Sphinx packet and the HTLC
     message that it is encapsulated within, if the following inequality doesn't hold,
     then the HTLC should be rejected as it would indicate that a prior hop has
     deviated from the specified parameters:

        incoming_htlc_amt - fee >= amt_to_forward

     Where `fee` is either calculated according to the receiving peer's advertised fee
     schema (as described in [BOLT #7](07-routing-gossip.md#htlc-fees))
     or is 0, if the processing node is the final node.

   * `outgoing_cltv_value`: The CLTV value that the _outgoing_ HTLC carrying
     the packet should have.

        cltv_expiry - cltv_expiry_delta >= outgoing_cltv_value

     Inclusion of this field allows a hop to both authenticate the information
     specified by the origin node, and the parameters of the HTLC forwarded,
	 and ensure the origin node is using the current `cltv_expiry_delta` value.
     If there is no next hop, `cltv_expiry_delta` is 0.
     If the values don't correspond, then the HTLC should be failed and rejected, as
     this indicates that either a forwarding node has tampered with the intended HTLC
     values or that the origin node has an obsolete `cltv_expiry_delta` value.
     The hop MUST be consistent in responding to an unexpected
     `outgoing_cltv_value`, whether it is the final node or not, to avoid
     leaking its position in the route.

   * `padding`: This field is for future use and also for ensuring that future non-0-`realm`
     `per_hop`s won't change the overall `hops_data` size.

When forwarding HTLCs, nodes MUST construct the outgoing HTLC as specified within
`per_hop` above; otherwise, deviation from the specified HTLC parameters
may lead to extraneous routing failure.

# Accepting and Forwarding a Payment

Once a node has decoded the payload it either accepts the payment locally, or forwards it to the peer indicated as the next hop in the payload.

## Non-strict Forwarding

A node MAY forward an HTLC along an outgoing channel other than the one
specified by `short_channel_id`, so long as the receiver has the same node
public key intended by `short_channel_id`. Thus, if `short_channel_id` connects
nodes A and B, the HTLC can forwarded across any channel connecting A and B.
Failure to adhere will result in the receiver being unable to decrypt the next
hop in the onion packet.

### Rationale

In the event that two peers have multiple channels, the downstream node will be
able to decrypt the next hop payload regardless of which channel the packet is
sent across.

Nodes implementing non-strict forwarding are able to make real-time assessments
of channel bandwidths with a particular peer, and use the channel that is
locally-optimal. 

For example, if the channel specified by `short_channel_id` connecting A and B
does not have enough bandwidth at forwarding time, then A is able use a
different channel that does. This can reduce payment latency by preventing the
HTLC from failing due to bandwidth constraints across `short_channel_id`, only
to have the sender attempt the same route differing only in the channel between
A and B.

Non-strict forwarding allows nodes to make use of private channels connecting
them to the receiving node, even if the channel is not known in the public
channel graph.

### Recommendation

Implementations using non-strict forwarding should consider applying the same
fee schedule to all channels with the same peer, as senders are likely to select
the channel which results in the lowest overall cost. Having distinct policies
may result in the forwarding node accepting fees based on the most optimal fee
schedule for the sender, even though they are providing aggregate bandwidth
across all channels with the same peer.

Alternatively, implementations may choose to apply non-strict forwarding only to
like-policy channels to ensure their expected fee revenue does not deviate by
using an alternate channel.

## Payload for the Last Node

When building the route, the origin node MUST use a payload for
the final node with the following values:
* `outgoing_cltv_value`: set to the final expiry specified by the recipient
* `amt_to_forward`: set to the final amount specified by the recipient

This allows the final node to check these values and return errors if needed,
but it also eliminates the possibility of probing attacks by the second-to-last
node. Such attacks could, otherwise, attempt to discover if the receiving peer is the
last one by re-sending HTLCs with different amounts/expiries.
The final node will extract its onion payload from the HTLC it has received and
compare its values against those of the HTLC. See the
[Returning Errors](#returning-errors) section below for more details.

If not for the above, since it need not forward payments, the final node could
simply discard its payload.

# Shared Secret

The origin node establishes a shared secret with each hop along the route using
Elliptic-curve Diffie-Hellman between the sender's ephemeral key at that hop and
the hop's node ID key. The resulting curve point is serialized to the
DER-compressed representation and hashed using `SHA256`. The hash output is used
as the 32-byte shared secret.

Elliptic-curve Diffie-Hellman (ECDH) is an operation on an EC private key and
an EC public key that outputs a curve point. For this protocol, the ECDH
variant implemented in `libsecp256k1` is used, which is defined over the
`secp256k1` elliptic curve. During packet construction, the sender uses the
ephemeral private key and the hop's public key as inputs to ECDH, whereas
during packet forwarding, the hop uses the ephemeral public key and its own
node ID private key. Because of the properties of ECDH, they will both derive
the same value.

# Blinding Ephemeral Keys

In order to ensure multiple hops along the route cannot be linked by the
ephemeral public keys they see, the key is blinded at each hop. The blinding is
done in a deterministic way that the allows the sender to compute the
corresponding blinded private keys during packet construction.

The blinding of an EC public key is a single scalar multiplication of
the EC point representing the public key with a 32-byte blinding factor. Due to
the commutative property of scalar multiplication, the blinded private key is
the multiplicative product of the input's corresponding private key with the
same blinding factor.

The blinding factor itself is computed as a function of the ephemeral public key
and the 32-byte shared secret. Concretely, is the `SHA256` hash value of the
concatenation of the public key serialized in its compressed format and the
shared secret.

# Packet Construction

In the following example, it's assumed that a _sending node_ (origin node),
`n_0`, wants to route a packet to a _receiving node_ (final node), `n_r`.
First, the sender computes a route `{n_0, n_1, ..., n_{r-1}, n_r}`, where `n_0`
is the sender itself and `n_r` is the final recipient. All nodes `n_i` and
`n_{i+1}` MUST be peers in the overlay network route. The sender then gathers the
public keys for `n_1` to `n_r` and generates a random 32-byte `sessionkey`.
Optionally, the sender may pass in _associated data_, i.e. data that the
packet commits to but that is not included in the packet itself. Associated
data will be included in the HMACs and must match the associated data provided
during integrity verification at each hop.

To construct the onion, the sender initializes the ephemeral private key for the
first hop `ek_1` to the `sessionkey` and derives from it the corresponding
ephemeral public key `epk_1` by multiplying with the `secp256k1` base point. For
each of the `k` hops along the route, the sender then iteratively computes the
shared secret `ss_k` and ephemeral key for the next hop `ek_{k+1}` as follows:

 - The sender executes ECDH with the hop's public key and the ephemeral private
 key to obtain a curve point, which is hashed using `SHA256` to produce the
 shared secret `ss_k`.
 - The blinding factor is the `SHA256` hash of the concatenation between the
 ephemeral public key `epk_k` and the shared secret `ss_k`.
 - The ephemeral private key for the next hop `ek_{k+1}` is computed by
 multiplying the current ephemeral private key `ek_k` by the blinding factor.
 - The ephemeral public key for the next hop `epk_{k+1}` is derived from the
 ephemeral private key `ek_{k+1}` by multiplying with the base point.

Once the sender has all the required information above, it can construct the
packet.
Constructing a packet routed over `r` hops requires `r` 32-byte ephemeral public keys, `r` 32-byte shared secrets, `r` 32-byte blinding factors, and `r` `hop_payload` payloads (each of size `hop_payload_len_i` bytes).
The construction returns a single 1366-byte packet along with the first receiving peer's address.

The packet construction is performed in the reverse order of the route, i.e.
the last hop's operations are applied first.

The packet is initialized with 1366 `0x00`-bytes.

For each hop in the route, in reverse order, the sender applies the
following operations:

 - The _rho_-key and _mu_-key are generated using the hop's shared secret.
 - The `hops_data` field is right-shifted by `hop_payload_len` bytes, discarding the last `hop_payload_len` bytes that exceed its 1300-byte size.
 - The payload for the hop is serialized into that hop's `raw_payload`, using the desired format, and the `num_frames_and_realm` is set accordingly.
 - The `num_frames_and_realm`, `raw_payload`, `padding` and `HMAC` are copied into the first `hop_payload_len` bytes of the `hops_data`, i.e., the bytes that were just shifted in.
 - The _rho_-key is used to generate 1300 bytes of pseudo-random byte stream which is then applied, with `XOR`, to the `hops_data` field.
 - If this is the last hop, i.e. the first iteration, then the tail of the `hops_data` field is overwritten with the routing information `filler` (see [Filler Generation](#filler-generation)).
 - The next HMAC is computed (with the _mu_-key as HMAC-key) over the concatenated `hops_data` and associated data.

The resulting final HMAC value is the HMAC that will be used by the next hop in the route.

The packet generation returns a serialized packet that contains the `version`
byte, the ephemeral pubkey for the first hop, the HMAC for the first hop, and
the obfuscated `hops_data`.

The following Go code is an example implementation of the packet construction:

```Go
// NewOnionPacket creates a new onion packet which is capable of
// obliviously routing a message through the mix-net path outline by
// 'paymentPath'.
func NewOnionPacket(path *PaymentPath, sessionKey *btcec.PrivateKey, assocData []byte) (*OnionPacket, error) {

	nodeKeys := path.NodeKeys()
	numHops := len(nodeKeys)
	hopSharedSecrets := generateSharedSecrets(nodeKeys, sessionKey)

	// Generate the padding, called "filler strings" in the paper.
	filler := generateFiller("rho", path, hopSharedSecrets)
	// Allocate zero'd out byte slices to store the final mix header packet
	// and the hmac for each hop.
	var (
		mixHeader  [routingInfoSize]byte
		nextHmac   [hmacSize]byte
		hopDataBuf bytes.Buffer
	)

	// Now we compute the routing information for each hop, along with a
	// MAC of the routing info using the shared key for that hop.
	for i := numHops - 1; i >= 0; i-- {
		// We'll derive the two keys we need for each hop in order to:
		// generate our stream cipher bytes for the mixHeader, and
		// calculate the MAC over the entire constructed packet.
		rhoKey := generateKey("rho", &hopSharedSecrets[i])
		muKey := generateKey("mu", &hopSharedSecrets[i])

		// The HMAC for the final hop is simply zeroes. This allows the
		// last hop to recognize that it is the destination for a
		// particular payment.
		path[i].HopPayload.HMAC = nextHmac

		// Next, using the key dedicated for our stream cipher, we'll
		// generate enough bytes to obfuscate this layer of the onion
		// packet.
		streamBytes := generateCipherStream(rhoKey, routingInfoSize)

		// Before we assemble the packet, we'll shift the current
		// mix-header to the right in order to make room for this next
		// per-hop data.
		rightShift(mixHeader[:], path[i].HopPayload.CountFrames()*frameSize)

		// With the mix header right-shifted, we'll encode the current
		// hop data into a buffer we'll re-use during the packet
		// construction.
		if err := path[i].HopPayload.Encode(&hopDataBuf); err != nil {
			return nil, err
		}

		copy(mixHeader[:], hopDataBuf.Bytes())

		// Once the packet for this hop has been assembled, we'll
		// re-encrypt the packet by XOR'ing with a stream of bytes
		// generated using our shared secret.
		xor(mixHeader[:], mixHeader[:], streamBytes[:])

		// If this is the "last" hop, then we'll override the tail of
		// the hop data.
		if i == numHops-1 {
			copy(mixHeader[len(mixHeader)-len(filler):], filler)
		}

		// The packet for this hop consists of: mixHeader. When
		// calculating the MAC, we'll also include the optional
		// associated data which can allow higher level applications to
		// prevent replay attacks.
		packet := append(mixHeader[:], assocData...)
		nextHmac = calcMac(muKey, packet)

		hopDataBuf.Reset()
	}

	return &OnionPacket{
		Version:      baseVersion,
		EphemeralKey: sessionKey.PubKey(),
		RoutingInfo:  mixHeader,
		HeaderMAC:    nextHmac,
	}, nil
}
```

# Packet Forwarding

This specification is limited to `version` `0` packets; the structure of future versions may change.

Upon receiving a packet, a processing node compares the version byte of the
packet with its own supported versions and aborts the connection if the packet
specifies a version number that it doesn't support.
For packets with supported version numbers, the processing node first parses the
packet into its individual fields.

Next, the processing node computes the shared secret using the private key
corresponding to its own public key and the ephemeral key from the packet, as
described in [Shared Secret](#shared-secret).

The above requirements prevent any hop along the route from retrying a payment
multiple times, in an attempt to track a payment's progress via traffic
analysis. Note that disabling such probing could be accomplished using a log of
previous shared secrets or HMACs, which could be forgotten once the HTLC would
not be accepted anyway (i.e. after `outgoing_cltv_value` has passed). Such a log
may use a probabilistic data structure, but it MUST rate-limit commitments as
necessary, in order to constrain the worst-case storage requirements or false
positives of this log.

Next, the processing node uses the shared secret to compute a _mu_-key, which it
in turn uses to compute the HMAC of the `hops_data`. The resulting HMAC is then
compared against the packet's HMAC.

Comparison of the computed HMAC and the packet's HMAC MUST be time-constant to avoid information leaks.

At this point, the processing node can generate a _rho_-key and a _gamma_-key.

The routing information is then deobfuscated, and the information about the
next hop is extracted.
To do so, the processing node copies the `hops_data` field, appends `20*FRAME_SIZE` `0x00`-bytes,
generates `1300 + 20*FRAME_SIZE` pseudo-random bytes (using the _rho_-key), and applies the result
,using `XOR`, to the copy of the `hops_data`.
The first byte of the `hops_data` corresponds to the `num_frames_and_realm` field in the `hop_payload`, which can be decoded to get the `num_frames` and `realm` fields that indicate how many frames are to be parsed and how the `raw_payload` should be interpreted.
The first `num_frames*FRAME_SIZE` bytes of the `hops_data` are the `hop_payload` field used for the the decoding hop.
The next 1300 bytes are the `hops_data` for the outgoing packet destined for the next hop.

A special `per_hop` `HMAC` value of 32 `0x00`-bytes indicates that the currently processing hop is the intended recipient and that the packet should not be forwarded.

If the HMAC does not indicate route termination, and if the next hop is a peer of the
processing node; then the new packet is assembled. Packet assembly is accomplished
by blinding the ephemeral key with the processing node's public key, along with the
shared secret, and by serializing the `hops_data`.
The resulting packet is then forwarded to the addressed peer.

## Requirements

The processing node:
  - if the ephemeral public key is NOT on the `secp256k1` curve:
    - MUST abort processing the packet.
    - MUST report a route failure to the origin node.
  - if the packet has previously been forwarded or locally redeemed, i.e. the
  packet contains duplicate routing information to a previously received packet:
    - if preimage is known:
      - MAY immediately redeem the HTLC using the preimage.
    - otherwise:
      - MUST abort processing and report a route failure.
  - if the computed HMAC and the packet's HMAC differ:
    - MUST abort processing.
    - MUST report a route failure.
  - if the `realm` is unknown:
    - MUST drop the packet.
    - MUST signal a route failure.
  - MUST address the packet to another peer that is its direct neighbor.
  - if the processing node does not have a peer with the matching address:
    - MUST drop the packet.
    - MUST signal a route failure.


# Filler Generation

Upon receiving a packet, the processing node extracts the information destined
for it from the route information and the per-hop payload.
The extraction is done by deobfuscating and left-shifting the field.
This would make the field shorter at each hop, allowing an attacker to deduce the
route length. For this reason, the field is pre-padded before forwarding.
Since the padding is part of the HMAC, the origin node will have to pre-generate an
identical padding (to that which each hop will generate) in order to compute the
HMACs correctly for each hop.
The filler is also used to pad the field-length, in the case that the selected
route is shorter than the maximum allowed route length of 20.

Before deobfuscating the `hops_data`, the processing node pads it with `20 * FRAME_SIZE`
`0x00`-bytes, such that the total length is `2 * 20 * FRAME_SIZE`.
It then generates the pseudo-random byte stream, of matching length, and applies
it with `XOR` to the `hops_data`.
This deobfuscates the information destined for it, while simultaneously
obfuscating the added `0x00`-bytes at the end.

In order to compute the correct HMAC, the origin node has to pre-generate the
`hops_data` for each hop, including the incrementally obfuscated padding added
by each hop. This incrementally obfuscated padding is referred to as the
`filler`.

The following example code shows how the filler is generated in Go:

```Go
func generateFiller(key string, path *PaymentPath, sharedSecrets []Hash256) []byte {
	numHops := path.TrueRouteLength()

	// We have to generate a filler that matches all but the last
	// hop (the last hop won't generate an HMAC)
	fillerFrames := path.CountFrames() - path[numHops-1].HopPayload.CountFrames()
	filler := make([]byte, fillerFrames*frameSize)

	for i := 0; i < numHops-1; i++ {
		// Sum up how many frames were used by prior hops
		fillerStart := routingInfoSize
		for _, p := range path[:i] {
			fillerStart = fillerStart - (p.HopPayload.CountFrames() * frameSize)
		}

		// The filler is the part dangling off of the end of
		// the routingInfo, so offset it from there, and use
		// the current hop's frame count as its size.
		fillerEnd := routingInfoSize + (path[i].HopPayload.CountFrames() * frameSize)

		streamKey := generateKey(key, &sharedSecrets[i])
		streamBytes := generateCipherStream(streamKey, numStreamBytes)

		xor(filler, filler, streamBytes[fillerStart:fillerEnd])
	}
	return filler
}
```

Note that this example implementation is for demonstration purposes only; the
`filler` can be generated much more efficiently.
The last hop need not obfuscate the `filler`, since it won't forward the packet
any further and thus need not extract an HMAC either.

# Returning Errors

The onion routing protocol includes a simple mechanism for returning encrypted
error messages to the origin node.
The returned error messages may be failures reported by any hop, including the
final node.
The format of the forward packet is not usable for the return path, since no hop
besides the origin has access to the information required for its generation.
Note that these error messages are not reliable, as they are not placed on-chain
due to the possibility of hop failure.

Intermediate hops store the shared secret from the forward path and reuse it to
obfuscate any corresponding return packet during each hop.
In addition, each node locally stores data regarding its own sending peer in the
route, so it knows where to return-forward any eventual return packets.
The node generating the error message (_erring node_) builds a return packet
consisting of the following fields:

1. data:
   * [`32`:`hmac`]
   * [`2`:`failure_len`]
   * [`failure_len`:`failuremsg`]
   * [`2`:`pad_len`]
   * [`pad_len`:`pad`]

Where `hmac` is an HMAC authenticating the remainder of the packet, with a key
generated using the above process, with key type `um`, `failuremsg` as defined
below, and `pad` as the extra bytes used to conceal length.

The erring node then generates a new key, using the key type `ammag`.
This key is then used to generate a pseudo-random stream, which is in turn
applied to the packet using `XOR`.

The obfuscation step is repeated by every hop along the return path.
Upon receiving a return packet, each hop generates its `ammag`, generates the
pseudo-random byte stream, and applies the result to the return packet before
return-forwarding it.

The origin node is able to detect that it's the intended final recipient of the
return message, because of course, it was the originator of the corresponding
forward packet.
When an origin node receives an error message matching a transfer it initiated
(i.e. it cannot return-forward the error any further) it generates the `ammag`
and `um` keys for each hop in the route.
It then iteratively decrypts the error message, using each hop's `ammag`
key, and computes the HMAC, using each hop's `um` key.
The origin node can detect the sender of the error message by matching the
`hmac` field with the computed HMAC.

The association between the forward and return packets is handled outside of
this onion routing protocol, e.g. via association with an HTLC in a payment
channel.

### Requirements

The _erring node_:
  - SHOULD set `pad` such that the `failure_len` plus `pad_len` is equal to 256.
    - Note: this value is 118 bytes longer than the longest currently-defined
    message.

The _origin node_:
  - once the return message has been decrypted:
    - SHOULD store a copy of the message.
    - SHOULD continue decrypting, until the loop has been repeated 20 times.
    - SHOULD use constant `ammag` and `um` keys to obfuscate the route length.

## Failure Messages

The failure message encapsulated in `failuremsg` has an identical format as
a normal message: a 2-byte type `failure_code` followed by data applicable
to that type. Below is a list of the currently supported `failure_code`
values, followed by their use case requirements.

Notice that the `failure_code`s are not of the same type as other message types,
defined in other BOLTs, as they are not sent directly on the transport layer
but are instead wrapped inside return packets.
The numeric values for the `failure_code` may therefore reuse values, that are
also assigned to other message types, without any danger of causing collisions.

The top byte of `failure_code` can be read as a set of flags:
* 0x8000 (BADONION): unparsable onion encrypted by sending peer
* 0x4000 (PERM): permanent failure (otherwise transient)
* 0x2000 (NODE): node failure (otherwise channel)
* 0x1000 (UPDATE): new channel update enclosed

Please note that the `channel_update` field is mandatory in messages whose
`failure_code` includes the `UPDATE` flag.

The following `failure_code`s are defined:

1. type: PERM|1 (`invalid_realm`)

The `realm` byte was not understood by the processing node.

1. type: NODE|2 (`temporary_node_failure`)

General temporary failure of the processing node.

1. type: PERM|NODE|2 (`permanent_node_failure`)

General permanent failure of the processing node.

1. type: PERM|NODE|3 (`required_node_feature_missing`)

The processing node has a required feature which was not in this onion.

1. type: BADONION|PERM|4 (`invalid_onion_version`)
2. data:
   * [`32`:`sha256_of_onion`]

The `version` byte was not understood by the processing node.

1. type: BADONION|PERM|5 (`invalid_onion_hmac`)
2. data:
   * [`32`:`sha256_of_onion`]

The HMAC of the onion was incorrect when it reached the processing node.

1. type: BADONION|PERM|6 (`invalid_onion_key`)
2. data:
   * [`32`:`sha256_of_onion`]

The ephemeral key was unparsable by the processing node.

1. type: UPDATE|7 (`temporary_channel_failure`)
2. data:
   * [`2`:`len`]
   * [`len`:`channel_update`]

The channel from the processing node was unable to handle this HTLC,
but may be able to handle it, or others, later.

1. type: PERM|8 (`permanent_channel_failure`)

The channel from the processing node is unable to handle any HTLCs.

1. type: PERM|9 (`required_channel_feature_missing`)

The channel from the processing node requires features not present in
the onion.

1. type: PERM|10 (`unknown_next_peer`)

The onion specified a `short_channel_id` which doesn't match any
leading from the processing node.

1. type: UPDATE|11 (`amount_below_minimum`)
2. data:
   * [`8`:`htlc_msat`]
   * [`2`:`len`]
   * [`len`:`channel_update`]

The HTLC amount was below the `htlc_minimum_msat` of the channel from
the processing node.

1. type: UPDATE|12 (`fee_insufficient`)
2. data:
   * [`8`:`htlc_msat`]
   * [`2`:`len`]
   * [`len`:`channel_update`]

The fee amount was below that required by the channel from the
processing node.

1. type: UPDATE|13 (`incorrect_cltv_expiry`)
2. data:
   * [`4`:`cltv_expiry`]
   * [`2`:`len`]
   * [`len`:`channel_update`]

The `cltv_expiry` does not comply with the `cltv_expiry_delta` required by
the channel from the processing node: it does not satisfy the following
requirement:

        cltv_expiry - cltv_expiry_delta >= outgoing_cltv_value

1. type: UPDATE|14 (`expiry_too_soon`)
2. data:
   * [`2`:`len`]
   * [`len`:`channel_update`]

The CLTV expiry is too close to the current block height for safe
handling by the processing node.

1. type: PERM|15 (`incorrect_or_unknown_payment_details`)
2. data:
   * [`8`:`htlc_msat`]

The `payment_hash` is unknown to the final node or the amount for that
`payment_hash` is incorrect.

Note: Originally PERM|16 (`incorrect_payment_amount`) was
used to differentiate incorrect final amount from unknown payment
hash. Sadly, sending this response allows for probing attacks whereby a node
which receives an HTLC for forwarding can check guesses as to its final
destination by sending payments with the same hash but much lower values to
potential destinations and check the response.

1. type: 17 (`final_expiry_too_soon`)

The CLTV expiry is too close to the current block height for safe
handling by the final node.

1. type: 18 (`final_incorrect_cltv_expiry`)
2. data:
   * [`4`:`cltv_expiry`]

The CLTV expiry in the HTLC doesn't match the value in the onion.

1. type: 19 (`final_incorrect_htlc_amount`)
2. data:
   * [`8`:`incoming_htlc_amt`]

The amount in the HTLC doesn't match the value in the onion.

1. type: UPDATE|20 (`channel_disabled`)
2. data:
   * [`2`: `flags`]
   * [`2`:`len`]
   * [`len`:`channel_update`]

The channel from the processing node has been disabled.

1. type: 21 (`expiry_too_far`)

The CLTV expiry in the HTLC is too far in the future.

### Requirements

An _erring node_:
  - MUST select one of the above error codes when creating an error message.
  - MUST include the appropriate data for that particular error type.
  - if there is more than one error:
    - SHOULD select the first error it encounters from the list above.

Any _erring node_ MAY:
  - if the `realm` byte is unknown:
    - return an `invalid_realm` error.
  - if an otherwise unspecified transient error occurs for the entire node:
    - return a `temporary_node_failure` error.
  - if an otherwise unspecified permanent error occurs for the entire node:
    - return a `permanent_node_failure` error.
  - if a node has requirements advertised in its `node_announcement` `features`,
  which were NOT included in the onion:
    - return a `required_node_feature_missing` error.

A _forwarding node_ MAY, but a _final node_ MUST NOT:
  - if the onion `version` byte is unknown:
    - return an `invalid_onion_version` error.
  - if the onion HMAC is incorrect:
    - return an `invalid_onion_hmac` error.
  - if the ephemeral key in the onion is unparsable:
    - return an `invalid_onion_key` error.
  - if during forwarding to its receiving peer, an otherwise unspecified,
  transient error occurs in the outgoing channel (e.g. channel capacity reached,
  too many in-flight HTLCs, etc.):
    - return a `temporary_channel_failure` error.
  - if an otherwise unspecified, permanent error occurs during forwarding to its
  receiving peer (e.g. channel recently closed):
    - return a `permanent_channel_failure` error.
  - if the outgoing channel has requirements advertised in its
  `channel_announcement`'s `features`, which were NOT included in the onion:
    - return a `required_channel_feature_missing` error.
  - if the receiving peer specified by the onion is NOT known:
    - return an `unknown_next_peer` error.
  - if the HTLC amount is less than the currently specified minimum amount:
    - report the amount of the outgoing HTLC and the current channel setting for
    the outgoing channel.
    - return an `amount_below_minimum` error.
  - if the HTLC does NOT pay a sufficient fee:
    - report the amount of the incoming HTLC and the current channel setting for
    the outgoing channel.
    - return a `fee_insufficient` error.
 -  if the incoming `cltv_expiry` minus the `outgoing_cltv_value` is below the
    `cltv_expiry_delta` for the outgoing channel:
    - report the `cltv_expiry` of the outgoing HTLC and the current channel setting for the outgoing
    channel.
    - return an `incorrect_cltv_expiry` error.
  - if the `cltv_expiry` is unreasonably near the present:
    - report the current channel setting for the outgoing channel.
    - return an `expiry_too_soon` error.
  - if the `cltv_expiry` is unreasonably far in the future:
    - return an `expiry_too_far` error.
  - if the channel is disabled:
    - report the current channel setting for the outgoing channel.
    - return a `channel_disabled` error.

An _intermediate hop_ MUST NOT, but the _final node_:
  - if the payment hash has already been paid:
    - MAY treat the payment hash as unknown.
    - MAY succeed in accepting the HTLC.
  - if the amount paid is less than the amount expected:
    - MUST fail the HTLC.
    - MUST return an `incorrect_or_unknown_payment_details` error.
  - if the payment hash is unknown:
    - MUST fail the HTLC.
    - MUST return an `incorrect_or_unknown_payment_details` error.
  - if the amount paid is more than twice the amount expected:
    - SHOULD fail the HTLC.
    - SHOULD return an `incorrect_or_unknown_payment_details` error.
      - Note: this allows the origin node to reduce information leakage by
      altering the amount while not allowing for accidental gross overpayment.
  - if the `cltv_expiry` value is unreasonably near the present:
    - MUST fail the HTLC.
    - MUST return a `final_expiry_too_soon` error.
  - if the `outgoing_cltv_value` does NOT correspond with the `cltv_expiry` from
  the final node's HTLC:
    - MUST return `final_incorrect_cltv_expiry` error.
  - if the `amt_to_forward` is greater than the `incoming_htlc_amt` from the
  final node's HTLC:
    - MUST return a `final_incorrect_htlc_amount` error.

## Receiving Failure Codes

### Requirements

The _origin node_:
  - MUST ignore any extra bytes in `failuremsg`.
  - if the _final node_ is returning the error:
    - if the PERM bit is set:
      - SHOULD fail the payment.
    - otherwise:
      - if the error code is understood and valid:
        - MAY retry the payment. In particular, `final_expiry_too_soon` can
        occur if the block height has changed since sending, and in this case
        `temporary_node_failure` could resolve within a few seconds.
  - otherwise, an _intermediate hop_ is returning the error:
    - if the NODE bit is set:
      - SHOULD remove all channels connected with the erring node from
      consideration.
    - if the PERM bit is NOT set:
      - SHOULD restore the channels as it receives new `channel_update`s.
    - otherwise:
      - if UPDATE is set, AND the `channel_update` is valid and more recent
      than the `channel_update` used to send the payment:
        - if `channel_update` should NOT have caused the failure:
          - MAY treat the `channel_update` as invalid.
        - otherwise:
          - SHOULD apply the `channel_update`.
        - MAY queue the `channel_update` for broadcast.
      - otherwise:
        - SHOULD eliminate the channel outgoing from the erring node from
        consideration.
        - if the PERM bit is NOT set:
          - SHOULD restore the channel as it receives new `channel_update`s.
    - SHOULD then retry routing and sending the payment.
  - MAY use the data specified in the various failure types for debugging
  purposes.

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")

This work is licensed under a [Creative Commons Attribution 4.0 International License][cc40]


[sphinx]: http://www.cypherpunks.ca/~iang/pubs/Sphinx_Oakland09.pdf
[RFC2104]: https://tools.ietf.org/html/rfc2104
[fips198]: http://csrc.nist.gov/publications/fips/fips198-1/FIPS-198-1_final.pdf
[sec2]: http://www.secg.org/sec2-v2.pdf
[rfc7539]: https://tools.ietf.org/html/rfc7539
[cc40]: http://creativecommons.org/licenses/by/4.0/
