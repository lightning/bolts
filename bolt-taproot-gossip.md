# Extension BOLT XX: Gossip V2

This document aims to define a gossip protocol which can be used to advertise
and verify both P2WSH channels and P2TR channels. The aim is that this protocol
could eventually completely replace the existing gossip protocol defined in
[BOLT 7][bolt-7] which can only be used to advertise P2WSH channels. An entirely
new set of gossip messages are defined that use [BIP-340][bip-340] signatures
and that use a pure TLV based structure.

# Table Of Contents

* [Terminology](#terminology)
* [Taproot Channel Proof and Verification](#taproot-channel-proof-and-verification)
* [TLV Based Messages](#tlv-based-messages)
* [Block-height fields](#block-height-fields)
* [Bootstrapping Taproot Gossip](#bootstrapping-taproot-gossip)
* [Specification](#specification)
    * [Type Definitions](#type-definitions)
    * [Features Bits](#feature-bits)
        * [`option_gossip_v2`](#option_gossip_v2)
        * [`option_gossip_v2_p2wsh`](#option_gossip_v2_p2wsh)
        * [`option_gossip_announce_private`](#option_gossip_announce_private)
    * [`open_channel` Extensions](#open_channel-extensions)
    * [`channel_ready` Extensions](#channel_ready-extensions)
    * [`announcement_signatures` Extra requirements](#announcement_signatures-extra-requirements)
    * [The `announcement_signatures_2` Message](#the-announcement_signatures_2-message)
    * [The `channel_announcement_2` Message](#the-channel_announcement_2-message)
    * [The `node_announcement_2` Message](#the-node_announcement_2-message)
    * [The `channel_update_2` Message](#the-channel_update_2-message)
* [Appendix A: Algorithms](#appendix-a-algorithms)
    * [Partial Signature Calculation](#partial-signature-calculation)
    * [Partial Signature Verification](#partial-signature-verification)
    * [Verifying the `channel_announcement_2` signature](#verifying-the-channelannouncement2-signature)
        * [The 3-of-3 MuSig2 Scenario](#the-3-of-3-musig2-scenario)
        * [The 4-of-4 MuSig2 Scenario](#the-4-of-4-musig2-scenario)
    * [Signature Message Construction](#signature-message-construction)
* [Appendix B: Test Vectors](#appendix-b-test-vectors)
* [Acknowledgements](#acknowledgements)

## Terminology

- `node_1` and `node_2` refer to the two parties involved in opening a channel.
- `node_ID_1` and `node_ID_2` respectively refer to the public keys that
  `node_1` and `node_2` use to identify their nodes in the network.
- `bitcoin_key_1` and `bitcoin_key_2` respectively refer to the public keys
  that `node_1` and `node_2` will use for the specific channel being opened.
  The funding transaction's output will be derived from these two keys.

## Taproot Channel Proof and Verification

All Taproot channel funding transaction outputs are SegWit V1 (P2TR) outputs of
the following form:

```
OP_1 <taproot_output_key> 
```

Ideally, the construction of the `taproot_output_key` should not matter to a
verifier of a channel. What a verifier cares about is whether the UTXO is
unspent and if the associated channel announcement contains a signature that
proves that the owner of the UTXO has participated in the signature
construction.

The simplest verification of a channel-announcement signature would then be to
check that the signature is valid for the following aggregate 3-of-3 MuSig2
public key:

```
P_agg = MuSig2.KeyAgg(MuSig2.KeySort(node_id_1, node_id_2, taproot_output_key))
```

This is simple and the spec can cater for this verification method today.
However, the spec must also contain recommendations for the construction of a
channel along with recommendations for the construction of a channel
announcement signature. The `taproot_output_key` will most likely be constructed
out of two or more keys where both channel peers own at least one key each and
so to compute a valid signature for the `P_agg` key noted above, the two channel
parties would need to make use of a nested MuSig2 protocol. Such a protocol has
yet to be specified and so this document can not yet rely on or reference such
a protocol.

Therefore, this document will also cater for the verification and construction
of a channel announcement signature for the following 4-of-4 MuSig2 public key:

```
P_agg = MuSig2.KeyAgg(MuSig2.KeySort(node_id_1, node_id_2, bitcoin_key_1, bitcoin_key_2))
```

In this case, the `taproot_output_key` is expected to be constructed in one of
two ways. The first way is as a pure key path spend output as follows:

```
taproot_output_key = MuSig2.KeyAgg(MuSig2.KeySort(bitcoin_key_1, bitcoin_key_2))
```

The second way includes a possible tweak:

```
taproot_internal_key = MuSig2.KeyAgg(MuSig2.KeySort(bitcoin_key_1, bitcoin_key_2))

taproot_output_key = taproot_internal_key + tagged_hash("TapTweak", merkle_root_hash) * G
```

In the case of Simple Taproot Channels, the `merkle_root_hash` will be equal to
the serialisation of the `taproot_internal_key`.

If the funding output is P2TR, then the verification method used all depends on
which information is provided in the `channel_announcement_2` message. All of
these verification methods require the `node_id_1` and `node_id_2` to be
provided along with a `short_channel_id` that will allow the verifier to fetch
the funding output from which the `taproot_output_key` can be extracted.

1. If no bitcoin keys are provided, then the signature must be verified against
   the following public key:

   ```
   P_agg = MuSig2.KeyAgg(MuSig2.KeySort(node_id_1, node_id_2, taproot_output_key)) 
   ```

   Allowing this proof type allows nodes to be somewhat future-proof since they
   will be able to verify and make use of channels using a proof construction
   not yet defined.

2. If the two bitcoin keys (`bitcoin_key_1` and `bitcoin_key_2`) are provided
   but no `merkle_root_hash` is provided then the verification steps are as
   follows:

    1. Compute the following aggregate 2-of-2 MuSig2 public key:
       ```
       P_agg_out = MuSig2.KeyAgg(MuSig2.KeySort(bitcoin_key_1, bitcoin_key_2))
       ```
    2. Assert that `P_agg_out` is equal to `taproot_output_key`.
    3. Now, compute the following aggregate 4-of-4 MuSig2 public key:
       ```
       P_agg = MuSig2.KeyAgg(MuSig2.KeySort(node_id_1, node_id_2, bitcoin_key_1, bitcoin_key_2))
       ```
    4. The signature must then be verified against `P_agg`.

3. If the two bitcoin keys and the `merkle_root_hash` is provided, then the
   verification steps are as follows:

    1. Compute the following aggregate 2-of-2 MuSig2 public key:
       ```
       P_internal = MuSig2.KeyAgg(MuSig2.KeySort(bitcoin_key_1, bitcoin_key_2))
       ``` 
    2. The compute the following output public key:
       ```
       P_output = P_internal + tagged_hash("TapTweak", merkle_root_hash) * G
       ```
    3. Assert that `P_output` is equal to `taproot_output_key`.
    4. Now, compute the following aggregate 4-of-4 MuSig2 public key:
       ```
       P_agg = MuSig2.KeyAgg(MuSig2.KeySort(node_id_1, node_id_2, bitcoin_key_1, bitcoin_key_2))
       ```
    5. The signature must then be verified against `P_agg`.

## TLV Based Messages

The initial set of Lightning Network messages consisted of a flat set of
serialised fields that were mandatory. Later on, TLV encoding was introduced
which provided a backward compatible way to extend messages. To ensure that the
new messages defined in this document remain as future-proof as possible, the
messages will be pure TLV streams with a set TLV range of signed fields and
unsigned fields. That way, any signature fields can be put in the un-signed
range along with any other large and non-mandatory fields such as SPV proofs.
By making all fields in the messages TLV records, fields that we consider
mandatory today can easily be dropped in future (when coupled with a new
feature bit) without needing to completely redefine the gossip message in order
to make the field optional.

## Block-height fields

In the messages defined in this document, block heights are used as timestamps
instead of the UNIX timestamps used in the BOLT 7 set of gossip messages.

### Rate Limiting

A block height based timestamp results in more natural rate limiting for gossip
messages: nodes are allowed to send at most one announcement and update per
block. To allow for bursts, nodes are encouraged not to use the latest block
height for their latest announcements/updates but rather to backdate and use
older block heights that they have not used in an announcement/update. There of
course needs to be a limit on the start block height that the node can use:
for `channel_update_2` messages, the lowest allowed `blockheight` is the block
height in which the channel funding transaction was mined and all updates after
the initial one must have increasing block heights. Nodes are then responsible
for building up their own timestamp buffer: if they want to be able to send
multiple `channel_update_2` messages per block, then they will need to ensure
that there are blocks during which they do not broadcast any updates. This
provides an incentive for nodes not to spam the network with too many updates.

### Simplifies Channel Announcement Queries

In the BOLT 7 gossip protocol, the timestamp of the `channel_announcement` is
hard to define since the message itself does not have a `timestamp` field. This
makes timestamp based gossip queries tricky. By using block heights as
timestamps instead, there is an implicit timestamp associated with the
`channel_announcement_2`: the block in which the funding transaction is mined.

## Interaction with BOLT 7

The idea is that the gossip message defined in this document could eventually
replace those defined in BOLT 7. The messages defined in this document can
therefore be used to advertise both P2WSH and P2TR channels. Doing this will
allow older channels to make use of the new gossip protocol and all its
advantages without needing to close all their channels and reopen them as PT2R
channels. The two protocols are to be seen as disjoint. This means, for example,
that a node may only advertise a `node_announcement_2` if it has advertised
a `channel_announcement_2`. This makes it easier to reason about the protocol.
Any nodes that understand both protocols are encouraged to persist both
advertisements in their database to cater for gossip syncing with older
peers, but they should favour the new protocol when making routing decisions.

While the network is in the upgrade phase, nodes will likely want to advertise
on both the old and new protocols for P2WSH channels so that older nodes
continue to see their channels. Eventually, when most of the network has
advertised their understanding of the new protocol, nodes can stop advertising
on the old protocol.

## Specification

### Type Definitions

The following convenient types are defined:

* `bip340sig`: a 64-byte bitcoin Elliptic Curve Schnorr signature as
  per [BIP-340][bip-340].
* `partial_signature`: a 32-byte partial MuSig2 signature as defined
  in [BIP-MuSig2][bip-musig2].
* `public_nonce`: a 66-byte public nonce as defined in [BIP-MuSig2][bip-musig2].
* `utf8`: a byte as part of a UTF-8 string. A writer MUST ensure an array of
  these is a valid UTF-8 string, a reader MAY reject any messages containing an
  array of these which is not a valid UTF-8 string.

### Pure TLV messages

All the messages defined in this document are pure TLV streams. The signed TLV
range is defined as the inclusive ranges: 0 to 159 and 1000000000 to 2999999999.

### Feature Bits

The proposed gossip upgrade is quite large and will require a lot of new code
for most implementations. It is therefore proposed that the upgrade be done
across a few feature bits. The following feature bits are proposed:

| Bits  | Name                             | Description                                               | Context | Dependencies       |
|-------|----------------------------------|-----------------------------------------------------------|---------|--------------------|
| 70/71 | `option_gossip_v2`               | Node understands gossip v2 protocol                       | IN*     |                    | 
| 72/73 | `option_gossip_v2_p2wsh`         | Node can advertise P2WSH channels with gossip v2 protocol | IN      | `option_gossip_v2` | 
| 74/75 | `option_gossip_announce_private` | Node is able to announce a previously unannounced channel | IN      |                    | 

The N* context above serves to indicate the legacy `node_announcement` message.
All the rest of the contexts are for the new gossip messages defined in this
document. The `option_gossip_v2` bit is implied if a node is making use of
the new set of gossip messages.

#### `option_gossip_v2`

This feature bit indicates that a node is able to understand all the new gossip
`_v2` messages defined in this document. This means it is able to verify both
P2TR and P2WSH channels announced with the new protocol If this feature bit is
set along with `option_taproot`, then the node is also able to open and
announce Simple Taproot Channels using the new gossip protocol. This bit can
be set in the `init` message along with the _legacy_ `node_announcement`
message.

#### `option_gossip_v2_p2wsh`

This feature bit depends on `option_gossip_v2` and indicates that a node is able
to use the new gossip protocol to advertise P2WSH channels. This means both that
for new channels, it can use the new gossip protocol to advertise them and that
for any existing, public, P2WSH channels, it can re-advertise them using the new
gossip protocol.

The reason this is a separate feature bit is that for some implementations, it
will be quite a large lift to support managing both sets of gossip messages for
a single channel and to support the flow of signing the announcement for
an existing channel. By separating out the bits, nodes can start announce
Simple Taproot Channels before they are able to re-announce their existing P2WSH
channels using the new gossip protocol.

#### `option_gossip_announce_private`

This feature bit indicates that a node is able to advertise a channel that
started out as unannounced. This means allowing the signing flow of the
`channel_announcement` and/or `channel_announcement_2` messages at any point
during the channel's lifetime even if the `announce_channel` bit was not set in
the `open_channel` message

#### Future feature bits

More feature bits may be added here to define, for example, different types of
channel proofs. An example is SPV proofs: a feature bit can be defined that
indicates that a node is able to produce an SPV proof and attach it to its
`channel_announcement_2` message if asked.

### `open_channel` Extensions

- If the `option_taproot` channel type was set in `open_channel`:
    - The sender:
        - If `option_gossip_v2` was negotiated:
            - MAY set the `announce_channel` bit in `channel_flags`
        - otherwise:
            - MUST NOT set the `announce_channel` bit.

    - The receiver:
        - if `option_gossip_v2` was not negotiated and the `announce_channel` bit
          in `channel_flags` was set, MUST fail the channel.

#### Rationale

- The `option_taproot` channel type was defined before this spec and limited
  peers that negotiated the channel type to open unannounced channels only.
  This document defines how peers can go about announcing these channels, and so
  this restriction can be lifted.

### `channel_ready` Extensions

The following extensions are defined for the `channel_ready` message:

1. `tlv_stream`: `channel_ready_tlvs`
2. types:
    1. type: 0 (`announcement_node_pubnonce`)
    2. data:
        * [`66*byte`: `public_nonce`]
    3. type: 2 (`announcement_bitcoin_pubnonce`)
    4. data:
        * [`66*byte`: `public_nonce`]

#### Requirements:

The following requirements apply if the `announce_channel` bit was set in the
`channel_flags` field of the `open_channel` message. Nodes advertising the
`option_gossip_announce_private` bit, may also choose to send the
`channel_ready` message at any point during the channel's lifetime in which
case, the following requirements also apply even if the `announce_channel` bit
was not set in `open_channel`.

The sender:

- If the negotiated channel type is `option_taproot` and `option_gossip_v2` was
  negotiated, then when the node is ready to advertise the channel:
    - SHOULD send `channel_ready` with the `announcement_node_pubnonce` and
      `announcement_bitcoin_pubnonce` fields set. The `announcement_node_pubnonce`
      must be set to the public nonce to be used for signing with the node's
      bitcoin key and the `announcement_bitcoin_pubnonce` must be set to the
      public nonce to be used for signing with the node's node ID key.
    - Upon reconnection, if a fully signed `channel_announcement_2` has not yet
      been constructed:
        - SHOULD re-send `channel_ready` with the nonce fields set.
    - Once a `channel_ready` message with the nonce fields has been both sent
      and received:
        - MUST proceed with constructing and sending the
          `announcement_signatures_2` message.
- If the negotiated channel type is not `option_taproot` (ie, it is a P2WSH
  channel) and the `option_gossip_v2_p2wsh` bit was negotiated, then when the
  node is ready to advertise the channel:
    - MAY send `channel_ready` either with or without the nonce fields set.
    - If the nonce fields are set, then the node MUST proceed with
      constructing and sending the `announcement_signatures_2` message
      in preparation for advertising the channel using the V2 protocol.
        - Upon reconnection, if a fully signed `channel_announcement_2` has not
          yet been constructed:
        - SHOULD re-send `channel_ready` with the nonce fields set.
    - Once a `channel_ready` message with the nonce fields has been both sent
      and received:
        - MUST proceed with constructing and sending the
          `announcement_signatures_2` message.
        - If they are not set, then node may proceed with constructing and
          sending the `announcement_signatures` message in preparation for
          advertising the channel using the V1 protocol.
        - Nodes may initiate the signing flow for both the V1 and V2 protocol
          and so should be able to handle receiving both the
          `announcement_signatures` and `announcement_signatures_2` messages.
- For any channel type, if the channel peers have negotiated the
  `option_gossip_announce_private` bit, then the node may send `channel_ready`
  at any point during the channel's lifetime to exchange nonces to use
  for the construction of the `announcement_signatures_2` message.

The recipient:

- If the nonce fields are set:
    - If only one of the nonce fields are set:
        - MUST ignore the message.
        - SHOULD send a warning.
        - MAY fail the connection.
    - If the channel has not reached sufficient confirmations:
        - SHOULD ignore the message.
    - Otherwise:
        - MUST store the nonces so that they can be used for the partial signature
          construction required for constructing the `announcement_signatures_2`
          message.
        - If it has not yet done so, SHOULD respond with its own `channel_ready`
          message with the nonce fields set.

#### Rationale

It cannot be a requirement that a node include the nonce fields in the
`channel_ready` since for cases such as zero-conf channels, nodes may send
`channel_ready` multiple times throughout the life of the channel to update it's
preferred channel alias, and it does not make sense to require that the nonce
fields be populated once the channel has already been announced.

### `announcement_signatures` Extra requirements

If peers have negotiated the `option_gossip_announce_private` bit, then the
`announcement_signatures` message can be used to initiate the signing flow for
a previously unannounced channel via the `channel_announcement` message at
any point during the channel's lifecycle. All existing requirements of the
message remain.

### The `announcement_signatures_2` Message

Like the legacy `announcement_signatures` message, this is a direct message
between the two endpoints of a channel and serves as an opt-in mechanism to
allow the announcement of the channel to the rest of the network. This message
is used to exchange the partial signatures required to construct the final
signature for the `channel_announcement_2` message.

This message can be sent in two cases:

1) At the start of the channel's lifetime if the `announce_channel` bit was set
   in the `channel_flags` field of the `open_channel` message.
2) At any other point in the channel's lifetime if the
   `option_gossip_announce_private` bit was negotiated between the channel peers.

1. type: 260 (`announcement_signatures_2`)
2. data:
    * [`announcement_signatures_2_tlvs`:`tlvs`]

1. `tlv_stream`: `announcement_signatures_2_tlvs`
2. types:
    1. type: 0 (`channel_id`)
    2. data:
        * [`channel_id`:`channel_id`]
    1. type: 2 (`short_channel_id`)
    2. data:
        * [`short_channel_id`:`short_channel_id`]
    1. type: 4 (`partial_signature`)
        * [`partial_signature`:`partial_signature`]


#### Requirements:

The requirements are similar to the ones defined for the legacy
`announcement_signatures` in that it should only be sent once a channel
has reached a sufficient number of confirmations meaning that nodes are able
to construct a valid `channel_announcement_2` for the channel.
This may be used for P2WSH channels IF the `option_gossip_v2_p2wsh` bit was
negotiated.

A node:
- if the `open_channel` message has the `announce_channel` bit set AND a
  `shutdown` message has not been sent:
    - MUST send the `announcement_signatures_2` message once a `channel_ready`
      message containing the announcement nonces has been sent and received AND
      the funding transaction has at least six confirmations.
    - MUST set the `partial_signature` field to the 32-byte `partial_sig` value
      of the partial signature calculated as described in [Partial Signature
      Calculation](#partial-signature-calculation). The message to be signed is
      `MsgHash("channel_announcement", "signature", m)` where `m` is the
      serialisation of the `channel_announcement_2` message tlv stream (see the
      [`MsgHash`](#signature-message-construction) definition).
- otherwise if the `option_gossip_announce_private` bit has been negotiated:
    - MAY send the `announcement_signatures_2` message at any point during the
      channel's lifetime with the same constraints as defined above.
- otherwise:
    - MUST NOT send the `announcement_signatures_2` message.
- upon reconnection (once the above timing requirements have been met):
    - MUST re-send a `channel_ready` message with the nonce fields set and await
      a reply.
    - Then, MUST respond to the first `announcement_signatures_2` message with
      its own `announcement_signatures_2` message.
    - if it has NOT received an `announcement_signatures_2` message:
        - SHOULD retransmit the `channel_ready` and `announcement_signatures_2`
          messages.

A recipient node:
- if the `short_channel_id` is NOT correct:
    - SHOULD send a `warning` and close the connection, or send an
      `error` and fail the channel.
- if the `partial_signature` is NOT valid as
  per [Partial Signature Verification](#partial-signature-verification):
    - MAY send a `warning` and close the connection, or send an
      `error` and fail the channel.
- if it has sent AND received a valid `announcement_signatures_2` message:
    - SHOULD queue the `channel_announcement_2` message for its peers.
- if it has not sent `channel_ready`:
    - MAY send a `warning` and close the connection, or send an `error` and fail
      the channel.

#### Rationale

The message contains the necessary partial signature, by the sender, that the
recipient will be able to combine with their own partial signature to construct
the signature to put in the `channel_announcement_2` message. Unlike the legacy
`announcement_signatures` message, `announcement_signatures_2` only has one
signature field. This field is a MuSig2 partial signature which is the
aggregation of the two signatures that the sender would have created (one for
`bitcoin_key_x` and another for `node_ID_x`).

### The `channel_announcement_2` Message

This gossip message contains ownership information regarding either a P2TR or
P2WSH channel. The channel is not practically usable until at least one side has
announced its fee levels and expiry, using `channel_update_2`.

1. type: 267 (`channel_announcement_2`)
2. data:
    * [`channel_announcement_2_tlvs`:`tlvs`]

1. `tlv_stream`: `channel_announcement_2_tlvs`
2. types:
    1. type: 0 (`chain_hash`)
    2. data:
        * [`chain_hash`:`chain_hash`]
    1. type: 2 (`features`)
    2. data:
        * [`...*byte`:`features`]
    1. type: 4 (`short_channel_id`)
    2. data:
        * [`short_channel_id`:`short_channel_id`]
    1. type: 6 (`capacity_satoshis`)
    2. data:
        * [`u64`:`capacity_satoshis`]
    1. type: 8 (`node_id_1`)
    2. data:
        * [`point`:`node_id_1`]
    1. type: 10 (`node_id_2`)
    2. data:
        * [`point`:`node_id_2`]
    1. type: 12 (`bitcoin_key_1`)
    2. data:
        * [`point`:`bitcoin_key_1`]
    1. type: 14 (`bitcoin_key_2`)
    2. data:
        * [`point`:`bitcoin_key_2`]
    1. type: 16 (`merkle_root_hash`)
    2. data:
        * [`32*byte`:`hash`]
    1. type: 18 (`outpoint`)
    2. data:
        * [`sha256`:`txid`]
        * [`u16`:`index`]
    1. type: 160 (`signature`)
    2. data:
        * [`bip340sig`:`sig`]

#### Message Field Descriptions

- The `chain_hash` is used to identify the blockchain containing the channel
  being referred to.
- `short_channel_id`: the short channel ID that can be used to uniquely identify
  the channel on-chain.
- `outpoint`: the funding transactions outpoint. A node may use this along with
  a bitcoin backend's `txindex` to look up the funding transaction.
- `capacity_satoshis`: the capacity of the channel in satoshis. This must be
  less than or equal to the value of the output identified by the `outpoint`
  and `short_channel_id` fields.
- `node_id_1` and `node_id_2`: the public keys of the two nodes involved in the
  channel.
- `bitcoin_key_1` and `bitcoin_key_2`: optional public keys used to derive the
  funding transaction's output.
- `merkle_root_hash`: an optional hash to use as the merkle root hash when
  deriving the tweak to apply to the internal key in the case of a P2TR channel.
- `signature`: a BIP 340 signature over the serialisation of the fields in the
  message's signed range. The public key that the signature should be verified
  against depends on the channel type along with which other fields in the
  message have been set.

#### Requirements:

The sender:
- If the chain that channel was opened with differs from the Bitcoin mainnet
  blockchain, then the `chain_hash` MUST be set to the 32-byte hash that
  uniquely identifies the chain. Otherwise, the field should not be set.
- MUST set `short_channel_id` to refer to the confirmed funding transaction,
  as specified in [BOLT #2](02-peer-protocol.md#the-channel_ready-message).
- MUST set `outpoint` to the refer to funding transaction. This MUST refer to
  the same output as the `short_channel_id` field.
- MUST set `capacity_satoshis` to the capacity of the channel in satoshis. This
  must be less than or equal to the value of the output identified by the
  `outpoint` and `short_channel_id` fields.
- MUST set `node_id_1` and `node_id_2` to the public keys of the two nodes
  operating the channel, such that `node_id_1` is the lexicographically-lesser
  of the two compressed keys sorted in ascending lexicographic order.
- If the channel being announced is a P2WSH type, then the `bitcoin_key_1` and
  `bitcoin_key_2` fields MUST be set and the `merkle_root_hash` field MUST NOT
  be set. See [Partial Signature Calculation](#partial-signature-calculation)
  for details on how to compute the `signature` field in this scenario.
- If the channel being announced is a P2TR type, then the `bitcoin_key_1`,
  `bitcoin_key_2` and `merkle_root_hash` fields are optional and the `signature`
  construction depends on how these fields are set and how `P_agg` has been
  derived. See [Partial Signature Calculation](#partial-signature-calculation)
  for details on how to compute the `signature` field in this scenario.
- The `signature` will always be over the serialised signed-range fields of the
  message.

The receiver:

- MUST verify the integrity AND authenticity of the `channel_announcement_2`
  message by verifying the signature. This verification will depend on the
  channel type along with which fields have been set in the message.
- Either the `short_channel_id` or the `outpoint` may be used to retrieve the
  channel's funding script. This can then be used to determine if the channel in
  question is a P2WSH channel or a P2TR channel.
- If the channel is a P2WSH channel:
    - The `bitcoin_key_1` and `bitcoin_key_2` fields MUST be set and the
      `merkle_root_hash` field MUST NOT be set. The message should be ignored
      otherwise.
    - The `signature` field must be valid according to the rules defined in
      [Verifying the `channel_announcement_2` signature](#verifying-the-channel_announcement_2-signature).
- otherwise:
    - The `bitcoin_key_1`, `bitcoin_key_2` and `merkle_root_hash` fields are
      optional.
    - The `signature` field must be valid according to the rules defined in
      [Verifying the `channel_announcement_2` signature](#verifying-the-channel_announcement_2-signature).
- If the `signature` is invalid:
    - SHOULD send a `warning`.
    - MAY close the connection.
    - MUST ignore the message.
- otherwise:
    - if `node_id_1` OR `node_id_2` are blacklisted:
        - SHOULD ignore the message.
    - otherwise:
        - if the transaction referred to was NOT previously announced as a
          channel:
            - SHOULD queue the message for rebroadcasting.
            - MAY choose NOT to for messages longer than the minimum expected
              length.
        - if it has previously received a valid `channel_announcement_v2`, for
          the same transaction, in the same block, but for a different
          `node_id_1` or `node_id_2`:
            - SHOULD blacklist the previous message's `node_id_1` and `node_id_2`,
              as well as this `node_id_1` and `node_id_2` AND forget any channels
              connected to them.
        - otherwise:
            - SHOULD store this `channel_announcement`.

- once its funding output has been spent OR reorganized out:
    - SHOULD forget a channel after a 12-block delay.

#### TLV Defaults

The following defaults TLV values apply if the TLV is not present in the
message:

| `channel_announcement_2` TLV Type  | Default Value                                                      | Comment                                                                                     |
|------------------------------------|--------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| 0  (`chain_hash`)                  | `6fe28c0ab6f1b372c1a6a246ae63f74f931e8365e15a089c68d6190000000000` | The hash of the genesis block of the mainnet Bitcoin blockchain.                            | 


### The `node_announcement_2` Message

This gossip message, like the `node_announcement` message, allows a node
to indicate extra data associated with it, in addition to its public key.
To avoid trivial denial of service attacks, nodes not associated with an already
known channel (advertised via a `channel_announcement_2` message) are ignored.

Unlike the `node_announcement` message, this message makes use of a
BIP340 signature instead of an ECDSA one. This will allow nodes to be backed
by multiple keys since MuSig2 can be used to construct the single signature.

1. type: 269 (`node_announcement_2`)
2. data:
    * [`node_announcement_2_tlvs`:`tlvs`]

1. `tlv_stream`: `node_announcement_2_tlvs`
2. types:
    1. type: 0 (`features`)
    1. type: 1 (`color`)
    2. data:
        * [`rgb_color`:`rgb_color`]
    2. data:
        * [`...*byte`: `features`]
    1. type: 2 (`block_height`)
    1. type: 3 (`alias`)
    2. data:
        * [`...*utf8`:`alias`]
    2. data:
        * [`u32`: `block_height`]
    1. type: 4 (`node_id`)
    2. data:
        * [`point`:`node_id`]
    1. type: 5 (`ipv4_addrs`)
    2. data:
        * [`...*ipv4_addr`: `ipv4_addresses`]
    1. type: 7 (`ipv6_addrs`)
    2. data:
        * [`...*ipv6_addr`: `ipv6_addresses`]
    1. type: 9 (`tor_v3_addrs`)
    2. data:
        * [`...*tor_v3_addr`: `tor_v3_addresses`]
    1. type: 11 (`dns_hostnames`)
    2. data:
        * [`...*dns_hostname`: `dns_hostnames`]
    1. type: 160 (`signature`)
    2. data:
        * [`bip340sig`:`sig`]

The following subtypes are defined:

1. subtype: `rgb_color`
2. data:
    * [`byte`:`red`]
    * [`byte`:`green`]
    * [`byte`:`blue`]

1. subtype: `ipv4_addr`
2. data:
    * [`u32`:`addr`]
    * [`u16`:`port`]

1. subtype: `ipv6_addr`
2. data:
    * [`16*byte`:`addr`]
    * [`u16`:`port`]

1. subtype: `tor_v3_addr`
2. data:
    * [`35*utf8`:`onion_addr`]
    * [`u16`:`port`]

1. subtype: `dns_hostname`
2. data:
    * [`u16`:`len`]
    * [`len*utf8`:`hostname`]
    * [`u16`:`port`]

#### Message Field Descriptions

- `signature` is the [BIP340][bip-340] signature for the `node_id` key. The
  message to be signed is `MsgHash("node_announcement_2", "signature", m)`
  where `m` is the serialised signed range of the TLV stream (see the
  [`MsgHash`](#signature-message-construction) definition).
- `features` is a bit vector with bits set according to [BOLT #9](09-features.md#assigned-features-flags)
- `block_height` allows for ordering or messages in the case of multiple
  announcements and also allows for natural rate limiting of
  `node_announcement_2` messages.
- `node_id` is the public key associated with this node. It must match a node ID
  that has previously been announced in the `node_id_1` or `node_id_2` fields of
  a `channel_announcement` or `channel_announcement_2` message for a channel
  that is still open.
- `rgb_color` is an optional field that a node may use to assign itself a color.
- `alias` is an optional field that a node may use to assign itself an alias
  that can then be used for a nicer UX on intelligence services. If this field
  is set, then it MUST be 32 utf8 characters or less.
- `ipv4_addr` is an ipv4 address and port.
- `ipv6_addr` is an ipv6 address and port.
- `tor_v3_addr` is a Tor version 3 ([prop224]) onion service address;
  Its `onion_addr` encodes:
  `[32:32_byte_ed25519_pubkey] || [2:checksum] || [1:version]`, where
  `checksum = sha3(".onion checksum" | pubkey || version)[:2]`.
- `dns_hostname` is a DNS hostname. The `hostname` MUST be ASCII characters.
  Non-ASCII characters MUST be encoded using [Punycode][punycode]. The length of
  the `hostname` cannot exceed 255 bytes.

#### Requirements

The sender:

- MUST set TLV fields 0, 2 and 4.
- MUST set `signature` to a valid [BIP340][bip-340] signature for the
  `node_id` key. The message to be signed is
  `MsgHash("node_announcement_2", "signature", m)` where `m` is the
  serialisation of the signed TLV range of the `node_announcement_2` message
  (see the [`MsgHash`](#signature-message-construction) definition).
- MAY set `color` and `alias` to customise appearance in maps and graphs.
- If the node sets the `alias`:
    - MUST use 32 utf8 characters or less.
- MUST set `block_height` to be greater than that of any previous
  `node_announcement_2` it has previously created. The `blockheight` should
  always be greater than or equal to funding block of the oldest channel that
  the node has advertised via `channel_announcement_2`.
- If the node wishes to announce its willingness to accept incoming network
  connections:
    - SHOULD set at least one of types 7-10.
- SHOULD set an address type (`ipv4_address`, `ipv6_address`, `tor_v3_address`
  and/or `dns_hostname`) for each public network address that expects incoming
  connections.
- SHOULD ensure that any specified `ipv4_addr` AND `ipv6_addr` are routable
  addresses.
- MUST not create a `ipv4_addr`, `ipv6_addr` or `dns_hostname` with a `port`
  equal to 0.
- MUST set `features` according to [BOLT #9][bolt-9-features].

The receiver:

- If type 0, 2 or 4 is missing:
    - SHOULD send a `warning`.
    - MAY close the connection.
    - MUST ignore the message.
- if `alias` is set and is larger than 32 utf8 characters:
    - SHOULD send a `warning`.
    - MAY close the connection.
    - MUST ignore the message.
- if `node_id` is NOT a valid compressed public key:
    - SHOULD send a `warning`.
    - MAY close the connection.
    - MUST NOT process the message further.
- if `signature` is NOT a valid [BIP340][bip-340] signature (using
  `node_id` over the message):
    - SHOULD send a `warning`.
    - MAY close the connection.
    - MUST NOT process the message further.
- if `features` field contains _unknown even bits_:
    - SHOULD NOT connect to the node.
    - Unless paying a [BOLT #11][bolt-11] invoice which does not have the same
      bit(s) set, MUST NOT attempt to send payments _to_ the node.
    - MUST NOT route a payment _through_ the node.
- if `port` is equal to 0 for any `ipv6_addr` OR `ipv4_addr` OR `hostname`:
    - SHOULD ignore that address.
- if `node_id` is NOT previously known from a `channel_announcement` OR
  `channel_announcement_2` message, OR if `blockheight` is NOT greater than the
  last-received `node_announcement_2` from this `node_id`:
    - SHOULD ignore the message.
- otherwise:
    - if `block_height` is greater than the last-received `node_announcement_2`
      from this `node_id`:
        - SHOULD queue the message for rebroadcasting.
- MAY use `rgb_color` AND `alias` to reference nodes in interfaces.
    - SHOULD insinuate their self-signed origins.

### Rationale

New node features are possible in the future: backwards compatible (or
optional) ones will have _odd_ `feature` _bits_, incompatible ones will have
_even_ `feature` _bits_. These will be propagated normally; incompatible feature
bits here refer to the nodes, not the `node_announcement_2` message itself.

### Security Considerations for Node Aliases

The security considerations for node aliases mentioned in
[BOLT #7][bolt-7-alias-security] apply here too.

### The `channel_update_2` Message

After a channel has been initially announced via `channel_announcement_2`, each
side independently announces the fees and minimum expiry delta it requires to
relay HTLCs through this channel. Each uses the 8-byte short channel id that
matches the `channel_announcement_2` and the `second_peer` field to
indicate which end of the channel it's on (origin or final). A node can do this
multiple times, in order to change fees.

1. type: 271 (`channel_update_2`)
2. data:
    * [`channel_update_2_tlvs`:`tlvs`]

1. `tlv_stream`: `channel_update_2_tlvs`
2. types:
    1. type: 0 (`chain_hash`)
    2. data:
        * [`chain_hash`:`chain_hash`]
    1. type: 2 (`short_channel_id`)
    2. data:
        * [`short_channel_id`:`short_channel_id`]
    1. type: 4 (`block_height`)
    2. data:
        * [`u32`:`block_height`]
    1. type: 6 (`disable_flags`)
    2. data:
        * [`byte`:`disable_flags`]
    1. type: 8 (`second_peer`)
    1. type: 10 (`cltv_expiry_delta`)
    2. data:
        * [`u16`:`cltv_expiry_delta`]
    1. type: 12 (`htlc_minimum_msat`)
    2. data:
        * [`u64`:`htlc_minimum_msat`]
    1. type: 14 (`htlc_maximum_msat`)
    2. data:
        * [`u64`:`htlc_maximum_msat`]
    1. type: 16 (`fee_base_msat`)
    2. data:
        * [`u32`:`fee_base_msat`]
    1. type: 18 (`fee_proportional_millionths`)
    2. data:
        * [`u32`:`fee_proportional_millionths`]
    1. type: 160 (`signature`)
    2. data:
        * [`bip340sig`:`sig`]


The `disable_flags` bitfield is used to indicate that the channel is either
temporarily or permanently disabled. The following table specifies the meaning
of the individual bits:

| Bit Position | Name        | Meaning                                               |
|--------------|-------------|-------------------------------------------------------|
| 0            | `permanant` | The disable update is permanent (otherwise temporary) |
| 1            | `incoming`  | The node can't receive via this channel               |
| 2            | `outgoing`  | The node can't forward or send via this channel       |

Both the `incoming` and `outgoing` bit can be set to indicate that the channel
peer is offline.

If the `permanant` bit is set, then the channel can be considered closed.

#### Message Field Descriptions

- The `chain_hash` is used to identify the blockchain containing the channel
  being referred to.
- `short_channel_id` is the unique identifier of the channel. If the channel is
  unannounced, then this may be set to an agreed upon alias.
- `block_height` is the timestamp associated with the message. A node may not
  send two `channel_update` messages with the same `block_height`. The
  `block_height` must also be greater than or equal to the block height
  indicated by the `short_channel_id` used in the `channel_announcement_2` and
  must not be greater than current best block height.
- The `disable` bit field can be used to advertise to the network that a channel
  is disabled and that it should not be used for routing. The individual
  `disable_flags` bits can be used to communicate more fine-grained information.
- The `second_peer` is used to indicate which node in the channel node pair has
  created and signed this message. If present, the node was `node_id_2` in the
  `channel_announcment_2`, otherwise the node is `node_id_1` in the
  `channel_announcement_2` message.
- `cltv_expiry_delta` is the number of blocks that the node will subtract from
  an incoming HTLC's `cltv_expiry`.
- `htlc_minimum_msat` is the minimum HTLC value (in millisatoshi) that the
  channel peer will accept.
- `htlc_maximum_msat` is the maximum value the node will send through this
  channel for a single HTLC.
    - MUST be less than or equal to the channel capacity
    - MUST be less than or equal to the `max_htlc_value_in_flight_msat` it
      received from the peer in the `open_channel` message.
- `fee_base_msat` is the base fee (in millisatoshis) that the node will charge
  for an HTLC.
- `fee_proportional_millionths` is the amount (in millionths of a satoshi) that
  node will charge per transferred satoshi.

#### TLV Defaults

For types 0, 6, 10, 12, 14, 16 and 18, the following defaults apply if the
TLV is not present in the message:

| `channel_update_2` TLV Type        | Default Value                                                      | Comment                                                                                     |
|------------------------------------|--------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| 0  (`chain_hash`)                  | `6fe28c0ab6f1b372c1a6a246ae63f74f931e8365e15a089c68d6190000000000` | The hash of the genesis block of the mainnet Bitcoin blockchain.                            | 
| 6  (`disable`)                     | empty                                                              |                                                                                             | 
| 10 (`cltv_expiry_delta`)           | 80                                                                 |                                                                                             | 
| 12 (`htlc_minimum_msat`)           | 1                                                                  |                                                                                             | 
| 14 (`htlc_maximum_msat`)           | floor(channel capacity / 2)                                        | // TODO: remove this since makes encoding/decoding dependent on things outside the message? | 
| 16 (`fee_base_msat`)               | 1000                                                               |                                                                                             | 
| 18 (`fee_proportional_millionths`) | 1                                                                  |                                                                                             |

#### Requirements

The origin node:

- For all fields with defined defaults:
    - SHOULD not include the field in the TLV stream if the default value is
      desired.
- MUST use the `channel_update_2` message to communicate channel parameters of a
  any channel advertised via `channel_announcement_2`.
- MUST NOT send a created `channel_update_2` before `channel_ready` has been
  received.
- For an unannounced channel (i.e. one where `announcement_signatures_2` has
  not been exchanged):
    - MAY create a `channel_update_2` to communicate the channel parameters to
      the channel peer.
    - MUST set the `short_channel_id` to either an `alias` it has received from
      the peer, or the real channel `short_channel_id`.
    - MUST NOT forward such a `channel_update_2` to other peers, for privacy
      reasons.
- For announced channels:
    - MUST set `chain_hash` AND `short_channel_id` to match the 32-byte hash AND
      8-byte channel ID that uniquely identifies the channel specified in the
      `channel_announcement_2` message.
- MUST set `signature` to a valid [BIP340][bip-340] signature for its own
  `node_id` key. The message to be signed is
  `MsgHash("channel_update_2", "signature", m)` where `m` is the serialised
  TLV stream of the `channel_update` (see the
  [`MsgHash`](#signature-message-construction) definition).
- SHOULD NOT create redundant `channel_update_2`s.
- If it creates a new `channel_update_2` with updated channel parameters:
    - SHOULD keep accepting the previous channel parameters for 2 blocks.

The receiving node:

- If the `short_channel_id` does NOT match a previous `channel_announcement_2`
  or `channel_announcement`, OR if the channel has been closed in the meantime:
    - MUST ignore `channel_update_2`s that do NOT correspond to one of its own
      channels.
- SHOULD accept `channel_update_2`s for its own channels (even if non-public),
  in order to learn the associated origin nodes' forwarding parameters.
- if `signature` is NOT a valid [BIP340][bip-340] signature (using `node_id`
  over the message):
    - SHOULD send a `warning` and close the connection.
    - MUST NOT process the message further.

### Query Messages

TODO:
1. new first block height & block range fields in gossip_timestamp_range
2. add block-height query option (like timestamps query option)

# Appendix A: Algorithms

## Partial Signature Calculation

When both nodes have exchanged a `channel_ready` message containing the
`announcement_node_pubnonce` and `announcement_bitcoin_pubnonce` fields then
they will each have the following information:

- `node_1` will know:
    - `bitcoin_priv_key_1`, `node_ID_priv_key_1`,
    - `bitcoin_key_2`,
    - `node_ID_1`,
    - `announcement_node_secnonce_1` and `announcement_node_pubnonce_1`,
    - `announcement_bitcoin_secnonce_1` and `announcement_bitcoin_pubnonce_1`,
    - `announcement_node_pubnonce_2`,
    - `announcement_bitcoin_pubnonce_2`,

- `node_2` will know:
    - `bitcoin_priv_key_2`, `node_ID_priv_key_2`,
    - `bitcoin_key_1`,
    - `node_ID_1`,
    - `announcement_node_secnonce_2` and `announcement_node_pubnonce_2`,
    - `announcement_bitcoin_secnonce_2` and `announcement_bitcoin_pubnonce_2`,
    - `announcement_node_pubnonce_1`,
    - `announcement_bitcoin_pubnonce_1`,

With the above information, both nodes can now start calculating the partial
signatures that will be exchanged in the `announcement_signatures_v2` message.

Firstly, the aggregate public key, `P_agg`, that the signature will be valid for
can be calculated as follows:

```
P_agg = Musig2.KeyAgg(Musig2.KeySort(node_ID_1, node_ID_2, bitcoin_key_1, bitcoin_key_2))
```

Next, the aggregate public nonce, `aggnonce`, can be calculated:

```
aggnonce = Musig2.NonceAgg(announcement_node_pubnonce_1, announcement_bitcoin_pubnonce_1, announcement_node_pubnonce_2, announcement_bitcoin_pubnonce_2)
```

The message, `msg` that the peers will sign is the serialisation of all the
TLV fields in the signed ranges of the `channel_announcement_2` message.

With all the information mentioned, both peers can now construct the
[`Session Context`][musig-session-ctx] defined by the MuSig2 protocol which is
necessary for as an input to the `Musig2.Sign` algorithm. The following members
of the `Session Context`, which we will call `session_ctx`, can be defined:

- `aggnonce`: `aggnonce`
- `u`: 2
- `pk1..u`: [`node_ID_1`, `node_ID_2`, `bitcoin_key_1`, `bitcoin_key_2`]
- `v`: 0
- `m`: `msg`

Both peers, `node_1` and `node_2` will need to construct two partial signatures.
One for their `bitcoin_key` and one for their `node_ID` and aggregate those.

- `node_1`:
    - calculates a partial signature for `node_ID_1` as follows:
       ```
       partial_sig_node_1 = MuSig2.Sign(announcement_node_secnonce_1, node_ID_priv_key_1, session_ctx) 
       ```
    - calculates a partial signature for `bitcoin_ID_1` as follows:
       ```
       partial_sig_bitcoin_1 = MuSig2.Sign(announcement_bitcoin_secnonce_1, bitcoin_priv_key_1, session_ctx) 
       ```
    - calculates `partial_sig_1` as follows:
       ```
       partial_sig_1 =  MuSig2.PartialSigAgg(partial_sig_node_1, partial_sig_bitcoin_1, session_ctx)
       ```

- `node_2`:
    - calculates a partial signature for `node_ID_2` as follows:
       ```
       partial_sig_node_2 = MuSig2.Sign(announcement_node_secnonce_2, node_ID_priv_key_2, session_ctx) 
       ```
    - calculates a partial signature for `bitcoin_ID_2` as follows:
       ```
       partial_sig_bitcoin_2 = MuSig2.Sign(announcement_bitcoin_secnonce_2, bitcoin_priv_key_2, session_ctx) 
       ```
    - calculates `partial_sig_2` as follows:
       ```
       partial_sig_2 =  MuSig2.PartialSigAgg(partial_sig_node_2, partial_sig_bitcoin_2, session_ctx)
       ```     

Note that since there are no tweaks involved in this MuSig2 signing flow,
signature aggregation is simply the addition of the two signatures:

```
    partial_sig = (partial_sig_node + partial_sig_bitcoin) % n
```

Where `n` is the [secp256k1][secp256k1] curve order.

## Partial Signature Verification

Since the partial signature put in `announcement_signatures_2` is the addition
of two of four signatures required to make up the final MuSig2 signature, the
verification of the partial signature is slightly different from what is
specified in the MuSig2 spec. The slightly adjusted algorithm will be defined
here. The notation used is the same as defined in the [MuSig2][musig-notation]
spec.

The inputs are:

- `partial_sig` sent by the peer in the `announcement_signatures_2` message.
- The `node_ID` and `bitcoin_key` of the peer.
- The `announcement_node_pubnonce` and `announcement_bitcoin_pubnonce` sent by
  the peer in the `channel_ready` message.
- The `session_ctx` as shown
  in [Partial Signature Calculation](#partial-signature-calculation).

Verification steps:

Note that the `GetSessionValues` and `GetSessionKeyAggCoeff` definitions can be
found in the [MuSig2][musig-session-ctx] spec.

- Let `(Q, _, _, b, R, e) = GetSessionValues(session_ctx)`
- Let `s = int(psig); fail if s >= n`
- Let `R_n1 = cpoint(announcement_node_pubnonce[0:33])`
- Let `R_n2 = cpoint(announcement_node_pubnonce[33:66])`
- Let `R_b1 = cpoint(announcement_bitcoin_pubnonce[0:33])`
- Let `R_b2 = cpoint(announcement_bitcoin_pubnonce[33:66])`
- Let `R_1 = R_n1 + R_b1`
- Let `R_2 = b*(R_n2 + R_b2)`
- Let `R_e' = R_1 + R_2`
- Let `R_e = R_e'` if `has_even_y(R)`, otherwise let `R_e = -R_e'`
- Let `P_n = node_ID`
- Let `P_b = bitcoin_key`
- Let `a_n = GetSessionKeyAggCoeff(session_ctx, P_n)`
- Let `a_b = GetSessionKeyAggCoeff(session_ctx, P_b)`
- Let `P = a_n*P_n + a_b*P_b`
- Let `g = 1` if `has_even_y(Q)`, otherwise `let g = -1 mod n`
- Fail if `s*G != R_e + e*g*P`

## Verifying the `channel_announcement_2` signature

For all the following cases, it should be verified that the output at the
provided `short_channel_id` or `outpoint` is an unspent P2WSH or P2TR output.

### The 3-of-3 MuSig2 Scenario

In the case where the funding transaction is a P2TR output and the received
`channel_announcement_2` message is does not have the optional `bitcoin_key_*`
fields, the signature of the message should be verified as a 3-of-3 MuSig2
signature. The keys involved are: `node_id_1`, `node_id_2` and the taproot
output key (`tr_output_key`) found in the channel's funding output specified by
the provided `short_channel_id`.

The full list of inputs required:
- `node_id_1`
- `node_id_2`
- `tr_output_key`
- `msg`: the serialised `channel_announcement_2` tlv stream.
- `sig`: the 64-byte BIP340 signature found in the `signature` field of the
  `channel_announcement_2` message. This signature must be parsed into `R` and
  `s` values as defined in BIP327.

The aggregate key can be calculated as follows:

```
P_agg = MuSig2.KeyAgg(MuSig2.KeySort(`node_id_1`, `node_id_2`, `tr_output_key`))
```

The signature can then be verified as follows:
- Let `pk` = `bytes(P_agg)` where the `bytes` function is defined in BIP340.
- Let `m` = `MsgHash("channel_announcement_2", "signature", msg)`
- Use the BIP340 `Verify` function to determine if the signature is valid by
  passing in `pk`, `m` and `sig`.

### The 4-of-4 MuSig2 Scenario

There are two possibilities here: the channel is a P2WSH channel or a P2TR
channel.

#### P2WSH Channels

In the case where the funding transaction is a P2WSH output, then the received
`channel_announcement_2` message MUST have both the optional `bitcoin_key_*`
fields and the `merkle_root_hash` should not be set. The verifier must then
ensure that the funding output matches the following P2WSH script:

    `2 <bitcoin_key_1> <bitcoin_key_2> 2 OP_CHECKMULTISIG`

After this has been verified, the signature of the message should be verified.
This is the same for P2TR channels and is described below.

#### P2TR Channels

In the case where the funding transaction is a P2TR output and the received
`channel_announcement_2` message has both the optional `bitcoin_key_*` fields,
the signature of the message should be verified as a 4-of-4 MuSig2 signature.
The keys involved are: `node_id_1`, `node_id_2`, `bitcoin_key_1` and
`bitcoin_key_2`. The message may also optionally contain the
`merkle_root_hash` field in this case.

Before the actual signature verification is done, it should first be asserted
that the taproot output key found in the funding output is in-fact made up of
the provided bitcoin keys. This can be done as follows:

First, calculate the aggregate key used as the internal key for the taproot
output, `P_internal`:

```
P_internal = KeyAgg(MuSig2.KeySort(`bitcoin_key_1`, `bitcoin_key_2`))
```

- Let `P_o` be the taproot output key found on-chain in the funding output
  referred to by the SCID.
- if the `merkle_root_hash` field is _not_ provided:
    - Fail the check if `P_internal != P_o`
- otherwise, if the `merkle_root_hash` is provided:
    - let `p` = `bytes(P_internal)`
    - let `t = hash_TapTweak(p || merkle_root_hash)` where `hash_TapTweak` uses
      the `hash_name(x)` method defined in BIP340.
    - Fail if `P_o != P_internal + t*G`

If the above check is successful, then it has been shown that the output key
is constructed from the two provided bitcoin keys.

#### Signature Verification

For both the above cases, the following signature verification applies:

The full list of inputs required:
- `node_id_1`
- `node_id_2`
- `bitcoin_key_1`
- `bitcoin_key_2`
- `msg`: the serialised signed range of the `channel_announcement_2` message.
- `sig`: the 64-byte BIP340 signature found in the `signature` field of the
  `channel_announcement_2` message. This signature must be parsed into `R` and
  `s` values as defined in BIP327.

The aggregate key can be calculated as follows:

```
P_agg = MuSig2.KeyAgg(MuSig2.KeySort(`node_id_1`, `node_id_2`, `bitcoin_key_1`, `bitcoin_key_2`))
```

The signature can then be verified as follows:
- Let `pk` = `bytes(P_agg)` where the `bytes` function is defined in BIP340.
- Let `m` = `MsgHash("channel_announcement_2", "signature", msg)`
- Use the BIP340 `Verify` function to determine if the signature is valid by
  passing in `pk`, `m` and `sig`.

## Signature Message Construction

The following `MsgHash` function is defined which can be used to construct a
32-byte message that can be used as a valid input to the [BIP-340][bip-340]
signing and verification algorithms.

_MsgHash:_
- _inputs_:
    * `message_name`: UTF-8 string
    * `field_name`: UTF-8 string
    * `message`: byte array

- Let `tag` = "lightning" || `message_name` || `field_name`
- return SHA256(SHA256(`tag`) || SHA256(`tag`) || SHA256(`message`))

# Appendix B: Test Vectors

TODO

# Acknowledgements

The ideas in this document are largely a consolidation and filtering of the
ideas mentioned in the following references:

- [Rusty's initial Gossip v2 proposal][ml-rusty-2019-gossip-v2] where the idea
  of replacing all gossip messages with new ones that use Schnorr signatures was
  first mentioned (in public writing). This post also included the idea of using
  block heights instead of Unix timestamps for timestamp fields as well as the
  idea of moving some optional fields to TLVs.
- [Roasbeef's post][ml-roasbeef-2022-tr-chan-announcement] on Taproot-aware
  Channel Announcements + Proof Verification which expands on the details of how
  taproot channel verification should work.

[bolt-7]: ./07-routing-gossip.md
[bolt-3]: ./03-transactions.md
[bolt-7-alias-security]: ./07-routing-gossip.md#security-considerations-for-node-aliases
[bolt-9-features]: ./09-features.md#bolt-9-assigned-feature-flags
[bolt-11]: ./11-payment-encoding.md
[bolt-11-tagged-fields]: ./11-payment-encoding.md#tagged-fields
[open-chan-msg]: ./02-peer-protocol.md#the-open_channel-message
[ml-rusty-2019-gossip-v2]: https://lists.linuxfoundation.org/pipermail/lightning-dev/2019-July/002065.html
[ml-roasbeef-2022-tr-chan-announcement]: https://lists.linuxfoundation.org/pipermail/lightning-dev/2022-March/003526.html
[bip-340]: https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki
[bip-340-verify]: https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki#verification
[simple-taproot-chans]: https://github.com/lightning/bolts/pull/995
[musig-keysort]: https://github.com/jonasnick/bips/blob/musig2/bip-musig2.mediawiki#key-sorting
[musig-keyagg]: https://github.com/jonasnick/bips/blob/musig2/bip-musig2.mediawiki#key-aggregation
[musig-signing]: https://github.com/jonasnick/bips/blob/musig2/bip-musig2.mediawiki#signing
[bip86-tweak]: https://github.com/bitcoin/bips/blob/master/bip-0086.mediawiki#address-derivation
[bip-musig2]: https://github.com/jonasnick/bips/blob/musig2/bip-musig2.mediawiki
[musig-session-ctx]: https://github.com/jonasnick/bips/blob/musig2/bip-musig2.mediawiki#session-context
[musig-notation]: https://github.com/jonasnick/bips/blob/musig2/bip-musig2.mediawiki#notation
[musig-partial-sig-agg]: https://github.com/jonasnick/bips/blob/musig2/bip-musig2.mediawiki#partial-signature-aggregation
[secp256k1]: https://www.secg.org/sec2-v2.pdf
[punycode]: https://en.wikipedia.org/wiki/Punycode
[prop224]: https://gitweb.torproject.org/torspec.git/tree/proposals/224-rend-spec-ng.txt
