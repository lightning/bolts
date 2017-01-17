# BOLT #3: Bitcoin Transaction and Script Formats

This details the exact format of on-chain transactions, which both sides need to agree on to ensure signatures are valid.  That is, the funding transaction output script, commitment transactions and the HTLC transactions.

# Table of Contents
  * [Transactions](#transactions)
    * [Transaction input and output ordering](#transaction-input-and-outpu-ordering)
    * [Use of segwit](#use-of-segwit)
    * [Funding Transaction Output](#funding-transaction-output)
    * [Commitment Transaction](#commitment-transaction)
        * [Commitment Transaction Outputs](#commitment-transaction-outputs)
        * [To-Local Output](#to-local-output)
        * [To-Remote Output](#to-remote-output)
        * [Offered HTLC Outputs](#offered-htlc-outputs)
        * [Received HTLC Outputs](#received-htlc-outputs)
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
* locktime: upper 8 bits are zero, lower 24 bits are the lower 24 bits of the obscured commitment transaction number.
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

The amounts for each output are rounded down to whole satoshis.  If this amount, minus the fees for the HTLC transaction is less than the `dust-limit-satoshis` set by the owner of the commitment transaction, the output is not produced (thus the funds add to fees).

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

This output sends funds to the other peer, thus is a simple P2PKH to `remotekey`.

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

## HTLC-Timeout and HTLC-Success Transactions
These HTLC transactions are almost identical, except the HTLC-Timeout transaction is timelocked.  This is also the transaction which can be spent by a valid penalty transaction.

* version: 2
* txin: the commitment transaction HTLC output.
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

    Commitment weight:   724 + 172 * num-htlc-outputs
    HTLC-timeout weight: 634
    HTLC-success weight: 671

#### Requirements

The fee for an HTLC-timeout transaction MUST BE calculated to match:

1. Multiply `feerate-per-kw` by 634 and divide by 1024 (rounding down).

The fee for an HTLC-success transaction MUST BE calculated to match:

1. Multiply `feerate-per-kw` by 671 and divide by 1024 (rounding down).

The fee for a commitment transaction MUST BE calculated to match:

1. Start with `weight` = 724, and `fee` = 0.

2. For every offered HTLC, if the HTLC amount is greater or equal to the local node's
   `dust-limit-satoshis` plus the HTLC-timeout
   transaction fee, then add 172 to `weight`, otherwise add
   the HTLC amount to `fee`.

3. For every accepted HTLC, if the HTLC amount is greater or equal to the local node's
   `dust-limit-satoshis` plus the HTLC-success
   transaction fee, then add 172 to `weight`, otherwise add
   the HTLC amount to `fee`.

4. Multiply `feerate-per-kw` by `weight`, divide by 1024 (rounding down),
   and add to `fee`.
   
#### Example

For example, suppose that we have a `feerate-per-kw` of 5000, a `dust-limit` of 546 satoshis, and commitment transaction with:
* 2 offered HTLCs of 5000000 and 1000000 millisatoshis (5000 and 1000 satoshis)
* 2 received HTLCs of 7000000 and 800000 millisatoshis (7000 and 800 satoshis)

The commitment transaction fee would be 6214 satoshis
The HTLC timeout transaction fee would be 3095 satoshis
The HTLC success transaction fee would be 3276 satoshis

The offered HTLC of 5000 satoshis is above 546 + 3095 and would result in:
* an output of 5000 satoshi in the commitment transaction
* a HTLC timeout transaction of 5000 - 3095 satoshis which spends this output

The offered HTLC of 1000 satoshis is below 546 + 3095, and its amount would be added to the commitment transaction fee

The received HTLC of 7000 satoshis is above 546 + 3276 and would result in:
* an output of 7000 satoshi in the commitment transaction
* a HTLC success transaction of 7000 - 3276 satoshis which spends this output

The received HTLC of 800 satoshis is below 546 + 3276 and its amount would be added to the commitment transaction fee

### Fee Payment

Fees will be extracted from the funder's amount, or if that is insufficient, will use the entire amount of the funder's output.

A node MAY fail the channel if the resulting fee rate is too low.

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

# Appendix B: Transactions Test Vectors

In the following:
 - we consider *local* transactions, which implies that all payments to *local* are delayed
 - we assume that *local* is the funder
 
We start by defining common parameters used in all tests.

    funding_tx_hash: 42a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7
    funding_output_index: 1
    funding_amount_satoshi: 10000000
    local_funding_key: 30ff4956bbdd3222d44cc5e8a1261dab1e07957bdac5ae88fe3261ef321f374901
    remote_funding_key: 1552dfba4f6cf29a62a0af13c8d6981d36d0ef8d61ba10fb0fe90da7634d7e1301
    local_revocation_key: 131526c63723ff1d36c28e61a8bdc86660d7893879bbda4cfeaad2022db7c10901
    local_payment_key: e937268a37a774aa948ebddff3187fedc7035e3f0a029d8d85f31bda33b02d5501
    remote_payment_key: ce65059278a571ee4f4c9b4d5d7fa07449bbe09d9c716879343d9e975df1de3301
    local_delay: 144
    local_dust_limit_satoshi: 546
    local_feerate_per_kw: 15000

    name: simple tx with two outputs
    to_local_msat: 7000000000
    to_remote_msat: 3000000000
    output commit_tx: 020000000142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba701000000005347388002c0c62d00000000001600141844e52616af46f531635b5b770737ec5695a08b53a66a00000000002200201c1a9b14ca64510fa53ec4a910dfbf023983489f82f3f51c5884941ef0d1944234ee4e00

    name: two outputs with fundee below dust limit
    to_local_msat: 9999000000
    to_remote_msat: 1000000
    output commit_tx: 020000000142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba701000000005347388002e8030000000000001600141844e52616af46f531635b5b770737ec5695a08b2b699800000000002200201c1a9b14ca64510fa53ec4a910dfbf023983489f82f3f51c5884941ef0d1944234ee4e00

    name: with htlcs, all above dust limit
    to_local_msat: 6970000000
    to_remote_msat: 3000000000
    htlc 0 direction: local->remote
    htlc 0 amount_msat: 10000000
    htlc 0 expiry: 443210
    htlc 0 payment_hash: 4231f5cbd75de98283f65f0eadf95ba05cd7331c94d88934a69031fda244d70e
    htlc 1 direction: remote->local
    htlc 1 amount_msat: 20000000
    htlc 1 expiry: 453203
    htlc 1 payment_hash: a44748f172677f67585ea34acf38fdc8f7c566c34e176842f2d87d2afa16f240
    output commit_tx: 020000000142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba70100000000534738800410270000000000002200207d8a3d7311cf89ac5e3110bf97a68fa69c0079cd0329d56135d5246638828202204e000000000000220020fca23ba30fe0400a01af3c1ca47ceeb679bff7bad703f0e44c7d3266faea88ccc0c62d00000000001600141844e52616af46f531635b5b770737ec5695a08b741d6a00000000002200201c1a9b14ca64510fa53ec4a910dfbf023983489f82f3f51c5884941ef0d1944234ee4e00
    output htlc_timeout_tx 0: 02000000015ffa1b4fea9232e5ca2b705474dc261c5e93617ed75d284061b27abaaacb2f1f0000000000ffffffff01c9020000000000002200201c1a9b14ca64510fa53ec4a910dfbf023983489f82f3f51c5884941ef0d194424ac30600
    output htlc_success_tx 0: 02000000015ffa1b4fea9232e5ca2b705474dc261c5e93617ed75d284061b27abaaacb2f1f0100000000ffffffff01bb270000000000002200201c1a9b14ca64510fa53ec4a910dfbf023983489f82f3f51c5884941ef0d1944200000000

    name: with htlcs, some below dust limit
    to_local_msat: 6839700000
    to_remote_msat: 3000000000
    htlc 0 direction: remote->local
    htlc 0 amount_msat: 130000000
    htlc 0 expiry: 445678
    htlc 0 payment_hash: c6420effb8e0c5239edb2acf6dd40a8fcfbe6ae96eb71bf75fb9a04bec230d68
    htlc 1 direction: remote->local
    htlc 1 amount_msat: 100000
    htlc 1 expiry: 448763
    htlc 1 payment_hash: 458397eca14e17f29c5b388b5454b5d44a9cab17cab68198dd02a7ab54f8dfb7
    htlc 2 direction: local->remote
    htlc 2 amount_msat: 200000
    htlc 2 expiry: 443120
    htlc 2 payment_hash: ca1153ea17994d47369342eef5f11d92d2855e0fec34b337dd8eed978b3e9339
    htlc 3 direction: local->remote
    htlc 3 amount_msat: 10000000
    htlc 3 expiry: 443210
    htlc 3 payment_hash: ae150412bcd53556bf52f03eccfc7a39ee516ffd45288d5dcc4d5b8720feb353
    htlc 4 direction: remote->local
    htlc 4 amount_msat: 20000000
    htlc 4 expiry: 445435
    htlc 4 payment_hash: 9b61ef0df1f9cecfe8b09881f93459db46355ba136058b7b99a8c143a3495e9b
    output commit_tx: 020000000142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000053473880051027000000000000220020aa135872238ade884390f2db277186bab2fa4aa4c92137e137558a482f217206204e000000000000220020456a02eb2b2e32d1f5cc126ed4b59c36996c1280dd30760d274e03c86f30f7a5d0fb01000000000022002095c9d9e8a78e97242682d84f7307ae8a6a628543b6c00ff44a11b43d0472713cc0c62d00000000001600141844e52616af46f531635b5b770737ec5695a08bf1026800000000002200201c1a9b14ca64510fa53ec4a910dfbf023983489f82f3f51c5884941ef0d1944234ee4e00
    output htlc_timeout_tx 0: 02000000015fff92d583678f5a84f137cf4626cc5aca536df458158e0e121e894eaf6cd92e0000000000ffffffff01c9020000000000002200201c1a9b14ca64510fa53ec4a910dfbf023983489f82f3f51c5884941ef0d194424ac30600
    output htlc_success_tx 0: 02000000015fff92d583678f5a84f137cf4626cc5aca536df458158e0e121e894eaf6cd92e0200000000ffffffff016bd50100000000002200201c1a9b14ca64510fa53ec4a910dfbf023983489f82f3f51c5884941ef0d1944200000000
    output htlc_success_tx 1: 02000000015fff92d583678f5a84f137cf4626cc5aca536df458158e0e121e894eaf6cd92e0100000000ffffffff01bb270000000000002200201c1a9b14ca64510fa53ec4a910dfbf023983489f82f3f51c5884941ef0d1944200000000

# Appendix C: Per-commitment Secret Generation Test Vectors

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
	
# Appendix D: Key Derivation Test Vectors

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

