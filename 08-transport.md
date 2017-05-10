# BOLT #8: Encrypted and Authenticated Transport

All communications between Lightning nodes is encrypted in order to
provide confidentiality for all transcripts between nodes, and authenticated to
avoid malicious interference. Each node has a known long-term identifier which
is a public key on Bitcoin's `secp256k1` curve. This long-term public key is
used within the protocol to establish an encrypted+authenticated connection
with peers, and also to authenticate any information advertised on behalf
of a node.

## Cryptographic Messaging Overview

Prior to sending any lightning messages, nodes must first initiate the
cryptographic session state which is used to encrypt and authenticate all
messages sent between nodes. The initialization of this cryptographic session
state is completely distinct from any inner protocol message header or
conventions.

The transcript between two nodes is separated into two distinct segments:

1. First, before any actual data transfer, both nodes participate in an
   authenticated key agreement protocol which is based off of the Noise
   Protocol Framework<sup>[2](#reference-2)</sup>.
2. If the initial handshake is successful, then nodes enter the lightning
   message exchange phase. In the lightning message exchange phase, all
   messages are `AEAD` ciphertexts.

### Authenticated Key Agreement Handshake

The handshake chosen for the authenticated key exchange is `Noise_XK`. As a
"pre-message", we assume that the initiator knows the identity public key of
the responder. This handshake provides a degree of identity hiding for the
responder, its public key is _never_ transmitted during the handshake. Instead,
authentication is achieved implicitly via a series of `ECDH` (Elliptic-Curve
Diffie-Hellman) operations followed by a `MAC` check.

The authenticated key agreement (`Noise_XK`) is performed in three distinct
steps. During each "act" of the handshake, some (possibly encrypted) keying
material is sent to the other party, an `ECDH` is performed based on exactly
which act is being executed with the result mixed into the current sent of
encryption keys (`ck` the chaining key and `k` the encryption key), and finally
an `AEAD` payload with a zero length cipher text is sent.  As this payload is
of length zero, only a `MAC` is sent across.  The mixing of `ECDH` outputs into
a hash digest forms an incremental TripleDH handshake.

Using the language of the Noise Protocol, `e` and `s` (both public keys)
indicate possibly encrypted keying material, and `es, ee, se` each indicate an
`ECDH` operation between two keys. The handshake is laid out as follows:

    Noise_XK(s, rs):
       <- s
       ...
       -> e, es
       <- e, ee
       -> s, se

All of the handshake data sent across the wire, including the keying material, is
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

### Noise Protocol Instantiation

Concrete instantiations of the Noise Protocol require the definition of
three abstract cryptographic objects: the hash function, the elliptic curve,
and finally the `AEAD` cipher scheme. Within our instantiation `SHA-256` is
chosen as the hash function, `secp256k1` as the elliptic curve, and finally
`ChaChaPoly-1305` as the `AEAD` construction. The composition of `ChaCha20`
and `Poly1305` used MUST conform to `RFC 7539`<sup>[1](#reference-1)</sup>. With this laid out, the
official Noise protocol name for our variant is:
`Noise_XK_secp256k1_ChaChaPoly_SHA256`.  The ASCII string representation of
this value is hashed into a digest used to initialize the starting handshake
state. If the protocol names of two endpoints differ, then the handshake
process fails immediately.


## Authenticated Key Exchange Handshake Specification

The handshake proceeds in three acts, taking 1.5 round trips. Each handshake is
a _fixed_ sized payload without any header or additional meta-data attached.
The exact size of each Act is as follows:

   * **Act One**: `50 bytes`
   * **Act Two**: `50 bytes`
   * **Act Three**: `66 bytes`

### Handshake State

Throughout the handshake process, each side maintains these variables:

 * `ck`: The **chaining key**. This value is the accumulated hash of all
   previous ECDH outputs. At the end of the handshake, `ck` is used to derive
   the encryption keys for lightning messages.

 * `h`: The **handshake hash**. This value is the accumulated hash of _all_
   handshake data that has been sent and received so far during the handshake
   process.

 * `temp_k1`, `temp_k2`, `temp_k3`: **intermediate keys** used to encrypt/decrypt the
   zero-length AEAD payloads at the end of each handshake message.

 * `e`: A party's **ephemeral keypair**. For each session a node MUST generate a
   new ephemeral key with strong cryptographic randomness.

 * `s`: A party's **static public key** (`ls` for local, `rs` for remote)

The following functions will also be referenced:

  * `ECDH(rk, k)`: Performs an Elliptic-Curve Diffie-Hellman operation using
    `rk` which is a `secp256k1` public key and `k` which is a valid private key
    within the finite field as defined by the curve parameters.
      * The returned value is the SHA256 of the DER compressed format of the
	    generated point.

  * `HKDF(salt,ikm)`: a function is defined in [3](#reference-3), evaluated with a
    zero-length `info` field.
     * All invocations of the `HKDF` implicitly return `64-bytes` of
       cryptographic randomness using the extract-and-expand component of the
       `HKDF`.

  * `encryptWithAD(k, n, ad, plaintext)`: outputs `encrypt(k, n, ad, plaintext)`
     * where `encrypt` is an evaluation of `ChaCha20-Poly1305` (IETF variant) with the passed
       arguments, with nonce `n` encoded as 32 zero bits followed by a *little-endian* 64-bit value (this
	   follows the Noise Protocol convention, rather than our normal endian).



  * `decryptWithAD(k, n, ad, ciphertext)`: outputs `decrypt(k, n, ad, ciphertext)`
     * where `decrypt` is an evaluation of `ChaCha20-Poly1305` (IETF variant) with the passed
       arguments, with nonce `n` encoded as 32 zero bits followed by a *little-endian* 64-bit value.

  * `generateKey()`
     * where generateKey generates and returns a fresh `secp256k1` keypair
     * the object returned by `generateKey` has two attributes: 
         * `.pub`: which returns an abstract object representing the public key
         * `.priv`: which represents the private key used to generate the
           public key
     * the object also has a single method: 
         * `.serializeCompressed()`

  * `a || b` denotes the concatenation of two byte strings `a` and `b`


### Handshake State Initialization

Before the start of the first act, both sides initialize their per-sessions
state as follows:

 1. `h = SHA-256(protocolName)`
    * where `protocolName = "Noise_XK_secp256k1_ChaChaPoly_SHA256"` encoded as
      an ASCII string.

 2. `ck = h`


 3. `h = SHA-256(h || prologue)`
    * where `prologue` is the ASCII string: `lightning`.


As a concluding step, both sides mix the responder's public key into the
handshake digest:


 * The initiating node mixes in the responding node's static public key
   serialized in Bitcoin's DER compressed format:
   * `h = SHA-256(h || rs.pub.serializeCompressed())`


 * The responding node mixes in their local static public key serialized in
   Bitcoin's DER compressed format:
   * `h = SHA-256(h || ls.pub.serializeCompressed())`


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


  * `h = SHA-256(h || e.pub.serializeCompressed())`
     * The newly generated ephemeral key is accumulated into our running
       handshake digest.


  * `ss = ECDH(rs, e.priv)`
     * The initiator performs a `ECDH` between its newly generated ephemeral
       key with the remote node's static public key.


  * `ck, temp_k1 = HKDF(ck, ss)`
     * This phase generates a new temporary encryption key which is
       used to generate the authenticating MAC.


  * `c = encryptWithAD(temp_k1, 0, h, zero)`
     * where `zero` is a zero-length plaintext


  * `h = SHA-256(h || c)`
     * Finally, the generated ciphertext is accumulated into the authenticating
       handshake digest.


  * Send `m = 0 || e.pub.serializeCompressed() || c` to the responder over the network buffer.


**Receiver Actions:**


  * Read _exactly_ `50-bytes` from the network buffer.


  * Parse out the read message (`m`) into `v = m[0]`, `re = m[1:33]` and `c = m[34:]`
    * where `m[0]` is the _first_ byte of `m`, `m[1:33]` are the next `33`
      bytes of `m` and `m[34:]` is the last 16 bytes of `m`
    * The raw bytes of the remote party's ephemeral public key (`e`) are to be
      deserialized into a point on the curve using affine coordinates as encoded
      by the key's serialized composed format.


  * If `v` is an unrecognized handshake version, then the responder MUST
    abort the connection attempt.


  * `h = SHA-256(h || re.serializeCompressed())`
    * Accumulate the initiator's ephemeral key into the authenticating
      handshake digest.

  * `ss = ECDH(re, s.priv)`
    * The responder performs an `ECDH` between its static public key and the
      initiator's ephemeral public key.


  * `ck, temp_k1 = HKDF(ck, ss)`
    * This phase generates a new temporary encryption key which will
      be used to shortly check the authenticating MAC.

  * `p = decryptWithAD(temp_k1, 0, h, c)`
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


  * `h = SHA-256(h || e.pub.serializeCompressed())`
     * The newly generated ephemeral key is accumulated into our running
       handshake digest.


  * `ss = ECDH(re, e.priv)`
     * where `re` is the ephemeral key of the initiator which was received
       during `ActOne`.


  * `ck, temp_k2 = HKDF(ck, ss)`
     * This phase generates a new temporary encryption key which is
       used to generate the authenticating MAC.


  * `c = encryptWithAD(temp_k2, 0, h, zero)`
     * where `zero` is a zero-length plaintext


  * `h = SHA-256(h || c)`
     * Finally, the generated ciphertext is accumulated into the authenticating
       handshake digest.

  * Send `m = 0 || e.pub.serializeCompressed() || c` to the initiator over the network buffer.


**Receiver Actions:**


  * Read _exactly_ `50-bytes` from the network buffer.


  * Parse out the read message (`m`) into `v = m[0]`, `re = m[1:33]` and `c = m[34:]`
    * where `m[0]` is the _first_ byte of `m`, `m[1:33]` are the next `33`
      bytes of `m` and `m[34:]` is the last 16 bytes of `m`


  * If `v` is an unrecognized handshake version, then the responder MUST
    abort the connection attempt.


  * `h = SHA-256(h || re.serializeCompressed())`


  * `ss = ECDH(re, e.priv)`
     * where `re` is the responder's ephemeral public key.
    * The raw bytes of the remote party's ephemeral public key (`re`) are to be
      deserialized into a point on the curve using affine coordinates as encoded
      by the key's serialized composed format.


  * `ck, temp_k2 = HKDF(ck, ss)`
     * This phase generates a new temporary encryption key which is
       used to generate the authenticating MAC.


  * `p = decryptWithAD(temp_k2, 0, h, c)`
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


  * `c = encryptWithAD(temp_k2, 1, h, s.pub.serializeCompressed())`
    * where `s` is the static public key of the initiator.


  * `h = SHA-256(h || c)`


  * `ss = ECDH(re, s.priv)`
    * where `re` is the ephemeral public key of the responder.


  * `ck, temp_k3 = HKDF(ck, ss)`
    * Mix the final intermediate shared secret into the running chaining key.


  * `t = encryptWithAD(temp_k3, 0, h, zero)`
     * where `zero` is a zero-length plaintext


  * `sk, rk = HKDF(ck, zero)`
     * where `zero` is a zero-length plaintext,


       `sk` is the key to be used by the initiator to encrypt messages to the
       responder,


       and `rk` is the key to be used by the initiator to decrypt messages sent by
       the responder.

     * This step generates the final encryption keys to be used for sending and
       receiving messages for the duration of the session.

  * `rn = 0, sn = 0`
     * The sending and receiving nonces are initialized to zero.

  * Send `m = 0 || c || t` over the network buffer.


**Receiver Actions:**


  * Read _exactly_ `66-bytes` from the network buffer.


  * Parse out the read message (`m`) into `v = m[0]`, `c = m[1:49]` and `t = m[50:]`


  * If `v` is an unrecognized handshake version, then the responder MUST
    abort the connection attempt.


  * `rs = decryptWithAD(temp_k2, 1, h, c)`
     * At this point, the responder has recovered the static public key of the
       initiator.


  * `h = SHA-256(h || c)`


  * `ss = ECDH(rs, e.priv)`
     * where `e` is the responder's original ephemeral key

  * `ck, temp_k3 = HKDF(ck, ss)`

  * `p = decryptWithAD(temp_k3, 0, h, t)`
     * If the MAC check in this operation fails, then the responder MUST
       terminate the connection without any further messages.


  * `rk, sk = HKDF(ck, zero)`
     * where `zero` is a zero-length plaintext,


       `rk` is the key to be used by the responder to decrypt the messages sent
       by the initiator,


       and `sk` is the key to be used by the responder to encrypt messages to
       the initiator,

     * This step generates the final encryption keys to be used for sending and
       receiving messages for the duration of the session.

  * `rn = 0, sn = 0`
     * The sending and receiving nonces are initialized to zero.

## Lightning Message Specification

At the conclusion of `Act Three` both sides have derived the encryption keys
which will be used to encrypt/decrypt messages for the remainder of the
session.

The actual lightning protocol messages are encapsulated within `AEAD` ciphertexts. Each message is prefixed with
another `AEAD` ciphertext which encodes the total length of the following lightning
message (not counting its MAC).

The *maximum* size of _any_ lightning message MUST NOT exceed `65535` bytes. A
maximum size of `65535` simplifies testing, makes memory management 
easier and helps mitigate memory exhaustion attacks.

In order to make make traffic analysis more difficult, the length prefix for
all encrypted lightning messages is also encrypted. Additionally we add a
`16-byte` `Poly-1305` tag to the encrypted length prefix in order to ensure
that the packet length hasn't been modified with in-flight, and also to avoid
creating a decryption oracle.

The structure of packets on the wire resembles the following:
```
+-------------------------------
|2-byte encrypted message length|
+-------------------------------
|  16-byte MAC of the encrypted |
|        message length         |
+-------------------------------
|                               |
|                               |
|     encrypted lightning       |
|            message            |
|                               |
+-------------------------------
|     16-byte MAC of the        |
|      lightning message        |
+-------------------------------
```
The prefixed message length is encoded as a `2-byte` big-endian integer,
for a total maximum packet length of `2 + 16 + 65535 + 16` = `65569` bytes.

### Encrypting Messages


In order to encrypt a lightning message (`m`), given a sending key (`sk`), and a nonce
(`sn`), the following is done:


  * let `l = len(m)`,
     where `len` obtains the length in bytes of the lightning message.


  * Serialize `l` into `2-bytes` encoded as a big-endian integer.


  * Encrypt `l` using `ChaChaPoly-1305`, `sn`, and `sk` to obtain `lc`
    (`18-bytes`)
    * The nonce `sn` is encoded as a 96-bit little-endian number. As our
      decoded nonces a 64-bit, we encode the 96-bit nonce as follows: 32-bits
      of leading zeroes followed by a 64-bit value.
        * The nonce `sn` MUST be incremented after this step.
    * A zero-length byte slice is to be passed as the AD (associated data).

  * Finally encrypt the message itself (`m`) using the same procedure used to
    encrypt the length prefix. Let encrypted ciphertext be known as `c`.
    * The nonce `sn` MUST be incremented after this step.

  * Send `lc || c` over the network buffer.


### Decrypting Messages


In order to decrypt the _next_ message in the network stream, the following is
done:


  * Read _exactly_ `18-bytes` from the network buffer.


  * Let the encrypted length prefix be known as `lc`


  * Decrypt `lc` using `ChaCha20-Poy1305`, `rn`, and `rk` to obtain size of
    the encrypted packet `l`.
    * A zero-length byte slice is to be passed as the AD (associated data).
    * The nonce `rn` MUST be incremented after this step.


  * Read _exactly_ `l+16` bytes from the network buffer, let the bytes be known as
    `c`.


  * Decrypt `c` using `ChaCha20-Poly1305`, `rn`, and `rk` to obtain decrypted
    plaintext packet `p`.

    * The nonce `rn` MUST be incremented after this step.


## Lightning Message Key Rotation


Changing keys regularly and forgetting the previous key is useful for
preventing decryption of old messages in the case of later key leakage (ie.
backwards secrecy).


Key rotation is performed for _each_ key (`sk` and `rk`) _individually _. A key
is to be rotated after a party sends of decrypts `1000` messages with it.
This can be properly accounted for by rotating the key once the nonce dedicated
to it exceeds `1000`.


Key rotation for a key `k` is performed according to the following:


  * Let `ck` be the chaining key obtained at the end of `Act Three`.
  * `ck', k' = HKDF(ck, k)`
  * Reset the nonce for the key to `n = 0`.
  * `k = k'`
  * `ck = ck'`
  
# Security Considerations #


It is strongly recommended that existing, commonly-used, validated
libraries be used for encryption and decryption, to avoid the many
implementation pitfalls possible.

# Appendix A: Transport Test Vectors

To make a repeatable handshake, we specify what `generateKey()` will
return (ie. the value for `e.priv`) for each side.  Note that this
is a violation of the spec, which requires randomness here.

## Initiator Tests

The initiator should produce the given output when fed this input.
The comments reflect internal state for debugging.

    name: transport-initiator successful handshake
    rs.pub: 0x028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    ls.priv: 0x1111111111111111111111111111111111111111111111111111111111111111
    ls.pub: 0x034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
    e.priv: 0x1212121212121212121212121212121212121212121212121212121212121212
    e.pub: 0x036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f7
    # Act One
    # h=0x9e0e7de8bb75554f21db034633de04be41a2b8a18da7a319a03c803bf02b396c
    # ss=0x1e2fb3c8fe8fb9f262f649f64d26ecf0f2c0a805a767cf02dc2d77a6ef1fdcc3
    # HKDF(0x2640f52eebcd9e882958951c794250eedb28002c05d7dc2ea0f195406042caf1,0x1e2fb3c8fe8fb9f262f649f64d26ecf0f2c0a805a767cf02dc2d77a6ef1fdcc3)
    # ck,temp_k1=0xb61ec1191326fa240decc9564369dbb3ae2b34341d1e11ad64ed89f89180582f,0xe68f69b7f096d7917245f5e5cf8ae1595febe4d4644333c99f9c4a1282031c9f
    # encryptWithAD(0xe68f69b7f096d7917245f5e5cf8ae1595febe4d4644333c99f9c4a1282031c9f, 0x000000000000000000000000, 0x9e0e7de8bb75554f21db034633de04be41a2b8a18da7a319a03c803bf02b396c, <empty>)
    # c=0df6086551151f58b8afe6c195782c6a
    # h=0x9d1ffbb639e7e20021d9259491dc7b160aab270fb1339ef135053f6f2cebe9ce
    output: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    input: 0x0002466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730ae
    # re=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # h=0x38122f669819f906000621a14071802f93f2ef97df100097bcac3ae76c6dc0bf
    # ss=0xc06363d6cc549bcb7913dbb9ac1c33fc1158680c89e972000ecd06b36c472e47
    # HKDF(0xb61ec1191326fa240decc9564369dbb3ae2b34341d1e11ad64ed89f89180582f,0xc06363d6cc549bcb7913dbb9ac1c33fc1158680c89e972000ecd06b36c472e47)
    # ck,temp_k2=0xe89d31033a1b6bf68c07d22e08ea4d7884646c4b60a9528598ccb4ee2c8f56ba,0x908b166535c01a935cf1e130a5fe895ab4e6f3ef8855d87e9b7581c4ab663ddc
    # decryptWithAD(0x908b166535c01a935cf1e130a5fe895ab4e6f3ef8855d87e9b7581c4ab663ddc, 0x000000000000000000000000, 0x38122f669819f906000621a14071802f93f2ef97df100097bcac3ae76c6dc0bf, 0x6e2470b93aac583c9ef6eafca3f730ae)
    # h=0x90578e247e98674e661013da3c5c1ca6a8c8f48c90b485c0dfa1494e23d56d72
    # Act Three
    # encryptWithAD(0x908b166535c01a935cf1e130a5fe895ab4e6f3ef8855d87e9b7581c4ab663ddc, 0x000000000100000000000000, 0x90578e247e98674e661013da3c5c1ca6a8c8f48c90b485c0dfa1494e23d56d72, 0x034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa)
    # c=0xb9e3a702e93e3a9948c2ed6e5fd7590a6e1c3a0344cfc9d5b57357049aa22355361aa02e55a8fc28fef5bd6d71ad0c3822
    # h=0x5dcb5ea9b4ccc755e0e3456af3990641276e1d5dc9afd82f974d90a47c918660
    # ss=0xb36b6d195982c5be874d6d542dc268234379e1ae4ff1709402135b7de5cf0766
    # HKDF(0xe89d31033a1b6bf68c07d22e08ea4d7884646c4b60a9528598ccb4ee2c8f56ba,0xb36b6d195982c5be874d6d542dc268234379e1ae4ff1709402135b7de5cf0766)
    # ck,temp_k3=0x919219dbb2920afa8db80f9a51787a840bcf111ed8d588caf9ab4be716e42b01,0x981a46c820fb7a241bc8184ba4bb1f01bcdfafb00dde80098cb8c38db9141520
    # encryptWithAD(0x981a46c820fb7a241bc8184ba4bb1f01bcdfafb00dde80098cb8c38db9141520, 0x000000000000000000000000, 0x5dcb5ea9b4ccc755e0e3456af3990641276e1d5dc9afd82f974d90a47c918660, <empty>)
    # t=0x8dc68b1c466263b47fdf31e560e139ba
    output: 0x00b9e3a702e93e3a9948c2ed6e5fd7590a6e1c3a0344cfc9d5b57357049aa22355361aa02e55a8fc28fef5bd6d71ad0c38228dc68b1c466263b47fdf31e560e139ba
    # HKDF(0x919219dbb2920afa8db80f9a51787a840bcf111ed8d588caf9ab4be716e42b01,zero)
    output: sk,rk=0x969ab31b4d288cedf6218839b27a3e2140827047f2c0f01bf5c04435d43511a9,0xbb9020b8965f4df047e07f955f3c4b88418984aadc5cdb35096b9ea8fa5c3442

    name: transport-initiator act2 short read test
    rs.pub: 0x028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    ls.priv: 0x1111111111111111111111111111111111111111111111111111111111111111
    ls.pub: 0x034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
    e.priv: 0x1212121212121212121212121212121212121212121212121212121212121212
    e.pub: 0x036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f7
    output: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    input: 0x0002466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730
    output: ERROR (ACT2_READ_FAILED)

    name: transport-initiator act2 bad version test
    rs.pub: 0x028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    ls.priv: 0x1111111111111111111111111111111111111111111111111111111111111111
    ls.pub: 0x034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
    e.priv: 0x1212121212121212121212121212121212121212121212121212121212121212
    e.pub: 0x036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f7
    output: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    input: 0x0102466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730ae
    output: ERROR (ACT2_BAD_VERSION 1)

    name: transport-initiator act2 bad key serialization test
    rs.pub: 0x028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    ls.priv: 0x1111111111111111111111111111111111111111111111111111111111111111
    ls.pub: 0x034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
    e.priv: 0x1212121212121212121212121212121212121212121212121212121212121212
    e.pub: 0x036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f7
    output: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    input: 0x0004466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730ae
    output: ERROR (ACT2_BAD_PUBKEY)

    name: transport-initiator act2 bad MAC test
    rs.pub: 0x028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    ls.priv: 0x1111111111111111111111111111111111111111111111111111111111111111
    ls.pub: 0x034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
    e.priv: 0x1212121212121212121212121212121212121212121212121212121212121212
    e.pub: 0x036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f7
    output: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    input: 0x0002466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730af
    output: ERROR (ACT2_BAD_TAG)

## Responder Tests

The responder should produce the given output when fed this input.

    name: transport-responder successful handshake
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # re=0x036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f7
    # h=0x9e0e7de8bb75554f21db034633de04be41a2b8a18da7a319a03c803bf02b396c
    # ss=0x1e2fb3c8fe8fb9f262f649f64d26ecf0f2c0a805a767cf02dc2d77a6ef1fdcc3
    # HKDF(0x2640f52eebcd9e882958951c794250eedb28002c05d7dc2ea0f195406042caf1,0x1e2fb3c8fe8fb9f262f649f64d26ecf0f2c0a805a767cf02dc2d77a6ef1fdcc3)
    # ck,temp_k1=0xb61ec1191326fa240decc9564369dbb3ae2b34341d1e11ad64ed89f89180582f,0xe68f69b7f096d7917245f5e5cf8ae1595febe4d4644333c99f9c4a1282031c9f
    # decryptWithAD(0xe68f69b7f096d7917245f5e5cf8ae1595febe4d4644333c99f9c4a1282031c9f, 0x000000000000000000000000, 0x9e0e7de8bb75554f21db034633de04be41a2b8a18da7a319a03c803bf02b396c, 0x0df6086551151f58b8afe6c195782c6a)
    # h=0x9d1ffbb639e7e20021d9259491dc7b160aab270fb1339ef135053f6f2cebe9ce
    # Act Two
    # e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27 e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    # h=0x38122f669819f906000621a14071802f93f2ef97df100097bcac3ae76c6dc0bf
    # ss=0xc06363d6cc549bcb7913dbb9ac1c33fc1158680c89e972000ecd06b36c472e47
    # HKDF(0xb61ec1191326fa240decc9564369dbb3ae2b34341d1e11ad64ed89f89180582f,0xc06363d6cc549bcb7913dbb9ac1c33fc1158680c89e972000ecd06b36c472e47)
    # ck,temp_k2=0xe89d31033a1b6bf68c07d22e08ea4d7884646c4b60a9528598ccb4ee2c8f56ba,0x908b166535c01a935cf1e130a5fe895ab4e6f3ef8855d87e9b7581c4ab663ddc
    # encryptWithAD(0x908b166535c01a935cf1e130a5fe895ab4e6f3ef8855d87e9b7581c4ab663ddc, 0x000000000000000000000000, 0x38122f669819f906000621a14071802f93f2ef97df100097bcac3ae76c6dc0bf, <empty>)
    # c=0x6e2470b93aac583c9ef6eafca3f730ae
    # h=0x90578e247e98674e661013da3c5c1ca6a8c8f48c90b485c0dfa1494e23d56d72
    output: 0x0002466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730ae
    # Act Three
    input: 0x00b9e3a702e93e3a9948c2ed6e5fd7590a6e1c3a0344cfc9d5b57357049aa22355361aa02e55a8fc28fef5bd6d71ad0c38228dc68b1c466263b47fdf31e560e139ba
    # decryptWithAD(0x908b166535c01a935cf1e130a5fe895ab4e6f3ef8855d87e9b7581c4ab663ddc, 0x000000000100000000000000, 0x90578e247e98674e661013da3c5c1ca6a8c8f48c90b485c0dfa1494e23d56d72, 0xb9e3a702e93e3a9948c2ed6e5fd7590a6e1c3a0344cfc9d5b57357049aa22355361aa02e55a8fc28fef5bd6d71ad0c3822)
    # rs=0x034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
    # h=0x5dcb5ea9b4ccc755e0e3456af3990641276e1d5dc9afd82f974d90a47c918660
    # ss=0xb36b6d195982c5be874d6d542dc268234379e1ae4ff1709402135b7de5cf0766
    # HKDF(0xe89d31033a1b6bf68c07d22e08ea4d7884646c4b60a9528598ccb4ee2c8f56ba,0xb36b6d195982c5be874d6d542dc268234379e1ae4ff1709402135b7de5cf0766)
    # ck,temp_k3=0x919219dbb2920afa8db80f9a51787a840bcf111ed8d588caf9ab4be716e42b01,0x981a46c820fb7a241bc8184ba4bb1f01bcdfafb00dde80098cb8c38db9141520
    # decryptWithAD(0x981a46c820fb7a241bc8184ba4bb1f01bcdfafb00dde80098cb8c38db9141520, 0x000000000000000000000000, 0x5dcb5ea9b4ccc755e0e3456af3990641276e1d5dc9afd82f974d90a47c918660, 0x8dc68b1c466263b47fdf31e560e139ba)
    # HKDF(0x919219dbb2920afa8db80f9a51787a840bcf111ed8d588caf9ab4be716e42b01,zero)
    output: rk,sk=0x969ab31b4d288cedf6218839b27a3e2140827047f2c0f01bf5c04435d43511a9,0xbb9020b8965f4df047e07f955f3c4b88418984aadc5cdb35096b9ea8fa5c3442

    name: transport-responder act1 short read test
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c
    output: ERROR (ACT1_READ_FAILED)

    name: transport-responder act1 bad version test
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x01036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    output: ERROR (ACT1_BAD_VERSION)

    name: transport-responder act1 bad key serialization test
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x00046360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    output: ERROR (ACT1_BAD_PUBKEY)

    name: transport-responder act1 bad MAC test
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6b
    output: ERROR (ACT1_BAD_TAG)

    name: transport-responder act3 bad version test
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    output: 0x0002466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730ae
    # Act Three
    input: 0x01b9e3a702e93e3a9948c2ed6e5fd7590a6e1c3a0344cfc9d5b57357049aa22355361aa02e55a8fc28fef5bd6d71ad0c38228dc68b1c466263b47fdf31e560e139ba
    output: ERROR (ACT3_BAD_VERSION 1)

    name: transport-responder act3 short read test
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    output: 0x0002466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730ae
    # Act Three
    input: 0x00b9e3a702e93e3a9948c2ed6e5fd7590a6e1c3a0344cfc9d5b57357049aa22355361aa02e55a8fc28fef5bd6d71ad0c38228dc68b1c466263b47fdf31e560e139
    output: ERROR (ACT3_READ_FAILED)

    name: transport-responder act3 bad MAC for ciphertext test 
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    output: 0x0002466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730ae
    # Act Three
    input: 0x00c9e3a702e93e3a9948c2ed6e5fd7590a6e1c3a0344cfc9d5b57357049aa22355361aa02e55a8fc28fef5bd6d71ad0c38228dc68b1c466263b47fdf31e560e139ba
    output: ERROR (ACT3_BAD_CIPHERTEXT)

    name: transport-responder act3 bad rs test
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    output: 0x0002466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730ae
    # Act Three
    input: 0x00bfe3a702e93e3a9948c2ed6e5fd7590a6e1c3a0344cfc9d5b57357049aa2235536ad09a8ee351870c2bb7f78b754a26c6cef79a98d25139c856d7efd252c2ae73c
    # decryptWithAD(0x908b166535c01a935cf1e130a5fe895ab4e6f3ef8855d87e9b7581c4ab663ddc, 0x000000000000000000000001, 0x90578e247e98674e661013da3c5c1ca6a8c8f48c90b485c0dfa1494e23d56d72, 0xd7fedc211450dd9602b41081c9bd05328b8bf8c0238880f7b7cb8a34bb6d8354081e8d4b81887fae47a74fe8aab3008653)
    # rs=0x044f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
    output: ERROR (ACT3_BAD_PUBKEY)

    name: transport-responder act3 bad MAC test
    ls.priv=2121212121212121212121212121212121212121212121212121212121212121
    ls.pub=028d7500dd4c12685d1f568b4c2b5048e8534b873319f3a8daa612b469132ec7f7
    e.priv=0x2222222222222222222222222222222222222222222222222222222222222222
    e.pub=0x02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
    # Act One
    input: 0x00036360e856310ce5d294e8be33fc807077dc56ac80d95d9cd4ddbd21325eff73f70df6086551151f58b8afe6c195782c6a
    # Act Two
    output: 0x0002466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f276e2470b93aac583c9ef6eafca3f730ae
    # Act Three
    input: 0x00b9e3a702e93e3a9948c2ed6e5fd7590a6e1c3a0344cfc9d5b57357049aa22355361aa02e55a8fc28fef5bd6d71ad0c38228dc68b1c466263b47fdf31e560e139bb
    output: ERROR (ACT3_BAD_TAG)

## Message Encryption Tests

In this test, the initiator sends length 5 messages containing "hello"
1001 times (we only show 6 example outputs for brevity, and to test
two key rotations):

	name: transport-message test
    ck=0x919219dbb2920afa8db80f9a51787a840bcf111ed8d588caf9ab4be716e42b01
	sk=0x969ab31b4d288cedf6218839b27a3e2140827047f2c0f01bf5c04435d43511a9
	rk=0xbb9020b8965f4df047e07f955f3c4b88418984aadc5cdb35096b9ea8fa5c3442
    # encrypt l: cleartext=0x0005, AD=NULL, sn=0x000000000000000000000000, sk=0x969ab31b4d288cedf6218839b27a3e2140827047f2c0f01bf5c04435d43511a9 => 0xcf2b30ddf0cf3f80e7c35a6e6730b59fe802
    # encrypt m: cleartext=0x68656c6c6f, AD=NULL, sn=0x000000000100000000000000, sk=0x969ab31b4d288cedf6218839b27a3e2140827047f2c0f01bf5c04435d43511a9 => 0x473180f396d88a8fb0db8cbcf25d2f214cf9ea1d95
	output 0: 0xcf2b30ddf0cf3f80e7c35a6e6730b59fe802473180f396d88a8fb0db8cbcf25d2f214cf9ea1d95
    # encrypt l: cleartext=0x0005, AD=NULL, sn=0x000000000200000000000000, sk=0x969ab31b4d288cedf6218839b27a3e2140827047f2c0f01bf5c04435d43511a9 => 0x72887022101f0b6753e0c7de21657d35a4cb
    # encrypt m: cleartext=0x68656c6c6f, AD=NULL, sn=0x000000000300000000000000, sk=0x969ab31b4d288cedf6218839b27a3e2140827047f2c0f01bf5c04435d43511a9 => 0x2a1f5cde2650528bbc8f837d0f0d7ad833b1a256a1
	output 1: 0x72887022101f0b6753e0c7de21657d35a4cb2a1f5cde2650528bbc8f837d0f0d7ad833b1a256a1
    # 0xcc2c6e467efc8067720c2d09c139d1f77731893aad1defa14f9bf3c48d3f1d31, 0x3fbdc101abd1132ca3a0ae34a669d8d9ba69a587e0bb4ddd59524541cf4813d8 = HKDF(0x919219dbb2920afa8db80f9a51787a840bcf111ed8d588caf9ab4be716e42b01, 0x969ab31b4d288cedf6218839b27a3e2140827047f2c0f01bf5c04435d43511a9)
    # 0xcc2c6e467efc8067720c2d09c139d1f77731893aad1defa14f9bf3c48d3f1d31, 0x3fbdc101abd1132ca3a0ae34a669d8d9ba69a587e0bb4ddd59524541cf4813d8 = HKDF(0x919219dbb2920afa8db80f9a51787a840bcf111ed8d588caf9ab4be716e42b01, 0x969ab31b4d288cedf6218839b27a3e2140827047f2c0f01bf5c04435d43511a9)
    output 500: 0x178cb9d7387190fa34db9c2d50027d21793c9bc2d40b1e14dcf30ebeeeb220f48364f7a4c68bf8
    output 501: 0x1b186c57d44eb6de4c057c49940d79bb838a145cb528d6e8fd26dbe50a60ca2c104b56b60e45bd
    # 0x728366ed68565dc17cf6dd97330a859a6a56e87e2beef3bd828a4c4a54d8df06, 0x9e0477f9850dca41e42db0e4d154e3a098e5a000d995e421849fcd5df27882bd = HKDF(0xcc2c6e467efc8067720c2d09c139d1f77731893aad1defa14f9bf3c48d3f1d31, 0x3fbdc101abd1132ca3a0ae34a669d8d9ba69a587e0bb4ddd59524541cf4813d8)
    # 0x728366ed68565dc17cf6dd97330a859a6a56e87e2beef3bd828a4c4a54d8df06, 0x9e0477f9850dca41e42db0e4d154e3a098e5a000d995e421849fcd5df27882bd = HKDF(0xcc2c6e467efc8067720c2d09c139d1f77731893aad1defa14f9bf3c48d3f1d31, 0x3fbdc101abd1132ca3a0ae34a669d8d9ba69a587e0bb4ddd59524541cf4813d8)
    output 1000: 0x4a2f3cc3b5e78ddb83dcb426d9863d9d9a723b0337c89dd0b005d89f8d3c05c52b76b29b740f09
    output 1001: 0x2ecd8c8a5629d0d02ab457a0fdd0f7b90a192cd46be5ecb6ca570bfc5e268338b1a16cf4ef2d36

# Acknowledgments

TODO(roasbeef); fin

# References
1. <a id="reference-1">https://tools.ietf.org/html/rfc7539</a>
2. <a id="reference-2">http://noiseprotocol.org/noise.html</a>
3. <a id="reference-3">https://tools.ietf.org/html/rfc5869</a>


# Authors

FIXME

This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
