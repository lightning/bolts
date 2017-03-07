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

This output sends funds to a HTLC-timeout transaction after the HTLC timeout, or to the remote peer using the payment preimage or the revocation key.  The output is a P2WSH, with a witness script:

    # To you with revocation key
    OP_DUP OP_HASH160 <revocationkey-hash> OP_EQUAL
    OP_IF
        OP_CHECKSIG
    OP_ELSE
        <remotekey> OP_SWAP OP_SIZE 32 OP_EQUAL
        OP_NOTIF
            # To me via HTLC-timeout transaction (timelocked).
            OP_DROP 2 OP_SWAP <localkey> 2 OP_CHECKMULTISIG
        OP_ELSE
            # To you with preimage.
            OP_HASH160 <ripemd-of-payment-hash> OP_EQUALVERIFY
            OP_CHECKSIG
        OP_ENDIF
    OP_ENDIF

The remote node can redeem the HTLC with the witness:

    <remotesig> <payment-preimage>

If a revoked commitment transaction is published, the remote node can spend this output immediately with the following witness:

    <revocation-sig> <revocationkey>

The sending node can use the HTLC-timeout transaction to time out the HTLC once the HTLC is expired, as shown below.

#### Received HTLC Outputs

This output sends funds to the remote peer after the HTLC timeout or using the revocation key, or to an HTLC-success transaction with a successful payment preimage. The output is a P2WSH, with a witness script:

    # To you with revocation key
    OP_DUP OP_HASH160 <revocationkey-hash> OP_EQUAL
    OP_IF
        OP_CHECKSIG
    OP_ELSE
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
    OP_ENDIF

To timeout the htlc, the remote node spends it with the witness:

    <remotesig> 0

If a revoked commitment transaction is published, the remote node can spend this output immediately with the following witness:

    <revocation-sig> <revocation-key>

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
    HTLC-timeout weight: 663
    HTLC-success weight: 703

Note that we refer to the "base fee" for a commitment transaction in the requirements below, which is what the funder pays.  The actual fee may be higher than the amount calculated here, due to rounding and trimmed outputs.

#### Requirements

The fee for an HTLC-timeout transaction MUST BE calculated to match:

1. Multiply `feerate-per-kw` by 663 and divide by 1000 (rounding down).

The fee for an HTLC-success transaction MUST BE calculated to match:

1. Multiply `feerate-per-kw` by 703 and divide by 1000 (rounding down).

The base fee for a commitment transaction MUST BE calculated to match:

1. Start with `weight` = 724.

2. For each committed HTLC, if that output is not trimmed as specified in
   [Trimmed Outputs](#trimmed-outputs), add 172 to `weight`.

3. Multiply `feerate-per-kw` by `weight`, divide by 1000 (rounding down).

#### Example

For example, suppose that we have a `feerate-per-kw` of 5000, a `dust-limit-satoshis` of 546 satoshis, and commitment transaction with:
* 2 offered HTLCs of 5000000 and 1000000 millisatoshis (5000 and 1000 satoshis)
* 2 received HTLCs of 7000000 and 800000 millisatoshis (7000 and 800 satoshis)

The HTLC timeout transaction weight is 663, thus fee would be 3315 satoshis.
The HTLC success transaction weight is 703, thus fee would be 3515 satoshis

The commitment transaction weight would be calculated as follows:

* weight starts at 724.

* The offered HTLC of 5000 satoshis is above 546 + 3315 and would result in:
  * an output of 5000 satoshi in the commitment transaction
  * a HTLC timeout transaction of 5000 - 3145 satoshis which spends this output
  * weight increases to 896

* The offered HTLC of 1000 satoshis is below 546 + 3315, so would be trimmed.

* The received HTLC of 7000 satoshis is above 546 + 3590 and would result in:
  * an output of 7000 satoshi in the commitment transaction
  * a HTLC success transaction of 7000 - 3590 satoshis which spends this output
  * weight increases to 1068

* The received HTLC of 800 satoshis is below 546 + 3515 so would be trimmed.

The base commitment transaction fee would be 5340 satoshi; the actual
fee (adding the 1000 and 800 satoshi HTLCs which would have made dust
outputs) is 7140 satoshi.  The final fee may even be more if the
`to-local` or `to-remote` outputs fall below `dust-limit-satoshis`.

### Fee Payment

Base commitment transaction fees will be extracted from the funder's amount, or if that is insufficient, will use the entire amount of the funder's output.

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

    accepted_htlc_script: 139 bytes
        - OP_DUP: 1 byte
        - OP_HASH160: 1 byte
        - OP_DATA: 1 byte (revocationkey-hash length)
        - revocationkey-hash: 20 bytes
        - OP_EQUAL: 1 byte
        - OP_IF: 1 byte
        - OP_CHECKSIG: 1 byte
        - OP_ELSE: 1 byte
        - OP_DATA: 1 byte (remotekey length)
        - remotekey: 33 bytes
        - OP_SWAP: 1 byte
        - OP_SIZE: 1 byte
        - 32: 2 bytes
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
        - OP_ENDIF: 1 byte

    offered_htlc_script: 133 bytes
        - OP_DUP: 1 byte
        - OP_HASH160: 1 byte
        - OP_DATA: 1 byte (revocationkey-hash length)
        - revocationkey-hash: 20 bytes
        - OP_EQUAL: 1 byte
        - OP_IF: 1 byte
        - OP_CHECKSIG: 1 byte
        - OP_ELSE: 1 byte
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
        - OP_ENDIF: 1 byte

    timeout_witness: 285 bytes
		- number_of_witness_elements: 1 byte
		- nil_length: 1 byte
		- sig_alice_length: 1 byte
		- sig_alice: 73 bytes
		- sig_bob_length: 1 byte
		- sig_bob: 73 bytes
		- nil_length: 1 byte
		- witness_script_length: 1 byte
		- witness_script (offered_htlc_script)

    success_witness: 325 bytes
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

    htlc_output: 43 bytes
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
			htlc_output
		- lock_time: 4 bytes

Multiplying non-witness data by 4, this gives a weight of 376.  Adding
the witness data for each case (285 + 2 for HTLC-timeout, 325 + 2 for
HTLC-success) gives a weight of:

	663 (HTLC-timeout)
	703 (HTLC-success)

# Appendix C: Funding Transaction Test Vectors

In the following:
 - we assume that *local* is the funder
 - private keys are displayed as 32 bytes plus a trailing 1 (bitcoin's convention for "compressed" private keys, i.e. keys for which the public key is compressed)
 - transaction signatures are all deterministic, using RFC6979 (using HMAC-SHA256)

The input for the funding transaction was created using a test chain
with the following first two blocks, the second one with a spendable
coinbase (note that such a P2PKH input is inadvisable as detailed in [BOLT #2](02-peer-protocol.md#the-funding_created-message), but provides the simplest example):

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
    local_feerate_per_kw: 15000
    # base commitment transaction fee = 10860
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6989140 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 304402205fdea103b8eb092e46362bbc8d80c790dd3756db2474baaf538bf96039a2670c02206dc19fb7e152382887018f5f76047d0b0d75e0876f06663a49c59d8f6d40895401
    remote_signature: 3045022100f732ff890ea9af685f9577bd38f11ceb77f5ead254af663638bbf80bbfa180da022005bb3493d2ba28e6ea43db36d156f5c2befa5de469d118a321a3fd3f3f356dcd01
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03654a56a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402205fdea103b8eb092e46362bbc8d80c790dd3756db2474baaf538bf96039a2670c02206dc19fb7e152382887018f5f76047d0b0d75e0876f06663a49c59d8f6d40895401483045022100f732ff890ea9af685f9577bd38f11ceb77f5ead254af663638bbf80bbfa180da022005bb3493d2ba28e6ea43db36d156f5c2befa5de469d118a321a3fd3f3f356dcd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

    name: commitment tx with all 5 htlcs untrimmed (minimum feerate
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 0
    # base commitment transaction fee = 0
    # actual commitment transaction fee = 0
    # HTLC received amount 1000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f401b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f501b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6988000 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 3045022100dabc698daa9a1affd35b44b83beaaba5d78f7feb2de77eea75a1b6aa26c70f0b02207ca677bed690437a35e0a817363d83c42616db5ea6e6522173145c09a11e5d5701
    remote_signature: 3045022100e7564212fdec08e782390799593a363d8a7d79fb658abdba1cef67ea0a5f621902206c24282cae485cd43134861ba4f666397c55355e79b2015315904c1e010ae73a01
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8007e803000000000000220020b1990f5a65230fc39e4ef790f3907d8f1a587d15b0810e89f9a6c68343767a1ad0070000000000002200207fca09ebacdfe6a4f704e8e3c1767bee0ede006ca7107b4358b34eb96c50bacfd007000000000000220020d9d8939fbb5b6f47577992ec878bcc4ee58272696dcef62607e152c29b6cd995b80b00000000000022002013cb27c5d1f5f13a763a06fa3299218fb51504a84bd10809f2be730407ff1b72a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036e0a06a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100dabc698daa9a1affd35b44b83beaaba5d78f7feb2de77eea75a1b6aa26c70f0b02207ca677bed690437a35e0a817363d83c42616db5ea6e6522173145c09a11e5d5701483045022100e7564212fdec08e782390799593a363d8a7d79fb658abdba1cef67ea0a5f621902206c24282cae485cd43134861ba4f666397c55355e79b2015315904c1e010ae73a01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature: 3044022038c1ecb18f42fafa1558d34c41cabc473c1b2ce4025cadb08fef217b7d8e61f302204ae9ea4c869848d51dbf0044f9b8bf7b9691ba853670a983000c5af2e5db9ea301
    # signature for output 1 (htlc 1)
    remote_htlc_signature: 304402200484125dc1430266f9e9156cc2ab59670781b6fae87dd5cc41bd9913c568dac50220020bf414550a39a559b2b2ba2431c4cba562c00fd16aae809412132f00b1175c01
    # signature for output 2 (htlc 2)
    remote_htlc_signature: 3045022100e8e8aac4e31d2f6574df3414ead1ff33b0a5b27e19b36b542706587093932ba1022074b35e23a40f2db0db5d0b73392debcca7a05998beab2916f9ab38274f003bd701
    # signature for output 3 (htlc 3)
    remote_htlc_signature: 3045022100a2f77f721bed8b3d181ec324fa78632e145f74cc43d32f6934caf00e364995030220309d309b215a9dca1bd721f56434d509016cff414845753d18d17656de32986001
    # signature for output 4 (htlc 4)
    remote_htlc_signature: 30450221009b7b7aafcc807df5a151bc9d15247deb7e9b68dc434212a7fd425644f4c09eb302207a8a632ead288e9f10d807435b493416740d3ce29e5b47a5551ca9575f47ac5a01
    # local signature 304402202e8d081f0386f76cf7eccb674d278b92af3f9f2e13ece232dcdf76899798f7490220359a4bb41f0eb93840f12dbcd7564cb346f2d0a1b436338eaca45d61b680090001
    output htlc_success_tx 0: 0200000000010178ed57e0737ae43861bef7c080dd7689e49f0e7465994f8bed5c7e57a3d541b700000000000000000001e8030000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022038c1ecb18f42fafa1558d34c41cabc473c1b2ce4025cadb08fef217b7d8e61f302204ae9ea4c869848d51dbf0044f9b8bf7b9691ba853670a983000c5af2e5db9ea30147304402202e8d081f0386f76cf7eccb674d278b92af3f9f2e13ece232dcdf76899798f7490220359a4bb41f0eb93840f12dbcd7564cb346f2d0a1b436338eaca45d61b6800900012000000000000000000000000000000000000000000000000000000000000000009921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f401b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000
    # local signature 3045022100e019321dbc1304a22f824ef7842d6562eea06a5d17771f6aa490d306f60ca2be02205657043cbe93d5ca20466fb3b195f9a33e5a9e2d85627d15c3c285e93212834c01
    output htlc_success_tx 1: 0200000000010178ed57e0737ae43861bef7c080dd7689e49f0e7465994f8bed5c7e57a3d541b701000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402200484125dc1430266f9e9156cc2ab59670781b6fae87dd5cc41bd9913c568dac50220020bf414550a39a559b2b2ba2431c4cba562c00fd16aae809412132f00b1175c01483045022100e019321dbc1304a22f824ef7842d6562eea06a5d17771f6aa490d306f60ca2be02205657043cbe93d5ca20466fb3b195f9a33e5a9e2d85627d15c3c285e93212834c012001010101010101010101010101010101010101010101010101010101010101019921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f501b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000
    # local signature 3044022023c25f082b0095437ae4f4d467b9fbdcd5f43129e7c31e7ac96b4fb0e06939b702203a3df0e4eee9a1a29b4c8e0ef79249285638e4927f72ac0198e121989aec018f01
    output htlc_timeout_tx 2: 0200000000010178ed57e0737ae43861bef7c080dd7689e49f0e7465994f8bed5c7e57a3d541b702000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e8e8aac4e31d2f6574df3414ead1ff33b0a5b27e19b36b542706587093932ba1022074b35e23a40f2db0db5d0b73392debcca7a05998beab2916f9ab38274f003bd701473044022023c25f082b0095437ae4f4d467b9fbdcd5f43129e7c31e7ac96b4fb0e06939b702203a3df0e4eee9a1a29b4c8e0ef79249285638e4927f72ac0198e121989aec018f01008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local signature 3045022100d72c4203c2818332e0f4eaf82e4c3ab31d32b3b22e57e5b7f7b225f500789ebb02200ff78f4b3ecc6e502e50f9925b0f3f8fd5e13f0c9d0045c42157d60f42034c7701
    output htlc_timeout_tx 3: 0200000000010178ed57e0737ae43861bef7c080dd7689e49f0e7465994f8bed5c7e57a3d541b703000000000000000001b80b0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a2f77f721bed8b3d181ec324fa78632e145f74cc43d32f6934caf00e364995030220309d309b215a9dca1bd721f56434d509016cff414845753d18d17656de32986001483045022100d72c4203c2818332e0f4eaf82e4c3ab31d32b3b22e57e5b7f7b225f500789ebb02200ff78f4b3ecc6e502e50f9925b0f3f8fd5e13f0c9d0045c42157d60f42034c7701008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local signature 30450221009a151261208bb52d2b2972b503bf403532ea94ec1f803c7281ae5f4a48489dfa02205384911c7dfd44f5e7656e08ee83a70630e1ed9c75d84749d868d1e14a359b7901
    output htlc_success_tx 4: 0200000000010178ed57e0737ae43861bef7c080dd7689e49f0e7465994f8bed5c7e57a3d541b704000000000000000001a00f0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221009b7b7aafcc807df5a151bc9d15247deb7e9b68dc434212a7fd425644f4c09eb302207a8a632ead288e9f10d807435b493416740d3ce29e5b47a5551ca9575f47ac5a014830450221009a151261208bb52d2b2972b503bf403532ea94ec1f803c7281ae5f4a48489dfa02205384911c7dfd44f5e7656e08ee83a70630e1ed9c75d84749d868d1e14a359b79012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 7 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 633
    # base commitment transaction fee = 1002
    # actual commitment transaction fee = 1002
    # HTLC received amount 1000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f401b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f501b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6986998 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 3045022100fe6350065023bca5f1101e9512240db9d5498e9d500d4972a300901d61eb4c6002207f46f0235759d52919afdbcb01d89dc584c7af3012e8e45679333cfba700d13001
    remote_signature: 3045022100b97814fe4df75aae650c070f5cd417231970af1686d7f73275735d886156b05d0220052e9537b3ff5826cd7e82f0186ee9043cae0f6974ec442d6b3b4e8903ef9bd501
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8007e803000000000000220020b1990f5a65230fc39e4ef790f3907d8f1a587d15b0810e89f9a6c68343767a1ad0070000000000002200207fca09ebacdfe6a4f704e8e3c1767bee0ede006ca7107b4358b34eb96c50bacfd007000000000000220020d9d8939fbb5b6f47577992ec878bcc4ee58272696dcef62607e152c29b6cd995b80b00000000000022002013cb27c5d1f5f13a763a06fa3299218fb51504a84bd10809f2be730407ff1b72a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036f69c6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100fe6350065023bca5f1101e9512240db9d5498e9d500d4972a300901d61eb4c6002207f46f0235759d52919afdbcb01d89dc584c7af3012e8e45679333cfba700d13001483045022100b97814fe4df75aae650c070f5cd417231970af1686d7f73275735d886156b05d0220052e9537b3ff5826cd7e82f0186ee9043cae0f6974ec442d6b3b4e8903ef9bd501475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (htlc 0)
    remote_htlc_signature: 3045022100f5920bcb9567cee174eb06b8e8e29a9ecb1605208cccb4f7a402a0da58af928d02206889a4a1ce98a2e1c79d357769a5bdd74f95e48cc8b3501749783423a86a060901
    # signature for output 1 (htlc 1)
    remote_htlc_signature: 3045022100c3a25a2faf093f5b5b2f5ecef0b4ba5e16424316a5eba32649d7a6b41448fbd402203895febc3f5ce6cc0d629e9f6808ce9271873a8dccd07eb6271d4b5f913d4e2301
    # signature for output 2 (htlc 2)
    remote_htlc_signature: 30450221008ccea0eb640ba92ea1778ce9e44bd650ae22778d0f655d3d182d2445da560684022079d7eb827f7fab92c4aea19c57756a8d91035804a756ceeb83392cab21ac318d01
    # signature for output 3 (htlc 3)
    remote_htlc_signature: 3044022079eac866205ca8e7274cbf194dccc7a0f1a504ceea252e504d13dc2208712b6402204dc67e95f8532954e2aa617d8cdcf4d97311293c301e8b9aa2cab6324609f8d601
    # signature for output 4 (htlc 4)
    remote_htlc_signature: 304402204a7c48b23e29f3771ea13867646d0cceb61c371a6c6c052dade95041186e868c02200d15508115b07340e212a634fe029c77d30cecdfe035db229d9142fb7896ebc101
    # local signature 30440220768a159111a177add5a15227890866fd28ceb8a9d936ae2f4f2c42c993f1dbf402202dd7c8fb78664a970f1f6f030983bbcda9c51f8565ce09d8e5aab5cd3dfb014001
    output htlc_success_tx 0: 02000000000101808804573e07544dfec1226db93a232a921c8001693611bec48b2d79cd516ae00000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f5920bcb9567cee174eb06b8e8e29a9ecb1605208cccb4f7a402a0da58af928d02206889a4a1ce98a2e1c79d357769a5bdd74f95e48cc8b3501749783423a86a0609014730440220768a159111a177add5a15227890866fd28ceb8a9d936ae2f4f2c42c993f1dbf402202dd7c8fb78664a970f1f6f030983bbcda9c51f8565ce09d8e5aab5cd3dfb0140012000000000000000000000000000000000000000000000000000000000000000009921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f401b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000
    # local signature 30440220442d9864b014a51bf893bd0219dfead878aaaa6290f08345073a54565c4de34b022053f36c62f37c89078031c4d23c85fb746dcf107af59b678654c27e9a4126d72d01
    output htlc_success_tx 1: 02000000000101808804573e07544dfec1226db93a232a921c8001693611bec48b2d79cd516ae0010000000000000000010a060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100c3a25a2faf093f5b5b2f5ecef0b4ba5e16424316a5eba32649d7a6b41448fbd402203895febc3f5ce6cc0d629e9f6808ce9271873a8dccd07eb6271d4b5f913d4e23014730440220442d9864b014a51bf893bd0219dfead878aaaa6290f08345073a54565c4de34b022053f36c62f37c89078031c4d23c85fb746dcf107af59b678654c27e9a4126d72d012001010101010101010101010101010101010101010101010101010101010101019921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f501b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000
    # local signature 30440220374299bca4f2c7faa34207dd25bc666ac10084664e551cc8da3343efb769bfc502204fa914b98bc8d53176c4cdb74d850b03ec54448a5f9a6f7ce046683dfb45c3fc01
    output htlc_timeout_tx 2: 02000000000101808804573e07544dfec1226db93a232a921c8001693611bec48b2d79cd516ae00200000000000000000129060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221008ccea0eb640ba92ea1778ce9e44bd650ae22778d0f655d3d182d2445da560684022079d7eb827f7fab92c4aea19c57756a8d91035804a756ceeb83392cab21ac318d014730440220374299bca4f2c7faa34207dd25bc666ac10084664e551cc8da3343efb769bfc502204fa914b98bc8d53176c4cdb74d850b03ec54448a5f9a6f7ce046683dfb45c3fc01008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local signature 304402207321402614ec8d604af1d701725a24bbf563e463a44f011873a35bcf8951ca4302201af0c6bc443ec09b8c123ebfbd12411cbe9b2161fa03e094aa0f7bd7731c81be01
    output htlc_timeout_tx 3: 02000000000101808804573e07544dfec1226db93a232a921c8001693611bec48b2d79cd516ae003000000000000000001110a0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022079eac866205ca8e7274cbf194dccc7a0f1a504ceea252e504d13dc2208712b6402204dc67e95f8532954e2aa617d8cdcf4d97311293c301e8b9aa2cab6324609f8d60147304402207321402614ec8d604af1d701725a24bbf563e463a44f011873a35bcf8951ca4302201af0c6bc443ec09b8c123ebfbd12411cbe9b2161fa03e094aa0f7bd7731c81be01008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local signature 3044022051df0562fb628047ebb9a3453af55908617fbe0c4102cb248b4bcd7caf0b0b0e0220262dbf209f5b4a70ab25b215f5cf07433fb1fc1c93f5ea692495bf7ff7e27f1801
    output htlc_success_tx 4: 02000000000101808804573e07544dfec1226db93a232a921c8001693611bec48b2d79cd516ae004000000000000000001da0d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402204a7c48b23e29f3771ea13867646d0cceb61c371a6c6c052dade95041186e868c02200d15508115b07340e212a634fe029c77d30cecdfe035db229d9142fb7896ebc101473044022051df0562fb628047ebb9a3453af55908617fbe0c4102cb248b4bcd7caf0b0b0e0220262dbf209f5b4a70ab25b215f5cf07433fb1fc1c93f5ea692495bf7ff7e27f18012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 6 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 634
    # base commitment transaction fee = 895
    # actual commitment transaction fee = 1895
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f501b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6987105 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 3045022100e1c5157d9ac24eea2ead29c12c26e2f8efdabcbbfc7abc73d5d0faa5cb85503102207bb244b9a2877a5bc6232ad88561f3ad02de54217dcf02bbe1b28bd51318fb6901
    remote_signature: 3045022100b88d68334f6699ac0b10aec7d0f7274628249517181c148119da7cc37cdc98b9022040ff3ed18cec6fa06bfb6a404393d073157e3eb5451904499b79e91a1011879c01
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d0070000000000002200207fca09ebacdfe6a4f704e8e3c1767bee0ede006ca7107b4358b34eb96c50bacfd007000000000000220020d9d8939fbb5b6f47577992ec878bcc4ee58272696dcef62607e152c29b6cd995b80b00000000000022002013cb27c5d1f5f13a763a06fa3299218fb51504a84bd10809f2be730407ff1b72a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036619d6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100e1c5157d9ac24eea2ead29c12c26e2f8efdabcbbfc7abc73d5d0faa5cb85503102207bb244b9a2877a5bc6232ad88561f3ad02de54217dcf02bbe1b28bd51318fb6901483045022100b88d68334f6699ac0b10aec7d0f7274628249517181c148119da7cc37cdc98b9022040ff3ed18cec6fa06bfb6a404393d073157e3eb5451904499b79e91a1011879c01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 1)
    remote_htlc_signature: 3045022100d995ca72c1fe434247a19b676e92c13a0647017d27fd98bfb2eea72244820abb022059ade937a1c486863a297daec0a9a06f2b290e551622a5ff0cfc9603ef3f2cd501
    # signature for output 1 (htlc 2)
    remote_htlc_signature: 30440220724e33a9a4359e54451e43235b08db1ab0aca996ab70a712a4026a52c29db87802204047add11a8ba1f3a49595ef6c6c1c90483d2ef90a35f64463fd8af57942d41801
    # signature for output 2 (htlc 3)
    remote_htlc_signature: 30450221008889477f5d321983202eb581f98c71c3deabcaf316cd3b14df0a4cedaa7bf02c022072750593042c01ea63d4b8d57cab4f86ac4e68312cfabf49e2550e2a51e26b2201
    # signature for output 3 (htlc 4)
    remote_htlc_signature: 30440220332c90c60799b563c84a018a639c98c3e5ecf3c0b374872b831bd4479b77da2802206d6157634fe81124c7f2fcd448830442b35f23760ba4e5eaab909e713344258901
    # local signature 30450221009b9d8bccc9272a37b83ed1fa6f745bbea07965f6d2144236d8d5a2b5b70f09bf022053d742b839dbf1005b4ec614c3cf4e7d102784e1df7653ad9c61bd0e14c266d501
    output htlc_success_tx 1: 02000000000101cd9cb94b99aaa9cae794ff7d8149b7f4f3a02879249b79234377281d056b44350000000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d995ca72c1fe434247a19b676e92c13a0647017d27fd98bfb2eea72244820abb022059ade937a1c486863a297daec0a9a06f2b290e551622a5ff0cfc9603ef3f2cd5014830450221009b9d8bccc9272a37b83ed1fa6f745bbea07965f6d2144236d8d5a2b5b70f09bf022053d742b839dbf1005b4ec614c3cf4e7d102784e1df7653ad9c61bd0e14c266d5012001010101010101010101010101010101010101010101010101010101010101019921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f501b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000
    # local signature 304502210088a0db8203ef8ee44ea008c092d4e27ce144c6c207d54da499a4e64fde592b6402203d2cc31da39b659ad16e1c5e857124c3220602cb1b5857d6a52b39c56945645b01
    output htlc_timeout_tx 2: 02000000000101cd9cb94b99aaa9cae794ff7d8149b7f4f3a02879249b79234377281d056b44350100000000000000000128060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220724e33a9a4359e54451e43235b08db1ab0aca996ab70a712a4026a52c29db87802204047add11a8ba1f3a49595ef6c6c1c90483d2ef90a35f64463fd8af57942d4180148304502210088a0db8203ef8ee44ea008c092d4e27ce144c6c207d54da499a4e64fde592b6402203d2cc31da39b659ad16e1c5e857124c3220602cb1b5857d6a52b39c56945645b01008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local signature 30440220052b4b1c9fdad0b8cd6ec7ab26c9f7d8e45e5c93c820702c712ea09dc34cc49c02202098bd434c57644a78b1b873b70d1fdf52ce2e0f02234313f2115c3e85ad3f9001
    output htlc_timeout_tx 3: 02000000000101cd9cb94b99aaa9cae794ff7d8149b7f4f3a02879249b79234377281d056b443502000000000000000001100a0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221008889477f5d321983202eb581f98c71c3deabcaf316cd3b14df0a4cedaa7bf02c022072750593042c01ea63d4b8d57cab4f86ac4e68312cfabf49e2550e2a51e26b22014730440220052b4b1c9fdad0b8cd6ec7ab26c9f7d8e45e5c93c820702c712ea09dc34cc49c02202098bd434c57644a78b1b873b70d1fdf52ce2e0f02234313f2115c3e85ad3f9001008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local signature 3045022100d653f99f84792215cb7150a8dfb44a44996a2b376baef729197a32d92bd094c3022060164b561ae395b430cf701a5080e6483a660412748b7c1a9d0671632dc8f62d01
    output htlc_success_tx 4: 02000000000101cd9cb94b99aaa9cae794ff7d8149b7f4f3a02879249b79234377281d056b443503000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220332c90c60799b563c84a018a639c98c3e5ecf3c0b374872b831bd4479b77da2802206d6157634fe81124c7f2fcd448830442b35f23760ba4e5eaab909e713344258901483045022100d653f99f84792215cb7150a8dfb44a44996a2b376baef729197a32d92bd094c3022060164b561ae395b430cf701a5080e6483a660412748b7c1a9d0671632dc8f62d012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 6 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2026
    # base commitment transaction fee = 2860
    # actual commitment transaction fee = 3860
    # HTLC received amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f501b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6985140 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 3045022100dee408978d75349528d11b5a4e7f083b8b159dd697cac53a67222e81b146be71022038a877cecd6b89c227bf7971d34214b3033238e1fd1c9b45ade9a032c83ed63301
    remote_signature: 30440220328749aa5f57a878685524d7893f1669a618c92494c2cdbb6836b0ca26f6b4cb0220184fa3cd9375a7869633726ffbe5e8ebafefafbe534198034c70ad65bf1ec0e501
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d0070000000000002200207fca09ebacdfe6a4f704e8e3c1767bee0ede006ca7107b4358b34eb96c50bacfd007000000000000220020d9d8939fbb5b6f47577992ec878bcc4ee58272696dcef62607e152c29b6cd995b80b00000000000022002013cb27c5d1f5f13a763a06fa3299218fb51504a84bd10809f2be730407ff1b72a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036b4956a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100dee408978d75349528d11b5a4e7f083b8b159dd697cac53a67222e81b146be71022038a877cecd6b89c227bf7971d34214b3033238e1fd1c9b45ade9a032c83ed633014730440220328749aa5f57a878685524d7893f1669a618c92494c2cdbb6836b0ca26f6b4cb0220184fa3cd9375a7869633726ffbe5e8ebafefafbe534198034c70ad65bf1ec0e501475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (htlc 1)
    remote_htlc_signature: 3045022100a8a065322199d515ed0a562101c2aed0c220dec3598f1e523733b82f684a66c902200feb709e3cf48771d6fca9f1dc125b10e07c252f1f3f85386c46cd9b1231e57c01
    # signature for output 1 (htlc 2)
    remote_htlc_signature: 304502210084763c1e9fd96e612c41e793a3e8beaaa64b0d2420b097abecd7df7d634a52f9022037115669e1676009dba6969cb4a8676270a685855e9c70f43069e4659259c1aa01
    # signature for output 2 (htlc 3)
    remote_htlc_signature: 3045022100db93f5c9188ee45194397502e89d3329d03f7b716a12ba38453c9fe84b3703e802206ca4b20c79f8e8647f2ca0d5573824f86cdc0b24d66c3b0a56ac2287e0646d6101
    # signature for output 3 (htlc 4)
    remote_htlc_signature: 3044022011c590a78cb5af7307ec42965545fa622c6750f76f8c70380636516ac666ff4502201173e0b45f1d8af493e70b63d86e56aefeac252d06101f8071779b739cb82f6001
    # local signature 3045022100ff3ff587d6d5d0b44c754d6132b875c94ddb29964d2082a254f92d90aab6267102203d0beb25adffbe135e43d32ebb9c9fad056fbeb063cda2c555d9be7df427e50c01
    output htlc_success_tx 1: 02000000000101fa20f7106f0a300a5555526642cdf6e37af85da7006e6fe26e6213789e8336c10000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a8a065322199d515ed0a562101c2aed0c220dec3598f1e523733b82f684a66c902200feb709e3cf48771d6fca9f1dc125b10e07c252f1f3f85386c46cd9b1231e57c01483045022100ff3ff587d6d5d0b44c754d6132b875c94ddb29964d2082a254f92d90aab6267102203d0beb25adffbe135e43d32ebb9c9fad056fbeb063cda2c555d9be7df427e50c012001010101010101010101010101010101010101010101010101010101010101019921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f501b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000
    # local signature 3045022100c37ff49b78cfd0951da0c2f44b04ad965498ff7840f7156104854d329bfc129a022079df3fc312a560cab4d73ad099ed5c469d1cd55ad3d3aecc126423507be954a001
    output htlc_timeout_tx 2: 02000000000101fa20f7106f0a300a5555526642cdf6e37af85da7006e6fe26e6213789e8336c10100000000000000000185020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050048304502210084763c1e9fd96e612c41e793a3e8beaaa64b0d2420b097abecd7df7d634a52f9022037115669e1676009dba6969cb4a8676270a685855e9c70f43069e4659259c1aa01483045022100c37ff49b78cfd0951da0c2f44b04ad965498ff7840f7156104854d329bfc129a022079df3fc312a560cab4d73ad099ed5c469d1cd55ad3d3aecc126423507be954a001008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local signature 30440220148dfbadce7f89eb34e66f7c092d43fc1dcf24a3fdb6d89d20ffdfb458a7aebc02202da1e7df63657820d74930ebd918f0c565f3671fa81ea4b8e64206704f7e563901
    output htlc_timeout_tx 3: 02000000000101fa20f7106f0a300a5555526642cdf6e37af85da7006e6fe26e6213789e8336c1020000000000000000016d060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100db93f5c9188ee45194397502e89d3329d03f7b716a12ba38453c9fe84b3703e802206ca4b20c79f8e8647f2ca0d5573824f86cdc0b24d66c3b0a56ac2287e0646d61014730440220148dfbadce7f89eb34e66f7c092d43fc1dcf24a3fdb6d89d20ffdfb458a7aebc02202da1e7df63657820d74930ebd918f0c565f3671fa81ea4b8e64206704f7e563901008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local signature 3045022100e156dc322fe686a5e1dfd605c282d3375d96d98a5691a21b3d6b5bced601869102206f1db61a9e96b0cd82e5828b94eada83f45cd80f60f5328f48dfa894718ae7e501
    output htlc_success_tx 4: 02000000000101fa20f7106f0a300a5555526642cdf6e37af85da7006e6fe26e6213789e8336c103000000000000000001f2090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022011c590a78cb5af7307ec42965545fa622c6750f76f8c70380636516ac666ff4502201173e0b45f1d8af493e70b63d86e56aefeac252d06101f8071779b739cb82f6001483045022100e156dc322fe686a5e1dfd605c282d3375d96d98a5691a21b3d6b5bced601869102206f1db61a9e96b0cd82e5828b94eada83f45cd80f60f5328f48dfa894718ae7e5012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 5 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2027
    # base commitment transaction fee = 2513
    # actual commitment transaction fee = 5513
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6985487 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 304402200fceec155e8791c96133ab30eeb41cacbd8d80c50cf2d285c7003ec3930ed40a0220388170a673a8c15ed331a5a24b7feae581d4aac0dc10e933a187ed93033fbf5c01
    remote_signature: 30450221008bc83955f695d3ddac27b928d02f36b8325d52a66c102466caa6264690dff1ca02206cc3b7540c1e06aa3ba981c72a6cc42bc37386f2ff3ea61b4d52ca471aac65ea01
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d007000000000000220020d9d8939fbb5b6f47577992ec878bcc4ee58272696dcef62607e152c29b6cd995b80b00000000000022002013cb27c5d1f5f13a763a06fa3299218fb51504a84bd10809f2be730407ff1b72a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0360f976a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402200fceec155e8791c96133ab30eeb41cacbd8d80c50cf2d285c7003ec3930ed40a0220388170a673a8c15ed331a5a24b7feae581d4aac0dc10e933a187ed93033fbf5c014830450221008bc83955f695d3ddac27b928d02f36b8325d52a66c102466caa6264690dff1ca02206cc3b7540c1e06aa3ba981c72a6cc42bc37386f2ff3ea61b4d52ca471aac65ea01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature: 3044022002998cbdd14679f75cb6e5673906d5a48d149aa8a4a161b8e7b28743b56f9d890220532775eba61d9e338c064303475f5954e45f8ef39bbb6202b42136fe27d24e2401
    # signature for output 1 (htlc 3)
    remote_htlc_signature: 3045022100cbf3323089fbd7d2b2994e66b1360cefc2bbb3fd52ace115f1a48f053a59fdbe022016388da5e0d6c5c6736d0ee4f4f1ad94f5c29319e9eba2b5ca30a33209c0663301
    # signature for output 2 (htlc 4)
    remote_htlc_signature: 30450221008425ccfbdcc627c86ec7f934df87bd7ee3adf8134623c21269006ec89d16ae440220124661889f9944fef9209b7735b316ecbf145ff0c2d733be200354ddb67b0eb801
    # local signature 30450221009b8eec79ffea7f06d60373cf77f6e2bcddcfce4118b29c66e5660c4d46f4067f02201b4e37893090ddb41993d8325f881641126fed685019a6560beab6d58358700001
    output htlc_timeout_tx 2: 02000000000101482c4e556cf79e904c70b389470c3d79aaa98a0cd347b6844df3fba2781f02cf0000000000000000000184020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022002998cbdd14679f75cb6e5673906d5a48d149aa8a4a161b8e7b28743b56f9d890220532775eba61d9e338c064303475f5954e45f8ef39bbb6202b42136fe27d24e24014830450221009b8eec79ffea7f06d60373cf77f6e2bcddcfce4118b29c66e5660c4d46f4067f02201b4e37893090ddb41993d8325f881641126fed685019a6560beab6d58358700001008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local signature 30440220511c97e26c5bb36d40b107d72693f589628c896f3211d4c28ab1e7f0c221362102200c8ec78bafa30aaa6e725f4cd01ca17ca1e6aa3dc67b53627f3612eb68bacb8501
    output htlc_timeout_tx 3: 02000000000101482c4e556cf79e904c70b389470c3d79aaa98a0cd347b6844df3fba2781f02cf010000000000000000016c060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100cbf3323089fbd7d2b2994e66b1360cefc2bbb3fd52ace115f1a48f053a59fdbe022016388da5e0d6c5c6736d0ee4f4f1ad94f5c29319e9eba2b5ca30a33209c06633014730440220511c97e26c5bb36d40b107d72693f589628c896f3211d4c28ab1e7f0c221362102200c8ec78bafa30aaa6e725f4cd01ca17ca1e6aa3dc67b53627f3612eb68bacb8501008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local signature 304502210080724c54b972ac9deed054418ea8d5655ea94d8e160e7998776e34138718516102204488f7495e7866c33ca9291a5935936736ffd4f124a1a4e48b6efa1ef93315b701
    output htlc_success_tx 4: 02000000000101482c4e556cf79e904c70b389470c3d79aaa98a0cd347b6844df3fba2781f02cf02000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221008425ccfbdcc627c86ec7f934df87bd7ee3adf8134623c21269006ec89d16ae440220124661889f9944fef9209b7735b316ecbf145ff0c2d733be200354ddb67b0eb80148304502210080724c54b972ac9deed054418ea8d5655ea94d8e160e7998776e34138718516102204488f7495e7866c33ca9291a5935936736ffd4f124a1a4e48b6efa1ef93315b7012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 5 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2174
    # base commitment transaction fee = 2695
    # actual commitment transaction fee = 5695
    # HTLC offered amount 2000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6985305 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 3045022100eac9149bf220051543ae6b99805cb2176943d86059a4af1bb3aa24993defe4d4022065c47cf6f35dd1aa6e99ae1d3dd34a134d4fe9a60e761f5f05baabaab102e9d801
    remote_signature: 30440220248683e4ed5b7e83111d0d4292fc0109e77dd6553be813f32f5bbad96e7715d002203bed55e5402616f9b4b9c5690598c7426999814247b6c3bb3efe313509bb4ecf01
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d007000000000000220020d9d8939fbb5b6f47577992ec878bcc4ee58272696dcef62607e152c29b6cd995b80b00000000000022002013cb27c5d1f5f13a763a06fa3299218fb51504a84bd10809f2be730407ff1b72a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03659966a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100eac9149bf220051543ae6b99805cb2176943d86059a4af1bb3aa24993defe4d4022065c47cf6f35dd1aa6e99ae1d3dd34a134d4fe9a60e761f5f05baabaab102e9d8014730440220248683e4ed5b7e83111d0d4292fc0109e77dd6553be813f32f5bbad96e7715d002203bed55e5402616f9b4b9c5690598c7426999814247b6c3bb3efe313509bb4ecf01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (htlc 2)
    remote_htlc_signature: 3045022100c409f0b837b72813e22dac88681cb2329e6a9e19b4698baaf20bbed991247e2f02201c5163bdd64f41566eaa46427bf637252875e7cb08d14816ae47089ed31549a801
    # signature for output 1 (htlc 3)
    remote_htlc_signature: 304402207b4abf8978d9aaf3029d36e70bc1648c3f54d05543a03ebc48f3a900ec82d8e102202c7a46e77385c4289b6ea0286e3f293f93be32a7f3457dde70f717aa124f409401
    # signature for output 2 (htlc 4)
    remote_htlc_signature: 304402205335cda43561c3eba06a332a21aa91e06bd7d5bb09e3f1c3fbf830e2d2a8764c0220548d3073a6e6782823449118adc59244de7ab72507396c072aebabcd3045f81401
    # local signature 304402207f7746fb57c46e08f18936a3a0897d1a150ed5c54637804a1c1df5ac2285321502207809c813dbc3e326dd8e695039e4053a57650b2876f0b261fe45d281de64802201
    output htlc_timeout_tx 2: 02000000000101aec1b3b2fa3939292a491575c41f8bce6eed5dac22bb53a407d3186b7c7a0ff00000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100c409f0b837b72813e22dac88681cb2329e6a9e19b4698baaf20bbed991247e2f02201c5163bdd64f41566eaa46427bf637252875e7cb08d14816ae47089ed31549a80147304402207f7746fb57c46e08f18936a3a0897d1a150ed5c54637804a1c1df5ac2285321502207809c813dbc3e326dd8e695039e4053a57650b2876f0b261fe45d281de64802201008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac68f6010000
    # local signature 3045022100ff7d0e998a574cf077bc07eca4d821db732c4dd74c04347334b711ae6c5aac4002203dba96a98b2a18c23a4e1c9e45bc78176bb57e295d89da5ed6cbcb47dcb80a6c01
    output htlc_timeout_tx 3: 02000000000101aec1b3b2fa3939292a491575c41f8bce6eed5dac22bb53a407d3186b7c7a0ff0010000000000000000010a060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402207b4abf8978d9aaf3029d36e70bc1648c3f54d05543a03ebc48f3a900ec82d8e102202c7a46e77385c4289b6ea0286e3f293f93be32a7f3457dde70f717aa124f409401483045022100ff7d0e998a574cf077bc07eca4d821db732c4dd74c04347334b711ae6c5aac4002203dba96a98b2a18c23a4e1c9e45bc78176bb57e295d89da5ed6cbcb47dcb80a6c01008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local signature 304502210097942fb769275ae8e259d7522ff176c2e0c143274aef1abd8c5a4f637e8f262e022064d0268e134b64ccfc785c987fd02009a2f628bf0e74daf96139afcdcfa64cfd01
    output htlc_success_tx 4: 02000000000101aec1b3b2fa3939292a491575c41f8bce6eed5dac22bb53a407d3186b7c7a0ff00200000000000000000188090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402205335cda43561c3eba06a332a21aa91e06bd7d5bb09e3f1c3fbf830e2d2a8764c0220548d3073a6e6782823449118adc59244de7ab72507396c072aebabcd3045f8140148304502210097942fb769275ae8e259d7522ff176c2e0c143274aef1abd8c5a4f637e8f262e022064d0268e134b64ccfc785c987fd02009a2f628bf0e74daf96139afcdcfa64cfd012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 4 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2175
    # base commitment transaction fee = 2322
    # actual commitment transaction fee = 7322
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6985678 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 304402204d4a74ffac48c65088a2ef7db905bec7754846f2150c5a530be18b7507d0be2702204fd27cf59239b188ff385ca259b0affe52fa875efad3848440dc01f44488692901
    remote_signature: 3045022100f03478bf2564b442175564720be7343042e2781513049445d4f40224c9d01e5802203d2d45140a0177605afc250b991c86089ddbb9ec733bd581e8400cf93f09b1f101
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b00000000000022002013cb27c5d1f5f13a763a06fa3299218fb51504a84bd10809f2be730407ff1b72a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036ce976a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402204d4a74ffac48c65088a2ef7db905bec7754846f2150c5a530be18b7507d0be2702204fd27cf59239b188ff385ca259b0affe52fa875efad3848440dc01f44488692901483045022100f03478bf2564b442175564720be7343042e2781513049445d4f40224c9d01e5802203d2d45140a0177605afc250b991c86089ddbb9ec733bd581e8400cf93f09b1f101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature: 3045022100b1004ab07a3b6308ea376b93e20eb965d92c13de0593a349990ff3d91be93d3b02200bc2ae5be86690a482d17cb1fd334d7c8cce4d27549cc30fde1a360588aa592201
    # signature for output 1 (htlc 4)
    remote_htlc_signature: 3045022100f3ac5f3eaed3242350eec14f4b16f0a858a4c6b7693c700cc198cc17c0feb761022026b0cd3b4edcc3546bcf312fa925bb5d9e0663234d09bb850798e2097b802f3701
    # local signature 304402206433ae4be2f3731d2db8a93c6c290fca5d2b5a872cbe33c581bd110b7241517a02201e99df3bb8e0ec6f879371703661c569804d2b3f2d0bd19b9aa43868e05f7fb301
    output htlc_timeout_tx 3: 02000000000101ccfa675a6dd0917873436d6c22f9c8a8193cc116b9605d74d19d1478405cdaba0000000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100b1004ab07a3b6308ea376b93e20eb965d92c13de0593a349990ff3d91be93d3b02200bc2ae5be86690a482d17cb1fd334d7c8cce4d27549cc30fde1a360588aa59220147304402206433ae4be2f3731d2db8a93c6c290fca5d2b5a872cbe33c581bd110b7241517a02201e99df3bb8e0ec6f879371703661c569804d2b3f2d0bd19b9aa43868e05f7fb301008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local signature 304402206c914b42e5647c8c827152e1766bb81d85c2d158d6afe6e50e892d0ed61cec5b022034460704644e0ecb1272cee36f0f4e9c0eb657d4dbbab7dc05a098fd4f6ec2e601
    output htlc_success_tx 4: 02000000000101ccfa675a6dd0917873436d6c22f9c8a8193cc116b9605d74d19d1478405cdaba0100000000000000000187090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100f3ac5f3eaed3242350eec14f4b16f0a858a4c6b7693c700cc198cc17c0feb761022026b0cd3b4edcc3546bcf312fa925bb5d9e0663234d09bb850798e2097b802f370147304402206c914b42e5647c8c827152e1766bb81d85c2d158d6afe6e50e892d0ed61cec5b022034460704644e0ecb1272cee36f0f4e9c0eb657d4dbbab7dc05a098fd4f6ec2e6012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 4 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3669
    # base commitment transaction fee = 3918
    # actual commitment transaction fee = 8918
    # HTLC offered amount 3000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6984082 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 3044022044b576ba804b1dd3b9481394de0805dd5fd366bd3c54b7c2a4da689b4cdbee4d02204a61b159659dc9f9d03d613b9667d53f56354cdf628c89500001124e79afa6f701
    remote_signature: 3044022035491b89b74fd3548cb831d0a50019b57aaac9e53f37a155c4df6c617c014f7d02206a853485f51b6a8d4a9cfe46f34b697cb3135f67b05a096512c97b9b0e5df29d01
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b00000000000022002013cb27c5d1f5f13a763a06fa3299218fb51504a84bd10809f2be730407ff1b72a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03692916a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022044b576ba804b1dd3b9481394de0805dd5fd366bd3c54b7c2a4da689b4cdbee4d02204a61b159659dc9f9d03d613b9667d53f56354cdf628c89500001124e79afa6f701473044022035491b89b74fd3548cb831d0a50019b57aaac9e53f37a155c4df6c617c014f7d02206a853485f51b6a8d4a9cfe46f34b697cb3135f67b05a096512c97b9b0e5df29d01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (htlc 3)
    remote_htlc_signature: 3045022100d4e27b76ff58c494414ca6fcdd1ab68e476c48f5f282dabc5939d1f0c851ab1f022016c14d82494ae59d9c89c3be1d5eb6ac33b17426ca59856c5a410816d647503601
    # signature for output 1 (htlc 4)
    remote_htlc_signature: 304402200284714d8473b03ff3e5c3cdcfbb7f2942c9a6d87aa9300a157df8e18cce137702202993c34c175a34638e0cd9e2c136803b9e1b01e400443ea0a57998909893ff7001
    # local signature 30440220137e8d2d847ecaea675fa8d6e8240cb9f91a1f6f59d11c6f1023083904894fbb022004b05f7e46ae21621b609e769c71e939affc38f2680d7d8549c73774e49c98c001
    output htlc_timeout_tx 3: 0200000000010157594e8e515d8e0676b3a0e60996cff25c1708200ce76231b60f772d0d9f66c90000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d4e27b76ff58c494414ca6fcdd1ab68e476c48f5f282dabc5939d1f0c851ab1f022016c14d82494ae59d9c89c3be1d5eb6ac33b17426ca59856c5a410816d6475036014730440220137e8d2d847ecaea675fa8d6e8240cb9f91a1f6f59d11c6f1023083904894fbb022004b05f7e46ae21621b609e769c71e939affc38f2680d7d8549c73774e49c98c001008b21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1953ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac68f7010000
    # local signature 3045022100a67d0e82a436e333c999f49cccee6a88c82ff23b5ddfdabec2d4e169d7926974022054e085af4b31f33fadcd7f113ffad550fab6705658c78be121dcbf47e186bafc01
    output htlc_success_tx 4: 0200000000010157594e8e515d8e0676b3a0e60996cff25c1708200ce76231b60f772d0d9f66c90100000000000000000156050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402200284714d8473b03ff3e5c3cdcfbb7f2942c9a6d87aa9300a157df8e18cce137702202993c34c175a34638e0cd9e2c136803b9e1b01e400443ea0a57998909893ff7001483045022100a67d0e82a436e333c999f49cccee6a88c82ff23b5ddfdabec2d4e169d7926974022054e085af4b31f33fadcd7f113ffad550fab6705658c78be121dcbf47e186bafc012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 3 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3670
    # base commitment transaction fee = 3288
    # actual commitment transaction fee = 11288
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6984712 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 3044022034eb7f35e028a65a81b6355aa082dd0f542e1b0563f0ac5dcd1019b90a99c7f3022063f3a220d1791674a03f9d3cda4029d17c831300e764c4a9413113fdffefd95601
    remote_signature: 3045022100843080ce69800b044dd0a510548e5ec24809310338cf34d42bdd2a5534e5d3f20220747eed13e771530625d1c3f169287fcd000913586fcd1067d7094959aedbee8301
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03608946a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022034eb7f35e028a65a81b6355aa082dd0f542e1b0563f0ac5dcd1019b90a99c7f3022063f3a220d1791674a03f9d3cda4029d17c831300e764c4a9413113fdffefd95601483045022100843080ce69800b044dd0a510548e5ec24809310338cf34d42bdd2a5534e5d3f20220747eed13e771530625d1c3f169287fcd000913586fcd1067d7094959aedbee8301475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature: 3044022034b3310f79b81599b91bcb836ac7b080d22f25eb4ee8df0e0a38a9d7a635664102206aba667077a98c6f4855da94ec18b242624ec25286e3363fc5db6c460fa5556401
    # local signature 3045022100fb48f200883979f341117f57dc16dfd268e977e2f7c20ac6f08e02323108c4a502202d73cbf0276be30e08b636d6a5018549fcb6bfc67423a77e71a4d6375b734e2901
    output htlc_success_tx 4: 0200000000010111ac9bcf5f21b0850a04052c3f239bdc4a56bba7655f4285e0bf1f43d412d7960000000000000000000155050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022034b3310f79b81599b91bcb836ac7b080d22f25eb4ee8df0e0a38a9d7a635664102206aba667077a98c6f4855da94ec18b242624ec25286e3363fc5db6c460fa5556401483045022100fb48f200883979f341117f57dc16dfd268e977e2f7c20ac6f08e02323108c4a502202d73cbf0276be30e08b636d6a5018549fcb6bfc67423a77e71a4d6375b734e29012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 3 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 4811
    # base commitment transaction fee = 4310
    # actual commitment transaction fee = 12310
    # HTLC received amount 4000 wscript 21039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac6868
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6983690 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 3044022025ab42ceb2823e79671f6e2b941dae7749b02965d1e9e75120531a48a9effb58022058a9775823a2fa39f5adc192aa6cb548bbabf62d42c54a80e80fead2c3dc209f01
    remote_signature: 30440220122c6d961fcb24de2ed36146209e6c94cf2afb20f37c51aa47bca1a793522f6702206552ccb157494dde384f78836f5029dc9aa62b91df6426f2613d03560835118601
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f000000000000220020d59585bda139e78d4bbb1abf59962c8c3fd2a52104b29c4c91b45d1f6af90eccc0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0360a906a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022025ab42ceb2823e79671f6e2b941dae7749b02965d1e9e75120531a48a9effb58022058a9775823a2fa39f5adc192aa6cb548bbabf62d42c54a80e80fead2c3dc209f014730440220122c6d961fcb24de2ed36146209e6c94cf2afb20f37c51aa47bca1a793522f6702206552ccb157494dde384f78836f5029dc9aa62b91df6426f2613d03560835118601475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (htlc 4)
    remote_htlc_signature: 3045022100cc46ce8f23ddf35df08c03a812cb963ad92b0876a6f99d49d32a8322519944bc022030f74bc5c5c726f253bdc68690af39dbd8c55ec89009ef8048aba6c5f5a5241c01
    # local signature 3044022014a7c5f58ebf3eefca61974920168c128ddf106e2817744a6498dc85656f773c0220590e3e68e854429e70a75d26372d73451e2e8f0709505b268d15585fb41c452b01
    output htlc_success_tx 4: 020000000001016795164953c30a73c87e4ab782f7a9fca81eb97fb47175977916919da39cc4460000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100cc46ce8f23ddf35df08c03a812cb963ad92b0876a6f99d49d32a8322519944bc022030f74bc5c5c726f253bdc68690af39dbd8c55ec89009ef8048aba6c5f5a5241c01473044022014a7c5f58ebf3eefca61974920168c128ddf106e2817744a6498dc85656f773c0220590e3e68e854429e70a75d26372d73451e2e8f0709505b268d15585fb41c452b012004040404040404040404040404040404040404040404040404040404040404049921039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac8787c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67820087637502f801b175ac677c75210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19ac686800000000

    name: commitment tx with 2 outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 4812
    # base commitment transaction fee = 3483
    # actual commitment transaction fee = 15483
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # to-local amount 6984517 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # local_signature = 30450221009041d59c3b3729e786f53a734a667e78cf5e8634b21c5e73ebda05e690b9858302202a2c685a61acfe352c2fbdce442578c1326f36de8faeaa316f7a5e4aac78384701
    remote_signature: 304402205b8c12c827c4066c6117dda6333fd8ae98edc3a816339d8674f808bcaa834dcd022005876f3497b9c53a41c4c7ebf6aaa0a93474123c2abcbe8267a97d61e22fbaa401
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8002c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a03645936a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004830450221009041d59c3b3729e786f53a734a667e78cf5e8634b21c5e73ebda05e690b9858302202a2c685a61acfe352c2fbdce442578c1326f36de8faeaa316f7a5e4aac7838470147304402205b8c12c827c4066c6117dda6333fd8ae98edc3a816339d8674f808bcaa834dcd022005876f3497b9c53a41c4c7ebf6aaa0a93474123c2abcbe8267a97d61e22fbaa401475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

    name: commitment tx with 2 outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651180
    # base commitment transaction fee = 6987454
    # actual commitment transaction fee = 6999454
    # to-local amount 546 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # local_signature = 3045022100bab11758e8182f7957047c19033df1b8294bc623a474efe4e1eb6519e49c7147022018af25c278ed3e9809dbf7f0b132ffccce6ff7b59a4a67f507a3648c46e5b3e501
    remote_signature: 3044022017f82cdb8e5b1c443afe9191efdde7aa742e8f03c265bdab7df18a74b30711a7022009a5b4c676778c6bda8d87db551ae5d89ac792aff62011734afa1caf4bc857dd01
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b800222020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80ec0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a0360400483045022100bab11758e8182f7957047c19033df1b8294bc623a474efe4e1eb6519e49c7147022018af25c278ed3e9809dbf7f0b132ffccce6ff7b59a4a67f507a3648c46e5b3e501473044022017f82cdb8e5b1c443afe9191efdde7aa742e8f03c265bdab7df18a74b30711a7022009a5b4c676778c6bda8d87db551ae5d89ac792aff62011734afa1caf4bc857dd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

    name: commitment tx with 1 output untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651181
    # base commitment transaction fee = 6987455
    # actual commitment transaction fee = 7000000
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # local_signature = 304402204788ebe839058b6d917999d82ffa7ad235710d49b8f99aea7c8d95fe60ecc26502200c6ad2bcec214d83e66570bf22fa383f8e71b8991cd63feea018d2cd610b86f601
    remote_signature: 30450221008dc967ec76f7a4837f00bdab1dc3e93c62cd28ec9931649dbb5f0b9105615bf702203fa4646c7f85b19d0bd4691a7ab89ee7243aa6f14a3a3744bed6fd6e0b6b17b901
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8001c0c62d0000000000160014e2f14ead9ca9a2f4c8b8a3f9bd109762ed33a036040047304402204788ebe839058b6d917999d82ffa7ad235710d49b8f99aea7c8d95fe60ecc26502200c6ad2bcec214d83e66570bf22fa383f8e71b8991cd63feea018d2cd610b86f6014830450221008dc967ec76f7a4837f00bdab1dc3e93c62cd28ec9931649dbb5f0b9105615bf702203fa4646c7f85b19d0bd4691a7ab89ee7243aa6f14a3a3744bed6fd6e0b6b17b901475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

    name: commitment tx with fee greater than funder amount
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651936
    # base commitment transaction fee = 6988001
    # actual commitment transaction fee = 7000000
    # to-remote amount 3000000 P2WPKH(039390232673a9de88820d44ea910f364a332dc815cb0122bf5088d581dcbac878)
    # local_signature = 304402204788ebe839058b6d917999d82ffa7ad235710d49b8f99aea7c8d95fe60ecc26502200c6ad2bcec214d83e66570bf22fa383f8e71b8991cd63feea018d2cd610b86f601
    remote_signature: 30450221008dc967ec76f7a4837f00bdab1dc3e93c62cd28ec9931649dbb5f0b9105615bf702203fa4646c7f85b19d0bd4691a7ab89ee7243aa6f14a3a3744bed6fd6e0b6b17b901
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

