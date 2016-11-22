# BOLT #0: Introduction and Index

Welcome, friend!  These Basis of Lightning Technology (BOLT) documents
describe a layer-2 protocol for off-chain bitcoin transfer by mutual
cooperation, relying on on-chain transactions for enforcement if
necessary.

Some requirements are subtle; we have tried to highlight motivations
and reasoning behind the results you see here.  I'm sure we've fallen
short: if you find any part confusing, or wrong, please contact us and
help us improve.

This is version 0.

1. [BOLT #1](01-messaging-crypto-and-init.md): Message Format, Encryption, Authentication and Initialization
2. [BOLT #2](02-peer-protocol.md): Peer Protocol for Channel Management
3. [BOLT #3](03-transactions.md): Bitcoin Transaction and Script Formats
4. [BOLT #4](04-onion-routing.md): Onion Routing Protocol
5. [BOLT #5](05-onchain.md): Recommendations for On-chain Transaction Handling
6. [BOLT #6](06-irc-announcements.md): Interim Node and Channel Discovery

## Glossary and Terminology Guide

* *Funding Transaction*:
   * The on-chain, irreversible transaction which pays to both peers
         on a channel.  Thus it can only be spent by mutual consent.


* *Channel*:
   * A fast, off-chain method of mutual exchange between two *peers*.
         To move funds, they exchange signatures for an updated *commitment
         transaction*.


* *Commitment Transaction*:
   * A transaction which spends the funding transaction; each peers
         holds a signature from the other peer for this transaction, so it
         always has a commitment transaction it can spend.  After a new
         commitment transaction is negotiated, the old one is *revoked*.


* *HTLC*: Hashed Time Locked Contract.
   * A conditional payment between two peers: the recipient can spend
         the payment by presenting its signature and a *payment preimage*,
         otherwise the payer can cancel the contract by spending it after
         a given time.  These are implemented as outputs from the
         *commitment transaction*.


* *Payment hash, payment preimage*:
   * The HTLC contains the payment hash, which is the hash of the
         payment preimage.  Only the final recipient knows the payment
         preimage; thus when it reveals the preimage to collect funds is
         considered proof that it received the payment.


* *Commitment revocation key*:
   * Every *commitment transaction* has a unique *commitment revocation key*
         value which allows the other peer to spend all outputs
         immediately: revealing this key is how old commitment
         transactions are revoked.  To do this, each output refers to the
         commitment revocation pubkey.


* *Per-commitment secret*:
   * Every commitment derives its keys from a *per-commitment secret*,
     which is generated such that the series of per-commitment secrets
     for all prevoius commitments can be stored compactly.


* *Mutual Close*:
   * A cooperative close of a channel, by broadcasting an unconditional
         spend of the *funding transaction* with an output to each peer
         (unless one output is too small, and thus is not included).


* *Unilateral Close*:
   * An uncooperative close of a channel, by broadcasting a
         *commitment transaction*.  This transaction is larger (ie. less
         efficient) than a mutual close transaction, and the peer whose
         commitment is broadcast cannot access its own outputs for some
         previously-negotiated duration.


* *Revoked Transaction Close*:
   * An invalid close of the channel, by broadcasting a revoked
         *commitment transaction*.  Since the other peer knows the
         *commitment revocation secret key*, it can create a *penalty transaction*.


* *Penalty Transaction*:
   * A transaction which spends all outputs of a revoked commitment
         transaction, using the *commitment revocation secret key*.  A peer uses this
         if the other peer tries to "cheat" by broadcasting a revoked
         *commitment transaction*.


* *Commitment Number*:
   * A 48-bit incrementing counter for each *commitment transaction*; they
         are independent for each peer in the channel, and start at 0.


* *Channel shortid*:
   * An 8 byte globally unique identifier for the *funding transaction*
         (and thus for the channel).


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
