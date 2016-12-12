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
   Protocol Framework<sup>[4](#reference-4)</sup>.
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
and `Poly1305` used MUST conform to `RFC 7539`<sup>[3](#reference-3)</sup>. With this laid out, the
official Noise protocol name for our variant is:
`Noise_XK_secp256k1_ChaChaPoly_SHA256`.  The ascii string representation of
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
    within the finite field as defined by the curve paramters.
      * The returned value is the serialization of the generated point in compressed format (33 bytes)

  * `HKDF`: a function is defined in [5](#reference-5), evaluated with a
    zero-length `info` field.
     * All invocations of the `HKDF` implicitly return `64-bytes` of
       cryptographic randomness using the extract-and-expand component of the
       `HKDF`.

  * `encryptWithAD(k, n, ad, plaintext)`: outputs `encrypt(k, n, ad, plaintext)`
     * where `encrypt` is an evaluation of `ChaCha20-Poly1305` (IETF variant) with the passed
       arguments, with nonce `n` encoded as a big-endian 96-bit value.



  * `decryptWithAD(k, n, ad, ciphertext)`: outputs `decrypt(k, n, ad, ciphertext)`
     * where `decrypt` is an evaluation of `ChaCha20-Poly1305` (IETF variant) with the passed
       arguments, with nonce `n` encoded as a big-endian 96-bit value.

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
      an ascii string.

 2. `ck = h`


 3. `h = SHA-256(h || prologue)`
    * where `prologue` is the ascii string: `lightning`.


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


  * Parse out the read message (`m`) into `v = m[0]`, `re = m[1:34]` and `c = m[43:]`
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


  * Parse out the read message (`m`) into `v = m[0]`, `re = m[1:34]` and `c = m[43:]`
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


  * Parse out the read message (`m`) into `v = m[0]`, `c = m[1:50]` and `t = m[50:]`


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
    * The nonce `sn` is encoded as a 96-bit big-endian number.
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

# Test vectors

The following test vectors were generated with the Noise go library listed at [4](#reference-4) with the addition of the secp256k1 ECDH function described above:

```
handshake=Noise_XK_secp256k1_ChaChaPoly_SHA256
init_static=000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
resp_static=0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20
gen_init_ephemeral=202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f
gen_resp_ephemeral=4142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f60
prologue=6e6f74736563726574
priv=202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f pub=021f8a566c205633d029094747d2e18f44e05993dda7a5f88f496078205f656e59
msg_0_payload=
msg_0_ciphertext=021f8a566c205633d029094747d2e18f44e05993dda7a5f88f496078205f656e59795b489341de8ba2aede9ef724ef41ed
priv=4142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f60 pub=037c3f0429768437a942f1818ef1616c609b7a6d8a8dd245e179c8c0838e7d169d
msg_1_payload=
msg_1_ciphertext=037c3f0429768437a942f1818ef1616c609b7a6d8a8dd245e179c8c0838e7d169db055b26c58562e78aeca76e40d12e862
msg_2_payload=
msg_2_ciphertext=9f9d6475c1af2e67564b29b1dfc4a6b864eaa0a9f74db4f793c6679fa0ada71ebcd946b0ffa309c143121811670afa40b06dd1f7a01f6e8411928ab73e72b64815
msg_3_payload=79656c6c6f777375626d6172696e65
msg_3_ciphertext=aba32cad174896f16cfa9666cba96a1ffca17e0f5403295e3bab452dee714b
msg_4_payload=7375626d6172696e6579656c6c6f77
msg_4_ciphertext=3ab95ff1ebdcc5e26d6656571eca24023065d71abaa976298ea5e3f30bf8d1
```

## Acknowledgements

TODO(roasbeef); fin

# References
3. <a id="reference-3">https://tools.ietf.org/html/rfc7539</a>
4. <a id="reference-4">http://noiseprotocol.org/noise.html</a>
5. <a id="reference-5">https://tools.ietf.org/html/rfc5869</a>


# Authors

FIXME

This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
