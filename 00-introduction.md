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

## Glossary and Terminology Guide

* *Announcement*:
   * A gossip message sent between *peers* intended to aid the discovery of a *channel* or a *node*.

* `chain_hash`:
   * The genesis hash of a
     target blockchain. This allows *nodes* to create and reference *channels* on
     several blockchains. Nodes are to ignore any messages that reference a
     `chain_hash` that are unknown to them. Unlike `bitcoin-cli`, the hash is
     not reversed but is used directly.

     For the main chain Bitcoin blockchain, the `chain_hash` value MUST be
     (encoded in hex):
     `6fe28c0ab6f1b372c1a6a246ae63f74f931e8365e15a089c68d6190000000000`.

* *Channel*:
   * A fast, off-chain method of mutual exchange between two *peers*.
   To transact funds, peers exchange signatures to create an updated *commitment transaction*.
   * _See closure methods: mutal close, revoked transaction close, unilateral close_

* *Closing transaction*:
   * A transaction generated as part of a _mutual close_. A closing transaction is similar to a _commitment transaction_, but with no pending payments.
   * _See related: commitment transaction, funding transaction, penalty transaction_

* *Commitment number*:
   * A 48-bit incrementing counter for each *commitment transaction*; counters
    are independent for each *peer* in the *channel* and start at 0.
   * _See container: commitment transaction_
   * _See related: closing transaction, funding transaction, penalty transaction_

* *Commitment revocation private key*:
   * Every *commitment transaction* has a unique commitment revocation private-key
    value that allows the other *peer* to spend all outputs
    immediately: revealing this key is how old commitment
    transactions are revoked. To support revocation, each output of the
    commitment transaction refers to the commitment revocation public key.
   * _See container: commitment transaction_
   * _See originator: per-commitment secret_

* *Commitment transaction*:
   * A transaction that spends the *funding transaction*.
   Each *peer* holds the other peer's signature for this transaction, so that each
   always has a commitment transaction that it can spend. After a new
   commitment transaction is negotiated, the old one is *revoked*.
   * _See parts: commitment number, commitment revocation private key, HTLC, per-commitment secret_
   * _See related: closing transaction, funding transaction, penalty transaction_
   * _See types: revoked commitment transaction_

* *Final node*:
   * The final recipient of a packet that is routing a payment from an _origin node_ through some number of _hops_. It is also the final *receiving peer* in a chain.
   * _See category: node_
   * _See related: origin node, processing node_

* *Funding transaction*:
   * An irreversible on-chain transaction that pays to both *peers* on a *channel*.
   It can only be spent by mutual consent.
   * _See related: closing transaction, commitment transaction, penalty transaction_

* *Hop*:
   * A *node*. Generally, an intermmediate node lying between an *origin node* and a *final node*.
   * _See category: node_

* *HTLC*: Hashed Time Locked Contract.
   * A conditional payment between two *peers*: the recipient can spend
    the payment by presenting its signature and a *payment preimage*,
    otherwise the payer can cancel the contract by spending it after
    a given time. These are implemented as outputs from the
    *commitment transaction*.
   * _See container: commitment transaction_
   * _See parts: Payment hash, Payment preimage_

* *It's ok to be odd*:
   * A rule applied to some numeric fields that indicates either optional or
     compulsory support for features. Even numbers indicate that both endpoints
     MUST support the feature in question, while odd numbers indicate
     that the feature MAY be disregarded by the other endpoint.

* *MSAT*:
   * A millisatoshi, often used as a field name.

* *Mutual close*:
   * A cooperative close of a *channel*, accomplished by broadcasting an unconditional
    spend of the *funding transaction* with an output to each *peer*
    (unless one output is too small, and thus is not included).
   * _See related: revoked transaction close, unilateral close__

* *Node*:
   * A computer or other device that is part of the Lightning network.
   * _See related: peers_
   * _See types: final node, hop, origin node, processing node, receiving node, sending node_

* *Origin node*:
   * The _node_ that originates a packet that will route a payment through some number of _hops_ to a _final node_. It is also the first _sending peer_ in a chain.
   * _See category: node_
   * _See related: final node, processing node_

* *Payment hash*:
   * The *HTLC* contains the payment hash, which is the hash of the
    *payment preimage*.
   * _See container: HTLC_
   * _See originator: payment preimage_

* *Payment preimage*:
   * Proof that payment has been received, held by
    the final recipient, who is the only person who knows this
    secret. The final recipient releases the preimage in order to
    release funds. The payment preimage is hashed as the *payment hash*
    in the *HTLC*.
   * _See container: HTLC_
   * _See derivation: payment hash_

* *Peers*:
   * Two *nodes* that are in communication with each other.
      * Two peers may gossip with each other prior to setting up a channel.
      * Two peers may establish a *channel* through which they transact.
   * _See related: node_

* *Penalty transaction*:
   * A transaction that spends all outputs of a *revoked commitment
    transaction*, using the *commitment revocation private key*. A *peer* uses this
    if the other peer tries to "cheat" by broadcasting a *revoked
    commitment transaction*.
   * _See related: closing transaction, commitment transaction, funding transaction_

* *Per-commitment secret*:
   * Every *commitment transaction* derives its keys from a per-commitment secret,
     which is generated such that the series of per-commitment secrets
     for all previous commitments can be stored compactly.
   * _See container: commitment transaction_
   * _See derivation: commitment revocation private key_

* *Processing node*:
   * A *node* that is processing a packet that originated with an *origin node* and that is being sent toward a *final node* in order to route a payment. It acts as a _receiving peer_ to receive the message, then a _sending peer_ to send on the packet.
   * _See category: node_
   * _See related: final node, origin node_

* *Receiving node*:
   * A *node* that is receiving a message.
   * _See category: node_
   * _See related: sending node_

* *Receiving peer*:
   * A *node* that is receiving a message from a directly connected *peer*.
   * _See category: peer_
   * _See related: sending peer_

* *Revoked commitment transaction*:
   * An old *commitment transaction* that has been revoked because a new commitment transaction has been negotiated.
   * _See category: commitment transaction_
   
* *Revoked transaction close*:
   * An invalid close of a *channel*, accomplished by broadcasting a *revoked
    commitment transaction*. Since the other *peer* knows the
    *commitment revocation secret key*, it can create a *penalty transaction*.
   * _See related: mutal close, unilateral close_

* *Sending node*: 
   * A *node* that is sending a message.
   * _See category: node_
   * _See related: receiving node_

* *Sending peer*: 
   * A *node* that is sending a message to a directly connected *peer*.
   * _See category: peer_
   * _See related: receiving peer_.

* *Unilateral close*:
   * An uncooperative close of a *channel*, accomplished by broadcasting a
    *commitment transaction*. This transaction is larger (i.e. less
    efficient) than a *mutual close transaction*, and the *peer* whose
    commitment is broadcast cannot access its own outputs for some
    previously-negotiated duration.
   * _See related: mutual close, revoked transaction close_

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
