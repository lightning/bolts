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
    # to-local amount 6989140 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022079f7751a489c2e3ee0d333d969553416461a7e32db9968c2358eccc8bbd82b7c0220092b9ed2dcb79fafec93445d1d956089b6779ddb8569d470c396a2ff43cf288c
    # local_signature = 3045022100a5a2529bfe215218a2185cba3bacc6079975004665cbabb290cbc79b6905300e02206f1e3d3062b33eb6ce33b395efb2020bf47640df52c4fc2d0b95e70bbbb8f33e
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03654a56a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100a5a2529bfe215218a2185cba3bacc6079975004665cbabb290cbc79b6905300e02206f1e3d3062b33eb6ce33b395efb2020bf47640df52c4fc2d0b95e70bbbb8f33e01473044022079f7751a489c2e3ee0d333d969553416461a7e32db9968c2358eccc8bbd82b7c0220092b9ed2dcb79fafec93445d1d956089b6779ddb8569d470c396a2ff43cf288c01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with all 5 htlcs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 0
    # base commitment transaction fee = 0
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 1000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6988000 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022053f93c95032af137889efc5f5c4d69a1ccc929d4b7680d255998a36420ca9c9902207c01c7a44b7b5b760bcbeaea71922274349c20136dcc59b725554f0cfa9a8299
    # local_signature = 3045022100c4400fbfba534a5cdae4289dfb301e4530e5d21fbeabdb92c4703f6626597f8602202407fb8767d0c459812b814ba446dd8b0985d4785f95ee5aadb39f11e7f06ce3
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8007e80300000000000022002042f0ed691122e37a50154fccac262c04cb843c835860a0bf5cbaeb39c2a18555d0070000000000002200208848c43f1877825f0e466e034cadc5f208fbefb125a4210d35222f226bf88fd6d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036e0a06a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100c4400fbfba534a5cdae4289dfb301e4530e5d21fbeabdb92c4703f6626597f8602202407fb8767d0c459812b814ba446dd8b0985d4785f95ee5aadb39f11e7f06ce301473044022053f93c95032af137889efc5f5c4d69a1ccc929d4b7680d255998a36420ca9c9902207c01c7a44b7b5b760bcbeaea71922274349c20136dcc59b725554f0cfa9a829901475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 3045022100f7d86a481f321c0d31bf79eb2e32149c51299e815e89cb58ac707323bfdc9c9c02201ae083dc16675e74de6b7b79affd8de6bde191fefee03c29a0b4fc23f343ef80
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 3045022100944aeff8b05350a01b7a53fe70c47d7f7c65781cf8162623be9fe2652c809ff20220444b7945226b84fe180fc86f078f44fa5c9a23e481d20b748ff17d8f4c67cdb1
    # signature for output 2 (htlc 2)
    remote_htlc_signature = 30450221009bb78d76c1b3bab0e189ad8d00497b422ccb68279d16b41b59c87e7d88351c630220636f8f9530cc116f23e65c1b3bbaa85183a139ae1ad598e1948e3614c76bd434
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 3045022100ab3b9a12b19f4dce462fa595c941665e0c94ca09c71d82c8dcfba82d2e11e32002201b644aa85fda740c49876e2ba032a50492672170feb0165969e739b759117305
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 3044022029029f5ca05018378adfe7ee817554f82b05774ffe2c3e955f9fbeaec450878302204987a493742f51deb874323c246594f895a9a0ca780220e3766afbfe19b663d1
    # local_signature = 3045022100b7e21c3c1e47ea5a6156e53e225457fbad1212502ad00cd71eece6537ec9e59f02206db7e644a1060b821b7badf1648319549839cc937f5cb7e07dda50e12d5afc35
    output htlc_success_tx 0: 020000000001015c677ff0b1ba939728ae4c2fa99f88f9756620c0040a6c46bc4faa2d4e48260f00000000000000000001e8030000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f7d86a481f321c0d31bf79eb2e32149c51299e815e89cb58ac707323bfdc9c9c02201ae083dc16675e74de6b7b79affd8de6bde191fefee03c29a0b4fc23f343ef8001483045022100b7e21c3c1e47ea5a6156e53e225457fbad1212502ad00cd71eece6537ec9e59f02206db7e644a1060b821b7badf1648319549839cc937f5cb7e07dda50e12d5afc35012000000000000000000000000000000000000000000000000000000000000000006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    # local_signature = 30440220764db825c7bebe8834cb6fdb811385b674d44c280b771d3bd116a86348a1fb4a02201b4eae2b72a64a21a6f4e07ac4e3c75ae52cc2d5e791d02c1174c0333dc89f2c
    output htlc_success_tx 1: 020000000001015c677ff0b1ba939728ae4c2fa99f88f9756620c0040a6c46bc4faa2d4e48260f01000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100944aeff8b05350a01b7a53fe70c47d7f7c65781cf8162623be9fe2652c809ff20220444b7945226b84fe180fc86f078f44fa5c9a23e481d20b748ff17d8f4c67cdb1014730440220764db825c7bebe8834cb6fdb811385b674d44c280b771d3bd116a86348a1fb4a02201b4eae2b72a64a21a6f4e07ac4e3c75ae52cc2d5e791d02c1174c0333dc89f2c012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    # local_signature = 3045022100f7bbe202fa6ee83cc745e13e0d18eaf7f738a604122ce91e8a370cf53748ed130220011f0001b6b2cdc44041278fe4f3cfe27aeea2742ac7ae7b47f1dad9b77f13a8
    output htlc_timeout_tx 2: 020000000001015c677ff0b1ba939728ae4c2fa99f88f9756620c0040a6c46bc4faa2d4e48260f02000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221009bb78d76c1b3bab0e189ad8d00497b422ccb68279d16b41b59c87e7d88351c630220636f8f9530cc116f23e65c1b3bbaa85183a139ae1ad598e1948e3614c76bd43401483045022100f7bbe202fa6ee83cc745e13e0d18eaf7f738a604122ce91e8a370cf53748ed130220011f0001b6b2cdc44041278fe4f3cfe27aeea2742ac7ae7b47f1dad9b77f13a801006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6822a10700
    # local_signature = 3044022066b026dae28aae6b9beb3c4ce1ea5433ed47e91331cc44a2294baa8d733319c702201df6a6284d1eb6f47f58e7ccd9e1c03feef32ac30a56085da1aa5ac673ca36dd
    output htlc_timeout_tx 3: 020000000001015c677ff0b1ba939728ae4c2fa99f88f9756620c0040a6c46bc4faa2d4e48260f03000000000000000001b80b0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100ab3b9a12b19f4dce462fa595c941665e0c94ca09c71d82c8dcfba82d2e11e32002201b644aa85fda740c49876e2ba032a50492672170feb0165969e739b75911730501473044022066b026dae28aae6b9beb3c4ce1ea5433ed47e91331cc44a2294baa8d733319c702201df6a6284d1eb6f47f58e7ccd9e1c03feef32ac30a56085da1aa5ac673ca36dd01006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6823a10700
    # local_signature = 3045022100a1119e8092ac10457f7a00e78dc1401d30e90bbcbf91ff6090e047c5064fda2b0220570fe49fe59159c377f9f05ffeebe9bcb3e13c34e6c76c4c1fa489f1e603ee28
    output htlc_success_tx 4: 020000000001015c677ff0b1ba939728ae4c2fa99f88f9756620c0040a6c46bc4faa2d4e48260f04000000000000000001a00f0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022029029f5ca05018378adfe7ee817554f82b05774ffe2c3e955f9fbeaec450878302204987a493742f51deb874323c246594f895a9a0ca780220e3766afbfe19b663d101483045022100a1119e8092ac10457f7a00e78dc1401d30e90bbcbf91ff6090e047c5064fda2b0220570fe49fe59159c377f9f05ffeebe9bcb3e13c34e6c76c4c1fa489f1e603ee28012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 7 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 678
    # base commitment transaction fee = 1073
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 1000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6986927 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100e49b89fb747d9ab8ca39ab14889c2053324b229354449d9ecc2afac797f1737702200c412764f8bf830ff43da21a7070b9395d4205e1fd848a5cf5774e5df9dea91e
    # local_signature = 3045022100ba26c8159468841e96b590c522224dbca850569d5977bfe22eb7958b1a1d673e022015a2f474f57abd5ff9eda5d82eb7cff97df38c62059808d238fdc53cc32e2930
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8007e80300000000000022002042f0ed691122e37a50154fccac262c04cb843c835860a0bf5cbaeb39c2a18555d0070000000000002200208848c43f1877825f0e466e034cadc5f208fbefb125a4210d35222f226bf88fd6d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036af9c6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100ba26c8159468841e96b590c522224dbca850569d5977bfe22eb7958b1a1d673e022015a2f474f57abd5ff9eda5d82eb7cff97df38c62059808d238fdc53cc32e293001483045022100e49b89fb747d9ab8ca39ab14889c2053324b229354449d9ecc2afac797f1737702200c412764f8bf830ff43da21a7070b9395d4205e1fd848a5cf5774e5df9dea91e01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature = 304502210095a10d3227d7e7f1389a8c6b4017e55d6387d9609eb5f4b551981f8ec050782202206b8370a06e488d6522192a8b03fa9f85dc69bbbba81570962adf648eeeeb6303
    # signature for output 1 (htlc 1)
    remote_htlc_signature = 304402204ada0cd50dc6cbfb4a789ee0893de23e3355fdc263d126f28e80f5f6ceb4184e02205ced11f4adc909b24156dec5f49179199ef5077dff769f9ad73ec275ed600350
    # signature for output 2 (htlc 2)
    remote_htlc_signature = 3045022100b12cedc13091bc44206ae61da67204721772cdcdec5e6ef10a1fc93b5c0de1990220237dbf8d0d52b1ff5a7b3d881157962cc3fb32d738c8e7aa583ea24b331a5a67
    # signature for output 3 (htlc 3)
    remote_htlc_signature = 3044022031fdc626f6175a980f4b2e5b11cd8bb6d3f6cb00d62965af41743f9a8b61d6f502202ba3682de6b227f6466ba8433abb585cc9dfb0d28c2aacf8392fe8a0d32638aa
    # signature for output 4 (htlc 4)
    remote_htlc_signature = 3044022006562370a20c7954f86a529de199f2dd121db749f910e5ab9ffec400fd122ab40220125428e40fd29baeab52c03aa3b3fe16c2c755514df5cafc8fe86b340246f7ac
    # local_signature = 3045022100b310c96063dd4274b88e01635f78642409881436431971be46d5cb1aa84121f802202a1c86f5d1d887b2723e5b8ea7e7c6e2f9e8dbd3a4aa5b7d9ed2a2c9eb9f34e1
    output htlc_success_tx 0: 02000000000101023e0bcdd847657a87995dd184e34d696716140669df874cb5b645659d98b3f00000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050048304502210095a10d3227d7e7f1389a8c6b4017e55d6387d9609eb5f4b551981f8ec050782202206b8370a06e488d6522192a8b03fa9f85dc69bbbba81570962adf648eeeeb630301483045022100b310c96063dd4274b88e01635f78642409881436431971be46d5cb1aa84121f802202a1c86f5d1d887b2723e5b8ea7e7c6e2f9e8dbd3a4aa5b7d9ed2a2c9eb9f34e1012000000000000000000000000000000000000000000000000000000000000000006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    # local_signature = 3045022100ce4ed8505389a09857d8c277a31988791dc5840bf436542870d30bf3db614057022056574a41098a5775ebe15b160bd51c520f23171e2d3a9e0d62b95326745625cf
    output htlc_success_tx 1: 02000000000101023e0bcdd847657a87995dd184e34d696716140669df874cb5b645659d98b3f00100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402204ada0cd50dc6cbfb4a789ee0893de23e3355fdc263d126f28e80f5f6ceb4184e02205ced11f4adc909b24156dec5f49179199ef5077dff769f9ad73ec275ed60035001483045022100ce4ed8505389a09857d8c277a31988791dc5840bf436542870d30bf3db614057022056574a41098a5775ebe15b160bd51c520f23171e2d3a9e0d62b95326745625cf012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    # local_signature = 3044022000dc904cfd8564ceeabf031684a2785f48e4a3d90088acd0ce44c3209addbe100220320d18d7bae674b8696214fa564b50ba90f1e27a0420a11dfbaa7a702484680a
    output htlc_timeout_tx 2: 02000000000101023e0bcdd847657a87995dd184e34d696716140669df874cb5b645659d98b3f00200000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100b12cedc13091bc44206ae61da67204721772cdcdec5e6ef10a1fc93b5c0de1990220237dbf8d0d52b1ff5a7b3d881157962cc3fb32d738c8e7aa583ea24b331a5a6701473044022000dc904cfd8564ceeabf031684a2785f48e4a3d90088acd0ce44c3209addbe100220320d18d7bae674b8696214fa564b50ba90f1e27a0420a11dfbaa7a702484680a01006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6822a10700
    # local_signature = 304502210098700212e70fcb615f429e01e0f1fcac68ba16629aede196fd3098373c46822202202ee1ea407b9dfebcea1819e6821aa1aca27fd8b6e6f0461dab88405e5ae173ed
    output htlc_timeout_tx 3: 02000000000101023e0bcdd847657a87995dd184e34d696716140669df874cb5b645659d98b3f003000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022031fdc626f6175a980f4b2e5b11cd8bb6d3f6cb00d62965af41743f9a8b61d6f502202ba3682de6b227f6466ba8433abb585cc9dfb0d28c2aacf8392fe8a0d32638aa0148304502210098700212e70fcb615f429e01e0f1fcac68ba16629aede196fd3098373c46822202202ee1ea407b9dfebcea1819e6821aa1aca27fd8b6e6f0461dab88405e5ae173ed01006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6823a10700
    # local_signature = 3045022100c27f95c3017f117936964b1b04b53226697d6d5a52b6b1a5bc89cbdabe6bd57702201fff4278519e4327b787df1b40e03e0db647a92aec79a965def55e09939a7e74
    output htlc_success_tx 4: 02000000000101023e0bcdd847657a87995dd184e34d696716140669df874cb5b645659d98b3f004000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022006562370a20c7954f86a529de199f2dd121db749f910e5ab9ffec400fd122ab40220125428e40fd29baeab52c03aa3b3fe16c2c755514df5cafc8fe86b340246f7ac01483045022100c27f95c3017f117936964b1b04b53226697d6d5a52b6b1a5bc89cbdabe6bd57702201fff4278519e4327b787df1b40e03e0db647a92aec79a965def55e09939a7e74012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 679
    # base commitment transaction fee = 958
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6987042 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100bf4fedf54e61057d3c2802d9ef49d74ec49272cf902113162d4d2427a256e82c02204a615b6d13105e6a122327ad99998814f3735c153d832ba0cfcfb85b6ad8f7f2
    # local_signature = 3045022100dc93b9ee55d5c0d332fb3766b4c5b745c98b029c71e144e4a031c17ed11b662602202bd7137f2a478eacd3b59a414f9f5d6b2191b078bb2dd9fb8111d6f39ec83ceb
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8006d0070000000000002200208848c43f1877825f0e466e034cadc5f208fbefb125a4210d35222f226bf88fd6d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036229d6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100dc93b9ee55d5c0d332fb3766b4c5b745c98b029c71e144e4a031c17ed11b662602202bd7137f2a478eacd3b59a414f9f5d6b2191b078bb2dd9fb8111d6f39ec83ceb01483045022100bf4fedf54e61057d3c2802d9ef49d74ec49272cf902113162d4d2427a256e82c02204a615b6d13105e6a122327ad99998814f3735c153d832ba0cfcfb85b6ad8f7f201475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 1)
    remote_htlc_signature = 3045022100a6d6190f056e3a2ff3e5d9abd763540d4533d3fb36d139808e36533d04be6c01022065de0eba3bbbb93a0392fbaba80aea934520ba8e7a43b35a14666258c58a476e
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 3045022100adfe34cd8d5c11b1542153c98c2c3f55759d495c17dbb1861cd950d3e788accf02204c41a9d94738b5f356009b5a8e7c2640f24002b1c243ba2a0de0c88972fabb57
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 3044022055a6858e222833bfdd21fb6fe3d2540210cebf7da46dd783b02cabf7aee3c7fc02200fd85d5a7436ace13df19dc151b791c2d7e9b005cb36959df4dfdedd78a7486e
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 3044022050eda9fee5215ce00698b93f5acf010a7e294210ef774e054a1c2efc7375c168022077a653d7126c0c8a64fd8282842d2a5df796175bcca15552e10aa041edf1053c
    # local_signature = 3045022100d1046a453bdfb920cfd26ed0992b95c28885c3f997ba090c47a472e2ecc969f00220426cc7643de88b42959011e27b9c8f9ac94b6350bd7dd18c913deae40bb02daa
    output htlc_success_tx 1: 020000000001017120d311a79957fd9ef845fc21a4e8554167822219663babeccc679493a2e9ce0000000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a6d6190f056e3a2ff3e5d9abd763540d4533d3fb36d139808e36533d04be6c01022065de0eba3bbbb93a0392fbaba80aea934520ba8e7a43b35a14666258c58a476e01483045022100d1046a453bdfb920cfd26ed0992b95c28885c3f997ba090c47a472e2ecc969f00220426cc7643de88b42959011e27b9c8f9ac94b6350bd7dd18c913deae40bb02daa012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    # local_signature = 3045022100e595b382fe3dfaeab2d4d5aa998cadff327163aa6d2554da48d938ba090077df02202f917f0e4d15bc290f4d45a3514712126eb81e7767ddc6759da921544dccc18f
    output htlc_timeout_tx 2: 020000000001017120d311a79957fd9ef845fc21a4e8554167822219663babeccc679493a2e9ce0100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100adfe34cd8d5c11b1542153c98c2c3f55759d495c17dbb1861cd950d3e788accf02204c41a9d94738b5f356009b5a8e7c2640f24002b1c243ba2a0de0c88972fabb5701483045022100e595b382fe3dfaeab2d4d5aa998cadff327163aa6d2554da48d938ba090077df02202f917f0e4d15bc290f4d45a3514712126eb81e7767ddc6759da921544dccc18f01006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6822a10700
    # local_signature = 304402203a80f7d7eb05a540c3d6941150cdacc802f585c7b9e211fe89e3c111e5251e0202201e5a4829d2b3a23a659e2ca0bc668bca1db4e142f2dddc9d8701833725293861
    output htlc_timeout_tx 3: 020000000001017120d311a79957fd9ef845fc21a4e8554167822219663babeccc679493a2e9ce02000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022055a6858e222833bfdd21fb6fe3d2540210cebf7da46dd783b02cabf7aee3c7fc02200fd85d5a7436ace13df19dc151b791c2d7e9b005cb36959df4dfdedd78a7486e0147304402203a80f7d7eb05a540c3d6941150cdacc802f585c7b9e211fe89e3c111e5251e0202201e5a4829d2b3a23a659e2ca0bc668bca1db4e142f2dddc9d870183372529386101006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6823a10700
    # local_signature = 304402205fc768e35333166142362da76c8585352b843403e369831883d894d1c1871c7002200f99e01dca04820c1068667bd00b796518e8c71769ad12939c629a5495db3e91
    output htlc_success_tx 4: 020000000001017120d311a79957fd9ef845fc21a4e8554167822219663babeccc679493a2e9ce03000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022050eda9fee5215ce00698b93f5acf010a7e294210ef774e054a1c2efc7375c168022077a653d7126c0c8a64fd8282842d2a5df796175bcca15552e10aa041edf1053c0147304402205fc768e35333166142362da76c8585352b843403e369831883d894d1c1871c7002200f99e01dca04820c1068667bd00b796518e8c71769ad12939c629a5495db3e91012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 6 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2168
    # base commitment transaction fee = 3061
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6984939 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100f416a7f07a7e49e392b9df16ef653d2eed491fc8886d7685a06bb56b88d78632022079f045a59226b7306f8cb9e102f4e15e8da06493095e697ab8b53a27b4a0b3c4
    # local_signature = 3045022100d8822c4a9124533913f508dd07adfd106d9c5b85960832958203c712fe5a0f3d02205cabbc92abf1ada1cfaf631164b754f640141956e753925ebeec4072321be238
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8006d0070000000000002200208848c43f1877825f0e466e034cadc5f208fbefb125a4210d35222f226bf88fd6d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036eb946a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100d8822c4a9124533913f508dd07adfd106d9c5b85960832958203c712fe5a0f3d02205cabbc92abf1ada1cfaf631164b754f640141956e753925ebeec4072321be23801483045022100f416a7f07a7e49e392b9df16ef653d2eed491fc8886d7685a06bb56b88d78632022079f045a59226b7306f8cb9e102f4e15e8da06493095e697ab8b53a27b4a0b3c401475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 1)
    remote_htlc_signature = 3045022100e5b3e3c0061ee9162e0a9ffed3b6b53a253156af3a6654c3512687206eb7215402207709e91f0d9ff65e66d42de5456d17a693d04d4bbed4c7f18cfb0e2751a7b1a4
    # signature for output 1 (htlc 2)
    remote_htlc_signature = 3045022100f8bf3bd7991c2f5e7bb7a1b2face90461f14dc0598a71ae558901993e01706aa0220679661e17b4e69731c4caabfa1a38a7ea026c32d4b0a7edb89c4ac99100ab184
    # signature for output 2 (htlc 3)
    remote_htlc_signature = 3044022010883d7fe56ffc224ae4b5f9e3b2bc2a864383fdd90c10b97dd144f1fa51bae6022027d7d01c7ab2b2abb9917b6d40356268ea5e2ec53189d714d16c6e141b96c7a5
    # signature for output 3 (htlc 4)
    remote_htlc_signature = 3045022100a207b6b85acf67220e076197e5532157e853498d785859a8196fae23d2958b3e022037c0fbe7483c761d3d3aec6d0c13c454c2bc3acce96c75e2c82d18862df73c04
    # local_signature = 30450221009dd988030a6ee1e0ab796a372c64959a760cef39d83663a53a1812018d74154702203ee8b22e023aba76da075539661975efaca72abc71133117d74a5bf8c9f0aad9
    output htlc_success_tx 1: 02000000000101d758d71c2c15f25707106ccad36798f21123dc7faf791ee231b102a4f341602c0000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e5b3e3c0061ee9162e0a9ffed3b6b53a253156af3a6654c3512687206eb7215402207709e91f0d9ff65e66d42de5456d17a693d04d4bbed4c7f18cfb0e2751a7b1a4014830450221009dd988030a6ee1e0ab796a372c64959a760cef39d83663a53a1812018d74154702203ee8b22e023aba76da075539661975efaca72abc71133117d74a5bf8c9f0aad9012001010101010101010101010101010101010101010101010101010101010101016e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    # local_signature = 3045022100e3e41b5b0b4f099be0a25f8479888a97c377ef8d79427c8579e1cbdb8479bef9022073676348fb39f22a42584ba07904d1dd145e11f83bedc605237005a077eb4351
    output htlc_timeout_tx 2: 02000000000101d758d71c2c15f25707106ccad36798f21123dc7faf791ee231b102a4f341602c0100000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f8bf3bd7991c2f5e7bb7a1b2face90461f14dc0598a71ae558901993e01706aa0220679661e17b4e69731c4caabfa1a38a7ea026c32d4b0a7edb89c4ac99100ab18401483045022100e3e41b5b0b4f099be0a25f8479888a97c377ef8d79427c8579e1cbdb8479bef9022073676348fb39f22a42584ba07904d1dd145e11f83bedc605237005a077eb435101006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6822a10700
    # local_signature = 304502210088f272bf79c5ebb31b0b7e84d3a156e71fe1fee0c15c4b4b38faef5e65842f1e02201fb8ca637cb79408f23dce583fc3e14a79518aed72355b2c6313cd545e6541ce
    output htlc_timeout_tx 3: 02000000000101d758d71c2c15f25707106ccad36798f21123dc7faf791ee231b102a4f341602c0200000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022010883d7fe56ffc224ae4b5f9e3b2bc2a864383fdd90c10b97dd144f1fa51bae6022027d7d01c7ab2b2abb9917b6d40356268ea5e2ec53189d714d16c6e141b96c7a50148304502210088f272bf79c5ebb31b0b7e84d3a156e71fe1fee0c15c4b4b38faef5e65842f1e02201fb8ca637cb79408f23dce583fc3e14a79518aed72355b2c6313cd545e6541ce01006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6823a10700
    # local_signature = 3045022100851c46585b5767505d64adf6ea649baa9e9083644b7d5085531f0a08d8bce81f022068783651ba904b531504e6c0b9da4af8b712cfb291182423555ba02e15305a9e
    output htlc_success_tx 4: 02000000000101d758d71c2c15f25707106ccad36798f21123dc7faf791ee231b102a4f341602c03000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a207b6b85acf67220e076197e5532157e853498d785859a8196fae23d2958b3e022037c0fbe7483c761d3d3aec6d0c13c454c2bc3acce96c75e2c82d18862df73c0401483045022100851c46585b5767505d64adf6ea649baa9e9083644b7d5085531f0a08d8bce81f022068783651ba904b531504e6c0b9da4af8b712cfb291182423555ba02e15305a9e012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2169
    # base commitment transaction fee = 2689
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6985311 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402202b08c5cffc5cce1ea07e5ea12aebd8bfce8dd48a7d9ee201c62ee3bbbebd20c4022054efe813ed9afe256b9de2b742db09222277b8d6ab7d05186b3fd9796eac2e8a
    # local_signature = 304402201df8e980323da68768388d1e3de84c0999c3a78c01ab021055f2ca814bb80f250220538b000ccdb3af1da66d5eba821d3058c1c288e5aea3be2a6fac6362ee2e95bb
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8005d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0365f966a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402201df8e980323da68768388d1e3de84c0999c3a78c01ab021055f2ca814bb80f250220538b000ccdb3af1da66d5eba821d3058c1c288e5aea3be2a6fac6362ee2e95bb0147304402202b08c5cffc5cce1ea07e5ea12aebd8bfce8dd48a7d9ee201c62ee3bbbebd20c4022054efe813ed9afe256b9de2b742db09222277b8d6ab7d05186b3fd9796eac2e8a01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 304402200d86deea6bcd4aafad2d8aea36492ef71d8f0349d00616b58b2536d2d0aaf76602201c759581006b116e4f95357b1d075c20f9807e9b73e4585f9101af275699dc8d
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 3045022100dcbc8baa0ab16650f4feb964c1fc6792dc0d06ca58280fb3ef35b8656568791d02207273c7c7e0a56e5cf91e11a9a98846392678f38507ddbef5ae522ca5bda0f960
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 3044022022d44cbf70aabbe611da6673638a126520043fa7e1114364e148ac647fb46084022078d338f2dbeb7490ad8032db0acde3c2ba5d9b82954d191504eb7d9bebdd40f8
    # local_signature = 304402201b2f9f3b4b738fe6ef65ecc1b0c7c681457282e3f3d9bfbe3ef8f165544eb6af0220300a1069930812c560e88288affaa345cf68b03ab8904ae06fe0580fdff9404a
    output htlc_timeout_tx 2: 020000000001011867fa0ec7c8df02396b9ed1e52dfee7b0983b1ec6873b34575a387ad79e372e0000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402200d86deea6bcd4aafad2d8aea36492ef71d8f0349d00616b58b2536d2d0aaf76602201c759581006b116e4f95357b1d075c20f9807e9b73e4585f9101af275699dc8d0147304402201b2f9f3b4b738fe6ef65ecc1b0c7c681457282e3f3d9bfbe3ef8f165544eb6af0220300a1069930812c560e88288affaa345cf68b03ab8904ae06fe0580fdff9404a01006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6822a10700
    # local_signature = 3044022034115c1c161321fbd1a3c0c807289c650e500f55267ba558bfeb4e366766cec7022018f0429b646da77cca48727526ba21a1e304314e7590527150bf168cd85e04ab
    output htlc_timeout_tx 3: 020000000001011867fa0ec7c8df02396b9ed1e52dfee7b0983b1ec6873b34575a387ad79e372e0100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100dcbc8baa0ab16650f4feb964c1fc6792dc0d06ca58280fb3ef35b8656568791d02207273c7c7e0a56e5cf91e11a9a98846392678f38507ddbef5ae522ca5bda0f96001473044022034115c1c161321fbd1a3c0c807289c650e500f55267ba558bfeb4e366766cec7022018f0429b646da77cca48727526ba21a1e304314e7590527150bf168cd85e04ab01006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6823a10700
    # local_signature = 30450221008623caa51320f3725cc2bc7bb2727f4093ffbddeb42d677b22391b91440edd7f02205daf373bdc407006d1bec1bc3032233cf754b50672e65b5e3d4e6f995765b2dc
    output htlc_success_tx 4: 020000000001011867fa0ec7c8df02396b9ed1e52dfee7b0983b1ec6873b34575a387ad79e372e02000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022022d44cbf70aabbe611da6673638a126520043fa7e1114364e148ac647fb46084022078d338f2dbeb7490ad8032db0acde3c2ba5d9b82954d191504eb7d9bebdd40f8014830450221008623caa51320f3725cc2bc7bb2727f4093ffbddeb42d677b22391b91440edd7f02205daf373bdc407006d1bec1bc3032233cf754b50672e65b5e3d4e6f995765b2dc012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 5 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2294
    # base commitment transaction fee = 2844
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6985156 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 304402206c8e7abfd7fade1d2d57aa449a8b4291a24703071a3870f6d3b8db4ad0414c76022054b1fa47edc5d4defc39ae07f689efe4920f75b7b1fc8d4793343d6620723f0c
    # local_signature = 3045022100a298a093a8319b01b730289d08df8a7ad0dcc5a83ff33018be612853600341b6022016193a18ac1400505a1765cb22572346186e883a182247672733701e0f842599
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8005d007000000000000220020a736f71c05ae323c2d1821f88e8b3b5563f9048ad6d63b27ce528722eda10f14b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036c4956a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100a298a093a8319b01b730289d08df8a7ad0dcc5a83ff33018be612853600341b6022016193a18ac1400505a1765cb22572346186e883a182247672733701e0f8425990147304402206c8e7abfd7fade1d2d57aa449a8b4291a24703071a3870f6d3b8db4ad0414c76022054b1fa47edc5d4defc39ae07f689efe4920f75b7b1fc8d4793343d6620723f0c01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature = 304402205a22ced46c6aa93736ddbcc2ce4a60c9feb90299071111a65b724c270162c528022011fd451961430415ccc681b999a307a5d54d85f1ac9f66e336a951e5fa33efd3
    # signature for output 1 (htlc 3)
    remote_htlc_signature = 3045022100ae9de3454d9a3db4e390262800095585dd9f01a6bfb4891df028ed8c75bf5efe022046b15e12147201379b50ba09b8430790dc90a2340323441b3a8c936a55387e44
    # signature for output 2 (htlc 4)
    remote_htlc_signature = 304402207714354358de126e92e496987a0e3497e38698c52b0a4056e416051fef9e2b2c02206cd1590f81beab71f8cc8c7ac318877633f60d7d5137fd365adb0a99ddc22622
    # local_signature = 3045022100dc4384cd8d97b8265147b63705476aee9f3263ad33d9301d6ded8f95916337a4022075c0d9cd1b4606e34e3e2275b927e3e61971817820441a4d2215c766d6df9ad9
    output htlc_timeout_tx 2: 02000000000101d0a2f599eee811845efa4b7c63e142a9a823043cf40e572a837bb83cefab829400000000000000000001cd010000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402205a22ced46c6aa93736ddbcc2ce4a60c9feb90299071111a65b724c270162c528022011fd451961430415ccc681b999a307a5d54d85f1ac9f66e336a951e5fa33efd301483045022100dc4384cd8d97b8265147b63705476aee9f3263ad33d9301d6ded8f95916337a4022075c0d9cd1b4606e34e3e2275b927e3e61971817820441a4d2215c766d6df9ad901006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6822a10700
    # local_signature = 3045022100a3f5a14d22ee3d507ff7a4d2d7bb1dd98ed93cd71e782f37c31710444ff59f1d02207899825f44c01e29ab3f9af48889022400e15df48eaa8a171a5f1a85830deea2
    output htlc_timeout_tx 3: 02000000000101d0a2f599eee811845efa4b7c63e142a9a823043cf40e572a837bb83cefab829401000000000000000001b5050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100ae9de3454d9a3db4e390262800095585dd9f01a6bfb4891df028ed8c75bf5efe022046b15e12147201379b50ba09b8430790dc90a2340323441b3a8c936a55387e4401483045022100a3f5a14d22ee3d507ff7a4d2d7bb1dd98ed93cd71e782f37c31710444ff59f1d02207899825f44c01e29ab3f9af48889022400e15df48eaa8a171a5f1a85830deea201006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6823a10700
    # local_signature = 304402206ae480ca410d04aceae660ba65fac848768734c5fcc74bd94827956442d5735102201b6a375d3d601f37ec177f2841f7ea004a4e64ce494a436ee0506bafbd36b1e7
    output htlc_success_tx 4: 02000000000101d0a2f599eee811845efa4b7c63e142a9a823043cf40e572a837bb83cefab8294020000000000000000019d090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402207714354358de126e92e496987a0e3497e38698c52b0a4056e416051fef9e2b2c02206cd1590f81beab71f8cc8c7ac318877633f60d7d5137fd365adb0a99ddc226220147304402206ae480ca410d04aceae660ba65fac848768734c5fcc74bd94827956442d5735102201b6a375d3d601f37ec177f2841f7ea004a4e64ce494a436ee0506bafbd36b1e7012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2295
    # base commitment transaction fee = 2451
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6985549 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 30440220330664bc5b297541b1518eb4622be2d52f0cc7d3e5bc2c9c7ffc59775539cd21022077225c0f022fef2481a18841b1d6e95f96f06c78550d267a1485f71eec677ad9
    # local_signature = 3045022100c6e4a7d022e365a611c39c039da6062938d4f9ed00848bf59d7b86f820fe57eb0220432c5b71f6242ae0d8f0e304105b5d20448b85070e801ad600c433f948982941
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8004b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0364d976a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100c6e4a7d022e365a611c39c039da6062938d4f9ed00848bf59d7b86f820fe57eb0220432c5b71f6242ae0d8f0e304105b5d20448b85070e801ad600c433f948982941014730440220330664bc5b297541b1518eb4622be2d52f0cc7d3e5bc2c9c7ffc59775539cd21022077225c0f022fef2481a18841b1d6e95f96f06c78550d267a1485f71eec677ad901475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3045022100c2a6a6e7ebc2097eb47f1613f9083a1ae6e4ae01c0d103f30bd7dcee39608650022013ace2e27cd06c3d563d97a79acf9ec23ad4a2cc8c16d9a4cd58d74fa3810c05
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 3045022100b36f62acfe05597fbca2483178b07ef85f04b560342e29df46f3607a4ccd7f7f022041c111201f9ebbe8ec8d7ebce7ad316b99510e1590024a15e4ccd579408c1a93
    # local_signature = 3045022100925e4297b71f0db4d48834bba893bce16c316e9c47c5d9b246199504fd6ec582022036759f1dd7056f64395a90decf2ceea96a62dc35abafd8d14909a18390cf1f29
    output htlc_timeout_tx 3: 02000000000101cf88984f750ee561aaa1ce043fb30e11475ff8b65a7a73bd88c7a7d2be47351f00000000000000000001b5050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100c2a6a6e7ebc2097eb47f1613f9083a1ae6e4ae01c0d103f30bd7dcee39608650022013ace2e27cd06c3d563d97a79acf9ec23ad4a2cc8c16d9a4cd58d74fa3810c0501483045022100925e4297b71f0db4d48834bba893bce16c316e9c47c5d9b246199504fd6ec582022036759f1dd7056f64395a90decf2ceea96a62dc35abafd8d14909a18390cf1f2901006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6823a10700
    # local_signature = 3044022043c42c82827c36376137089df87616b848286b913db6b4cc38bc9749939b74e802203bb3242fe71aa424706604215af22410cdd05cb094a45e0cba41e266261d5def
    output htlc_success_tx 4: 02000000000101cf88984f750ee561aaa1ce043fb30e11475ff8b65a7a73bd88c7a7d2be47351f010000000000000000019d090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100b36f62acfe05597fbca2483178b07ef85f04b560342e29df46f3607a4ccd7f7f022041c111201f9ebbe8ec8d7ebce7ad316b99510e1590024a15e4ccd579408c1a9301473044022043c42c82827c36376137089df87616b848286b913db6b4cc38bc9749939b74e802203bb3242fe71aa424706604215af22410cdd05cb094a45e0cba41e266261d5def012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 4 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3872
    # base commitment transaction fee = 4135
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6983865 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022009b4de087a6bf37e0653cbbc6f274d44dcae079576f906ad80bf900fab1ccec50220781232f50d2caba921087b682e57de1b5bc79a74e1fe061fa2d478a2acb630c1
    # local_signature = 3044022079ac374642fa8f55f706305cb088c14b936f0bd289535217622d6644547ed8ee02207ca6c8414fb24f7457036b46e490c9ba5adc2a4a8d98ad17293424cba1156ade
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8004b80b0000000000002200205e984a3f84e6f0e09d7b3f4685c37f9c78eae32dd1a97e3fdd55d78e414d6c39a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036b9906a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022079ac374642fa8f55f706305cb088c14b936f0bd289535217622d6644547ed8ee02207ca6c8414fb24f7457036b46e490c9ba5adc2a4a8d98ad17293424cba1156ade01473044022009b4de087a6bf37e0653cbbc6f274d44dcae079576f906ad80bf900fab1ccec50220781232f50d2caba921087b682e57de1b5bc79a74e1fe061fa2d478a2acb630c101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature = 3045022100e805f3e273e5ed7eea480685dd9a9671b462bfce62aeddcd19824d3b8e5d14d202202472bc9b0c2789a88a338bd4368a673118c6e22b31e362870afc579f9a7ba595
    # signature for output 1 (htlc 4)
    remote_htlc_signature = 3045022100fe52a3c7a8872d192c44bcb887497d0fd8a867e57ac6a599e90f66260906b5ae0220364c5d07215c18e96816235c97de9d35db541a399b59f325e5857622fc6636ef
    # local_signature = 3044022026dd69b6542a93766e4b26bc70fd2bc1a51efcaf9e6a0315329c64efffca0da9022052fc15b82af74908471005531308d63a98711bf930998e3feaa9aa020e8142cc
    output htlc_timeout_tx 3: 020000000001010af0266704eda1287bc87635f735fe2e46de71c4bc2fcb22f81530432c08b30c0000000000000000000192010000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e805f3e273e5ed7eea480685dd9a9671b462bfce62aeddcd19824d3b8e5d14d202202472bc9b0c2789a88a338bd4368a673118c6e22b31e362870afc579f9a7ba59501473044022026dd69b6542a93766e4b26bc70fd2bc1a51efcaf9e6a0315329c64efffca0da9022052fc15b82af74908471005531308d63a98711bf930998e3feaa9aa020e8142cc01006e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6823a10700
    # local_signature = 3045022100e8e04ab1eedb20ba7786bc1d43c5a87d07d2c5f01eb733d7c68548869b70a857022018070239cf505e9c08feb776c28b4caf1430343b0a3b41b40cb1ba8361ff6b3e
    output htlc_success_tx 4: 020000000001010af0266704eda1287bc87635f735fe2e46de71c4bc2fcb22f81530432c08b30c010000000000000000017a050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100fe52a3c7a8872d192c44bcb887497d0fd8a867e57ac6a599e90f66260906b5ae0220364c5d07215c18e96816235c97de9d35db541a399b59f325e5857622fc6636ef01483045022100e8e04ab1eedb20ba7786bc1d43c5a87d07d2c5f01eb733d7c68548869b70a857022018070239cf505e9c08feb776c28b4caf1430343b0a3b41b40cb1ba8361ff6b3e012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3873
    # base commitment transaction fee = 3470
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6984530 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022032ebb782359c55a1352137cc36743a776e3e504769db7eae69a206434afd775802202db8de2715cce9947dd1166b30aae6a4f78433610c247f1faabe5d6d483546c6
    # local_signature = 3045022100cd105a6c7efdc436709813237bb6a29bdba47b9b3310bec571df800f692f335402203e537e538773a33cb8e7fdfbb5c1bee2f7da1afefa8596726c5061653f8534a3
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8003a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03652936a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100cd105a6c7efdc436709813237bb6a29bdba47b9b3310bec571df800f692f335402203e537e538773a33cb8e7fdfbb5c1bee2f7da1afefa8596726c5061653f8534a301473044022032ebb782359c55a1352137cc36743a776e3e504769db7eae69a206434afd775802202db8de2715cce9947dd1166b30aae6a4f78433610c247f1faabe5d6d483546c601475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 3045022100a2764b4f5996760b339359c347cb8713a9130ddf7b20966beeb09e9d86a76a670220449838aa31dfd7b4494e472f9ace88624328bb1042a3b98397384d93f4f6f7df
    # local_signature = 304402206b277668c86614f691ebd9f73accd95df4fe09309f7a0da5a99073916c3a121a02202fb5fd15b86b8dd5b4b98f747c3d0d23bef10afc423f16bb4bfe2a8eb1351387
    output htlc_success_tx 4: 020000000001013201046b1e80901949913b3834b4f87e7b376fa1aac0c017afd1f7a57920c106000000000000000000017a050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a2764b4f5996760b339359c347cb8713a9130ddf7b20966beeb09e9d86a76a670220449838aa31dfd7b4494e472f9ace88624328bb1042a3b98397384d93f4f6f7df0147304402206b277668c86614f691ebd9f73accd95df4fe09309f7a0da5a99073916c3a121a02202fb5fd15b86b8dd5b4b98f747c3d0d23bef10afc423f16bb4bfe2a8eb1351387012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 3 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5149
    # base commitment transaction fee = 4613
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac68
    # to-local amount 6983387 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3045022100b47cd8b98e3bf3e54909995826153534e4260e3be71691f252a35543172e608302201ad3aae15f6101e9b91d209ba3c2afdcd0ef723add884a27a4d84e94c195f499
    # local_signature = 304402201a26ed7a4036667252d9d3f1cbcf6a6d9965d109ad10e132b7cf993a2a5ffb2502206afd0c14395689ce10258db51b9110c70ef61d559a948fe4bdbecfa365e71c81
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8003a00f0000000000002200207bc2a7bc6010011781444f13c1f0144477f3d6fd11798936e5cc9decfbf1531ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036db8e6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402201a26ed7a4036667252d9d3f1cbcf6a6d9965d109ad10e132b7cf993a2a5ffb2502206afd0c14395689ce10258db51b9110c70ef61d559a948fe4bdbecfa365e71c8101483045022100b47cd8b98e3bf3e54909995826153534e4260e3be71691f252a35543172e608302201ad3aae15f6101e9b91d209ba3c2afdcd0ef723add884a27a4d84e94c195f49901475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature = 30450221008579a67d5fe8bc6bc64f096c3bfba8ade838771c2b6bc7f56cee2aba349572da02204327b447c7e8cfd65a013466cba416fc192577faa7b1b4a70c6e16757ea1e955
    # local_signature = 3045022100d330e4e2d7134fd3bf54c38f9c9fa08f503932021a5446903ed34d1307db23760220177f00536926d0afda24af87dc5356a18cb905396cd6b2e99e8559f0e2ce4874
    output htlc_success_tx 4: 020000000001019bbbfb56f9cdd272f505dc15e38ac4edb3ce93e6a1463579410d40da5012a1cb0000000000000000000121020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221008579a67d5fe8bc6bc64f096c3bfba8ade838771c2b6bc7f56cee2aba349572da02204327b447c7e8cfd65a013466cba416fc192577faa7b1b4a70c6e16757ea1e95501483045022100d330e4e2d7134fd3bf54c38f9c9fa08f503932021a5446903ed34d1307db23760220177f00536926d0afda24af87dc5356a18cb905396cd6b2e99e8559f0e2ce4874012004040404040404040404040404040404040404040404040404040404040404046e21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae6775029000b175ac6800000000
    
    name: commitment tx with 2 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 5150
    # base commitment transaction fee = 3728
    # to-local amount 6984272 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022050b1418c8c39ffd83477ce8bbab1935b601f5a38bfe47a6ce6a8a23fb578fb8202202ddf960dbae2e535e852806ce5b9f9048643645582ded8a1a232b4a60c022ebe
    # local_signature = 3045022100b53a62ee656234579adf85883123b06c9d474d5ed85f06222ad28f9b0ddc207202204d2f3e3c8a9be5f2437b9b9c8e6671f67676b68aa190aae018cad5da4097d6cc
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03650926a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100b53a62ee656234579adf85883123b06c9d474d5ed85f06222ad28f9b0ddc207202204d2f3e3c8a9be5f2437b9b9c8e6671f67676b68aa190aae018cad5da4097d6cc01473044022050b1418c8c39ffd83477ce8bbab1935b601f5a38bfe47a6ce6a8a23fb578fb8202202ddf960dbae2e535e852806ce5b9f9048643645582ded8a1a232b4a60c022ebe01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0
    
    name: commitment tx with 2 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651180
    # base commitment transaction fee = 6987454
    # to-local amount 546 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    remote_signature = 3044022051492da22d3e86db160944338466f4d816ca6007ffa2f9031309b877974e7f4f02207f6fd5f316c3a0cbdea132c4068162c1c213a06bd4e1ac305422558d1080b013
    # local_signature = 3044022046d08c9e4c1bb4dcd9bef1f0645f8085f76629adae09a9bac95c6e6e38b00ed6022053dda88480c400fdd7e957637073e66df5bc6669d92884dba97e174203c1b650
    output commit_tx: 0200000000010142a26bb3a430a536cf9e3a8ce2cbcb0427c29ec6c7d647175cfc78328b57fba7010000000038b02b800222020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0360400473044022046d08c9e4c1bb4dcd9bef1f0645f8085f76629adae09a9bac95c6e6e38b00ed6022053dda88480c400fdd7e957637073e66df5bc6669d92884dba97e174203c1b65001473044022051492da22d3e86db160944338466f4d816ca6007ffa2f9031309b877974e7f4f02207f6fd5f316c3a0cbdea132c4068162c1c213a06bd4e1ac305422558d1080b01301475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
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

