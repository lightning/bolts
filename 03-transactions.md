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
    # HTLC offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 1000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac68
    # HTLC received amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
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
    local_feerate_per_kw: 678
    # base commitment transaction fee = 1073
    # HTLC offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 1000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac68
    # HTLC received amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6986927 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 30440220729dd4556b452b3222b47f039a6beebbdcd9d04e78c48a3f429ecbc7b98b713a02203301434dc6c6158d4ec00be6b7ab81abae1bc24c564edf4e7afd9273efb9b6f6
    # local_signature = 3045022100a53d0ddf7dbdf86a06cc3e4796f02bccd65a461c0e441be2991b5235f1633b2302205c230034d07ad253a1d99789ba03ae70857f1e6f3190833c0e19fd7a005e5240
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8007e8030000000000002200207eaf624c3ab8f5cad0589f46db3fed940bf79a88fb5ab7fa3a6e1d071b5845bfd00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78d007000000000000220020edcdff3e4bb6b538c0ee9639f56dfc4f222e5077bface165abc48764160da0c2b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110af9c6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100a53d0ddf7dbdf86a06cc3e4796f02bccd65a461c0e441be2991b5235f1633b2302205c230034d07ad253a1d99789ba03ae70857f1e6f3190833c0e19fd7a005e5240014730440220729dd4556b452b3222b47f039a6beebbdcd9d04e78c48a3f429ecbc7b98b713a02203301434dc6c6158d4ec00be6b7ab81abae1bc24c564edf4e7afd9273efb9b6f601475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 3044022021413c112f8a8bb8343e5508acc11748ecc1dcf6a11b51534ce18a4af3ab252702200cda8cfaaaeb9f759ae551d3e67837fa8da6dd6396306ffeb98c3275f3315461
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 3045022100e15b88618207d6f13353f8fae061a712dd49cbf40be68b0246c57fc41389d708022079490aa87d1284f05abeecb9d09cbb1ebe7fb46e2bf047764f7e8280ed79e83d
    # signature for output 2 (htlc 1)
    remote_htlc_signature = 3045022100b4849aa05fa22eb429404e19e58928821f62089b0a27e3ada7f07e9607bd50310220699e7042cf51f7c76e722c898aefc75791ad4ee82ff152c16dfcffdf9f84008d
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 30450221009c264fdcdecf1730008bdd1206c73f08978b3b62162a12228d8ffa2322c9154702204c54dee3ffcc0a3a77d6524779665a078971c9040fdac2fdb80936dd63d11681
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 30450221009039b990b12951fcf180df6107b226d018caa8291f7ba753d22bf2b09b7d7f7b022060e9b05bcf6e2ab0ded7ae7aae179a4eccc7a3a39912da89a2468c292c549b59
    # local_signature = 3045022100c9328a474ca222952a1cd25df57ea65b577cbf824752aed7fde4af1609b83b9202202888d5252a2d5949b288b0002f1019ba13c3c1a8e31ca5eb9ccab649bfebb789
    output htlc_success_tx 0: 020000000001014a13eb73434fa97218577b183a4f2051b307dcee3712318b96eccd98be63c73a0000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022021413c112f8a8bb8343e5508acc11748ecc1dcf6a11b51534ce18a4af3ab252702200cda8cfaaaeb9f759ae551d3e67837fa8da6dd6396306ffeb98c3275f331546101483045022100c9328a474ca222952a1cd25df57ea65b577cbf824752aed7fde4af1609b83b9202202888d5252a2d5949b288b0002f1019ba13c3c1a8e31ca5eb9ccab649bfebb789012000000000000000000000000000000000000000000000000000000000000000006e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac6800000000
    # local_signature = 30440220681a5ead13175c42fdde64ee5bbf84792ea674d015f671702f49394a0458845d02206b30233fcbaabbc8d705990afffaabbc7e980a84b5cc89c8386337151e147a07
    output htlc_timeout_tx 2: 020000000001014a13eb73434fa97218577b183a4f2051b307dcee3712318b96eccd98be63c73a0100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e15b88618207d6f13353f8fae061a712dd49cbf40be68b0246c57fc41389d708022079490aa87d1284f05abeecb9d09cbb1ebe7fb46e2bf047764f7e8280ed79e83d014730440220681a5ead13175c42fdde64ee5bbf84792ea674d015f671702f49394a0458845d02206b30233fcbaabbc8d705990afffaabbc7e980a84b5cc89c8386337151e147a07010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3045022100c9bbc7e587b4d389e560f6018223439f9e96f847c6c4e991b3330b357f680bc402207defb5248a0facee31402f52b6bd98764769e1ecd6d43c61fdbd1101f950d9b8
    output htlc_success_tx 1: 020000000001014a13eb73434fa97218577b183a4f2051b307dcee3712318b96eccd98be63c73a0200000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100b4849aa05fa22eb429404e19e58928821f62089b0a27e3ada7f07e9607bd50310220699e7042cf51f7c76e722c898aefc75791ad4ee82ff152c16dfcffdf9f84008d01483045022100c9bbc7e587b4d389e560f6018223439f9e96f847c6c4e991b3330b357f680bc402207defb5248a0facee31402f52b6bd98764769e1ecd6d43c61fdbd1101f950d9b8012001010101010101010101010101010101010101010101010101010101010101016e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 304402201fa562a84bb0e584119c23b90ed19576c3ba84c8c7634c82f2dc769059119494022023e6b232bce609bd2ad9541f1fed074ec615b5fdb32e8f1d6070a1409749467c
    output htlc_timeout_tx 3: 020000000001014a13eb73434fa97218577b183a4f2051b307dcee3712318b96eccd98be63c73a03000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221009c264fdcdecf1730008bdd1206c73f08978b3b62162a12228d8ffa2322c9154702204c54dee3ffcc0a3a77d6524779665a078971c9040fdac2fdb80936dd63d116810147304402201fa562a84bb0e584119c23b90ed19576c3ba84c8c7634c82f2dc769059119494022023e6b232bce609bd2ad9541f1fed074ec615b5fdb32e8f1d6070a1409749467c010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100a04ab5017ad8d31b9bbede5d2c7365213dc9dec3c13e2cad9e5d5a9105c8ddd60220422dac0092b5523def0bd17f38343ffac7528abe0a3ee840a7302dedbf3e3541
    output htlc_success_tx 4: 020000000001014a13eb73434fa97218577b183a4f2051b307dcee3712318b96eccd98be63c73a04000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221009039b990b12951fcf180df6107b226d018caa8291f7ba753d22bf2b09b7d7f7b022060e9b05bcf6e2ab0ded7ae7aae179a4eccc7a3a39912da89a2468c292c549b5901483045022100a04ab5017ad8d31b9bbede5d2c7365213dc9dec3c13e2cad9e5d5a9105c8ddd60220422dac0092b5523def0bd17f38343ffac7528abe0a3ee840a7302dedbf3e3541012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 679
    # base commitment transaction fee = 958
    # HTLC offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6987042 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100c6941c6b439f5874f1204beb5547a178efd879b532ef4bac767c8e9338fa86f702203a42ba6aee5a88f6abb51da055c7b9d6926e2cb777adaa77737f82aa700f900d
    # local_signature = 304402202d10bc09cb003320b2785a3dde3f376f52cfa10053f7113a8459242ad60555e702207380250de16176a97a257e4cb119273e9919ce913f02ae3514d091468136fe13
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78d007000000000000220020edcdff3e4bb6b538c0ee9639f56dfc4f222e5077bface165abc48764160da0c2b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110229d6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402202d10bc09cb003320b2785a3dde3f376f52cfa10053f7113a8459242ad60555e702207380250de16176a97a257e4cb119273e9919ce913f02ae3514d091468136fe1301483045022100c6941c6b439f5874f1204beb5547a178efd879b532ef4bac767c8e9338fa86f702203a42ba6aee5a88f6abb51da055c7b9d6926e2cb777adaa77737f82aa700f900d01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 30440220484ef65cff47f331dbcceadb0869ddaf3294152a7093f37ee3f3232959d1ab5402206a7b461e4ccc547047222d9c9214a80bb81e69288c98084c963d43696065de18
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 304402201bd43e22a7254a0f5815fd01f809f69ffcebd8e30c21c6f6ba0c4e1fd8a2b7f602207a981abb50c57ee55f5f5a11edb2874db6224a19b4b12796396f0f8b210389f2
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 3044022050b90a9dce9b4bd9c990dd061dc78a4e05384e6c6a842e0083dafdbb1e9633670220116b0bf051c42c5140764dd7b0aeae7ae554b59763b896b2f2361ea40fb95383
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 304402202ae6f7bdd636f8d58808c9edb57e8636cc7ca60a45ac4b259f5559e766791c0c02201edc23b90278b8ca6496b913e5853dd0d0f6ea7552bc69fe0d0e4638c6daf81c
    # local_signature = 304402204c3b04c3270813e74cad0de2e5f5fb62323331a6d65bdc5a3b86afdf9765cbca02202dabee2c7a8c36405264bfb7536ea68092e8285f65b059736141712bc1a80d52
    output htlc_timeout_tx 2: 02000000000101cd5d003c91e0835851f17af14a992992d5d936a1e110d1245fb4857fd20b34610000000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220484ef65cff47f331dbcceadb0869ddaf3294152a7093f37ee3f3232959d1ab5402206a7b461e4ccc547047222d9c9214a80bb81e69288c98084c963d43696065de180147304402204c3b04c3270813e74cad0de2e5f5fb62323331a6d65bdc5a3b86afdf9765cbca02202dabee2c7a8c36405264bfb7536ea68092e8285f65b059736141712bc1a80d52010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 304402202fbf39a891903070c1271a03324bb567595864bc1d247fe1f9a8c2d0db3af82402205cd73ffadc2aa4cc08d12f10321c1c2a0973686a012de8df874258cb3dd79345
    output htlc_success_tx 1: 02000000000101cd5d003c91e0835851f17af14a992992d5d936a1e110d1245fb4857fd20b34610100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402201bd43e22a7254a0f5815fd01f809f69ffcebd8e30c21c6f6ba0c4e1fd8a2b7f602207a981abb50c57ee55f5f5a11edb2874db6224a19b4b12796396f0f8b210389f20147304402202fbf39a891903070c1271a03324bb567595864bc1d247fe1f9a8c2d0db3af82402205cd73ffadc2aa4cc08d12f10321c1c2a0973686a012de8df874258cb3dd79345012001010101010101010101010101010101010101010101010101010101010101016e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3045022100aea9c2577bb4ceb0ebaab154b79cbfb3f9f8e706327293014719601e152697af022040ff02881720fbc9d50fc0315aec2f75ff1d7287f6f04184a25b5fcd46ce4b44
    output htlc_timeout_tx 3: 02000000000101cd5d003c91e0835851f17af14a992992d5d936a1e110d1245fb4857fd20b346102000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022050b90a9dce9b4bd9c990dd061dc78a4e05384e6c6a842e0083dafdbb1e9633670220116b0bf051c42c5140764dd7b0aeae7ae554b59763b896b2f2361ea40fb9538301483045022100aea9c2577bb4ceb0ebaab154b79cbfb3f9f8e706327293014719601e152697af022040ff02881720fbc9d50fc0315aec2f75ff1d7287f6f04184a25b5fcd46ce4b44010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3044022016dfb71d6dc25c8770efcf498cf9066be5e314ba1fcbc8f521ce5f6ea595182902200864c249c893437bfd163c7dbaaf8452b7e0e47c6ec84f348ee5828449d805ea
    output htlc_success_tx 4: 02000000000101cd5d003c91e0835851f17af14a992992d5d936a1e110d1245fb4857fd20b346103000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402202ae6f7bdd636f8d58808c9edb57e8636cc7ca60a45ac4b259f5559e766791c0c02201edc23b90278b8ca6496b913e5853dd0d0f6ea7552bc69fe0d0e4638c6daf81c01473044022016dfb71d6dc25c8770efcf498cf9066be5e314ba1fcbc8f521ce5f6ea595182902200864c249c893437bfd163c7dbaaf8452b7e0e47c6ec84f348ee5828449d805ea012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2168
    # base commitment transaction fee = 3061
    # HTLC offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac68
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6984939 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022049ae72bf1b8ddd6cefed5dad42fb286f869e54efc1f5d200451a1c7d1638af0a02200813549d94834109a175582c56520177a9f734c2234f135ec4113f1265bca2bb
    # local_signature = 304502210088c38ef87bf165f104bce01e81296b6892f96d841c20045dfb43909a3a219291022053b017c23b0525e072becb657c95a277c1b946ea4dc3cf25a7a8910bd0894b6d
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78d007000000000000220020edcdff3e4bb6b538c0ee9639f56dfc4f222e5077bface165abc48764160da0c2b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110eb946a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040048304502210088c38ef87bf165f104bce01e81296b6892f96d841c20045dfb43909a3a219291022053b017c23b0525e072becb657c95a277c1b946ea4dc3cf25a7a8910bd0894b6d01473044022049ae72bf1b8ddd6cefed5dad42fb286f869e54efc1f5d200451a1c7d1638af0a02200813549d94834109a175582c56520177a9f734c2234f135ec4113f1265bca2bb01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 3045022100e8ac400e27af941dadf73c71b5000de5010358f06939e9225c14477dfa47630902207854a54a7b8f154ffc6266195dfc7276188cabe2716c2a6b854ebd90da87112f
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 3044022035c2ad04cecadc146678cbe234ff24b1d5a6931345307e2685d4e0f56b0cd98602200a9955ff3ebc552962a4cb41a4cdcb059c8c23fe7b4859db010a72bfe9efd7f9
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 30440220583c9e3694f17fd2571711179aa6bd3ead20899729c394a83e846fec0262a84c022049aad14ff2a71e3d5a28caa6c6118dca740ba5d973ca5c3f9d8d627120690863
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 304402204f3d886669f0f34dd245d1f1321d1e2e98029cf4d353f990c62b013a2b8b0f2902202552984fe43a6564ac06310ec811619c4634aa1324dcb70624fe8a94fcf467d7
    # local_signature = 3045022100b25b98d35e4c7f5cb1ca010f200a108cb107f423295942f70a288cd27b70ee710220172338d452bc1b6f72d9c302fdb858d72cadfacaf41eee09f3e08df1d5aba0ca
    output htlc_timeout_tx 2: 02000000000101355b1108732ec0d1c2c9fe99a80ca796873245ee1d7494778869d1350370e2830000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e8ac400e27af941dadf73c71b5000de5010358f06939e9225c14477dfa47630902207854a54a7b8f154ffc6266195dfc7276188cabe2716c2a6b854ebd90da87112f01483045022100b25b98d35e4c7f5cb1ca010f200a108cb107f423295942f70a288cd27b70ee710220172338d452bc1b6f72d9c302fdb858d72cadfacaf41eee09f3e08df1d5aba0ca010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 304502210093e14a9f1b736721e415e4778cc254c1f965bab1766865639a4b1b6dba0439c70220453a664bfc9b9954d724252b9793a8ef039b82fa087bf031597c4310d590a7e0
    output htlc_success_tx 1: 02000000000101355b1108732ec0d1c2c9fe99a80ca796873245ee1d7494778869d1350370e2830100000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022035c2ad04cecadc146678cbe234ff24b1d5a6931345307e2685d4e0f56b0cd98602200a9955ff3ebc552962a4cb41a4cdcb059c8c23fe7b4859db010a72bfe9efd7f90148304502210093e14a9f1b736721e415e4778cc254c1f965bab1766865639a4b1b6dba0439c70220453a664bfc9b9954d724252b9793a8ef039b82fa087bf031597c4310d590a7e0012001010101010101010101010101010101010101010101010101010101010101016e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3045022100da32ed520f6631de64cfc453e02e9326f520b676a0d41e1d12072380b9e803ee02206044141b7d7bb0290fd9cfc3c9f0fe6ba95ced3638331ff9e3e22ccdc8097e38
    output htlc_timeout_tx 3: 02000000000101355b1108732ec0d1c2c9fe99a80ca796873245ee1d7494778869d1350370e2830200000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220583c9e3694f17fd2571711179aa6bd3ead20899729c394a83e846fec0262a84c022049aad14ff2a71e3d5a28caa6c6118dca740ba5d973ca5c3f9d8d62712069086301483045022100da32ed520f6631de64cfc453e02e9326f520b676a0d41e1d12072380b9e803ee02206044141b7d7bb0290fd9cfc3c9f0fe6ba95ced3638331ff9e3e22ccdc8097e38010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100a5d204ac1942fa19eb521f93caf0799dc62892b19ed3391a5ef06d773409a87202203dccb273666f7f43f28e4db658b3a3d906ac3c1559694ac59ec0b0fa161e0a3f
    output htlc_success_tx 4: 02000000000101355b1108732ec0d1c2c9fe99a80ca796873245ee1d7494778869d1350370e28303000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402204f3d886669f0f34dd245d1f1321d1e2e98029cf4d353f990c62b013a2b8b0f2902202552984fe43a6564ac06310ec811619c4634aa1324dcb70624fe8a94fcf467d701483045022100a5d204ac1942fa19eb521f93caf0799dc62892b19ed3391a5ef06d773409a87202203dccb273666f7f43f28e4db658b3a3d906ac3c1559694ac59ec0b0fa161e0a3f012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2169
    # base commitment transaction fee = 2689
    # HTLC offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985311 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100cbd07ef5ed361cd65f48e6725855f69989989fab3f4d8ce4fd8cd5e64a1ae85c022031be133bfc0497b7cdf924bf3d9e85863305882e38a7df1171643df7253e91ff
    # local_signature = 304502210083a7dc01af84e5de5f69929c2615795f418562ffaa98480e3c7bdc58ea07b833022060ecb1a979045f96dca93ba0a7d90ab1cb3415ac721685bfc5ceb0a5cd747693
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de8431105f966a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040048304502210083a7dc01af84e5de5f69929c2615795f418562ffaa98480e3c7bdc58ea07b833022060ecb1a979045f96dca93ba0a7d90ab1cb3415ac721685bfc5ceb0a5cd74769301483045022100cbd07ef5ed361cd65f48e6725855f69989989fab3f4d8ce4fd8cd5e64a1ae85c022031be133bfc0497b7cdf924bf3d9e85863305882e38a7df1171643df7253e91ff01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 3044022022552bf8e2eab2b2cb482dc498323cbc131d613faf9da8db3301deb2fb818310022013b0cc4fed9aba5753c0e859435bfd6889b3c1bf5fee15128ba154ed3e9a3029
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 3044022039d6640f4c35031e0735d3040355d95ad222ffc15a4e30c2fefbb2eeb8485478022001c102121f319c9f309a8fa1843d6cf1c2637c200ee8335bd3c84e07857fecb0
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 30450221008351f3f4560531ed1eba38e473d3344a4c6ccf5cd9ded86e99e1e92b4ba00c2902202867b0fbdc29fc8064181919653916092e91705530a59ae5350944d065948809
    # local_signature = 3045022100df021222b05d3077759245e2fd5da66036c2b2f490c40ebd6dc0af111d24f099022037e5b405789bbc7b57224bd5826809c99d2238062e950dee16922e5f14761c7c
    output htlc_timeout_tx 2: 02000000000101bdfb471db604919d9dfa674eaef03495ee8280e70703097e1297bfa95dab0e370000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022022552bf8e2eab2b2cb482dc498323cbc131d613faf9da8db3301deb2fb818310022013b0cc4fed9aba5753c0e859435bfd6889b3c1bf5fee15128ba154ed3e9a302901483045022100df021222b05d3077759245e2fd5da66036c2b2f490c40ebd6dc0af111d24f099022037e5b405789bbc7b57224bd5826809c99d2238062e950dee16922e5f14761c7c010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 304402204758dd16ba751a3518562ca27c273e2e5f536384bd3046047d95841eadfd746d022044fcaaaae43f84a10e7aafce30344762ec201b8e5729e61a3e8d3a0935e373e9
    output htlc_timeout_tx 3: 02000000000101bdfb471db604919d9dfa674eaef03495ee8280e70703097e1297bfa95dab0e370100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022039d6640f4c35031e0735d3040355d95ad222ffc15a4e30c2fefbb2eeb8485478022001c102121f319c9f309a8fa1843d6cf1c2637c200ee8335bd3c84e07857fecb00147304402204758dd16ba751a3518562ca27c273e2e5f536384bd3046047d95841eadfd746d022044fcaaaae43f84a10e7aafce30344762ec201b8e5729e61a3e8d3a0935e373e9010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100a5ab4ee479a7dcc20c6b6be4a504a95f2597d4cd1b66e6b0df167deefdd9e2ba02200406fa79dfa0ba95921b1608a1c7109332b9a4ec4304b356b04315f55c838f6f
    output htlc_success_tx 4: 02000000000101bdfb471db604919d9dfa674eaef03495ee8280e70703097e1297bfa95dab0e3702000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221008351f3f4560531ed1eba38e473d3344a4c6ccf5cd9ded86e99e1e92b4ba00c2902202867b0fbdc29fc8064181919653916092e91705530a59ae5350944d06594880901483045022100a5ab4ee479a7dcc20c6b6be4a504a95f2597d4cd1b66e6b0df167deefdd9e2ba02200406fa79dfa0ba95921b1608a1c7109332b9a4ec4304b356b04315f55c838f6f012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2294
    # base commitment transaction fee = 2844
    # HTLC offered amount 2000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985156 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022063c332681fd706f3bcd1095d926cbd8c82ef4c0d2b1c0dac7d90f22c27041e7902201cc82cd37d3f5ceaa03455117b71f17f95b933753b96e0ce0760a8b92f317403
    # local_signature = 30440220045ed5e88d0fae2275cf66191855c23e65b3b97e8c2ce04bc6287aa8b4b32638022033103b89cb368e9ff4c1a5b2a888fec188e02a6c45d2af0d173de78c8b034bda
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d00700000000000022002083975515b28ad8c03b0915cae90787ff5f1a0ad8f313806a71ef6152fd5ecc78b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110c4956a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004730440220045ed5e88d0fae2275cf66191855c23e65b3b97e8c2ce04bc6287aa8b4b32638022033103b89cb368e9ff4c1a5b2a888fec188e02a6c45d2af0d173de78c8b034bda01473044022063c332681fd706f3bcd1095d926cbd8c82ef4c0d2b1c0dac7d90f22c27041e7902201cc82cd37d3f5ceaa03455117b71f17f95b933753b96e0ce0760a8b92f31740301475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 3045022100a7e2001faa2ad45159dbbe7293bdb7f1e69d6a3228371345dbddb2dec0b691ed022016fdae9966a1c9b39da0b78b07483ea5558853fb3852078905e1e2517f879787
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 304402200753e5bdc1698212861a71b34d6708df3648ab4f83ae394f15d4da9dc8565dce02207f644f7f8a76830930d6799a33428804807394b180636741c90084fd54608a9e
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 3045022100de573504656841eaa21e5ecf2a2632354249c3829c52f44f66de7b326c0cf8a80220696b322d4c29d73825ca38d41f0ad876e41bc48b795a10e57a16c663967b29da
    # local_signature = 304402203df687faa111e37ff544415abf85bc5c016983855c13ee68541c1bb45224fce1022007e92686ae9245fc13896ed1258009dc9fa1dfbfd10f64ea8ba7ef74067799a2
    output htlc_timeout_tx 2: 02000000000101524488b7d27c8edc4e9152fa8f9b2f7b6f22f83bb98b5497c94d19baa0e8895800000000000000000001cd010000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a7e2001faa2ad45159dbbe7293bdb7f1e69d6a3228371345dbddb2dec0b691ed022016fdae9966a1c9b39da0b78b07483ea5558853fb3852078905e1e2517f8797870147304402203df687faa111e37ff544415abf85bc5c016983855c13ee68541c1bb45224fce1022007e92686ae9245fc13896ed1258009dc9fa1dfbfd10f64ea8ba7ef74067799a2010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 304402202396482d4cd0c2788b9213509f61747b387fb3f01ce056de1feb3ac368236aba02202b6be086f885c95f0cf7dfb1403b433ff85b669f9e7c7f51f2d5ca4a17626c3a
    output htlc_timeout_tx 3: 02000000000101524488b7d27c8edc4e9152fa8f9b2f7b6f22f83bb98b5497c94d19baa0e8895801000000000000000001b5050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402200753e5bdc1698212861a71b34d6708df3648ab4f83ae394f15d4da9dc8565dce02207f644f7f8a76830930d6799a33428804807394b180636741c90084fd54608a9e0147304402202396482d4cd0c2788b9213509f61747b387fb3f01ce056de1feb3ac368236aba02202b6be086f885c95f0cf7dfb1403b433ff85b669f9e7c7f51f2d5ca4a17626c3a010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3044022018007fa68537452162184deb1350c2ec364ce08bcd4909b5a2fc166157fa471702200b90cd02099b2173b9393e733cc4a91ff8d5f34820094ac667d3f2a5cab750a5
    output htlc_success_tx 4: 02000000000101524488b7d27c8edc4e9152fa8f9b2f7b6f22f83bb98b5497c94d19baa0e88958020000000000000000019d090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100de573504656841eaa21e5ecf2a2632354249c3829c52f44f66de7b326c0cf8a80220696b322d4c29d73825ca38d41f0ad876e41bc48b795a10e57a16c663967b29da01473044022018007fa68537452162184deb1350c2ec364ce08bcd4909b5a2fc166157fa471702200b90cd02099b2173b9393e733cc4a91ff8d5f34820094ac667d3f2a5cab750a5012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2295
    # base commitment transaction fee = 2451
    # HTLC offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985549 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022075732bdddc06ff6b3b4cba29738fcf6f9ed662f621e4be0e729871fada8f7e7c02204cd4fe969bc2794101bc9f465f36845419b5b3044f6c4471cb667d2d5b004e6a
    # local_signature = 3044022054463d360d30ed5e94e12b801a5260e3bec433aff3b0e203977b925772f0b2a8022044d2d15f7e31d3ec41a63ba09cb7c7268ffbbfb15834614a91db4a997bb66ca4
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de8431104d976a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022054463d360d30ed5e94e12b801a5260e3bec433aff3b0e203977b925772f0b2a8022044d2d15f7e31d3ec41a63ba09cb7c7268ffbbfb15834614a91db4a997bb66ca401473044022075732bdddc06ff6b3b4cba29738fcf6f9ed662f621e4be0e729871fada8f7e7c02204cd4fe969bc2794101bc9f465f36845419b5b3044f6c4471cb667d2d5b004e6a01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3044022052652817ac84e2a50dd4d25a745be0aa63aea11fc27aa5b96ee8bc30a910db6e02207c6499749fd7fbc93e67472f6fdd607e3711b820c107b608af0d8e5f2c4614de
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 304402206a9d8e1e803ea60aa950a1f7af7be20be9570247490a6ae8b01ae7f23209dcd802207f3a72b9bf21e2ad5d60c9594edbc98a308012e4024c82cab243a243ebf68166
    # local_signature = 3045022100be5d226150df8d6d637b2200796543095e0675ee65cfe7400609f8f81e4d152502205a9439d25518935995ad840f842ea7a53344a47a73dc62d09bb0aebfe016b007
    output htlc_timeout_tx 3: 0200000000010106bc451de7e7e3a0c1160ddeace10a5c18b0231d452bdb98cfca8a05e76065d700000000000000000001b5050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022052652817ac84e2a50dd4d25a745be0aa63aea11fc27aa5b96ee8bc30a910db6e02207c6499749fd7fbc93e67472f6fdd607e3711b820c107b608af0d8e5f2c4614de01483045022100be5d226150df8d6d637b2200796543095e0675ee65cfe7400609f8f81e4d152502205a9439d25518935995ad840f842ea7a53344a47a73dc62d09bb0aebfe016b007010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100a2efcfc7ed51423edc3b3b5ebfe783cdd52831a713954bc54d14e0bd3e80086c022061870d72ff0d18d3ae8822b13eae67c57ee0d0ffe6b2a4fd51c4f04a96b39337
    output htlc_success_tx 4: 0200000000010106bc451de7e7e3a0c1160ddeace10a5c18b0231d452bdb98cfca8a05e76065d7010000000000000000019d090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402206a9d8e1e803ea60aa950a1f7af7be20be9570247490a6ae8b01ae7f23209dcd802207f3a72b9bf21e2ad5d60c9594edbc98a308012e4024c82cab243a243ebf6816601483045022100a2efcfc7ed51423edc3b3b5ebfe783cdd52831a713954bc54d14e0bd3e80086c022061870d72ff0d18d3ae8822b13eae67c57ee0d0ffe6b2a4fd51c4f04a96b39337012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3872
    # base commitment transaction fee = 4135
    # HTLC offered amount 3000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6983865 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022046a14cdadaf4d52d690b1576c6cbdd8ed2a203a4b035a96cd0fec90f8654c0d7022016df94e5aaf1cd04258e06002e1b1cbaabda622fd2d01f7b9c64b6bdf2ef4b20
    # local_signature = 304402206e5279fba8cd87a6dad6464e0d19d34317272e192290bd5b68249887bd6e4a6702200354725a19234b9a882c5ac2feb810e801d46802f76ead8b567444d8a7537ce1
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b000000000000220020311b8632d824446eb4104b5eac4c95ea8efc3f84f7863b772586c57b62450312a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110b9906a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402206e5279fba8cd87a6dad6464e0d19d34317272e192290bd5b68249887bd6e4a6702200354725a19234b9a882c5ac2feb810e801d46802f76ead8b567444d8a7537ce101473044022046a14cdadaf4d52d690b1576c6cbdd8ed2a203a4b035a96cd0fec90f8654c0d7022016df94e5aaf1cd04258e06002e1b1cbaabda622fd2d01f7b9c64b6bdf2ef4b2001475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 304402206c2855a02ce665d2026a5260f903d0b664635b9fce20632e6cc83ed8ed49d65a0220102bf44886423e47c653d9e5c9e1d1946fa0b6f3f0b4d9bf9a8d3b03dcb4caf1
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 3045022100f9defb0eb591c1b34e40fe5383fab107760ad2e147245aca26c7bd5d3dd689d30220448e799bbfad12d5043427bcf4846a547c638ef63f1481610ae27faa34d371c2
    # local_signature = 3045022100bfdcc196ceee04c42353859441727263baf9204b88a18a20f127b022632f656c02202f2752ffd5b81c10d0aa5fec6a4a1f17c71bb9caed279536648fb8caaf0426fa
    output htlc_timeout_tx 3: 020000000001014a8538dd13ea2968eebdc40129ccf1ecf43f220a6cba89d1d90876a18d5ddef90000000000000000000192010000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402206c2855a02ce665d2026a5260f903d0b664635b9fce20632e6cc83ed8ed49d65a0220102bf44886423e47c653d9e5c9e1d1946fa0b6f3f0b4d9bf9a8d3b03dcb4caf101483045022100bfdcc196ceee04c42353859441727263baf9204b88a18a20f127b022632f656c02202f2752ffd5b81c10d0aa5fec6a4a1f17c71bb9caed279536648fb8caaf0426fa010069210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3044022055be4e69cef8ebf3a562508ae309aaa92469fe8c4219ef8eacd3164bab4cffa30220458caa1db416cd418f30818420d196da928ca32d0d4f2b701b119478a6fe2631
    output htlc_success_tx 4: 020000000001014a8538dd13ea2968eebdc40129ccf1ecf43f220a6cba89d1d90876a18d5ddef9010000000000000000017a050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f9defb0eb591c1b34e40fe5383fab107760ad2e147245aca26c7bd5d3dd689d30220448e799bbfad12d5043427bcf4846a547c638ef63f1481610ae27faa34d371c201473044022055be4e69cef8ebf3a562508ae309aaa92469fe8c4219ef8eacd3164bab4cffa30220458caa1db416cd418f30818420d196da928ca32d0d4f2b701b119478a6fe2631012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3873
    # base commitment transaction fee = 3470
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6984530 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022011a4e9d6fa7fdc7a43577afeb5ad03346ccdc304f6177f848be265dcb9c683b1022023eb93a8416fbec9ac82f62e89fb86f6d0b1518ff47131b802c62545aea653f3
    # local_signature = 3045022100f2ab19b64c21a78851957ba88d58b137189cd4e0087edd3c98cb15ed4deab3e102204ddc5fd2c6315dff8bd642f1765df230c8b56d34a133a93f5ecf1f243d100559
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311052936a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100f2ab19b64c21a78851957ba88d58b137189cd4e0087edd3c98cb15ed4deab3e102204ddc5fd2c6315dff8bd642f1765df230c8b56d34a133a93f5ecf1f243d10055901473044022011a4e9d6fa7fdc7a43577afeb5ad03346ccdc304f6177f848be265dcb9c683b1022023eb93a8416fbec9ac82f62e89fb86f6d0b1518ff47131b802c62545aea653f301475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 304402205b40c077022528532a0ffcaf264127e57c73a17fffed437bd9f5a12ea2f19bf90220756db7c61c8a4221684e7c9910b8bf544d86cbd9486188b902d95c1beb363cd1
    # local_signature = 3044022033cef7b3da92ef464e551ea1a135c4e07e5691f06b2e26fcd39bced5a42064d802205310e735114067c805e3ae575e759b56ffe0f3cca45fc6378e33d84730abf4db
    output htlc_success_tx 4: 020000000001012d70d8747447022ff93ba3f6f9c7c3c9db8d38348630d6c88567bca64530cfdb000000000000000000017a050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402205b40c077022528532a0ffcaf264127e57c73a17fffed437bd9f5a12ea2f19bf90220756db7c61c8a4221684e7c9910b8bf544d86cbd9486188b902d95c1beb363cd101473044022033cef7b3da92ef464e551ea1a135c4e07e5691f06b2e26fcd39bced5a42064d802205310e735114067c805e3ae575e759b56ffe0f3cca45fc6378e33d84730abf4db012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5149
    # base commitment transaction fee = 4613
    # HTLC received amount 4000 wscript 210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6983387 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 304402202003a88f1f9527747acb57c13de2fe754de1f24160b8242a5d48701a90908bd302204bdd6b9c83089b70961ba12896e57544968ccbe5714bc6eff3de4166482421d8
    # local_signature = 3045022100d0c0725958031c218a97fcfd7ee271e08e9791b729ac8a0376235624bde042f40220325effabe03cac1315d7cfe260d0b843ebb0ff5740c55f685254841be582cd43
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f00000000000022002022ca70b9138696c383f9da5e3250280d26b993e13eb55f19cd841d7dc966d3c8c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110db8e6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100d0c0725958031c218a97fcfd7ee271e08e9791b729ac8a0376235624bde042f40220325effabe03cac1315d7cfe260d0b843ebb0ff5740c55f685254841be582cd430147304402202003a88f1f9527747acb57c13de2fe754de1f24160b8242a5d48701a90908bd302204bdd6b9c83089b70961ba12896e57544968ccbe5714bc6eff3de4166482421d801475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 30450221008b0fdf939565d1c3b0b45f1e2148326843e8709943cb02813ff5d12d66643c610220535b7bc5ef2f5c627fd12ee528cd2b07f4a643ee0d222fbdc6b66879edcc337f
    # local_signature = 3045022100f67bf0b58336062870df4f4e76432fe4fde1e63c7460800af86a45c9da33168d0220268c163c3204774d5bc0985bdfb56ee04b650783be920d9434281920949c3040
    output htlc_success_tx 4: 02000000000101f7403e3509287192717bdce1b1f0371e259308055451ddb3950ffe1e3338bcc50000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221008b0fdf939565d1c3b0b45f1e2148326843e8709943cb02813ff5d12d66643c610220535b7bc5ef2f5c627fd12ee528cd2b07f4a643ee0d222fbdc6b66879edcc337f01483045022100f67bf0b58336062870df4f4e76432fe4fde1e63c7460800af86a45c9da33168d0220268c163c3204774d5bc0985bdfb56ee04b650783be920d9434281920949c3040012004040404040404040404040404040404040404040404040404040404040404046e210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 2 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5150
    # base commitment transaction fee = 3728
    # to-local amount 6984272 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 304402205ccd7e9ce0670be0b57acde9fa09cba5a7a0dd0f92e9f07a45353ef1b0c2022c022069cece10b0bc87bd016cd3572721bc37373f3238dd816b3e88816da03210e2fa
    # local_signature = 304402206f7917f579a89734ed87a41df3ff733eaa65422edce59aa561f0458bb3028217022066e7fdd91ca7d70c9735530f6674537b00cadb77b3df4c11e78d62ff2f95e2e8
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8002c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311050926a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402206f7917f579a89734ed87a41df3ff733eaa65422edce59aa561f0458bb3028217022066e7fdd91ca7d70c9735530f6674537b00cadb77b3df4c11e78d62ff2f95e2e80147304402205ccd7e9ce0670be0b57acde9fa09cba5a7a0dd0f92e9f07a45353ef1b0c2022c022069cece10b0bc87bd016cd3572721bc37373f3238dd816b3e88816da03210e2fa01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
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

