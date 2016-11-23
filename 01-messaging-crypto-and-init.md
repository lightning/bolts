# BOLT #1: Message Format, Encryption, Authentication and Initialization

All communications between Lightning nodes should be encrypted in order to
provide confidentiality for all transcripts between nodes, and authenticated to
avoid malicious interference. Each node has a known long-term identifier which
is a public key on Bitcoin's `secp256k1` curve. This long-term public key is
used within the protocol to establish an encrypted+authenticated connection
with peers, and also to authenticate any information advertised on the behalf
of a node.

## Communication Protocols

This protocol is written with TCP in mind, but could use any ordered,
reliable transport.

The default TCP port is `9735`.  This corresponds to hexadecimal `2607`,
the unicode code point for LIGHTNING.<sup>[2](#reference-2)</sup>

## Message Format and Handling

All messages are of form:

1. `4-byte` big-endian data length.
2. `4-byte` big-endian type.
3. Data bytes as specified by the length.

All data fields are big-endian unless otherwise specified.

### Requirements

A node MUST NOT send a message with data length greater than `8388608`
bytes.  A node MUST NOT send an evenly-typed message not listed here
without prior negotiation.

A node MUST disconnect if it receives a message with data length
greater than `8388608` bytes; it MUST NOT fail the channels in that case.

A node MUST ignore a received message of unknown type, if that type is
odd.  A node MUST fail the channels if it receives a message of unknown
type, if that type is even.

A node MUST ignore any additional data within a message, beyond the
length it expects for that type.

### Rationale

The standard endian of `SHA2` and the encoding of bitcoin public keys
are big endian, thus it would be unusual to use a different endian for
other fields.

Length is limited to avoid memory exhaustion attacks, yet still allow
(for example) an entire bitcoin block to be comfortable forwarded as a
reasonable upper limit.

The "it's OK to be odd" rule allows for future optional extensions
without negotiation or special coding in clients.  The "ignore
additional data" rule similarly allows for future expansion.

## Cryptographic Messaging Overview

Prior to sending any protocol related messages, nodes must first initiate the
cryptographic session state which is used to encrypt and authenticate all
messages sent between nodes. The initialization of this cryptographic session
state is completely distinct from any inner protocol message header or
conventions.

The transcript between two nodes is separated into two distinct segments:

1. First, before any actual data transfer, both nodes participate in an
   authenticated key agreement protocol which is based off of the Noise
   Protocol Framework<sup>[4](#reference-4)</sup>.
2. If the initial handshake is successful, then nodes enter the transport
   message exchange phase. In the transport message exchange phase, all
   messages are `AEAD` ciphertexts.

### Authenticated Key Agreement Handshake

The handshake chosen for the authenticated key exchange is `Noise_XK`. As a
"pre-message", we assume that the initiator knows the identity public key of
the responder. This handshake provides a degree of identity hiding for the
responder, its public key is _never_ transmitted during the handshake. Instead,
authentication is achieved implicitly via a series of `ECDH` operations followed
by a `MAC` check.

The authenticated key agreement (`Noise_XK`) is performed in three distinct
steps. During each "act" of the handshake, some (possibly encrypted) keying
material is sent to the other party, an `ECDH` is performed based on exactly
which act is being executed with the result mixed into the current sent of
encryption keys (`ck` and `k`), and finally an `AEAD` payload with a zero
length cipher text is sent.  As this payload is of length zero, only a `MAC` is
sent across.  The mixing of `ECDH` outputs into a hash digest forms an
incremental TripleDH handshake.

Using the language of the Noise Protocol, `e` and `s` indicate possibly
encrypted keying material, and `es, ee, se` indicates `ECDH` operations.  The
handshake is laid out as follows:

    Noise_XK(s, rs):
       <- s
       ...
       -> e, es
       <- e, ee
       -> s, se

All of the handshake data sent across the wire including the keying material is
incrementally hashed into a session-wide "handshake digest", `h`. Note that the
handshake state `h`, is never transmitted during the handshake, instead digest
is used as the Authenticated Data within the zero-length AEAD messages.

By authenticating each message sent, we can ensure that a MiTM hasn't modified
or replaced any of the data sent across as part of a handshake, as the MAC
check would fail on the other side if so.

A successful check of the `MAC` by the receiver indicates implicitly that all
authentication has been successful up to that point. If `MAC` check ever fails
during the handshake process, then the connection is to be immediately
terminated.

## Handshake Versioning

Each message sent during the initial handshake starts with a single leading
byte which indicates the version used for the current handshake. A version of 0
indicates that no change is necessary, while a non-zero version indicate the
client has deviated from the protocol originally specified within this
document. Clients MUST reject handshake attempts initiated with an unknown
version.

### Transport Message Exchange

The actual protocol messages sent during the transport message exchange phase
are encapsulated within `AEAD` ciphertexts. Each message is prefixed with
another `AEAD` ciphertext which encodes the total length of the next transport
message.  The length prefix itself is protected with a MAC in order to avoid
the creation of an oracle and to also prevent a MiTM from modifying the length
prefix thereby causing a node to erroneously read an incorrect number of bytes.


## Protocol Message Encapsulation

Once both sides have entered the transport message exchange phase (after a
successful completion of the handshake), Lightning Network protocol messages
will be encapsulated within the exchanged `AEAD` ciphertexts. The maximum size
of transport messages is `65535-bytes`. Node MUST NOT send a transport message
which exceeds this size. Note that this is only a cryptographic messaging limit
within the protocol, and not a limit on the message size of Lightning Network
protocol messages. A Lightning Network message which exceeds this size can be
chunked into several messages before being sent.

### Noise Protocol Instantiation

Concrete instantiations of the Noise Protocol are require the definition of
three abstract cryptographic objects: the hash function, the elliptic curve,
and finally the `AEAD` cipher scheme. Within our instantiation `SHA-256` is
chosen as the hash function, `secp256k1` as the elliptic curve, and finally
`ChaChaPoly-1305` as the `AEAD` construction. The composition of `ChaChaPoly`
and `Poly1305` used MUST conform to `RFC 7539`<sup>[3](#reference-3)</sup>. With this laid out, the
official Noise protocol name for our variant is:
`Noise_XK_secp256k1_ChaChaPoly_SHA256`.  The ascii string representation of
this value is hashed into a digest used to initialize the starting handshake
state. If the protocol names of two endpoints differs, then the handshake
process fails immediately.


## Authenticated Key Exchange Handshake Specification

The handshake proceeds in three acts, taking 1.5 round trips. Each handshake is
a _fixed_ sized payload without any header or additional meta-data attached.
The exact size of each Act is as follows:

   * **Act One**: `50 bytes`
   * **Act Two**: `50 bytes`
   * **Act Three**: `66 bytes`

### Handshake State

Throughout the handshake process, each side maintains these three variables:

 * `ck`: The **chaining key**. This value is the accumulated hash of all
   previous ECDH outputs. At the end of the handshake, `ck` is used to derive
   the encryption keys for transport messages.

 * `h`: The **handshake hash**. This value is the accumulated hash of _all_
   handshake data that has been sent and received so far during the handshake
   process.

 * `temp_k`: An **intermediate key** key used to encrypt/decrypt the
   zero-length AEAD payloads at the end of each handshake message.

 * `n`: A **counter-based nonce** which is to be used with `temp_k` to encrypt
   each message with a new nonce.

 * `e`: A party's **ephemeral public key**. For each session a node MUST generate a
   new ephemeral key with strong cryptographic randomness.

 * `s`: A party's **static public key**.

The following functions will also be referenced:

  * `HKDF`: a function is defined in [3](#reference-3), evaluated with a zero-length `info`
    field.

  * `encryptWithAD(ad, plaintext)`: outputs `encrypt(k, n++, ad, plaintext)`
     * where `encrypt` is an evaluation of `ChaChaPoly-Poly1305` with the
       passed arguments.

  * `decryptWithAD(ad, ciphertext)`: outputs `decrypt(k, n++, ad, ciphertext)`
     * where `decrypt` is an evaluation of `ChaChaPoly-Poly1305` with the
       passed arguments.

  * `e = generateKey()`
     * where generateKey generates a fresh secp256k1 keypair

  * `a || b` denotes the concatenation of two byte strings `a` and `b`


### Handshake State Initialization

Before the start of the first act, both sides initialize their per-sessions
state as follows:

 * `h = SHA-256(protocolName)`
    * where `protocolName = "Noise_XK_secp256k1_ChaChaPoly_SHA256"` encoded as
      an ascii string.

 * `ck = h`


 * `temp_k = empty`
    * where `empty` is a byte string of length 32 fully zeroed out.


 * `n = 0`


 * `h = SHA-256(h || prologue)`
    * where `prologue` is the ascii string: `lightning`.


As a concluding step, both sides mix the responder's public key into the
handshake digest:


 * The initiating node mixes in the responding node's static public key
   serialized in Bitcoin's DER compressed format:
   * `h = SHA-256(h || rs.serializeCompressed())`


 * The responding node mixes in their local static public key serialized in
   Bitcoin's DER compressed format:
   * `h = SHA-256(h || ls.serializeCompressed())`


### Handshake Exchange


#### Act One


```
    -> e, es
```


Act One is sent from initiator to responder. During `Act One`, the initiator
attempts to satisfy an implicit challenge by the responder. To complete this
challenge, the initiator _must_ know the static public key of the responder.


The handshake message is _exactly_ `50 bytes`: `1 byte` for the handshake
version, `33 bytes` for the compressed ephemeral public key of the initiator,
and `16 bytes` for the `poly1305` tag.


**Sender Actions:**


  * `e = generateKey()`


  * `h = SHA-256(h || e.serializeCompressed())`
     * The newly generated ephemeral key is accumulated into our running
       handshake digest.


  * `s = ECDH(e, rs)`
     * The initiator performs a ECDH between its newly generated ephemeral key
       with the remote node's static public key.


  * `ck, temp_k = HKDF(ck, s)`
     * This phase generates a new temporary encryption key (`temp_k`) which is
       used to generate the authenticating MAC.


  * `c = encryptWithAD(h, zero)`
     * where `zero` is a zero-length plaintext


  * `h = SHA-256(h || c)`
     * Finally, the generated ciphertext is accumulated into the authenticating
       handshake digest.


  * Send `m = 0 || e || c` to the responder over the network buffer.


**Receiver Actions:**


  * Read _exactly_ `50-bytes` from the network buffer.


  * Parse out the read message (`m`) into `v = m[0]`, `e = m[1:34]` and `c = m[43:]`
    * where `m[0]` is the _first_ byte of `m`, `m[1:33]` are the next `33`
      bytes of `m` and `m[34:]` is the last 16 bytes of `m`


  * If `v` is an unrecognized handshake version, then the the responder MUST
    abort the connection attempt.


  * `h = SHA-256(h || e.serializeCompressed())`
    * Accumulate the initiator's ephemeral key into the authenticating
      handshake digest.

  * `s = ECDH(s, e)`
    * The responder performs an ECDH between its static public key and the
      initiator's ephemeral public key.


  * `ck, temp_k = HKDF(ck, s)`
    * This phase generates a new temporary encryption key (`temp_k`) which will
      be used to shortly check the authenticating MAC.


  * `p = decryptWithAD(h, c)`
    * If the MAC check in this operation fails, then the initiator does _not_
      know our static public key. If so, then the responder MUST terminate the
      connection without any further messages.


  * `h = SHA-256(h || c)`
     * Mix the received ciphertext into the handshake digest. This step serves
       to ensure the payload wasn't modified by a MiTM.




#### Act Two
```
   <- e, ee
```

`Act Two` is sent from the responder to the initiator. `Act Two` will _only_
take place if `Act One` was successful. `Act One` was successful if the
responder was able to properly decrypt and check the `MAC` of the tag sent at
the end of `Act One`.

The handshake is _exactly_ `50 bytes:` `1 byte` for the handshake version, `33
bytes` for the compressed ephemeral public key of the initiator, and `16 bytes`
for the `poly1305` tag.

**Sender Actions:**


  * `e = generateKey()`


  * `h = SHA-256(h || e.serializeCompressed())`
     * The newly generated ephemeral key is accumulated into our running
       handshake digest.


  * `s = ECDH(e, re)`
     * where `re` is the ephemeral key of the initiator which was received
       during `ActOne`.


  * `ck, temp_k = HKDF(ck, s)`
     * This phase generates a new temporary encryption key (`temp_k`) which is
       used to generate the authenticating MAC.


  * `c = encryptWithAD(h, zero)`
     * where `zero` is a zero-length plaintext


  * `h = SHA-256(h || c)`
     * Finally, the generated ciphertext is accumulated into the authenticating
       handshake digest.

  * Send `m = 0 || e || c` to the initiator over the network buffer.


**Receiver Actions:**


  * Read _exactly_ `50-bytes` from the network buffer.


  * Parse out the read message (`m`) into `v = m[0]`, e = m[1:34]` and `c = m[43:]`
    * where `m[0]` is the _first_ byte of `m`, `m[1:33]` are the next `33`
      bytes of `m` and `m[34:]` is the last 16 bytes of `m`


  * If `v` is an unrecognized handshake version, then the the responder MUST
    abort the connection attempt.


  * `h = SHA-256(h || e.serializeCompressed())`


  * `s = ECDH(re, e)`
     * where `re` is the responder's ephemeral public key.


  * `ck, temp_k = HKDF(ck, s)`
     * This phase generates a new temporary encryption key (`temp_k`) which is
       used to generate the authenticating MAC.


  * `p = decryptWithAD(h, c)`
    * If the MAC check in this operation fails, then the initiator MUST
      terminate the connection without any further messages.


  * `h = SHA-256(h || c)`
     * Mix the received ciphertext into the handshake digest. This step serves
       to ensure the payload wasn't modified by a MiTM.


#### Act Three
```
   -> s, se
```


`Act Three` is the final phase in the authenticated key agreement described in
this section. This act is sent from the initiator to the responder as a final
concluding step. `Act Three` is only executed `iff` `Act Two` was successful.
During `Act Three`, the initiator transports its static public key to the
responder encrypted with _strong_ forward secrecy using the accumulated `HKDF`
derived secret key at this point of the handshake.


The handshake is _exactly_ `66 bytes`: `1 byte` for the handshake version, `33
bytes` for the ephemeral public key encrypted with the `ChaCha20` stream
cipher, `16 bytes` for the encrypted public key's tag generated via the `AEAD`
construction, and `16 bytes` for a final authenticating tag.


**Sender Actions:**


  * `c = encryptWithAD(h, s.serializeCompressed())`
    * where `s` is the static public key of the initiator.


  * `h = SHA-256(h || c)`


  * `s = ECDH(s, re)`
    * where `re` is the ephemeral public key of the responder.


  * `ck, temp_k = HKDF(ck, s)`
    * Mix the finaly intermediate shared secret into the running chaining key.


  * `t = encryptWithAD(h, zero)`
     * where `zero` is a zero-length plaintext


  * `h = SHA-256(h || t)`


  * `sk, rk = HKDF(ck, zero)`
     * where `zero` is a zero-length plaintext,


       `sk` is the key to be used by the initiator to encrypt messages to the
       responder,


       and `rk` is the key to be used by the initiator to decrypt messages sent by
       the responder.

     * This step generates the final encryption keys to be used for sending and
       receiving messages for the duration of the session.


  * Send `m = 0 || c || t` over the network buffer.


**Receiver Actions:**


  * Read _exactly_ `66-bytes` from the network buffer.


  * Parse out the read message (`m`) into `v = m[0]`, `c = m[1:50]` and `t = m[50:]`


  * If `v` is an unrecognized handshake version, then the the responder MUST
    abort the connection attempt.


  * `rs = decryptWithAD(h, c)
     * At this point, the responder has recovered the static public key of the
       initiator.


  * `h = SHA-256(h || rs.serializeCompressed())`


  * `s = ECDH(e, rs)`
     * where `e` is the responder's original ephemeral key


  * `p = decryptWithAD(h, t)`
     * If the MAC check in this operation fails, then the responder MUST
       terminate the connection without any further messages.


  * `rk, sk = HKDF(ck, zero)`
     * where `zero` is a zero-length plaintext,


       `rk` is the key to be used by the responder to decrypt the messages sent
       by the responder,


       and `sk` is the key to be used by the initiator to encrypt messages to
       the responder,

     * This step generates the final encryption keys to be used for sending and
       receiving messages for the duration of the session.


## Transport Message Specification

At the conclusion of `Act Three` both sides have derived the encryption keys
which will be used to encrypt/decrypt messages for the remainder of the
session.

The *maximum* size of _any_ transport message MUST NOT exceed 65535 bytes. A
maximum payload size of 65535 simplifies testing and also makes memory
management and avoid exhaustion attacks easy. Note that the protocol messages
encapsulated in within the encrypted transport messages can be larger that the
maximum transport messages. If a party wishes to send a message larger then
65535 bytes, then they can simply partition the message into chunks less than
the maximum size, sending each of them sequentially. Messages which exceed the
max message size MUST be partitioned into chunks of size `65519 bytes`, in
order to leave room for the `16-byte` `MAC`.


In order to make make traffic analysis more difficult, then length prefix for
all encrypted transport messages is also encrypted. We additionally add a
`16-byte` `Poly-1305` tag to the encrypted length prefix in order to ensure
that the packet length hasn't been modified with in-flight, and also to avoid
creating a decryption oracle.


The structure of transport messages resembles the following:
```
+------------------------------
|2-byte encrypted packet length|
+------------------------------
| 16-byte MAC of the encrypted |
|        packet length         |
+------------------------------
|                              |
|                              |
|          ciphertext          |
|                              |
|                              |
+------------------------------
```

The prefixed packet lengths are encoded as a `16-byte` big-endian integer.


### Encrypting Messages


In order to encrypt a message (`m`), given a sending key (`sk`), and a nonce
(`n`), the following is done:


  * let `l = len(m)`,
     where `len` obtains the length in bytes of the message.


  * Serialize `l` into `2-bytes` encoded as a big-endian integer.


  * Encrypt `l` using `ChaChaPoly-1305`, `n`, and `sk` to obtain `lc`
    (`18-bytes`)
    * The nonce for `sk MUST be incremented after this step.


  * Finally encrypt the message itself (`m`) using the same procedure used to
    encrypt the length prefix. Let encrypted ciphertext be known as `c`.
    * The nonce for `sk` MUST be incremented after this step.

  * Send `lc || c` over the network buffer.


### Decrypting Messages


In order to decrypt the _next_ message in the network stream, the following is
done:


  * Read _exactly_ `18-bytes` from the network buffer.


  * Let the encrypted length prefix be known as `lc`


  * Decrypt `lc` using `ChaChaPoly-1305`, `n`, and `rk` to obtain size of the
    encrypted packet `l`.
    * The nonce for `rk` MUST be incremented after this step.


  * Read _exactly_ `l` bytes from the network buffer, let the bytes be known as
    `c`.


  * Decrypt `c` using `ChaChaPoly-1305`, `n`, and `rk` to obtain decrypted
    plaintext packet `p`.


    * The nonce for `rk` MUST be incremented after this step.


## Transport Message Key Rotation


Changing keys regularly and forgetting the previous key is useful for
preventing decryption of old messages in the case of later key leakage (ie.
backwards secrecy).


Key rotation is performed for _each_ key (`sk` and `rk`) _individually _. A key
is to be rotated after a party sends of decrypts `1000` messages with it.
This can be properly accounted for by rotating the key once the nonce dedicated
to it exceeds `1000`.


Key rotation for a key `k` is performed according to the following:


  * Let `ck` be the chaining key obtained at the end of `Act Three`.
  * `ck, k' = HKDF(ck, k)`
     * The underscore indicates that only `32-bytes` are extracted from the
       `HKDF`.
  * Reset the nonce for the key to `n = 0`.
  * `k = k'`




## Future Directions


Protocol messages may be padded out to the full maximum message length in order
to max traffic analysis even more difficult.

The initial handshake message may also be padded out to a fixed size in order
to obscure exactly which of the Noise handshakes is being executed.

In order to allow zero-RTT encrypted+authenticated communication, a Noise Pipes
protocol can be adopted which composes two handshakes, potentially falling back
to a full handshake if static public keys have changed.

## Initialization Message

Once authentication is complete, the first message reveals the
features supported or required by this node.  Odd features are
optional, even features are compulsory ("it's OK to be odd!").  The
meaning of these bits will be defined in future.

1. type: 16 (`init`)
2. data:
   * [4:gflen]
   * [gflen:globalfeatures]
   * [4:lflen]
   * [lflen:localfeatures]

The 4-byte len fields indicate the number of bytes in the immediately
following field.


### Requirements


The sending node SHOULD use the minimum lengths required to represent
the feature fields.  The sending node MUST set feature bits
corresponding to features is requires the peer to support, and SHOULD
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


## Error Message


For simplicity of diagnosis, it is often useful to tell the peer that
something is incorrect.


1. type: 17 (`error`)
2. data:
   * [8:channel-id]
   * [4:len]
   * [len:data]

The 4-byte len field indicates the number of bytes in the immediately
following field.


### Requirements


A node SHOULD send `error` for protocol violations or internal
errors which make channels unusable or further communication unusable.
A node MAY send an empty [data] field.  A node sending `error` MUST
fail the channel referred to by the `channel-id`, or if `channel-id`
is 0xFFFFFFFFFFFFFFFF it MUST fail all channels and MUST close the
connection. A node MUST NOT set `len` to greater than the data length.


A node receiving `error` MUST fail the channel referred to by
`channel-id`, or if `channel-id` is 0xFFFFFFFFFFFFFFFF it MUST fail
all channels and MUST close the connection.  A receiving node MUST truncate `len` to the remainder of the packet if it is larger.


A receiving node SHOULD only print out `data` verbatim if it is a
valid string.


### Rationale


There are unrecoverable errors which require abort of conversations;
if the connection is simply dropped then the peer may retry
connection.  It's also useful to describe protocol violations for
diagnosis, as it indicates that one peer has a bug.


It may be wise not to distinguish errors in production settings, lest
it leak information, thus the optional data field.


# Security Considerations #


It is strongly recommended that existing, commonly-used, validated
libraries be used for encryption and decryption, to avoid the many
implementation pitfalls possible.

## Acknowledgements

TODO(roasbeef); fin


# References
1. <a id="reference-1">https://en.bitcoin.it/wiki/Secp256k1</a>
2. <a id="reference-2">http://www.unicode.org/charts/PDF/U2600.pdf</a>
3. <a id="reference-3">https://tools.ietf.org/html/rfc7539</a>
4. <a id="reference-4">http://noiseprotocol.org/noise.html</a>

# Authors

FIXME
