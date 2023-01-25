# Mitigating Channel Jamming with One-Shot HTLC Forward Reputation Credentials

Authors: Antoine Riard <btc@ariard.me>

Created: 2022-11-15

# Problem Statement

The channel jamming issue has been one of the longuest standing and unsolved issue affecting the
Lightning Network. Not only attack has been demonstrated in practice, but also theoritically
[studied](https://jamming-dev.github.io/book/): "A channel jamming is when a malicious entity blocks up liquidity in the LN,
by making a payment to themselves, via third party channels and then never revealing the secret, such
that the payment never completes".

The channel jamming root cause comes from the following situation. A routed HTLC across multiple Lightning
hops is a chain of contracts among trust-minimized counterparties. The settlement of this chain of contracts
is uniform in its outcome (success/failure) across all the intermediary counterparties, however such counterparties
cannot influence the outcome, once the chain of contract is established. As setting up this chain of contracts
consume scarce resources (i.e the channel liquidity timevalue), there is a counterparty risk without guarantee
there is an adequate compensation. Indeed, the routing fees are only paid in case of success.

# Solution introduction

This counterparty risk can be solved straightforwardly by the introduction of a premimum fee carried on by
the HTLC sender. This jamming solution known as ["upfront fees"](https://github.com/t-bast/lightning-docs/blob/master/spam-prevention.md)
in the Lightning community, aims to a fair distribution of the HTLC forward risk among all the chain of
contracts counterparties. While there is a concern this risk distribution doesn't capture well the
shenanigans of a HTLC forward (e.g offline routing hop, spontaneously congestioned channel), there is a
major drawback as it introduces a permanent overhead fee for the network participants.

In contrast, another type of reputation-based solution can be introduced by formalizing a new assumption
"Reputation incentives HTLC senders to behave-well, if there is an adequate proportion between the
acquisition cost and the amount of resources credited in function of said reputation". This assumption is
in fact analoguous to the one underpining routing scoring algorithms incentiving the routing hops reliability.
A reputation system attached to the HTLC forward, not only can protect against malicious jamming entity but
also can offer the traffic shapping tool for node operators to improve the quality of their inbound HTLC
across time.

# Proposed solution

The proposed solution is to introduce a new reputation credentials system, where credentials
should be attached to each HTLC forward request. The credentials are issued locally by each
routing hop, there is no global credential system maintained for the whole Lightning Network.
The credentials represent channel liquidity lockup rights, covering both amount and CLTV duration.
The exact ratio between a quantity of credentials and the channel liquidity lockup rights is
a routing hop policy decision and can be adjusted in real-time in function of channel congestion
rate and other factors. This routing policy can be announced towards the LN network through
the public gossips mechanism.

The credentials are disseminated from the routing hops towards the HTLC senders through onion
communication channels. The credentials acquisition method and cost are defined by the routing
hops. For this version of the protocol, we propose upfront fees as a credential acquisition
method. Payment HTLC are sent to the routing hop and credentials are returned back to the sender
with a onion reply path. The credentials are counter-signed by the issuer to authenticate their
origin. The amount of satoshis and the corresponding quantity of credentials delivered is defined
by each routing hop as a routing policy decision, there is no global pricing of the channel liquidity.
Alternative acquisiton methods (e.g [proof-of-UTXO ownership](https://lists.linuxfoundation.org/pipermail/lightning-dev/2020-November/002884.html))
can be experimented and deployed in a compatible fashion, without network-wide coordination.

Once a HTLC sender has bootstrapped the possession of sufficient credentials to route across
the network to reach its payee destination, payment paths can be drawn. For each hop in the path,
the HTLC onion payload should contain the correct amount of credentials, as requested by the
hop routing policy.

At reception of a HTLC forward, the credentials signatures should be verified and enforced against
the routing hop policy. If the HTLC sender has staked enough credentials to lockup outbound liquidity
for the request msat amount and CTLV duration, the HTLC forward should be committed on the outbound
channel, and the HTLC setup phase pursued until the destination payee is reached.

At HTLC settlement, if the HTLC is successful, the routing fees are paid accordingly to current
`channel_update`, a new set of credentials is issued and counter-signed by the hop and returned back
to the sender through [onion communication channels](https://github.com/lightning/bolts/pull/759).
A supplement of credentials can be joined, as reward of honoring the routing fees, and unlocking more
consequential liquidity lockups for future HTLC forwards.

If the HTLC is a failure, the reputation credentials are slashed. No new credentials are issued back
to the HTLC sender as a punishment. To limit reputation whitewashing, where the jamming damage is superior
to the reputation acquisition cost, a proportion sould be maintained between the credentials acquisition
cost (either from upfront fees or honored routing fees) and the channel liquidity lockup rights.

To preserve the confidentiality of the HTLC senders (or payers), the credentials should be anonymized,
a routing hop should not be able to link between a credential issuance at dissemination and its usage
at the reception of a HTLC forward request. A cryposystem satisfying those requirements could be to
leverage EC [blinded signatures](https://sceweb.sce.uhcl.edu/yang/teaching/csci5234WebSecurityFall2011/Chaum-blind-signatures.PDF).

Additionally, this proposal is extending the `channel_update` message to announce routing fees paid on the
CLTV duration, therefore allowing compensation of the routing hops for the transport of long-term held
class of packets (e.g [hold-invoice](https://github.com/lightningnetwork/lnd/pull/2022), [swaps](https://github.com/ElementsProject/peerswap/blob/master/docs/peer-protocol.md)).

# Protocol extensions

This proposal introduces modifications to the following existent BOLT data structures:
- one new TLV record `credentials_payload` is added to the BOLT4 onion payload
- one new failure message `routing_policy_error` is added in the list of BOLT4 error messages
- two new TLV records `fee_base_block_grace_threshold` and `fee_base_block` are added to `channel_update`

Two new data structures are introduced:
- a BOLT7 gossip message `routing_policy`
- a credential data format: a 32-byte string of random data

# Protocol Phase

This proposal introduces a completely new dissemination phase unknown from the current LN protocol
set of operations.

Additionally, this proposal modifies few other protocol operations:
- the routing & payment path construction
- the HTLC forward phase (i.e ["Accepting and Forwarding a Payment"](https://github.com/lightning/bolts/blob/master/04-onion-routing.md#accepting-and-forwarding-a-payment))
- the HTLC settlement phase (i.e ["Removing an HTLC"](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md#removing-an-htlc-update_fulfill_htlc-update_fail_htlc-and-update_fail_malformed_htlc))

## Credentials dissemination phase

The dissemination phase consists of the satisfaction of an acquisition method announced by the
routing hop by the HTLC sender.

```
			2.
			    BOLT-12 offers
              -------------------------------------------
             /	   3.				         \
	 ___V_____    HTLC     _________    HTLC     _____\____
	|	  |---------->|	        |---------->|	       |
	|	  |           |         |           |	       |
	|  Alice  | 1.        |   Bob   |           |  Caroll  |
	|	  |  gossips  |	        |  gossips  |	       |
	|_________|<----------|_________|<----------|__________|
	    ^					   /
	     \					  /
	      ------------------------------------
		       onions(credentials)
		    4.

```

In this diagram:
1. Alice discovers Caroll's `routing_policy` gossip.
2. Alice fetches an offer from Caroll to pay the `credential_to_liquidity_unit` announced.
3. Alice sends a HTLC to Caroll, the onion payload contains unsigned credentials.
4. Caroll receives the HTLC, counter-signed the credentials and send them back to Alice by onions.

The [reply_path](https://github.com/lightning/bolts/pull/765) between Alice-Caroll to transfer back
the finalized credentials could be communicated during the offer exchage or the HTLC send.

In this topology, Bob is Alice's LSP and credentials to route through him is assumed to be have been
acquired by Alice in a prelimary dissemination phase. Alternatively, Bob could confer a set of free
credentials to Alice due to the LSP-spoke trust-enhanced relationship.

## Building credentials-enhanced payment paths

The introduction of credentials assigned to each routing hops require some modification in the
payment path construction algorithms.

```
						 	 _______
							|	|  channel_update::fee_base_msat: 10
							|  Bob  |
							|_______|  routing_policy::credential_to_liquidity_unit: 2

	 _________  Bob: 100 credentials					 	 				 _________
	|	  | /					 ________							|	  |
	|	  |/					|	 |  channel_update::fee_base_msat: 10			|	  |
	|  Alice  |---- Caroll: 30 credentials  	| Caroll |							|   Eve   |
	|	  |\					|________|  routing_policy::credential_to_liquidity_unit: 3	|	  |
	|_________| \													|_________|
		    Dave: 250 credentials
							 ________
							|	 |  channel_update::fee_base_msat: 10
							|  Dave  |
							|________|  routing_policy::credential_to_liquidity_unit: 1

```

In this diagram, Alice would like to send a 1 BTC HTLC to Eve. Bob, Caroll, Dave are all intermediary valid
routing hops. Each routing hop has both channel with Alice and Eve (non-represented). Alice have been through
3 dissemination phases, one with each of them, to collect credentials. The `fee_base_msat` are equivalent
among the 3 routing hops.

With her stack of credentials, Alice has 3 options:
- She can locks the Bob-Eve link for `100 / 2 = 50` blocks.
- She can locks the Caroll-Eve link for `30 / 3 = 10` blocks.
- She can locks the Dave-Eve link for `250 / 1 = 250` blocks.

Assuming the credentials acquisition cost is uniform across the routing hops, if Alice wishes for the maximum
of `min_final_cltv_expiry_delta`, the Dave option is the optimum. She can build a payment path Alice-Dave-Eve,
wraps Dave credentials into Dave onion, then send him an `update_add_htlc`.

The `credential_to_liquidity_unit` currently represents both the liquidity capacity and the CLTV duration, it's
left as a subject of research if there should be two translation from credentials to channel liquidity lockup units.
(i.e `credentials` -> `liquidity_capacity` and `credentials` -> `CLTV duration`).

## Checking HTLC forward request

Accepting and forwarding a payment as described in BOLT 4 is modified. A routing hop requiring reputation credentials
should enforce additional checks.

```
				     
					  2.	
					      routing_policy(credentials)? 
	 _________   1.	                              _________		                               __________
	|	  |	  	                     |	       | 3a.		                      |	         |
	|	  |    HTLC + onions(credentials)    |	       |    yes           HTLC   	      |	         |
	|  Alice  |--------------------------------->|   Bob   |------------------------------------->|  Caroll  |
	|	  |	                     	     |	       |		   	              |	         |
	|_________|	                     3b.     |_________|		                      |__________|
		^				no    /
		 \	     fail_htlc		     /
		  \_________________________________/
			
```

In this diagram:
1. Alice sends a HTLC+credentials to Bob.
2. Bob extracts the credentials, verifies the signature and validate the credentials against his own `routing_policy`.
3a. The routing checks are successful, Bob forwards the HTLC along the Bob-Caroll link.
4a. Bob stores the backward credentials into the local state until the HTLC settlement.
3b. The routing checks are unsuccessful, Bob rejects the HTLC.

The credentials are wrapped inside the HTLC onion `credentials_payload`. There are two types of credentials: forward/backward.
The forward credentials are covering the ongoing HTLC forward, they should have been counter-signed by the target routing hop
during the dissemination phase or a previous HTLC forward/settlement phase with the same target routing hop. The backward
credentials are also wrapped into the HTLC onion, however they're not signed and should be blinded. If the settlement is successful,
those backward credentials should be the "forward" credentials for Alice's future HTLC sends.

## Signing or slashing credentials during HTLC Settlement

The current HTLC settlement does not encompass any routing checks processing by routing hops, whatever the outcome `update_fulfill_htlc`/
`update_fail_htlc`.

```
						    2. HTLC success ?

							2a. yes, sign backward credentials

							2b. no, slash forward credentials

	 _________   3a. HTLC + onions(signed_credentials)   _________						__________
	|	  |<----------------------------------------|	      |	       1.			       |	  |
	|	  |				            |	      |		  HTLC settlement	       |	  |
	|  Alice  |				            |   Bob   |<---------------------------------------|  Caroll  |
	|	  |         3b. HTLC 		            |	      |				               |	  |
	|_________|<----------------------------------------|_________|					       |__________|

```

In this diagram:
1. Caroll settles the HTLC back to Bob with either a success or a failure.
2a. If it's a success, Bob sign the blinded backward credentials stored during the previous phase.
3a. If it's a failure, Bob slashes the forward credentials. There is no backward credentials return back to Alice.

To prevent replay usage of slashed forward credentials or previously used forward credentials, the signature should be
logged by the routing hop in an [accumulator data structure](https://link.springer.com/content/pdf/10.1007/3-540-48285-7_24.pdf),
allowing efficient test membership. Merkle tree can constitute such accumulator. To limit the growing size of this accumulator,
all credentials issued can be expired according to a `routing_gossip::credential_expiration_height` field.

Once Alice receives the countersigned and still blinded backward credentials, she can unblind them and rely on them
for future payment path construction.

# Security & Privacy considerations

Credentials temporary storage could constitute memory-DoS vectors.

Credentials signing and accumulator test membership could constitute CPU-DoS vectors.

Credentials issuance and usage timing could be leveraged for deanonymization attacks.
