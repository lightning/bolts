# BOLT #0: Introduction and Index

Welcome, friend! These Basis of Lightning Technology (BOLT) documents
describe a layer-2 protocol for off-chain bitcoin transfer by mutual
cooperation, relying on on-chain transactions for enforcement if
necessary.

Some requirements are subtle; we have tried to highlight motivations
and reasoning behind the results you see here. I'm sure we've fallen
short; if you find any part confusing or wrong, please contact us and
help us improve.

This is version 0.

1. [BOLT #1](01-messaging.md): Base Protocol
2. [BOLT #2](02-peer-protocol.md): Peer Protocol for Channel Management
3. [BOLT #3](03-transactions.md): Bitcoin Transaction and Script Formats
4. [BOLT #4](04-onion-routing.md): Onion Routing Protocol
5. [BOLT #5](05-onchain.md): Recommendations for On-chain Transaction Handling
7. [BOLT #7](07-routing-gossip.md): P2P Node and Channel Discovery
8. [BOLT #8](08-transport.md): Encrypted and Authenticated Transport
9. [BOLT #9](09-features.md): Assigned Feature Flags
10. [BOLT #10](10-dns-bootstrap.md): DNS Bootstrap and Assisted Node Location
11. [BOLT #11](11-payment-encoding.md): Invoice Protocol for Lightning Payments

## The Spark: A Short Introduction to Lightning

Lightning is a protocol for fast payments using Bitcoin, using a
network of channels.

### Channels

Lightning works by establishing *channels*: two participants share
custody of some bitcoin (e.g. 0.1 bitcoin), spendable only with both
their signatures.

Initially they each hold a bitcoin transaction which sends all the
bitcoin (e.g. 0.1) back to one party.  They can sign a new bitcoin
transaction which splits these funds differently, e.g. 0.09 to one
party, 0.01 to the other, and invalidate the previous bitcoin
transaction so it won't be spent.

See [BOLT #2: Channel Establishment](02-peer-protocol.md#channel-establishment) for more on
channel establishment and [BOLT #3: Funding Transaction Output](03-transactions.md#funding-transaction-output) for the format of the bitcoin transaction which creates the channel.  See [BOLT #5: Recommendations for On-chain Transaction Handling](05-onchain.md) for the requirements when peers disagree or fail, and the cross-signed bitcoin transaction must be spent.

### Conditional Payments

The participants can add a conditional payment to the channel,
e.g. "you get 0.01 bitcoin if you reveal the secret within 6 hours".
Once the recipient presents the secret, that bitcoin transaction is
replaced with one lacking the conditional payment and adding the funds
to that recipient's output.

See [BOLT #2: Adding an HTLC](02-peer-protocol.md#adding-an-htlc-update_add_htlc) for the commands a participant uses to add a conditional payment, and [BOLT #3: Commitment Transaction](03-transactions.md#commitment-transaction) for the
complete format of the bitcoin transaction.

### Forwarding

Such a conditional payment can be safely forwarded to another
participant, e.g. "you get 0.01 bitcoin if you reveal the secret
within 5 hours".  This allows channels to be chained for payments
without trusting the intermediaries.

See [BOLT #2: Forwarding HTLCs](02-peer-protocol.md#forwarding-htlcs) for details on forwarding payments, [BOLT #4: Packet Structure](04-onion-routing.md#packet-structure) for how payment instructions are transported.

### Network Topology

To make a payment, a participant needs to know what channels it can
send through.  Participants tell each other about channel and node
creation, and updates.

See [BOLT #7: P2P Node and Channel Discovery](07-routing-gossip.md)
for details on the communication protocol, and [BOLT #10: DNS
Bootstrap and Assisted Node Location](10-dns-bootstrap.md) for initial
network bootstrap.

### Payment Invoicing

To know what payments to make, [BOLT #11: Invoice Protocol for Lightning Payments](11-payment-encoding.md) presents the protocol for describing the destination and purpose of a payment such that the payer can later prove successful payment.


## Glossary and Terminology Guide

* *Node*:
   * A computer or other device connected to the Bitcoin network.

* *Peers*:
   * *Nodes* transacting bitcoins with one another through a *channel*.

* *MSAT*:
   * A millisatoshi, often used as a field name.

* *Funding transaction*:
   * An irreversible on-chain transaction that pays to both *peers* on a *channel*.
   It can only be spent by mutual consent.

* *Channel*:
   * A fast, off-chain method of mutual exchange between two *peers*.
   To transact funds, peers exchange signatures to create an updated *commitment transaction*.

* *Commitment transaction*:
   * A transaction that spends the *funding transaction*.
   Each *peer* holds the other peer's signature for this transaction, so that each
   always has a commitment transaction that it can spend. After a new
   commitment transaction is negotiated, the old one is *revoked*.

* *HTLC*: Hashed Time Locked Contract.
   * A conditional payment between two *peers*: the recipient can spend
    the payment by presenting its signature and a *payment preimage*,
    otherwise the payer can cancel the contract by spending it after
    a given time. These are implemented as outputs from the
    *commitment transaction*.

* *Payment hash*:
   * The *HTLC* contains the payment hash, which is the hash of the
    *payment preimage*.

* *Payment preimage*:
   * Proof that payment has been received, held by
    the final recipient, who is the only person who knows this
    secret. The final recipient releases the preimage in order to
    release funds. The payment preimage is hashed as the *payment hash*
    in the *HTLC*.

* *Commitment revocation secret key*:
   * Every *commitment transaction* has a unique *commitment revocation* secret-key
    value that allows the other *peer* to spend all outputs
    immediately: revealing this key is how old commitment
    transactions are revoked. To support revocation, each output of the
    commitment transaction refers to the commitment revocation public key.

* *Per-commitment secret*:
   * Every *commitment transaction* derives its keys from a per-commitment secret,
     which is generated such that the series of per-commitment secrets
     for all previous commitments can be stored compactly.

* *Mutual close*:
   * A cooperative close of a *channel*, accomplished by broadcasting an unconditional
    spend of the *funding transaction* with an output to each *peer*
    (unless one output is too small, and thus is not included).

* *Unilateral close*:
   * An uncooperative close of a *channel*, accomplished by broadcasting a
    *commitment transaction*. This transaction is larger (i.e. less
    efficient) than a *mutual close* transaction, and the peer whose
    commitment is broadcast cannot access its own outputs for some
    previously-negotiated duration.

* *Revoked transaction close*:
   * An invalid close of a *channel*, accomplished by broadcasting a revoked
    *commitment transaction*. Since the other *peer* knows the
    *commitment revocation secret key*, it can create a *penalty transaction*.

* *Penalty transaction*:
   * A transaction that spends all outputs of a revoked *commitment
    transaction*, using the *commitment revocation secret key*. A *peer* uses this
    if the other peer tries to "cheat" by broadcasting a revoked
    *commitment transaction*.

* *Commitment number*:
   * A 48-bit incrementing counter for each *commitment transaction*; counters
    are independent for each *peer* in the *channel* and start at 0.

* *It's ok to be odd*:
   * A rule applied to some numeric fields that indicates either optional or
     compulsory support for features. Even numbers indicate that both endpoints
     MUST support the feature in question, while odd numbers indicate
     that the feature MAY be disregarded by the other endpoint.

* `chain_hash`:
   * Used in several of the BOLT documents to denote the genesis hash of a
     target blockchain. This allows *nodes* to create and reference *channels* on
     several blockchains. Nodes are to ignore any messages that reference a
     `chain_hash` that are unknown to them. Unlike `bitcoin-cli`, the hash is
     not reversed but is used directly.

     For the main chain Bitcoin blockchain, the `chain_hash` value MUST be
     (encoded in hex):
     `6fe28c0ab6f1b372c1a6a246ae63f74f931e8365e15a089c68d6190000000000`.

## Theme Song

      Why this network could be democratic...
      Numismatic...
      Cryptographic!
      Why it could be released Lightning!
      (Release Lightning!)


      We'll have some timelocked contracts with hashed pubkeys, oh yeah.
      (Keep talking, whoa keep talkin')
      We'll segregate the witness for trustless starts, oh yeah.
      (I'll get the money, I've got to get the money)
      With dynamic onion routes, they'll be shakin' in their boots;
      You know that's just the truth, we'll be scaling through the roof.
      Release Lightning!
      (Go, go, go, go; go, go, go, go, go, go)


      [Chorus:]
      Oh released Lightning, it's better than a debit card..
      (Release Lightning, go release Lightning!)
      With released Lightning, micropayments just ain't hard...
      (Release Lightning, go release Lightning!)
      Then kaboom: we'll hit the moon -- release Lightning!
      (Go, go, go, go; go, go, go, go, go, go)


      We'll have QR codes, and smartphone apps, oh yeah.
      (Ooo ooo ooo ooo ooo ooo ooo)
      P2P messaging, and passive incomes, oh yeah.
      (Ooo ooo ooo ooo ooo ooo ooo)
      Outsourced closure watch, gives me feelings in my crotch.
      You'll know it's not a brag when the repo gets a tag:
      Released Lightning.


      [Chorus]
      [Instrumental, ~1m10s]
      [Chorus]
      (Lightning! Lightning! Lightning! Lightning!
       Lightning! Lightning! Lightning! Lightning!)


      C'mon guys, let's get to work!


   -- Anthony Towns <aj@erisian.com.au>

## Authors

[ FIXME: Insert Author List ]

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
