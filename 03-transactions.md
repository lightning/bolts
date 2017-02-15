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
    HTLC-timeout weight: 635
    HTLC-success weight: 673

Note that we refer to the "base fee" for a commitment transaction in the requirements below, which is what the funder pays.  The actual fee may be higher than the amount calculated here, due to rounding and trimmed outputs.

#### Requirements

The fee for an HTLC-timeout transaction MUST BE calculated to match:

1. Multiply `feerate-per-kw` by 635 and divide by 1000 (rounding down).

The fee for an HTLC-success transaction MUST BE calculated to match:

1. Multiply `feerate-per-kw` by 673 and divide by 1000 (rounding down).

The base fee for a commitment transaction MUST BE calculated to match:

1. Start with `weight` = 724.

2. For each committed HTLC, if that output is not trimmed as specified in
   [Trimmed Outputs](#trimmed-outputs), add 172 to `weight`.

3. Multiply `feerate-per-kw` by `weight`, divide by 1000 (rounding down).

#### Example

For example, suppose that we have a `feerate-per-kw` of 5000, a `dust-limit-satoshis` of 546 satoshis, and commitment transaction with:
* 2 offered HTLCs of 5000000 and 1000000 millisatoshis (5000 and 1000 satoshis)
* 2 received HTLCs of 7000000 and 800000 millisatoshis (7000 and 800 satoshis)

The HTLC timeout transaction weight is 635, thus fee would be 3175 satoshis.
The HTLC success transaction weight is 673, thus fee would be 3365 satoshis

The commitment transaction weight would be calculated as follows:

* weight starts at 724.

* The offered HTLC of 5000 satoshis is above 546 + 3175 and would result in:
  * an output of 5000 satoshi in the commitment transaction
  * a HTLC timeout transaction of 5000 - 3175 satoshis which spends this output
  * weight increases to 896

* The offered HTLC of 1000 satoshis is below 546 + 3175, so would be trimmed.

* The received HTLC of 7000 satoshis is above 546 + 3365 and would result in:
  * an output of 7000 satoshi in the commitment transaction
  * a HTLC success transaction of 7000 - 3365 satoshis which spends this output
  * weight increases to 1068

* The received HTLC of 800 satoshis is below 546 + 3365 so would be trimmed.

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

    accepted_htlc_script: 111 bytes
	    - OP_DATA: 1 byte (remotekey length)
		- remotekey: 33 bytes
		- OP_SWAP: 1 byte
		- OP_SIZE: 1 byte
		- OP_DATA: 1 byte (32 length)
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
		- OP_DATA: 1 byte (locktime length)
		- locktime: 3 bytes
		- OP_CHECKLOCKTIMEVERIFY: 1 byte
		- OP_DROP: 1 byte
        - OP_CHECKSIG: 1 byte
		- OP_ENDIF: 1 byte

    offered_htlc_script: 105 bytes
		- OP_DATA: 1 byte (remotekey length)
		- remotekey: 33 bytes
		- OP_SWAP: 1 byte
		- OP_SIZE: 1 byte
		- OP_DATA: 1 byte (32 length)
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

    timeout_witness: 257 bytes
		- number_of_witness_elements: 1 byte
		- nil_length: 1 byte
		- sig_alice_length: 1 byte
		- sig_alice: 73 bytes
		- sig_bob_length: 1 byte
		- sig_bob: 73 bytes
		- nil_length: 1 byte
		- witness_script_length: 1 byte
		- witness_script (offered_htlc_script)

    success_witness: 295 bytes
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
the witness data for each case (257 + 2 for HTLC-timeout, 295 + 2 for
HTLC-success) gives a weight of:

	635 (HTLC-timeout)
	673 (HTLC-success)

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
# From local_revocation_basepoint_secret
INTERNAL: local_revocation_basepoint: 02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
# From local_delayed_payment_basepoint_secret
INTERNAL: local_delayed_payment_basepoint: 023c72addb4fdf09af94f0c94d7fe92a386a7e70cf8a1d85916386bb2535c7b1b1
INTERNAL: local_per_commitment_point: 025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486
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
    remotekey: 0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b
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
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100f51d2e566a70ba740fc5d8c0f07b9b93d2ed741c3c0860c613173de7d39e7968022041376d520e9c0e1ad52248ddf4b22e12be8763007df977253ef45a4ca3bdb7c0
    # local_signature = 3044022051b75c73198c6deee1a875871c3961832909acd297c6b908d59e3319e5185a46022055c419379c5051a78d00dbbce11b5b664a0c22815fbcc6fcef6b1937c3836939
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8002c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311054a56a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022051b75c73198c6deee1a875871c3961832909acd297c6b908d59e3319e5185a46022055c419379c5051a78d00dbbce11b5b664a0c22815fbcc6fcef6b1937c383693901483045022100f51d2e566a70ba740fc5d8c0f07b9b93d2ed741c3c0860c613173de7d39e7968022041376d520e9c0e1ad52248ddf4b22e12be8763007df977253ef45a4ca3bdb7c001475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with all 5 htlcs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 0
    # base commitment transaction fee = 0
    # HTLC 2 offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC 3 offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC 0 received amount 1000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac68
    # HTLC 1 received amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6988000 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 30450221008f60b91c64ffaeb498bca51827c378a5a0c3488888677cd8483b42bae7222269022028e7ff07936b62327bd43f5c27c2cbc28351242bcb3b4a9f77e0fc3ee8558c93
    # local_signature = 3045022100ce8a5a47e1377b7878c65209affe5645e400f0b834ddcbd2248a961c034686590220349d27b5a3bd2dac4117bdcf6a94449b0e4a5b179aef1d6b23f526081cdfe8ab
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8007e8030000000000002200207eaf624c3ab8f5cad0589f46db3fed940bf79a88fb5ab7fa3a6e1d071b5845bfd00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78d007000000000000220020edcdff3e4bb6b538c0ee9639f56dfc4f222e5077bface165abc48764160da0c2b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110e0a06a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100ce8a5a47e1377b7878c65209affe5645e400f0b834ddcbd2248a961c034686590220349d27b5a3bd2dac4117bdcf6a94449b0e4a5b179aef1d6b23f526081cdfe8ab014830450221008f60b91c64ffaeb498bca51827c378a5a0c3488888677cd8483b42bae7222269022028e7ff07936b62327bd43f5c27c2cbc28351242bcb3b4a9f77e0fc3ee8558c9301475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 3044022056ac6967aa077841c05f0913c1b053802cfd151bb1fcf37c2d1d7b83222d2b4902207b549e33be640a9832987349fd9eb3ecafae20fdf22fa9f131bde787fbf46313
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 3045022100a34b05a95f131afb1b459d29a975a9c7c9b3ffd65a334958e4427697fb16c2ae0220233c50db9fd05eb9abce00225af2c5b33ffb595b88d3aa347b1198c4f46cd255
    # signature for output 2 (htlc 1)
    remote_htlc_signature = 3044022018115b421de0a76eba67a932bbe6004f031cf3019330d13fa57bea4c2478bb81022000d6bbbc1e2aee760ff0d3e4b94a194b1a1f7f8f8681357ff1ee655bde2dc27a
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 30450221009f8aa1b587474f4b4af7dd9795287aa038e3b064d0d781acd047b14d6708756b022044e6ce746548a99f01f1beb0fc09e996dd9e893895fd184477d79d44ba087a2b
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 3045022100d41900c2f5539f97c8dde8b3d26906e94cc9f84ee8f4fba408b49d88713df6320220296f4886681f2bb8fd120bcb8b8bc50a7e0c90b4d5b62ab953ff8eb2c68ecbdc
    # local_signature = 30440220789e447081e83c7248c85badd21c5cbdd3336091628514744011b504600b7ed8022053bbbb93c761e6784d45ab16226d9b59afbf1fa4490332df7e7764326c2ed065
    output htlc_success_tx 0: 02000000000101e7ba31f387356434fbfcb332390bf7c98934445aa5b011d06efc3a2337777e1f00000000000000000001e8030000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022056ac6967aa077841c05f0913c1b053802cfd151bb1fcf37c2d1d7b83222d2b4902207b549e33be640a9832987349fd9eb3ecafae20fdf22fa9f131bde787fbf46313014730440220789e447081e83c7248c85badd21c5cbdd3336091628514744011b504600b7ed8022053bbbb93c761e6784d45ab16226d9b59afbf1fa4490332df7e7764326c2ed065012000000000000000000000000000000000000000000000000000000000000000006e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac6800000000
    # local_signature = 30450221008b4943e473ae4457124b7bf05ff4b12a4a2eddee33689a841464b40ec2e6018802202c5515d12df8f06c71ff868dd0bd9ad172deef69101debb3b8c77bb30042ccf4
    output htlc_timeout_tx 2: 02000000000101e7ba31f387356434fbfcb332390bf7c98934445aa5b011d06efc3a2337777e1f01000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a34b05a95f131afb1b459d29a975a9c7c9b3ffd65a334958e4427697fb16c2ae0220233c50db9fd05eb9abce00225af2c5b33ffb595b88d3aa347b1198c4f46cd255014830450221008b4943e473ae4457124b7bf05ff4b12a4a2eddee33689a841464b40ec2e6018802202c5515d12df8f06c71ff868dd0bd9ad172deef69101debb3b8c77bb30042ccf4010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3044022011d3237aa0e2d885b5e59196adad4d217a30ffeebb59fdf0213e29d3f8c3b9ad02206048b2c00e481e9f6d23f094ba991a387babe0302c639b872e986badcc042845
    output htlc_success_tx 1: 02000000000101e7ba31f387356434fbfcb332390bf7c98934445aa5b011d06efc3a2337777e1f02000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022018115b421de0a76eba67a932bbe6004f031cf3019330d13fa57bea4c2478bb81022000d6bbbc1e2aee760ff0d3e4b94a194b1a1f7f8f8681357ff1ee655bde2dc27a01473044022011d3237aa0e2d885b5e59196adad4d217a30ffeebb59fdf0213e29d3f8c3b9ad02206048b2c00e481e9f6d23f094ba991a387babe0302c639b872e986badcc042845012001010101010101010101010101010101010101010101010101010101010101016e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3044022035a12e30fa72206d12ba8d576fa6c5d7573af8bf465b53be0816aeb0350a0c120220288c3cedbdf16100f55bc00e67c67c28525cbd1b1f9fdd9c12fc83dcebf6642f
    output htlc_timeout_tx 3: 02000000000101e7ba31f387356434fbfcb332390bf7c98934445aa5b011d06efc3a2337777e1f03000000000000000001b80b0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221009f8aa1b587474f4b4af7dd9795287aa038e3b064d0d781acd047b14d6708756b022044e6ce746548a99f01f1beb0fc09e996dd9e893895fd184477d79d44ba087a2b01473044022035a12e30fa72206d12ba8d576fa6c5d7573af8bf465b53be0816aeb0350a0c120220288c3cedbdf16100f55bc00e67c67c28525cbd1b1f9fdd9c12fc83dcebf6642f010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100e9e55274fdbbe7d096f568eaadb005e790fcfc3612f581c706f95cd3ec6008fd0220539348f7618b50317765c99358027cb1dbd27c9354159d3c918bd58aa43c573b
    output htlc_success_tx 4: 02000000000101e7ba31f387356434fbfcb332390bf7c98934445aa5b011d06efc3a2337777e1f04000000000000000001a00f0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d41900c2f5539f97c8dde8b3d26906e94cc9f84ee8f4fba408b49d88713df6320220296f4886681f2bb8fd120bcb8b8bc50a7e0c90b4d5b62ab953ff8eb2c68ecbdc01483045022100e9e55274fdbbe7d096f568eaadb005e790fcfc3612f581c706f95cd3ec6008fd0220539348f7618b50317765c99358027cb1dbd27c9354159d3c918bd58aa43c573b012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 7 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 676
    # base commitment transaction fee = 1070
    # HTLC 2 offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC 3 offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC 0 received amount 1000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac68
    # HTLC 1 received amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6986930 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100f46729e7a3126cf03d94691f814405b26cf896ecd6617d565aba6915c68de3a202204ca52c50b0c6fe424671b9986907f6180d8c65b289347fa02aac3c69065c6b97
    # local_signature = 30450221009fb6cb38db01817f77a5f973729948b8af0b3a6dad3429e2bd7a88b7b3d1de8b022025e1cd9f23dfe3f87e39e8c14fd054771758287e35aa1b4499de99427844abf2
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8007e8030000000000002200207eaf624c3ab8f5cad0589f46db3fed940bf79a88fb5ab7fa3a6e1d071b5845bfd00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78d007000000000000220020edcdff3e4bb6b538c0ee9639f56dfc4f222e5077bface165abc48764160da0c2b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110b29c6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004830450221009fb6cb38db01817f77a5f973729948b8af0b3a6dad3429e2bd7a88b7b3d1de8b022025e1cd9f23dfe3f87e39e8c14fd054771758287e35aa1b4499de99427844abf201483045022100f46729e7a3126cf03d94691f814405b26cf896ecd6617d565aba6915c68de3a202204ca52c50b0c6fe424671b9986907f6180d8c65b289347fa02aac3c69065c6b9701475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 3044022056bebc4022fd5fbf2476ca55a855f062850ffc8ea1f9bb35cd39b7bdc64ac573022009e29305705e4807b6caaa3f574292b62933474ca469a6b0b0ed9c2d33c8e1a3
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 304402201355346d12f88fcee4e79e093e89527339ea1e560c0c2ea3d1279ef5f3aced4a022039b3e9856d2250b3a7e151ab960c2c5b9e7dfced40da41fb80177e4738767422
    # signature for output 2 (htlc 1)
    remote_htlc_signature = 3045022100cd05e73a45c0eb3fcaf35728c27cba2ebc9e6b490615a94d0108238559794aab0220242975b8644e94691f4a8840bec81c27faca10e221440af1922f8b041fea107a
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 3045022100d72170b2c83f7077da0f420f38a6261eaf672b220fb148b1e7a50006614c196002200be39c59743a1752dea8f77fc1a664bd4c0eee7f721ba4d532e97421552a52f4
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 3045022100da8218fc0d6d01dd14ac50a4f3eed4a6ace56268f617511694382a3abc5fd91202206d51f9530723ee3a5cbbc5d85f11fd91008384fab48dbf05caff666e99513744
    # local_signature = 3045022100b5ec2a995317b3dfa98377240f1b06e86e03d04131543306173cb34fc640a2b50220797a3ef9d1c4b7fda79263c310df5a291d2c10beb540d83aea2325f2581e0dc2
    output htlc_success_tx 0: 020000000001017644b6a9fb53bbc752147b6bb88b1a90ab5bfca44d7a87b8f993f83446b418b30000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022056bebc4022fd5fbf2476ca55a855f062850ffc8ea1f9bb35cd39b7bdc64ac573022009e29305705e4807b6caaa3f574292b62933474ca469a6b0b0ed9c2d33c8e1a301483045022100b5ec2a995317b3dfa98377240f1b06e86e03d04131543306173cb34fc640a2b50220797a3ef9d1c4b7fda79263c310df5a291d2c10beb540d83aea2325f2581e0dc2012000000000000000000000000000000000000000000000000000000000000000006e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac6800000000
    # local_signature = 3044022056f350b2a0c004b5a7ef94258962788cea6eee47642dfda0863db0efda8d5dfb02203e542f1cbf95961953c3bee001e77f959460f81b3687451d75e7430e97bcdc1d
    output htlc_timeout_tx 2: 020000000001017644b6a9fb53bbc752147b6bb88b1a90ab5bfca44d7a87b8f993f83446b418b30100000000000000000123060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402201355346d12f88fcee4e79e093e89527339ea1e560c0c2ea3d1279ef5f3aced4a022039b3e9856d2250b3a7e151ab960c2c5b9e7dfced40da41fb80177e473876742201473044022056f350b2a0c004b5a7ef94258962788cea6eee47642dfda0863db0efda8d5dfb02203e542f1cbf95961953c3bee001e77f959460f81b3687451d75e7430e97bcdc1d010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3045022100e64eee114e87eb70756de34a4ca4ef1cfa1d84b67144761b4136d72514bc40f9022014e895f8039db06a0654fe2bd66f8be721537cc6ddae52d4d65a53e2012fd3eb
    output htlc_success_tx 1: 020000000001017644b6a9fb53bbc752147b6bb88b1a90ab5bfca44d7a87b8f993f83446b418b3020000000000000000010a060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100cd05e73a45c0eb3fcaf35728c27cba2ebc9e6b490615a94d0108238559794aab0220242975b8644e94691f4a8840bec81c27faca10e221440af1922f8b041fea107a01483045022100e64eee114e87eb70756de34a4ca4ef1cfa1d84b67144761b4136d72514bc40f9022014e895f8039db06a0654fe2bd66f8be721537cc6ddae52d4d65a53e2012fd3eb012001010101010101010101010101010101010101010101010101010101010101016e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 304402206e361b4d177ede694046c294fd1d6d408228fd25f55c2b5f00ba4ef3690292bd022028306fb9fb21013eaa6d04083e2946ae6ea6c7038ad8e920adb358f36488241d
    output htlc_timeout_tx 3: 020000000001017644b6a9fb53bbc752147b6bb88b1a90ab5bfca44d7a87b8f993f83446b418b3030000000000000000010b0a0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d72170b2c83f7077da0f420f38a6261eaf672b220fb148b1e7a50006614c196002200be39c59743a1752dea8f77fc1a664bd4c0eee7f721ba4d532e97421552a52f40147304402206e361b4d177ede694046c294fd1d6d408228fd25f55c2b5f00ba4ef3690292bd022028306fb9fb21013eaa6d04083e2946ae6ea6c7038ad8e920adb358f36488241d010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100ea1f5e5c1a0f0b4387cd6e0be9f6f4dc73aa225154a89359a76dfe886badbb5d02205b035bc9730928871dd77c35619a672d44183a55020c4bf24b6bf8fc32c68d8c
    output htlc_success_tx 4: 020000000001017644b6a9fb53bbc752147b6bb88b1a90ab5bfca44d7a87b8f993f83446b418b304000000000000000001da0d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100da8218fc0d6d01dd14ac50a4f3eed4a6ace56268f617511694382a3abc5fd91202206d51f9530723ee3a5cbbc5d85f11fd91008384fab48dbf05caff666e9951374401483045022100ea1f5e5c1a0f0b4387cd6e0be9f6f4dc73aa225154a89359a76dfe886badbb5d02205b035bc9730928871dd77c35619a672d44183a55020c4bf24b6bf8fc32c68d8c012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 677
    # base commitment transaction fee = 955
    # HTLC 2 offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC 3 offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC 1 received amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6987045 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022025a153b4c6310fa5f1825a077625054f993e07540149ef76f39d41fdbfa3432402202ff44666e56a9cfc3dbca68d26d2174f09a7aad9f2ca0741f3e7373686ff7c9d
    # local_signature = 30450221008acdee277c284cacc3c0b64b0724d459bcae09e3390cd36767f6a65bb265ccfe0220608b5459263c4a80fa30ca3901c08642df793d3048bf985df7da66d6dbb5d4b9
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78d007000000000000220020edcdff3e4bb6b538c0ee9639f56dfc4f222e5077bface165abc48764160da0c2b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110259d6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004830450221008acdee277c284cacc3c0b64b0724d459bcae09e3390cd36767f6a65bb265ccfe0220608b5459263c4a80fa30ca3901c08642df793d3048bf985df7da66d6dbb5d4b901473044022025a153b4c6310fa5f1825a077625054f993e07540149ef76f39d41fdbfa3432402202ff44666e56a9cfc3dbca68d26d2174f09a7aad9f2ca0741f3e7373686ff7c9d01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 304402200b99af3616ff5bf54e09bc09d2c5ebf9f2b37665af54bf4458a4adf4154b60ad022047680a6c88e0360b578567937262a9f8a865df62e138ad7668f0bfef004f1681
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 304502210092b842a1d8cd997498efb58153d059f47388f928656adaa9e321ed5a8a2aef8602203cf1e01c6d20925f8082b5e993b9992fb24ed1ec07c14e7725b4b22a3262f57a
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 304402207490b35056190b32ed34528ffec3a5753466c369b4657bc212daf030d7b9ffcb022023f0628ff934b97faebc3c6d2c65da2d3c9b58a2264fd45cc794dc68b66bb0b4
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 3045022100bb73d81662e1dd73083c8302695d8364ebb136cffb1c079268ffb41bae0e14a8022048996892352789e47f9459cb3cbd80ad6b9b75ee2c2188b21925c2938cdc0c90
    # local_signature = 3045022100a4f249efd68e88a54e037ac4caa6b595dd54da07fa1495ffe489847ae13d7f380220488231fb716770c32310496dd763c18ec4350bcc255aba6227858310e1739e7f
    output htlc_timeout_tx 2: 0200000000010134b61a3d1d1d3cd46c7629aa6ca01bd424b88efd417a9e8ec5ab53ba850fabea0000000000000000000123060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402200b99af3616ff5bf54e09bc09d2c5ebf9f2b37665af54bf4458a4adf4154b60ad022047680a6c88e0360b578567937262a9f8a865df62e138ad7668f0bfef004f168101483045022100a4f249efd68e88a54e037ac4caa6b595dd54da07fa1495ffe489847ae13d7f380220488231fb716770c32310496dd763c18ec4350bcc255aba6227858310e1739e7f010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 30440220123df40dd4eb163f79ebef3f65ab3fead75602714c6b14ae3deb4e1b8580fbb202200fe4305c2d51880a5019788b1f17ee4db48ba061351727c6f30487a1ff880939
    output htlc_success_tx 1: 0200000000010134b61a3d1d1d3cd46c7629aa6ca01bd424b88efd417a9e8ec5ab53ba850fabea0100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050048304502210092b842a1d8cd997498efb58153d059f47388f928656adaa9e321ed5a8a2aef8602203cf1e01c6d20925f8082b5e993b9992fb24ed1ec07c14e7725b4b22a3262f57a014730440220123df40dd4eb163f79ebef3f65ab3fead75602714c6b14ae3deb4e1b8580fbb202200fe4305c2d51880a5019788b1f17ee4db48ba061351727c6f30487a1ff880939012001010101010101010101010101010101010101010101010101010101010101016e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3045022100f49d6833dbc36beb93a55fcd985111f9e0fa5bf8218658444c618f45fb74c167022073deecf585665a25178658833fb75577264ecfa392412e4548bbade9fbf1cc67
    output htlc_timeout_tx 3: 0200000000010134b61a3d1d1d3cd46c7629aa6ca01bd424b88efd417a9e8ec5ab53ba850fabea020000000000000000010b0a0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402207490b35056190b32ed34528ffec3a5753466c369b4657bc212daf030d7b9ffcb022023f0628ff934b97faebc3c6d2c65da2d3c9b58a2264fd45cc794dc68b66bb0b401483045022100f49d6833dbc36beb93a55fcd985111f9e0fa5bf8218658444c618f45fb74c167022073deecf585665a25178658833fb75577264ecfa392412e4548bbade9fbf1cc67010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 304402201189fdb64c5fd545dccdf8411ce8bae8a60ea0a5470fb0874a3770b9ba26ac0e0220759e339a19feb419f869962e2d3f8911aeac8408b16959252a725605eb39744a
    output htlc_success_tx 4: 0200000000010134b61a3d1d1d3cd46c7629aa6ca01bd424b88efd417a9e8ec5ab53ba850fabea03000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100bb73d81662e1dd73083c8302695d8364ebb136cffb1c079268ffb41bae0e14a8022048996892352789e47f9459cb3cbd80ad6b9b75ee2c2188b21925c2938cdc0c900147304402201189fdb64c5fd545dccdf8411ce8bae8a60ea0a5470fb0874a3770b9ba26ac0e0220759e339a19feb419f869962e2d3f8911aeac8408b16959252a725605eb39744a012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2161
    # base commitment transaction fee = 3051
    # HTLC 2 offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC 3 offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC 1 received amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6984949 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100a9976e89763982487b7ff07a26347d398b9f19c0fb01046c8a787d7cd6068f440220224138e065ed31f248fd2756d3e209c0cab69ea5e1ede66d019e18072267284f
    # local_signature = 3045022100b42a3229202c8c5ddbff95efa6aa2d48c39b57d437ad4a8b2a917d11a3ca55ff02205bb9c65d06656222ced3bfd804145f658d1fa11804b20ef44962a9ea547bd6b7
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78d007000000000000220020edcdff3e4bb6b538c0ee9639f56dfc4f222e5077bface165abc48764160da0c2b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110f5946a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100b42a3229202c8c5ddbff95efa6aa2d48c39b57d437ad4a8b2a917d11a3ca55ff02205bb9c65d06656222ced3bfd804145f658d1fa11804b20ef44962a9ea547bd6b701483045022100a9976e89763982487b7ff07a26347d398b9f19c0fb01046c8a787d7cd6068f440220224138e065ed31f248fd2756d3e209c0cab69ea5e1ede66d019e18072267284f01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 3045022100f3e6e01988f50a0eb0ea811af3b3b716293a353ae8e3d47e2b87abd2c98c6a12022025b4d26a915b2854d81f377def7cbbbc7249aad11570c304687a1ec546c8f6e4
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 3044022044e4357623253d491447e2174093b4fae67b9c65e166ccf783ad8c66556424e002206bc129d62fc6536262973cf9363622af4142af8cedaff41543fd54565e4d1767
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 3045022100f81e573131abf61f9ffc0901777caf674f9426dc5abe257f1df5c20a078421f902207c2fa5afa0b74d2916aa6651a51305287ef23ca1ad82c1a26e73fac2c9ca8f72
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 3045022100bae10b27ee2b973f9125cc6477caaa0d9391a68ac494a269b9751d12a6fa2a2f02206d1bb6b5bc3d274c35b3de9a757b26b15a518ae37b3e638ea757e0bd92c2fede
    # local_signature = 3045022100dd0da1cc28939c4557cca12ea7dc79e2c2b6062b30dc5783176a9d47a13b55e30220117f8707fe2f1a9906c1266bd304fb9470ef8ca7a22b7dde87ec17ae6bb65807
    output htlc_timeout_tx 2: 02000000000101f5d95dc4771c3e5529cb497b33d38ef187851266ab5e4f387208009bf4b9ede70000000000000000000174020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f3e6e01988f50a0eb0ea811af3b3b716293a353ae8e3d47e2b87abd2c98c6a12022025b4d26a915b2854d81f377def7cbbbc7249aad11570c304687a1ec546c8f6e401483045022100dd0da1cc28939c4557cca12ea7dc79e2c2b6062b30dc5783176a9d47a13b55e30220117f8707fe2f1a9906c1266bd304fb9470ef8ca7a22b7dde87ec17ae6bb65807010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3045022100ab4059b7672cb8c55153574b9e467cae0e0f3bccf29bd5d1ef68565a91c68804022023a6c4018bade67d8def5218eb61b5ad2572a30277903ffd09e677f117313c6d
    output htlc_success_tx 1: 02000000000101f5d95dc4771c3e5529cb497b33d38ef187851266ab5e4f387208009bf4b9ede70100000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022044e4357623253d491447e2174093b4fae67b9c65e166ccf783ad8c66556424e002206bc129d62fc6536262973cf9363622af4142af8cedaff41543fd54565e4d176701483045022100ab4059b7672cb8c55153574b9e467cae0e0f3bccf29bd5d1ef68565a91c68804022023a6c4018bade67d8def5218eb61b5ad2572a30277903ffd09e677f117313c6d012001010101010101010101010101010101010101010101010101010101010101016e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3045022100f556f34674d72aa5ce638b549f70a9129bc9dd0ab58ebf966c759b334d1915660220108e20d1a66821ffe24505c4709521981e52f090f269a0e1de4a96e0aacc19f9
    output htlc_timeout_tx 3: 02000000000101f5d95dc4771c3e5529cb497b33d38ef187851266ab5e4f387208009bf4b9ede7020000000000000000015c060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f81e573131abf61f9ffc0901777caf674f9426dc5abe257f1df5c20a078421f902207c2fa5afa0b74d2916aa6651a51305287ef23ca1ad82c1a26e73fac2c9ca8f7201483045022100f556f34674d72aa5ce638b549f70a9129bc9dd0ab58ebf966c759b334d1915660220108e20d1a66821ffe24505c4709521981e52f090f269a0e1de4a96e0aacc19f9010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3044022006292dcb6d8e574d70bc40965efb6f618bb30b7a0efef53b460cdbd52ed164f802201a979d4ca50257731bdeda47a2a519f480ea62b0c2650835c4c16cab0f444c02
    output htlc_success_tx 4: 02000000000101f5d95dc4771c3e5529cb497b33d38ef187851266ab5e4f387208009bf4b9ede703000000000000000001f2090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100bae10b27ee2b973f9125cc6477caaa0d9391a68ac494a269b9751d12a6fa2a2f02206d1bb6b5bc3d274c35b3de9a757b26b15a518ae37b3e638ea757e0bd92c2fede01473044022006292dcb6d8e574d70bc40965efb6f618bb30b7a0efef53b460cdbd52ed164f802201a979d4ca50257731bdeda47a2a519f480ea62b0c2650835c4c16cab0f444c02012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2162
    # base commitment transaction fee = 2680
    # HTLC 2 offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC 3 offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985320 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100e7b45245c3b6079d0606000d1e340f6957621ab09fa8feb28ec69272851ed9650220299ecd0833d086d97a094b0e1b82be2b878fbd03b15616ee06e40ca8b909d84c
    # local_signature = 3045022100bfcdea8720cb25031a4ffa9f44195b2b66922183af9fcf040281b60ebcaa1dac0220636987b0fbacd90ea9ba6262d675f97d77aeaf8808ed0aaeecca20991b19c7d5
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311068966a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100bfcdea8720cb25031a4ffa9f44195b2b66922183af9fcf040281b60ebcaa1dac0220636987b0fbacd90ea9ba6262d675f97d77aeaf8808ed0aaeecca20991b19c7d501483045022100e7b45245c3b6079d0606000d1e340f6957621ab09fa8feb28ec69272851ed9650220299ecd0833d086d97a094b0e1b82be2b878fbd03b15616ee06e40ca8b909d84c01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 3045022100a04f5b2f9d29610afd8381096f6ccf78f649f875224b505741b730b32eb5836402207054c0e91ef09fb9c1fe06d6449d9383551d94463600395924b92dc758352e78
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 3045022100916b4d9e90b4fb8744b1459c9d37f1e724c5bd64caef2e1a3ae7f5610057fca1022072e980b5ba830f3b7b9cc6f0fae9c28ed31093e6409f15e7253a68c0617f0d16
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 30440220389760f23945771d62e56a7359c86421f041ef48266afc5b4e2289cd3ade4caa022051fa511b1823af90711b2d52ffdfe8199242016f2c7f4d97c9e0f7c033a6f291
    # local_signature = 3045022100f3ac249aadab618ed1348e7f97dcda549259f6fafd077b5567c3a651118f387f02202dfe392548f29f97f9bc2dc07e849bdd79f994c4ac4198995249428761df9c5c
    output htlc_timeout_tx 2: 0200000000010129d38824741464418e2c9d0090584d909fb13c996845369706e4b969999e156d0000000000000000000174020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a04f5b2f9d29610afd8381096f6ccf78f649f875224b505741b730b32eb5836402207054c0e91ef09fb9c1fe06d6449d9383551d94463600395924b92dc758352e7801483045022100f3ac249aadab618ed1348e7f97dcda549259f6fafd077b5567c3a651118f387f02202dfe392548f29f97f9bc2dc07e849bdd79f994c4ac4198995249428761df9c5c010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3045022100f158da7f08390b84376e7ca8df04e147b999800dd71b3ef6410efb8dbfe0ed6702207154e65eaaf5369d9ae04321cd41c64cbc9c376dca81229b808c7e922a413f03
    output htlc_timeout_tx 3: 0200000000010129d38824741464418e2c9d0090584d909fb13c996845369706e4b969999e156d010000000000000000015c060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100916b4d9e90b4fb8744b1459c9d37f1e724c5bd64caef2e1a3ae7f5610057fca1022072e980b5ba830f3b7b9cc6f0fae9c28ed31093e6409f15e7253a68c0617f0d1601483045022100f158da7f08390b84376e7ca8df04e147b999800dd71b3ef6410efb8dbfe0ed6702207154e65eaaf5369d9ae04321cd41c64cbc9c376dca81229b808c7e922a413f03010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100f252e2b953f7150bed0650740dee62a6b54a5dd443667907fbc8250bc05a65ac02206589d94bc9468a89925dc11ad393c56c39222a5210860925fb9cc08dc86bd374
    output htlc_success_tx 4: 0200000000010129d38824741464418e2c9d0090584d909fb13c996845369706e4b969999e156d02000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220389760f23945771d62e56a7359c86421f041ef48266afc5b4e2289cd3ade4caa022051fa511b1823af90711b2d52ffdfe8199242016f2c7f4d97c9e0f7c033a6f29101483045022100f252e2b953f7150bed0650740dee62a6b54a5dd443667907fbc8250bc05a65ac02206589d94bc9468a89925dc11ad393c56c39222a5210860925fb9cc08dc86bd374012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2291
    # base commitment transaction fee = 2840
    # HTLC 2 offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC 3 offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985160 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 30440220204316f3553a265922a99c207addeae456349e0aca229d809a526193d5ebd03002206bb618812f43efff52bbf48ca4cbb92529ef0bd6dcfaae4235ff8aebde1b121f
    # local_signature = 3045022100b9174ba09413297731a39e245d1b7fda4cb363c333b58dd6f7f780b9ec2497f102205da2fca746fa0b4516f5e0d4d9cb8ecdf5cf241b44dd33c4b24e8313e844df72
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110c8956a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100b9174ba09413297731a39e245d1b7fda4cb363c333b58dd6f7f780b9ec2497f102205da2fca746fa0b4516f5e0d4d9cb8ecdf5cf241b44dd33c4b24e8313e844df72014730440220204316f3553a265922a99c207addeae456349e0aca229d809a526193d5ebd03002206bb618812f43efff52bbf48ca4cbb92529ef0bd6dcfaae4235ff8aebde1b121f01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 3045022100e703e0c17a734382ac58ef10aed5cdbaf0383b4c5b0437ca03bb3a0b7b17089902201d8e60fa3bfd73657d1be755952e8d65d5bae0fe577907acbd115080e0ef0a06
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 3044022048f3fdb4f73979aa094ebf21381bc2bce380efc01c1f273276b42e9d45b9ea5802203399f857b4a405bfac204cf20ce112f64aaf183254e1d277a5fab23f5de0ef92
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 3045022100da1da796de2d7a36a78095c91506bb2681c2f84040ddf60c44b18fff8c643eb00220307fd2bdf460f1448ee6bef270303976cbfd22e8bd179e2576e63f3e90c181be
    # local_signature = 30450221009422776299ddfc9a0d3eb16aefb9b6a575cfa3798726fd35eec2f6d03a3a019a022017a8641446f9d7380c98c3b2fe2717a5e86b46321bc5d9858ead0229e2fbd3f2
    output htlc_timeout_tx 2: 0200000000010186bfaebdd8e7b7d864bcce7797f09ef8eff68ad8a99bdcc4f02f7a15b04555420000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e703e0c17a734382ac58ef10aed5cdbaf0383b4c5b0437ca03bb3a0b7b17089902201d8e60fa3bfd73657d1be755952e8d65d5bae0fe577907acbd115080e0ef0a06014830450221009422776299ddfc9a0d3eb16aefb9b6a575cfa3798726fd35eec2f6d03a3a019a022017a8641446f9d7380c98c3b2fe2717a5e86b46321bc5d9858ead0229e2fbd3f2010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 304402204b9a0da0a36d6709040c4c1cdb77baa740333ad5e03386f0054e70eb61acf851022000977f3b17d37f4d8497ac59ec173d5db1b01949a0a3bd2ac49d25c7420844e8
    output htlc_timeout_tx 3: 0200000000010186bfaebdd8e7b7d864bcce7797f09ef8eff68ad8a99bdcc4f02f7a15b0455542010000000000000000010a060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022048f3fdb4f73979aa094ebf21381bc2bce380efc01c1f273276b42e9d45b9ea5802203399f857b4a405bfac204cf20ce112f64aaf183254e1d277a5fab23f5de0ef920147304402204b9a0da0a36d6709040c4c1cdb77baa740333ad5e03386f0054e70eb61acf851022000977f3b17d37f4d8497ac59ec173d5db1b01949a0a3bd2ac49d25c7420844e8010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100de51aa4c8cfd02b2dc218dc2e59e4b44bc44f26d4dd207eb8dea4b96ae1a35ea022069cd4117c233bd19f9a63d549e1d22ce5f854b5d13b7a5de65550addf379565f
    output htlc_success_tx 4: 0200000000010186bfaebdd8e7b7d864bcce7797f09ef8eff68ad8a99bdcc4f02f7a15b0455542020000000000000000019b090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100da1da796de2d7a36a78095c91506bb2681c2f84040ddf60c44b18fff8c643eb00220307fd2bdf460f1448ee6bef270303976cbfd22e8bd179e2576e63f3e90c181be01483045022100de51aa4c8cfd02b2dc218dc2e59e4b44bc44f26d4dd207eb8dea4b96ae1a35ea022069cd4117c233bd19f9a63d549e1d22ce5f854b5d13b7a5de65550addf379565f012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2292
    # base commitment transaction fee = 2447
    # HTLC 3 offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985553 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 304502210085ef217e4ee408810c1be4994bb671b2c4868c37169a3d853f8f122bdfb87be9022003188677686ebf025849b67ad49babff11325b5255fe9b608fbfac16722e47a4
    # local_signature = 3045022100e0b270640f8fd88e51f75c5142443b943e6a349671fa7eae0325bdaff86a87c40220009796bfc452cb6c49a3286defea2ac8efaf4721bcc643eb92a7e93bb9c5b4d3
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311051976a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100e0b270640f8fd88e51f75c5142443b943e6a349671fa7eae0325bdaff86a87c40220009796bfc452cb6c49a3286defea2ac8efaf4721bcc643eb92a7e93bb9c5b4d30148304502210085ef217e4ee408810c1be4994bb671b2c4868c37169a3d853f8f122bdfb87be9022003188677686ebf025849b67ad49babff11325b5255fe9b608fbfac16722e47a401475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3045022100cf2c946eef75296dd18956639914b7709e59f62f00f08735f8745af591449f6f02205bd75f75967b83deb31986488bb5f7073cce9857591fe6c18feba2bf0cfa1e7c
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 30440220107e3d519087ba5a2244ea685b2921e5c8d1645cb03a7996ec2a043eeb24a0d102207a78d35e72a077dc11ac6adad1e0a1f0ffd25ce6d55ee8302c5e094a2280883d
    # local_signature = 304402204c3dd73943f0633888a14602e8ceb1f4f134688a7bdadb540c16a463ca3d5b4d022048a619753ecf56e4c709d625dbe2eba9f87069a0fd172ddd8382e2c0d5e13a51
    output htlc_timeout_tx 3: 02000000000101a585726f1d0fae46f9b04685641fbf9db0193c342efb3c78b2bb82f8e49bab960000000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100cf2c946eef75296dd18956639914b7709e59f62f00f08735f8745af591449f6f02205bd75f75967b83deb31986488bb5f7073cce9857591fe6c18feba2bf0cfa1e7c0147304402204c3dd73943f0633888a14602e8ceb1f4f134688a7bdadb540c16a463ca3d5b4d022048a619753ecf56e4c709d625dbe2eba9f87069a0fd172ddd8382e2c0d5e13a51010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100dd9079a96e09d38bc08c5a3ccf478edd1d87bdc35ad0538f962a8ab970541b0d02207e10942952071edca58206f64c8cefff385e941c449d6ef7949026cdf66fdd35
    output htlc_success_tx 4: 02000000000101a585726f1d0fae46f9b04685641fbf9db0193c342efb3c78b2bb82f8e49bab96010000000000000000019a090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220107e3d519087ba5a2244ea685b2921e5c8d1645cb03a7996ec2a043eeb24a0d102207a78d35e72a077dc11ac6adad1e0a1f0ffd25ce6d55ee8302c5e094a2280883d01483045022100dd9079a96e09d38bc08c5a3ccf478edd1d87bdc35ad0538f962a8ab970541b0d02207e10942952071edca58206f64c8cefff385e941c449d6ef7949026cdf66fdd35012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3866
    # base commitment transaction fee = 4128
    # HTLC 3 offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6983872 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100efb46b8a0ab766a7c81de0deb00985eed8a9928d055485ef12bd554cf8afa84e02207dfcff213f6e6c5ef4c369a0aaafadfcc9fad3a21a7888919cfeee114755d03d
    # local_signature = 304502210080b66478598786deb4bdb9d49574012b0a8c988d5d784f14a42e9329569ae52802207276e265d0c3a86d97cfe97d6491a51c3c2013ff762fb1caced12d5b31f0029a
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110c0906a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040048304502210080b66478598786deb4bdb9d49574012b0a8c988d5d784f14a42e9329569ae52802207276e265d0c3a86d97cfe97d6491a51c3c2013ff762fb1caced12d5b31f0029a01483045022100efb46b8a0ab766a7c81de0deb00985eed8a9928d055485ef12bd554cf8afa84e02207dfcff213f6e6c5ef4c369a0aaafadfcc9fad3a21a7888919cfeee114755d03d01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3045022100a67d0fb628a0100c6b05f1ed7558d6e0844b5e6d281b920978c343c1271d893d0220629c6ebb8458fd8a1f15c803c17a74b2a6d9e736d1fbe8a469d67e9ca82aac9c
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 3044022001efdca09d42146f8e6226adbb27c549b61bedc2ebed1add558f24b9ffbea59a022006655453e8889f4d3389fa6a82f2982397c291cbb2fd4407ebcdcd35282ddf9c
    # local_signature = 3045022100f4eeae7293e3f53040fdb7ef790b02394933460afd89ba41a2f16dcc4318ac4d022078b0f801a58667c98b20db8abc9a9156ad960b891060564bbe58a3968a64b899
    output htlc_timeout_tx 3: 0200000000010148439aa5723b46460760747bd9fece11423a1e864e82e040d7203c558adc0b600000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a67d0fb628a0100c6b05f1ed7558d6e0844b5e6d281b920978c343c1271d893d0220629c6ebb8458fd8a1f15c803c17a74b2a6d9e736d1fbe8a469d67e9ca82aac9c01483045022100f4eeae7293e3f53040fdb7ef790b02394933460afd89ba41a2f16dcc4318ac4d022078b0f801a58667c98b20db8abc9a9156ad960b891060564bbe58a3968a64b899010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 304402205343a840479e665e9453af5461dc093e9d9fee203ccf31dc5fbe21ec02da398e022009051bc6717b04351df8159e0b06d2c2e6cb7bb3c2d4318b5b5e571f70abdc0f
    output htlc_success_tx 4: 0200000000010148439aa5723b46460760747bd9fece11423a1e864e82e040d7203c558adc0b600100000000000000000177050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022001efdca09d42146f8e6226adbb27c549b61bedc2ebed1add558f24b9ffbea59a022006655453e8889f4d3389fa6a82f2982397c291cbb2fd4407ebcdcd35282ddf9c0147304402205343a840479e665e9453af5461dc093e9d9fee203ccf31dc5fbe21ec02da398e022009051bc6717b04351df8159e0b06d2c2e6cb7bb3c2d4318b5b5e571f70abdc0f012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3867
    # base commitment transaction fee = 3464
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6984536 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022045b6ce3604bbd13d2bf83d003f721dd726bfb8357e5a68b6f8a49db5a86faf48022070b95df3fadd1244c53cca7a62d1e128085d5138bd9b70be61662c09d4a60853
    # local_signature = 304402201923a8d7909f2c8708863ba70b2ba5c20939abffd603cf937c54129e5c6b28b2022018ca56507178141663fe1fac2a55d9e9b4278b8324a5f880464d3e6edbc44a1b
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311058936a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402201923a8d7909f2c8708863ba70b2ba5c20939abffd603cf937c54129e5c6b28b2022018ca56507178141663fe1fac2a55d9e9b4278b8324a5f880464d3e6edbc44a1b01473044022045b6ce3604bbd13d2bf83d003f721dd726bfb8357e5a68b6f8a49db5a86faf48022070b95df3fadd1244c53cca7a62d1e128085d5138bd9b70be61662c09d4a6085301475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 3045022100e5591d515991ee3e6d48033e470a032cdb29450005f08586eadcd0ec297ae9f702207c8c13f5f2159382a3af0c160d58c39982718bcac5eea7b3cb77698b2b5816ad
    # local_signature = 3044022053248ffdd9dde75e1c2af20b7d7359de98b7896df019aa232f99770fef087ef2022060cc04fe2726d86e178efc3618d6d79750d081bc315c8b7bbfb5292ca6c99c73
    output htlc_success_tx 4: 02000000000101e1a9f9f4ba9519f8845cfbcac71ec3fc5144778ed23c3ba85b40eb09bd2687740000000000000000000176050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e5591d515991ee3e6d48033e470a032cdb29450005f08586eadcd0ec297ae9f702207c8c13f5f2159382a3af0c160d58c39982718bcac5eea7b3cb77698b2b5816ad01473044022053248ffdd9dde75e1c2af20b7d7359de98b7896df019aa232f99770fef087ef2022060cc04fe2726d86e178efc3618d6d79750d081bc315c8b7bbfb5292ca6c99c73012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5133
    # base commitment transaction fee = 4599
    # HTLC 4 received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6983401 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100f7164661832d55b28789b7b63690bee01b43bde46fd713ca7e8747258b00d7410220602329a65ab366e99ec2c68b91acf7162fff7d61298e78472d1544d7dd2204a8
    # local_signature = 3045022100b413ebb50e942ae53fea93578a0122603b79af5b1daac71a35e52cc176e8247d022066eca652a57ec48eab57ebfe719dcf17aad8e0e746f4b0fb10bad866693e2014
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110e98e6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100b413ebb50e942ae53fea93578a0122603b79af5b1daac71a35e52cc176e8247d022066eca652a57ec48eab57ebfe719dcf17aad8e0e746f4b0fb10bad866693e201401483045022100f7164661832d55b28789b7b63690bee01b43bde46fd713ca7e8747258b00d7410220602329a65ab366e99ec2c68b91acf7162fff7d61298e78472d1544d7dd2204a801475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 3045022100e7bd4ef16506505f4ba310ea26fd73bc11d4944b97e23f5df18c052d6c062ee80220692f4ad7cc206e1f8f8588ed74059042a58a464d8b2ecef92fe41efac25e907c
    # local_signature = 304402205484ad6d8270c4f5ae59869392e1a9ba47fadfa849e01bf116859046e3112a350220244573b2bce282b8381b00af3d40ecc55144482aedf39044f7652b0eb05d84be
    output htlc_success_tx 4: 0200000000010177c0ecdcafa956808c24108cfa273705470aa53829781677f73aafe4ca80b69f0000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e7bd4ef16506505f4ba310ea26fd73bc11d4944b97e23f5df18c052d6c062ee80220692f4ad7cc206e1f8f8588ed74059042a58a464d8b2ecef92fe41efac25e907c0147304402205484ad6d8270c4f5ae59869392e1a9ba47fadfa849e01bf116859046e3112a350220244573b2bce282b8381b00af3d40ecc55144482aedf39044f7652b0eb05d84be012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 2 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5134
    # base commitment transaction fee = 3717
    # to-local amount 6984283 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100c386d933436598ea7c33491ef464300a214cff27a0f7312d99ab3768326d7b8d02204df07a4f71c5dbd697032c50b9819f2519d604219a097dd0fab61377ece322a2
    # local_signature = 3045022100fc35aae81065b76858d692233d20fd3b249fefbacc14eb4caf001a0347cc00670220613311610016742e609e19d1bc1e6b5a1f5ff9dc080f443633afdbc953c119c0
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8002c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de8431105b926a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100fc35aae81065b76858d692233d20fd3b249fefbacc14eb4caf001a0347cc00670220613311610016742e609e19d1bc1e6b5a1f5ff9dc080f443633afdbc953c119c001483045022100c386d933436598ea7c33491ef464300a214cff27a0f7312d99ab3768326d7b8d02204df07a4f71c5dbd697032c50b9819f2519d604219a097dd0fab61377ece322a201475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with 2 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651180
    # base commitment transaction fee = 6987454
    # to-local amount 546 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022037f83ff00c8e5fb18ae1f918ffc24e54581775a20ff1ae719297ef066c71caa9022039c529cccd89ff6c5ed1db799614533844bd6d101da503761c45c713996e3bbd
    # local_signature = 30440220514f977bf7edc442de8ce43ace9686e5ebdc0f893033f13e40fb46c8b8c6e1f90220188006227d175f5c35da0b092c57bea82537aed89f7778204dc5bacf4f29f2b9
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b800222020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80ec0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311004004730440220514f977bf7edc442de8ce43ace9686e5ebdc0f893033f13e40fb46c8b8c6e1f90220188006227d175f5c35da0b092c57bea82537aed89f7778204dc5bacf4f29f2b901473044022037f83ff00c8e5fb18ae1f918ffc24e54581775a20ff1ae719297ef066c71caa9022039c529cccd89ff6c5ed1db799614533844bd6d101da503761c45c713996e3bbd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with 1 output untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651181
    # base commitment transaction fee = 6987455
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022064901950be922e62cbe3f2ab93de2b99f37cff9fc473e73e394b27f88ef0731d02206d1dfa227527b4df44a07599289e207d6fd9cca60c0365682dcd3deaf739567e
    # local_signature = 3044022031a82b51bd014915fe68928d1abf4b9885353fb896cac10c3fdd88d7f9c7f2e00220716bda819641d2c63e65d3549b6120112e1aeaf1742eed94a471488e79e206b1
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8001c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de8431100400473044022031a82b51bd014915fe68928d1abf4b9885353fb896cac10c3fdd88d7f9c7f2e00220716bda819641d2c63e65d3549b6120112e1aeaf1742eed94a471488e79e206b101473044022064901950be922e62cbe3f2ab93de2b99f37cff9fc473e73e394b27f88ef0731d02206d1dfa227527b4df44a07599289e207d6fd9cca60c0365682dcd3deaf739567e01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with fee greater than funder amount
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651936
    # base commitment transaction fee = 6988001
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022064901950be922e62cbe3f2ab93de2b99f37cff9fc473e73e394b27f88ef0731d02206d1dfa227527b4df44a07599289e207d6fd9cca60c0365682dcd3deaf739567e
    # local_signature = 3044022031a82b51bd014915fe68928d1abf4b9885353fb896cac10c3fdd88d7f9c7f2e00220716bda819641d2c63e65d3549b6120112e1aeaf1742eed94a471488e79e206b1
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8001c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de8431100400473044022031a82b51bd014915fe68928d1abf4b9885353fb896cac10c3fdd88d7f9c7f2e00220716bda819641d2c63e65d3549b6120112e1aeaf1742eed94a471488e79e206b101473044022064901950be922e62cbe3f2ab93de2b99f37cff9fc473e73e394b27f88ef0731d02206d1dfa227527b4df44a07599289e207d6fd9cca60c0365682dcd3deaf739567e01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
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

