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

Lightning is a new protocol that sits on top of Bitcoin and that
supports faster, cheaper, and more scalable payments.

### What is Bitcoin?

Bitcoin  is  a  cryptocurrency  system that  supports  the  trustless,
pseudonymous, decentralized exchange of value. This allows currency to
be exchanged without the need for a central authority, creating a more
democratic  system  where  each  participant  is in  charge  of  their
financial destiny.

The Bitcoin network as it currently stands works well for certain
types of transactions, particularly purchases involving non-negligible
amounts of currency where settlement does not need to be instantaneous.

However, the configuration of the Bitcoin network also faces specific
challenges:

   * _Bitcoin Has Notable Fees._ Any Bitcoin transaction requires that
     fees be paid to the miners who compile those transactions into
     blocks, then add them to the blockchain. These fees were
     negligible in the early days of Bitcoin, but as the network
     became more busy and as the value of Bitcoin increased, these
     fees increased as well. Bitcoin fees spiked as high as $50 USD
     during a period of network congestion in late 2017, but generally
     fees ran in the [$1-2
     USD](https://bitinfocharts.com/comparison/bitcoin-transactionfees.html)
     range for much of 2017-2018 — which might be OK for purchasing a
     year's worth of server time, but not for downloading an ebook.

   * _Bitcoin Has Slow Settlement Times._ Bitcoin transactions can
     only be trusted after they have been verified and included in a
     block. Because Bitcoin blocks are created, on average, every ten
     minutes, the expected value of the wait is five minutes. It can,
     however, take much longer: if a transaction includes a low fee,
     it might take several blocks for it to be included. This could
     raise the expected value before a transaction is verified to 15
     minutes or 25 minutes or even an hour and five minutes. But even
     after a transaction has been included in a block, it's still not
     entirely trustworthy because there's the opportunity for
     short-term reversals on the blockchain, where a block becomes
     orphaned because a competing block was accepted first. Sometimes
     chains of orphaned blocks can form, before Bitcoin settles on a
     consensus for which is the main chain. For this reason it's
     generally suggested that six blocks be processed before a
     transaction is truly considered final. You put that all together
     and the trusted settlement time on Bitcoin can run 1-2
     hours. That's a long time to wait for a cup of coffee.

   * _Bitcoin Has Scalability Issues._ The [Lightning Network
     Whitepaper](https://lightning.network/lightning-network-paper.pdf)
     notes that the Visa payment network reached 47,000 transactions
     per second (tps) during the 2013 holidays. In contrast, the
     maximum tps of Bitcoin is estimated to be [7
     tps](http://www.comp.nus.edu.sg/~prateeks/papers/Bitcoin-scaling.pdf)
     at a maximum block size of 1MB. Even getting to the average Visa
     tps of 2000-4000 tps is an almost unimaginable jump because it's
     constrained by other issues than block size, such as the overall
     size of the blockchain itself.

To resolve all of these challenges requires something more than just
Bitcoin.

### What is Lightning?

The Lightning Network is a layer-2 protocol (i.e. it sits atop a lower
layer blockchain, rather than replacing it) that acts as a payment
channel (i.e. it's designed to allow participants to make Bitcoin
transactions without committing them to the blockchain).

In its simplest form, Lightning is a bidirectional payment
channel. Two participants jointly lock up funds that they plan to
exchange with each other. First, they must decide how much of those
initial funds belongs to each person. Then, as they transact with
each other, they must make new agreements about the current ownership
of their joint funds. This all occurs off-chain, without anything
being written to the blockchain. At any time, either participant can
close out the payment channel, which settles the final agreement for
the funds to the blockchain.

However, Lightning is bigger than that: it's a _Network_ formed by
multiple participants who all have bidirectional payments channels.
Payments can be sent across a route on this network, with each pair of
people adjusting their funds agreement appropriately to allow movement
of a payment from a participant to a more distant participant.

### How Does Lightning Improve on Bitcoin?

The Lightning Network resolves many of the problems that prevent
Bitcoin from being used as an everyday currency. Though you probably
wouldn't use Bitcoin itself to buy a newspaper or a cup or a coffee, or to
pay a tip or patronage fee on the internet, you can do so with Lightning.

   * _Lightning Has Rapid Settlement._ Because the Lightning Network
     only writes to the blockchain when initially funding a Lightning
     channel and when closing out that channel, settlement can be very
     rapid. In fact, it's almost instantaneous. There are some caveats:
     it can take a while to initially get funds onto the Lightning
     Network and (in some situations) to settle them back to the
     Bitcoin network; and it's possible for funds to get temporarily
     locked up if a route failed. However, once cryptocurrency is in
     the Lightning Network, it can be transacted very quickly most of
     the time.

   * _Lightning Has Lower Fees._ For each Lightning channel,
     transactions are only written to the blockchain twice: once when
     the channel is funded and once when it is closed. The fees for
     these on-chain transactions will be quickly amortized if the
     channel is used for multiple transactions. There are some fees
     for using the Lightning Network itself: these are paid to
     processing nodes in a route, who act as intermediaries between a
     payer and their payee, in return for temporarily tying up their
     funds. However, they are negligible amounts compared to Bitcoin
     fees.

   * _Light Supports Micropayments._ Because of its lower fees, the
     Lightning Network enables micropayments. Not only can the
     Lightning Network be used to pay for that newspaper or cup of
     coffee, where the few dollar cost of the purchase would have been
     matched by a few dollar fee on Bitcoin, but they can also be used
     to pay tips, to acquire individual articles or stories, or to
     make similar purchases where the cost might be measured in cents,
     not dollars.

   * _Lightning Improves Privacy._ Because the blockchain is an
     immutable ledger, everything written to it is there permanently,
     which impacts privacy. Because the Lightning Network only writes
     its initial funding and its final settlement to the blockchain,
     privacy is considerably improved. All that can be seen is that
     one person exchanged funds with one other person.

   * _Lightning Improves Scalability._ Bitcoin has scalability
     limitations because of the block size limit, because of the
     necessity of broadcasting all of the blocks, and because of the
     requirement that full nodes to store all of those blocks
     forever. The Lightning Network resolves all of these issues
     because it rarely logs to the blockchain and in fact doesn't have
     any type of permanent data storage, except between peers. By
     moving payments off-chain to the Lightning Network, Bitcoin can
     dramatically ramp up its own scalability.

   * _Lightning Improves Cross-Chain Swaps._ Because Lightning Network
     transactions are atomic in nature, they allow for almost
     instantaneous atomic cross-chain swaps, where cryptocurrency on
     one blockchain can be exchanged for cryptocurrency on another
     blockchain. This extends all of the advantages of Lightning, such
     as high speed, low feeds, and improved privacy to cross-chain
     swaps.

Though the Lightning Network has many strengths, it has weaknesses
too. Peer failures where hops in a route are unresponsive can notably
delay payments. High-value payments can also be troublesome, because
every hop in the route must have sufficient funds. However, every
technology has its advantages and weaknesses; the right one must
simply be chosen for each use case.

### How Does Lightning Work?

These BOLTS as a whole describe how Lightning works, in specific and
technical detail. What follows is only an overview, slightly expanding
on the summary so far with a gloss of the technical features of the
technology.

#### Setting Up a Lightning Channel

Interaction with the Lightning Network begins when a pair of Bitcoin
users create a _funding transaction_. This is a transaction that is
signed by two participants and placed on the blockchain. It locks the
funds that will be used by the participants on the Lightning Network.

A _commitment transaction_ identifies how much of the funds are owned
by each of the two parties. It always appears in two forms: a
commitment signed by the first party is given to the second party; and
a commitment signed by the second party is given to the first
party. An initial pair of commitment transactions is created before
the funding transaction is placed on the blockchain, but the
commitment transaction is kept off-chain (at least for now).

This establishes a _channel_, of you prefer a Lightning payment
channel, between these two participants.

_See [Bolt #2](02-peer-protocol.md#channel-establishment) for more on
channel establishment and [Bolt
#3](03-transactions.md#funding-transaction-output) for the format of
the funding transaction. Also see [Bolt #1](01-messaging.md) for the
basics of Lightning messaging and [Bolt #8](08-transport.md) for
Lightning message encryption._

#### Using a Lightning Channel

When the two participants in a Lightning channel want to transact,
they virtually exchange funds by creating an updated pair of
_commitment transactions_, which shows a new version of how much of
the original funds are now owned by each of the two parties.

As with the commitment transactions created as part of the channel
establishment, these updated commitment transactions are cross-signed
by the respective counterparties, but they are not placed on the
blockchain at the time. In fact, placing commitment transactions on
the blockchain is how a channel is closed, finalizing the allocation
of the initial funds.

_See [Bolt #3](03-transactions.md#commitment-transaction) for the
format of the commitment transactions._

#### Misusing a Lightning Channel

The latest _commitment transaction_ is the one that lists the most
up-to-date state of the funds in a Lightning channel. However, a
mechanism is required to keep either participant from broadcasting an
out-of-date commitment transaction that might benefit them more.

This is part of the design of the commitment transactions. Each
participant has one that is uniquely identified as belonging to
them. If they sign it and place it on the blockchain, they must wait
before they receive the funds. If it was an old commitment
transaction, the counterparty is given the opportunity to take all of
the funds for themselves as a _penalty transaction_.

_Again see [Bolt #3](03-transactions.md#commitment-transaction) for
the format of the commitment transactions. See [Bolt
#5](05-onchain.md#revoked-transaction-close-handling) for the Revoked
Transaction Close Handling that is used to close out a channel if an
older commitment transaction is misused in this way._

#### Extending to the Lightning Network

The Lightning Network is far more than a single Lightning channel:
it's a collection of channels that can be together used to route
payment to and from more distant participants. There are specific
methods for node and channel discovery, which allow Lightning
participants to build maps of the network around them, in order to
identify distant participants

_See [Bolt #7](7-routing-gossip.md) for Node and Channel
Discovery. Also see [Bolt #10](10-dns-bootstrap.md) for DNS Bootstrap
and Assisted Node Discovery and finally [Bolt #9](09-features.md) for
flags that identify features on channels and nodes._

Once a participant has identified a distant participant and a _route_
to get to them, he can send his payment from his _origin node_ to the
_final node_ via a number of _hops_.

A transaction is propagated across a route by each participant sending
the payment to the next hop in the route and receiving payment from
the previous hop in the route. In order for this to be trustless, a
timelocked transaction is created between each pair of nodes in the
route, with the timelocks being shortest near the final node and
increasingly long nearer the origin node. This is done through
_HTLCs_, or Hashed Time Locked Contracts.

When a series of timelocked transactions successfully spans the entire
route, the final node releases the secret for the HTLC, a _payment
preimage_. Running through the route in reverse order, each _receiving
peer_ now has an increasing amount of time to use that same secret to
release the payment made to them from their _sending peer_. (If the
secret is never released, then all the HTLCs just time out, and no
funds are transferred.)

_See [Bolt #2](02-peer-protocol.md#normal-operation) for the normal
operation of the Lightning network and [Bolt #4](04-onion-routing.md)
for the Onion Routing Protocol._

#### Invoicing for Lightning Payments

Payments are not made to addresses on the Lightning Network, as is the
case with Bitcoin. Instead, a participant must generate a one-time
_invoice_. This is a QR-code-ready protocol for requesting
payments. The invoice includes a request for a certain amount of a
certain cryptocurrency, additional invoice data such as fees and
expiry, some technical data, and a signature. The signature allows the
payer to determine the node that the payment should be sent to.

_See [Bolt #11](11-payment-encoding.md) for the format of Lightning
Network invoices._

#### Closing a Lightning Channel

A Lightning channel can be closed in one of three ways.

A _mutual close_ occurs when two peered participants agree to close
their _channel_ together. They create a new output for their _funding
transaction_ that shares the funds appropriately and place that
transaction on the blockchain. They will both be able to access their
funds almost immediately.

_See [Bolt #2](https://github.com/lightningnetwork/lightning-rfc/blob/master/02-peer-protocol.md#channel-close) for mutual channel closing._

A _unilateral close_ occurs when a participant can not get the
assistance of their peer to close their _channel_. They simply sign
and place their final _commitment transaction_ on the blockchain, but
must wait for a timelock to expire before they can access their
funds. (Their uncooperative peer will be able to access their own
share of the funds immediately.)

_See [Bolt
#5](https://github.com/lightningnetwork/lightning-rfc/blob/master/05-onchain.md#unilateral-close-handling-local-commitment-transaction)
unilateral channel closing._

A _revoked transaction close_ occurs when a participant signs and
places an old, _revoked commitment transaction_ on the
blockchain. Their peer on the channel will be able to claim all of the
funds as a _penalty transaction_ if they do so before the
transaction's timelock expires.

_Again see [Bolt #5](05-onchain.md#revoked-transaction-close-handling) for _revoked transaction closing_.

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
