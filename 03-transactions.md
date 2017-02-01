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

For every offered HTLC, if the HTLC amount plus the HTLC-timeout fee
would be less than `dust-limit-satoshis` set by the transaction owner,
the commitment transaction MUST NOT contain that output, otherwise it
MUST be generated as specified in
[Offered HTLC Outputs](#offered-htlc-outputs).

For every received HTLC, if the HTLC amount plus the HTLC-success fee
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

We start by defining common basic parameters for each test vector: the
HTLCs are not used for the first "simple commitment tx with no HTLCs" test.

    funding_tx_hash: 42a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7
    funding_output_index: 1
    funding_amount_satoshi: 10000000
    commitment_number: 42
    local_delay: 144
    local_dust_limit_satoshi: 546
    htlc 0 direction: remote->local
    htlc 0 amount_msat: 1000000
    htlc 0 expiry: 500000
    htlc 0 payment_preimage: 0000000000000000000000000000000000000000000000000000000000000000
    htlc 1 direction: remote->local
    htlc 1 amount_msat: 2000000
    htlc 1 expiry: 500001
    htlc 1 payment_preimage: 0101010101010101010101010101010101010101010101010101010101010101
    htlc 2 direction: local->remote
    htlc 2 amount_msat: 2000000
    htlc 2 expiry: 500002
    htlc 2 payment_preimage: 0202020202020202020202020202020202020202020202020202020202020202
    htlc 3 direction: local->remote
    htlc 3 amount_msat: 3000000
    htlc 3 expiry: 500003
    htlc 3 payment_preimage: 0303030303030303030303030303030303030303030303030303030303030303
    htlc 4 direction: remote->local
    htlc 4 amount_msat: 4000000
    htlc 4 expiry: 500004
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

    name: simple tx with two outputs
    to_local_msat: 7000000000
    to_remote_msat: 3000000000
    feerate_per_kw: 15000
    # base commitment transaction fee = 10860
    # to-local amount 6989140 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100ce5dadef1f831e531b0c07384c777b9bee6f7d712838579f432feb796cdd1470022057907a69b6d134a394d1450c3e92f53d99730a4818a06359a040f5656a6fb300
    # local_signature = 304402203390ec7939c2000500c5c859912acaa37811a9182b71f733c11fb30e62eb983602207f7c477f12093e99ba16e2b41bbcfe518b1ab02410789b83ad66a241b606513e
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03654a56a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba040047304402203390ec7939c2000500c5c859912acaa37811a9182b71f733c11fb30e62eb983602207f7c477f12093e99ba16e2b41bbcfe518b1ab02410789b83ad66a241b606513e01483045022100ce5dadef1f831e531b0c07384c777b9bee6f7d712838579f432feb796cdd1470022057907a69b6d134a394d1450c3e92f53d99730a4818a06359a040f5656a6fb30001475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with all 5 htlcs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 0
    # base commitment transaction fee = 0
    # HTLC offered amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 1000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # HTLC received amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6988000 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100bccece648600e113c32f7bb2fc0c000db05fc9c68ada9d067558e99403c60bf6022076947664f20b0b6e0e30ca2878e9f4842602097c9e927fa1cf5ea03735071efa
    # local_signature = 3045022100a5f947ad0516b7751cce0e252b22fe2088355d82db774334e2a4d839cb64313e0220498ad6cacdd8ce16641be7984b03e31488b8a352d69db21e32bdcd5c6c7a05b1
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8007e803000000000000220020d392ebcc3aaaa6b063e8e7e67f5bf9bc1b5e8fc0d9e956699b342eee8887efffd0070000000000002200201e918f414255792d26e3ce43c578c1dfcc5492179dc802ff8adc0c8492afd7f2d007000000000000220020ab9d30be0a9663f2545e2627abca2b237a7f386b7dd38726d4079429ca43993cb80b000000000000220020745b4bf58775220540a3f2ae17a926a69d39f82da7a2257d463c9ccdab3d5c4ca00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036e0a06a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0400483045022100a5f947ad0516b7751cce0e252b22fe2088355d82db774334e2a4d839cb64313e0220498ad6cacdd8ce16641be7984b03e31488b8a352d69db21e32bdcd5c6c7a05b101483045022100bccece648600e113c32f7bb2fc0c000db05fc9c68ada9d067558e99403c60bf6022076947664f20b0b6e0e30ca2878e9f4842602097c9e927fa1cf5ea03735071efa01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 304402202aa0fcc5fe85fd1e55b02e78a1965efbb2b5ddb6b7bfa03cfb6272f9ca18037a02206175a6a952b8a164a1fdb1ba10f47bafde07d634fce0ec950246508415db4aea
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 30440220606aed69b4ec8fd08023f75b01c328ccf0e4ee99761989e37167da6ed095acd9022065d30187e0228b5c0c720786542d3da2db3e684c7adb45f0d50122b3da1ab141
    # signature for output 2 (htlc 1)
    remote_htlc_signature = 30440220307a986e12203a0a1ecb4e6c03ed07a93f49ee88d946c06d098c5682ea55c9bc022044c4cf76dad4eacce9c5b7456af720ce19a7d8ea5f42076661858e238c605d15
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 3045022100910de1f3a1079d91dfb21342f18d801b2174863f1e865d65429f444fd34cf0d602205946cefacbf5cd8bae8935fe7bdb3a58c72de6c30c3d4b527bae6d0093fd19de
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 3044022050f20f5dd28b8aa74cd2bc01becf97aee7b3a551f1e554cac41404ad956ec97d02204fa17fa59a1b2b3962b45891af44e53e2c308770fe37a57757c0f638d33f7fd7
    # local_signature = 3043021f0f500c5f0547c6362625f7fa8be36b7496fc4c9d805da5b34cdaf296d95eb902201f311a41ad6450db7bcc586e60f13212953dbf6deb83d90246fdc5fbddd19ba7
    output htlc_success_tx 0: 0200000000010190c96ee655bdbfd15e2574455d71c519b6789b9da9b3f80217b81e3c71b0da0e00000000000000000001e803000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402202aa0fcc5fe85fd1e55b02e78a1965efbb2b5ddb6b7bfa03cfb6272f9ca18037a02206175a6a952b8a164a1fdb1ba10f47bafde07d634fce0ec950246508415db4aea01463043021f0f500c5f0547c6362625f7fa8be36b7496fc4c9d805da5b34cdaf296d95eb902201f311a41ad6450db7bcc586e60f13212953dbf6deb83d90246fdc5fbddd19ba7012000000000000000000000000000000000000000000000000000000000000000006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    # local_signature = 3045022100fc6538e0ba0d9e12141a731d169eeb0a4771ac33cbcfe28b8932a3b31fa7ea3002200a588f4901cc54ed61769bce60852161c2486f0778d8b702f782b0db0b559e95
    output htlc_timeout_tx 2: 0200000000010190c96ee655bdbfd15e2574455d71c519b6789b9da9b3f80217b81e3c71b0da0e01000000000000000001d007000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba05004730440220606aed69b4ec8fd08023f75b01c328ccf0e4ee99761989e37167da6ed095acd9022065d30187e0228b5c0c720786542d3da2db3e684c7adb45f0d50122b3da1ab14101483045022100fc6538e0ba0d9e12141a731d169eeb0a4771ac33cbcfe28b8932a3b31fa7ea3002200a588f4901cc54ed61769bce60852161c2486f0778d8b702f782b0db0b559e9501006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6822a10700
    # local_signature = 3044022025aae5ffacf0451916511aa68d6ad9283b14b93460369ad5eb4febe915c6dbde0220290c017b1f886bb2473710b0f8a5c2b8ba5ca2dd6493cd6adc18382bf81e58b1
    output htlc_success_tx 1: 0200000000010190c96ee655bdbfd15e2574455d71c519b6789b9da9b3f80217b81e3c71b0da0e02000000000000000001d007000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba05004730440220307a986e12203a0a1ecb4e6c03ed07a93f49ee88d946c06d098c5682ea55c9bc022044c4cf76dad4eacce9c5b7456af720ce19a7d8ea5f42076661858e238c605d1501473044022025aae5ffacf0451916511aa68d6ad9283b14b93460369ad5eb4febe915c6dbde0220290c017b1f886bb2473710b0f8a5c2b8ba5ca2dd6493cd6adc18382bf81e58b1012001010101010101010101010101010101010101010101010101010101010101016d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    # local_signature = 30450221008bddcf6ed47d23dbfc3152fd11f30b6638616e7153bb598d8a316cfe9c8cafe902203b1095023ffcb5b4bc39c47ee949cd1f744c018343b2af2b8f91a4cf7fea93a8
    output htlc_timeout_tx 3: 0200000000010190c96ee655bdbfd15e2574455d71c519b6789b9da9b3f80217b81e3c71b0da0e03000000000000000001b80b000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500483045022100910de1f3a1079d91dfb21342f18d801b2174863f1e865d65429f444fd34cf0d602205946cefacbf5cd8bae8935fe7bdb3a58c72de6c30c3d4b527bae6d0093fd19de014830450221008bddcf6ed47d23dbfc3152fd11f30b6638616e7153bb598d8a316cfe9c8cafe902203b1095023ffcb5b4bc39c47ee949cd1f744c018343b2af2b8f91a4cf7fea93a801006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6823a10700
    # local_signature = 3045022100a16e1b9c1f69b4bc56872627bcdb00f124f6a55fd5ea6478842b16314a87f3f102206bdee196d63cb558290baa93de3d0ca7c692d57ec753f77d8344e3e1d1deebb2
    output htlc_success_tx 4: 0200000000010190c96ee655bdbfd15e2574455d71c519b6789b9da9b3f80217b81e3c71b0da0e04000000000000000001a00f000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500473044022050f20f5dd28b8aa74cd2bc01becf97aee7b3a551f1e554cac41404ad956ec97d02204fa17fa59a1b2b3962b45891af44e53e2c308770fe37a57757c0f638d33f7fd701483045022100a16e1b9c1f69b4bc56872627bcdb00f124f6a55fd5ea6478842b16314a87f3f102206bdee196d63cb558290baa93de3d0ca7c692d57ec753f77d8344e3e1d1deebb2012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 7 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 678
    # base commitment transaction fee = 1073
    # HTLC offered amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 1000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # HTLC received amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6986927 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402205ec58ed9566c61046117af0337974dda4dd644beb7f9d119a82032e940740f3b022059c34279f333d841b2733879ae43100252036516d652095078a83e25e699d0d0
    # local_signature = 304402207e2d3b11091e739de71649b0a598552ce525916948a69d6c279945b7296622ab0220382a4a164906faec1a7254e4b5d0d56a68f9b822eeff5b91cb34d236fa33b910
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8007e803000000000000220020d392ebcc3aaaa6b063e8e7e67f5bf9bc1b5e8fc0d9e956699b342eee8887efffd0070000000000002200201e918f414255792d26e3ce43c578c1dfcc5492179dc802ff8adc0c8492afd7f2d007000000000000220020ab9d30be0a9663f2545e2627abca2b237a7f386b7dd38726d4079429ca43993cb80b000000000000220020745b4bf58775220540a3f2ae17a926a69d39f82da7a2257d463c9ccdab3d5c4ca00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036af9c6a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba040047304402207e2d3b11091e739de71649b0a598552ce525916948a69d6c279945b7296622ab0220382a4a164906faec1a7254e4b5d0d56a68f9b822eeff5b91cb34d236fa33b9100147304402205ec58ed9566c61046117af0337974dda4dd644beb7f9d119a82032e940740f3b022059c34279f333d841b2733879ae43100252036516d652095078a83e25e699d0d001475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 3045022100908ba5b3476df91c981260bd5935f0cbbf587fc01558368a05280b86c7c9c26e02200338061211c2d4725081f19de4590136f814e1ae46f887b4e37fb367df886ed0
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 3045022100eceb968b0defb3551b09fd8cc0e6978731f0c44e8d62497fcf3cc13ab27fb3970220146d06b6eafd8a33555e12a7f0bbe1cecb433d6debfc75706b8e7398936164a5
    # signature for output 2 (htlc 1)
    remote_htlc_signature = 304402200bbe3e275571550798f65260fe8b8c03b289b6f989d2ece89b8fb200dba84fbc022026619055cb780171e4dab6e878845ea27aaa713935a7df160fa171c0d1e0d45a
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 30450221008030abbd92321737f53961720b0251edba561166373eb189ac50c96768949e13022029060757497bfb7974a276e358bcb83fb9e82dc43f0f108cc1c25b90f5801a24
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 304402204081cfb9323f5bdaff89921f625b27d9e4e602ece2b1a8f8cac6ef681c45c4b9022015e052b1375170a72040ce5e9f4ae8b138db1c0008ca2ce4c66ef7b072594249
    # local_signature = 30440220567b409d58063c8df380bb1c38bab1847205419f40f6520d99cd741e48e0111f022051e0d06d5d7c7d975e2ae50e40dd2d4d50c40e37a457bbfb352991b7777f5388
    output htlc_success_tx 0: 020000000001011d2033b287d23a37cae96a514c76c1699b6c2cf286e495c7f1ca6f28522ff59c000000000000000000012102000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500483045022100908ba5b3476df91c981260bd5935f0cbbf587fc01558368a05280b86c7c9c26e02200338061211c2d4725081f19de4590136f814e1ae46f887b4e37fb367df886ed0014730440220567b409d58063c8df380bb1c38bab1847205419f40f6520d99cd741e48e0111f022051e0d06d5d7c7d975e2ae50e40dd2d4d50c40e37a457bbfb352991b7777f5388012000000000000000000000000000000000000000000000000000000000000000006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    # local_signature = 3045022100e85850ccd3b44914b344d57fc3e7b83242780309c0b8580f14463c7a00433dca022047b26864d9ff3459a09f5cc151d6b8f30f6b40a0e18d0f69dcb28521e4455016
    output htlc_timeout_tx 2: 020000000001011d2033b287d23a37cae96a514c76c1699b6c2cf286e495c7f1ca6f28522ff59c010000000000000000010906000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500483045022100eceb968b0defb3551b09fd8cc0e6978731f0c44e8d62497fcf3cc13ab27fb3970220146d06b6eafd8a33555e12a7f0bbe1cecb433d6debfc75706b8e7398936164a501483045022100e85850ccd3b44914b344d57fc3e7b83242780309c0b8580f14463c7a00433dca022047b26864d9ff3459a09f5cc151d6b8f30f6b40a0e18d0f69dcb28521e445501601006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6822a10700
    # local_signature = 3045022100ecde0a07d1a94a0d411655f5437e5f603d2209f43e033312a593429fe1f754fc0220181988e152064fcdb93cecc7a320a10288a6477f5526e02571bc3fa76b16abcd
    output htlc_success_tx 1: 020000000001011d2033b287d23a37cae96a514c76c1699b6c2cf286e495c7f1ca6f28522ff59c020000000000000000010906000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402200bbe3e275571550798f65260fe8b8c03b289b6f989d2ece89b8fb200dba84fbc022026619055cb780171e4dab6e878845ea27aaa713935a7df160fa171c0d1e0d45a01483045022100ecde0a07d1a94a0d411655f5437e5f603d2209f43e033312a593429fe1f754fc0220181988e152064fcdb93cecc7a320a10288a6477f5526e02571bc3fa76b16abcd012001010101010101010101010101010101010101010101010101010101010101016d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    # local_signature = 3045022100acac9c5cfaba0f636d01c47738c80a663cd2130d8a4b8bc4a1c6945d789ba65b0220550b108c6d1e1f4ab9ec53ee1e64b5cc346666c11ee1231d2b6767585e540ffb
    output htlc_timeout_tx 3: 020000000001011d2033b287d23a37cae96a514c76c1699b6c2cf286e495c7f1ca6f28522ff59c03000000000000000001f109000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba05004830450221008030abbd92321737f53961720b0251edba561166373eb189ac50c96768949e13022029060757497bfb7974a276e358bcb83fb9e82dc43f0f108cc1c25b90f5801a2401483045022100acac9c5cfaba0f636d01c47738c80a663cd2130d8a4b8bc4a1c6945d789ba65b0220550b108c6d1e1f4ab9ec53ee1e64b5cc346666c11ee1231d2b6767585e540ffb01006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6823a10700
    # local_signature = 3044022032b2082cfbfda544aaca0a4808c7aa596474bb922d9bc81e51de613db1f3ff13022079ff20da12e73151557ad5ff218ba70f020066867055eae43a84d77c3835ac22
    output htlc_success_tx 4: 020000000001011d2033b287d23a37cae96a514c76c1699b6c2cf286e495c7f1ca6f28522ff59c04000000000000000001d90d000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402204081cfb9323f5bdaff89921f625b27d9e4e602ece2b1a8f8cac6ef681c45c4b9022015e052b1375170a72040ce5e9f4ae8b138db1c0008ca2ce4c66ef7b07259424901473044022032b2082cfbfda544aaca0a4808c7aa596474bb922d9bc81e51de613db1f3ff13022079ff20da12e73151557ad5ff218ba70f020066867055eae43a84d77c3835ac22012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 679
    # base commitment transaction fee = 958
    # HTLC offered amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6987042 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100e666f3387824532b3209ee97452ccd2ab694ef31c30e83bf538ab46760d917cb02203e81a884535dcee987ea278f42542783f9bc2177564aa98d200472f70b5314fd
    # local_signature = 304502210080f7bf4df39c359f32ab48d99a491727f6fd46646de4aef6d2a19d2ae838d79f02206e99f68a8c807b23f5e85d4ae482f1c23401b7b6d13b2dc7f5623c965ea10b04
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8006d0070000000000002200201e918f414255792d26e3ce43c578c1dfcc5492179dc802ff8adc0c8492afd7f2d007000000000000220020ab9d30be0a9663f2545e2627abca2b237a7f386b7dd38726d4079429ca43993cb80b000000000000220020745b4bf58775220540a3f2ae17a926a69d39f82da7a2257d463c9ccdab3d5c4ca00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036229d6a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba040048304502210080f7bf4df39c359f32ab48d99a491727f6fd46646de4aef6d2a19d2ae838d79f02206e99f68a8c807b23f5e85d4ae482f1c23401b7b6d13b2dc7f5623c965ea10b0401483045022100e666f3387824532b3209ee97452ccd2ab694ef31c30e83bf538ab46760d917cb02203e81a884535dcee987ea278f42542783f9bc2177564aa98d200472f70b5314fd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 304402203a657c7427ba9d72625158d0c433d74606299b380a709d115c07c172ce6e06b802202aaee4e00df1317449c54a5ee9f0946657ca1396d83aaa02bfd8e6f9f20e3831
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 3045022100f2ca37e5c31a3fa1a6ec0709070cd4488e0cf8832495b56388adf76c389a64f002207a53747ecfaf589de9073aa29efda74475c14263dab4b6eca7e9ae418cd4af81
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 3044022024db994248658916569ce505abde957c554db218d35d9717b3801f672f1c3b9b022016cdca398b4068192b723906a22fff842bbb63ecd5d4f32d620c2fc11480c90a
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 3044022058cf2c4c15b106430e5822a68e4b2cbeecc6b5be3715be471cd85de2f5f5648c02200aeacb99af0899610d1c72b3085d0cf8274a12bb4df144b6d3bbd0302f084054
    # local_signature = 304402200702e9ec366e0d3ca068b4e7eb347194261975957dc19f33c7a1d4f23a139c68022013f34639c6118dad4a370dda8b30c5580840e5cc75ec880ec18c2b06fad36505
    output htlc_timeout_tx 2: 02000000000101df1157810b7174e8852d1eea24abf9b5038e95c2bc47d3e6421e1dd6727ae671000000000000000000010906000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402203a657c7427ba9d72625158d0c433d74606299b380a709d115c07c172ce6e06b802202aaee4e00df1317449c54a5ee9f0946657ca1396d83aaa02bfd8e6f9f20e38310147304402200702e9ec366e0d3ca068b4e7eb347194261975957dc19f33c7a1d4f23a139c68022013f34639c6118dad4a370dda8b30c5580840e5cc75ec880ec18c2b06fad3650501006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6822a10700
    # local_signature = 304402206393db43e2a59cc650dd929142b18fe99db5ba9f3b09224946644d4509f9627002207160ab4ed465b464845cf1da3e4e0938fe3d9da00757045d176f678134340795
    output htlc_success_tx 1: 02000000000101df1157810b7174e8852d1eea24abf9b5038e95c2bc47d3e6421e1dd6727ae671010000000000000000010906000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500483045022100f2ca37e5c31a3fa1a6ec0709070cd4488e0cf8832495b56388adf76c389a64f002207a53747ecfaf589de9073aa29efda74475c14263dab4b6eca7e9ae418cd4af810147304402206393db43e2a59cc650dd929142b18fe99db5ba9f3b09224946644d4509f9627002207160ab4ed465b464845cf1da3e4e0938fe3d9da00757045d176f678134340795012001010101010101010101010101010101010101010101010101010101010101016d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    # local_signature = 304402201b43cc8a04ca5dc59d44f502a8f3941ef87c7aa94fdcea87f69115af6d7f1f1e02204f9df9c075181ed611fb7ec100ca01488b3d193eda2a2c03c22d7edb1f9d4c71
    output htlc_timeout_tx 3: 02000000000101df1157810b7174e8852d1eea24abf9b5038e95c2bc47d3e6421e1dd6727ae67102000000000000000001f109000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500473044022024db994248658916569ce505abde957c554db218d35d9717b3801f672f1c3b9b022016cdca398b4068192b723906a22fff842bbb63ecd5d4f32d620c2fc11480c90a0147304402201b43cc8a04ca5dc59d44f502a8f3941ef87c7aa94fdcea87f69115af6d7f1f1e02204f9df9c075181ed611fb7ec100ca01488b3d193eda2a2c03c22d7edb1f9d4c7101006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6823a10700
    # local_signature = 3044022062c43ec183ff2cceb1a13912eb0408dc99e81213cd0d7b4404da2a7c677becd90220181fea9db5b367a0fc609a7da49a847619845e988552ab1db048e8b4480220d8
    output htlc_success_tx 4: 02000000000101df1157810b7174e8852d1eea24abf9b5038e95c2bc47d3e6421e1dd6727ae67103000000000000000001d90d000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500473044022058cf2c4c15b106430e5822a68e4b2cbeecc6b5be3715be471cd85de2f5f5648c02200aeacb99af0899610d1c72b3085d0cf8274a12bb4df144b6d3bbd0302f08405401473044022062c43ec183ff2cceb1a13912eb0408dc99e81213cd0d7b4404da2a7c677becd90220181fea9db5b367a0fc609a7da49a847619845e988552ab1db048e8b4480220d8012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2168
    # base commitment transaction fee = 3061
    # HTLC offered amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6984939 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022053574d78f635806143aadad1d483422a4298b0402882724941da95f04ed201ed02203e4dd853f0f34414f6df992c2c76a31da41e027c428e9eab5661b0560f011571
    # local_signature = 304402205bfc1a43adb5642fe5290d9ae4a650d5b92581a6f2916605c4e2a459c26cd7750220053f809fe89b4b8789b7e314dd27fdd377154f2677e2e38e16feba8a875d0c84
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8006d0070000000000002200201e918f414255792d26e3ce43c578c1dfcc5492179dc802ff8adc0c8492afd7f2d007000000000000220020ab9d30be0a9663f2545e2627abca2b237a7f386b7dd38726d4079429ca43993cb80b000000000000220020745b4bf58775220540a3f2ae17a926a69d39f82da7a2257d463c9ccdab3d5c4ca00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036eb946a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba040047304402205bfc1a43adb5642fe5290d9ae4a650d5b92581a6f2916605c4e2a459c26cd7750220053f809fe89b4b8789b7e314dd27fdd377154f2677e2e38e16feba8a875d0c8401473044022053574d78f635806143aadad1d483422a4298b0402882724941da95f04ed201ed02203e4dd853f0f34414f6df992c2c76a31da41e027c428e9eab5661b0560f01157101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 304402207f51b3a47128e5092e861f773ce0b24bfeff404b75643565eebc93612c1ec26802200c067f3e6a65270ac3aa0c8f7a5252c1998279e7b31058180c8b23b40fea7dbc
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 3045022100bebe7584c00119359e89dbe9f594eab20006138b878b523a8537e17d50056b1a02203dc430b29340d01bfdbbe6929840a3019dc22e08c3909b350cb8a13cc7360d4c
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 304402205bed3cbf80d36b8c237d9a4b462ce6949ec93d01e8264f3113fd0f6f0c350ea5022002bddd2bbf3dbaa49ada4f72b7db0e1ea84acb1d7fc92f3ac6eea4eb458b4ded
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 30440220168a9565bce487a2104534317f08d3f6e68df91f87354c407aac4804faf1f96202205c0177a4fd40b33332114ef7a594f2900a6e7c89572e86a4d94b3656c3e60e22
    # local_signature = 3044022008a3ac30280a4561d4999582f289844df4d28baeed504aac8cd819b8f4a1c60b02207f781d3ffd442d3479cce62b1d220ef3aefcb2c1ddf2d54de69af4e9ddd0758b
    output htlc_timeout_tx 2: 02000000000101acefca4fb602c8d750a53805a96729cb7c460b255d45d29e113bdf3a0daa23fa000000000000000000012102000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402207f51b3a47128e5092e861f773ce0b24bfeff404b75643565eebc93612c1ec26802200c067f3e6a65270ac3aa0c8f7a5252c1998279e7b31058180c8b23b40fea7dbc01473044022008a3ac30280a4561d4999582f289844df4d28baeed504aac8cd819b8f4a1c60b02207f781d3ffd442d3479cce62b1d220ef3aefcb2c1ddf2d54de69af4e9ddd0758b01006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6822a10700
    # local_signature = 3045022100c63098d283b2606cd803e9b12f1fa991088c6003ade6d25039625c66f7e6b55a022043a6e2ad030ec87c2a5688fce716099f0d1821a044cc1218fd3130f0cf2ac60d
    output htlc_success_tx 1: 02000000000101acefca4fb602c8d750a53805a96729cb7c460b255d45d29e113bdf3a0daa23fa010000000000000000012102000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500483045022100bebe7584c00119359e89dbe9f594eab20006138b878b523a8537e17d50056b1a02203dc430b29340d01bfdbbe6929840a3019dc22e08c3909b350cb8a13cc7360d4c01483045022100c63098d283b2606cd803e9b12f1fa991088c6003ade6d25039625c66f7e6b55a022043a6e2ad030ec87c2a5688fce716099f0d1821a044cc1218fd3130f0cf2ac60d012001010101010101010101010101010101010101010101010101010101010101016d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    # local_signature = 3045022100f8327a3a3e550af6f113efa378c6e17bfd82b37da958f729a4e34a94b6536f2202207a7388a1a22a65a0a8ce5ef9f03f8a762111de5ab19a667507e62d56fe91e038
    output htlc_timeout_tx 3: 02000000000101acefca4fb602c8d750a53805a96729cb7c460b255d45d29e113bdf3a0daa23fa020000000000000000010906000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402205bed3cbf80d36b8c237d9a4b462ce6949ec93d01e8264f3113fd0f6f0c350ea5022002bddd2bbf3dbaa49ada4f72b7db0e1ea84acb1d7fc92f3ac6eea4eb458b4ded01483045022100f8327a3a3e550af6f113efa378c6e17bfd82b37da958f729a4e34a94b6536f2202207a7388a1a22a65a0a8ce5ef9f03f8a762111de5ab19a667507e62d56fe91e03801006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6823a10700
    # local_signature = 3045022100d149e6f4aec0a506122dcb773895f9dd7c1a6107bf5218f14c689e5590ac25d902205611f3a0b42268a12e070410ccc51c91f5ab670d515cdc5ccf4c6abb6cd25867
    output htlc_success_tx 4: 02000000000101acefca4fb602c8d750a53805a96729cb7c460b255d45d29e113bdf3a0daa23fa03000000000000000001f109000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba05004730440220168a9565bce487a2104534317f08d3f6e68df91f87354c407aac4804faf1f96202205c0177a4fd40b33332114ef7a594f2900a6e7c89572e86a4d94b3656c3e60e2201483045022100d149e6f4aec0a506122dcb773895f9dd7c1a6107bf5218f14c689e5590ac25d902205611f3a0b42268a12e070410ccc51c91f5ab670d515cdc5ccf4c6abb6cd25867012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2169
    # base commitment transaction fee = 2689
    # HTLC offered amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6985311 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022044f485e69dd18b200af793d11cf01a63a88875968e1f428889946ea911dee6e102204fa5f4d72afa9ed58d6d2dc0b9cce58cbb2397be895c388493d2ed48cce23fd3
    # local_signature = 304402206ce4d08fe4c41a2958a5ad4363110fbf3b9d93949a1f90d0bb6fd78daa6f1daa02204c5053bbc61257bfbe7a0b72d484b77fde3859f542797d3fecec51aba20dcb3a
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8005d0070000000000002200201e918f414255792d26e3ce43c578c1dfcc5492179dc802ff8adc0c8492afd7f2b80b000000000000220020745b4bf58775220540a3f2ae17a926a69d39f82da7a2257d463c9ccdab3d5c4ca00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0365f966a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba040047304402206ce4d08fe4c41a2958a5ad4363110fbf3b9d93949a1f90d0bb6fd78daa6f1daa02204c5053bbc61257bfbe7a0b72d484b77fde3859f542797d3fecec51aba20dcb3a01473044022044f485e69dd18b200af793d11cf01a63a88875968e1f428889946ea911dee6e102204fa5f4d72afa9ed58d6d2dc0b9cce58cbb2397be895c388493d2ed48cce23fd301475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 3045022100af1f81490d1003967273a85981ab1208ea16f1f44427301c7def728c1129b4020220243c5bc266e84cc9e470fabd9d646eda57018d1f459b025fbefca7482ef7440f
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 304402205d8ea2626a999f65be5ebf02c40ece3fd2125fa3a91f5b13d6b279ef268ccec302207a5ee61665a98d54553ea59500824ace572793d1b1e0184662b14ad41f2f9da8
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 30450221008e3dbd9c55361d0ec192fc1406192c31b4062c6decfb1f0118e889f169c27a4a022047d1e5c70f23fd1f8b0027504d565875ff18795afa4027bff9de3b5b96527553
    # local_signature = 304502210095753ad49c6b786628b1dee3aac0b1760207ad0d6429e1e709faa41a6b67858602207d3ae06b6f240b2d95d3eca530ae8cfcea8c4f5728c2b7d3a39301eda639ad48
    output htlc_timeout_tx 2: 02000000000101f265406b0ee3eb37ab6e365862228fbadd762567f1d1be612a9f749558663f86000000000000000000012102000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500483045022100af1f81490d1003967273a85981ab1208ea16f1f44427301c7def728c1129b4020220243c5bc266e84cc9e470fabd9d646eda57018d1f459b025fbefca7482ef7440f0148304502210095753ad49c6b786628b1dee3aac0b1760207ad0d6429e1e709faa41a6b67858602207d3ae06b6f240b2d95d3eca530ae8cfcea8c4f5728c2b7d3a39301eda639ad4801006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6822a10700
    # local_signature = 3045022100da33bbef961e5c52f047edbeb63a6896f0a59127d9e0a0d3a304f7c4dab0f001022043ada6b2f93be37cb94a1fb4abc5ec2c5c7a18388a902e33a840bf3c75730ef3
    output htlc_timeout_tx 3: 02000000000101f265406b0ee3eb37ab6e365862228fbadd762567f1d1be612a9f749558663f86010000000000000000010906000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402205d8ea2626a999f65be5ebf02c40ece3fd2125fa3a91f5b13d6b279ef268ccec302207a5ee61665a98d54553ea59500824ace572793d1b1e0184662b14ad41f2f9da801483045022100da33bbef961e5c52f047edbeb63a6896f0a59127d9e0a0d3a304f7c4dab0f001022043ada6b2f93be37cb94a1fb4abc5ec2c5c7a18388a902e33a840bf3c75730ef301006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6823a10700
    # local_signature = 3045022100e90a02bd620dfc64ecd0dd686622528242901a9fcfa47aaa15c71f543ec1bf0c02205138b5a0f5dd9f7ae8cf3232cb39ddb9df1c5a5e18d636a39cfd03fee906a4ca
    output htlc_success_tx 4: 02000000000101f265406b0ee3eb37ab6e365862228fbadd762567f1d1be612a9f749558663f8602000000000000000001f109000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba05004830450221008e3dbd9c55361d0ec192fc1406192c31b4062c6decfb1f0118e889f169c27a4a022047d1e5c70f23fd1f8b0027504d565875ff18795afa4027bff9de3b5b9652755301483045022100e90a02bd620dfc64ecd0dd686622528242901a9fcfa47aaa15c71f543ec1bf0c02205138b5a0f5dd9f7ae8cf3232cb39ddb9df1c5a5e18d636a39cfd03fee906a4ca012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2294
    # base commitment transaction fee = 2844
    # HTLC offered amount 2000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6985156 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100ae45b846cdeb8ba8140bec0584662013005622db4a9e73f99693c6474e22d24202201086ece2dc0619d96c8d05b62b23f01a8ae34f1923f2b0a26aa6805cbd61f18b
    # local_signature = 3044022048c6a9e633af4b0228334f81ab13d6cac704fe4b6b2d189c07922b7a10332e31022049612a801e3ae0fd1cab4b8ef4058357aa32775a1c848110d07c820f8b3f43ef
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8005d0070000000000002200201e918f414255792d26e3ce43c578c1dfcc5492179dc802ff8adc0c8492afd7f2b80b000000000000220020745b4bf58775220540a3f2ae17a926a69d39f82da7a2257d463c9ccdab3d5c4ca00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036c4956a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0400473044022048c6a9e633af4b0228334f81ab13d6cac704fe4b6b2d189c07922b7a10332e31022049612a801e3ae0fd1cab4b8ef4058357aa32775a1c848110d07c820f8b3f43ef01483045022100ae45b846cdeb8ba8140bec0584662013005622db4a9e73f99693c6474e22d24202201086ece2dc0619d96c8d05b62b23f01a8ae34f1923f2b0a26aa6805cbd61f18b01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 304402203200d5276ca101cfbf3d3a062ef73c0db26f9ceea27e31c962dfe84476ddbc8702203fdd1aafd64ff98814914a49f75cadab7fa111834a282945038e5e4417fcf338
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 3044022054302900e64585286b1fb46269a36e4bcd32c2030a7e6fb02023e9f17fef3f8502206fde54ddc5757213834b1deb9d8e42946d442a4394d6de5ef1db5c113bab258c
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 304402201471cf006c8b38f2d3288f83a8825b0cb19e1b3c82f99495512ef71047c8e43402205d398accb039a3742515df7481cf85687db794295415f5638974c3c7b29506ce
    # local_signature = 304402205fedaac342af1cf6abfbdefda4bff9528fce5841282aaf761ebed874082c609b0220321779e191350ef5688ceac9a52094654af2f02d2af36b90fe4a8531620b61cf
    output htlc_timeout_tx 2: 02000000000101ea6cd61d4ea8bb748d046b8af4fc2e319b0fb3cacc2829dff8fc53bb859909ef00000000000000000001cd01000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402203200d5276ca101cfbf3d3a062ef73c0db26f9ceea27e31c962dfe84476ddbc8702203fdd1aafd64ff98814914a49f75cadab7fa111834a282945038e5e4417fcf3380147304402205fedaac342af1cf6abfbdefda4bff9528fce5841282aaf761ebed874082c609b0220321779e191350ef5688ceac9a52094654af2f02d2af36b90fe4a8531620b61cf01006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6822a10700
    # local_signature = 304402205afdc7972ddfb7b66825c1cca7b1bd0381f02f58071ad5b6f0291a5fe81cb62302205d63388f68668272e286d1d09d377add657e9ea1f08b2eaadf021e094fc50d78
    output htlc_timeout_tx 3: 02000000000101ea6cd61d4ea8bb748d046b8af4fc2e319b0fb3cacc2829dff8fc53bb859909ef01000000000000000001b505000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500473044022054302900e64585286b1fb46269a36e4bcd32c2030a7e6fb02023e9f17fef3f8502206fde54ddc5757213834b1deb9d8e42946d442a4394d6de5ef1db5c113bab258c0147304402205afdc7972ddfb7b66825c1cca7b1bd0381f02f58071ad5b6f0291a5fe81cb62302205d63388f68668272e286d1d09d377add657e9ea1f08b2eaadf021e094fc50d7801006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6823a10700
    # local_signature = 304402200f1f1786d9c3f7fd65bba961b698201e12b59704936cfa6eefe23f359be4990d022053cc3551678dd3cb1c5f28d97af4c982550f5cd535319500338335cdd242d63f
    output htlc_success_tx 4: 02000000000101ea6cd61d4ea8bb748d046b8af4fc2e319b0fb3cacc2829dff8fc53bb859909ef020000000000000000019d09000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402201471cf006c8b38f2d3288f83a8825b0cb19e1b3c82f99495512ef71047c8e43402205d398accb039a3742515df7481cf85687db794295415f5638974c3c7b29506ce0147304402200f1f1786d9c3f7fd65bba961b698201e12b59704936cfa6eefe23f359be4990d022053cc3551678dd3cb1c5f28d97af4c982550f5cd535319500338335cdd242d63f012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2295
    # base commitment transaction fee = 2451
    # HTLC offered amount 3000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6985549 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100e9605a4ef8cfb0be6b16c553836b428b0a3d1fd5dc8950f1090f78796b3a301f02202e19495c268c6ae6b1823d7679b2336f8f52bab499636e288733e122a758e9ff
    # local_signature = 304402207ed562646a36e85484d126b96fd5d7e033e1be0d0a7a7af5a2aa7c7c5c057c7202207693ef8431999f6c699b9a7fb69d32e44541547ab8008fd85b2f5cd776c58294
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8004b80b000000000000220020745b4bf58775220540a3f2ae17a926a69d39f82da7a2257d463c9ccdab3d5c4ca00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0364d976a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba040047304402207ed562646a36e85484d126b96fd5d7e033e1be0d0a7a7af5a2aa7c7c5c057c7202207693ef8431999f6c699b9a7fb69d32e44541547ab8008fd85b2f5cd776c5829401483045022100e9605a4ef8cfb0be6b16c553836b428b0a3d1fd5dc8950f1090f78796b3a301f02202e19495c268c6ae6b1823d7679b2336f8f52bab499636e288733e122a758e9ff01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 304502210095a47ac775231b7a58d8577e088e34e2eea397fd828e2ca8e4c9873560c5d02602206fe5b48d0fdff39b44a57815f079c50780718209eacb509f50eb39a02d59de90
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 3045022100e116948cb6762197889cec1edab0dbb3b5b99b88408b567452c55154d4ec4de1022020fca7ce152fa9bb2b1d3e99932b5999c58bd2f4b706ac3846007b069b832722
    # local_signature = 3044022020050070a90374cda3625ef4a52c97d7035a71ea86b2f0dda2d233379052b54a02200bce9a938da93dc5287d4e656b60648022b6783b20203ca30e8290af759957dc
    output htlc_timeout_tx 3: 020000000001015ce7fb29feafef7e2d739579425422776681ac23619659b7da303c2ec438d34300000000000000000001b505000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050048304502210095a47ac775231b7a58d8577e088e34e2eea397fd828e2ca8e4c9873560c5d02602206fe5b48d0fdff39b44a57815f079c50780718209eacb509f50eb39a02d59de9001473044022020050070a90374cda3625ef4a52c97d7035a71ea86b2f0dda2d233379052b54a02200bce9a938da93dc5287d4e656b60648022b6783b20203ca30e8290af759957dc01006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6823a10700
    # local_signature = 3045022100e12aa73f78a1a3232b81a1729d2db07aecdea61f6ba41301f61847712823b2da02200822d900c1064e6a56bac6618709a04cd05c0ca14aaab3bed6d81be2128c2d69
    output htlc_success_tx 4: 020000000001015ce7fb29feafef7e2d739579425422776681ac23619659b7da303c2ec438d343010000000000000000019d09000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500483045022100e116948cb6762197889cec1edab0dbb3b5b99b88408b567452c55154d4ec4de1022020fca7ce152fa9bb2b1d3e99932b5999c58bd2f4b706ac3846007b069b83272201483045022100e12aa73f78a1a3232b81a1729d2db07aecdea61f6ba41301f61847712823b2da02200822d900c1064e6a56bac6618709a04cd05c0ca14aaab3bed6d81be2128c2d69012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3872
    # base commitment transaction fee = 4135
    # HTLC offered amount 3000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c820120876475527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6983865 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402206e9d8a6d39a7ec84e150db616764c80104e0c11ee66b7f2ab80ea410c29c8c1e02200285517a05f2aad6a8b626a849bbb8364599704f438e7c250467440de0ef5050
    # local_signature = 3045022100b50d7f38ce8c6dc7429c5b6372f1527f315b4bf0fefee6389990f670bc8ed4f2022041e29889dfaa8960fd7916e7d2be276b66b58cd8b2ab220f6b46ed069def47d3
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8004b80b000000000000220020745b4bf58775220540a3f2ae17a926a69d39f82da7a2257d463c9ccdab3d5c4ca00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036b9906a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0400483045022100b50d7f38ce8c6dc7429c5b6372f1527f315b4bf0fefee6389990f670bc8ed4f2022041e29889dfaa8960fd7916e7d2be276b66b58cd8b2ab220f6b46ed069def47d30147304402206e9d8a6d39a7ec84e150db616764c80104e0c11ee66b7f2ab80ea410c29c8c1e02200285517a05f2aad6a8b626a849bbb8364599704f438e7c250467440de0ef505001475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3045022100eba60d565833f632718a2357e548209735c89d49e426e5442156df9468cd7fd102200ee5ffe504dd0a8d83bbca18298f0842b0ff7f49fac47a3e9a697cb6e454cbe4
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 3045022100ef6ef748eb50b14f081a191cd5f07f051019bc9263f50ca9c35ec7cc67194b5702200d51d4258f749a9bcd3befbd474fea0456fe8f0f8f6182e70e853409426f6f99
    # local_signature = 3045022100a23d210ce374b0198deda3817c2df48b3a1341c5918be0f288d11770f39526bf02203f6c0ae0180bd8689f27dbc94275aa894aa0b939529e8b3d41bc63c491f269a5
    output htlc_timeout_tx 3: 020000000001017783afbd3fd5427ab3382b207487e6a94d874b19d58a870fc2971513f6735951000000000000000000019201000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500483045022100eba60d565833f632718a2357e548209735c89d49e426e5442156df9468cd7fd102200ee5ffe504dd0a8d83bbca18298f0842b0ff7f49fac47a3e9a697cb6e454cbe401483045022100a23d210ce374b0198deda3817c2df48b3a1341c5918be0f288d11770f39526bf02203f6c0ae0180bd8689f27dbc94275aa894aa0b939529e8b3d41bc63c491f269a501006d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6823a10700
    # local_signature = 3045022100e3112720bd7c36a82cff4cd4a6eb5bc03777474e170fbdcf742afb75535b47ee02201767a1fd4095037ebacde1484f1417b6f94286527509b4ecb4e01e69ee23cbdd
    output htlc_success_tx 4: 020000000001017783afbd3fd5427ab3382b207487e6a94d874b19d58a870fc2971513f6735951010000000000000000017a05000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0500483045022100ef6ef748eb50b14f081a191cd5f07f051019bc9263f50ca9c35ec7cc67194b5702200d51d4258f749a9bcd3befbd474fea0456fe8f0f8f6182e70e853409426f6f9901483045022100e3112720bd7c36a82cff4cd4a6eb5bc03777474e170fbdcf742afb75535b47ee02201767a1fd4095037ebacde1484f1417b6f94286527509b4ecb4e01e69ee23cbdd012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3873
    # base commitment transaction fee = 3470
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6984530 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402201464cb566b6e388e3391195ee8c2b6d31debbc9ad67c7d7bd49b377adb578ea302200370de135558dba1656e11c1813318bd35f3df7cb6f9e99d7ee9413428f83084
    # local_signature = 304402206ee5d5bd861ed806c9edd43091fbf0af70d1b528354d0769f9d7f93b83b453630220750995c401044f12a4d93ebd09f83989baefb411932915db56527d99a91a626d
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8003a00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03652936a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba040047304402206ee5d5bd861ed806c9edd43091fbf0af70d1b528354d0769f9d7f93b83b453630220750995c401044f12a4d93ebd09f83989baefb411932915db56527d99a91a626d0147304402201464cb566b6e388e3391195ee8c2b6d31debbc9ad67c7d7bd49b377adb578ea302200370de135558dba1656e11c1813318bd35f3df7cb6f9e99d7ee9413428f8308401475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 304402207da27c3f00980b8e9dfe24a26e888ebc252602d5667c6a3e5525e4912cad588302200c27c1854971f1890ef1b6d6973dbc67ffd5b07f448e5f52d62b7db81a4bcc54
    # local_signature = 3045022100a8ec8f2b1597abd81c78b1e68f2322bf4142a287baa5e112b479ab92d2c26e280220263d1e2b4b376d08ea0badbd48e1946064ad055341c968fd146ee77f29805328
    output htlc_success_tx 4: 0200000000010192ed41bf58ca076e0b109203a0360480dc03cce34f8a427a2f9892042c9d45a4000000000000000000017a05000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402207da27c3f00980b8e9dfe24a26e888ebc252602d5667c6a3e5525e4912cad588302200c27c1854971f1890ef1b6d6973dbc67ffd5b07f448e5f52d62b7db81a4bcc5401483045022100a8ec8f2b1597abd81c78b1e68f2322bf4142a287baa5e112b479ab92d2c26e280220263d1e2b4b376d08ea0badbd48e1946064ad055341c968fd146ee77f29805328012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5149
    # base commitment transaction fee = 4613
    # HTLC received amount 4000 wscript 21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e77c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac87852ae67750190b175ac68
    # to-local amount 6983387 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100dca4a9dc6a1e725613ace6eb0c680985281b8e42156b34ff40c605972c4d8a9e022013713c1dc3588f0387c25117da1501c1145a3399a0e4a07567bd12359f008735
    # local_signature = 3045022100ca252149de81e1af536d90e0b6ccbcddcb4f86e46b40ef282f8febaedcafdbcf0220031bbdaad9df1208455e6ce195ae7f5877c0f41ef161ea1f636ffe850c715f2c
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8003a00f00000000000022002004043762d271057eb218a5bd80c380463ab573e6849bb2e2e6a6e4570686ec6bc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036db8e6a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba0400483045022100ca252149de81e1af536d90e0b6ccbcddcb4f86e46b40ef282f8febaedcafdbcf0220031bbdaad9df1208455e6ce195ae7f5877c0f41ef161ea1f636ffe850c715f2c01483045022100dca4a9dc6a1e725613ace6eb0c680985281b8e42156b34ff40c605972c4d8a9e022013713c1dc3588f0387c25117da1501c1145a3399a0e4a07567bd12359f00873501475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 304402202db2ebaae11b1a7c2eb9227e6fbfb360a6074c755fdab102d7b2b68a85ab00990220685f5700015b2e312768220c098cc069a0ff356afcaeaf65cf9e94cf81791ac5
    # local_signature = 3045022100fc79604e9379412d6a6ec7921e38107e40c610cf69eaa2fbd0989ede9581db520220376b8d1143787d0697e63a7e85302ffc9861c567f7ee29989f0e4b7c6923916f
    output htlc_success_tx 4: 02000000000101d238e3c4451861683115318783419da9900c53bb805765dfe6204b2da3e07906000000000000000000012102000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba050047304402202db2ebaae11b1a7c2eb9227e6fbfb360a6074c755fdab102d7b2b68a85ab00990220685f5700015b2e312768220c098cc069a0ff356afcaeaf65cf9e94cf81791ac501483045022100fc79604e9379412d6a6ec7921e38107e40c610cf69eaa2fbd0989ede9581db520220376b8d1143787d0697e63a7e85302ffc9861c567f7ee29989f0e4b7c6923916f012004040404040404040404040404040404040404040404040404040404040404046d21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67750190b175ac6800000000
    
    name: commitment tx with 2 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5150
    # base commitment transaction fee = 3728
    # to-local amount 6984272 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022041ccf144a130316ae78299ea206dde3bddb7fe4c0ab12a496fa1d614245077b70220691e33980cf7b7a6103bc3c9f83ea6829b9fdea0348b0b6fb53eace41dae147f
    # local_signature = 304402207fe8bd16423edd49e6b6629e1ad22d124bc6b88a26472ed6d2d3b8808e3db2470220687675bb856fde5a9cd297c1542c8139211929ed7a50ba21cb61fcc84881ee70
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03650926a0000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acba040047304402207fe8bd16423edd49e6b6629e1ad22d124bc6b88a26472ed6d2d3b8808e3db2470220687675bb856fde5a9cd297c1542c8139211929ed7a50ba21cb61fcc84881ee7001473044022041ccf144a130316ae78299ea206dde3bddb7fe4c0ab12a496fa1d614245077b70220691e33980cf7b7a6103bc3c9f83ea6829b9fdea0348b0b6fb53eace41dae147f01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with 2 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651180
    # base commitment transaction fee = 6987454
    # to-local amount 546 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19670190b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022054168140084bb59f5036b7f61457be7cf9915faf426c5f48bbb117740062a4df022052efbae4430eaf72092c6f57e6a59d89bd32dfcbdacf6f079c87d92ce8b90677
    # local_signature = 3045022100b597c44b770fbc2fbf3656af5cf2dfad13c45e2a9204d10cba6518e78845041f022059b1dfc46dafa54bc24a869b2704911398e20210cd8486b44894ad1093d9a985
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b80022202000000000000220020b736bcf56020e73439245b2d13ef024ac9d1eaf802616d82cedeae33ecd7acbac0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0360400483045022100b597c44b770fbc2fbf3656af5cf2dfad13c45e2a9204d10cba6518e78845041f022059b1dfc46dafa54bc24a869b2704911398e20210cd8486b44894ad1093d9a98501473044022054168140084bb59f5036b7f61457be7cf9915faf426c5f48bbb117740062a4df022052efbae4430eaf72092c6f57e6a59d89bd32dfcbdacf6f079c87d92ce8b9067701475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with 1 output untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651181
    # base commitment transaction fee = 6987455
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100dc0d223b65e0a38830aa4b93c4a5f5b8d0d061839ec3d4ddec3d1f7a435969e30220351ec01ab46ab526b4d4f220e32410f36a1ba32d7078e9b7ddf7f61ae21c1dcd
    # local_signature = 30450221009ab8ff2d8fb67fdd436c908752e81cf3d55dcc38d85e03b68b4233733149273202206a3126124d92b29280d014087d9770f8bde4f9d57a65a63fb9205e4e6c125daa
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8001c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03604004830450221009ab8ff2d8fb67fdd436c908752e81cf3d55dcc38d85e03b68b4233733149273202206a3126124d92b29280d014087d9770f8bde4f9d57a65a63fb9205e4e6c125daa01483045022100dc0d223b65e0a38830aa4b93c4a5f5b8d0d061839ec3d4ddec3d1f7a435969e30220351ec01ab46ab526b4d4f220e32410f36a1ba32d7078e9b7ddf7f61ae21c1dcd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with fee greater than funder amount
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651936
    # base commitment transaction fee = 6988001
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100dc0d223b65e0a38830aa4b93c4a5f5b8d0d061839ec3d4ddec3d1f7a435969e30220351ec01ab46ab526b4d4f220e32410f36a1ba32d7078e9b7ddf7f61ae21c1dcd
    # local_signature = 30450221009ab8ff2d8fb67fdd436c908752e81cf3d55dcc38d85e03b68b4233733149273202206a3126124d92b29280d014087d9770f8bde4f9d57a65a63fb9205e4e6c125daa
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8001c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03604004830450221009ab8ff2d8fb67fdd436c908752e81cf3d55dcc38d85e03b68b4233733149273202206a3126124d92b29280d014087d9770f8bde4f9d57a65a63fb9205e4e6c125daa01483045022100dc0d223b65e0a38830aa4b93c4a5f5b8d0d061839ec3d4ddec3d1f7a435969e30220351ec01ab46ab526b4d4f220e32410f36a1ba32d7078e9b7ddf7f61ae21c1dcd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

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

