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
 - a 1300-byte `hops_data` consisting of twenty fixed-size packets, each containing
   information to be used by its associated hop during message forwarding
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
   * [`20*65`:`hops_data`]
   * [`32`:`hmac`]

For this specification (_version 0_), `version` has a constant value of `0x00`.

The `hops_data` field is a structure that holds obfuscations of the next hop's
address, transfer information, and its associated HMAC. It is 1300 bytes (`20x65`) long
and has the following structure:

1. type: `hops_data`
2. data:
   * [`1`:`realm`]
   * [`32`:`per_hop`]
   * [`32`:`HMAC`]
   * ...
   * `filler`

Where, the `realm`, `per_hop` (with contents dependent on `realm`), and `HMAC`
are repeated for each hop; and where, `filler` consists of obfuscated,
deterministically-generated padding, as detailed in
[Filler Generation](#filler-generation). Additionally, `hops_data` is
incrementally obfuscated at each hop.

The `realm` byte determines the format of the `per_hop` field; currently, only `realm`
0 is defined, for which the `per_hop` format follows:

1. type: `per_hop` (for `realm` 0)
2. data:
   * [`8`:`short_channel_id`]
   * [`8`:`amt_to_forward`]
   * [`4`:`outgoing_cltv_value`]
   * [`12`:`padding`]

Using the `per_hop` field, the origin node is able to precisely specify the path and
structure of the HTLCs forwarded at each hop. As the `per_hop` is protected
under the packet-wide HMAC, the information it contains is fully authenticated
with each pair-wise relationship between the HTLC sender (origin node) and each
hop in the path.

Using this end-to-end authentication,
each
hop is able to
cross-check the HTLC parameters with the `per_hop`'s specified values
and to ensure that the sending peer hasn't forwarded an
ill-crafted HTLC.

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
packet. Constructing a packet routed over `r` hops requires `r` 32-byte
ephemeral public keys, `r` 32-byte shared secrets, `r` 32-byte blinding factors,
and `r` 65-byte `per_hop` payloads. The construction returns a single 1366-byte
packet along with the first receiving peer's address.

The packet construction is performed in the reverse order of the route, i.e.
the last hop's operations are applied first.

The packet is initialized with 1366 `0x00`-bytes.

A 65-byte filler is generated (see [Filler Generation](#filler-generation))
using the shared secret.

For each hop in the route, in reverse order, the sender applies the
following operations:

 - The _rho_-key and _mu_-key are generated using the hop's shared secret.
 - The `hops_data` field is right-shifted by 65 bytes, discarding the last 65
 bytes that exceed its 1300-byte size.
 - The `version`, `short_channel_id`, `amt_to_forward`, `outgoing_cltv_value`,
   `padding`, and `HMAC` are copied into the following 65 bytes.
 - The _rho_-key is used to generate 1300 bytes of pseudo-random byte stream
 which is then applied, with `XOR`, to the `hops_data` field.
 - If this is the last hop, i.e. the first iteration, then the tail of the
 `hops_data` field is overwritten with the routing information `filler`.
 - The next HMAC is computed (with the _mu_-key as HMAC-key) over the
 concatenated `hops_data` and associated data.

The resulting final HMAC value is the HMAC that will be used by the first
receiving peer in the route.

The packet generation returns a serialized packet that contains the `version`
byte, the ephemeral pubkey for the first hop, the HMAC for the first hop, and
the obfuscated `hops_data`.

The following Go code is an example implementation of the packet construction:

```Go
func NewOnionPacket(paymentPath []*btcec.PublicKey, sessionKey *btcec.PrivateKey,
	hopsData []HopData, assocData []byte) (*OnionPacket, error) {

	numHops := len(paymentPath)
	hopSharedSecrets := make([][sha256.Size]byte, numHops)

	// Initialize ephemeral key for the first hop to the session key.
	var ephemeralKey big.Int
	ephemeralKey.Set(sessionKey.D)

	for i := 0; i < numHops; i++ {
		// Perform ECDH and hash the result.
		ecdhResult := scalarMult(paymentPath[i], ephemeralKey)
		hopSharedSecrets[i] = sha256.Sum256(ecdhResult.SerializeCompressed())

		// Derive ephemeral public key from private key.
		ephemeralPrivKey := btcec.PrivKeyFromBytes(btcec.S256(), ephemeralKey.Bytes())
		ephemeralPubKey := ephemeralPrivKey.PubKey()

		// Compute blinding factor.
		sha := sha256.New()
		sha.Write(ephemeralPubKey.SerializeCompressed())
		sha.Write(hopSharedSecrets[i])

		var blindingFactor big.Int
		blindingFactor.SetBytes(sha.Sum(nil))

		// Blind ephemeral key for next hop.
		ephemeralKey.Mul(&ephemeralKey, &blindingFactor)
		ephemeralKey.Mod(&ephemeralKey, btcec.S256().Params().N)
	}

	// Generate the padding, called "filler strings" in the paper.
	filler := generateHeaderPadding("rho", numHops, hopDataSize, hopSharedSecrets)

	// Allocate and initialize fields to zero-filled slices
	var mixHeader [routingInfoSize]byte
	var nextHmac [hmacSize]byte

	// Compute the routing information for each hop along with a
	// MAC of the routing information using the shared key for that hop.
	for i := numHops - 1; i >= 0; i-- {
		rhoKey := generateKey("rho", hopSharedSecrets[i])
		muKey := generateKey("mu", hopSharedSecrets[i])

		hopsData[i].HMAC = nextHmac

		// Shift and obfuscate routing information
		streamBytes := generateCipherStream(rhoKey, numStreamBytes)

		rightShift(mixHeader[:], hopDataSize)
		buf := &bytes.Buffer{}
		hopsData[i].Encode(buf)
		copy(mixHeader[:], buf.Bytes())
		xor(mixHeader[:], mixHeader[:], streamBytes[:routingInfoSize])

		// These need to be overwritten, so every node generates a correct padding
		if i == numHops-1 {
			copy(mixHeader[len(mixHeader)-len(filler):], filler)
		}

		packet := append(mixHeader[:], assocData...)
		nextHmac = calcMac(muKey, packet)
	}

	packet := &OnionPacket{
		Version:      0x00,
		EphemeralKey: sessionKey.PubKey(),
		RoutingInfo:  mixHeader,
		HeaderMAC:    nextHmac,
	}
	return packet, nil
}
```

# Packet Forwarding

This specification is limited to `version` `0` packets; the structure
of future versions may change.

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

Comparison of the computed HMAC and the packet's HMAC MUST be
time-constant to avoid information leaks.

At this point, the processing node can generate a _rho_-key and a _gamma_-key.

The routing information is then deobfuscated, and the information about the
next hop is extracted.
To do so, the processing node copies the `hops_data` field, appends 65 `0x00`-bytes,
generates 1365 pseudo-random bytes (using the _rho_-key), and applies the result
,using `XOR`, to the copy of the `hops_data`.
The first 65 bytes of the resulting routing information become the `per_hop`
field used for the next hop. The next 1300 bytes are the `hops_data` for the
outgoing packet.

A special `per_hop` `HMAC` value of 32 `0x00`-bytes indicates that the currently
processing hop is the intended recipient and that the packet should not be forwarded.

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

Before deobfuscating the `hops_data`, the processing node pads it with 65
`0x00`-bytes, such that the total length is `(20 + 1) * 65`.
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
func generateFiller(key string, numHops int, hopSize int, sharedSecrets [][sharedSecretSize]byte) []byte {
	fillerSize := uint((numMaxHops + 1) * hopSize)
	filler := make([]byte, fillerSize)

	// The last hop does not obfuscate, it's not forwarding anymore.
	for i := 0; i < numHops-1; i++ {

		// Left-shift the field
		copy(filler[:], filler[hopSize:])

		// Zero-fill the last hop
		copy(filler[len(filler)-hopSize:], bytes.Repeat([]byte{0x00}, hopSize))

		// Generate pseudo-random byte stream
		streamKey := generateKey(key, sharedSecrets[i])
		streamBytes := generateCipherStream(streamKey, fillerSize)

		// Obfuscate
		xor(filler, filler, streamBytes)
	}

	// Cut filler down to the correct length (numHops+1)*hopSize
	// bytes will be prepended by the packet generation.
	return filler[(numMaxHops-numHops+2)*hopSize:]
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

# Test Vector

## Packet Creation

The following is an in-depth trace (including intermediate data) of an example
of packet creation:

### Parameters

	pubkey[0] = 0x02eec7245d6b7d2ccb30380bfbe2a3648cd7a942653f5aa340edcea1f283686619
	pubkey[1] = 0x0324653eac434488002cc06bbfb7f10fe18991e35f9fe4302dbea6d2353dc0ab1c
	pubkey[2] = 0x027f31ebc5462c1fdce1b737ecff52d37d75dea43ce11c74d25aa297165faa2007
	pubkey[3] = 0x032c0b7cf95324a07d05398b240174dc0c2be444d96b159aa6c7f7b1e668680991
	pubkey[4] = 0x02edabbd16b41c8371b92ef2f04c1185b4f03b6dcd52ba9b78d9d7c89c8f221145

	nhops = 5/20
	sessionkey = 0x4141414141414141414141414141414141414141414141414141414141414141
	associated data = 0x4242424242424242424242424242424242424242424242424242424242424242

The HMAC is omitted in the following `hop_data`, since it's likely to be filled
by the onion construction. Hence, the values below are the `realm`, the
`short_channel_id`, the `amt_to_forward`, the `outgoing_cltv`, and the 12-byte
`padding`. They were initialized by byte-filling the `short_channel_id` to the
each hop's respective position in the route and then, starting at 0, setting
`amt_to_forward` and `outgoing_cltv` to the same route position.

	hop_payload[0] = 0x000000000000000000000000000000000000000000000000000000000000000000
	hop_payload[1] = 0x000101010101010101000000000000000100000001000000000000000000000000
	hop_payload[2] = 0x000202020202020202000000000000000200000002000000000000000000000000
	hop_payload[3] = 0x000303030303030303000000000000000300000003000000000000000000000000
	hop_payload[4] = 0x000404040404040404000000000000000400000004000000000000000000000000

### Per-Hop Information

	hop_shared_secret[0] = 0x53eb63ea8a3fec3b3cd433b85cd62a4b145e1dda09391b348c4e1cd36a03ea66
	hop_blinding_factor[0] = 0x2ec2e5da605776054187180343287683aa6a51b4b1c04d6dd49c45d8cffb3c36
	hop_ephemeral_pubkey[0] = 0x02eec7245d6b7d2ccb30380bfbe2a3648cd7a942653f5aa340edcea1f283686619

	hop_shared_secret[1] = 0xa6519e98832a0b179f62123b3567c106db99ee37bef036e783263602f3488fae
	hop_blinding_factor[1] = 0xbf66c28bc22e598cfd574a1931a2bafbca09163df2261e6d0056b2610dab938f
	hop_ephemeral_pubkey[1] = 0x028f9438bfbf7feac2e108d677e3a82da596be706cc1cf342b75c7b7e22bf4e6e2

	hop_shared_secret[2] = 0x3a6b412548762f0dbccce5c7ae7bb8147d1caf9b5471c34120b30bc9c04891cc
	hop_blinding_factor[2] = 0xa1f2dadd184eb1627049673f18c6325814384facdee5bfd935d9cb031a1698a5
	hop_ephemeral_pubkey[2] = 0x03bfd8225241ea71cd0843db7709f4c222f62ff2d4516fd38b39914ab6b83e0da0

	hop_shared_secret[3] = 0x21e13c2d7cfe7e18836df50872466117a295783ab8aab0e7ecc8c725503ad02d
	hop_blinding_factor[3] = 0x7cfe0b699f35525029ae0fa437c69d0f20f7ed4e3916133f9cacbb13c82ff262
	hop_ephemeral_pubkey[3] = 0x031dde6926381289671300239ea8e57ffaf9bebd05b9a5b95beaf07af05cd43595

	hop_shared_secret[4] = 0xb5756b9b542727dbafc6765a49488b023a725d631af688fc031217e90770c328
	hop_blinding_factor[4] = 0xc96e00dddaf57e7edcd4fb5954be5b65b09f17cb6d20651b4e90315be5779205
	hop_ephemeral_pubkey[4] = 0x03a214ebd875aab6ddfd77f22c5e7311d7f77f17a169e599f157bbcdae8bf071f4

### Per-Packet Information

	filler = 0xc6b008cf6414ed6e4c42c291eb505e9f22f5fe7d0ecdd15a833f4d016ac974d33adc6ea3293e20859e87ebfb937ba406abd025d14af692b12e9c9c2adbe307a679779259676211c071e614fdb386d1ff02db223a5b2fae03df68d321c7b29f7c7240edd3fa1b7cb6903f89dc01abf41b2eb0b49b6b8d73bb0774b58204c0d0e96d3cce45ad75406be0bc009e327b3e712a4bd178609c00b41da2daf8a4b0e1319f07a492ab4efb056f0f599f75e6dc7e0d10ce1cf59088ab6e873de377343880f7a24f0e36731a0b72092f8d5bc8cd346762e93b2bf203d00264e4bc136fc142de8f7b69154deb05854ea88e2d7506222c95ba1aab065c8a851391377d3406a35a9af3ac

### Wrapping the Onion

	rhokey[4] = 0x034e18b8cc718e8af6339106e706c52d8df89e2b1f7e9142d996acf88df8799b
	mukey[4] = 0x8e45e5c61c2b24cb6382444db6698727afb063adecd72aada233d4bf273d975a
	routing_info[4] (unencrypted) = 0x00040404040404040400000000000000040000000400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000
	routing_info[4] (encrypted) = 0xf6a9e85e5c6a0458c98282b782ffe8efb2f3f0e2cae0283a71aa4d873686d7efeac03dcb113fd91113df4bb5d5e8c13cde4bd12eced21d367381fdc31efe09695d6ecc095083c1571d10ed076ee914745479dfedcab84efd3889e6375f544562ea4a6522035738a9ba1a9ab4204339569d3d0c217324f1d5f3a107e930ade50b913777d1140096e2b26ce47486b66a6740f026ae91429115e17270c5a542b4c82ce438725060248726956e7639da64a55cec00b61719383271e0ab97dafe44ad194e7338ea841bf25a505d0041eb53dc0d0e6c3f7986f6647ede9327467212a3ca5724ece8503bfaba3800372d747abe2c174cbc2da01dd967fc0bae56d2bc7184e1d5d823661b8ff06eb466d483d6fa69a4f8b592ebc3006b7c047055b12407925ea74c2bb09ca21f4bc9d39dc4a7237ef6facbb15f5ba56d8e2ab94ad24267bf85cea55b0605cd6260b4b0f17994a03e39bebfcad0834849b188e83bf5c954dc112d33b0fada26f25d76d53ec9b95ed344059a279719d5edc953a4de2b1cc4f47d5da090c3b0f4c7eef14830f9a2230bffb722f11fd2ea82c43d58261e5a868361262abbd81b9f1e6145562ed6765aac732e7d91bfff7716509d72314d46904bcc8053cfd1e3cd7824b4b6499bf8c77762275fa4f651d163a8701f02a5ca67bb7d37787a66d269d4079aa92a489493020b11d87791a3e3ef66780bd0007c8fa2782bac7a839b57e8ace7618a75fe03604097960d2236616d579207fb943c85bef4f804e7f13d7d78ff3aab0f7f440a3005a363f32c31567b8d64669a7ae0299b06b80e4d224d2d70b80077ff966cfb8c11cf763954f398c592ca619acc2e0e86dad54b9cfa47bc10520f3c9ba2e0d2e27e0ba8ef8ece3e71c8a1ff75fe0c8369a3555e42db30565b2e12a8e862d0f873bd781ebf8255372e540bf6fbf4c1dae200823144f8da8df82ccd41b1b678eb91a289b88c6ee5aff71d98b64e8b17e2027fcb6826c418dbdb51f06bec866d69d9554931412808bd90021be2e0dad1d1ececfdd41fcdf6f67b88ef09eb9edcc4c226e07bdfe86b8e50e3bf68b19c0c9e0bf9aaaaddb15bc05a5666733789fa6efde866a49d0329185d852dc84a7e16c41f6c2daadc04665197152d9c0db63d0bd926c06bf3646b810186ae908a2f27a33d010b3262b0c0805c3adf135b41f15a033bb82a8db2c38160dbce672290878d7ad8d08fdd483ef9d95b3a1b2ea2b6ff0adde762e9df7b78fe5f3644df54c6d98709d70924ce6ec94650cb207b4f90d35569acb55811ad3f01b28bb2b16cfde454531b9462024abf419fb3bef80db9bb9fa5bd62a7e94f61a667e74140c8da4b27ad7b934c0824756fbc56f8ac7529fc4c5224158fd4915eba25a3f2a72a7f718a5cda6395bd8b2bc484a950aba483c8cadec376f9bee62c93f886d83371b41c361a36c15679ff933422e09c5eaf98d3c6b008cf6414ed6e4c42c291eb505e9f22f5fe7d0ecdd15a833f4d016ac974d33adc6ea3293e20859e87ebfb937ba406abd025d14af692b12e9c9c2adbe307a679779259676211c071e614fdb386d1ff02db223a5b2fae03df68d321c7b29f7c7240edd3fa1b7cb6903f89dc01abf41b2eb0b49b6b8d73bb0774b58204c0d0e96d3cce45ad75406be0bc009e327b3e712a4bd178609c00b41da2daf8a4b0e1319f07a492ab4efb056f0f599f75e6dc7e0d10ce1cf59088ab6e873de377343880f7a24f0e36731a0b72092f8d5bc8cd346762e93b2bf203d00264e4bc136fc142de8f7b69154deb05854ea88e2d7506222c95ba1aab065c8a851391377d3406a35a9af3ac
	hmac_data[4] = 0xf6a9e85e5c6a0458c98282b782ffe8efb2f3f0e2cae0283a71aa4d873686d7efeac03dcb113fd91113df4bb5d5e8c13cde4bd12eced21d367381fdc31efe09695d6ecc095083c1571d10ed076ee914745479dfedcab84efd3889e6375f544562ea4a6522035738a9ba1a9ab4204339569d3d0c217324f1d5f3a107e930ade50b913777d1140096e2b26ce47486b66a6740f026ae91429115e17270c5a542b4c82ce438725060248726956e7639da64a55cec00b61719383271e0ab97dafe44ad194e7338ea841bf25a505d0041eb53dc0d0e6c3f7986f6647ede9327467212a3ca5724ece8503bfaba3800372d747abe2c174cbc2da01dd967fc0bae56d2bc7184e1d5d823661b8ff06eb466d483d6fa69a4f8b592ebc3006b7c047055b12407925ea74c2bb09ca21f4bc9d39dc4a7237ef6facbb15f5ba56d8e2ab94ad24267bf85cea55b0605cd6260b4b0f17994a03e39bebfcad0834849b188e83bf5c954dc112d33b0fada26f25d76d53ec9b95ed344059a279719d5edc953a4de2b1cc4f47d5da090c3b0f4c7eef14830f9a2230bffb722f11fd2ea82c43d58261e5a868361262abbd81b9f1e6145562ed6765aac732e7d91bfff7716509d72314d46904bcc8053cfd1e3cd7824b4b6499bf8c77762275fa4f651d163a8701f02a5ca67bb7d37787a66d269d4079aa92a489493020b11d87791a3e3ef66780bd0007c8fa2782bac7a839b57e8ace7618a75fe03604097960d2236616d579207fb943c85bef4f804e7f13d7d78ff3aab0f7f440a3005a363f32c31567b8d64669a7ae0299b06b80e4d224d2d70b80077ff966cfb8c11cf763954f398c592ca619acc2e0e86dad54b9cfa47bc10520f3c9ba2e0d2e27e0ba8ef8ece3e71c8a1ff75fe0c8369a3555e42db30565b2e12a8e862d0f873bd781ebf8255372e540bf6fbf4c1dae200823144f8da8df82ccd41b1b678eb91a289b88c6ee5aff71d98b64e8b17e2027fcb6826c418dbdb51f06bec866d69d9554931412808bd90021be2e0dad1d1ececfdd41fcdf6f67b88ef09eb9edcc4c226e07bdfe86b8e50e3bf68b19c0c9e0bf9aaaaddb15bc05a5666733789fa6efde866a49d0329185d852dc84a7e16c41f6c2daadc04665197152d9c0db63d0bd926c06bf3646b810186ae908a2f27a33d010b3262b0c0805c3adf135b41f15a033bb82a8db2c38160dbce672290878d7ad8d08fdd483ef9d95b3a1b2ea2b6ff0adde762e9df7b78fe5f3644df54c6d98709d70924ce6ec94650cb207b4f90d35569acb55811ad3f01b28bb2b16cfde454531b9462024abf419fb3bef80db9bb9fa5bd62a7e94f61a667e74140c8da4b27ad7b934c0824756fbc56f8ac7529fc4c5224158fd4915eba25a3f2a72a7f718a5cda6395bd8b2bc484a950aba483c8cadec376f9bee62c93f886d83371b41c361a36c15679ff933422e09c5eaf98d3c6b008cf6414ed6e4c42c291eb505e9f22f5fe7d0ecdd15a833f4d016ac974d33adc6ea3293e20859e87ebfb937ba406abd025d14af692b12e9c9c2adbe307a679779259676211c071e614fdb386d1ff02db223a5b2fae03df68d321c7b29f7c7240edd3fa1b7cb6903f89dc01abf41b2eb0b49b6b8d73bb0774b58204c0d0e96d3cce45ad75406be0bc009e327b3e712a4bd178609c00b41da2daf8a4b0e1319f07a492ab4efb056f0f599f75e6dc7e0d10ce1cf59088ab6e873de377343880f7a24f0e36731a0b72092f8d5bc8cd346762e93b2bf203d00264e4bc136fc142de8f7b69154deb05854ea88e2d7506222c95ba1aab065c8a851391377d3406a35a9af3ac4242424242424242424242424242424242424242424242424242424242424242
	hmac[4] = 0x62cc962876e734e089e79eda497077fb411fac5f36afd43329040ecd1e16c6d9

	rhokey[3] = 0xcbe784ab745c13ff5cffc2fbe3e84424aa0fd669b8ead4ee562901a4a4e89e9e
	mukey[3] = 0x5052aa1b3d9f0655a0932e50d42f0c9ba0705142c25d225515c45f47c0036ee9
	routing_info[3] (unencrypted) = 0x00030303030303030300000000000000030000000300000000000000000000000062cc962876e734e089e79eda497077fb411fac5f36afd43329040ecd1e16c6d9f6a9e85e5c6a0458c98282b782ffe8efb2f3f0e2cae0283a71aa4d873686d7efeac03dcb113fd91113df4bb5d5e8c13cde4bd12eced21d367381fdc31efe09695d6ecc095083c1571d10ed076ee914745479dfedcab84efd3889e6375f544562ea4a6522035738a9ba1a9ab4204339569d3d0c217324f1d5f3a107e930ade50b913777d1140096e2b26ce47486b66a6740f026ae91429115e17270c5a542b4c82ce438725060248726956e7639da64a55cec00b61719383271e0ab97dafe44ad194e7338ea841bf25a505d0041eb53dc0d0e6c3f7986f6647ede9327467212a3ca5724ece8503bfaba3800372d747abe2c174cbc2da01dd967fc0bae56d2bc7184e1d5d823661b8ff06eb466d483d6fa69a4f8b592ebc3006b7c047055b12407925ea74c2bb09ca21f4bc9d39dc4a7237ef6facbb15f5ba56d8e2ab94ad24267bf85cea55b0605cd6260b4b0f17994a03e39bebfcad0834849b188e83bf5c954dc112d33b0fada26f25d76d53ec9b95ed344059a279719d5edc953a4de2b1cc4f47d5da090c3b0f4c7eef14830f9a2230bffb722f11fd2ea82c43d58261e5a868361262abbd81b9f1e6145562ed6765aac732e7d91bfff7716509d72314d46904bcc8053cfd1e3cd7824b4b6499bf8c77762275fa4f651d163a8701f02a5ca67bb7d37787a66d269d4079aa92a489493020b11d87791a3e3ef66780bd0007c8fa2782bac7a839b57e8ace7618a75fe03604097960d2236616d579207fb943c85bef4f804e7f13d7d78ff3aab0f7f440a3005a363f32c31567b8d64669a7ae0299b06b80e4d224d2d70b80077ff966cfb8c11cf763954f398c592ca619acc2e0e86dad54b9cfa47bc10520f3c9ba2e0d2e27e0ba8ef8ece3e71c8a1ff75fe0c8369a3555e42db30565b2e12a8e862d0f873bd781ebf8255372e540bf6fbf4c1dae200823144f8da8df82ccd41b1b678eb91a289b88c6ee5aff71d98b64e8b17e2027fcb6826c418dbdb51f06bec866d69d9554931412808bd90021be2e0dad1d1ececfdd41fcdf6f67b88ef09eb9edcc4c226e07bdfe86b8e50e3bf68b19c0c9e0bf9aaaaddb15bc05a5666733789fa6efde866a49d0329185d852dc84a7e16c41f6c2daadc04665197152d9c0db63d0bd926c06bf3646b810186ae908a2f27a33d010b3262b0c0805c3adf135b41f15a033bb82a8db2c38160dbce672290878d7ad8d08fdd483ef9d95b3a1b2ea2b6ff0adde762e9df7b78fe5f3644df54c6d98709d70924ce6ec94650cb207b4f90d35569acb55811ad3f01b28bb2b16cfde454531b9462024abf419fb3bef80db9bb9fa5bd62a7e94f61a667e74140c8da4b27ad7b934c0824756fbc56f8ac7529fc4c5224158fd4915eba25a3f2a72a7f718a5cda6395bd8b2bc484a950aba483c8cadec376f9bee62c93f886d83371b41c361a36c15679ff933422e09c5eaf98d3c6b008cf6414ed6e4c42c291eb505e9f22f5fe7d0ecdd15a833f4d016ac974d33adc6ea3293e20859e87ebfb937ba406abd025d14af692b12e9c9c2adbe307a679779259676211c071e614fdb386d1ff02db223a5b2fae03df68d321c7b29f7c7240edd3fa1b7cb6903f89dc01abf41b2eb0b49b6b8d73bb0774b58204c0d0e96d3cce45ad75406be0bc009e327b3e712a4bd178609c00b41da2daf8a4b0e1319f07a492ab4efb056f0f599f75e6dc7e0d10ce1cf59088ab6e873de377343880f7a24f
	routing_info[3] (encrypted) = 0x35dd8ba6f4e53e2f0372992046827fc994c3312b57591844fc713c0cca433626a0b62453d756641c1372dfde1a586ef971823104027062465283f8ff9b89ea3c3daf3e17e529ce3c0c58316f255a42848df14bce0785a4653c84ac8f58bf89671cd0d4b692e9e42584a52509e03f8769bb4ef6a0f6f4002c81011da7f5f9a8da9b19bd25cb25aeb3873c5fa95396b56900847794a97935e542637ef5f42f088c6e24e8e95de7be71d110872c84a60a53bbd789f3a58c1072c5fbb84192dd5f780deb14bdbbf458be297eb3244499a7921db98912625c88350cb29e71ca8d788bfb9bd11146e48659b0d86afe13b47685ec49d36e57292d819442ba516d365be31e7980c0e7b14f40807393b1391d9b83c30191d4bfe49c143da2848d2d7bfd54c32bdfdaefcd4cb84ea895e2305745d2ae257b0414563224af66f3b25d3d451bdd8331670e9dcac78b0690c4ae849d0bd8e956dbc56b5a8114008e9dc54f1252544a45861521efd6376b6c0fb34c1c433b677c08d6bf5356e81772bfeed5a894b590859cd409dedd1cd9881c3b8caed81d4d8d834dbd3e870a39e69d6a1ce2dc15df8f8c34d64d292b0b99bf17bb92b263176b65634dc8f368cf7b558fef5b259964f42ec94eeac74d0abd829baa9b04f89ea3606074a4aace03e7f2217f2dec855f4028392f64f0baddd178d56d84cab16c8484633f7c5e8e7f8651ce8a7f5ce1ca3a966562a0a2a7247d105a3114ab2adbd10cfd70b2765113c42e4d1cbcb8721a719f46b25d8579a670be085d1afd2d2e541c4a27bdfffe49674798cf690f28bf4f58ec1495561be071d1c94156f15c95f3426a7409680ef8cf335a0d4786bbb0bf108589c3c8baf10f04dc7f8beda2f70117f28c771a83890d4e1c47903d642fef8a93a216576f377db3ad5be3abe7eaa924e1e7de9ac88e07177e57cad41ef5a561f6bdb741961eddee56f3d9aef9fc4e52343f2efda3a2d40b8d2b4afa735cd5655d3014d21b41eba3a8cf34a8c29cbf94dfb9a4312ee0851c6e32896b33d52d991560e3ae97c769071453a4969374aecf7423f07ee17ce71111dc925294b0130249ad00d49e26dbfddcaf214dc8356cee3a0d7486fa6144c6c826be0892ceea30e52d7b64a13b08eda3e991f37e210ccd216108c847adb58df3b2a53553689f5119e41b4f4f221474c21e197d8a13e9cf7cf23875a0dbc6ddaeca9eb6d95add2a0054528d9dc03d59bc108157291b4caa0faa53f2511bec3088a164a0768d38d7fe3281ea8459abbe3a5b5f43c697e5cbdc995832220a3c6fcf1e82bd35f4b94b13cc9312efc3ca4e3c8199e862c551fa7916e3cb0ad17ba24e456fcd2159f9e81628c508da4c2de4825100fee1c3226d1d431a740d2d8ab0c04953b073d9a20919e0f2d03e97b3f34a1644cbeeab7d0c78d898e8c523fbccc75ffc329fafe45288e21c82817e23589d0c6db453be7d3f8ecfa0ae1d24ae80c63511193c718195255a576c1b43c8d941ba22f6d9f743a7dd558e08ac2262fd67056d60e837edd3e21ce23ef27d48c9180d845ce8c5d6d4c488fcf55af99aef02f3bdf6a07833660628a672b878f8b15427189e49bf2d9e0e7e63e3c5632d9ef1e412e9bbd732b616a353097e90494a098df6a21729f1d3658f91b1bde4aaaae58530ab0e402fc10eb0910c07cace1afd0aacb579690e6dcbc184025e4160cf4de3e47106339046724d098b5b7b92f5a2bb33c11f86d4953f372fdd9ebc260b0ee2e391420c4b11145bd439954834d9a79e78abc57e03d3ee20d239d8a13014976e3f057ab3c38ca79ee81ff8849d94dca37b0920cc3e72
	hmac_data[3] = 0x35dd8ba6f4e53e2f0372992046827fc994c3312b57591844fc713c0cca433626a0b62453d756641c1372dfde1a586ef971823104027062465283f8ff9b89ea3c3daf3e17e529ce3c0c58316f255a42848df14bce0785a4653c84ac8f58bf89671cd0d4b692e9e42584a52509e03f8769bb4ef6a0f6f4002c81011da7f5f9a8da9b19bd25cb25aeb3873c5fa95396b56900847794a97935e542637ef5f42f088c6e24e8e95de7be71d110872c84a60a53bbd789f3a58c1072c5fbb84192dd5f780deb14bdbbf458be297eb3244499a7921db98912625c88350cb29e71ca8d788bfb9bd11146e48659b0d86afe13b47685ec49d36e57292d819442ba516d365be31e7980c0e7b14f40807393b1391d9b83c30191d4bfe49c143da2848d2d7bfd54c32bdfdaefcd4cb84ea895e2305745d2ae257b0414563224af66f3b25d3d451bdd8331670e9dcac78b0690c4ae849d0bd8e956dbc56b5a8114008e9dc54f1252544a45861521efd6376b6c0fb34c1c433b677c08d6bf5356e81772bfeed5a894b590859cd409dedd1cd9881c3b8caed81d4d8d834dbd3e870a39e69d6a1ce2dc15df8f8c34d64d292b0b99bf17bb92b263176b65634dc8f368cf7b558fef5b259964f42ec94eeac74d0abd829baa9b04f89ea3606074a4aace03e7f2217f2dec855f4028392f64f0baddd178d56d84cab16c8484633f7c5e8e7f8651ce8a7f5ce1ca3a966562a0a2a7247d105a3114ab2adbd10cfd70b2765113c42e4d1cbcb8721a719f46b25d8579a670be085d1afd2d2e541c4a27bdfffe49674798cf690f28bf4f58ec1495561be071d1c94156f15c95f3426a7409680ef8cf335a0d4786bbb0bf108589c3c8baf10f04dc7f8beda2f70117f28c771a83890d4e1c47903d642fef8a93a216576f377db3ad5be3abe7eaa924e1e7de9ac88e07177e57cad41ef5a561f6bdb741961eddee56f3d9aef9fc4e52343f2efda3a2d40b8d2b4afa735cd5655d3014d21b41eba3a8cf34a8c29cbf94dfb9a4312ee0851c6e32896b33d52d991560e3ae97c769071453a4969374aecf7423f07ee17ce71111dc925294b0130249ad00d49e26dbfddcaf214dc8356cee3a0d7486fa6144c6c826be0892ceea30e52d7b64a13b08eda3e991f37e210ccd216108c847adb58df3b2a53553689f5119e41b4f4f221474c21e197d8a13e9cf7cf23875a0dbc6ddaeca9eb6d95add2a0054528d9dc03d59bc108157291b4caa0faa53f2511bec3088a164a0768d38d7fe3281ea8459abbe3a5b5f43c697e5cbdc995832220a3c6fcf1e82bd35f4b94b13cc9312efc3ca4e3c8199e862c551fa7916e3cb0ad17ba24e456fcd2159f9e81628c508da4c2de4825100fee1c3226d1d431a740d2d8ab0c04953b073d9a20919e0f2d03e97b3f34a1644cbeeab7d0c78d898e8c523fbccc75ffc329fafe45288e21c82817e23589d0c6db453be7d3f8ecfa0ae1d24ae80c63511193c718195255a576c1b43c8d941ba22f6d9f743a7dd558e08ac2262fd67056d60e837edd3e21ce23ef27d48c9180d845ce8c5d6d4c488fcf55af99aef02f3bdf6a07833660628a672b878f8b15427189e49bf2d9e0e7e63e3c5632d9ef1e412e9bbd732b616a353097e90494a098df6a21729f1d3658f91b1bde4aaaae58530ab0e402fc10eb0910c07cace1afd0aacb579690e6dcbc184025e4160cf4de3e47106339046724d098b5b7b92f5a2bb33c11f86d4953f372fdd9ebc260b0ee2e391420c4b11145bd439954834d9a79e78abc57e03d3ee20d239d8a13014976e3f057ab3c38ca79ee81ff8849d94dca37b0920cc3e724242424242424242424242424242424242424242424242424242424242424242
	hmac[3] = 0x0daed5f832ef34ea8d0d2cc0699134287a2739c77152d9edc8fe5ccce7ec838f

	rhokey[2] = 0x11bf5c4f960239cb37833936aa3d02cea82c0f39fd35f566109c41f9eac8deea
	mukey[2] = 0xcaafe2820fa00eb2eeb78695ae452eba38f5a53ed6d53518c5c6edf76f3f5b78
	routing_info[2] (unencrypted) = 0x0002020202020202020000000000000002000000020000000000000000000000000daed5f832ef34ea8d0d2cc0699134287a2739c77152d9edc8fe5ccce7ec838f35dd8ba6f4e53e2f0372992046827fc994c3312b57591844fc713c0cca433626a0b62453d756641c1372dfde1a586ef971823104027062465283f8ff9b89ea3c3daf3e17e529ce3c0c58316f255a42848df14bce0785a4653c84ac8f58bf89671cd0d4b692e9e42584a52509e03f8769bb4ef6a0f6f4002c81011da7f5f9a8da9b19bd25cb25aeb3873c5fa95396b56900847794a97935e542637ef5f42f088c6e24e8e95de7be71d110872c84a60a53bbd789f3a58c1072c5fbb84192dd5f780deb14bdbbf458be297eb3244499a7921db98912625c88350cb29e71ca8d788bfb9bd11146e48659b0d86afe13b47685ec49d36e57292d819442ba516d365be31e7980c0e7b14f40807393b1391d9b83c30191d4bfe49c143da2848d2d7bfd54c32bdfdaefcd4cb84ea895e2305745d2ae257b0414563224af66f3b25d3d451bdd8331670e9dcac78b0690c4ae849d0bd8e956dbc56b5a8114008e9dc54f1252544a45861521efd6376b6c0fb34c1c433b677c08d6bf5356e81772bfeed5a894b590859cd409dedd1cd9881c3b8caed81d4d8d834dbd3e870a39e69d6a1ce2dc15df8f8c34d64d292b0b99bf17bb92b263176b65634dc8f368cf7b558fef5b259964f42ec94eeac74d0abd829baa9b04f89ea3606074a4aace03e7f2217f2dec855f4028392f64f0baddd178d56d84cab16c8484633f7c5e8e7f8651ce8a7f5ce1ca3a966562a0a2a7247d105a3114ab2adbd10cfd70b2765113c42e4d1cbcb8721a719f46b25d8579a670be085d1afd2d2e541c4a27bdfffe49674798cf690f28bf4f58ec1495561be071d1c94156f15c95f3426a7409680ef8cf335a0d4786bbb0bf108589c3c8baf10f04dc7f8beda2f70117f28c771a83890d4e1c47903d642fef8a93a216576f377db3ad5be3abe7eaa924e1e7de9ac88e07177e57cad41ef5a561f6bdb741961eddee56f3d9aef9fc4e52343f2efda3a2d40b8d2b4afa735cd5655d3014d21b41eba3a8cf34a8c29cbf94dfb9a4312ee0851c6e32896b33d52d991560e3ae97c769071453a4969374aecf7423f07ee17ce71111dc925294b0130249ad00d49e26dbfddcaf214dc8356cee3a0d7486fa6144c6c826be0892ceea30e52d7b64a13b08eda3e991f37e210ccd216108c847adb58df3b2a53553689f5119e41b4f4f221474c21e197d8a13e9cf7cf23875a0dbc6ddaeca9eb6d95add2a0054528d9dc03d59bc108157291b4caa0faa53f2511bec3088a164a0768d38d7fe3281ea8459abbe3a5b5f43c697e5cbdc995832220a3c6fcf1e82bd35f4b94b13cc9312efc3ca4e3c8199e862c551fa7916e3cb0ad17ba24e456fcd2159f9e81628c508da4c2de4825100fee1c3226d1d431a740d2d8ab0c04953b073d9a20919e0f2d03e97b3f34a1644cbeeab7d0c78d898e8c523fbccc75ffc329fafe45288e21c82817e23589d0c6db453be7d3f8ecfa0ae1d24ae80c63511193c718195255a576c1b43c8d941ba22f6d9f743a7dd558e08ac2262fd67056d60e837edd3e21ce23ef27d48c9180d845ce8c5d6d4c488fcf55af99aef02f3bdf6a07833660628a672b878f8b15427189e49bf2d9e0e7e63e3c5632d9ef1e412e9bbd732b616a353097e90494a098df6a21729f1d3658f91b1bde4aaaae58530ab0e402fc10eb0910c07cace1afd0aacb579690e6dcbc184025e4160cf4de3e47106339046724d098b5b7b92f5a2bb33c11f86d4
	routing_info[2] (encrypted) = 0xe22ca641baa077154733abc584fae578ea0ed4c1871d0554235171e45e1e2a1868760d4c61ed34c17bc188784a4684939fd54d7b4aa9d83c21aec9ad843035b63836277ec6404d85da476af5cfbce7a392d4b8c931b67629c04ff70c08e51fa8d73eaef8c0bdad85ad9872ba87afe0846b75a05e004a744b02687a8c3110a88471b7faea10de1025016f6fcb6f685abdaf55c7908fd922f531d27e206307f7c9086355a351298fd6ed1f05d8724a6b159f52ed4cb988cde07f1d0eb0384803511b480ed31a1ecb7320bbd98da168ae64de73347d59df8ed0588aba661dc2d0bba2bc74ac0d2c479f466ee73def4a32cd806b0966b8f535e742c6a907af0f3dad003016db95194d381109c53499efcf4d868677c3a6dc4a184eccc2198aec260673a801814e60405670f557e618bb3b5df1e51cc90d995d0832b307c102b3fd1d083f52794ccb5a185885280dbd9e36ce64ddf320b6a7e340180e4f525c682bcd1f9cfa3ae5bbd8cdbd83e3d291e98606a7890bd8abbcf57aea1492fc1d6c876cad86446fc85b2db47ff2c6ea384fdda8bc53e81152687a702318c91f657253403612393ec7f864ddf5e807497cb88816f736f08a593d8d1e2c46c13675de2b2aa8c383b8610a5c772bbcf831e426f750c6358e623d9938890aa1d70297c4e4d238b14967f48da074ca469212336a77a2fe0fc80dc2ecd59a2ca389440cb2c1f9835786ad7e1f5bf3ceb27c8abe10178bffcbd888a9b31b9b9a5e308cefe00bdc25c82597dc22ff814b4dcb717be6ec6d87cf25dbb9fde6726461d504d4b9707d708238415ca3dc6e86d3738b902ff4a449597fcac06757fd97e0fe52c1addf7b34731366e2a5694883c60f4c9676ea6167a9fbf8b7d64932676e11fd38f7338e8954236ae31dbd7e2732d74a16b4d0809229ce44e696ceb383c41375ea0e40686f4e0c3967fa22a9e8a2ebb637816c8d1875edf86b1a4998b8525708a027a57852e28e7e84ab3d0db6b73b7e6775604d317139bc0146fedf45a17bc8b3559d4921cb87c51a21f374e040da55e013f4748b22e58f3a53f8ba733bf823eec2f2e8250d3584bd0719bdc36c1f411bfc3d6baf0db966ff2f60dc348da8ed5d011634677ff04c705b6a6942eaffbea4dc0ff5451083f5f7117df044b868df8ae2291ee68998f4c159e885ebcd1073f751899557546e5d8ddbee87a5747e5fa3f5610adf7dece55a339276e7efc3d9a152f222dd3f0452ee4ec56af7a5c1f3b9130ccf1c689e8e1401e8b885ca67349b69526ff523f217c3b36c643a9c46c46b0dc2d0f1d80c83435f752740ee7e423a59badfd5981706ec62d38ce07295ef4fbe23a4ab6cf85a2289e09cc5ad0bae981d3f42e9c6c85eeaff1f257e8ab99c2e93754e88ccd23fe3ad9c78be182b3944b79877aa1eced48b8fcf1f51c5cd01c4b2b111c97f0338e0efccc61e728e784c51d50371f453d926b02fae5c46e118a2f23a28d6f0830ec04b736ed84cf09ea1b0e228d13d7c8794ae6f363d100538a9baa9fbe533a909717dcce4c012d7f258aaee4b41c2e3f1bfe44a652ba8da51dc67164c43112805d474372b9076f3f3f0e7af94604f4fcddd2136dd7dc80ce3ff845924462cf52f5818aebf3b64f38f98edf8cb9c460477a2f94b891573929c4b51deafe6db81bc30680f7226a68567588f195ce96a791e28204b9b5844c28a61736ac20722fe156175210c7b9b6e1804c89c0a7ee136597b5b3de5d54be23671bc9477805ba10d03afb0715782845d2ab45df012f6644207cc5fa4739aa3eaf6bf84e790128aa08aede33bf30c6be2b264b33fac566209
	hmac_data[2] = 0xe22ca641baa077154733abc584fae578ea0ed4c1871d0554235171e45e1e2a1868760d4c61ed34c17bc188784a4684939fd54d7b4aa9d83c21aec9ad843035b63836277ec6404d85da476af5cfbce7a392d4b8c931b67629c04ff70c08e51fa8d73eaef8c0bdad85ad9872ba87afe0846b75a05e004a744b02687a8c3110a88471b7faea10de1025016f6fcb6f685abdaf55c7908fd922f531d27e206307f7c9086355a351298fd6ed1f05d8724a6b159f52ed4cb988cde07f1d0eb0384803511b480ed31a1ecb7320bbd98da168ae64de73347d59df8ed0588aba661dc2d0bba2bc74ac0d2c479f466ee73def4a32cd806b0966b8f535e742c6a907af0f3dad003016db95194d381109c53499efcf4d868677c3a6dc4a184eccc2198aec260673a801814e60405670f557e618bb3b5df1e51cc90d995d0832b307c102b3fd1d083f52794ccb5a185885280dbd9e36ce64ddf320b6a7e340180e4f525c682bcd1f9cfa3ae5bbd8cdbd83e3d291e98606a7890bd8abbcf57aea1492fc1d6c876cad86446fc85b2db47ff2c6ea384fdda8bc53e81152687a702318c91f657253403612393ec7f864ddf5e807497cb88816f736f08a593d8d1e2c46c13675de2b2aa8c383b8610a5c772bbcf831e426f750c6358e623d9938890aa1d70297c4e4d238b14967f48da074ca469212336a77a2fe0fc80dc2ecd59a2ca389440cb2c1f9835786ad7e1f5bf3ceb27c8abe10178bffcbd888a9b31b9b9a5e308cefe00bdc25c82597dc22ff814b4dcb717be6ec6d87cf25dbb9fde6726461d504d4b9707d708238415ca3dc6e86d3738b902ff4a449597fcac06757fd97e0fe52c1addf7b34731366e2a5694883c60f4c9676ea6167a9fbf8b7d64932676e11fd38f7338e8954236ae31dbd7e2732d74a16b4d0809229ce44e696ceb383c41375ea0e40686f4e0c3967fa22a9e8a2ebb637816c8d1875edf86b1a4998b8525708a027a57852e28e7e84ab3d0db6b73b7e6775604d317139bc0146fedf45a17bc8b3559d4921cb87c51a21f374e040da55e013f4748b22e58f3a53f8ba733bf823eec2f2e8250d3584bd0719bdc36c1f411bfc3d6baf0db966ff2f60dc348da8ed5d011634677ff04c705b6a6942eaffbea4dc0ff5451083f5f7117df044b868df8ae2291ee68998f4c159e885ebcd1073f751899557546e5d8ddbee87a5747e5fa3f5610adf7dece55a339276e7efc3d9a152f222dd3f0452ee4ec56af7a5c1f3b9130ccf1c689e8e1401e8b885ca67349b69526ff523f217c3b36c643a9c46c46b0dc2d0f1d80c83435f752740ee7e423a59badfd5981706ec62d38ce07295ef4fbe23a4ab6cf85a2289e09cc5ad0bae981d3f42e9c6c85eeaff1f257e8ab99c2e93754e88ccd23fe3ad9c78be182b3944b79877aa1eced48b8fcf1f51c5cd01c4b2b111c97f0338e0efccc61e728e784c51d50371f453d926b02fae5c46e118a2f23a28d6f0830ec04b736ed84cf09ea1b0e228d13d7c8794ae6f363d100538a9baa9fbe533a909717dcce4c012d7f258aaee4b41c2e3f1bfe44a652ba8da51dc67164c43112805d474372b9076f3f3f0e7af94604f4fcddd2136dd7dc80ce3ff845924462cf52f5818aebf3b64f38f98edf8cb9c460477a2f94b891573929c4b51deafe6db81bc30680f7226a68567588f195ce96a791e28204b9b5844c28a61736ac20722fe156175210c7b9b6e1804c89c0a7ee136597b5b3de5d54be23671bc9477805ba10d03afb0715782845d2ab45df012f6644207cc5fa4739aa3eaf6bf84e790128aa08aede33bf30c6be2b264b33fac5662094242424242424242424242424242424242424242424242424242424242424242
	hmac[2] = 0x548e58057ab0a0e6c2d8ad8e855d89f9224279a5652895ea14f60bffb81590eb

	rhokey[1] = 0x450ffcabc6449094918ebe13d4f03e433d20a3d28a768203337bc40b6e4b2c59
	mukey[1] = 0x05ed2b4a3fb023c2ff5dd6ed4b9b6ea7383f5cfe9d59c11d121ec2c81ca2eea9
	routing_info[1] (unencrypted) = 0x000101010101010101000000000000000100000001000000000000000000000000548e58057ab0a0e6c2d8ad8e855d89f9224279a5652895ea14f60bffb81590ebe22ca641baa077154733abc584fae578ea0ed4c1871d0554235171e45e1e2a1868760d4c61ed34c17bc188784a4684939fd54d7b4aa9d83c21aec9ad843035b63836277ec6404d85da476af5cfbce7a392d4b8c931b67629c04ff70c08e51fa8d73eaef8c0bdad85ad9872ba87afe0846b75a05e004a744b02687a8c3110a88471b7faea10de1025016f6fcb6f685abdaf55c7908fd922f531d27e206307f7c9086355a351298fd6ed1f05d8724a6b159f52ed4cb988cde07f1d0eb0384803511b480ed31a1ecb7320bbd98da168ae64de73347d59df8ed0588aba661dc2d0bba2bc74ac0d2c479f466ee73def4a32cd806b0966b8f535e742c6a907af0f3dad003016db95194d381109c53499efcf4d868677c3a6dc4a184eccc2198aec260673a801814e60405670f557e618bb3b5df1e51cc90d995d0832b307c102b3fd1d083f52794ccb5a185885280dbd9e36ce64ddf320b6a7e340180e4f525c682bcd1f9cfa3ae5bbd8cdbd83e3d291e98606a7890bd8abbcf57aea1492fc1d6c876cad86446fc85b2db47ff2c6ea384fdda8bc53e81152687a702318c91f657253403612393ec7f864ddf5e807497cb88816f736f08a593d8d1e2c46c13675de2b2aa8c383b8610a5c772bbcf831e426f750c6358e623d9938890aa1d70297c4e4d238b14967f48da074ca469212336a77a2fe0fc80dc2ecd59a2ca389440cb2c1f9835786ad7e1f5bf3ceb27c8abe10178bffcbd888a9b31b9b9a5e308cefe00bdc25c82597dc22ff814b4dcb717be6ec6d87cf25dbb9fde6726461d504d4b9707d708238415ca3dc6e86d3738b902ff4a449597fcac06757fd97e0fe52c1addf7b34731366e2a5694883c60f4c9676ea6167a9fbf8b7d64932676e11fd38f7338e8954236ae31dbd7e2732d74a16b4d0809229ce44e696ceb383c41375ea0e40686f4e0c3967fa22a9e8a2ebb637816c8d1875edf86b1a4998b8525708a027a57852e28e7e84ab3d0db6b73b7e6775604d317139bc0146fedf45a17bc8b3559d4921cb87c51a21f374e040da55e013f4748b22e58f3a53f8ba733bf823eec2f2e8250d3584bd0719bdc36c1f411bfc3d6baf0db966ff2f60dc348da8ed5d011634677ff04c705b6a6942eaffbea4dc0ff5451083f5f7117df044b868df8ae2291ee68998f4c159e885ebcd1073f751899557546e5d8ddbee87a5747e5fa3f5610adf7dece55a339276e7efc3d9a152f222dd3f0452ee4ec56af7a5c1f3b9130ccf1c689e8e1401e8b885ca67349b69526ff523f217c3b36c643a9c46c46b0dc2d0f1d80c83435f752740ee7e423a59badfd5981706ec62d38ce07295ef4fbe23a4ab6cf85a2289e09cc5ad0bae981d3f42e9c6c85eeaff1f257e8ab99c2e93754e88ccd23fe3ad9c78be182b3944b79877aa1eced48b8fcf1f51c5cd01c4b2b111c97f0338e0efccc61e728e784c51d50371f453d926b02fae5c46e118a2f23a28d6f0830ec04b736ed84cf09ea1b0e228d13d7c8794ae6f363d100538a9baa9fbe533a909717dcce4c012d7f258aaee4b41c2e3f1bfe44a652ba8da51dc67164c43112805d474372b9076f3f3f0e7af94604f4fcddd2136dd7dc80ce3ff845924462cf52f5818aebf3b64f38f98edf8cb9c460477a2f94b891573929c4b51deafe6db81bc30680f7226a68567588f195ce96a791e28204b9b5844c28a61736ac20722fe156175210c7b9b6e1804c89c0a7ee136
	routing_info[1] (encrypted) = 0x03445185327b8cbf5c5bfa27f825f3a9af4f431f6e7a16ad786704887cbd85bd93ea121ae2ef7bd3e013160bcd3f3221de72fb18b2817404cb6ed0f761eacda9a22e464b80d7772900ad5040e65374840ee298625c75768d6199fa32154615bb0bd8d9876f25d08d2569c04c58f1b425b6719fe213327d45f13b277a6334bd175ae300b29fe5456be97ea49b4b0b4501a96b8432e111c936ae7d94c9de13ecda4ed4b79d2d3e3936e59384ae852d338141b196ea5fe26ad429bf1372a003730981f0bb85a7e9c07d9fba335719c04ec58607918874c513a94c6426bd0181a3233ba12283b03be24cb8e2a530a8cb92b9bed43889267aab86d69d3d72f734e6768324125c75b25988ac2aab93da5939e2059fc0d5479d7c404b6bd1e5a9e995e47cb6966bb063377aedd689052f0a72c6576548f7264989ccd9838068b56cf7e3620f88627276674be6376007208afb027234b9e2a0267a51141ffa8ae1f3da72a8604417e63cffc3d5c4263c7e96c7ef2baa91dcf629efb87a088550b6165686c75ff9f60f24d79b5e560ceb38e987f0371cd002c1ebd09cfe3bfa1191ea1e4b23886d20a64a4526584d7beb2db9c51c3895d84cc9ecb15bff52cc64320c1f79f7d3659e2ee54a4aeed1cebb412eacd782f83ae2288c623e1a1256370262fd1afbb1a61d5e323d5bd679690105b597f027141d035a0f6ec4ef468d9a3ab39b9d54f1817878b745567f181b6678b9900299c11f21c92618da90cb10b2ecbef3d07a0b78cd35ddcc11d02e2e859f9296687268979557b99a9eaffd0875bdce1c03b1f507537916d0aba5aa437c3611ddf9e6975fc82545b67344a4f02125b08a27873079e4490519ec839a105638728d6b2dffa8024b6c4eb08dd793fbd7e53aac0e327401e1de38f826d7ac66beea3925232b0c7d086095a474b1c4f5dbb5651f5de1d1699b90bb500202673d867d00654244ece624c820d7a84db2c5e9515ace71158e45d52790a47b3b7c33ffda69b04dcf107a61a5bb0e6ab6bf06d6b44552d823f2b5969ccbe2f3986cb7180bf7acad66684117c391ff428a2023d7d29063766bb9fbb2c276c3067fab08c7fcf18fa3741b2bd409a58a4fc67d9cffde1faeb39dd86b21fa9b7930c2c6b8d28e4aeea263b3bec2bbc95b939c6ad208689204b83ea8eec2e90a42c0fde1ca8de5aaacd8a614328f83480b4a5bb5e12546ba0e56aef9e88d813dcc7c83f905c91bc5853b7d734a160f3e0efc10237aae97767abea0181c48861f2fabe52a38bcd7859d25ac5dc80eb457615d5064d77a81516b97f90c2feab7861dd9728d51a05247ef5defa05d77486812bd909195ef11c772b374d6cbe18a218af26aa19c72de077307567fa90b18eb1bc77a357ab09cc637b93d5d55793ea075285d60b04ca48bcdd45a32f55932358687db09440ff4ba255fa72e4dacee47e9029bfc16af51e121efdeb189b31dd5be103ef9dd2b5eac641768a81fce1056e6416cb8fc53b8fe946f8e37ab1f94520c3fb0d01dc15207cdec370b0fe76e5234343db30b2f8e0afdc50f1d52d761fbcd3dfcca053f01cfd3c43763546f9d5fc66e1adba7c9d66af0f61d27622f12372c4a75af5861151dcd2da571c7e90c7bde4dae9aea645f85c0781e4472e2b68d63d6789e3dc7ccb543ec47d68d1fa700c0081908a8d2e4687b6e826f4254bc169921b7e02643f3faa0264c7ff77a52205a9388d0a98c0394dc4dee81989115ade30d309374fea8435815418038534d12e4ffe88b91406a71d89d5a083e3b8224d86b2be11be32169afb04b9ea997854be9085472c342ef5fca19bf5479
	hmac_data[1] = 0x03445185327b8cbf5c5bfa27f825f3a9af4f431f6e7a16ad786704887cbd85bd93ea121ae2ef7bd3e013160bcd3f3221de72fb18b2817404cb6ed0f761eacda9a22e464b80d7772900ad5040e65374840ee298625c75768d6199fa32154615bb0bd8d9876f25d08d2569c04c58f1b425b6719fe213327d45f13b277a6334bd175ae300b29fe5456be97ea49b4b0b4501a96b8432e111c936ae7d94c9de13ecda4ed4b79d2d3e3936e59384ae852d338141b196ea5fe26ad429bf1372a003730981f0bb85a7e9c07d9fba335719c04ec58607918874c513a94c6426bd0181a3233ba12283b03be24cb8e2a530a8cb92b9bed43889267aab86d69d3d72f734e6768324125c75b25988ac2aab93da5939e2059fc0d5479d7c404b6bd1e5a9e995e47cb6966bb063377aedd689052f0a72c6576548f7264989ccd9838068b56cf7e3620f88627276674be6376007208afb027234b9e2a0267a51141ffa8ae1f3da72a8604417e63cffc3d5c4263c7e96c7ef2baa91dcf629efb87a088550b6165686c75ff9f60f24d79b5e560ceb38e987f0371cd002c1ebd09cfe3bfa1191ea1e4b23886d20a64a4526584d7beb2db9c51c3895d84cc9ecb15bff52cc64320c1f79f7d3659e2ee54a4aeed1cebb412eacd782f83ae2288c623e1a1256370262fd1afbb1a61d5e323d5bd679690105b597f027141d035a0f6ec4ef468d9a3ab39b9d54f1817878b745567f181b6678b9900299c11f21c92618da90cb10b2ecbef3d07a0b78cd35ddcc11d02e2e859f9296687268979557b99a9eaffd0875bdce1c03b1f507537916d0aba5aa437c3611ddf9e6975fc82545b67344a4f02125b08a27873079e4490519ec839a105638728d6b2dffa8024b6c4eb08dd793fbd7e53aac0e327401e1de38f826d7ac66beea3925232b0c7d086095a474b1c4f5dbb5651f5de1d1699b90bb500202673d867d00654244ece624c820d7a84db2c5e9515ace71158e45d52790a47b3b7c33ffda69b04dcf107a61a5bb0e6ab6bf06d6b44552d823f2b5969ccbe2f3986cb7180bf7acad66684117c391ff428a2023d7d29063766bb9fbb2c276c3067fab08c7fcf18fa3741b2bd409a58a4fc67d9cffde1faeb39dd86b21fa9b7930c2c6b8d28e4aeea263b3bec2bbc95b939c6ad208689204b83ea8eec2e90a42c0fde1ca8de5aaacd8a614328f83480b4a5bb5e12546ba0e56aef9e88d813dcc7c83f905c91bc5853b7d734a160f3e0efc10237aae97767abea0181c48861f2fabe52a38bcd7859d25ac5dc80eb457615d5064d77a81516b97f90c2feab7861dd9728d51a05247ef5defa05d77486812bd909195ef11c772b374d6cbe18a218af26aa19c72de077307567fa90b18eb1bc77a357ab09cc637b93d5d55793ea075285d60b04ca48bcdd45a32f55932358687db09440ff4ba255fa72e4dacee47e9029bfc16af51e121efdeb189b31dd5be103ef9dd2b5eac641768a81fce1056e6416cb8fc53b8fe946f8e37ab1f94520c3fb0d01dc15207cdec370b0fe76e5234343db30b2f8e0afdc50f1d52d761fbcd3dfcca053f01cfd3c43763546f9d5fc66e1adba7c9d66af0f61d27622f12372c4a75af5861151dcd2da571c7e90c7bde4dae9aea645f85c0781e4472e2b68d63d6789e3dc7ccb543ec47d68d1fa700c0081908a8d2e4687b6e826f4254bc169921b7e02643f3faa0264c7ff77a52205a9388d0a98c0394dc4dee81989115ade30d309374fea8435815418038534d12e4ffe88b91406a71d89d5a083e3b8224d86b2be11be32169afb04b9ea997854be9085472c342ef5fca19bf54794242424242424242424242424242424242424242424242424242424242424242
	hmac[1] = 0x9b122c79c8aee73ea2cdbc22eca15bbcc9409a4cdd73d2b3fcd4fe26a492d376

	rhokey[0] = 0xce496ec94def95aadd4bec15cdb41a740c9f2b62347c4917325fcc6fb0453986
	mukey[0] = 0xb57061dc6d0a2b9f261ac410c8b26d64ac5506cbba30267a649c28c179400eba
	routing_info[0] (unencrypted) = 0x0000000000000000000000000000000000000000000000000000000000000000009b122c79c8aee73ea2cdbc22eca15bbcc9409a4cdd73d2b3fcd4fe26a492d37603445185327b8cbf5c5bfa27f825f3a9af4f431f6e7a16ad786704887cbd85bd93ea121ae2ef7bd3e013160bcd3f3221de72fb18b2817404cb6ed0f761eacda9a22e464b80d7772900ad5040e65374840ee298625c75768d6199fa32154615bb0bd8d9876f25d08d2569c04c58f1b425b6719fe213327d45f13b277a6334bd175ae300b29fe5456be97ea49b4b0b4501a96b8432e111c936ae7d94c9de13ecda4ed4b79d2d3e3936e59384ae852d338141b196ea5fe26ad429bf1372a003730981f0bb85a7e9c07d9fba335719c04ec58607918874c513a94c6426bd0181a3233ba12283b03be24cb8e2a530a8cb92b9bed43889267aab86d69d3d72f734e6768324125c75b25988ac2aab93da5939e2059fc0d5479d7c404b6bd1e5a9e995e47cb6966bb063377aedd689052f0a72c6576548f7264989ccd9838068b56cf7e3620f88627276674be6376007208afb027234b9e2a0267a51141ffa8ae1f3da72a8604417e63cffc3d5c4263c7e96c7ef2baa91dcf629efb87a088550b6165686c75ff9f60f24d79b5e560ceb38e987f0371cd002c1ebd09cfe3bfa1191ea1e4b23886d20a64a4526584d7beb2db9c51c3895d84cc9ecb15bff52cc64320c1f79f7d3659e2ee54a4aeed1cebb412eacd782f83ae2288c623e1a1256370262fd1afbb1a61d5e323d5bd679690105b597f027141d035a0f6ec4ef468d9a3ab39b9d54f1817878b745567f181b6678b9900299c11f21c92618da90cb10b2ecbef3d07a0b78cd35ddcc11d02e2e859f9296687268979557b99a9eaffd0875bdce1c03b1f507537916d0aba5aa437c3611ddf9e6975fc82545b67344a4f02125b08a27873079e4490519ec839a105638728d6b2dffa8024b6c4eb08dd793fbd7e53aac0e327401e1de38f826d7ac66beea3925232b0c7d086095a474b1c4f5dbb5651f5de1d1699b90bb500202673d867d00654244ece624c820d7a84db2c5e9515ace71158e45d52790a47b3b7c33ffda69b04dcf107a61a5bb0e6ab6bf06d6b44552d823f2b5969ccbe2f3986cb7180bf7acad66684117c391ff428a2023d7d29063766bb9fbb2c276c3067fab08c7fcf18fa3741b2bd409a58a4fc67d9cffde1faeb39dd86b21fa9b7930c2c6b8d28e4aeea263b3bec2bbc95b939c6ad208689204b83ea8eec2e90a42c0fde1ca8de5aaacd8a614328f83480b4a5bb5e12546ba0e56aef9e88d813dcc7c83f905c91bc5853b7d734a160f3e0efc10237aae97767abea0181c48861f2fabe52a38bcd7859d25ac5dc80eb457615d5064d77a81516b97f90c2feab7861dd9728d51a05247ef5defa05d77486812bd909195ef11c772b374d6cbe18a218af26aa19c72de077307567fa90b18eb1bc77a357ab09cc637b93d5d55793ea075285d60b04ca48bcdd45a32f55932358687db09440ff4ba255fa72e4dacee47e9029bfc16af51e121efdeb189b31dd5be103ef9dd2b5eac641768a81fce1056e6416cb8fc53b8fe946f8e37ab1f94520c3fb0d01dc15207cdec370b0fe76e5234343db30b2f8e0afdc50f1d52d761fbcd3dfcca053f01cfd3c43763546f9d5fc66e1adba7c9d66af0f61d27622f12372c4a75af5861151dcd2da571c7e90c7bde4dae9aea645f85c0781e4472e2b68d63d6789e3dc7ccb543ec47d68d1fa700c0081908a8d2e4687b6e826f4254bc169921b7e02643f3faa0264c7ff77a52205a9388d0a98c0394dc4dee81
	routing_info[0] (encrypted) = 0xe5f14350c2a76fc232b5e46d421e9615471ab9e0bc887beff8c95fdb878f7b3a71da571226458c510bbadd1276f045c21c520a07d35da256ef75b4367962437b0dd10f7d61ab590531cf08000178a333a347f8b4072e216400406bdf3bf038659793a86cae5f52d32f3438527b47a1cfc54285a8afec3a4c9f3323db0c946f5d4cb2ce721caad69320c3a469a202f3e468c67eaf7a7cda226d0fd32f7b48084dca885d15222e60826d5d971f64172d98e0760154400958f00e86697aa1aa9d41bee8119a1ec866abe044a9ad635778ba61fc0776dc832b39451bd5d35072d2269cf9b040d6ba38b54ec35f81d7fc67678c3be47274f3c4cc472aff005c3469eb3bc140769ed4c7f0218ff8c6c7dd7221d189c65b3b9aaa71a01484b122846c7c7b57e02e679ea8469b70e14fe4f70fee4d87b910cf144be6fe48eef24da475c0b0bcc6565ae82cd3f4e3b24c76eaa5616c6111343306ab35c1fe5ca4a77c0e314ed7dba39d6f1e0de791719c241a939cc493bea2bae1c1e932679ea94d29084278513c77b899cc98059d06a27d171b0dbdf6bee13ddc4fc17a0c4d2827d488436b57baa167544138ca2e64a11b43ac8a06cd0c2fba2d4d900ed2d9205305e2d7383cc98dacb078133de5f6fb6bed2ef26ba92cea28aafc3b9948dd9ae5559e8bd6920b8cea462aa445ca6a95e0e7ba52961b181c79e73bd581821df2b10173727a810c92b83b5ba4a0403eb710d2ca10689a35bec6c3a708e9e92f7d78ff3c5d9989574b00c6736f84c199256e76e19e78f0c98a9d580b4a658c84fc8f2096c2fbea8f5f8c59d0fdacb3be2802ef802abbecb3aba4acaac69a0e965abd8981e9896b1f6ef9d60f7a164b371af869fd0e48073742825e9434fc54da837e120266d53302954843538ea7c6c3dbfb4ff3b2fdbe244437f2a153ccf7bdb4c92aa08102d4f3cff2ae5ef86fab4653595e6a5837fa2f3e29f27a9cde5966843fb847a4a61f1e76c281fe8bb2b0a181d096100db5a1a5ce7a910238251a43ca556712eaadea167fb4d7d75825e440f3ecd782036d7574df8bceacb397abefc5f5254d2722215c53ff54af8299aaaad642c6d72a14d27882d9bbd539e1cc7a527526ba89b8c037ad09120e98ab042d3e8652b31ae0e478516bfaf88efca9f3676ffe99d2819dcaeb7610a626695f53117665d267d3f7abebd6bbd6733f645c72c389f03855bdf1e4b8075b516569b118233a0f0971d24b83113c0b096f5216a207ca99a7cddc81c130923fe3d91e7508c9ac5f2e914ff5dccab9e558566fa14efb34ac98d878580814b94b73acbfde9072f30b881f7f0fff42d4045d1ace6322d86a97d164aa84d93a60498065cc7c20e636f5862dc81531a88c60305a2e59a985be327a6902e4bed986dbf4a0b50c217af0ea7fdf9ab37f9ea1a1aaa72f54cf40154ea9b269f1a7c09f9f43245109431a175d50e2db0132337baa0ef97eed0fcf20489da36b79a1172faccc2f7ded7c60e00694282d93359c4682135642bc81f433574aa8ef0c97b4ade7ca372c5ffc23c7eddd839bab4e0f14d6df15c9dbeab176bec8b5701cf054eb3072f6dadc98f88819042bf10c407516ee58bce33fbe3b3d86a54255e577db4598e30a135361528c101683a5fcde7e8ba53f3456254be8f45fe3a56120ae96ea3773631fcb3873aa3abd91bcff00bd38bd43697a2e789e00da6077482e7b1b1a677b5afae4c54e6cbdf7377b694eb7d7a5b913476a5be923322d3de06060fd5e819635232a2cf4f0731da13b8546d1d6d4f8d75b9fce6c2341a71b0ea6f780df54bfdb0dd5cd9855179f602f9172
	hmac_data[0] = 0xe5f14350c2a76fc232b5e46d421e9615471ab9e0bc887beff8c95fdb878f7b3a71da571226458c510bbadd1276f045c21c520a07d35da256ef75b4367962437b0dd10f7d61ab590531cf08000178a333a347f8b4072e216400406bdf3bf038659793a86cae5f52d32f3438527b47a1cfc54285a8afec3a4c9f3323db0c946f5d4cb2ce721caad69320c3a469a202f3e468c67eaf7a7cda226d0fd32f7b48084dca885d15222e60826d5d971f64172d98e0760154400958f00e86697aa1aa9d41bee8119a1ec866abe044a9ad635778ba61fc0776dc832b39451bd5d35072d2269cf9b040d6ba38b54ec35f81d7fc67678c3be47274f3c4cc472aff005c3469eb3bc140769ed4c7f0218ff8c6c7dd7221d189c65b3b9aaa71a01484b122846c7c7b57e02e679ea8469b70e14fe4f70fee4d87b910cf144be6fe48eef24da475c0b0bcc6565ae82cd3f4e3b24c76eaa5616c6111343306ab35c1fe5ca4a77c0e314ed7dba39d6f1e0de791719c241a939cc493bea2bae1c1e932679ea94d29084278513c77b899cc98059d06a27d171b0dbdf6bee13ddc4fc17a0c4d2827d488436b57baa167544138ca2e64a11b43ac8a06cd0c2fba2d4d900ed2d9205305e2d7383cc98dacb078133de5f6fb6bed2ef26ba92cea28aafc3b9948dd9ae5559e8bd6920b8cea462aa445ca6a95e0e7ba52961b181c79e73bd581821df2b10173727a810c92b83b5ba4a0403eb710d2ca10689a35bec6c3a708e9e92f7d78ff3c5d9989574b00c6736f84c199256e76e19e78f0c98a9d580b4a658c84fc8f2096c2fbea8f5f8c59d0fdacb3be2802ef802abbecb3aba4acaac69a0e965abd8981e9896b1f6ef9d60f7a164b371af869fd0e48073742825e9434fc54da837e120266d53302954843538ea7c6c3dbfb4ff3b2fdbe244437f2a153ccf7bdb4c92aa08102d4f3cff2ae5ef86fab4653595e6a5837fa2f3e29f27a9cde5966843fb847a4a61f1e76c281fe8bb2b0a181d096100db5a1a5ce7a910238251a43ca556712eaadea167fb4d7d75825e440f3ecd782036d7574df8bceacb397abefc5f5254d2722215c53ff54af8299aaaad642c6d72a14d27882d9bbd539e1cc7a527526ba89b8c037ad09120e98ab042d3e8652b31ae0e478516bfaf88efca9f3676ffe99d2819dcaeb7610a626695f53117665d267d3f7abebd6bbd6733f645c72c389f03855bdf1e4b8075b516569b118233a0f0971d24b83113c0b096f5216a207ca99a7cddc81c130923fe3d91e7508c9ac5f2e914ff5dccab9e558566fa14efb34ac98d878580814b94b73acbfde9072f30b881f7f0fff42d4045d1ace6322d86a97d164aa84d93a60498065cc7c20e636f5862dc81531a88c60305a2e59a985be327a6902e4bed986dbf4a0b50c217af0ea7fdf9ab37f9ea1a1aaa72f54cf40154ea9b269f1a7c09f9f43245109431a175d50e2db0132337baa0ef97eed0fcf20489da36b79a1172faccc2f7ded7c60e00694282d93359c4682135642bc81f433574aa8ef0c97b4ade7ca372c5ffc23c7eddd839bab4e0f14d6df15c9dbeab176bec8b5701cf054eb3072f6dadc98f88819042bf10c407516ee58bce33fbe3b3d86a54255e577db4598e30a135361528c101683a5fcde7e8ba53f3456254be8f45fe3a56120ae96ea3773631fcb3873aa3abd91bcff00bd38bd43697a2e789e00da6077482e7b1b1a677b5afae4c54e6cbdf7377b694eb7d7a5b913476a5be923322d3de06060fd5e819635232a2cf4f0731da13b8546d1d6d4f8d75b9fce6c2341a71b0ea6f780df54bfdb0dd5cd9855179f602f91724242424242424242424242424242424242424242424242424242424242424242
	hmac[0] = 0x65f21f9190c70217774a6fbaaa7d63ad64199f4664813b955cff954949076dcf

### Final Packet

	onionpacket = 0x0002eec7245d6b7d2ccb30380bfbe2a3648cd7a942653f5aa340edcea1f283686619e5f14350c2a76fc232b5e46d421e9615471ab9e0bc887beff8c95fdb878f7b3a71da571226458c510bbadd1276f045c21c520a07d35da256ef75b4367962437b0dd10f7d61ab590531cf08000178a333a347f8b4072e216400406bdf3bf038659793a86cae5f52d32f3438527b47a1cfc54285a8afec3a4c9f3323db0c946f5d4cb2ce721caad69320c3a469a202f3e468c67eaf7a7cda226d0fd32f7b48084dca885d15222e60826d5d971f64172d98e0760154400958f00e86697aa1aa9d41bee8119a1ec866abe044a9ad635778ba61fc0776dc832b39451bd5d35072d2269cf9b040d6ba38b54ec35f81d7fc67678c3be47274f3c4cc472aff005c3469eb3bc140769ed4c7f0218ff8c6c7dd7221d189c65b3b9aaa71a01484b122846c7c7b57e02e679ea8469b70e14fe4f70fee4d87b910cf144be6fe48eef24da475c0b0bcc6565ae82cd3f4e3b24c76eaa5616c6111343306ab35c1fe5ca4a77c0e314ed7dba39d6f1e0de791719c241a939cc493bea2bae1c1e932679ea94d29084278513c77b899cc98059d06a27d171b0dbdf6bee13ddc4fc17a0c4d2827d488436b57baa167544138ca2e64a11b43ac8a06cd0c2fba2d4d900ed2d9205305e2d7383cc98dacb078133de5f6fb6bed2ef26ba92cea28aafc3b9948dd9ae5559e8bd6920b8cea462aa445ca6a95e0e7ba52961b181c79e73bd581821df2b10173727a810c92b83b5ba4a0403eb710d2ca10689a35bec6c3a708e9e92f7d78ff3c5d9989574b00c6736f84c199256e76e19e78f0c98a9d580b4a658c84fc8f2096c2fbea8f5f8c59d0fdacb3be2802ef802abbecb3aba4acaac69a0e965abd8981e9896b1f6ef9d60f7a164b371af869fd0e48073742825e9434fc54da837e120266d53302954843538ea7c6c3dbfb4ff3b2fdbe244437f2a153ccf7bdb4c92aa08102d4f3cff2ae5ef86fab4653595e6a5837fa2f3e29f27a9cde5966843fb847a4a61f1e76c281fe8bb2b0a181d096100db5a1a5ce7a910238251a43ca556712eaadea167fb4d7d75825e440f3ecd782036d7574df8bceacb397abefc5f5254d2722215c53ff54af8299aaaad642c6d72a14d27882d9bbd539e1cc7a527526ba89b8c037ad09120e98ab042d3e8652b31ae0e478516bfaf88efca9f3676ffe99d2819dcaeb7610a626695f53117665d267d3f7abebd6bbd6733f645c72c389f03855bdf1e4b8075b516569b118233a0f0971d24b83113c0b096f5216a207ca99a7cddc81c130923fe3d91e7508c9ac5f2e914ff5dccab9e558566fa14efb34ac98d878580814b94b73acbfde9072f30b881f7f0fff42d4045d1ace6322d86a97d164aa84d93a60498065cc7c20e636f5862dc81531a88c60305a2e59a985be327a6902e4bed986dbf4a0b50c217af0ea7fdf9ab37f9ea1a1aaa72f54cf40154ea9b269f1a7c09f9f43245109431a175d50e2db0132337baa0ef97eed0fcf20489da36b79a1172faccc2f7ded7c60e00694282d93359c4682135642bc81f433574aa8ef0c97b4ade7ca372c5ffc23c7eddd839bab4e0f14d6df15c9dbeab176bec8b5701cf054eb3072f6dadc98f88819042bf10c407516ee58bce33fbe3b3d86a54255e577db4598e30a135361528c101683a5fcde7e8ba53f3456254be8f45fe3a56120ae96ea3773631fcb3873aa3abd91bcff00bd38bd43697a2e789e00da6077482e7b1b1a677b5afae4c54e6cbdf7377b694eb7d7a5b913476a5be923322d3de06060fd5e819635232a2cf4f0731da13b8546d1d6d4f8d75b9fce6c2341a71b0ea6f780df54bfdb0dd5cd9855179f602f917265f21f9190c70217774a6fbaaa7d63ad64199f4664813b955cff954949076dcf

## Returning Errors

The same parameters (node IDs, shared secrets, etc.) as above are used.

	# node 4 is returning an error
	failure_message = 2002
	# creating error message
	shared_secret = b5756b9b542727dbafc6765a49488b023a725d631af688fc031217e90770c328
	payload = 0002200200fe0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000
	um_key = 4da7f2923edce6c2d85987d1d9fa6d88023e6c3a9c3d20f07d3b10b61a78d646
	raw_error_packet = 4c2fc8bc08510334b6833ad9c3e79cd1b52ae59dfe5c2a4b23ead50f09f7ee0b0002200200fe0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000
	# forwarding error packet
	shared_secret = b5756b9b542727dbafc6765a49488b023a725d631af688fc031217e90770c328
	 ammag_key = 2f36bb8822e1f0d04c27b7d8bb7d7dd586e032a3218b8d414afbba6f169a4d68
	stream = e9c975b07c9a374ba64fd9be3aae955e917d34d1fa33f2e90f53bbf4394713c6a8c9b16ab5f12fd45edd73c1b0c8b33002df376801ff58aaa94000bf8a86f92620f343baef38a580102395ae3abf9128d1047a0736ff9b83d456740ebbb4aeb3aa9737f18fb4afb4aa074fb26c4d702f42968888550a3bded8c05247e045b866baef0499f079fdaeef6538f31d44deafffdfd3afa2fb4ca9082b8f1c465371a9894dd8c243fb4847e004f5256b3e90e2edde4c9fb3082ddfe4d1e734cacd96ef0706bf63c9984e22dc98851bcccd1c3494351feb458c9c6af41c0044bea3c47552b1d992ae542b17a2d0bba1a096c78d169034ecb55b6e3a7263c26017f033031228833c1daefc0dedb8cf7c3e37c9c37ebfe42f3225c326e8bcfd338804c145b16e34e4
	error packet for node 4: a5e6bd0c74cb347f10cce367f949098f2457d14c046fd8a22cb96efb30b0fdcda8cb9168b50f2fd45edd73c1b0c8b33002df376801ff58aaa94000bf8a86f92620f343baef38a580102395ae3abf9128d1047a0736ff9b83d456740ebbb4aeb3aa9737f18fb4afb4aa074fb26c4d702f42968888550a3bded8c05247e045b866baef0499f079fdaeef6538f31d44deafffdfd3afa2fb4ca9082b8f1c465371a9894dd8c243fb4847e004f5256b3e90e2edde4c9fb3082ddfe4d1e734cacd96ef0706bf63c9984e22dc98851bcccd1c3494351feb458c9c6af41c0044bea3c47552b1d992ae542b17a2d0bba1a096c78d169034ecb55b6e3a7263c26017f033031228833c1daefc0dedb8cf7c3e37c9c37ebfe42f3225c326e8bcfd338804c145b16e34e4
	# forwarding error packet
	shared_secret = 21e13c2d7cfe7e18836df50872466117a295783ab8aab0e7ecc8c725503ad02d
	ammag_key = cd9ac0e09064f039fa43a31dea05f5fe5f6443d40a98be4071af4a9d704be5ad
	stream = 617ca1e4624bc3f04fece3aa5a2b615110f421ec62408d16c48ea6c1b7c33fe7084a2bd9d4652fc5068e5052bf6d0acae2176018a3d8c75f37842712913900263cff92f39f3c18aa1f4b20a93e70fc429af7b2b1967ca81a761d40582daf0eb49cef66e3d6fbca0218d3022d32e994b41c884a27c28685ef1eb14603ea80a204b2f2f474b6ad5e71c6389843e3611ebeafc62390b717ca53b3670a33c517ef28a659c251d648bf4c966a4ef187113ec9848bf110816061ca4f2f68e76ceb88bd6208376460b916fb2ddeb77a65e8f88b2e71a2cbf4ea4958041d71c17d05680c051c3676fb0dc8108e5d78fb1e2c44d79a202e9d14071d536371ad47c39a05159e8d6c41d17a1e858faaaf572623aa23a38ffc73a4114cb1ab1cd7f906c6bd4e21b29694
	error packet for node 3: c49a1ce81680f78f5f2000cda36268de34a3f0a0662f55b4e837c83a8773c22aa081bab1616a0011585323930fa5b9fae0c85770a2279ff59ec427ad1bbff9001c0cd1497004bd2a0f68b50704cf6d6a4bf3c8b6a0833399a24b3456961ba00736785112594f65b6b2d44d9f5ea4e49b5e1ec2af978cbe31c67114440ac51a62081df0ed46d4a3df295da0b0fe25c0115019f03f15ec86fabb4c852f83449e812f141a9395b3f70b766ebbd4ec2fae2b6955bd8f32684c15abfe8fd3a6261e52650e8807a92158d9f1463261a925e4bfba44bd20b166d532f0017185c3a6ac7957adefe45559e3072c8dc35abeba835a8cb01a71a15c736911126f27d46a36168ca5ef7dccd4e2886212602b181463e0dd30185c96348f9743a02aca8ec27c0b90dca270
	forwarding error packet
	shared_secret = 3a6b412548762f0dbccce5c7ae7bb8147d1caf9b5471c34120b30bc9c04891cc
	ammag_key = 1bf08df8628d452141d56adfd1b25c1530d7921c23cecfc749ac03a9b694b0d3
	stream = 6149f48b5a7e8f3d6f5d870b7a698e204cf64452aab4484ff1dee671fe63fd4b5f1b78ee2047dfa61e3d576b149bedaf83058f85f06a3172a3223ad6c4732d96b32955da7d2feb4140e58d86fc0f2eb5d9d1878e6f8a7f65ab9212030e8e915573ebbd7f35e1a430890be7e67c3fb4bbf2def662fa625421e7b411c29ebe81ec67b77355596b05cc155755664e59c16e21410aabe53e80404a615f44ebb31b365ca77a6e91241667b26c6cad24fb2324cf64e8b9dd6e2ce65f1f098cfd1ef41ba2d4c7def0ff165a0e7c84e7597c40e3dffe97d417c144545a0e38ee33ebaae12cc0c14650e453d46bfc48c0514f354773435ee89b7b2810606eb73262c77a1d67f3633705178d79a1078c3a01b5fadc9651feb63603d19decd3a00c1f69af2dab259593
	error packet for node 2: a5d3e8634cfe78b2307d87c6d90be6fe7855b4f2cc9b1dfb19e92e4b79103f61ff9ac25f412ddfb7466e74f81b3e545563cdd8f5524dae873de61d7bdfccd496af2584930d2b566b4f8d3881f8c043df92224f38cf094cfc09d92655989531524593ec6d6caec1863bdfaa79229b5020acc034cd6deeea1021c50586947b9b8e6faa83b81fbfa6133c0af5d6b07c017f7158fa94f0d206baf12dda6b68f785b773b360fd0497e16cc402d779c8d48d0fa6315536ef0660f3f4e1865f5b38ea49c7da4fd959de4e83ff3ab686f059a45c65ba2af4a6a79166aa0f496bf04d06987b6d2ea205bdb0d347718b9aeff5b61dfff344993a275b79717cd815b6ad4c0beb568c4ac9c36ff1c315ec1119a1993c4b61e6eaa0375e0aaf738ac691abd3263bf937e3
	# forwarding error packet
	shared_secret = a6519e98832a0b179f62123b3567c106db99ee37bef036e783263602f3488fae
	ammag_key = 59ee5867c5c151daa31e36ee42530f429c433836286e63744f2020b980302564
	stream = 0f10c86f05968dd91188b998ee45dcddfbf89fe9a99aa6375c42ed5520a257e048456fe417c15219ce39d921555956ae2ff795177c63c819233f3bcb9b8b28e5ac6e33a3f9b87ca62dff43f4cc4a2755830a3b7e98c326b278e2bd31f4a9973ee99121c62873f5bfb2d159d3d48c5851e3b341f9f6634f51939188c3b9ff45feeb11160bb39ce3332168b8e744a92107db575ace7866e4b8f390f1edc4acd726ed106555900a0832575c3a7ad11bb1fe388ff32b99bcf2a0d0767a83cf293a220a983ad014d404bfa20022d8b369fe06f7ecc9c74751dcda0ff39d8bca74bf9956745ba4e5d299e0da8f68a9f660040beac03e795a046640cf8271307a8b64780b0588422f5a60ed7e36d60417562938b400802dac5f87f267204b6d5bcfd8a05b221ec2
	error packet for node 1: aac3200c4968f56b21f53e5e374e3a2383ad2b1b6501bbcc45abc31e59b26881b7dfadbb56ec8dae8857add94e6702fb4c3a4de22e2e669e1ed926b04447fc73034bb730f4932acd62727b75348a648a1128744657ca6a4e713b9b646c3ca66cac02cdab44dd3439890ef3aaf61708714f7375349b8da541b2548d452d84de7084bb95b3ac2345201d624d31f4d52078aa0fa05a88b4e20202bd2b86ac5b52919ea305a8949de95e935eed0319cf3cf19ebea61d76ba92532497fcdc9411d06bcd4275094d0a4a3c5d3a945e43305a5a9256e333e1f64dbca5fcd4e03a39b9012d197506e06f29339dfee3331995b21615337ae060233d39befea925cc262873e0530408e6990f1cbd233a150ef7b004ff6166c70c68d9f8c853c1abca640b8660db2921
	# forwarding error packet
	shared_secret = 53eb63ea8a3fec3b3cd433b85cd62a4b145e1dda09391b348c4e1cd36a03ea66
	ammag_key = 3761ba4d3e726d8abb16cba5950ee976b84937b61b7ad09e741724d7dee12eb5
	stream = 3699fd352a948a05f604763c0bca2968d5eaca2b0118602e52e59121f050936c8dd90c24df7dc8cf8f1665e39a6c75e9e2c0900ea245c9ed3b0008148e0ae18bbfaea0c711d67eade980c6f5452e91a06b070bbde68b5494a92575c114660fb53cf04bf686e67ffa4a0f5ae41a59a39a8515cb686db553d25e71e7a97cc2febcac55df2711b6209c502b2f8827b13d3ad2f491c45a0cafe7b4d8d8810e805dee25d676ce92e0619b9c206f922132d806138713a8f69589c18c3fdc5acee41c1234b17ecab96b8c56a46787bba2c062468a13919afc18513835b472a79b2c35f9a91f38eb3b9e998b1000cc4a0dbd62ac1a5cc8102e373526d7e8f3c3a1b4bfb2f8a3947fe350cb89f73aa1bb054edfa9895c0fc971c2b5056dc8665902b51fced6dff80c
	error packet for node 0: 9c5add3963fc7f6ed7f148623c84134b5647e1306419dbe2174e523fa9e2fbed3a06a19f899145610741c83ad40b7712aefaddec8c6baf7325d92ea4ca4d1df8bce517f7e54554608bf2bd8071a4f52a7a2f7ffbb1413edad81eeea5785aa9d990f2865dc23b4bc3c301a94eec4eabebca66be5cf638f693ec256aec514620cc28ee4a94bd9565bc4d4962b9d3641d4278fb319ed2b84de5b665f307a2db0f7fbb757366067d88c50f7e829138fde4f78d39b5b5802f1b92a8a820865af5cc79f9f30bc3f461c66af95d13e5e1f0381c184572a91dee1c849048a647a1158cf884064deddbf1b0b88dfe2f791428d0ba0f6fb2f04e14081f69165ae66d9297c118f0907705c9c4954a199bae0bb96fad763d690e7daa6cfda59ba7f2c8d11448b604d12d

# References

# Authors

[ FIXME: ]

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).


[sphinx]: http://www.cypherpunks.ca/~iang/pubs/Sphinx_Oakland09.pdf
[RFC2104]: https://tools.ietf.org/html/rfc2104
[fips198]: http://csrc.nist.gov/publications/fips/fips198-1/FIPS-198-1_final.pdf
[sec2]: http://www.secg.org/sec2-v2.pdf
[rfc7539]: https://tools.ietf.org/html/rfc7539
