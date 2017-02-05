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

# Appendix C: Funding Transaction Test Vectors

In the following:
 - we assume that *local* is the funder
 - private keys are displayed as 32 bytes plus a trailing 1 (bitcoin's convention for "compressed" private keys, i.e. keys for which the public key is compressed)
 - transaction signatures are all deterministic, using RFC6979 (using HMAC-SHA256)

The input for the funding transaction was created using a test chain
with the following first two blocks, the second one with a spendable
coinbase:

    Block 0: 0000002006226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910ff9890709ca11e62b57183010e07d1c84aaa1cebbf0f20d8b1dc9ead01613966e1ecc9358ffff7f20020000000101000000010000000000000000000000000000000000000000000000000000000000000000ffffffff03510101ffffffff0100f2052a010000002321032e57ef0ffb715b021124682754110ef749029648f457ded64dd3583e647dd248ac00000000
    Block 1: 000000208d73f5cc72d40cc8e824947ea0ad2e5717daf246adec336f82fb701c135eb8535835f3d32a88faeb8b6af4ed6fdb73774121c62227bf7038f702ee3efb7baa8832cc9358ffff7f20010000000101000000010000000000000000000000000000000000000000000000000000000000000000ffffffff03520101ffffffff0100f2052a010000001976a9143ca33c2e4446f4a305f23c80df8ad1afdcf652f988ac00000000
    Block 1 coinbase transaction: 01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff03520101ffffffff0100f2052a010000001976a9143ca33c2e4446f4a305f23c80df8ad1afdcf652f988ac00000000
    Block 1 coinbase privkey: 6bd078650fcee8444e4e09825227b801a1ca928debb750eb36e6d56124bb20e80101
    # privkey in base58: cRCH7YNcarfvaiY1GWUKQrRGmoezvfAiqHtdRvxe16shzbd7LDMz

The funding transaction is paid to the following keys:

    local_funding_pubkey: 023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb
    remote_funding_pubkey: 030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c1
    # funding witness script = 5221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae

The funding transaction has a single input, and a change output (order
determined by BIP69 in this case):

    input txid: 5835f3d32a88faeb8b6af4ed6fdb73774121c62227bf7038f702ee3efb7baa88
    input[0] input: 0
    input[0] satoshis: 5000000000
    funding satoshis: 10000000
    # feerate_per_kw: 15000
    change satoshis: 4989986080
    funding output: 0

The resulting funding transaction is:

    funding tx: 02000000015835f3d32a88faeb8b6af4ed6fdb73774121c62227bf7038f702ee3efb7baa88000000006b483045022100b1b6bec46e4a4a085cdb38ec23a7ff58ef33d05282bef9e527f4ffb8385c548b022041cafe51b5df61b659c11f1cc22e8d22a5f0c12798754b1351b61ed57d7e1f2c012103535b32d5eb0a6ed0982a0479bbadc9868d9836f6ba94dd5a63be16d875069184ffffffff028096980000000000220020c015c4a6be010e21657068fc2e6a9d02b27ebe4d490a25846f7237f104d1a3cd20256d29010000001600143ca33c2e4446f4a305f23c80df8ad1afdcf652f900000000
    # txid: 1487eaf006bf446e96e195d9482d9cd92a575a15819cba95520b71849f21318c

# Appendix C: Commitment and HTLC Transaction Test Vectors

In the following:
 - we consider *local* transactions, which implies that all payments to *local* are delayed
 - we assume that *local* is the funder
 - private keys are displayed as 32 bytes plus a trailing 1 (bitcoin's convention for "compressed" private keys, i.e. keys for which the public key is compressed)
 - transaction signatures are all deterministic, using RFC6979 (using HMAC-SHA256)

We start by defining common basic parameters for each test vector: the
HTLCs are not used for the first "simple commitment tx with no HTLCs" test.

    funding_tx_hash: 1487eaf006bf446e96e195d9482d9cd92a575a15819cba95520b71849f21318c
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
    remote_signature = 3044022017744823a5fc7e8b186f515ee34bfd6cc6c78184c1c25af1f55bbb99063d6e67022013a4fe3aa1bd456d2a4147332c34d34f2809a707231ca85c66722cf18e28b8d5
    # local_signature = 3044022100f516a394d379e49dcc71b97f63fb2eb008a0b1a6b28f1338db367cf8e7e77339021f7aacbb329a945b01975112b5e9afa05b8be021adb627b73d846b604d16dc3a
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03654a56a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022100f516a394d379e49dcc71b97f63fb2eb008a0b1a6b28f1338db367cf8e7e77339021f7aacbb329a945b01975112b5e9afa05b8be021adb627b73d846b604d16dc3a01473044022017744823a5fc7e8b186f515ee34bfd6cc6c78184c1c25af1f55bbb99063d6e67022013a4fe3aa1bd456d2a4147332c34d34f2809a707231ca85c66722cf18e28b8d501475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
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
    remote_signature = 3045022100b0d591a8dff945eae569c3d1a5f6187087180c7e681873173197a78970b625c102204edd1269dc0df167cf1528846895d9a48de34acd1edb20985eba7c9f48f13a7d
    # local_signature = 304402202787e564d921d5f2bd1481533a29a2dd7e0f8d3ea93da16cf2a14de0ec6de7ee02200495bf4403a0af3967cff8bc5330c67f8334176675009ed54c621460434c6410
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8007e80300000000000022002070b024855cc882f19cadb563400cb24cc07987c917daf702bb5b2e6f52e04318d0070000000000002200204117dad487a3c3bc07e34db505d567fcc263b30075f0b4679a1b27c297b4b147d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036e0a06a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402202787e564d921d5f2bd1481533a29a2dd7e0f8d3ea93da16cf2a14de0ec6de7ee02200495bf4403a0af3967cff8bc5330c67f8334176675009ed54c621460434c641001483045022100b0d591a8dff945eae569c3d1a5f6187087180c7e681873173197a78970b625c102204edd1269dc0df167cf1528846895d9a48de34acd1edb20985eba7c9f48f13a7d01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 3044022065c1a67257255e24380d0fc7feea6655a2cb84c1135cbbc77188fac6e4e9878c0220245666ec22d9850a2a7989d64310cda4a1c0980a678effbce54d7b48d1d7c82a
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 3045022100f8151fe27f75e7f939a3f3e67bc71d1378a1a300b5a247ebf695c8953e0f7f6d02200263612f6173b6b0db8ec04d8a6254ca879dbba3bab5a23456bbbee2e845824d
    # signature for output 2 (htlc 2)
    remote_htlc_signature = 3045022100e52052d6b8abbc7a1f20be519b71c857f1d78211c8e19c56a39ce360a11e6e4702202cdfcf94ca907061bc793dba987f9194bb9382d7eec16db0b9feea46c17f9d07
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 3044022062287a6cc7905bbb43306f83b7147d105b2756cae3633894eb23897c9027f87e02200a70f3a3f7b77106d5e2b6eeca73d18ae25b555c44e21b27e21433eb7b59f6e1
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 3045022100f4b606f1ed5a464f51cf09df544c012a24be5c409ee9de07aa00179a72ec127c02202524d28fd6126d8b9167b4cb783ee5534c3c324796343ff99c0e1da6840c23cd
    # local_signature = 30440220432622cd5312de85f5d97ecd569e2e43957c9ce0c5202b1c2de935f96a6bbedf02207219127c8bee7862acdb1f9393899749afc6065c10d33e095c06a153bef7fa3a
    output htlc_success_tx 0: 02000000000101f8899e08a7de3d96c7dc2f2cf17ac97ed9c1769461ff2a49b2cd26f0e3346f5800000000000000000001e8030000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022065c1a67257255e24380d0fc7feea6655a2cb84c1135cbbc77188fac6e4e9878c0220245666ec22d9850a2a7989d64310cda4a1c0980a678effbce54d7b48d1d7c82a014730440220432622cd5312de85f5d97ecd569e2e43957c9ce0c5202b1c2de935f96a6bbedf02207219127c8bee7862acdb1f9393899749afc6065c10d33e095c06a153bef7fa3a012000000000000000000000000000000000000000000000000000000000000000006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac6800000000
    # local_signature = 3044022050cb3317bc1474c781c4d465e86c0394142bce4edefe1bbf0834672e7ae9786e02204c6b16e6bb283f54aafd639c09515268e445845b703d3ab3cca3062d29d828ab
    output htlc_success_tx 1: 02000000000101f8899e08a7de3d96c7dc2f2cf17ac97ed9c1769461ff2a49b2cd26f0e3346f5801000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f8151fe27f75e7f939a3f3e67bc71d1378a1a300b5a247ebf695c8953e0f7f6d02200263612f6173b6b0db8ec04d8a6254ca879dbba3bab5a23456bbbee2e845824d01473044022050cb3317bc1474c781c4d465e86c0394142bce4edefe1bbf0834672e7ae9786e02204c6b16e6bb283f54aafd639c09515268e445845b703d3ab3cca3062d29d828ab012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 304402205ff9b02dbe661c4d6f09ae2e01e105f65b3abe3f131901307560eb506bb0862e0220057a8733da0da1d335ccd5c61fc0711426fc2a8a1599705211890dc86ab5390d
    output htlc_timeout_tx 2: 02000000000101f8899e08a7de3d96c7dc2f2cf17ac97ed9c1769461ff2a49b2cd26f0e3346f5802000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e52052d6b8abbc7a1f20be519b71c857f1d78211c8e19c56a39ce360a11e6e4702202cdfcf94ca907061bc793dba987f9194bb9382d7eec16db0b9feea46c17f9d070147304402205ff9b02dbe661c4d6f09ae2e01e105f65b3abe3f131901307560eb506bb0862e0220057a8733da0da1d335ccd5c61fc0711426fc2a8a1599705211890dc86ab5390d01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3045022100a2cf4f657a89ed09636e7097b61dbdf8c9a509e51cb29bd3a89bd4cf6ca261c602204b1dc50a23fc29b4910d558b2f75dfd74d6b81ca7f972a144210b3fa9307613a
    output htlc_timeout_tx 3: 02000000000101f8899e08a7de3d96c7dc2f2cf17ac97ed9c1769461ff2a49b2cd26f0e3346f5803000000000000000001b80b0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022062287a6cc7905bbb43306f83b7147d105b2756cae3633894eb23897c9027f87e02200a70f3a3f7b77106d5e2b6eeca73d18ae25b555c44e21b27e21433eb7b59f6e101483045022100a2cf4f657a89ed09636e7097b61dbdf8c9a509e51cb29bd3a89bd4cf6ca261c602204b1dc50a23fc29b4910d558b2f75dfd74d6b81ca7f972a144210b3fa9307613a01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100d5210412b3703910ca5302a90066d4240ad786aa2cdcaadd872d152279abc69502205774bc3a3a1e5bfa8ace974037fd40c1261f3df03c4b40dc1b2349c7f2d00963
    output htlc_success_tx 4: 02000000000101f8899e08a7de3d96c7dc2f2cf17ac97ed9c1769461ff2a49b2cd26f0e3346f5804000000000000000001a00f0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f4b606f1ed5a464f51cf09df544c012a24be5c409ee9de07aa00179a72ec127c02202524d28fd6126d8b9167b4cb783ee5534c3c324796343ff99c0e1da6840c23cd01483045022100d5210412b3703910ca5302a90066d4240ad786aa2cdcaadd872d152279abc69502205774bc3a3a1e5bfa8ace974037fd40c1261f3df03c4b40dc1b2349c7f2d00963012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
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
    remote_signature = 3045022100f87d3f250e495bdc89f4e5a50f3e4de7875d66340694d0454bdf66c30b60829f022043acf1c7b5c86ca6da9609f64048a0c4ef3e943b79f90312cc4f1522bde1fea3
    # local_signature = 30450221008151b2dd7f13dd1d0a524fb361cfaa543dfdabdb592bad6ce351697f7e1bb85202201b9d890908628a604f7b083f50b49a13c8df331c841068b9c208d95e8efa5974
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8007e80300000000000022002070b024855cc882f19cadb563400cb24cc07987c917daf702bb5b2e6f52e04318d0070000000000002200204117dad487a3c3bc07e34db505d567fcc263b30075f0b4679a1b27c297b4b147d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036af9c6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004830450221008151b2dd7f13dd1d0a524fb361cfaa543dfdabdb592bad6ce351697f7e1bb85202201b9d890908628a604f7b083f50b49a13c8df331c841068b9c208d95e8efa597401483045022100f87d3f250e495bdc89f4e5a50f3e4de7875d66340694d0454bdf66c30b60829f022043acf1c7b5c86ca6da9609f64048a0c4ef3e943b79f90312cc4f1522bde1fea301475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 3045022100d3ddd3a5a118bee615de898888725949c1e22590b09e5c10d4cd2da818d3e7a6022061df3ef77ddd5e5c5b7ba8e1b0f9aa755580402ac73c51716d0e58d619c0401e
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 3045022100cba06bbdd586bae81750902a5617fdb0d160f04f5d0f55302fabea8596c6f4240220668859f2d01c34f06794a521bb1fb3755ef40488ebb92ffba5531a8c3f56afee
    # signature for output 2 (htlc 2)
    remote_htlc_signature = 3045022100de05230e8799c6360b1e54a13ef970637020010e1b691fa303fae675c2ea48dc02202dad7cfdbf70430b5d79beb6b170970977a90c34e0a356387a0eaac263d39ff7
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 304502210088e45e606180084293dfe4885058ac8cdefe5a679b74ebec4c559cf30fdca28e02201abf2224a59c5d909eddfa35ffe5eeebff55b69e9722b1c07b72066a36047497
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 3045022100f65f24f75383cfe95223836c9a2d0db9792fb1c828bfa06795295b88c1d522040220099a0789d084f80977959559c5c27e6b2ab9bb365b4bb6325dcd676ec8392a93
    # local_signature = 3045022100bf6c1ce0634e888f45ace61f1d975bf9771a1066732e7ca4af44abe2c300534c02203dc8f884979a4747fd08b1555142e4bbba3c36f2301392134d1b8650ce56be32
    output htlc_success_tx 0: 020000000001014c3e5858f59ab4e857f82ef0593d0399b4c8eec2e52f3cb057d6c6e91b0ed9930000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d3ddd3a5a118bee615de898888725949c1e22590b09e5c10d4cd2da818d3e7a6022061df3ef77ddd5e5c5b7ba8e1b0f9aa755580402ac73c51716d0e58d619c0401e01483045022100bf6c1ce0634e888f45ace61f1d975bf9771a1066732e7ca4af44abe2c300534c02203dc8f884979a4747fd08b1555142e4bbba3c36f2301392134d1b8650ce56be32012000000000000000000000000000000000000000000000000000000000000000006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac6800000000
    # local_signature = 3045022100f9c196c41995206b979083a82b7edb57ea120eeaeb86e1358071cff73769bc3c02200999554d8a4b948830eed2656c55f0f2e1074e74e439bd8d5f6c4ba8dae09ec7
    output htlc_success_tx 1: 020000000001014c3e5858f59ab4e857f82ef0593d0399b4c8eec2e52f3cb057d6c6e91b0ed9930100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100cba06bbdd586bae81750902a5617fdb0d160f04f5d0f55302fabea8596c6f4240220668859f2d01c34f06794a521bb1fb3755ef40488ebb92ffba5531a8c3f56afee01483045022100f9c196c41995206b979083a82b7edb57ea120eeaeb86e1358071cff73769bc3c02200999554d8a4b948830eed2656c55f0f2e1074e74e439bd8d5f6c4ba8dae09ec7012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3045022100c48789347c9389da75d1cd64525485302e0d68fa472dcd59f39c39eb40d7f43e02202097f8a076ab111b9401b36a859afa79f0adb0fb98264008d19c777976519473
    output htlc_timeout_tx 2: 020000000001014c3e5858f59ab4e857f82ef0593d0399b4c8eec2e52f3cb057d6c6e91b0ed9930200000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100de05230e8799c6360b1e54a13ef970637020010e1b691fa303fae675c2ea48dc02202dad7cfdbf70430b5d79beb6b170970977a90c34e0a356387a0eaac263d39ff701483045022100c48789347c9389da75d1cd64525485302e0d68fa472dcd59f39c39eb40d7f43e02202097f8a076ab111b9401b36a859afa79f0adb0fb98264008d19c77797651947301006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3045022100cb5118acdf45ebd4c2ef84ad992cdac7c081378fbab1e4ddc8dc708abed393f302204543aea8a711bdb7c7e87d9cb53c2913eecc5fb88913d57f08222f80f127d683
    output htlc_timeout_tx 3: 020000000001014c3e5858f59ab4e857f82ef0593d0399b4c8eec2e52f3cb057d6c6e91b0ed99303000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050048304502210088e45e606180084293dfe4885058ac8cdefe5a679b74ebec4c559cf30fdca28e02201abf2224a59c5d909eddfa35ffe5eeebff55b69e9722b1c07b72066a3604749701483045022100cb5118acdf45ebd4c2ef84ad992cdac7c081378fbab1e4ddc8dc708abed393f302204543aea8a711bdb7c7e87d9cb53c2913eecc5fb88913d57f08222f80f127d68301006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3044022044d3dc2523bd2178adef486565209651a1496332dde60fa9110d5b79cd9ccbc002205c89679d268790098ac2e20bea43e4a12c2bbecb88adca81a2938b201fcbbdf0
    output htlc_success_tx 4: 020000000001014c3e5858f59ab4e857f82ef0593d0399b4c8eec2e52f3cb057d6c6e91b0ed99304000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f65f24f75383cfe95223836c9a2d0db9792fb1c828bfa06795295b88c1d522040220099a0789d084f80977959559c5c27e6b2ab9bb365b4bb6325dcd676ec8392a9301473044022044d3dc2523bd2178adef486565209651a1496332dde60fa9110d5b79cd9ccbc002205c89679d268790098ac2e20bea43e4a12c2bbecb88adca81a2938b201fcbbdf0012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
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
    remote_signature = 304402204d4545221bd12ebb7f6c44af91c34871311c8f2caf055c85a6b148b3a89c7fcd0220138b54de41a53ab565f8f84e2baeb0412ca2f4634cc4b063d3e2100f016f8261
    # local_signature = 304402204e8b06b179bdc257d898edd1faef2c96440842182eb997fe04fc7f170d89f1260220180c1805c311efbe1229c4be3a153ed68b1fd347deab6e00082a7d159b448b95
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8006d0070000000000002200204117dad487a3c3bc07e34db505d567fcc263b30075f0b4679a1b27c297b4b147d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036229d6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402204e8b06b179bdc257d898edd1faef2c96440842182eb997fe04fc7f170d89f1260220180c1805c311efbe1229c4be3a153ed68b1fd347deab6e00082a7d159b448b950147304402204d4545221bd12ebb7f6c44af91c34871311c8f2caf055c85a6b148b3a89c7fcd0220138b54de41a53ab565f8f84e2baeb0412ca2f4634cc4b063d3e2100f016f826101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 1)
    remote_htlc_signature = 30450221008723f10cf5504104eae63c50fa84c4537600303fe01c99d3d558fc901b93128c02206680a5c39bdfe7fb6c2e56210b98019a398230af855bfb7f0bef2c16eb6b586e
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 3045022100dfc8c4dcf7cac18aa3b7eeeb410d0b700361802b246859fda1bf7e9ddb28bd4302207c91d8e60538550d6786a8a04393985a2f24988a7906dab593a32f42ffe5fc49
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 3044022022451a3e75e1e28622d81afd9d612de5cca491ccfea1f43a00f310229b1946260220725f0d0afb4988d6ba90489c900a9f1eebe6cd4f92dd4cd09a4d084651bab218
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 3045022100df27b590bad19d0b9fa374dd997e8b92c2aecc462ac14ef575694cd99b5bd60c0220682b1740b13749b5b08dc166111b9d7b05594c1b1362f23353983441bd366dd9
    # local_signature = 3045022100ab4e3df69d6de956a2a0248d0f6f379d1b5623d0cc9cc26c1cce08e10afa0fb002207554ff93a34e98b0f1031eb7f66f9e317271c95f5ac9a4ab221279f8c3435a3c
    output htlc_success_tx 1: 020000000001010714f2b125cf0932c3549c237ca6dfd774ea510ac7170ae5b7ec74390945a4740000000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221008723f10cf5504104eae63c50fa84c4537600303fe01c99d3d558fc901b93128c02206680a5c39bdfe7fb6c2e56210b98019a398230af855bfb7f0bef2c16eb6b586e01483045022100ab4e3df69d6de956a2a0248d0f6f379d1b5623d0cc9cc26c1cce08e10afa0fb002207554ff93a34e98b0f1031eb7f66f9e317271c95f5ac9a4ab221279f8c3435a3c012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3045022100da971a7dae8022d2d1ae7dd332c46f771b36504251397d90bfe12596f9b683e1022011e33e63784c4c5affa2a2b791393040868f3caf004649a7a62c7600fc5f1815
    output htlc_timeout_tx 2: 020000000001010714f2b125cf0932c3549c237ca6dfd774ea510ac7170ae5b7ec74390945a4740100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100dfc8c4dcf7cac18aa3b7eeeb410d0b700361802b246859fda1bf7e9ddb28bd4302207c91d8e60538550d6786a8a04393985a2f24988a7906dab593a32f42ffe5fc4901483045022100da971a7dae8022d2d1ae7dd332c46f771b36504251397d90bfe12596f9b683e1022011e33e63784c4c5affa2a2b791393040868f3caf004649a7a62c7600fc5f181501006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 30450221008cbf983c5e41ecf9eea727d4937f32fac5bc9f9cacdd597b6836cdab827f00bc02203962a2728ca22f0bdc0699fb6c043aeb2ee80aa678cc180c858b2e4506705c49
    output htlc_timeout_tx 3: 020000000001010714f2b125cf0932c3549c237ca6dfd774ea510ac7170ae5b7ec74390945a47402000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022022451a3e75e1e28622d81afd9d612de5cca491ccfea1f43a00f310229b1946260220725f0d0afb4988d6ba90489c900a9f1eebe6cd4f92dd4cd09a4d084651bab218014830450221008cbf983c5e41ecf9eea727d4937f32fac5bc9f9cacdd597b6836cdab827f00bc02203962a2728ca22f0bdc0699fb6c043aeb2ee80aa678cc180c858b2e4506705c4901006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 304402206b136dca453d91558224527b221467e215e35b6f29b444100774b5ac6c1a8684022005a231d02ed1b9346d61b4fa071df9cc5758e9c57424baccbf710db628ac8026
    output htlc_success_tx 4: 020000000001010714f2b125cf0932c3549c237ca6dfd774ea510ac7170ae5b7ec74390945a47403000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100df27b590bad19d0b9fa374dd997e8b92c2aecc462ac14ef575694cd99b5bd60c0220682b1740b13749b5b08dc166111b9d7b05594c1b1362f23353983441bd366dd90147304402206b136dca453d91558224527b221467e215e35b6f29b444100774b5ac6c1a8684022005a231d02ed1b9346d61b4fa071df9cc5758e9c57424baccbf710db628ac8026012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
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
    remote_signature = 3044022048394e918fd648801c4e18731769e5ca8c00747f2ce1c00804a58b9803d058c402205552d537f699e8bdb0b2ddee0f7b479040606b4d274aec0de230cc2860d86622
    # local_signature = 304402203ce586ccb5f9615f12515ea2ea4c69141f68b3a3f3410bb9852cc9b810b2e4e10220427dc8e00f33038b058a11f6b78821303cbe734dba4758610d3a223d984a85e7
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8006d0070000000000002200204117dad487a3c3bc07e34db505d567fcc263b30075f0b4679a1b27c297b4b147d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036eb946a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402203ce586ccb5f9615f12515ea2ea4c69141f68b3a3f3410bb9852cc9b810b2e4e10220427dc8e00f33038b058a11f6b78821303cbe734dba4758610d3a223d984a85e701473044022048394e918fd648801c4e18731769e5ca8c00747f2ce1c00804a58b9803d058c402205552d537f699e8bdb0b2ddee0f7b479040606b4d274aec0de230cc2860d8662201475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 1)
    remote_htlc_signature = 30450221009fb54f59f1388631b4570183f1b0eeaaa5a0e521e99ad0634c075c47613175a7022005e6c084cbd40e1cb6cfcd158e885e3c0b0bc9dc2ce87d9a7138d65bf185fb6a
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 3045022100f4d25b14253d72479c4450687c500b536311603a899f51e3d3d42ecf2fa5d73502200fbeeddda73b74177eac6b24eaca25833871019ee4573ec495e0128a70700734
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 304402206bfd98be9b311eeb5919e01e0bae30c34889cf1ecfea31ba4e0773fcb235525e022068b70cd13eca088501250f0246fe9268a4042b51c3d1c9c843a6e091238b23e5
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 3044022022dfbdbf543436445613aa37abf548ad8caad09067723b3b87271f63b2b2e6a20220059b8d294ddc64fcb0fbb3f2911496ae821b531efc98889d958edc204e1fb288
    # local_signature = 30440220067e560bc3574614cff9336d8dd4829fdaa9402621748316ee766532a76878e202207b83635ef95e0dc1d48592e9ab801b62a6fecfed2756761b60d50444a902c344
    output htlc_success_tx 1: 02000000000101b004999c386cb186bcee5e63c80196709f1eda673a55d47d72d577801ac200110000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221009fb54f59f1388631b4570183f1b0eeaaa5a0e521e99ad0634c075c47613175a7022005e6c084cbd40e1cb6cfcd158e885e3c0b0bc9dc2ce87d9a7138d65bf185fb6a014730440220067e560bc3574614cff9336d8dd4829fdaa9402621748316ee766532a76878e202207b83635ef95e0dc1d48592e9ab801b62a6fecfed2756761b60d50444a902c344012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6800000000
    # local_signature = 3044022064c2deb4a68de7ce7d2d7090524a6875df3dcc0bbcd861cf942cdf4f99a5dc8202201a523da06e3bce4543cd4d572bfadbe316c546f36fa184158c681c56c7b2988f
    output htlc_timeout_tx 2: 02000000000101b004999c386cb186bcee5e63c80196709f1eda673a55d47d72d577801ac200110100000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f4d25b14253d72479c4450687c500b536311603a899f51e3d3d42ecf2fa5d73502200fbeeddda73b74177eac6b24eaca25833871019ee4573ec495e0128a7070073401473044022064c2deb4a68de7ce7d2d7090524a6875df3dcc0bbcd861cf942cdf4f99a5dc8202201a523da06e3bce4543cd4d572bfadbe316c546f36fa184158c681c56c7b2988f01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 30440220473f9c39061d801cc3a69b32a9b9a64856799d8fcbb494df37aedc9b3c11564e022020eb18c61d70c57d457fb142aef9b1b2c24633a0591b2aa2a74df0bdc88a914a
    output htlc_timeout_tx 3: 02000000000101b004999c386cb186bcee5e63c80196709f1eda673a55d47d72d577801ac200110200000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402206bfd98be9b311eeb5919e01e0bae30c34889cf1ecfea31ba4e0773fcb235525e022068b70cd13eca088501250f0246fe9268a4042b51c3d1c9c843a6e091238b23e5014730440220473f9c39061d801cc3a69b32a9b9a64856799d8fcbb494df37aedc9b3c11564e022020eb18c61d70c57d457fb142aef9b1b2c24633a0591b2aa2a74df0bdc88a914a01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 30440220171096b7c61825f9d541b6c074a2730554ec1701c9db85bd578f0e221192af0602207d71c64206fbb6a234405369cba14c9033931a8064c22ca17a386e32dd2a4b94
    output htlc_success_tx 4: 02000000000101b004999c386cb186bcee5e63c80196709f1eda673a55d47d72d577801ac2001103000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022022dfbdbf543436445613aa37abf548ad8caad09067723b3b87271f63b2b2e6a20220059b8d294ddc64fcb0fbb3f2911496ae821b531efc98889d958edc204e1fb288014730440220171096b7c61825f9d541b6c074a2730554ec1701c9db85bd578f0e221192af0602207d71c64206fbb6a234405369cba14c9033931a8064c22ca17a386e32dd2a4b94012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
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
    remote_signature = 304402205c6c018b8394531f5cc83564aa906818c1e991038e3719112c063affcb964f7c02203cc68c355c0276c8c612f519800da8f9c7054e3605048e2cd6dd9d6741643934
    # local_signature = 3045022100c87aa55dadff058208a59f34b197407db1f97383611853573331e1ea9749c3c70220258ef209f7aaf17e0a91c9716a94f8eef3d6f2327559a30389cee1fac0564407
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8005d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0365f966a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100c87aa55dadff058208a59f34b197407db1f97383611853573331e1ea9749c3c70220258ef209f7aaf17e0a91c9716a94f8eef3d6f2327559a30389cee1fac05644070147304402205c6c018b8394531f5cc83564aa906818c1e991038e3719112c063affcb964f7c02203cc68c355c0276c8c612f519800da8f9c7054e3605048e2cd6dd9d674164393401475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 304402205e0a60923ba72184a7af522592cff0916568b39e7902a6fc2e8676929079cfe2022044c85f9f41901c85a8a63d9f2defe730cb7a0abbd965a9cbf08f43dea52dfd46
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 3045022100ead1bb716eca9483c4a1d9e535a823011ed88930c0bf6a52d6c7595e6547e0f502206d677f5aaff989c5a96df668569fd7e85d8f0409f273ff28b5c48c5bf09b8db9
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 304502210096f045fb204f1482706c05ce0234cb569d54ad3da6b5de5e453c477f159e09a5022025870367be40c04981510198e5aa276dde634e3f25469b2094bb129463bfa552
    # local_signature = 3045022100cb3939d50b7d835302e7f0ac8bdad5c4cc4c8fbdd5aa50e06f1309536a4a4aae022059d0dee4aaa184235dabb9153620eb491cb42a287f45a5e4b1ca40bf5065fd26
    output htlc_timeout_tx 2: 02000000000101af680027909b7c572b65dcf5f493121a4cba294d5513878b04832255487cd8f30000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402205e0a60923ba72184a7af522592cff0916568b39e7902a6fc2e8676929079cfe2022044c85f9f41901c85a8a63d9f2defe730cb7a0abbd965a9cbf08f43dea52dfd4601483045022100cb3939d50b7d835302e7f0ac8bdad5c4cc4c8fbdd5aa50e06f1309536a4a4aae022059d0dee4aaa184235dabb9153620eb491cb42a287f45a5e4b1ca40bf5065fd2601006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 3044022079b5d15d8768c3f16e89331167ea1229fe56c570355b751fc2a2fe159cb384470220376f649125b8dcd137445c03722d2147dcea843b3567d8293391d0e5d98e8c3f
    output htlc_timeout_tx 3: 02000000000101af680027909b7c572b65dcf5f493121a4cba294d5513878b04832255487cd8f30100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100ead1bb716eca9483c4a1d9e535a823011ed88930c0bf6a52d6c7595e6547e0f502206d677f5aaff989c5a96df668569fd7e85d8f0409f273ff28b5c48c5bf09b8db901473044022079b5d15d8768c3f16e89331167ea1229fe56c570355b751fc2a2fe159cb384470220376f649125b8dcd137445c03722d2147dcea843b3567d8293391d0e5d98e8c3f01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 30450221009af86b53bd5ec839f8c3503b79c052dd8f4d49180ce97a4f295ca8e2f44090f9022076cc96c957f91322c9f9ab20771b1d65c827bb8c1886268a2744fccb949c46c7
    output htlc_success_tx 4: 02000000000101af680027909b7c572b65dcf5f493121a4cba294d5513878b04832255487cd8f302000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050048304502210096f045fb204f1482706c05ce0234cb569d54ad3da6b5de5e453c477f159e09a5022025870367be40c04981510198e5aa276dde634e3f25469b2094bb129463bfa552014830450221009af86b53bd5ec839f8c3503b79c052dd8f4d49180ce97a4f295ca8e2f44090f9022076cc96c957f91322c9f9ab20771b1d65c827bb8c1886268a2744fccb949c46c7012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
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
    remote_signature = 3044022040400be36273ae73fb049bc752a02bbd2cac91f317b136eb23a0508294c8db9302203233fe070357bd7254fdbd7bf3523d6a5da1eeeb22356bca5ebe49335daea0d2
    # local_signature = 3044022068cf7d57c4d8a4001e5009843d3e4c692f99817bf1e1a08439511662605829a40220782047d7e9703edbf9db9767d429193c51835df935f617e0e729e1a2962d2263
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8005d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036c4956a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022068cf7d57c4d8a4001e5009843d3e4c692f99817bf1e1a08439511662605829a40220782047d7e9703edbf9db9767d429193c51835df935f617e0e729e1a2962d226301473044022040400be36273ae73fb049bc752a02bbd2cac91f317b136eb23a0508294c8db9302203233fe070357bd7254fdbd7bf3523d6a5da1eeeb22356bca5ebe49335daea0d201475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 3045022100a70693eb04d5f2135f5e485f0b4362ab04a38042371a5f03abc0455869116872022061a84f37836e5a640d591c416a540e2fca662cb957570a1f202455ebee6d7698
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 304402202f6a113b04032c5bee13d8f256b2ce575106166907c3833fbfe8a9d4e0be2cb0022021458437ee16a1ba8108b274647c48172e6e5d630e6b0b0ff51df10462168e43
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 3045022100e38a2e20649d51e21de527202ecc682a98f0c18b71798d3d4b1fcbe736187303022018c97af9f1ae3ba1bf1e705296be7bb07e621b320f9da9e4c88afafc514047a5
    # local_signature = 3044022035155ab93c96ebd4d8aa3a7cf118161847cb68e752b13055d7f2b77c07c8cb67022025dd3bbc93ff8564cc8d3c60b0b550842ac49fd54006e70b7cbbf81987f1ad18
    output htlc_timeout_tx 2: 020000000001014b1a8373f95079a67d47a75fe1e12f1241e3aab117fd86ea8352c7ac44e43d5e00000000000000000001cd010000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a70693eb04d5f2135f5e485f0b4362ab04a38042371a5f03abc0455869116872022061a84f37836e5a640d591c416a540e2fca662cb957570a1f202455ebee6d769801473044022035155ab93c96ebd4d8aa3a7cf118161847cb68e752b13055d7f2b77c07c8cb67022025dd3bbc93ff8564cc8d3c60b0b550842ac49fd54006e70b7cbbf81987f1ad1801006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local_signature = 304402205a3e683d58eb9a78675ca8c93b01c23436a343296acebae476e8e49baf1f3c18022013b79a955d3f174fb8d399a7e60af820d4f3eed5ca23b538696877e37a3e65a1
    output htlc_timeout_tx 3: 020000000001014b1a8373f95079a67d47a75fe1e12f1241e3aab117fd86ea8352c7ac44e43d5e01000000000000000001b5050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402202f6a113b04032c5bee13d8f256b2ce575106166907c3833fbfe8a9d4e0be2cb0022021458437ee16a1ba8108b274647c48172e6e5d630e6b0b0ff51df10462168e430147304402205a3e683d58eb9a78675ca8c93b01c23436a343296acebae476e8e49baf1f3c18022013b79a955d3f174fb8d399a7e60af820d4f3eed5ca23b538696877e37a3e65a101006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 30450221009b243f956eddcb7ef55b5511d551be5d516e1741884cdc5ab56f8fef7337f471022038f09735ca41dbeb109fd5caf434457d87c752095da6efb6d790e1a7db118d6d
    output htlc_success_tx 4: 020000000001014b1a8373f95079a67d47a75fe1e12f1241e3aab117fd86ea8352c7ac44e43d5e020000000000000000019d090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e38a2e20649d51e21de527202ecc682a98f0c18b71798d3d4b1fcbe736187303022018c97af9f1ae3ba1bf1e705296be7bb07e621b320f9da9e4c88afafc514047a5014830450221009b243f956eddcb7ef55b5511d551be5d516e1741884cdc5ab56f8fef7337f471022038f09735ca41dbeb109fd5caf434457d87c752095da6efb6d790e1a7db118d6d012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2295
    # base commitment transaction fee = 2451
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6985549 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100c0e3cae1c43c1052e07af51bd3902fb1d4a9f4efde9ec06ab2df5ce60ccd9449022024dbf355751072a2181805fd7addef00ceca7c4196f1c6df64cf15e1befa2945
    # local_signature = 30450221008352e298d3ccaa0cff60a98e53c5b2b7adf3ccea340e3bbb6482b1df0c0e0c8f02201ca7fda9fbe5882d18970e27194241d5e6c2c20251ed6fa314b938e5be28bd60
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8004b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0364d976a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004830450221008352e298d3ccaa0cff60a98e53c5b2b7adf3ccea340e3bbb6482b1df0c0e0c8f02201ca7fda9fbe5882d18970e27194241d5e6c2c20251ed6fa314b938e5be28bd6001483045022100c0e3cae1c43c1052e07af51bd3902fb1d4a9f4efde9ec06ab2df5ce60ccd9449022024dbf355751072a2181805fd7addef00ceca7c4196f1c6df64cf15e1befa294501475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3044022019aeb1cd0b64553930c44ade382a87b9a2adfe7a7e0a76a2eecaddc999b952e802202959f16e4cd10e7c93d48ac432391ac4057ff8a65fd8a2eab1cdff8f2ed64df6
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 30440220373d35db702bd36791f36514c89eff0aa17345179d3db131241c6508fca5180f02204016c924363290533dbfba58683d07769358a5eb8536ef253cef02c030b9d574
    # local_signature = 3045022100a54d17e067d2a8c9209ac9f10f90ed8ebe095272d04b88dcf9971a8f1562f226022020fe1b188146e4f6f12521523f1929d1ac9d4167eeb23774e20b9655c96d48de
    output htlc_timeout_tx 3: 020000000001018bd5eb82897ef628d809ecd61b1987be12fcb9e14a502c8d110355d74fecf43600000000000000000001b5050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022019aeb1cd0b64553930c44ade382a87b9a2adfe7a7e0a76a2eecaddc999b952e802202959f16e4cd10e7c93d48ac432391ac4057ff8a65fd8a2eab1cdff8f2ed64df601483045022100a54d17e067d2a8c9209ac9f10f90ed8ebe095272d04b88dcf9971a8f1562f226022020fe1b188146e4f6f12521523f1929d1ac9d4167eeb23774e20b9655c96d48de01006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100e52fb5bae86d1f6d57d60f8974b148ec5a16c92b7c43fc2004a22b19537cec8e0220222550a5781222fce7cecc3ee4a0aee84b4a6cc3bcf1ec7307ea76cfb24f052a
    output htlc_success_tx 4: 020000000001018bd5eb82897ef628d809ecd61b1987be12fcb9e14a502c8d110355d74fecf436010000000000000000019d090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220373d35db702bd36791f36514c89eff0aa17345179d3db131241c6508fca5180f02204016c924363290533dbfba58683d07769358a5eb8536ef253cef02c030b9d57401483045022100e52fb5bae86d1f6d57d60f8974b148ec5a16c92b7c43fc2004a22b19537cec8e0220222550a5781222fce7cecc3ee4a0aee84b4a6cc3bcf1ec7307ea76cfb24f052a012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3872
    # base commitment transaction fee = 4135
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6983865 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022033ec830ca9284fb68195facbaaafc8c12b86bc5cfcd6a3fc3112850a01b25bb702206ad13b9ad718b294b289c56fdded283a09d7c7f35d29137ec012b2893581ced8
    # local_signature = 3045022100c5ae9614b5cdd5fd8445de079e44104942e3491b349eea624ba75a188ebaab8f02202b72477c6528ada1f9cc44aa2d3c671ccf4ef468b0efa2058d3931e7ed0871b0
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8004b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036b9906a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100c5ae9614b5cdd5fd8445de079e44104942e3491b349eea624ba75a188ebaab8f02202b72477c6528ada1f9cc44aa2d3c671ccf4ef468b0efa2058d3931e7ed0871b001473044022033ec830ca9284fb68195facbaaafc8c12b86bc5cfcd6a3fc3112850a01b25bb702206ad13b9ad718b294b289c56fdded283a09d7c7f35d29137ec012b2893581ced801475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3044022048b807affd3960af34a8d0f225e10bfe4c3d0d78b441def7842183e08c88479502206d16cf847919e46647846a512bf41e2654256e7d1ca5a2ad2c94aab0c1642b3a
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 3044022069089b858f9f4711751ee829d5ef8ccbe39a11b1f9963e12adf5019e1993fef90220089408c79926bff710247ab2efdc94e60d6309e222a1e5a5cf32ea5f1c4b24d9
    # local_signature = 3045022100fb415f03d6e808cb8052eb910c300c0cc80cf17c43f341ef26b4057eb207f91b02201eca49353a5de9ab2499a97ec7407dd783a59445f2d0a213e4fd214f7625f364
    output htlc_timeout_tx 3: 02000000000101053f39751be467b7511b3aa92b5afdf5198fbab846843050f033b5986d046dc50000000000000000000192010000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022048b807affd3960af34a8d0f225e10bfe4c3d0d78b441def7842183e08c88479502206d16cf847919e46647846a512bf41e2654256e7d1ca5a2ad2c94aab0c1642b3a01483045022100fb415f03d6e808cb8052eb910c300c0cc80cf17c43f341ef26b4057eb207f91b02201eca49353a5de9ab2499a97ec7407dd783a59445f2d0a213e4fd214f7625f36401006921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local_signature = 3045022100f0286877f889f75b8bcc4807fd2537d81e085ee8747de9aff6ac3d31e7921343022010325156844e5dfeb7fa24166d158baa1be2310d2799ccea04946ac0b68a9f00
    output htlc_success_tx 4: 02000000000101053f39751be467b7511b3aa92b5afdf5198fbab846843050f033b5986d046dc5010000000000000000017a050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022069089b858f9f4711751ee829d5ef8ccbe39a11b1f9963e12adf5019e1993fef90220089408c79926bff710247ab2efdc94e60d6309e222a1e5a5cf32ea5f1c4b24d901483045022100f0286877f889f75b8bcc4807fd2537d81e085ee8747de9aff6ac3d31e7921343022010325156844e5dfeb7fa24166d158baa1be2310d2799ccea04946ac0b68a9f00012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3873
    # base commitment transaction fee = 3470
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6984530 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100a2a2eb2056daf5e219bf9ec37c9cff95090007a0eb8eaf42f3b4d649349952c5022048f757d01436fb19acb93c7130c095753548d867145dc3447ef72c71a19c4555
    # local_signature = 304402201116a3c1a7e170d217cf5de7b9ef8d691c330f76d3d938cfbd9ca88cf05682d90220127411a53906359c10954d13fbf2f261e48809d959e3efe88ecf2f3a7a2e338f
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8003a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03652936a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402201116a3c1a7e170d217cf5de7b9ef8d691c330f76d3d938cfbd9ca88cf05682d90220127411a53906359c10954d13fbf2f261e48809d959e3efe88ecf2f3a7a2e338f01483045022100a2a2eb2056daf5e219bf9ec37c9cff95090007a0eb8eaf42f3b4d649349952c5022048f757d01436fb19acb93c7130c095753548d867145dc3447ef72c71a19c455501475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 3045022100e3015e60b77b16fb3550a965037344fc9bb82dbe109eefb814f23100a1dfe3e4022041aea2ff8ba5fed0644a05a421e9175aa274ed77ac9f3914829025100220ebdf
    # local_signature = 3045022100d68e79f8a3b6a2573237f87f88b477deb80f3c06db8f9d85184dc6a8a084ca3a022030e44041a1b17276d620784e41163d9fa982d35f2ed8bd5f22cb7add3922cefc
    output htlc_success_tx 4: 02000000000101e7be5420871e79810e6ef1762192a4c62eff83a3da4790c877e6c9a81b98a74d000000000000000000017a050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e3015e60b77b16fb3550a965037344fc9bb82dbe109eefb814f23100a1dfe3e4022041aea2ff8ba5fed0644a05a421e9175aa274ed77ac9f3914829025100220ebdf01483045022100d68e79f8a3b6a2573237f87f88b477deb80f3c06db8f9d85184dc6a8a084ca3a022030e44041a1b17276d620784e41163d9fa982d35f2ed8bd5f22cb7add3922cefc012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5149
    # base commitment transaction fee = 4613
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac68
    # to-local amount 6983387 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100d209fa298238b49d03a71ba2ab68a8a448c83165dede54a9e2a3531c9bcae9e902200f7506df768d5fdf804b9b72f64dc7c48d43c215cdb8e92d5da5a37958a55321
    # local_signature = 3044022017de3f7a6789ca1e5a19af6c30dc1f5b7ccb6d5f607328724723b3178664ae49022024c9e1278ed9ec271d718f9e217c356bc332bcb2fe886bc0801fcba8570ed8bc
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8003a00f00000000000022002024bec9455b911553c1200bbf925db2d5fe047130c80da32a7d05abb490996e22c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036db8e6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022017de3f7a6789ca1e5a19af6c30dc1f5b7ccb6d5f607328724723b3178664ae49022024c9e1278ed9ec271d718f9e217c356bc332bcb2fe886bc0801fcba8570ed8bc01483045022100d209fa298238b49d03a71ba2ab68a8a448c83165dede54a9e2a3531c9bcae9e902200f7506df768d5fdf804b9b72f64dc7c48d43c215cdb8e92d5da5a37958a5532101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 30440220659dccb38d358d1316a4fa6100c39ae39d70c30d48dff9047bf3d29b2dc6aed702201134cf9d6a41f4d738b16df47638b70e2067ef26160fc9b87449c4a5a3d998f3
    # local_signature = 3045022100a03b21cde59f607eb8627fba49e970c67b979207e4a57e96757479935b1c2d75022018b3c794576a47e9a70a05b4ed120a5471532c46503bce3bc23a8e205d74c013
    output htlc_success_tx 4: 02000000000101e8b07e6e63e5a507fcb31f3184f56ef30c49028b8ae2699d97a201d5ad31fc570000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220659dccb38d358d1316a4fa6100c39ae39d70c30d48dff9047bf3d29b2dc6aed702201134cf9d6a41f4d738b16df47638b70e2067ef26160fc9b87449c4a5a3d998f301483045022100a03b21cde59f607eb8627fba49e970c67b979207e4a57e96757479935b1c2d75022018b3c794576a47e9a70a05b4ed120a5471532c46503bce3bc23a8e205d74c013012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6800000000
    
    name: commitment tx with 2 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5150
    # base commitment transaction fee = 3728
    # to-local amount 6984272 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 30450221008b9382b273ee6002e66bafbb38aeca1beaa00f87c6716d6f21bca7284e70540a022061fab472e7bfeba7bbeca4f9d1d2187d15d6175c5aa1998bac31c42f3c7595fe
    # local_signature = 30450221009b3e720cafef6b19cf4d37ba084597b0a28d6401d4b90c5eab4d773f20b7f859022050f2e59e5165b446ecff38e8477680c330c8ee041c521f15ea7c0c77daa3e40a
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03650926a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004830450221009b3e720cafef6b19cf4d37ba084597b0a28d6401d4b90c5eab4d773f20b7f859022050f2e59e5165b446ecff38e8477680c330c8ee041c521f15ea7c0c77daa3e40a014830450221008b9382b273ee6002e66bafbb38aeca1beaa00f87c6716d6f21bca7284e70540a022061fab472e7bfeba7bbeca4f9d1d2187d15d6175c5aa1998bac31c42f3c7595fe01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with 2 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651180
    # base commitment transaction fee = 6987454
    # to-local amount 546 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 30450221009ed503febfd1d4c545eda9559407f8549a98cebc993d5a5276a8af9bc57015a0022074d34ea29b7b575e6a1410849e017f200872408ae1783fd5c4a1849f1c0a64e1
    # local_signature = 3044022054be555efca328402d5b2aa69de18741717fae930529f5cb5c5d4ef32d6e696002207f973a2a8683456c940987ad91f6a728679db66e40a8a0d77228feda8ee79d5a
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b800222020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0360400473044022054be555efca328402d5b2aa69de18741717fae930529f5cb5c5d4ef32d6e696002207f973a2a8683456c940987ad91f6a728679db66e40a8a0d77228feda8ee79d5a014830450221009ed503febfd1d4c545eda9559407f8549a98cebc993d5a5276a8af9bc57015a0022074d34ea29b7b575e6a1410849e017f200872408ae1783fd5c4a1849f1c0a64e101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with 1 output untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651181
    # base commitment transaction fee = 6987455
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402204b029edee09ba1ab1a647cae290cf57778300e48b75c707224329d32a6b96324022032737e48c97a9f987035305ec22c4ad4a78bbc363b472e109fffdeaa17751471
    # local_signature = 30440220459650e7c680f581cd38f8b9a73316bc4fea888763272972674353115119fd1d02200ea456307ebfef0255f8134d2440f47f96c2d73c51d2dbc122c53481bfc07cc4
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8001c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03604004730440220459650e7c680f581cd38f8b9a73316bc4fea888763272972674353115119fd1d02200ea456307ebfef0255f8134d2440f47f96c2d73c51d2dbc122c53481bfc07cc40147304402204b029edee09ba1ab1a647cae290cf57778300e48b75c707224329d32a6b96324022032737e48c97a9f987035305ec22c4ad4a78bbc363b472e109fffdeaa1775147101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with fee greater than funder amount
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651936
    # base commitment transaction fee = 6988001
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402204b029edee09ba1ab1a647cae290cf57778300e48b75c707224329d32a6b96324022032737e48c97a9f987035305ec22c4ad4a78bbc363b472e109fffdeaa17751471
    # local_signature = 30440220459650e7c680f581cd38f8b9a73316bc4fea888763272972674353115119fd1d02200ea456307ebfef0255f8134d2440f47f96c2d73c51d2dbc122c53481bfc07cc4
    output commit_tx: 020000000001018c31219f84710b5295ba9c81155a572ad99c2d48d995e1966e44bf06f0ea8714000000000038b02b8001c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03604004730440220459650e7c680f581cd38f8b9a73316bc4fea888763272972674353115119fd1d02200ea456307ebfef0255f8134d2440f47f96c2d73c51d2dbc122c53481bfc07cc40147304402204b029edee09ba1ab1a647cae290cf57778300e48b75c707224329d32a6b96324022032737e48c97a9f987035305ec22c4ad4a78bbc363b472e109fffdeaa1775147101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
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

