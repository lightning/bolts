# Route Blinding

## Table of Contents

* [Proposal](#proposal)
  * [Introduction](#introduction)
  * [Overview](#overview)
  * [Notations](#notations)
  * [Requirements](#requirements)
  * [Encrypted data](#encrypted-data)
  * [Creating a blinded route](#creating-a-blinded-route)
  * [Sending to a blinded route](#sending-to-a-blinded-route)
  * [Receiving from a blinded route](#receiving-from-a-blinded-route)
  * [Blinded payments](#blinded-payments)
* [Attacks](#attacks)
  * [Unblinding channels with payment probing](#unblinding-channels-with-payment-probing)
  * [Unblinding nodes after restart](#unblinding-nodes-after-restart)
* [Tips and Tricks](#tips-and-tricks)
  * [Recipient pays fees](#recipient-pays-fees)
  * [Dummy hops](#dummy-hops)
  * [Wallets and unannounced channels](#wallets-and-unannounced-channels)
  * [Blinded trampoline route](#blinded-trampoline-route)
* [FAQ](#faq)
  * [Why not use rendezvous](#why-not-use-rendezvous)
  * [Why not use HORNET](#why-not-use-hornet)

## Proposal

### Introduction

Route blinding is a lightweight technique to provide recipient anonymity by blinding an arbitrary
amount of hops at the end of an onion path. It's more flexible than rendezvous routing because it
simply replaces the public keys of the nodes in the route with random public keys while letting
senders choose what data they put in the onion for each hop. Blinded routes are also reusable in
some cases (e.g. onion messages).

The downside compared to rendezvous is that senders have more leeway to probe by changing various
variables, so the scheme needs to explicitly defend against probing attacks and may provide less
privacy against some classes of attacks.

Some use-cases where route blinding is useful include:

* Sender and recipient anonymity for onion messages
* Recipient anonymity for Bolt 12 offers
* Recipient anonymity when receiving payments
* Using unannounced channels in invoices without revealing them
* Forcing a payment to go through a specific set of intermediaries that can witness the payment

### Overview

At a high level, route blinding works by having the recipient choose an _introduction point_ and a
route to itself from that introduction point. The recipient then blinds each node and channel along
that route with ECDH. The recipient sends details about the blinded route and some cryptographic
material to the sender (via a Bolt 11 invoice or Bolt 12 offer), which lets the sender build an
onion with enough information to allow nodes in the blinded route to incrementally unblind the next
node in the route.

This scheme requires all the nodes in the blinded route and the sender to activate support for the
feature. It needs a big enough share of the network to support it to provide meaningful privacy
guarantees.

### Notations

* A node `N(i)`'s `node_id` is defined as: `N(i) = k(i) * G` (`k(i)` is the node's private key).
* Blinded `node_id`s are defined as: `B(i) = b(i) * G` (`b(i)` is the blinding factor).
* Sphinx ephemeral public keys are defined as: `E(i) = e(i) * G`.

### Requirements

A node `N(r)` wants to provide a blinded route `N(0) -> N(1) -> ... -> N(r)` that must be used
to receive onions.

* Intermediate nodes in the blinded route MUST NOT learn the `node_id` or `scid` of other
  intermediate nodes except for their immediate predecessor or successor.
* Intermediate nodes in the blinded route MUST NOT learn their distance to the recipient `N(r)`.
* Senders MUST NOT learn the real `node_id` and `scid` of the blinded intermediate hops after the
  introduction point `N(0)`.
* If `N(r)` creates multiple blinded routes to itself, senders MUST NOT be able to tell that these
  routes lead to the same recipient (unless of course this information is leaked by higher layers
  of the protocol, such as using the same `payment_hash` or being generated for the same offer).

### Encrypted data

Route blinding introduces a new TLV field to the onion `tlv_payload`: the `encrypted_data`.

This field is used to carry data coming from the builder of the route that cannot be modified by
the sender. It needs to contain enough data to let intermediate nodes locate the next node in the
route (usually a `node_id` or `scid`), and may be extended with additional data in the future. It
uses ChaCha20-Poly1305 as AEAD scheme.

1. type: 10 (`encrypted_data`)
2. data:
    * [`...*byte`:`encrypted_data`]

Once decrypted, the content of this encrypted payload is a TLV stream.

### Creating a blinded route

`N(r)` performs the following steps to create a blinded route:

```text
Initialization:

  e(0) <- {0;1}^256
  E(0) = e(0) * G

Blinding:

  For i = 0 to r:
    ss(i) = H(e(i) * N(i)) = H(k(i) * E(i))         // shared secret known only by N(r) and N(i)
    B(i) = HMAC256("blinded_node_id", ss(i)) * N(i) // Blinded node_id for N(i), private key known only by N(i)
    rho(i) = HMAC256("rho", ss(i))                  // Key used to encrypt payload for N(i) by N(r)
    e(i+1) = H(E(i) || ss(i)) * e(i)                // Ephemeral private key, only known by N(r)
    E(i+1) = H(E(i) || ss(i)) * E(i)                // NB: N(i) must not learn e(i)
```

Note that this is exactly the same construction as Sphinx, but at each hop we use the shared secret
to derive a blinded `node_id` for `N(i)` for which the private key will only be known by `N(i)`.

The recipient then creates `encrypted_data(i)` by encrypting application-specific data with
ChaCha20-Poly1305 using the `rho(i)` key.

To use the blinded route, senders need the following data:

* The real `node_id` of the introduction point `N(0)` (to locate the beginning of the route)
* The list of blinded `node_id`s: `[B(1),...,B(r)]`
* The encrypted data for each node: `[encrypted_data(0),...,encrypted_data(r)]`
* The first blinding ephemeral key: `E(0)`

### Sending to a blinded route

The sender finds a route to the introduction point `N(0)`, and extends it with the blinded route.
It then creates an onion for that whole route, and includes `E(0)` and `encrypted_data(0)` in the
onion payload for `N(0)`. It includes `encrypted_data(i)` in the onion payload for `B(i)`.

When `N(0)` receives the onion and decrypts it, it finds `E(0)` in the payload and is able to
compute the following:

```text
  ss(0) = H(k(0) * E(0))
  rho(0) = HMAC256("rho", ss(0))
  E(1) = H(E(0) || ss(0)) * E(0)
```

It uses `rho(0)` to decrypt the `encrypted_data(0)` and discovers that `B(1)` is actually `N(1)`.
It forwards the onion to `N(1)` and includes `E(1)` in a TLV field in the lightning message
(e.g. in the extension field of an `update_add_htlc` message).

All the following intermediate nodes `N(i)` do the following steps:

```text
  E(i) <- extracted from the lightning message's fields
  ss(i) = H(k(i) * E(i))
  b(i) = HMAC256("blinded_node_id", ss(i)) * k(i)
  Use b(i) instead of k(i) to decrypt the incoming onion using sphinx
  rho(i) = HMAC256("rho", ss(i))
  Use rho(i) to decrypt the `encrypted_data` inside the onion and discover the next node
  E(i+1) = H(E(i) || ss(i)) * E(i)
  Forward the onion to the next node and include E(i+1) in a TLV field in the message
```

### Receiving from a blinded route

When `N(r)` receives the onion message and `E(r)`, they do the same unwrapping as intermediate
nodes. The difference is that the onion will be a final onion.

`N(r)` must also validate that the blinded route was used in the context it was created for, and is
a route that they created. It's important to note than anyone can create valid blinded routes to
anyone else. Alice for example is able to create a blinded route `Bob -> Carol -> Dave`. In most
cases, Dave wants to ignore messages that come through routes that were created by someone else.

The details of this validation step depends on the actual application using route blinding. For
example, when using a blinded route for payments, the recipient must verify that the route was
used in conjunction with the right `payment_hash`. It can do so by storing the `payment_preimage`
in the `encrypted_data` payload to itself and verifying it when receiving the payment: malicious
senders don't know the preimage beforehand, so they won't be able to create a satisfying route.

Without this validation step, the recipient exposes itself to malicious probing, which could let
attackers deanonymize the route.

### Blinded payments

This section provides more details on how route blinding can be used for payments.

In order to protect against malicious probing (detailed in the [Attacks](#attacks) section), it is
the recipient who chooses what payment relay parameters will be used inside the route (e.g. fees)
and encodes them in the `encrypted_data` payload for each blinded node. The sender will not set the
`amt_to_forward` and `outgoing_cltv_value` fields in the onion payloads for blinded intermediate
nodes: these nodes will instead follow the instructions found in their `encrypted_data`.

The `encrypted_data` for each intermediate node will contain the following fields:

* `short_channel_id`: outgoing channel that should be used to route the payment
* `fee_base_msat`: base fee that must be applied before relaying the payment
* `fee_proportional_millionths`: proportional fee that must be applied before relaying the payment
* `cltv_expiry_delta`: cltv expiry delta that must be applied before relaying the payment
* `max_cltv_expiry`: maximum expiry allowed for this payment
* `htlc_minimum_msat`: minimum htlc amount that should be accepted
* `allowed_features`: features related to payment relay that the sender is allowed to use

The recipient must use values that exceed the ones found in each `channel_udpate`, otherwise it
would be easy for a malicious sender to figure out which channels are hidden inside the blinded
route.

The recipient also includes the `payment_preimage` (or another private unique identifier for the
payment) in the `path_id` field of the `encrypted_data` payload for itself: this will let the
recipient verify that the route is only used for that specific payment and was generated by them.

If a node inside the blinded route receives a payment that doesn't use the parameters provided in
the `encrypted_data`, it must reject the payment and respond with an unparsable error onion. That
ensures the payer won't know which node failed and for what reason (otherwise that would provide
data that the payer could use to probe nodes inside the route).

Note that we are also providing a `max_cltv_expiry` field: this ensures that the blinded route
expires after some time, restricting future probing attempts.

If we assume that all nodes support `var_onion_option`, we don't need to include the
`allowed_features` field for now as there are no other features that affect payment relay and
could be used as a probing vector. However, future updates may add such features (e.g. PTLC
support), in which case the `allowed_features` field must not be empty.

Let's go through an example to clarify those requirements.

Alice creates an invoice with the following blinded route: `Carol -> Bob -> Alice`.
The channels along that route have the following settings:

* `Carol -> Bob`
  * `fee_base_msat`: 10
  * `fee_proportional_millionths`: 250
  * `cltv_expiry_delta`: 144
  * `htlc_minimum_msat`: 1
* `Bob -> Alice`
  * `fee_base_msat`: 50
  * `fee_proportional_millionths`: 100
  * `cltv_expiry_delta`: 48
  * `htlc_minimum_msat`: 1000

Alice chooses the following parameters for the blinded route, that satisfy the requirements of the
channels described above and adds a safety margin in case nodes update their relay parameters:

* `fee_base_msat`: 100
* `fee_proportional_millionths`: 500
* `htlc_minimum_msat`: 1000
* `cltv_expiry_delta`: 144

Alice uses the same values for both channels for simplicity's sake. Alice can now compute aggregate
values for the complete route (iteratively starting from the end of the route):

* `route_fee_base_msat`: ceil(100 + 100 * (1 + 500/1000000)) = 201
* `route_fee_proportional_millionths`: ceil((500/1000000) + (500/1000000) + (500/1000000)^2) = 1001
* `route_cltv_expiry_delta`: 288
* NB: we need to round values up, otherwise the recipient will receive slightly less than expected

Let's assume the current block height is 1000. Alice wants the route to be used in the next 200
blocks, so she sets `max_cltv_expiry = 1200` and adds `cltv_expiry_delta` for each hop. Alice then
transmits the following information to the sender (most likely via an invoice):

* Blinded route: `[N(carol), B(bob), B(alice)]`
* First blinding ephemeral key: `E(carol)`
* Aggregated route relay parameters and constraints:
  * `fee_base_msat`: 201
  * `fee_proportional_millionths`: 1001
  * `htlc_minimum_msat`: 1000
  * `cltv_expiry_delta`: 288
  * `max_cltv_expiry`: 1200
  * `allowed_features`: empty
* Encrypted data for blinded nodes:
  * `encrypted_payload(alice)`:
    * `path_id`: `payment_preimage`
    * `max_cltv_expiry`: 1200
  * `encrypted_payload(bob)`:
    * `outgoing_channel_id`: `scid_bob_alice`
    * `fee_base_msat`: 100
    * `fee_proportional_millionths`: 500
    * `htlc_minimum_msat`: 1000
    * `max_cltv_expiry`: 1344
  * `encrypted_payload(carol)`:
    * `outgoing_channel_id`: `scid_carol_bob`
    * `fee_base_msat`: 100
    * `fee_proportional_millionths`: 500
    * `htlc_minimum_msat`: 1000
    * `max_cltv_expiry`: 1488

Note that the introduction point (Carol) uses the real `node_id`, not the blinded one, because the
sender needs to be able to locate this introduction point and find a route to it. The sender will
send the first blinding ephemeral key `E(carol)` in the onion `hop_payload` for Carol, which will
allow Carol to compute the blinding shared secret and correctly forward. We put this blinding
ephemeral key in the onion instead of using a tlv in `update_add_htlc` because intermediate nodes
added before the blinded route may not support route blinding and wouldn't know how to relay it.

Eve wants to send 100 000 msat to this blinded route.
She can reach Carol via Dave: `Eve -> Dave -> Carol`, where the channel between Dave and Carol uses
the following relay parameters:

* `fee_base_msat`: 10
* `fee_proportional_millionths`: 100
* `cltv_expiry_delta`: 24

Eve uses the aggregated route relay parameters to compute how much should be sent to Carol:

* `amount = ceil(100000 + 201 + 1001 * 100000 / 1000000) = 100302 msat`

Eve chooses a final expiry of 1100, which is below Alice's `max_cltv_expiry`, and computes the
expiry that should be sent to Carol:

* `expiry = 1100 + 288 = 1388`

When a node in the blinded route receives an htlc, the onion will not contain the `amt_to_forward`
or `outgoing_cltv_value`. They will have to compute them based on the fields contained in their
`encrypted_data` (`fee_base_msat`, `fee_proportional_millionths` and `cltv_expiry_delta`).

For example, here is how Carol will compute the values for the htlc she relays to Bob:

* `amount = ceil((100302 - fee_base_msat) / (1 + fee_proportional_millionths)) = 100152 msat`
* `expiry = 1388 - cltv_expiry_delta = 1244`

And here is how Bob computes the values for the htlc he relays to Alice:

* `amount = ceil((100152 - fee_base_msat) / (1 + fee_proportional_millionths)) = 100002 msat`
* `expiry = 1244 - cltv_expiry_delta = 1100`

Note that as the rounding errors aggregate, the recipient will receive slightly more than what was
expected. The sender includes `amt_to_forward` in the onion payload for the recipient to let them
verify that the received amount is (slightly) greater than what the sender intended to send (which
protects against intermediate nodes that would try to relay a lower amount).

The messages exchanged will contain the following values:

```text
     Eve                                          Dave                                                   Carol                                                   Bob                                         Alice
      |             update_add_htlc                |              update_add_htlc                          |             update_add_htlc                          |             update_add_htlc                |
      |     +--------------------------------+     |      +------------------------------------------+     |     +------------------------------------------+     |     +--------------------------------+     |
      |     |  amount: 100322 msat           |     |      |  amount: 100302 msat                     |     |     |  amount: 100152 msat                     |     |     |  amount: 100002 msat           |     |
      |     |  expiry: 1412                  |     |      |  expiry: 1388                            |     |     |  expiry: 1244                            |     |     |  expiry: 1100                  |     |
      |     |  onion_routing_packet:         |     |      |  onion_routing_packet:                   |     |     |  onion_routing_packet:                   |     |     |  onion_routing_packet:         |     |
      |     | +----------------------------+ |     |      | +--------------------------------------+ |     |     | +--------------------------------------+ |     |     | +----------------------------+ |     |
      | --> | | amount_fwd: 100302 msat    | | --> | -->  | | blinding_eph_key: E(carol)           | | --> | --> | | encrypted_data:                      | | --> | --> | | amount_fwd: 100000 msat    | | --> |
      |     | | outgoing_expiry: 1388      | |     |      | | encrypted_data:                      | |     |     | | +----------------------------------+ | |     |     | | outgoing_expiry: 1100      | |     |
      |     | | scid: scid_dave_to_carol   | |     |      | | +----------------------------------+ | |     |     | | | scid: scid_bob_to_alice          | | |     |     | | encrypted_data:            | |     |
      |     | +----------------------------+ |     |      | | | scid: scid_carol_to_bob          | | |     |     | | | fee_base_msat: 100               | | |     |     | | +-----------------------+  | |     |
      |     | | blinding_eph_key: E(carol) | |     |      | | | fee_base_msat: 100               | | |     |     | | | fee_proportional_millionths: 500 | | |     |     | | | path_id: preimage     |  | |     |
      |     | | encrypted_data(carol)      | |     |      | | | fee_proportional_millionths: 500 | | |     |     | | | htlc_minimum_msat: 1000          | | |     |     | | | max_cltv_expiry: 1200 |  | |     |
      |     | +----------------------------+ |     |      | | | htlc_minimum_msat: 1000          | | |     |     | | | cltv_expiry_delta: 144           | | |     |     | | +-----------------------+  | |     |
      |     | | encrypted_data(bob)        | |     |      | | | cltv_expiry_delta: 144           | | |     |     | | | max_cltv_expiry: 1344            | | |     |     | +----------------------------+ |     |
      |     | +----------------------------+ |     |      | | | max_cltv_expiry: 1488            | | |     |     | | +----------------------------------+ | |     |     |  tlv_extension                 |     |
      |     | | amount_fwd: 100000 msat    | |     |      | | +----------------------------------+ | |     |     | +--------------------------------------+ |     |     | +----------------------------+ |     |
      |     | | outgoing_expiry: 1100      | |     |      | +--------------------------------------+ |     |     | | amount_fwd: 100000 msat              | |     |     | | blinding_eph_key: E(alice) | |     |
      |     | | encrypted_data(alice)      | |     |      | | encrypted_data(bob)                  | |     |     | | outgoing_expiry: 1100                | |     |     | +----------------------------+ |     |
      |     | +----------------------------+ |     |      | +--------------------------------------+ |     |     | | encrypted_data(alice)                | |     |     +--------------------------------+     |
      |     +--------------------------------+     |      | | amount_fwd: 100000 msat              | |     |     | +--------------------------------------+ |     |                                            |
      |                                            |      | | outgoing_expiry: 1100                | |     |     |  tlv_extension                           |     |                                            |
      |                                            |      | | encrypted_data(alice)                | |     |     | +--------------------------------------+ |     |                                            |
      |                                            |      | +--------------------------------------+ |     |     | | blinding_eph_key: E(bob)             | |     |                                            |
      |                                            |      +------------------------------------------+     |     | +--------------------------------------+ |     |                                            |
      |                                            |                                                       |     +------------------------------------------+     |                                            |
      |                                            |                                                       |                                                      |                                            |
```

Note that all onion payloads are described in each `update_add_htlc` for clarity, but only the
first one can be decrypted by the intermediate node that receives the message (standard Bolt 4
onion encryption).

## Attacks

### Unblinding channels with payment probing

Recipients must be careful when using route blinding for payments to avoid letting attackers
guess which nodes are hidden inside of the route. Let's walk through an attack to understand
why.

Let's assume that our routing graph looks like this:

```text
               +-------+      +-------+
               |   X   |      |   X   |
               +-------+      +-------+
                   |              |
                   |              |
+-------+      +-------+      +-------+      +-------+
|   X   |------| Carol |------|  Bob  |------| Alice |
+-------+      +-------+      +-------+      +-------+
                   |              |
                   |              |
               +-------+      +-------+
               |   X   |      |   X   |
               +-------+      +-------+
```

Alice creates a blinded route `Carol -> Bob -> Alice`.
Alice has chosen what fee settings will be used inside the blinded route.
Let's assume she has chosen `fee_base_msat = 10` and `fee_proportional_millionths = 100`.

The attacker knows that the recipient is at most two hops away from Carol. Instead of making the
payment, the attacker watches for new `channel_update`s for every channel in a two-hops radius
around Carol. At some point, the attacker sees a `channel_update` for the channel `Bob -> Alice`
that sets `fee_proportional_millionths = 150`, which exceeds what Alice has chosen for the blinded
route. The attacker then tries to make the payment.

When Bob receives the payment, the fees are below its current settings, so it should reject it.
The attacker would then receive a failure, and be able to infer that it's very likely that Alice
is the final recipient.

If the attackers are able to frequently request invoices from the recipient (e.g. from a Bolt 12
offer), they don't even have to attempt the payment to detect this. They can simply periodically
request invoices from the recipient and detect when the recipient raises the fees or cltv of the
blinded route, and match that with recent `channel_update`s that they received.

Similarly, feature bits that apply to payment relaying behavior can be used to fingerprint nodes
inside the blinded route: this is why `allowed_features` are committed inside the `encrypted_data`.

If nodes across the network use different values for `htlc_minimum_msat`, it can also be used to
fingerprint nodes: that's why it is also committed inside the `encrypted_data`.

This type of attack is the reason why all parameters that affect payment relaying behavior (fees,
cltv, features, etc) are chosen by the recipient. The recipient should add a large enough margin
to the current values actually used by nodes inside the route to protect against future raises.
This is also why blinded routes used for payments have a `max_cltv_expiry` set by the recipient,
even though that doesn't fully address the issue if the attackers are able to frequently request
new blinded routes.

Altruistic relaying nodes inside a blinded route could choose to relay payments with fees below
their current settings, which would break this heuristic: however their economic incentive is to
reject them, so we cannot rely on them to protect recipient privacy.

Similarly, we mandate relaying nodes to only accept payments using exactly the fees provided in
the `encrypted_data` payload. Otherwise, when observing a `channel_update` that raises a specific
channel's fees, the attackers could try to use these new fees in a payment attempt: if the payment
goes through, they would have even more confidence about the channel used in the blinded route.
The incentives for relaying nodes aren't great, because we're asking them to reject payments that
give them the right amount of fees to protect recipient privacy.

### Unblinding nodes after restart

The attacks described in the previous section only applied to scenarios that use route blinding
for payments. However, a variation of the same technique can be used for any scenario relying on
route blinding to relay messages.

If attackers suspect that a given node `N` may be part of a blinded route, they can wait for that
node to go offline, and try using the blinded route while the node is offline. If the blinded
route fails, it's likely that this node was indeed part of the blinded route. By repeating this
sampling regularly, attackers can increase the confidence in their unblinding.

To address this, recipients should choose nodes with high uptime for their blinded routes and
periodically refresh them.

## Tips and Tricks

### Recipient pays fees

It may be unfair to make payers pay more fees to accomodate the recipient's wish for anonymity.
It should instead be the recipient that pays the fees of the blinded hops (and the payer pays the
fees to reach the introduction point).

If a merchant is selling an item for `N` satoshis, it should create an invoice for `N-f` satoshis,
where `f` is the fee of the blinded part of the route.

### Dummy hops

The sender knows an upper bound on the distance between the recipient and `N(0)`. If the recipient
is close to `N(0)`, this might not be ideal. In such cases, the recipient may add any number of
dummy hops at the end of the blinded route by using `N(j) = N(r)`. The sender will not be able to
distinguish those from normal blinded hops.

NB:

* the recipient needs to fully validate each dummy hop's onion payload to detect tampering (and
  must ensure that these hops have been used and not truncated)
* the recipient must use padding to ensure all `encrypted_data` payloads have the same length,
  otherwise the payer will be able to guess which hop is actually the recipient

### Wallets and unannounced channels

Route blinding is particularly useful for wallets that are connected to nodes via unannounced
channels. Such wallets could use a single blinded hop, which effectively hides their `node_id`
and `scid` from the sender. It obviously reveals to the blinded node that the next node is the
final recipient, but a wallet that's not online all the time with a stable IP will never be able
to hide that information from the nodes it connects to anyway (even with rendezvous).

### Blinded trampoline route

Route blinding can also be used with trampoline very easily. Instead of providing the
`outgoing_channel_id` in `encrypted_data`, we simply need to provide the `outgoing_node_id`.

Each trampoline node can then decrypt the `node_id` of the next node and compute `E(i)` for the
next trampoline node. That `E(i)` can then be sent in the outer onion payload instead of using the
lightning message's fields, which is even cleaner and doesn't require nodes between trampoline
nodes to understand route blinding.

## FAQ

### Why not use rendezvous

While rendezvous is more private, it's also less flexible: senders cannot add data to the partial
onion nor reuse it. When used for payments, the amount must be fixed ahead of time in the partial
onion, which doesn't combine well with multi-part payments or temporary liquidity issues.

Route blinding lets senders choose most of the data they put in the onion payloads, which makes
it much more flexible, at the expense of introducing more probing surface for attackers.

### Why not use HORNET

HORNET requires a slow session setup before it can provide useful speedups. In cases where you
expect to send a single message per session (which is the case for payments and onion messages),
HORNET actually performs worse than Sphinx in latency, bandwidth and privacy.
