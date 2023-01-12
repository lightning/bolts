# Staking Credentials

This document specifies the Staking Credentials architecture and requirements for its constituents
protocols used for constructing privacy-preserving credentials mechanisms in the context of Bitcoin
contracting protocols.

This draft is version 0.1 of the Staking Credentials architecture.

## Introduction

Staking Credentials is an architecture for Bitcoin contracting protocols collateralizing based on
privacy-preserving credentials mechanisms derived from the Privacy Pass protocol.
Those credentials are not only unlinking the collaterals generation from their consumption, but also
allows user staking of credentials to decrease the collateral costs to enter in future Bitcoin contracts.
The quality and thresholds of collaterals can be selected with granularity by the contract provider
to achieve a satisfying level of risks, defined in a monetary strategy or reputation strategy in function
of the base collateral considered. Staking Credentials approach is the following: the clients present
a scarce asset (fees, stakes cerificates) and blinded credentials to the server, the credentials are
authenticated and yielded back to the client. Once unblinded the credentials can be used to fulfill a
contract request, the proofs, or credentials are anonymous in the sense that a given credential cannot
be linked to the protocol instance in which that credential was initially issued.

At a high level, the Staking Credentials architecture consists of two protocols: credentials issuance
and redemption. The issuance protocol runs between two endpoint referred to as Committer and Issuer and
one function: Collateral Authentication. The entity that implements the Collateral Authentication,
referred to as the Issuer, is responsible for counter-signing the collaterals in response to requests
from Committer. Issuer might offer different base Collateral in function of their risk strategy, and the
overhead cost they would like to transfer on the Committer for answering a contract request. Committer and
Issuer might agree on an Authentication method in function of the cryptographic properties aimed for.
The redemption protocol runs between two endpoint referred to as Client and Contract Provider and
one function: Collateral Pledge. The entity that implements the Collateral Pledge, referred to
as the Client, is responsible to provide an authenticated Credential covering the contract request
risk, as defined by the Contract Provider. A Client can be a Committer, but those entities can be also
dissociated. An Issuer can be a Contract Provider, but those entities can be also dissociated. A
Client might aggregate authenticated Credential from multiple Committer.

The Staking Credentials architecture primary deployment is to mitigate against channel jamming attacks
against the Lightning Network. Channel jamming is a type of attack where the adversary consumes a routing
hop liquidity, without any financial compensation in case of deliberate contract failure. As the failure
is non-dependent on the hop, there is a plain timevalue loss encumbered by the hop. Under the Staking
Credentials architecture, the HTLC sender must as a Committer secure an authenticated credential from a
routing hop as an Issuer in exchange of a scarce asset (on-chain payment, off-chain payment, etc). Then
the HTLC must as a Client attached this authenticated credential to a HTLC forward request presented to
the routing hop as Contract Provider. If the credential satisfies the routing hop risk-management policy
at that time, the HTLC forward is accepted and relayed forward along the payment path. The HTLC sender
must repeat this operation for as many routing hops there are in the payment path.

The credentials issuance and redemption protocols operate in concert as shown in the figure below:

```
			 	          ___________					                  ____________
  				         |	     |	     1. Scarce asset + Blinded Credentials 	 |	      |
				         |	     |-------------------------------------------------->|	      |
  3. Authenticated Unblinded Credentials |           |	      	    	                                 |	      | 5. Credentials Authentication Validation
				         | Committer |					                 |   Issuer   |
	     ----------------------------|	     |	    2. Authenticated Unblinded Credentials       |	      |<-------------------
	     |			      	 |	     |<--------------------------------------------------|	      |			  |
	     |			      	 |___________|					   	         |____________|			  |
	     |																  |
	     |																  |
	 ____V_______														     _____|_______
	|	     |			  4. Authenticated Unblinded Credentials + Contract Request			  	    |		  |
	|	     |------------------------------------------------------------------------------------------------------------->|		  |
	|	     |													  	    |		  |
	|   Client   |														    |   Contract  |
	|	     |			         6. Contract Acceptance OR Contract Reject					    |   Provider  |
	|	     |<-------------------------------------------------------------------------------------------------------------|		  |
	|____________|														    |_____________|

```

This documents describes requirements for both issuance and redemption protocols. It also provides
recommendations on how the architecture should be deployed to ensure the economic effectiveness of
collaterals, the compatibility of incentives, the conservation of the client UX, the privacy and
security and the decentralization of the ecosystem.

## Terminology

The following terms are used throughout this document.

- Client: An entity that pledges a Credential as collateral for a Contract protection.
- Committer: An entity that commit a scarce asset to redeem an authenticated Credential from an Issuer.
- Issuer: An entity that accept a scarce asset in exchange of authenticating a Credential.
- Contract Provider: An entity that accept a set of Credentials as guarantee in case of Contract default from the client.

## Architecture

The Staking Credentials architecture consists of four logical entities -- Client, Issuer, Attester, Contract provider --
that work in concert for credentials issuance and redemption.

## Credentials Issuance

The credentials issuance is an authorization protocol wherein the Committer presents scarce asset and
blinded credentials to the Issuer for authorization. Usually, the rate of scarce assets to credentials
as placed by the Issuer should have been discovered by the Committer in non-defined protocol phase.

There are a number of base collaterals that can serve, including (non-limited):
- off-chain payment
- on-chain payment
- ecash token
- proof-of-utxo-ownership
- contract fee

Issuer should consider which base collaterals to accept in function of the risk-management strategy they adopt. If
they aim for a 0-risk coverage, where all the contract execution risk is transferred on the counterparty, they
sould pick up the default of on-chain/off-chain payment, where each contract cost unit should be covered by
a satoshi unit.

The credential issuance can be deployed as "native" or "reward".

In the "native" contract, a scarce asset for credential authentication should be exchanged a priori of a redemption phase:

```
		 ___________					    ____________
		|	    |	  1. Scarce asset + Credentials    |	        |
		|           |------------------------------------->|	        |
		|           |					   |	        |
		| Committer |					   |   Issuer   |
		|	    |	  2. Authenticated Credentials	   |		|
		|	    |<-------------------------------------|		|
		|___________|					   |____________|

```

In the "reward" context, one type of scarce asset, i.e contract fees are paid by the Client to the Contract
Provider, a posteriori of a successful redemption phase. A quantity of authenticated credentials should be given
from the linked Issuer, back to the Committer:

```

				 ____________
				|	     |
				|	     |
			        |	     |
			        |   Client   |        	            		    	    _____________
				|	     |          1. Contract fees       	           |		 |
				|            |-------------------------------------------->|		 |
				|____________|					   	   |		 |
		 ___________								   |   Contract	 |
		|	    |	                        				   |   Provider  |
		|	    |								   |		 |
		|	    |								   |_____________|
		| Committer |					    ____________		  |
		|	    |     3. Authenticated Credentials	   |		|		  |
		|	    |<-------------------------------------|		|		  |
		|___________|					   |            |		  |
								   |   Issuer   |<-----------------
								   |   		|
								   |            |	2. Unauthenticated Credential Callback
								   |____________|

```

During issuance, the credentials should be blinded to ensure future unlinkability during the redemption phase.

Discovery of assets-to-credentials announced by the Issuer and consumed by the Committer should be
defined in its own document.

A privacy-preserving communication protocol between Committer and Issuer for credentials issuance should
be defined in its own document.

## Redemption

The redemption protocol is an identification protocol wherein the Client presents authenticated credentials
to the Contract Provider to redeem the acceptance of a contract. The credentials should be unblinded before
to be presented to the Contract Provider. The quantity of credentials attached to the contract request should
satisfy the contract liquidity units as enforced by the Contract Provider. Usually, the rate of credentials
to contract unit announced by the Contract Provider should have been discovered by the Committer in a non-defined
protocol phase.

The protocol works as in the figure below:

```
		 ____________										 _____________
		|	     |	      1. Authenticated Unblinded Credentials + Contract Request		|	      |
		|	     |------------------------------------------------------------------------->|	      |
		|	     |										|	      |    3. Contract Execution
		|   Client   |										|   Contract  |----------------------------->
		|	     |		    2. Contract Acceptance OR Contract Reject			|   Provider  |
		|	     |<-------------------------------------------------------------------------|             |
		|____________|										|_____________|

```

Depending on the contract execution outcome (success or failure), a Contract fee can be paid by the Client
to the Contract Provider. This fee should be determined in function of market forces constraining the type
of contract executed.

### Redemption Protocol Extensibility

The Staking Credentials and redemption protocol are both intended to be receptive to extensions that expand
the current set of functionalities through new types or modes of Bitcoin contracting protocols covered. Among them,
long-term held contracts based on a timelock exceeding the usual requirements of Lightning payments.
Another type of flow is the correction of the opening asymmetries in multi-party Lightning channels funding transactions.

## Deployment Considerations

### Lightning HTLC routing

In this model, a HTLC forwarder (Committer) send an off-chain payment and a list of blinded credentials to a Routing hop (Issuer).
The Routing hop counter-sign the blinded credentials and send them back to the HTLC forwarder (Collateral Authentication phase).
The HTLC forwarder (Client) unblinds the credential, attach a HTLC and send the request for acceptance to the Routing hop (Contract
Provider). If the quantity of credentials attached satisfies the Routing hop, the HTLC is accepted and forward to the next hop
in the payment path.

This model is shown below:

```
		 _____________	   1. Off-chain payment + Blinded Credentials	      ____________
		|	      |----------------------------------------------------->|		  |
		|	      |							     |		  |
		|     HTLC    |	      2. Counter-signed Blinded Credentials 	     |  Routing   |  4. HTLC relay
		|  forwarder  |<-----------------------------------------------------|    hop     |--------------->
		|	      |							     |		  |
		|	      |	     3. Unblinded Credentials + HTLC forward 	     |		  |
		|_____________|----------------------------------------------------->|____________|

```


## Security Considerations

The major security risk from an Issuer perspective is the double-spend of the credentials by a Client. In
the context of the Staking Credential architecture, a double-spend is the replay of credential for multiple
Contract requests, therefore provoking a plain timevalue loss if contract fees are not paid by the Client for
each Contract request instance.

The Issuer should keep a private database to log every credential covering a Contract request. This private
database should be accessible by the Contract Provider to validate all the credentials presented for a Contract
request.

A major security risk from a Committer perspective is the tampering of the credentials during transport between
the Committer and Issuers hosts. Credentials could be hijacked based on credentials volume traffic monitoring. As
such credentials transport should be authenticated and the packets obfuscate against network-level inspection.

## References

- [Privacy Pass Architecture](https://www.ietf.org/archive/id/draft-ietf-privacypass-architecture-09.html)
- [Mitigating Channel Jamming with Stakes Certificates](https://lists.linuxfoundation.org/pipermail/lightning-dev/2020-November/002884.html)
- [Solving channel jamming issue of the lightning network](https://jamming-dev.github.io/book/about.html)
- [Discreet Log Contracts specification](https://github.com/discreetlogcontracts/dlcspecs/)
- [Lightning interactive transaction construction protocol](https://github.com/lightning/bolts/pull/851)

## Copyright

This document is placed in the public domain.
