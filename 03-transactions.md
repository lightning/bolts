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

# Appendix B: Transactions Test Vectors

In the following:
 - we consider *local* transactions, which implies that all payments to *local* are delayed
 - we assume that *local* is the funder
 - private keys are displayed as 32 bytes plus a trailing 1 (bitcoin's convention for "compressed" private keys, i.e. keys for which the public key is compressed)
  - transaction signatures are all deterministic, using RFC6979 (using HMAC-SHA256)

These test transactions are signed and be published and spent on regtest using the following setup:
- start bitcoin-qt or bitcoind in regtest mode with an empty data directory and priority set to false
```
rm -rf /tmp/btc1 && mkdir /tmp/btc1 && ~/code/bitcoin/src/qt/bitcoin-qt -txindex -regtest --relaypriority=false -datadir=/tmp/btc1 -port=18441 -rpcport=8441
```
- import block #1 (you already have the genesis block #0, using the debug console:
```   
submitblock 0000002006226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910faf2d96b7d903bc86c5dd4b609ceee6ab0ca396cac66c2eac1f671d87a5bd3eed1b849458ffff7f20000000000102000000010000000000000000000000000000000000000000000000000000000000000000ffffffff03510101ffffffff0200f2052a010000002321023699c8328fd3b3071558b651fb18c51e2ea93ebd0e507966b912cb1babf3ff97ac0000000000000000266a24aa21a9ede2f61c3f71d1defd3fa999dfa36953755c690689799962b48bebd836974e8cf900000000
```
- import the private key that can be used to spend the coinbase tx in block #1
```
importprivkey cR3LefrJ1cM4D5H4UVpSdgNRrX9nVM22EAQDSNj1H3fPhcUJ4GRv
```
- generate 499 blocks. this is necessay to activate segwit. You can check its activation status with getblockchaininfo
```
generate 500
```

Please note that the HTLC-Timeout transactions are time-locked, and that you will need to generate the appropriate number of blocks before you can publish them.

This is the funding transaction. You can import it in bitcoind with the following command:
```
sendrawtransaction  0200000001af2d96b7d903bc86c5dd4b609ceee6ab0ca396cac66c2eac1f671d87a5bd3eed000000004847304402201289831e1fc031557771c2a3bb7964b53155e2aee2bfdc84bcbf5900ee57478d022067584ff44e081cecaf37155a57d93ef56876580a6200efdcc4a21b95fcdc129c01ffffffff028096980000000000220020bcb416bd33938b5c716422dbc71f1f984c56e00a1ffc566116ecc622b98e9358805b6d29010000001976a914d3a1382595770b5fe47561375747c330c632c26a88ac00000000
```

We start by defining common basic parameters for each test vector: the
HTLCs are not used for the first "simple commitment tx with no HTLCs" test.

	local_payment_basepoint: 034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
	remote_payment_basepoint: 032c0b7cf95324a07d05398b240174dc0c2be444d96b159aa6c7f7b1e668680991
	local_funding_privkey: 1552dfba4f6cf29a62a0af13c8d6981d36d0ef8d61ba10fb0fe90da7634d7e1301
	local_funding_pubkey: 030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c1
	remote_funding_pubkey: 021cc26a70e15b191021a73101cb1331cbb28409285519fdb1d60cd17ea220b826
	local_secretkey: bb13b121cdc357cd2e608b0aea294afca36e2b34cf958e2e6451a2f27469449101
	localkey: 030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7
	remotekey: 039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878
	local_delayedkey: 03fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c
	local_revocation_key: 0212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19
	# funding wscript = 5221021cc26a70e15b191021a73101cb1331cbb28409285519fdb1d60cd17ea220b82621030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae
	
	htlc 0 direction: remote->local
	htlc 0 amount_msat: 1000000
	htlc 0 expiry: 550
	htlc 0 payment_preimage: 0000000000000000000000000000000000000000000000000000000000000000
	htlc 1 direction: remote->local
	htlc 1 amount_msat: 2000000
	htlc 1 expiry: 551
	htlc 1 payment_preimage: 0101010101010101010101010101010101010101010101010101010101010101
	htlc 2 direction: local->remote
	htlc 2 amount_msat: 2000000
	htlc 2 expiry: 552
	htlc 2 payment_preimage: 0202020202020202020202020202020202020202020202020202020202020202
	htlc 3 direction: local->remote
	htlc 3 amount_msat: 3000000
	htlc 3 expiry: 553
	htlc 3 payment_preimage: 0303030303030303030303030303030303030303030303030303030303030303
	htlc 4 direction: remote->local
	htlc 4 amount_msat: 4000000
	htlc 4 expiry: 554
	htlc 4 payment_preimage: 0404040404040404040404040404040404040404040404040404040404040404

	name: simple commitment tx with no HTLCs
	to_local_msat: MilliSatoshi(7000000000)
	to_remote_msat: MilliSatoshi(3000000000)
	feerate_per_kw: 15000
	# base commitment transaction fee = Satoshi(10860)
	# to-remote amount Satoshi(3000000)
	# to-local amount Satoshi(6989140)
	# local_signature = 3044022036746bef8fb1089cd095369b035df6bc7b99038cb1de86708652cd506410bb3f0220146091c405bf363aa598980071341e9f6caad323ef353654b52258974aea151c01
	# remote_signature = 3045022100835cef73786abd48b50c81aaa0eb0b14dc3d6239d41be46f41315e8264e08b460220484e9f6707b2b7d9cf44658af77751ddce96368cfb6347f43161f06a61dcaa5e01
	output commit_tx: 02000000000101f13dcd401237b2331c3b20669df9447ab6177b7c6a545b0a87434a99fd6b43e7000000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03654a56a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100835cef73786abd48b50c81aaa0eb0b14dc3d6239d41be46f41315e8264e08b460220484e9f6707b2b7d9cf44658af77751ddce96368cfb6347f43161f06a61dcaa5e01473044022036746bef8fb1089cd095369b035df6bc7b99038cb1de86708652cd506410bb3f0220146091c405bf363aa598980071341e9f6caad323ef353654b52258974aea151c01475221021cc26a70e15b191021a73101cb1331cbb28409285519fdb1d60cd17ea220b82621030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220

	name: commitment tx with all 5 htlcs untrimmed (minimum feerate
	to_local_msat: MilliSatoshi(6988000000)
	to_remote_msat: MilliSatoshi(3000000000)
	feerate_per_kw: 0
	# local_signature = 304402202edd45320199ef17c984546bca702f566cab80a75d0832d9b91aa15e579e67dd02201fe6aafdbd706fbef5e4065968cccd2fc86a7563a7caf71bd01279b18348339b01
	# remote_signature = 3045022100f8ee620e671c68cb3e8b18c234834beb8188512a515db56150255061b0a1324a02204a67401c75d347cc405344843f5db97bc2fbeaebc287540bd42074d16fcb139701
	# base commitment transaction fee = Satoshi(0)
	# to-local amount Satoshi(1000)
	# to-local amount Satoshi(2000)
	# to-local amount Satoshi(2000)
	# to-local amount Satoshi(3000)
	# to-local amount Satoshi(4000)
	# to-remote amount Satoshi(3000000)
	# to-local amount Satoshi(6988000)
	output commit_tx: 02000000000101f13dcd401237b2331c3b20669df9447ab6177b7c6a545b0a87434a99fd6b43e7000000000038b02b8007e8030000000000002200202d2d3cb16283e9ed46315612dfec8ebbb0aaa40aa308ba671a5f6a8c025b4bedd007000000000000220020a1eec874abf599f53a82a2e92e7f9226fa40bd59dfc4e59bedd9fe3eb9b83af9d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f0000000000002200207096603e654d70b82e0fd737f392495e645177e84a07b42da7f8e80a7da3284ac0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036e0a06a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100f8ee620e671c68cb3e8b18c234834beb8188512a515db56150255061b0a1324a02204a67401c75d347cc405344843f5db97bc2fbeaebc287540bd42074d16fcb13970147304402202edd45320199ef17c984546bca702f566cab80a75d0832d9b91aa15e579e67dd02201fe6aafdbd706fbef5e4065968cccd2fc86a7563a7caf71bd01279b18348339b01475221021cc26a70e15b191021a73101cb1331cbb28409285519fdb1d60cd17ea220b82621030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
	# htlc timeout tx 0 spends commit tx output 3 amount Satoshi(3000)
	# htlc timeout tx 0 local signature 304402204c481c6edf3146f57165fde8e245ca46f7a3f5912cd9d4ef092ed3d6a64a07a002207934732f2c7df9e144ca2a69d72f0eb0be4ebf4df85a2db51634727b1a849df801
	# htlc timeout tx 0 remote signature 3044022012a9d70574ccb834d8aefa1f35f83d82d0b30b902816d6105716d676b450e18902206f9ad172bbdc2a572e2b4dde3040b5cae134e03d51a0c741ace78baa0f4be86101
	# htlc timeout tx 0 02000000000101a99a7e9e181d73f09b8932d9632987982548f8d67672e10a837785d777bb350903000000000000000001b80b0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022012a9d70574ccb834d8aefa1f35f83d82d0b30b902816d6105716d676b450e18902206f9ad172bbdc2a572e2b4dde3040b5cae134e03d51a0c741ace78baa0f4be8610147304402204c481c6edf3146f57165fde8e245ca46f7a3f5912cd9d4ef092ed3d6a64a07a002207934732f2c7df9e144ca2a69d72f0eb0be4ebf4df85a2db51634727b1a849df801006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6829020000
	# htlc timeout tx 1 spends commit tx output 2 amount Satoshi(2000)
	# htlc timeout tx 1 local signature 304402202d3254e65559a0f6302428d328b43615fc584c9658f0a314f3abae6cba34400102205c395c8849cae485f9a63e47e25a1ccfa873b86b4a47f3c641f41748dd87406c01
	# htlc timeout tx 1 remote signature 3045022100d5f080f59b5b9ce5a091bff02c17a7deae76c8c9007249d08360c63c8c77db6302205ab05af8493025a975737a2558a61e7944141e4cae4f4392896552e3117dc51a01
	# htlc timeout tx 1 02000000000101a99a7e9e181d73f09b8932d9632987982548f8d67672e10a837785d777bb350902000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d5f080f59b5b9ce5a091bff02c17a7deae76c8c9007249d08360c63c8c77db6302205ab05af8493025a975737a2558a61e7944141e4cae4f4392896552e3117dc51a0147304402202d3254e65559a0f6302428d328b43615fc584c9658f0a314f3abae6cba34400102205c395c8849cae485f9a63e47e25a1ccfa873b86b4a47f3c641f41748dd87406c01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6828020000
	# htlc success tx 0 spends commit tx output 4 amount Satoshi(4000)
	# htlc success tx 0 local signature 30450221008b96c7a9ce4c3cdbafaace4093b390196f8bad8ada11c303677cc9d73185ae180220603e198b7518f3d32c09bd11e75fcc9a8e388104055846f4e8bcf69fcd69d01401
	# htlc success tx 0 remote signature 304402202d8a97f37d5bbcabd24d4164ac5caf3e2d8c054e2b474931b754ecff6944e2ef02201ac7df7cb691b2a72137da0b8bef668f7c358d583ccdff332fb97c6341067be401
	# htlc success tx 0 02000000000101a99a7e9e181d73f09b8932d9632987982548f8d67672e10a837785d777bb350904000000000000000001a00f0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402202d8a97f37d5bbcabd24d4164ac5caf3e2d8c054e2b474931b754ecff6944e2ef02201ac7df7cb691b2a72137da0b8bef668f7c358d583ccdff332fb97c6341067be4014830450221008b96c7a9ce4c3cdbafaace4093b390196f8bad8ada11c303677cc9d73185ae180220603e198b7518f3d32c09bd11e75fcc9a8e388104055846f4e8bcf69fcd69d014012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775022a02b175ac6800000000
	# htlc success tx 1 spends commit tx output 1 amount Satoshi(2000)
	# htlc success tx 1 local signature 304402203e27d1118dcc19045ac9b00d7296a2fb76e28dcb7105a2fc8ded9969dd965f9e022008f6f92ca8f5766cf5ef0d75a3b8b4feee84ae16135cf64f910bbfe51359f0d001
	# htlc success tx 1 remote signature 304402200a17f698f4bf6217a068e3f9cd127e3e25de56ab48208b4b46a8190ed97ea5cc0220467af7a2cc7a670dcfe136c445963e240869e65ea0f7f462aed4ab8ca190339701
	# htlc success tx 1 02000000000101a99a7e9e181d73f09b8932d9632987982548f8d67672e10a837785d777bb350901000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402200a17f698f4bf6217a068e3f9cd127e3e25de56ab48208b4b46a8190ed97ea5cc0220467af7a2cc7a670dcfe136c445963e240869e65ea0f7f462aed4ab8ca19033970147304402203e27d1118dcc19045ac9b00d7296a2fb76e28dcb7105a2fc8ded9969dd965f9e022008f6f92ca8f5766cf5ef0d75a3b8b4feee84ae16135cf64f910bbfe51359f0d0012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775022702b175ac6800000000
	# htlc success tx 2 spends commit tx output 0 amount Satoshi(1000)
	# htlc success tx 2 local signature 30440220125c7636bca705990701eb4208b0b708259b2191848b70b744ece2d0f5162836022041a10baa18b8554ecbd0d12bee65b788662e468cb41c99a422b3699280ac99ba01
	# htlc success tx 2 remote signature 3045022100bb0ffe2dad759646ee8bd4df8f2e6b349eab84b4cad488be87a31f15dda711a90220665c09a6062db9c696cc8bb2d64faa0837e5af66575af1974308a6055a62146c01
	# htlc success tx 2 02000000000101a99a7e9e181d73f09b8932d9632987982548f8d67672e10a837785d777bb350900000000000000000001e8030000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100bb0ffe2dad759646ee8bd4df8f2e6b349eab84b4cad488be87a31f15dda711a90220665c09a6062db9c696cc8bb2d64faa0837e5af66575af1974308a6055a62146c014730440220125c7636bca705990701eb4208b0b708259b2191848b70b744ece2d0f5162836022041a10baa18b8554ecbd0d12bee65b788662e468cb41c99a422b3699280ac99ba012000000000000000000000000000000000000000000000000000000000000000006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775022602b175ac6800000000
    


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

