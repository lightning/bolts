# BOLT #3: Bitcoin Transaction and Script Formats

This details the exact format of on-chain transactions, which both sides need to agree on to ensure signatures are valid.  That is, the funding transaction output script, commitment transactions and the HTLC transactions.

# Table of Contents
  * [Transactions](#transactions)
    * [Transaction input and output ordering](#transaction-input-and-output-ordering)
    * [Use of segwit](#use-of-segwit)
    * [Funding Transaction Output](#funding-transaction-output)
    * [Commitment Transaction](#commitment-transaction)
        * [Commitment Transaction Outputs](#commitment-transaction-outputs)
        * [To-Local Output](#to-local-output)
        * [To-Remote Output](#to-remote-output)
        * [Offered HTLC Outputs](#offered-htlc-outputs)
        * [Received HTLC Outputs](#received-htlc-outputs)
        * [Trimmed Outputs](#trimmed-outputs)
    * [HTLC-Timeout and HTLC-Success Transactions](#htlc-timeout-and-htlc-success-transactions)
    * [Fees](#fees)
        * [Fee Calculation](#fee-calculation)   
        * [Fee Payment](#fee-payment)
  * [Keys](#keys)
    * [Key Derivation](#key-derivation)
        * [`localkey`, `remotekey`, `local-delayedkey` and `remote-delayedkey` Derivation](#localkey-remotekey-local-delayedkey-and-remote-delayedkey-derivation)
        * [`revocationkey` Derivation](#revocationkey-derivation) 
        * [Per-commitment Secret Requirements](#per-commitment-secret-requirements) 
    * [Efficient Per-commitment Secret Storage](#efficient-per-commitment-secret-storage)
  * [Appendix A: Expected weights](#appendix-a-expected-weights)    
      * [Expected weight of the commitment transaction](#expected-weight-of-the-commitment-transaction)
      * [Expected weight of HTLC-Timeout and HTLC-Success Transactions](#expected-weight-of-htlc-timeout-and-htlc-success-transactions)
  * [Appendix B: Transactions Test Vectors](#appendix-b-transactions-test-vectors)
  * [Appendix C: Per-commitment Secret Generation Test Vectors](#appendix-c-per-commitment-secret-generation-test-vectors)    
    * [Generation tests](#generation-tests)
    * [Storage tests](#storage-tests)
  * [Appendix D: Key Derivation Test Vectors](#appendix-d-key-derivation-test-vectors)
  * [References](#references)   
  * [Authors](#authors)   
  
# Transactions

## Transaction input and output ordering

Lexicographic ordering as per BIP 69.

## Use of segwit

Most transaction outputs used here are P2WSH outputs, the segwit version of P2SH. To spend such outputs, the last item on the witness stack must be the actual script that was used to generate the P2WSH output that is being spent. This last item has been omitted for brevity in the rest of this document.

## Funding Transaction Output

* The funding output script is a pay-to-witness-script-hash<sup>[BIP141](https://github.com/bitcoin/bips/blob/master/bip-0141.mediawiki#witness-program)</sup> to:
   * `2 <key1> <key2> 2 OP_CHECKMULTISIG`
* Where `key1` is the numerically lesser of the two DER-encoded `funding-pubkey` and `key2` is the greater.

## Commitment Transaction
* version: 2
* locktime: upper 8 bits are 0x20, lower 24 bits are the lower 24 bits of the obscured commitment transaction number.
* txin count: 1
   * `txin[0]` outpoint: `txid` and `output_index` from `funding_created` message
   * `txin[0]` sequence: upper 8 bits are 0x80, lower 24 bits are upper 24 bits of the obscured commitment transaction number.
   * `txin[0]` script bytes: 0
   * `txin[0]` witness: `0 <signature-for-key1> <signature-for-key-2>`

The 48-bit commitment transaction number is obscured by `XOR` with the lower 48 bits of:

    SHA256(payment-basepoint from open_channel || payment-basepoint from accept_channel)

This obscures the number of commitments made on the channel in the
case of unilateral close, yet still provides a useful index for both
nodes (who know the payment-basepoints) to quickly find a revoked
commitment transaction.

### Commitment Transaction Outputs

To allow an opportunity for penalty transactions in case of a revoked commitment transaction, all outputs which return funds to the owner of the commitment transaction (aka "local node") must be delayed for `to-self-delay` blocks.  This delay is done in a second stage HTLC transaction (HTLC-success for HTLCs accepted by the local node, HTLC-timeout for HTLCs offered by the local node).

The reason for the separate transaction stage for HTLC outputs is so that HTLCs can time out or be fulfilled even though they are within the `to-self-delay` delay.
Otherwise the required minimum timeout on HTLCs is lengthened by this delay, causing longer timeouts for HTLCs traversing the network.

The amounts for each output MUST BE rounded down to whole satoshis.  If this amount, minus the fees for the HTLC transaction is less than the `dust-limit-satoshis` set by the owner of the commitment transaction, the output MUST NOT be produced (thus the funds add to fees).

#### To-Local Output

This output sends funds back to the owner of this commitment transaction, thus must be timelocked using `OP_CSV`. It can be claimed, without delay, by the other party if they know the revocation key. The output is a version 0 P2WSH, with a witness script:

    OP_IF
        # Penalty transaction
        <revocation-pubkey>
    OP_ELSE
        `to-self-delay`
        OP_CSV
        OP_DROP
        <local-delayedkey>
    OP_ENDIF
    OP_CHECKSIG

It is spent by a transaction with `nSequence` field set to `to-self-delay` (which can only be valid after that duration has passed), and witness:

	<local-delayedsig> 0

If a revoked commitment transaction is published, the other party can spend this output immediately with the following witness:

    <revocation-sig> 1

#### To-Remote Output

This output sends funds to the other peer, thus is a simple P2WPKH to `remotekey`.

#### Offered HTLC Outputs

This output sends funds to a HTLC-timeout transaction after the HTLC timeout, or to the remote peer on successful payment preimage.  The output is a P2WSH, with a witness script:

    <remotekey> OP_SWAP
        OP_SIZE 32 OP_EQUAL
    OP_NOTIF
        # To me via HTLC-timeout transaction (timelocked).
        OP_DROP 2 OP_SWAP <localkey> 2 OP_CHECKMULTISIG
    OP_ELSE
        # To you with preimage.
        OP_HASH160 <ripemd-of-payment-hash> OP_EQUALVERIFY
        OP_CHECKSIG
    OP_ENDIF

The remote node can redeem the HTLC with the witness:

    <remotesig> <payment-preimage>

Either node can use the HTLC-timeout transaction to time out the HTLC once the HTLC is expired, as shown below.

#### Received HTLC Outputs

This output sends funds to the remote peer after the HTLC timeout, or to an HTLC-success transaction with a successful payment preimage. The output is a P2WSH, with a witness script:

    <remotekey> OP_SWAP
        OP_SIZE 32 OP_EQUAL
    OP_IF
        # To me via HTLC-success transaction.
        OP_HASH160 <ripemd-of-payment-hash> OP_EQUALVERIFY
        2 OP_SWAP <localkey> 2 OP_CHECKMULTISIG
    OP_ELSE
        # To you after timeout.
        OP_DROP <locktime> OP_CHECKLOCKTIMEVERIFY OP_DROP
        OP_CHECKSIG
    OP_ENDIF

To timeout the htlc, the remote node spends it with the witness:

    <remotesig> 0

To redeem the HTLC, the HTLC-success transaction is used as detailed below.

### Trimmed Outputs

Each peer specifies `dust-limit-satoshis` below which outputs should
not be produced; we term these outputs "trimmed".  A trimmed output is
considered too small to be worth creating, and thus that amount adds
to the commitment transaction fee.  For HTLCs, we need to take into
account that the second-stage HTLC transaction may also be below the
limit.

#### Requirements

The base fee must be subtracted from the `to-local` or `to-remote`
outputs as specified in [Fee Calculation](#fee-calculation) before the
commitment transaction outputs are determined.

If the amount of the commitment transaction `to-local` output would be
less than `dust-limit-satoshis` set by the transaction owner, the
commitment transaction MUST NOT contain that output, otherwise it MUST
be generated as specified in [To-Local Output](#to-local-output).

If the amount of the commitment transaction `to-remote` output would be
less than `dust-limit-satoshis` set by the transaction owner, the
commitment transaction MUST NOT contain that output, otherwise it MUST
be generated as specified in [To-Remote Output](#to-remote-output).

For every offered HTLC, if the HTLC amount minus the HTLC-timeout fee
would be less than `dust-limit-satoshis` set by the transaction owner,
the commitment transaction MUST NOT contain that output, otherwise it
MUST be generated as specified in
[Offered HTLC Outputs](#offered-htlc-outputs).

For every received HTLC, if the HTLC amount minus the HTLC-success fee
would be less than `dust-limit-satoshis` set by the transaction owner,
the commitment transaction MUST NOT contain that output, otherwise it
MUST be generated as specified in
[Received HTLC Outputs](#received-htlc-outputs).


## HTLC-Timeout and HTLC-Success Transactions
These HTLC transactions are almost identical, except the HTLC-Timeout transaction is timelocked.  This is also the transaction which can be spent by a valid penalty transaction.

* version: 2
* locktime: `0` for HTLC-Success, `htlc-timeout` for HTLC-Timeout.
* txin count: 1
   * `txin[0]` outpoint: `txid` of the commitment transaction and `output_index` of the matching HTLC output for the HTLC transaction.
   * `txin[0]` sequence: `0`
   * `txin[0]` script bytes: `0`
   * `txin[0]` witness stack: `0 <remotesig> <localsig>  <payment-preimage>` for HTLC-Success, `0 <remotesig> <localsig> 0` for HTLC-Timeout.
* txout count: 1
   * `txout[0]` amount: the HTLC amount minus fees (see [Fee Calculation](#fee-calculation)).
   * `txout[0]` script: version 0 P2WSH with witness script as shown below.

The witness script for the output is:

    OP_IF
        # Penalty transaction
        <revocation-pubkey>
    OP_ELSE
        `to-self-delay`
        OP_CSV
        OP_DROP
        <local-delayedkey>
    OP_ENDIF
    OP_CHECKSIG

To spend this via penalty, the remote node uses a witness stack `<revocationsig> 1` and to collect the output the local node uses an input with nSequence `to-self-delay` and a witness stack `<local-delayedsig> 0`

## Fees

### Fee Calculation

The fee calculation for both commitment transactions and HTLC
transactions is based on the current `feerate-per-kw` and the
*expected weight* of the transaction.

The actual and expected weight vary for several reasons:

* Bitcoin uses DER-encoded signatures which vary in size.
* Bitcoin also uses variable-length integers, so a large number of outputs will take 3 bytes to encode rather than 1.
* The `to-remote` output may be below the dust limit.
* The `to-local` output may be below the dust limit once fees are extracted.

Thus we use a simplified formula for *expected weight*, which assumes:

* Signatures are 73 bytes long (the maximum length)
* There is a small number of outputs (thus 1 byte to count them)
* There is always both a to-local output and a to-remote output.

This gives us the following *expected weights* (details of the computation in [Appendix A](#appendix-a-expected-weights)):

    Commitment weight:   724 + 172 * num-untrimmed-htlc-outputs
    HTLC-timeout weight: 634
    HTLC-success weight: 671

Note that we refer to the "base fee" for a commitment transaction in the requirements below, which is what the funder pays.  The actual fee may be higher than the amount calculated here, due to rounding and trimmed outputs.

#### Requirements

The fee for an HTLC-timeout transaction MUST BE calculated to match:

1. Multiply `feerate-per-kw` by 634 and divide by 1000 (rounding down).

The fee for an HTLC-success transaction MUST BE calculated to match:

1. Multiply `feerate-per-kw` by 671 and divide by 1000 (rounding down).

The base fee for a commitment transaction MUST BE calculated to match:

1. Start with `weight` = 724.

2. For each committed HTLC, if that output is not trimmed as specified in
   [Trimmed Outputs](#trimmed-outputs), add 172 to `weight`.

3. Multiply `feerate-per-kw` by `weight`, divide by 1000 (rounding down).

#### Example

For example, suppose that we have a `feerate-per-kw` of 5000, a `dust-limit-satoshis` of 546 satoshis, and commitment transaction with:
* 2 offered HTLCs of 5000000 and 1000000 millisatoshis (5000 and 1000 satoshis)
* 2 received HTLCs of 7000000 and 800000 millisatoshis (7000 and 800 satoshis)

The HTLC timeout transaction weight is 634, thus fee would be 3170 satoshis.
The HTLC success transaction weight is 671, thus fee would be 3355 satoshis

The commitment transaction weight would be calculated as follows:

* weight starts at 724.

* The offered HTLC of 5000 satoshis is above 546 + 3170 and would result in:
  * an output of 5000 satoshi in the commitment transaction
  * a HTLC timeout transaction of 5000 - 3170 satoshis which spends this output
  * weight increases to 896

* The offered HTLC of 1000 satoshis is below 546 + 3710, so would be trimmed.

* The received HTLC of 7000 satoshis is above 546 + 3355 and would result in:
  * an output of 7000 satoshi in the commitment transaction
  * a HTLC success transaction of 7000 - 3355 satoshis which spends this output
  * weight increases to 1068

* The received HTLC of 800 satoshis is below 546 + 3355 so would be trimmed.

The base commitment transaction fee would be 5340 satoshi; the actual
fee (adding the 1000 and 800 satoshi HTLCs which would have made dust
outputs) is 7140 satoshi.  The final fee may even be more if the
`to-local` or `to-remote` outputs fall below `dust-limit-satoshis`.

### Fee Payment

Base commimtment transaction fees will be extracted from the funder's amount, or if that is insufficient, will use the entire amount of the funder's output.

Note that if once fee amount is subtracted from the to-funder output,
that output may be below `dust-limit-satoshis` and thus also
contributes to fees.

A node MAY fail the channel if the resulting fee rate is too low.

## Commitment Transaction Construction

This section ties the previous sections together to spell out the
algorithm for constructing the commitment transaction for one peer,
given that peer's `dust-limit-satoshis`, the current `feerate-per-kw`,
amounts due to each peer (`to-local` and `to-remote`), and all
committed HTLCs:

1. Initialize the commitment transaction input and locktime as specified
   in [Commitment Transaction](#commitment-transaction).
1. Calculate which committed HTLCs need to be trimmed (see [Trimmed Outputs](#trimmed-outputs)).
2. Calculate the base [commitment transaction fee](#fee-calculation).
3. Subtract this base fee from the funder (either `to-local` or `to-remote`),
   with a floor of zero (see [Fee Payment](#fee-payment)).
3. For every offered HTLC, if it is not trimmed, add an
   [offered HTLC output](#offered-htlc-outputs).
4. For every received HTLC, if it is not trimmed, add an
   [received HTLC output](#received-htlc-outputs).
5. If the `to-local` amount is greater or equal to `dust-limit-satoshis`,
   add a [To-Local Output](#to-local-output).
6. If the `to-remote` amount is greater or equal to `dust-limit-satoshis`,
   add a [To-Remote Output](#to-remote-output).
7. Sort the outputs into [BIP 69 order](#transaction-input-and-output-ordering)

# Keys

## Key Derivation

Each commitment transaction uses a unique set of keys; `localkey` and `remotekey`.  The HTLC-success and HTLC-timeout transactions use `local-delayedkey` and `revocationkey`.  These are changed every time depending on the
`per-commitment-point`.

Keys change because of the desire for trustless outsourcing of
watching for revoked transactions; a _watcher_ should not be able to
determine what the contents of commitment transaction is, even if
given the transaction ID to watch for and can make a resonable guess
as to what HTLCs and balances might be included.  Nonetheless, to
avoid storage for every commitment transaction, it can be given the
`per-commitment-secret` values (which can be stored compactly) and the
`revocation-basepoint` and `delayed-payment-basepoint` to regnerate
the scripts required for the penalty transaction: it need only be
given (and store) the signatures for each penalty input.

Changing the `localkey` and `remotekey` every time ensures that commitment transaction id cannot be guessed: Every commitment transaction uses one of these in its output script.  Splitting the `local-delayedkey` which is required for the penalty transaction allows that to be shared with the watcher without revealing `localkey`; even if both peers use the same watcher, nothing is revealed.

Finally, even in the case of normal unilateral close, the HTLC-success
and/or HTLC-timeout transactions do not reveal anything to the
watcher, as it does not know the corresponding `per-commitment-secret` and
cannot relate the `local-delayedkey` or `revocationkey` with
their bases.

For efficiency, keys are generated from a series of per-commitment secrets which are generated from a single seed, allowing the receiver to compactly store them (see [below](#efficient-per-commitment-secret-storage)).

### `localkey`, `remotekey`, `local-delayedkey` and `remote-delayedkey` Derivation

These keys are simply generated by addition from their base points:

	pubkey = basepoint + SHA256(per-commitment-point || basepoint)*G

The `localkey` uses the local node's `payment-basepoint`, `remotekey`
uses the remote node's `payment-basepoint`, the `local-delayedkey`
uses the local node's `delayed-payment-basepoint`, and the
`remote-delayedkey` uses the remote node's
`delayed-payment-basepoint`.

The corresponding private keys can be derived similarly if the basepoint
secrets are known (i.e., `localkey` and `local-delayedkey` only):

    secretkey = basepoint-secret + SHA256(per-commitment-point || basepoint)

### `revocationkey` Derivation

The revocationkey is a blinded key: the remote node provides the base,
and the local node provides the blinding factor which it later
reveals, so the remote node can use the secret revocationkey for a
penalty transaction.

The `per-commitment-point` is generated using EC multiplication:

	per-commitment-point = per-commitment-secret * G

And this is used to derive the revocation key from the remote node's
`revocation-basepoint`:

	revocationkey = revocation-basepoint * SHA256(revocation-basepoint || per-commitment-point) + per-commitment-point*SHA256(per-commitment-point || revocation-basepoint)

This construction ensures that neither the node providing the
basepoint nor the node providing the `per-commitment-point` can know the
private key without the other node's secret.

The corresponding private key can be derived once the `per-commitment-secret`
is known:

    revocationsecretkey = revocation-basepoint-secret * SHA256(revocation-basepoint || per-commitment-point) + per-commitment-secret*SHA256(per-commitment-point || revocation-basepoint)

### Per-commitment Secret Requirements

A node MUST select an unguessable 256-bit seed for each connection,
and MUST NOT reveal the seed.  Up to 2^48-1 per-commitment secrets can be
generated; the first secret used MUST be index 281474976710655, and
then the index decremented.

The I'th secret P MUST match the output of this algorithm:

    generate_from_seed(seed, I):
        P = seed
        for B in 0 to 47:
            if B set in I:
                flip(B) in P
                P = SHA256(P)
        return P

Where "flip(B)" alternates the B'th least significant bit in the value P.

The receiving node MAY store all previous per-commitment secrets, or
MAY calculate it from a compact representation as described below.

## Efficient Per-commitment Secret Storage

The receiver of a series of secrets can store them compactly in an
array of 49 (value,index) pairs.  This is because given a secret on a
2^X boundary, we can derive all secrets up to the next 2^X boundary,
and we always receive secrets in descending order starting at
`0xFFFFFFFFFFFF`.

In binary, it's helpful to think of any index in terms of a *prefix*,
followed by some trailing zeroes.  You can derive the secret for any
index which matches this *prefix*.

For example, secret `0xFFFFFFFFFFF0` allows us to derive secrets for
`0xFFFFFFFFFFF1` through `0xFFFFFFFFFFFF` inclusive. Secret `0xFFFFFFFFFF08`
allows us to derive secrets `0xFFFFFFFFFF09` through `0xFFFFFFFFFF0F`
inclusive.

We do this using a slight generalization of `generate_from_seed` above:

    # Return I'th secret given base secret whose index has bits..47 the same.
    derive_secret(base, bits, I):
        P = base
        for B in 0 to bits:
            if B set in I:
                flip(B) in P
                P = SHA256(P)
        return P

We need only save one secret for each unique prefix; in effect we can
count the number of trailing zeros, and that determines where in our
storage array we store the secret:

    # aka. count trailing zeroes
    where_to_put_secret(I):
		for B in 0 to 47:
			if testbit(I) in B == 1:
				return B
        # I = 0, this is the seed.
		return 48

We also need to double-check that all previous secrets derive correctly,
otherwise the secrets were not generated from the same seed:

    insert_secret(secret, I):
		B = where_to_put_secret(secret, I)

        # This tracks the index of the secret in each bucket as we traverse.
		for b in 0 to B:
			if derive_secret(secret, B, known[b].index) != known[b].secret:
				error The secret for I is incorrect
				return

        # Assuming this automatically extends known[] as required.
		known[B].index = I
		known[B].secret = secret

Finally, if we are asked to derive secret at index `I`, we need to
figure out which known secret we can derive it from.  The simplest
method is iterating over all the known secrets, and testing if we
can derive from it:

	derive_old_secret(I):
		for b in 0 to len(secrets):
		    # Mask off the non-zero prefix of the index.
		    MASK = ~((1 << b)-1)
			if (I & MASK) == secrets[b].index:
				return derive_secret(known, i, I)
	    error We haven't received index I yet.

This looks complicated, but remember that the index in entry `b` has
`b` trailing zeros; the mask and compare is just seeing if the index
at each bucket is a prefix of the index we want.

# Appendix A: Expected weights

## Expected weight of the commitment transaction

The *expected weight* of a commitment transaction is calculated as follows:

	p2wsh: 34 bytes
		- OP_0: 1 byte
		- OP_DATA: 1 byte (witness_script_SHA256 length)
		- witness_script_SHA256: 32 bytes

	p2wpkh: 22 bytes
		- OP_0: 1 byte
		- OP_DATA: 1 byte (public_key_HASH160 length)
		- public_key_HASH160: 20 bytes

	multi_sig: 71 bytes
		- OP_2: 1 byte
		- OP_DATA: 1 byte (pub_key_alice length)
		- pub_key_alice: 33 bytes
		- OP_DATA: 1 byte (pub_key_bob length)
		- pub_key_bob: 33 bytes
		- OP_2: 1 byte
		- OP_CHECKMULTISIG: 1 byte

	witness: 222 bytes
		- number_of_witness_elements: 1 byte
		- nil_length: 1 byte
		- sig_alice_length: 1 byte
		- sig_alice: 73 bytes
		- sig_bob_length: 1 byte
		- sig_bob: 73 bytes
		- witness_script_length: 1 byte
		- witness_script (multi_sig)
		
	funding_input: 41 bytes
		- previous_out_point: 36 bytes
			- hash: 32 bytes
			- index: 4 bytes
		- var_int: 1 byte (script_sig length)
		- script_sig: 0 bytes
		- witness <----	we use "witness" instead of "script_sig" for
	 			transaction validation, but "witness" is stored
	 			separately and cost for it size is smaller. So
	 			we separate the calculation of ordinary data
	 			from witness data.
		- sequence: 4 bytes

	output_paying_to_us: 43 bytes
		- value: 8 bytes
		- var_int: 1 byte (pk_script length)
		- pk_script (p2wsh): 34 bytes

	output_paying_to_them: 31 bytes
		- value: 8 bytes
		- var_int: 1 byte (pk_script length)
		- pk_script (p2wpkh): 22 bytes

	 htlc_output: 43 bytes
		- value: 8 bytes
		- var_int: 1 byte (pk_script length)
		- pk_script (p2wsh): 34 bytes

	 witness_header: 2 bytes
		- flag: 1 byte
		- marker: 1 byte

	 commitment_transaction: 125 + 43 * num-htlc-outputs bytes
		- version: 4 bytes
		- witness_header <---- part of the witness data
		- count_tx_in: 1 byte
		- tx_in: 41 bytes
			funding_input
		- count_tx_out: 1 byte
		- tx_out: 74 + 43 * num-htlc-outputs bytes
			output_paying_to_them,
			output_paying_to_us,
			....htlc_output's...
		- lock_time: 4 bytes
	
Multiplying non-witness data by 4, this gives a weight of:
	
	// 500 + 172 * num-htlc-outputs weight
	commitment_transaction_weight = 4 * commitment_transaction

	// 224 weight
	witness_weight = witness_header + witness

	overall_weight = 500 + 172 * num-htlc-outputs + 224 weight 

## Expected weight of HTLC-Timeout and HTLC-Success Transactions

The *expected weight* of an HTLC transaction is calculated as follows:

    accepted_htlc_script: 109 bytes
	    - OP_DATA: 1 byte (remotekey length)
		- remotekey: 33 bytes
		- OP_SWAP: 1 byte
		- OP_SIZE: 1 byte
		- 32: 1 byte
		- OP_EQUAL: 1 byte
		- OP_IF: 1 byte
		- OP_HASH160: 1 byte
		- OP_DATA: 1 byte (ripemd-of-payment-hash length)
		- ripemd-of-payment-hash: 20 bytes
		- OP_EQUALVERIFY: 1 byte
		- 2: 1 byte
		- OP_SWAP: 1 byte
		- OP_DATA: 1 byte (localkey length)
		- localkey: 33 bytes
		- 2: 1 byte
		- OP_CHECKMULTISIG: 1 byte
		- OP_ELSE: 1 byte
		- OP_DROP: 1 byte
		- OP_PUSHDATA2: 1 byte (locktime length)
		- locktime: 2 bytes
		- OP_CHECKLOCKTIMEVERIFY: 1 byte
		- OP_DROP: 1 byte
        - OP_CHECKSIG: 1 byte
		- OP_ENDIF: 1 byte

    offered_htlc_script: 104 bytes
		- OP_DATA: 1 byte (remotekey length)
		- remotekey: 33 bytes
		- OP_SWAP: 1 byte
		- OP_SIZE: 1 byte
		- 32: 1 byte
		- OP_EQUAL: 1 byte
		- OP_NOTIF: 1 byte
		- OP_DROP: 1 byte
		- 2: 1 byte
		- OP_SWAP: 1 byte
		- OP_DATA: 1 byte (localkey length)
		- localkey: 33 bytes
		- 2: 1 byte
		- OP_CHECKMULTISIG: 1 byte
		- OP_ELSE: 1 byte
		- OP_HASH160: 1 byte
		- OP_DATA: 1 byte (ripemd-of-payment-hash length)
		- ripemd-of-payment-hash: 20 bytes
		- OP_EQUALVERIFY: 1 byte
		- OP_CHECKSIG: 1 byte
		- OP_ENDIF: 1 byte

    timeout_witness: 256 bytes
		- number_of_witness_elements: 1 byte
		- nil_length: 1 byte
		- sig_alice_length: 1 byte
		- sig_alice: 73 bytes
		- sig_bob_length: 1 byte
		- sig_bob: 73 bytes
		- nil_length: 1 byte
		- witness_script_length: 1 byte
		- witness_script (offered_htlc_script)

    success_witness: 293 bytes
		- number_of_witness_elements: 1 byte
		- nil_length: 1 byte
		- sig_alice_length: 1 byte
		- sig_alice: 73 bytes
		- sig_bob_length: 1 byte
		- sig_bob: 73 bytes
		- preimage_length: 1 byte
		- preimage: 32 bytes
		- witness_script_length: 1 byte
		- witness_script (accepted_htlc_script)

    commitment_input: 41 bytes
		- previous_out_point: 36 bytes
			- hash: 32 bytes
			- index: 4 bytes
		- var_int: 1 byte (script_sig length)
		- script_sig: 0 bytes
		- witness (success_witness or timeout_witness)
		- sequence: 4 bytes

    htlc_tx_output: 43 bytes
		- value: 8 bytes
		- var_int: 1 byte (pk_script length)
		- pk_script (p2wsh): 34 bytes

	htlc_transaction: 
		- version: 4 bytes
		- witness_header <---- part of the witness data
		- count_tx_in: 1 byte
		- tx_in: 41 bytes
			commitment_input
		- count_tx_out: 1 byte
		- tx_out: 43
			htlc_tx_output
		- lock_time: 4 bytes

Multiplying non-witness data by 4, this gives a weight of 376.  Adding
the witness data for each case (256 + 2 for HTLC-timeout, 293 + 2 for
HTLC-success) gives a weight of:

	634 (HTLC-timeout)
	671 (HTLC-success)

# Appendix C: Funding Transaction Test Vectors

In the following:
 - we assume that *local* is the funder
 - private keys are displayed as 32 bytes plus a trailing 1 (bitcoin's convention for "compressed" private keys, i.e. keys for which the public key is compressed)
 - transaction signatures are all deterministic, using RFC6979 (using HMAC-SHA256)

The input for the funding transaction was created using a test chain
with the following first two blocks, the second one with a spendable
coinbase:

    Block 0 (genesis): 0100000000000000000000000000000000000000000000000000000000000000000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4adae5494dffff7f20020000000101000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4d04ffff001d0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e206272696e6b206f66207365636f6e64206261696c6f757420666f722062616e6b73ffffffff0100f2052a01000000434104678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5fac00000000
    Block 1: 0000002006226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910fadbb20ea41a8423ea937e76e8151636bf6093b70eaff942930d20576600521fdc30f9858ffff7f20000000000101000000010000000000000000000000000000000000000000000000000000000000000000ffffffff03510101ffffffff0100f2052a010000001976a9143ca33c2e4446f4a305f23c80df8ad1afdcf652f988ac00000000
    Block 1 coinbase transaction: 01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff03510101ffffffff0100f2052a010000001976a9143ca33c2e4446f4a305f23c80df8ad1afdcf652f988ac00000000
    Block 1 coinbase privkey: 6bd078650fcee8444e4e09825227b801a1ca928debb750eb36e6d56124bb20e80101
    # privkey in base58: cRCH7YNcarfvaiY1GWUKQrRGmoezvfAiqHtdRvxe16shzbd7LDMz
    # pubkey in base68: mm3aPLSv9fBrbS68JzurAMp4xGoddJ6pSf

The funding transaction is paid to the following keys:

    local_funding_pubkey: 023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb
    remote_funding_pubkey: 030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c1
    # funding witness script = 5221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae

The funding transaction has a single input, and a change output (order
determined by BIP69 in this case):

    input txid: adbb20ea41a8423ea937e76e8151636bf6093b70eaff942930d20576600521fd
    input index: 0
    input satoshis: 5000000000
    funding satoshis: 10000000
    # funding witness script = 5221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae
    # feerate_per_kw: 15000
    change satoshis: 4989986080
    funding output: 0

The resulting funding transaction is:

    funding tx: 0200000001adbb20ea41a8423ea937e76e8151636bf6093b70eaff942930d20576600521fd000000006b48304502210090587b6201e166ad6af0227d3036a9454223d49a1f11839c1a362184340ef0240220577f7cd5cca78719405cbf1de7414ac027f0239ef6e214c90fcaab0454d84b3b012103535b32d5eb0a6ed0982a0479bbadc9868d9836f6ba94dd5a63be16d875069184ffffffff028096980000000000220020c015c4a6be010e21657068fc2e6a9d02b27ebe4d490a25846f7237f104d1a3cd20256d29010000001600143ca33c2e4446f4a305f23c80df8ad1afdcf652f900000000
    # txid: 8984484a580b825b9972d7adb15050b3ab624ccd731946b3eeddb92f4e7ef6be

# Appendix C: Commitment and HTLC Transaction Test Vectors

In the following:
 - we consider *local* transactions, which implies that all payments to *local* are delayed
 - we assume that *local* is the funder
 - private keys are displayed as 32 bytes plus a trailing 1 (bitcoin's convention for "compressed" private keys, i.e. keys for which the public key is compressed)
 - transaction signatures are all deterministic, using RFC6979 (using HMAC-SHA256)

We start by defining common basic parameters for each test vector: the
HTLCs are not used for the first "simple commitment tx with no HTLCs" test.

    funding_tx_id: 8984484a580b825b9972d7adb15050b3ab624ccd731946b3eeddb92f4e7ef6be
    funding_output_index: 0
    funding_amount_satoshi: 10000000
    commitment_number: 42
    local_delay: 144
    local_dust_limit_satoshi: 546
    htlc 0 direction: remote->local
    htlc 0 amount_msat: 1000000
    htlc 0 expiry: 500
    htlc 0 payment_preimage: 0000000000000000000000000000000000000000000000000000000000000000
    htlc 1 direction: remote->local
    htlc 1 amount_msat: 2000000
    htlc 1 expiry: 501
    htlc 1 payment_preimage: 0101010101010101010101010101010101010101010101010101010101010101
    htlc 2 direction: local->remote
    htlc 2 amount_msat: 2000000
    htlc 2 expiry: 502
    htlc 2 payment_preimage: 0202020202020202020202020202020202020202020202020202020202020202
    htlc 3 direction: local->remote
    htlc 3 amount_msat: 3000000
    htlc 3 expiry: 503
    htlc 3 payment_preimage: 0303030303030303030303030303030303030303030303030303030303030303
    htlc 4 direction: remote->local
    htlc 4 amount_msat: 4000000
    htlc 4 expiry: 504
    htlc 4 payment_preimage: 0404040404040404040404040404040404040404040404040404040404040404

<!-- We derive the test vector values as per Key Derivation, though it's not
     required for this test.  They're included here for completeness and
	 in case someone wants to reproduce the test vectors themselves:

INTERNAL: remote_funding_privkey: 1552dfba4f6cf29a62a0af13c8d6981d36d0ef8d61ba10fb0fe90da7634d7e130101
INTERNAL: local_payment_basepoint_secret: 111111111111111111111111111111111111111111111111111111111111111101
INTERNAL: local_revocation_basepoint_secret: 222222222222222222222222222222222222222222222222222222222222222201
INTERNAL: local_delayed_payment_basepoint_secret: 333333333333333333333333333333333333333333333333333333333333333301
INTERNAL: remote_payment_basepoint_secret: 444444444444444444444444444444444444444444444444444444444444444401
x_local_per_commitment_secret: 1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a0908070605040302010001
INTERNAL: remote_per_commit_secret: 444444444444444444444444444444444444444444444444444444444444444401
# From local_revocation_basepoint_secret
INTERNAL: local_revocation_basepoint: 02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
# From local_delayed_payment_basepoint_secret
INTERNAL: local_delayed_payment_basepoint: 023c72addb4fdf09af94f0c94d7fe92a386a7e70cf8a1d85916386bb2535c7b1b1
INTERNAL: local_per_commitment_point: 025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486
INTERNAL: remote_per_commitment_point: 022c76692fd70814a8d1ed9dedc833318afaaed8188db4d14727e2e99bc619d325
INTERNAL: remote_secretkey: 839ad0480cde69fc721fb8e919dcf20bc4f2b3374c7b27ff37f200ddfa7b0edb01
# From local_delayed_payment_basepoint_secret, local_per_commitment_point and local_delayed_payment_basepoint
INTERNAL: local_delayed_secretkey: adf3464ce9c2f230fd2582fda4c6965e4993ca5524e8c9580e3df0cf226981ad01
-->

Here are the points used to derive the obscuring factor for the commitment number:

    local_payment_basepoint: 034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
    remote_payment_basepoint: 032c0b7cf95324a07d05398b240174dc0c2be444d96b159aa6c7f7b1e668680991
    # obscured commitment transaction number = 0x2bb038521914 ^ 42

And here are the keys needed to create the transactions:

    local_funding_privkey: 30ff4956bbdd3222d44cc5e8a1261dab1e07957bdac5ae88fe3261ef321f37490101
    local_funding_pubkey: 023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb
    remote_funding_pubkey: 030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c1
    local_secretkey: bb13b121cdc357cd2e608b0aea294afca36e2b34cf958e2e6451a2f27469449101
    localkey: 030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7
    remotekey: 039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878
    local_delayedkey: 03fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c
    local_revocation_key: 0212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19
    # funding wscript = 5221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae

And here are the test vectors themselves:

    name: simple commitment tx with no HTLCs
    to_local_msat: 7000000000
    to_remote_msat: 3000000000
    feerate_per_kw: 15000
    # base commitment transaction fee = 10860
    # to-local amount 6989140 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100f732ff890ea9af685f9577bd38f11ceb77f5ead254af663638bbf80bbfa180da022005bb3493d2ba28e6ea43db36d156f5c2befa5de469d118a321a3fd3f3f356dcd
    # local_signature = 304402205fdea103b8eb092e46362bbc8d80c790dd3756db2474baaf538bf96039a2670c02206dc19fb7e152382887018f5f76047d0b0d75e0876f06663a49c59d8f6d408954
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03654a56a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402205fdea103b8eb092e46362bbc8d80c790dd3756db2474baaf538bf96039a2670c02206dc19fb7e152382887018f5f76047d0b0d75e0876f06663a49c59d8f6d40895401483045022100f732ff890ea9af685f9577bd38f11ceb77f5ead254af663638bbf80bbfa180da022005bb3493d2ba28e6ea43db36d156f5c2befa5de469d118a321a3fd3f3f356dcd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with all 5 htlcs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 0
    # base commitment transaction fee = 0
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 1000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac68
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6988000 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100b8aa92242b6f9f414b3d9c06d2bb03ae2d8b458232dae446ece5c250823e8619022078f1bf9d0fe59434517df3adf46acce524e79db6759e70ecce8cc26612bf5bbd
    # local_signature = 3044022002ae4ffeca449455d06bd20192d70a107b68faed1a57ba0702ca77755f9da32102202e667e6b079d7d529a3b33af89428e4469d7d58db609f8d678113b1be1f51534
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8007e80300000000000022002070b024855cc882f19cadb563400cb24cc07987c917daf702bb5b2e6f52e04318d0070000000000002200204117dad487a3c3bc07e34db505d567fcc263b30075f0b4679a1b27c297b4b147d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036e0a06a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022002ae4ffeca449455d06bd20192d70a107b68faed1a57ba0702ca77755f9da32102202e667e6b079d7d529a3b33af89428e4469d7d58db609f8d678113b1be1f5153401483045022100b8aa92242b6f9f414b3d9c06d2bb03ae2d8b458232dae446ece5c250823e8619022078f1bf9d0fe59434517df3adf46acce524e79db6759e70ecce8cc26612bf5bbd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 304402204e50ed69b56f58e708375afa013668021e6566453391628651d1a20fdddb84950220560f0e2d69318d56f8b1eac6c37a4ca528e2fb637fe0e903888084dbad015ca3
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 3045022100fb753e8d55c79df0d2fbbde4e3490ce94dbaae4b5c5746d51baf0e5cb9f7b31502206f2177f6eb87751f8156974e004138ea1c01456cc857dffd1227a75dc5729fbe
    # signature for output 2 (htlc 2)
    remote_htlc_signature = 304402205d2b97b6a91bd22f7fdfde9ff5cc19f0f6146078939f1e6c49d83b0727f66fb8022060c7959b4fe63f56fb02e0c9d53191d340925ab93b1742f59aa2e716b7e50bea
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 30440220552fd8a6f1234e34b55b90567114136cf71db75a937abe41a3a77e9c2cf9bf7502207257bff5d2d4f44b149fef0e491a13563e055d26a7d93accef11ffc91211f3fd
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 3045022100f3ea490be7b41fd7cfe10c9d3c30e01db2615ab74e30638be4b87af3eb205715022077d4d87cce155999b5e7baf1c367abc5bede0b5f49a37207416f2a777d9a644e
    # local_signature = 3045022100ea869343de2b16e82a4d9fc4a9d0e45853d769e43fb1ddc3c1511897d19d1a4802202a8a6ba64ab5425d31a126b64404a5facd5ebbf2e8e137ff64176108a6ea1325
    output htlc_success_tx 0: 02000000000101ec9b088c36a14702c0ee66223b51bfc0826102497824b91fb09e6516ed09473f00000000000000000001e8030000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402204e50ed69b56f58e708375afa013668021e6566453391628651d1a20fdddb84950220560f0e2d69318d56f8b1eac6c37a4ca528e2fb637fe0e903888084dbad015ca301483045022100ea869343de2b16e82a4d9fc4a9d0e45853d769e43fb1ddc3c1511897d19d1a4802202a8a6ba64ab5425d31a126b64404a5facd5ebbf2e8e137ff64176108a6ea1325012000000000000000000000000000000000000000000000000000000000000000006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac6800000000
    # local_signature = 304402200ce66e1786e4cfb568e1c8d2de0164d0fec52c2cff3c225075f6f18ebe87be5502202b771e8e0d519c5ce23cc26260ffe80fe567c1916112b5a5f275f2b61d7cdd7e
    output htlc_success_tx 1: 02000000000101ec9b088c36a14702c0ee66223b51bfc0826102497824b91fb09e6516ed09473f01000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100fb753e8d55c79df0d2fbbde4e3490ce94dbaae4b5c5746d51baf0e5cb9f7b31502206f2177f6eb87751f8156974e004138ea1c01456cc857dffd1227a75dc5729fbe0147304402200ce66e1786e4cfb568e1c8d2de0164d0fec52c2cff3c225075f6f18ebe87be5502202b771e8e0d519c5ce23cc26260ffe80fe567c1916112b5a5f275f2b61d7cdd7e012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3045022100bb339c56a4edf19203a8e4101cda3e8a9b96cc9ecd14beaefca3ce36b24232740220316ab679e7b547e0d1a1e3bb341ce9e7ebb85045e4a61e8286a822bf3973f417
    output htlc_timeout_tx 2: 02000000000101ec9b088c36a14702c0ee66223b51bfc0826102497824b91fb09e6516ed09473f02000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402205d2b97b6a91bd22f7fdfde9ff5cc19f0f6146078939f1e6c49d83b0727f66fb8022060c7959b4fe63f56fb02e0c9d53191d340925ab93b1742f59aa2e716b7e50bea01483045022100bb339c56a4edf19203a8e4101cda3e8a9b96cc9ecd14beaefca3ce36b24232740220316ab679e7b547e0d1a1e3bb341ce9e7ebb85045e4a61e8286a822bf3973f41701006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 30450221009f2da369c170ff31c6a09df269880e6dad8fce73f1b9a7e2e2c51f7067623f0702201d47b596e06b2f71a14f0118094791d94e9203133792a9b4c8a4ee33f6be69ee
    output htlc_timeout_tx 3: 02000000000101ec9b088c36a14702c0ee66223b51bfc0826102497824b91fb09e6516ed09473f03000000000000000001b80b0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220552fd8a6f1234e34b55b90567114136cf71db75a937abe41a3a77e9c2cf9bf7502207257bff5d2d4f44b149fef0e491a13563e055d26a7d93accef11ffc91211f3fd014830450221009f2da369c170ff31c6a09df269880e6dad8fce73f1b9a7e2e2c51f7067623f0702201d47b596e06b2f71a14f0118094791d94e9203133792a9b4c8a4ee33f6be69ee01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 30440220507a7b30296747a04d6cf89c1b95aa49571b5b520b04b4f6dd6ac1f3bad505ef022068cc3787015a2216ca0f6d04fb2fdd1631c77e32940613af82c990d0e5779117
    output htlc_success_tx 4: 02000000000101ec9b088c36a14702c0ee66223b51bfc0826102497824b91fb09e6516ed09473f04000000000000000001a00f0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f3ea490be7b41fd7cfe10c9d3c30e01db2615ab74e30638be4b87af3eb205715022077d4d87cce155999b5e7baf1c367abc5bede0b5f49a37207416f2a777d9a644e014730440220507a7b30296747a04d6cf89c1b95aa49571b5b520b04b4f6dd6ac1f3bad505ef022068cc3787015a2216ca0f6d04fb2fdd1631c77e32940613af82c990d0e5779117012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 7 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 678
    # base commitment transaction fee = 1073
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 1000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac68
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6986927 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402202e737723eaa3b291bbdf9e66623b2ca9a571034d92a0403c3140ada9d536c25f022012a21463bd9767f3645145fbd2507231908d4a76a5beb00d944da7b954e0ad77
    # local_signature = 3045022100ce89d603b86ab055ad0546fe3e3407566598f6a671368223a0aaa449eb36a4b902204cc65a61c8f799b8e541d3190f3951bd2dbd5a4af36698ff469cc68dd2b69675
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8007e80300000000000022002070b024855cc882f19cadb563400cb24cc07987c917daf702bb5b2e6f52e04318d0070000000000002200204117dad487a3c3bc07e34db505d567fcc263b30075f0b4679a1b27c297b4b147d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036af9c6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100ce89d603b86ab055ad0546fe3e3407566598f6a671368223a0aaa449eb36a4b902204cc65a61c8f799b8e541d3190f3951bd2dbd5a4af36698ff469cc68dd2b696750147304402202e737723eaa3b291bbdf9e66623b2ca9a571034d92a0403c3140ada9d536c25f022012a21463bd9767f3645145fbd2507231908d4a76a5beb00d944da7b954e0ad7701475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 3043021f596df33b36db84076c6e4a8812da556872fc3303439ebc91778154c92b09f10220581a5f30cf0caa4e12771f3abd0168fc2f76f974b201963c7cd2ce8515fa2ce1
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 304402200129c0fb24a57c0fdd18b3e7e4c35c9a224b389757dd1cb1380de9880897713602206e4ac8eb6f641815257b2822784aa16d25e53e2bfafd4facdd28468593afebfa
    # signature for output 2 (htlc 2)
    remote_htlc_signature = 3045022100f42d53186c3debf3dbed4fff092372ea9b9390f730cc1c1822f3c7399a8781e0022044b0b3680e3ee20a636cdee9c4754bcab7167c4b21177df55f23ed100f5d2828
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 3045022100815d4ea550897aac19da74f77e057ef0ff5640714a5a138943533111326b71650220136189c225d4981f68f53aa2815beb788ee4d072e8290cb99afa301a57f5f5d3
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 3045022100d388ded6a2cb9ebd6480342bd48ba28543b77bea5ea08c4b4b4a11751a13ced7022060aea2991e0f8c45a588ec0bf1bfc8ea939ee45e12edadba103d6fb49e2f76be
    # local_signature = 304402203bac3c0a776bf03e3f404239b8907b62db4c7db02b6dafdee8c62ff875bca42302206f4b1f68ab018ce788ffe16db38d9a36ae6738aa4a11fcdabe721dfa79d75909
    output htlc_success_tx 0: 0200000000010182fafbf148ac73a8a8cbbdf459408e1d368b4a2498bb0305a703cb800ae03b0e0000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500463043021f596df33b36db84076c6e4a8812da556872fc3303439ebc91778154c92b09f10220581a5f30cf0caa4e12771f3abd0168fc2f76f974b201963c7cd2ce8515fa2ce10147304402203bac3c0a776bf03e3f404239b8907b62db4c7db02b6dafdee8c62ff875bca42302206f4b1f68ab018ce788ffe16db38d9a36ae6738aa4a11fcdabe721dfa79d75909012000000000000000000000000000000000000000000000000000000000000000006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac6800000000
    # local_signature = 3045022100879a2b8250211e9d450855f5303b83d4942adce55ac120be2b9e9dcd3283698d0220223ea486e041e94f5da1dafef7e15c98af0a6e2751c4dd3f24e9c0731c75e775
    output htlc_success_tx 1: 0200000000010182fafbf148ac73a8a8cbbdf459408e1d368b4a2498bb0305a703cb800ae03b0e0100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402200129c0fb24a57c0fdd18b3e7e4c35c9a224b389757dd1cb1380de9880897713602206e4ac8eb6f641815257b2822784aa16d25e53e2bfafd4facdd28468593afebfa01483045022100879a2b8250211e9d450855f5303b83d4942adce55ac120be2b9e9dcd3283698d0220223ea486e041e94f5da1dafef7e15c98af0a6e2751c4dd3f24e9c0731c75e775012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3045022100ffd8a793a88de836ee065126d0302455d3d03ba50ba086004d36cc8d40d772a202203750a10f668612cb469c315e9c9f4105dddc597749e34acbc23c75028729c110
    output htlc_timeout_tx 2: 0200000000010182fafbf148ac73a8a8cbbdf459408e1d368b4a2498bb0305a703cb800ae03b0e0200000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f42d53186c3debf3dbed4fff092372ea9b9390f730cc1c1822f3c7399a8781e0022044b0b3680e3ee20a636cdee9c4754bcab7167c4b21177df55f23ed100f5d282801483045022100ffd8a793a88de836ee065126d0302455d3d03ba50ba086004d36cc8d40d772a202203750a10f668612cb469c315e9c9f4105dddc597749e34acbc23c75028729c11001006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3045022100a074832b8f1ab20a623fb4aa5e1173001f04c7b2cbcc9b87572c1c12a1bf3b1f02200a47b31262dbea329ae0f70b278c34b55176993d038f57a264e10b62b9d017aa
    output htlc_timeout_tx 3: 0200000000010182fafbf148ac73a8a8cbbdf459408e1d368b4a2498bb0305a703cb800ae03b0e03000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100815d4ea550897aac19da74f77e057ef0ff5640714a5a138943533111326b71650220136189c225d4981f68f53aa2815beb788ee4d072e8290cb99afa301a57f5f5d301483045022100a074832b8f1ab20a623fb4aa5e1173001f04c7b2cbcc9b87572c1c12a1bf3b1f02200a47b31262dbea329ae0f70b278c34b55176993d038f57a264e10b62b9d017aa01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 304502210082bb528c57eb739edd87307fdc55f6f22dc33ef16aecdf3b42d8ad5c6b6ee7f202207cd93b27fb31301abfb1ef2f6dc3b96c0e059ecd4433933129e849126ac216d5
    output htlc_success_tx 4: 0200000000010182fafbf148ac73a8a8cbbdf459408e1d368b4a2498bb0305a703cb800ae03b0e04000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d388ded6a2cb9ebd6480342bd48ba28543b77bea5ea08c4b4b4a11751a13ced7022060aea2991e0f8c45a588ec0bf1bfc8ea939ee45e12edadba103d6fb49e2f76be0148304502210082bb528c57eb739edd87307fdc55f6f22dc33ef16aecdf3b42d8ad5c6b6ee7f202207cd93b27fb31301abfb1ef2f6dc3b96c0e059ecd4433933129e849126ac216d5012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 679
    # base commitment transaction fee = 958
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6987042 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100baadda7b5f7dfd01f26546d2cbdd570fc4325026ff4f981150ad7ca94ae3614e02206a0a999ae63d06550894ba4b2347e1b3ee52e8837496c7c92cb51a54950385d8
    # local_signature = 30440220241985f3095d908e8d92d935bc2fdfa2c06983c889c31c09dcedbc4336cc5086022056d0325ab2898ca9cd460c0f730ba027867d7ae58a10ab9bffc500652add187b
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d0070000000000002200204117dad487a3c3bc07e34db505d567fcc263b30075f0b4679a1b27c297b4b147d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036229d6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004730440220241985f3095d908e8d92d935bc2fdfa2c06983c889c31c09dcedbc4336cc5086022056d0325ab2898ca9cd460c0f730ba027867d7ae58a10ab9bffc500652add187b01483045022100baadda7b5f7dfd01f26546d2cbdd570fc4325026ff4f981150ad7ca94ae3614e02206a0a999ae63d06550894ba4b2347e1b3ee52e8837496c7c92cb51a54950385d801475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 1)
    remote_htlc_signature = 304402207ca6575ff42811dd8328caf8a01190b66f8100d89eb9a0739563796798f37b0602202d558b093b5ef5a54531b02d93bdbb0c56cec9ea349349e086e472ac3add2ac0
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 3045022100848bffb02cf62be98f08f6babafd5d1498ba8d8b0bc7e3ab5bfcf1c597891fd30220129d8ec85355b0afe6894b301fd03fc81b71ce135e41e1dfde5ff020cb85d28b
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 3045022100b3f859ab27066fe6753be1868f05c88ddfc332dedd679f1fcbca73e8dff192a702206bbda2cf9d64c32f0e4060456c9dcd5c10088b38119eae7074d16612230523aa
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 304402204122962712067f011032b826fc63391c6cefdb11947363b64a422363f8c66b0f0220655d854da73ecd2df38653607c62caddb6df186c806219ba7b882a3ab0cf7418
    # local_signature = 3045022100b603c6616294f65e9d5094eec2cbeb7e5d70774cb32f6ce438eba0386508bc5a0220008c2f2d784eb8e3eff4cc3c4e9a65943bfe60df4100cff0ee3626d16662d618
    output htlc_success_tx 1: 020000000001015dd0d7d8d9f5630cdb43d104c9e3217e23974ae83478e76286b78669e6ad529a0000000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402207ca6575ff42811dd8328caf8a01190b66f8100d89eb9a0739563796798f37b0602202d558b093b5ef5a54531b02d93bdbb0c56cec9ea349349e086e472ac3add2ac001483045022100b603c6616294f65e9d5094eec2cbeb7e5d70774cb32f6ce438eba0386508bc5a0220008c2f2d784eb8e3eff4cc3c4e9a65943bfe60df4100cff0ee3626d16662d618012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3044022017c37834380e608e4c4db3f3f00efec6d5cc54991c39d030dbc3933c84f35ead0220656b9ab4ebaf202a44d68b8ea5458f89b53bfed6d4b976f97488913596cc8c7d
    output htlc_timeout_tx 2: 020000000001015dd0d7d8d9f5630cdb43d104c9e3217e23974ae83478e76286b78669e6ad529a0100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100848bffb02cf62be98f08f6babafd5d1498ba8d8b0bc7e3ab5bfcf1c597891fd30220129d8ec85355b0afe6894b301fd03fc81b71ce135e41e1dfde5ff020cb85d28b01473044022017c37834380e608e4c4db3f3f00efec6d5cc54991c39d030dbc3933c84f35ead0220656b9ab4ebaf202a44d68b8ea5458f89b53bfed6d4b976f97488913596cc8c7d01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 304402201017649385496e50c465d5229bf8493a9ed98b3366dfe7e80d993a6cf98ebf4e022076ffe499b0962737f3f751119f9bf1b71c1077bbdc0ab91a1974fea2657960c1
    output htlc_timeout_tx 3: 020000000001015dd0d7d8d9f5630cdb43d104c9e3217e23974ae83478e76286b78669e6ad529a02000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100b3f859ab27066fe6753be1868f05c88ddfc332dedd679f1fcbca73e8dff192a702206bbda2cf9d64c32f0e4060456c9dcd5c10088b38119eae7074d16612230523aa0147304402201017649385496e50c465d5229bf8493a9ed98b3366dfe7e80d993a6cf98ebf4e022076ffe499b0962737f3f751119f9bf1b71c1077bbdc0ab91a1974fea2657960c101006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100ee7d0ca14125a031543ab0784770ab56596c7a521e71cd846ec6e45deb2e91d30220432cb31afff3554198e0ad478a440763fb2e85bfb8b777ad8ec4749c321fd0dd
    output htlc_success_tx 4: 020000000001015dd0d7d8d9f5630cdb43d104c9e3217e23974ae83478e76286b78669e6ad529a03000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402204122962712067f011032b826fc63391c6cefdb11947363b64a422363f8c66b0f0220655d854da73ecd2df38653607c62caddb6df186c806219ba7b882a3ab0cf741801483045022100ee7d0ca14125a031543ab0784770ab56596c7a521e71cd846ec6e45deb2e91d30220432cb31afff3554198e0ad478a440763fb2e85bfb8b777ad8ec4749c321fd0dd012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2168
    # base commitment transaction fee = 3061
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6984939 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304502210088e8509b60534065e2097be1a4fc8590864850424f482306e33e4beef6c284ba022009a13b8984819c812f0dcacbcfc26c266d6c1a4c4ca966295896f75597a1eec7
    # local_signature = 304502210081e3e359864c94003bacf4c34cfac9a6698188aace28688b2329a2ff2bc6865b02206cdf48dd2ab4cc2e1049094857387646d995f7775cf22b53168769360a45f93f
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d0070000000000002200204117dad487a3c3bc07e34db505d567fcc263b30075f0b4679a1b27c297b4b147d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036eb946a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040048304502210081e3e359864c94003bacf4c34cfac9a6698188aace28688b2329a2ff2bc6865b02206cdf48dd2ab4cc2e1049094857387646d995f7775cf22b53168769360a45f93f0148304502210088e8509b60534065e2097be1a4fc8590864850424f482306e33e4beef6c284ba022009a13b8984819c812f0dcacbcfc26c266d6c1a4c4ca966295896f75597a1eec701475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 1)
    remote_htlc_signature = 3045022100cf346484186820d14676587587dffde8e9e55cfe22b7aebb9e31b2458361845a02204f9b62cb2c2af855cdd5839ac3edc5a2445fe8298410078b05f00e2b6fff12bc
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 30450221008e7d1872d3667cfa4afeb2bfec332df1b568bf445c434250aa0989b42208b59f022022a96192c31ac04e7279d87fb3ce10e34577493d9cae9a97ec76eb5456e20b69
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 3044022041a3810b0cd1604b3a64fee154b55c651bc737caceba0d2f87adc08263ecd453022035b5570078bdc4976571f7420cb5c184cb8ea234f2cdf9ab84045517050118c8
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 304402207fdf4b6a44e5ebf54845f1f9b059c1bbe4d41e7e06fd26c3d9593b493c72eb4f02207bf98f8884579eccf452f52acee46cc21d8c31e2e00f72ca80e4a4e481ad6609
    # local_signature = 304402202c0f8b27d2e944254f729b177da2797f8ed4bf8253b29b2d203f52f37223940c0220436ba1d95c3e9b21c63acdec8dd6a715ae6d8bfaef048dcfb3aa5f73386aab2a
    output htlc_success_tx 1: 020000000001010b9c9c5163b35adf821388e0e3b33467a111c01796706effde80b46493f87f710000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100cf346484186820d14676587587dffde8e9e55cfe22b7aebb9e31b2458361845a02204f9b62cb2c2af855cdd5839ac3edc5a2445fe8298410078b05f00e2b6fff12bc0147304402202c0f8b27d2e944254f729b177da2797f8ed4bf8253b29b2d203f52f37223940c0220436ba1d95c3e9b21c63acdec8dd6a715ae6d8bfaef048dcfb3aa5f73386aab2a012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3045022100cabb9fe80a272039c27ba87063c7d0dbd3deb3575547a10816318882508cb16a02207be0731516c14586eddc4764aa35bb17af1f8958591552df506ee05392ab0026
    output htlc_timeout_tx 2: 020000000001010b9c9c5163b35adf821388e0e3b33467a111c01796706effde80b46493f87f710100000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221008e7d1872d3667cfa4afeb2bfec332df1b568bf445c434250aa0989b42208b59f022022a96192c31ac04e7279d87fb3ce10e34577493d9cae9a97ec76eb5456e20b6901483045022100cabb9fe80a272039c27ba87063c7d0dbd3deb3575547a10816318882508cb16a02207be0731516c14586eddc4764aa35bb17af1f8958591552df506ee05392ab002601006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 304402203457efc398322a3e997dc89fe41927f37cb25f1f5b5cf2d8a7ab27b3f81584d6022055f6d7c706249c1c5ff3f61a69a82f45633bf4c2cd70b26e7dbcddec30d40b5a
    output htlc_timeout_tx 3: 020000000001010b9c9c5163b35adf821388e0e3b33467a111c01796706effde80b46493f87f710200000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022041a3810b0cd1604b3a64fee154b55c651bc737caceba0d2f87adc08263ecd453022035b5570078bdc4976571f7420cb5c184cb8ea234f2cdf9ab84045517050118c80147304402203457efc398322a3e997dc89fe41927f37cb25f1f5b5cf2d8a7ab27b3f81584d6022055f6d7c706249c1c5ff3f61a69a82f45633bf4c2cd70b26e7dbcddec30d40b5a01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 304402203047e2b04242b13601cedae12d2aac7e02298e96dfda7ab455b81595bf5ba5fd02202f1048568566ff17987f54efec49c607acc06ac73a89491b88cebf26685a8120
    output htlc_success_tx 4: 020000000001010b9c9c5163b35adf821388e0e3b33467a111c01796706effde80b46493f87f7103000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402207fdf4b6a44e5ebf54845f1f9b059c1bbe4d41e7e06fd26c3d9593b493c72eb4f02207bf98f8884579eccf452f52acee46cc21d8c31e2e00f72ca80e4a4e481ad66090147304402203047e2b04242b13601cedae12d2aac7e02298e96dfda7ab455b81595bf5ba5fd02202f1048568566ff17987f54efec49c607acc06ac73a89491b88cebf26685a8120012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2169
    # base commitment transaction fee = 2689
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985311 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100c5b421beaa860fb40fa14127ce51b01f63f0359f3c6fb83a1fa9cfd78ce876c302204644c1fef1299ac051559c542aed6903bcd8c58c0587296e2d57025e4e354ba9
    # local_signature = 3045022100970682c827d19dc2c0b3a0dc5b5423ed9bbfdf70536177401da31d9edf050c2602200c6754465782f62ee48e95387c9a86b82ae4bd04813ddf0485a8646ab670f16c
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0365f966a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100970682c827d19dc2c0b3a0dc5b5423ed9bbfdf70536177401da31d9edf050c2602200c6754465782f62ee48e95387c9a86b82ae4bd04813ddf0485a8646ab670f16c01483045022100c5b421beaa860fb40fa14127ce51b01f63f0359f3c6fb83a1fa9cfd78ce876c302204644c1fef1299ac051559c542aed6903bcd8c58c0587296e2d57025e4e354ba901475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 304502210087a5299eb74f0c65fd8297c17caec197dd8cdfbba5d5e21c8192f507c4968ab202206e363876ab33f0d1eb0732e32d0bde646b1456533a930ea605773ea791efed26
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 3044022030505fba2a63aad11201fb2c5aed37ae288863737c4d894338a8d836275b6338022056bfd21b79c01b36ee22ec4b6b41c75b50c77903736be845c3c040df5eb8570f
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 3045022100aae568798bd745bf832262964862dc2ef5a3ac807d034cde7f07bb2d8903239602203a88c51a692ac0e0ab285ef743ae8a8d0a2542dd288d5d8046d34016da04afb8
    # local_signature = 3045022100af43d0b1a5daf75f6d18f1b348a54b39033c4be672ca5a25a250168263ce503d022007ee1597bd9e0aed05e751907d59ca06b5ecbb79f7f4b0c6bfdc75942ab910dc
    output htlc_timeout_tx 2: 020000000001015364f7ccb1255576d6f7165d3cbf2ed189ce457d08c5cde485e5abf99b9b39160000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050048304502210087a5299eb74f0c65fd8297c17caec197dd8cdfbba5d5e21c8192f507c4968ab202206e363876ab33f0d1eb0732e32d0bde646b1456533a930ea605773ea791efed2601483045022100af43d0b1a5daf75f6d18f1b348a54b39033c4be672ca5a25a250168263ce503d022007ee1597bd9e0aed05e751907d59ca06b5ecbb79f7f4b0c6bfdc75942ab910dc01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 304402200a606fa2b49fb5ade57726a61c18e58b2be399281008b54745726dabab9d4c9b022010dd2cda9967fcd8e49617e95a3553c159df31fdad239bdd4bc2fd9cb2be4385
    output htlc_timeout_tx 3: 020000000001015364f7ccb1255576d6f7165d3cbf2ed189ce457d08c5cde485e5abf99b9b39160100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022030505fba2a63aad11201fb2c5aed37ae288863737c4d894338a8d836275b6338022056bfd21b79c01b36ee22ec4b6b41c75b50c77903736be845c3c040df5eb8570f0147304402200a606fa2b49fb5ade57726a61c18e58b2be399281008b54745726dabab9d4c9b022010dd2cda9967fcd8e49617e95a3553c159df31fdad239bdd4bc2fd9cb2be438501006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3044022036a34f4101d756c1f9fac495959377700f8c41c6088549e93bf2b1b66508548e02205069eb7866a7715a45bf3ea616b47f528e953c85cf69db363ec017fb6e71e729
    output htlc_success_tx 4: 020000000001015364f7ccb1255576d6f7165d3cbf2ed189ce457d08c5cde485e5abf99b9b391602000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100aae568798bd745bf832262964862dc2ef5a3ac807d034cde7f07bb2d8903239602203a88c51a692ac0e0ab285ef743ae8a8d0a2542dd288d5d8046d34016da04afb801473044022036a34f4101d756c1f9fac495959377700f8c41c6088549e93bf2b1b66508548e02205069eb7866a7715a45bf3ea616b47f528e953c85cf69db363ec017fb6e71e729012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2294
    # base commitment transaction fee = 2844
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985156 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402207e387e7e3646ba0cd45db3e35a768d294cbb96f59225f3151cf12ae4856788c602203c3cb2dbc2d18425b5c78969a8a3e6ff179a0af6e26f7cd260981845184b0ffb
    # local_signature = 30440220412f4f5e7738e0822e87093570297b4be7f486f0dd5e204ba59d3fe9732686f4022048734cbdaf8a8a29a0dbcbb11a47a2b913a15d83eac3eca2fe82a8a62fd0958f
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036c4956a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004730440220412f4f5e7738e0822e87093570297b4be7f486f0dd5e204ba59d3fe9732686f4022048734cbdaf8a8a29a0dbcbb11a47a2b913a15d83eac3eca2fe82a8a62fd0958f0147304402207e387e7e3646ba0cd45db3e35a768d294cbb96f59225f3151cf12ae4856788c602203c3cb2dbc2d18425b5c78969a8a3e6ff179a0af6e26f7cd260981845184b0ffb01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 304402205d551bc03f82aca8f89de6543377c4f0624f1d675c17e4f6af43bd598cc6ca2a022063ed1122937275103292657f1f01f42ccdc2f795b295db53d3fb4a64e7818b4f
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 3045022100d9ce83a146faeabff8518b50b0fc7243fc047d10cfb889abd4d8a3a8e991eb4e02207d121f22e960a01a8d277fe3968a46877f395c6f5ca2ea4bbf5027d352a7af2a
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 30440220716b626e9d739e190729af83fe02a586a51089160fd3eb932e47dc4ed5f12fe0022064b3b378780d8ce0aa0f0221a21a6d7784ac1018f9da65e0814109291034a894
    # local_signature = 304402201a79e8f7b63d3723064d1b117ab8f3be552ba6ff76c761c5b99e020fc1a66b5902206591f41ff79758111aa7ee80b999de583a03775b75bab218046df94bc62e5fd7
    output htlc_timeout_tx 2: 0200000000010169889bdd9390093733714e7af0f38005bdb1aa122e04479ab35b2160c0dce7d700000000000000000001cd010000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402205d551bc03f82aca8f89de6543377c4f0624f1d675c17e4f6af43bd598cc6ca2a022063ed1122937275103292657f1f01f42ccdc2f795b295db53d3fb4a64e7818b4f0147304402201a79e8f7b63d3723064d1b117ab8f3be552ba6ff76c761c5b99e020fc1a66b5902206591f41ff79758111aa7ee80b999de583a03775b75bab218046df94bc62e5fd701006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3044022070307b439a48b8e16265982544e6374a4f41cf1d80b9d9d680da7027d48b1767022030c7531bea8d9646a0c79971930c6b515664b142126696f0519e85b0053d8d39
    output htlc_timeout_tx 3: 0200000000010169889bdd9390093733714e7af0f38005bdb1aa122e04479ab35b2160c0dce7d701000000000000000001b5050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d9ce83a146faeabff8518b50b0fc7243fc047d10cfb889abd4d8a3a8e991eb4e02207d121f22e960a01a8d277fe3968a46877f395c6f5ca2ea4bbf5027d352a7af2a01473044022070307b439a48b8e16265982544e6374a4f41cf1d80b9d9d680da7027d48b1767022030c7531bea8d9646a0c79971930c6b515664b142126696f0519e85b0053d8d3901006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3044022014fea6f3b4a5970a2f584e10be99d3c931e01d2393445fc92cdb8742a000df2502205641dc12cb6fcffbec2652e9b2f7c3a89ed0383f23bc2c4c79d950281d7abeb0
    output htlc_success_tx 4: 0200000000010169889bdd9390093733714e7af0f38005bdb1aa122e04479ab35b2160c0dce7d7020000000000000000019d090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220716b626e9d739e190729af83fe02a586a51089160fd3eb932e47dc4ed5f12fe0022064b3b378780d8ce0aa0f0221a21a6d7784ac1018f9da65e0814109291034a89401473044022014fea6f3b4a5970a2f584e10be99d3c931e01d2393445fc92cdb8742a000df2502205641dc12cb6fcffbec2652e9b2f7c3a89ed0383f23bc2c4c79d950281d7abeb0012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2295
    # base commitment transaction fee = 2451
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985549 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100e858d59c407479f1fbe64849ef80f5535848c9b509329fc3895357641720e67c02207c6018822d79c59a46416a790fd841deb78729a9fe129ef9b954480601a0ae32
    # local_signature = 3045022100a1a83337bc08abc2e1e0ec076fd8955cd52654c4fecfda5085f4c1a80a795c0502207803dc3e7a16714386ccca408716def503d4d06f04ce2db317035c1f561b9492
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0364d976a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100a1a83337bc08abc2e1e0ec076fd8955cd52654c4fecfda5085f4c1a80a795c0502207803dc3e7a16714386ccca408716def503d4d06f04ce2db317035c1f561b949201483045022100e858d59c407479f1fbe64849ef80f5535848c9b509329fc3895357641720e67c02207c6018822d79c59a46416a790fd841deb78729a9fe129ef9b954480601a0ae3201475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3045022100ec8a8253af554ff19c70aaebcc4c980804fb74c942802a346b7d22a52f177550022003690a8cdb9cbed4f3b91aa7e54dcc525e801858012ba6a9d000bbaf39e7873e
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 304402206f80b711dbeb00d271225bb7063da85b1c3db0b9771b8cbce1a89cb6e4fa5cd202204da109f62e7153023b4ee44ca9b8b6799366c4bcc7d890fe26fe87654b933d3a
    # local_signature = 304402204b82a3b9721ce54991e6ca73c11f344a70dbc00df1823ea105c82d63100abf75022048a864f35009abbe76ab567e2250f2319d4c095e1e39c3a88af5a1846d7669b5
    output htlc_timeout_tx 3: 02000000000101f872151f1af1194fa3025f4266d7a68b1edb8c680c69d7f61558a9ae5066c0a100000000000000000001b5050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100ec8a8253af554ff19c70aaebcc4c980804fb74c942802a346b7d22a52f177550022003690a8cdb9cbed4f3b91aa7e54dcc525e801858012ba6a9d000bbaf39e7873e0147304402204b82a3b9721ce54991e6ca73c11f344a70dbc00df1823ea105c82d63100abf75022048a864f35009abbe76ab567e2250f2319d4c095e1e39c3a88af5a1846d7669b501006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 30440220081a522c1c98c5307be83b8562f7f95d94a3d6e52f90bd2dca1d56d2efa7f65e02202fcde5b7ac1e5d8b77c746cf569b5e7b721e149debf5b133feb57725b8fce079
    output htlc_success_tx 4: 02000000000101f872151f1af1194fa3025f4266d7a68b1edb8c680c69d7f61558a9ae5066c0a1010000000000000000019d090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402206f80b711dbeb00d271225bb7063da85b1c3db0b9771b8cbce1a89cb6e4fa5cd202204da109f62e7153023b4ee44ca9b8b6799366c4bcc7d890fe26fe87654b933d3a014730440220081a522c1c98c5307be83b8562f7f95d94a3d6e52f90bd2dca1d56d2efa7f65e02202fcde5b7ac1e5d8b77c746cf569b5e7b721e149debf5b133feb57725b8fce079012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3872
    # base commitment transaction fee = 4135
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6983865 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100cfa71cb1cc0523056bc195ab9d41faf9fdbde3ea793fcf686b10da8a63893b490220102a99f828ae77aa5ddb1aeffb33196d13e552167ddd090b37667783f9d6d9da
    # local_signature = 3045022100d102f5830a8c342028e6814b182945e8f5a089b2ee916c292a1b60b9dc65081902203c28957d11f8ebacd6ec4c7b7fa95c6f1dbe80a38d066625e1f1e906aca0ada5
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036b9906a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100d102f5830a8c342028e6814b182945e8f5a089b2ee916c292a1b60b9dc65081902203c28957d11f8ebacd6ec4c7b7fa95c6f1dbe80a38d066625e1f1e906aca0ada501483045022100cfa71cb1cc0523056bc195ab9d41faf9fdbde3ea793fcf686b10da8a63893b490220102a99f828ae77aa5ddb1aeffb33196d13e552167ddd090b37667783f9d6d9da01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3044022004ce547f69c05eae526b0f4da16f199d146ad6e67832250469ee59b5dd4e51f30220269a2b266daa43a531c300e21eeb572945cca254b0ba0907d574c334cafbb55d
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 3044022074b167dfa032f58611c87591680c4b8d5386dee7f68a347f8e6b85680e52ce520220555b5f31fa39e37efc75d520f1d8e3fae41748863702cc8d2f66f8d00dacd7ba
    # local_signature = 304402201759d91b7925e6f208993c5001a45bb2facbbcca68302ae2ec90e59e7b92d79d02203d0cd7228723b6720e1660fba027e684f3fec2463ace3789f680341164f27f5c
    output htlc_timeout_tx 3: 02000000000101764f514f625da07421ee83f6f1138b3b0a325312f42c5bc8f649834e0dff3c110000000000000000000192010000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022004ce547f69c05eae526b0f4da16f199d146ad6e67832250469ee59b5dd4e51f30220269a2b266daa43a531c300e21eeb572945cca254b0ba0907d574c334cafbb55d0147304402201759d91b7925e6f208993c5001a45bb2facbbcca68302ae2ec90e59e7b92d79d02203d0cd7228723b6720e1660fba027e684f3fec2463ace3789f680341164f27f5c01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3044022024eff1443972abf247e02665070d8195470f56510684be537c23fd15e39887b5022049c1ea5a469fc5f34a6b2664151206ff8150ac3bd02669b131d38da95f235168
    output htlc_success_tx 4: 02000000000101764f514f625da07421ee83f6f1138b3b0a325312f42c5bc8f649834e0dff3c11010000000000000000017a050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022074b167dfa032f58611c87591680c4b8d5386dee7f68a347f8e6b85680e52ce520220555b5f31fa39e37efc75d520f1d8e3fae41748863702cc8d2f66f8d00dacd7ba01473044022024eff1443972abf247e02665070d8195470f56510684be537c23fd15e39887b5022049c1ea5a469fc5f34a6b2664151206ff8150ac3bd02669b131d38da95f235168012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3873
    # base commitment transaction fee = 3470
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6984530 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402204aea8340a74b1ad2ccc149db8cae4ea8ca87bee3874291f238a8b3575fb4d94702203885c9b27fa44819c02767a50536e7dde2badcbff58492abd71eeb158668128a
    # local_signature = 30440220670c9bbffc08bf3b7afaa11b54b6da3a9ec2c104ad68c63a060200caeeb056ed02206c4f2e16735ad2517aa1051797cd90e1b684f1d7472948033308e3754dace6be
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03652936a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004730440220670c9bbffc08bf3b7afaa11b54b6da3a9ec2c104ad68c63a060200caeeb056ed02206c4f2e16735ad2517aa1051797cd90e1b684f1d7472948033308e3754dace6be0147304402204aea8340a74b1ad2ccc149db8cae4ea8ca87bee3874291f238a8b3575fb4d94702203885c9b27fa44819c02767a50536e7dde2badcbff58492abd71eeb158668128a01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 3045022100bae0f0f1116dedaf23eaec5fc9fd4ccda8a5f52a8a1c246a0a2b04b8ccf71299022025c91d2ac13010a8c9fd9b4c06d6cfe8adef38850352730a2ae18af653506759
    # local_signature = 3045022100df4e26dbc0a5860431c465caef214d11cdfcacfc33d74813ff5bbd58d909fa6802202f545551331cfc55da26a6f80ebd6c84a70289d2d1caad0cd5d8b630be8be483
    output htlc_success_tx 4: 020000000001015340dd3b159dd3498066b0ab1f06ba79721ca09b41a90037038f491234afdc5f000000000000000000017a050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100bae0f0f1116dedaf23eaec5fc9fd4ccda8a5f52a8a1c246a0a2b04b8ccf71299022025c91d2ac13010a8c9fd9b4c06d6cfe8adef38850352730a2ae18af65350675901483045022100df4e26dbc0a5860431c465caef214d11cdfcacfc33d74813ff5bbd58d909fa6802202f545551331cfc55da26a6f80ebd6c84a70289d2d1caad0cd5d8b630be8be483012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5149
    # base commitment transaction fee = 4613
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6983387 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100a1886113f74051fff92e6c549a5d39ace6b9ee51c6a6b86518ad4bb5d1158720022059421e01a12838946e03da07e29307c72bf8b486c9d80359e1235ec582a5f479
    # local_signature = 304402203ced9eb9d0ef8aed60615853a4c29c526b4f74515a763ad76d94d866192528ca0220301023778619919648a009809dfb45adb76f55cd83350c5461a0113a48eba85d
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036db8e6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402203ced9eb9d0ef8aed60615853a4c29c526b4f74515a763ad76d94d866192528ca0220301023778619919648a009809dfb45adb76f55cd83350c5461a0113a48eba85d01483045022100a1886113f74051fff92e6c549a5d39ace6b9ee51c6a6b86518ad4bb5d1158720022059421e01a12838946e03da07e29307c72bf8b486c9d80359e1235ec582a5f47901475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 3045022100fb4bdf470d9e9168f171d152975ca3b958b1e3c34ef27fc7530bc642f5c28f6d02202fd047aaed7b95a8694aca4b39e09feedaaed99f03119c2f3c9c629aa8cababc
    # local_signature = 3045022100b12c8fea69157ec53f1bd70af203e6080de97acf8f011b6c35aa6678eacf8c6202207e67ed4c9421fe55fa8d0de05b5d22bc4ffc3a53feb0a2a9cf3a1b75f18b2dc3
    output htlc_success_tx 4: 020000000001016880c046571697ecc7de48afd267b38a6a9bed851a9f2353b3d9c1242662f4280000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100fb4bdf470d9e9168f171d152975ca3b958b1e3c34ef27fc7530bc642f5c28f6d02202fd047aaed7b95a8694aca4b39e09feedaaed99f03119c2f3c9c629aa8cababc01483045022100b12c8fea69157ec53f1bd70af203e6080de97acf8f011b6c35aa6678eacf8c6202207e67ed4c9421fe55fa8d0de05b5d22bc4ffc3a53feb0a2a9cf3a1b75f18b2dc3012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 2 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5150
    # base commitment transaction fee = 3728
    # to-local amount 6984272 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100bd729fa3790528e36f6518f5efdcedc0b0e25650e156ca5684960de37fd1cf9c022004069b1771651d8ea77ac18d1d86219a1b1bd46e635db85d3b73a8293e42c191
    # local_signature = 304402202f5f5d8b3abbbfab4781d7b18ea0bbe9f3fd0e4fb538afdfab61e269bc1921760220357518aa91c1cda40f24ec64f32e685427f886d40ab22b9c4f1df9b87746f103
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03650926a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402202f5f5d8b3abbbfab4781d7b18ea0bbe9f3fd0e4fb538afdfab61e269bc1921760220357518aa91c1cda40f24ec64f32e685427f886d40ab22b9c4f1df9b87746f10301483045022100bd729fa3790528e36f6518f5efdcedc0b0e25650e156ca5684960de37fd1cf9c022004069b1771651d8ea77ac18d1d86219a1b1bd46e635db85d3b73a8293e42c19101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with 2 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651180
    # base commitment transaction fee = 6987454
    # to-local amount 546 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022017f82cdb8e5b1c443afe9191efdde7aa742e8f03c265bdab7df18a74b30711a7022009a5b4c676778c6bda8d87db551ae5d89ac792aff62011734afa1caf4bc857dd
    # local_signature = 3045022100bab11758e8182f7957047c19033df1b8294bc623a474efe4e1eb6519e49c7147022018af25c278ed3e9809dbf7f0b132ffccce6ff7b59a4a67f507a3648c46e5b3e5
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b800222020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0360400483045022100bab11758e8182f7957047c19033df1b8294bc623a474efe4e1eb6519e49c7147022018af25c278ed3e9809dbf7f0b132ffccce6ff7b59a4a67f507a3648c46e5b3e501473044022017f82cdb8e5b1c443afe9191efdde7aa742e8f03c265bdab7df18a74b30711a7022009a5b4c676778c6bda8d87db551ae5d89ac792aff62011734afa1caf4bc857dd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with 1 output untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651181
    # base commitment transaction fee = 6987455
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 30450221008dc967ec76f7a4837f00bdab1dc3e93c62cd28ec9931649dbb5f0b9105615bf702203fa4646c7f85b19d0bd4691a7ab89ee7243aa6f14a3a3744bed6fd6e0b6b17b9
    # local_signature = 304402204788ebe839058b6d917999d82ffa7ad235710d49b8f99aea7c8d95fe60ecc26502200c6ad2bcec214d83e66570bf22fa383f8e71b8991cd63feea018d2cd610b86f6
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8001c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036040047304402204788ebe839058b6d917999d82ffa7ad235710d49b8f99aea7c8d95fe60ecc26502200c6ad2bcec214d83e66570bf22fa383f8e71b8991cd63feea018d2cd610b86f6014830450221008dc967ec76f7a4837f00bdab1dc3e93c62cd28ec9931649dbb5f0b9105615bf702203fa4646c7f85b19d0bd4691a7ab89ee7243aa6f14a3a3744bed6fd6e0b6b17b901475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with fee greater than funder amount
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651936
    # base commitment transaction fee = 6988001
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 30450221008dc967ec76f7a4837f00bdab1dc3e93c62cd28ec9931649dbb5f0b9105615bf702203fa4646c7f85b19d0bd4691a7ab89ee7243aa6f14a3a3744bed6fd6e0b6b17b9
    # local_signature = 304402204788ebe839058b6d917999d82ffa7ad235710d49b8f99aea7c8d95fe60ecc26502200c6ad2bcec214d83e66570bf22fa383f8e71b8991cd63feea018d2cd610b86f6
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8001c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036040047304402204788ebe839058b6d917999d82ffa7ad235710d49b8f99aea7c8d95fe60ecc26502200c6ad2bcec214d83e66570bf22fa383f8e71b8991cd63feea018d2cd610b86f6014830450221008dc967ec76f7a4837f00bdab1dc3e93c62cd28ec9931649dbb5f0b9105615bf702203fa4646c7f85b19d0bd4691a7ab89ee7243aa6f14a3a3744bed6fd6e0b6b17b901475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

# Appendix D: Per-commitment Secret Generation Test Vectors

These test the generation algorithm which all nodes use.

## Generation tests

    name: generate_from_seed 0 final node
	seed: 0x0000000000000000000000000000000000000000000000000000000000000000
	I: 281474976710655
	output: 0x02a40c85b6f28da08dfdbe0926c53fab2de6d28c10301f8f7c4073d5e42e3148

	name: generate_from_seed FF final node
	seed: 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
	I: 281474976710655
	output: 0x7cc854b54e3e0dcdb010d7a3fee464a9687be6e8db3be6854c475621e007a5dc

	name: generate_from_seed FF alternate bits 1
	seed: 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
	I: 0xaaaaaaaaaaa
	output: 0x56f4008fb007ca9acf0e15b054d5c9fd12ee06cea347914ddbaed70d1c13a528

	name: generate_from_seed FF alternate bits 2
	seed: 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
	I: 0x555555555555
	output: 0x9015daaeb06dba4ccc05b91b2f73bd54405f2be9f217fbacd3c5ac2e62327d31

	name: generate_from_seed 01 last nontrivial node
	seed: 0x0101010101010101010101010101010101010101010101010101010101010101
	I: 1
	output: 0x915c75942a26bb3a433a8ce2cb0427c29ec6c1775cfc78328b57f6ba7bfeaa9c

## Storage tests

These test the optional compact storage system.  In many cases, an
incorrect entry cannot be determined until its parent is revealed; we
specifically corrupt an entry and all its children (except for the
last test, which would require another 8 samples to be detected).  For
these tests we use a seed of `0xFFF...FF` and incorrect entries are
seeded with `0x000...00`.

    name: insert_secret correct sequence
	I: 281474976710655
	secret: 0x7cc854b54e3e0dcdb010d7a3fee464a9687be6e8db3be6854c475621e007a5dc
	output: OK
	I: 281474976710654
	secret: 0xc7518c8ae4660ed02894df8976fa1a3659c1a8b4b5bec0c4b872abeba4cb8964
	output: OK
	I: 281474976710653
	secret: 0x2273e227a5b7449b6e70f1fb4652864038b1cbf9cd7c043a7d6456b7fc275ad8
	output: OK
	I: 281474976710652
	secret: 0x27cddaa5624534cb6cb9d7da077cf2b22ab21e9b506fd4998a51d54502e99116
	output: OK
	I: 281474976710651
	secret: 0xc65716add7aa98ba7acb236352d665cab17345fe45b55fb879ff80e6bd0c41dd
	output: OK
	I: 281474976710650
	secret: 0x969660042a28f32d9be17344e09374b379962d03db1574df5a8a5a47e19ce3f2
	output: OK
	I: 281474976710649
	secret: 0xa5a64476122ca0925fb344bdc1854c1c0a59fc614298e50a33e331980a220f32
	output: OK
	I: 281474976710648
	secret: 0x05cde6323d949933f7f7b78776bcc1ea6d9b31447732e3802e1f7ac44b650e17
	output: OK

    name: insert_secret #1 incorrect
	I: 281474976710655
	secret: 0x02a40c85b6f28da08dfdbe0926c53fab2de6d28c10301f8f7c4073d5e42e3148
	output: OK
	I: 281474976710654
	secret: 0xc7518c8ae4660ed02894df8976fa1a3659c1a8b4b5bec0c4b872abeba4cb8964
	output: ERROR

    name: insert_secret #2 incorrect (#1 derived from incorrect)
	I: 281474976710655
	secret: 0x02a40c85b6f28da08dfdbe0926c53fab2de6d28c10301f8f7c4073d5e42e3148
	output: OK
	I: 281474976710654
	secret: 0xdddc3a8d14fddf2b68fa8c7fbad2748274937479dd0f8930d5ebb4ab6bd866a3
	output: OK
	I: 281474976710653
	secret: 0x2273e227a5b7449b6e70f1fb4652864038b1cbf9cd7c043a7d6456b7fc275ad8
	output: OK
	I: 281474976710652
	secret: 0x27cddaa5624534cb6cb9d7da077cf2b22ab21e9b506fd4998a51d54502e99116
	output: ERROR

    name: insert_secret #3 incorrect
	I: 281474976710655
	secret: 0x7cc854b54e3e0dcdb010d7a3fee464a9687be6e8db3be6854c475621e007a5dc
	output: OK
	I: 281474976710654
	secret: 0xc7518c8ae4660ed02894df8976fa1a3659c1a8b4b5bec0c4b872abeba4cb8964
	output: OK
	I: 281474976710653
	secret: 0xc51a18b13e8527e579ec56365482c62f180b7d5760b46e9477dae59e87ed423a
	output: OK
	I: 281474976710652
	secret: 0x27cddaa5624534cb6cb9d7da077cf2b22ab21e9b506fd4998a51d54502e99116
	output: ERROR

    name: insert_secret #4 incorrect (1,2,3 derived from incorrect)
	I: 281474976710655
	secret: 0x02a40c85b6f28da08dfdbe0926c53fab2de6d28c10301f8f7c4073d5e42e3148
	output: OK
	I: 281474976710654
	secret: 0xdddc3a8d14fddf2b68fa8c7fbad2748274937479dd0f8930d5ebb4ab6bd866a3
	output: OK
	I: 281474976710653
	secret: 0xc51a18b13e8527e579ec56365482c62f180b7d5760b46e9477dae59e87ed423a
	output: OK
	I: 281474976710652
	secret: 0xba65d7b0ef55a3ba300d4e87af29868f394f8f138d78a7011669c79b37b936f4
	output: OK
	I: 281474976710651
	secret: 0xc65716add7aa98ba7acb236352d665cab17345fe45b55fb879ff80e6bd0c41dd
	output: OK
	I: 281474976710650
	secret: 0x969660042a28f32d9be17344e09374b379962d03db1574df5a8a5a47e19ce3f2
	output: OK
	I: 281474976710649
	secret: 0xa5a64476122ca0925fb344bdc1854c1c0a59fc614298e50a33e331980a220f32
	output: OK
	I: 281474976710648
	secret: 0x05cde6323d949933f7f7b78776bcc1ea6d9b31447732e3802e1f7ac44b650e17
	output: ERROR
	
    name: insert_secret #5 incorrect
	I: 281474976710655
	secret: 0x7cc854b54e3e0dcdb010d7a3fee464a9687be6e8db3be6854c475621e007a5dc
	output: OK
	I: 281474976710654
	secret: 0xc7518c8ae4660ed02894df8976fa1a3659c1a8b4b5bec0c4b872abeba4cb8964
	output: OK
	I: 281474976710653
	secret: 0x2273e227a5b7449b6e70f1fb4652864038b1cbf9cd7c043a7d6456b7fc275ad8
	output: OK
	I: 281474976710652
	secret: 0x27cddaa5624534cb6cb9d7da077cf2b22ab21e9b506fd4998a51d54502e99116
	output: OK
	I: 281474976710651
	secret: 0x631373ad5f9ef654bb3dade742d09504c567edd24320d2fcd68e3cc47e2ff6a6
	output: OK
	I: 281474976710650
	secret: 0x969660042a28f32d9be17344e09374b379962d03db1574df5a8a5a47e19ce3f2
	output: ERROR

    name: insert_secret #6 incorrect (5 derived from incorrect)
	I: 281474976710655
	secret: 0x7cc854b54e3e0dcdb010d7a3fee464a9687be6e8db3be6854c475621e007a5dc
	output: OK
	I: 281474976710654
	secret: 0xc7518c8ae4660ed02894df8976fa1a3659c1a8b4b5bec0c4b872abeba4cb8964
	output: OK
	I: 281474976710653
	secret: 0x2273e227a5b7449b6e70f1fb4652864038b1cbf9cd7c043a7d6456b7fc275ad8
	output: OK
	I: 281474976710652
	secret: 0x27cddaa5624534cb6cb9d7da077cf2b22ab21e9b506fd4998a51d54502e99116
	output: OK
	I: 281474976710651
	secret: 0x631373ad5f9ef654bb3dade742d09504c567edd24320d2fcd68e3cc47e2ff6a6
	output: OK
	I: 281474976710650
	secret: 0xb7e76a83668bde38b373970155c868a653304308f9896692f904a23731224bb1
	output: OK
	I: 281474976710649
	secret: 0xa5a64476122ca0925fb344bdc1854c1c0a59fc614298e50a33e331980a220f32
	output: OK
	I: 281474976710648
	secret: 0x05cde6323d949933f7f7b78776bcc1ea6d9b31447732e3802e1f7ac44b650e17
	output: ERROR

    name: insert_secret #7 incorrect
	I: 281474976710655
	secret: 0x7cc854b54e3e0dcdb010d7a3fee464a9687be6e8db3be6854c475621e007a5dc
	output: OK
	I: 281474976710654
	secret: 0xc7518c8ae4660ed02894df8976fa1a3659c1a8b4b5bec0c4b872abeba4cb8964
	output: OK
	I: 281474976710653
	secret: 0x2273e227a5b7449b6e70f1fb4652864038b1cbf9cd7c043a7d6456b7fc275ad8
	output: OK
	I: 281474976710652
	secret: 0x27cddaa5624534cb6cb9d7da077cf2b22ab21e9b506fd4998a51d54502e99116
	output: OK
	I: 281474976710651
	secret: 0xc65716add7aa98ba7acb236352d665cab17345fe45b55fb879ff80e6bd0c41dd
	output: OK
	I: 281474976710650
	secret: 0x969660042a28f32d9be17344e09374b379962d03db1574df5a8a5a47e19ce3f2
	output: OK
	I: 281474976710649
	secret: 0xe7971de736e01da8ed58b94c2fc216cb1dca9e326f3a96e7194fe8ea8af6c0a3
	output: OK
	I: 281474976710648
	secret: 0x05cde6323d949933f7f7b78776bcc1ea6d9b31447732e3802e1f7ac44b650e17
	output: ERROR

    name: insert_secret #8 incorrect
	I: 281474976710655
	secret: 0x7cc854b54e3e0dcdb010d7a3fee464a9687be6e8db3be6854c475621e007a5dc
	output: OK
	I: 281474976710654
	secret: 0xc7518c8ae4660ed02894df8976fa1a3659c1a8b4b5bec0c4b872abeba4cb8964
	output: OK
	I: 281474976710653
	secret: 0x2273e227a5b7449b6e70f1fb4652864038b1cbf9cd7c043a7d6456b7fc275ad8
	output: OK
	I: 281474976710652
	secret: 0x27cddaa5624534cb6cb9d7da077cf2b22ab21e9b506fd4998a51d54502e99116
	output: OK
	I: 281474976710651
	secret: 0xc65716add7aa98ba7acb236352d665cab17345fe45b55fb879ff80e6bd0c41dd
	output: OK
	I: 281474976710650
	secret: 0x969660042a28f32d9be17344e09374b379962d03db1574df5a8a5a47e19ce3f2
	output: OK
	I: 281474976710649
	secret: 0xa5a64476122ca0925fb344bdc1854c1c0a59fc614298e50a33e331980a220f32
	output: OK
	I: 281474976710648
	secret: 0xa7efbc61aac46d34f77778bac22c8a20c6a46ca460addc49009bda875ec88fa4
	output: ERROR
	
# Appendix E: Key Derivation Test Vectors

These test the derivation for `localkey`, `remotekey`, `local-delayedkey` and
`remote-delayedkey` (which use the formula), as well as the `revocation-key`.

All of them use the following secrets (and thus the derived points):

    base_secret: 0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
    per_commitment_secret: 0x1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a09080706050403020100
    base_point: 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2
    per_commitment_point: 0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486

    name: derivation of key from basepoint and per-commitment-point
    # SHA256(per-commitment-point || basepoint)
    # => SHA256(0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486 || 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0xcbcdd70fcfad15ea8e9e5c5a12365cf00912504f08ce01593689dd426bca9ff0
    # + basepoint (0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0x0235f2dbfaa89b57ec7b055afe29849ef7ddfeb1cefdb9ebdc43f5494984db29e5
    localkey: 0x0235f2dbfaa89b57ec7b055afe29849ef7ddfeb1cefdb9ebdc43f5494984db29e5

    name: derivation of secret key from basepoint secret and per-commitment-secret
	# SHA256(per-commitment-point || basepoint)
    # => SHA256(0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486 || 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0xcbcdd70fcfad15ea8e9e5c5a12365cf00912504f08ce01593689dd426bca9ff0
    # + basepoint_secret (0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f)
    # = 0xcbced912d3b21bf196a766651e436aff192362621ce317704ea2f75d87e7be0f
    localprivkey: 0xcbced912d3b21bf196a766651e436aff192362621ce317704ea2f75d87e7be0f

    name: derivation of revocation key from basepoint and per-commitment-point
    # SHA256(revocation-basepoint || per-commitment-point)
    # => SHA256(0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2 || 0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486)
    # = 0xefbf7ba5a074276701798376950a64a90f698997cce0dff4d24a6d2785d20963
    # x revocation-basepoint = 0x02c00c4aadc536290422a807250824a8d87f19d18da9d610d45621df22510db8ce
    # SHA256(per-commitment-point || revocation-basepoint)
    # => SHA256(0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486 || 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0xcbcdd70fcfad15ea8e9e5c5a12365cf00912504f08ce01593689dd426bca9ff0
    # x per-commitment-point = 0x0325ee7d3323ce52c4b33d4e0a73ab637711057dd8866e3b51202a04112f054c43
    # 0x02c00c4aadc536290422a807250824a8d87f19d18da9d610d45621df22510db8ce + 0x0325ee7d3323ce52c4b33d4e0a73ab637711057dd8866e3b51202a04112f054c43 => 0x02916e326636d19c33f13e8c0c3a03dd157f332f3e99c317c141dd865eb01f8ff0
    revocationkey: 0x02916e326636d19c33f13e8c0c3a03dd157f332f3e99c317c141dd865eb01f8ff0

    name: derivation of revocation secret from basepoint-secret and per-commitment-secret
    # SHA256(revocation-basepoint || per-commitment-point)
    # => SHA256(0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2 || 0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486)
    # = 0xefbf7ba5a074276701798376950a64a90f698997cce0dff4d24a6d2785d20963
    # * revocation-basepoint-secret (0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f)# = 0x44bfd55f845f885b8e60b2dca4b30272d5343be048d79ce87879d9863dedc842
    # SHA256(per-commitment-point || revocation-basepoint)
    # => SHA256(0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486 || 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0xcbcdd70fcfad15ea8e9e5c5a12365cf00912504f08ce01593689dd426bca9ff0
    # * per-commitment-secret (0x1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a09080706050403020100)# = 0x8be02a96a97b9a3c1c9f59ebb718401128b72ec009d85ee1656319b52319b8ce
    # => 0xd09ffff62ddb2297ab000cc85bcb4283fdeb6aa052affbc9dddcf33b61078110
    revocationprivkey: 0xd09ffff62ddb2297ab000cc85bcb4283fdeb6aa052affbc9dddcf33b61078110

# References

# Authors

FIXME

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).

