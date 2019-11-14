# BOLT #3: Bitcoin Transaction and Script Formats

This details the exact format of on-chain transactions, which both sides need to agree on to ensure signatures are valid. This consists of the funding transaction output script, the commitment transactions, and the HTLC transactions.

# Table of Contents

  * [Transactions](#transactions)
    * [Transaction Input and Output Ordering](#transaction-input-and-output-ordering)
    * [Use of Segwit](#use-of-segwit)
    * [Funding Transaction Output](#funding-transaction-output)
    * [Commitment Transaction](#commitment-transaction)
        * [Commitment Transaction Outputs](#commitment-transaction-outputs)
          * [`to_local` Output](#to_local-output)
          * [`to_remote` Output](#to_remote-output)
          * [Offered HTLC Outputs](#offered-htlc-outputs)
          * [Received HTLC Outputs](#received-htlc-outputs)
        * [Trimmed Outputs](#trimmed-outputs)
    * [HTLC-timeout and HTLC-success Transactions](#htlc-timeout-and-htlc-success-transactions)
	* [Closing Transaction](#closing-transaction)
    * [Fees](#fees)
        * [Fee Calculation](#fee-calculation)
        * [Fee Payment](#fee-payment)
  * [Keys](#keys)
    * [Key Derivation](#key-derivation)
        * [`localpubkey`, `remotepubkey`, `local_htlcpubkey`, `remote_htlcpubkey`, `local_delayedpubkey`, and `remote_delayedpubkey` Derivation](#localpubkey-remotepubkey-local_htlcpubkey-remote_htlcpubkey-local_delayedpubkey-and-remote_delayedpubkey-derivation)
        * [`revocationpubkey` Derivation](#revocationpubkey-derivation)
        * [Per-commitment Secret Requirements](#per-commitment-secret-requirements)
    * [Efficient Per-commitment Secret Storage](#efficient-per-commitment-secret-storage)
  * [Appendix A: Expected Weights](#appendix-a-expected-weights)
      * [Expected Weight of the Commitment Transaction](#expected-weight-of-the-commitment-transaction)
      * [Expected Weight of HTLC-timeout and HTLC-success Transactions](#expected-weight-of-htlc-timeout-and-htlc-success-transactions)
  * [Appendix B: Funding Transaction Test Vectors](#appendix-b-funding-transaction-test-vectors)
  * [Appendix C: Commitment and HTLC Transaction Test Vectors](#appendix-c-commitment-and-htlc-transaction-test-vectors)
  * [Appendix D: Per-commitment Secret Generation Test Vectors](#appendix-d-per-commitment-secret-generation-test-vectors)
    * [Generation Tests](#generation-tests)
    * [Storage Tests](#storage-tests)
  * [Appendix E: Key Derivation Test Vectors](#appendix-e-key-derivation-test-vectors)
  * [Appendix F: Dual Funded Transaction Test Vectors](#appendix-f-dual-funded-transaction-test-vectors)
  * [References](#references)
  * [Authors](#authors)

# Transactions

## Transaction Input and Output Ordering

Lexicographic ordering: see [BIP69](https://github.com/bitcoin/bips/blob/master/bip-0069.mediawiki).  In the case of identical HTLC outputs, the outputs are ordered in increasing `cltv_expiry` order.

## Rationale

Two offered HTLCs which have the same `amount_msat` and `payment_hash`
will have identical outputs, even if their `cltv_expiry` differs.
This only matters because the same ordering is used to send
`htlc_signatures` and the HTLC transactions themselves are different,
thus the two peers must agree on the canonical ordering for this case.

## Use of Segwit

Most transaction outputs used here are pay-to-witness-script-hash<sup>[BIP141](https://github.com/bitcoin/bips/blob/master/bip-0141.mediawiki#witness-program)</sup> (P2WSH) outputs: the Segwit version of P2SH. To spend such outputs, the last item on the witness stack must be the actual script that was used to generate the P2WSH output that is being spent. This last item has been omitted for brevity in the rest of this document.

## Funding Transaction Output

* The funding output script is a P2WSH to:

`2 <pubkey1> <pubkey2> 2 OP_CHECKMULTISIG`

* Where `pubkey1` is the numerically lesser of the two DER-encoded `funding_pubkey` and where `pubkey2` is the numerically greater of the two.

## Commitment Transaction

* version: 2
* locktime: upper 8 bits are 0x20, lower 24 bits are the lower 24 bits of the obscured commitment number
* txin count: 1
   * `txin[0]` outpoint: `txid` and `output_index` from `funding_created` message
   * `txin[0]` sequence: upper 8 bits are 0x80, lower 24 bits are upper 24 bits of the obscured commitment number
   * `txin[0]` script bytes: 0
   * `txin[0]` witness: `0 <signature_for_pubkey1> <signature_for_pubkey2>`

The 48-bit commitment number is obscured by `XOR` with the lower 48 bits of:

    SHA256(payment_basepoint from open_channel || payment_basepoint from accept_channel)

This obscures the number of commitments made on the channel in the
case of unilateral close, yet still provides a useful index for both
nodes (who know the `payment_basepoint`s) to quickly find a revoked
commitment transaction.

### Commitment Transaction Outputs

To allow an opportunity for penalty transactions, in case of a revoked commitment transaction, all outputs that return funds to the owner of the commitment transaction (a.k.a. the "local node") must be delayed for `to_self_delay` blocks. This delay is done in a second-stage HTLC transaction (HTLC-success for HTLCs accepted by the local node, HTLC-timeout for HTLCs offered by the local node).

The reason for the separate transaction stage for HTLC outputs is so that HTLCs can timeout or be fulfilled even though they are within the `to_self_delay` delay.
Otherwise, the required minimum timeout on HTLCs is lengthened by this delay, causing longer timeouts for HTLCs traversing the network.

The amounts for each output MUST be rounded down to whole satoshis. If this amount, minus the fees for the HTLC transaction, is less than the `dust_limit_satoshis` set by the owner of the commitment transaction, the output MUST NOT be produced (thus the funds add to fees).

#### `to_local` Output

This output sends funds back to the owner of this commitment transaction and thus must be timelocked using `OP_CHECKSEQUENCEVERIFY`. It can be claimed, without delay, by the other party if they know the revocation private key. The output is a version-0 P2WSH, with a witness script:

    OP_IF
        # Penalty transaction
        <revocationpubkey>
    OP_ELSE
        `to_self_delay`
        OP_CHECKSEQUENCEVERIFY
        OP_DROP
        <local_delayedpubkey>
    OP_ENDIF
    OP_CHECKSIG

The output is spent by a transaction with `nSequence` field set to `to_self_delay` (which can only be valid after that duration has passed) and witness:

    <local_delayedsig> 0

If a revoked commitment transaction is published, the other party can spend this output immediately with the following witness:

    <revocation_sig> 1

#### `to_remote` Output

This output sends funds to the other peer and thus is a simple P2WPKH to `remotepubkey`.

#### Offered HTLC Outputs

This output sends funds to either an HTLC-timeout transaction after the HTLC-timeout or to the remote node using the payment preimage or the revocation key. The output is a P2WSH, with a witness script:

    # To remote node with revocation key
    OP_DUP OP_HASH160 <RIPEMD160(SHA256(revocationpubkey))> OP_EQUAL
    OP_IF
        OP_CHECKSIG
    OP_ELSE
        <remote_htlcpubkey> OP_SWAP OP_SIZE 32 OP_EQUAL
        OP_NOTIF
            # To local node via HTLC-timeout transaction (timelocked).
            OP_DROP 2 OP_SWAP <local_htlcpubkey> 2 OP_CHECKMULTISIG
        OP_ELSE
            # To remote node with preimage.
            OP_HASH160 <RIPEMD160(payment_hash)> OP_EQUALVERIFY
            OP_CHECKSIG
        OP_ENDIF
    OP_ENDIF

The remote node can redeem the HTLC with the witness:

    <remotehtlcsig> <payment_preimage>

If a revoked commitment transaction is published, the remote node can spend this output immediately with the following witness:

    <revocation_sig> <revocationpubkey>

The sending node can use the HTLC-timeout transaction to timeout the HTLC once the HTLC is expired, as shown below. This is the only way that the local node can timeout the HTLC, and this branch requires `<remotehtlcsig>`, which ensures that the local node cannot prematurely timeout the HTLC since the HTLC-timeout transaction has `cltv_expiry` as its specified `locktime`. The local node must also wait `to_self_delay` before accessing these funds, allowing for the remote node to claim these funds if the transaction has been revoked.

#### Received HTLC Outputs

This output sends funds to either the remote node after the HTLC-timeout or using the revocation key, or to an HTLC-success transaction with a successful payment preimage. The output is a P2WSH, with a witness script:

    # To remote node with revocation key
    OP_DUP OP_HASH160 <RIPEMD160(SHA256(revocationpubkey))> OP_EQUAL
    OP_IF
        OP_CHECKSIG
    OP_ELSE
        <remote_htlcpubkey> OP_SWAP OP_SIZE 32 OP_EQUAL
        OP_IF
            # To local node via HTLC-success transaction.
            OP_HASH160 <RIPEMD160(payment_hash)> OP_EQUALVERIFY
            2 OP_SWAP <local_htlcpubkey> 2 OP_CHECKMULTISIG
        OP_ELSE
            # To remote node after timeout.
            OP_DROP <cltv_expiry> OP_CHECKLOCKTIMEVERIFY OP_DROP
            OP_CHECKSIG
        OP_ENDIF
    OP_ENDIF

To timeout the HTLC, the remote node spends it with the witness:

    <remotehtlcsig> 0

If a revoked commitment transaction is published, the remote node can spend this output immediately with the following witness:

    <revocation_sig> <revocationpubkey>

To redeem the HTLC, the HTLC-success transaction is used as detailed below. This is the only way that the local node can spend the HTLC, since this branch requires `<remotehtlcsig>`, which ensures that the local node must wait `to_self_delay` before accessing these funds allowing for the remote node to claim these funds if the transaction has been revoked.

### Trimmed Outputs

Each peer specifies a `dust_limit_satoshis` below which outputs should
not be produced; these outputs that are not produced are termed "trimmed". A trimmed output is
considered too small to be worth creating and is instead added
to the commitment transaction fee. For HTLCs, it needs to be taken into
account that the second-stage HTLC transaction may also be below the
limit.

#### Requirements

The base fee:
  - before the commitment transaction outputs are determined:
    - MUST be subtracted from the `to_local` or `to_remote`
    outputs, as specified in [Fee Calculation](#fee-calculation).

The commitment transaction:
  - if the amount of the commitment transaction `to_local` output would be
less than `dust_limit_satoshis` set by the transaction owner:
    - MUST NOT contain that output.
  - otherwise:
    - MUST be generated as specified in [`to_local` Output](#to_local-output).
  - if the amount of the commitment transaction `to_remote` output would be
less than `dust_limit_satoshis` set by the transaction owner:
    - MUST NOT contain that output.
  - otherwise:
    - MUST be generated as specified in [`to_remote` Output](#to_remote-output).
  - for every offered HTLC:
    - if the HTLC amount minus the HTLC-timeout fee would be less than
    `dust_limit_satoshis` set by the transaction owner:
      - MUST NOT contain that output.
    - otherwise:
      - MUST be generated as specified in
      [Offered HTLC Outputs](#offered-htlc-outputs).
  - for every received HTLC:
    - if the HTLC amount minus the HTLC-success fee would be less than
    `dust_limit_satoshis` set by the transaction owner:
      - MUST NOT contain that output.
    - otherwise:
      - MUST be generated as specified in
      [Received HTLC Outputs](#received-htlc-outputs).

## HTLC-Timeout and HTLC-Success Transactions

These HTLC transactions are almost identical, except the HTLC-timeout transaction is timelocked. Both HTLC-timeout/HTLC-success transactions can be spent by a valid penalty transaction.

* version: 2
* locktime: `0` for HTLC-success, `cltv_expiry` for HTLC-timeout
* txin count: 1
   * `txin[0]` outpoint: `txid` of the commitment transaction and `output_index` of the matching HTLC output for the HTLC transaction
   * `txin[0]` sequence: `0`
   * `txin[0]` script bytes: `0`
   * `txin[0]` witness stack: `0 <remotehtlcsig> <localhtlcsig>  <payment_preimage>` for HTLC-success, `0 <remotehtlcsig> <localhtlcsig> 0` for HTLC-timeout
* txout count: 1
   * `txout[0]` amount: the HTLC amount minus fees (see [Fee Calculation](#fee-calculation))
   * `txout[0]` script: version-0 P2WSH with witness script as shown below

The witness script for the output is:

    OP_IF
        # Penalty transaction
        <revocationpubkey>
    OP_ELSE
        `to_self_delay`
        OP_CHECKSEQUENCEVERIFY
        OP_DROP
        <local_delayedpubkey>
    OP_ENDIF
    OP_CHECKSIG

To spend this via penalty, the remote node uses a witness stack `<revocationsig> 1`, and to collect the output, the local node uses an input with nSequence `to_self_delay` and a witness stack `<local_delayedsig> 0`.

## Closing Transaction

Note that there are two possible variants for each node.

* version: 2
* locktime: 0
* txin count: 1
   * `txin[0]` outpoint: `txid` and `output_index` from `funding_created` message
   * `txin[0]` sequence: 0xFFFFFFFF
   * `txin[0]` script bytes: 0
   * `txin[0]` witness: `0 <signature_for_pubkey1> <signature_for_pubkey2>`
* txout count: 0, 1 or 2
   * `txout` amount: final balance to be paid to one node (minus `fee_satoshis` from `closing_signed`, if this peer funded the channel)
   * `txout` script: as specified in that node's `scriptpubkey` in its `shutdown` message

### Requirements

Each node offering a signature:
  - MUST round each output down to whole satoshis.
  - MUST subtract the fee given by `fee_satoshis` from the output to the funder.
  - MUST remove any output below its own `dust_limit_satoshis`.
  - MAY eliminate its own output.

### Rationale

There is a possibility of irreparable differences on closing if one
node considers the other's output too small to allow propagation on
the Bitcoin network (a.k.a. "dust"), and that other node instead
considers that output too valuable to discard. This is why each
side uses its own `dust_limit_satoshis`, and the result can be a
signature validation failure, if they disagree on what the closing
transaction should look like.

However, if one side chooses to eliminate its own output, there's no
reason for the other side to fail the closing protocol; so this is
explicitly allowed. The signature indicates which variant
has been used.

There will be at least one output, if the funding amount is greater
than twice `dust_limit_satoshis`.

## Fees

### Fee Calculation

The fee calculation for both commitment transactions and HTLC
transactions is based on the current `feerate_per_kw` and the
*expected weight* of the transaction.

The actual and expected weights vary for several reasons:

* Bitcoin uses DER-encoded signatures, which vary in size.
* Bitcoin also uses variable-length integers, so a large number of outputs will take 3 bytes to encode rather than 1.
* The `to_remote` output may be below the dust limit.
* The `to_local` output may be below the dust limit once fees are extracted.

Thus, a simplified formula for *expected weight* is used, which assumes:

* Signatures are 73 bytes long (the maximum length).
* There are a small number of outputs (thus 1 byte to count them).
* There are always both a `to_local` output and a `to_remote` output.

This yields the following *expected weights* (details of the computation in [Appendix A](#appendix-a-expected-weights)):

    Commitment weight:   724 + 172 * num-untrimmed-htlc-outputs
    HTLC-timeout weight: 663
    HTLC-success weight: 703

Note the reference to the "base fee" for a commitment transaction in the requirements below, which is what the funder pays. The actual fee may be higher than the amount calculated here, due to rounding and trimmed outputs.

#### Requirements

The fee for an HTLC-timeout transaction:
  - MUST BE calculated to match:
    1. Multiply `feerate_per_kw` by 663 and divide by 1000 (rounding down).

The fee for an HTLC-success transaction:
  - MUST BE calculated to match:
    1. Multiply `feerate_per_kw` by 703 and divide by 1000 (rounding down).

The base fee for a commitment transaction:
  - MUST be calculated to match:
    1. Start with `weight` = 724.
    2. For each committed HTLC, if that output is not trimmed as specified in
    [Trimmed Outputs](#trimmed-outputs), add 172 to `weight`.
    3. Multiply `feerate_per_kw` by `weight`, divide by 1000 (rounding down).

#### Example

For example, suppose there is a `feerate_per_kw` of 5000, a `dust_limit_satoshis` of 546 satoshis, and a commitment transaction with:
* two offered HTLCs of 5000000 and 1000000 millisatoshis (5000 and 1000 satoshis)
* two received HTLCs of 7000000 and 800000 millisatoshis (7000 and 800 satoshis)

The HTLC-timeout transaction `weight` is 663, and thus the fee is 3315 satoshis.
The HTLC-success transaction `weight` is 703, and thus the fee is 3515 satoshis

The commitment transaction `weight` is calculated as follows:

* `weight` starts at 724.

* The offered HTLC of 5000 satoshis is above 546 + 3315 and results in:
  * an output of 5000 satoshi in the commitment transaction
  * an HTLC-timeout transaction of 5000 - 3315 satoshis that spends this output
  * `weight` increases to 896

* The offered HTLC of 1000 satoshis is below 546 + 3315 so it is trimmed.

* The received HTLC of 7000 satoshis is above 546 + 3515 and results in:
  * an output of 7000 satoshi in the commitment transaction
  * an HTLC-success transaction of 7000 - 3515 satoshis that spends this output
  * `weight` increases to 1068

* The received HTLC of 800 satoshis is below 546 + 3515 so it is trimmed.

The base commitment transaction fee is 5340 satoshi; the actual
fee (which adds the 1000 and 800 satoshi HTLCs that would make dust
outputs) is 7140 satoshi. The final fee may be even higher if the
`to_local` or `to_remote` outputs fall below `dust_limit_satoshis`.

### Fee Payment

Base commitment transaction fees are extracted from the funder's amount; if that amount is insufficient, the entire amount of the funder's output is used.

Note that after the fee amount is subtracted from the to-funder output,
that output may be below `dust_limit_satoshis`, and thus will also
contribute to fees.

A node:
  - if the resulting fee rate is too low:
    - MAY fail the channel.

## Channel Establishment v2 Funding Transaction Fees

For channel establishment v2, fees are paid by the opener (the node that
sends the `open_channel` message). Change, if any, is paid to the
opener's change address, a zero value output in their output set.

A change output of value `change_satoshis` will be included if its
value is greater than `dust_limit_satoshis`.

```
    change_satoshis = sum(inputs.satoshis) - est_tx_fee
                      - sum(outputs.satoshis) - sum(funding_satoshis)
```

### Calculating `est_tx_fee`

The fee for a v2 funding transaction is calculated in up to two rounds.
 - if the `opener` provided a change address, first:
   - MUST calculate the `est_tx_fee` as:
      1. Multiply (funding_transaction_weight + witness_weight) by `feerate_per_kw_funding`
         and divide by 1000 (rounding down).
      2. Confirm that `change_satoshis` is greater than `dust_limit_satoshis`.
 - if no change address is provided or `change_satoshis` is less
   than or equal to the negotiated `dust_limit_satoshis`:
   - MUST calculate the `est_tx_fee` without the change output (if provided) as:
      1. Multiply (funding_transaction_weight - change_output_weight +
         witness_weight) by `feerate_per_kw_funding` and divide by
         1000 (rounding down).
      2. As there is no change_output, any remaining `change_satoshis`
         will be added to the funding output, and credited to the opener's
         initial channel balance.
   - if the resulting `change_satoshis` is less than zero:
      - `opener_funding` will be decreased by the difference.


Computation details are included in [Appendix A](#appendix-a-expected-weights) and [Appendix F, Dual Funded Transaction Test Vectors](#appendix-f-dual-funded-transaction-test-vectors).

## Commitment Transaction Construction

This section ties the previous sections together to detail the
algorithm for constructing the commitment transaction for one peer:
given that peer's `dust_limit_satoshis`, the current `feerate_per_kw`,
the amounts due to each peer (`to_local` and `to_remote`), and all
committed HTLCs:

1. Initialize the commitment transaction input and locktime, as specified
   in [Commitment Transaction](#commitment-transaction).
1. Calculate which committed HTLCs need to be trimmed (see [Trimmed Outputs](#trimmed-outputs)).
2. Calculate the base [commitment transaction fee](#fee-calculation).
3. Subtract this base fee from the funder (either `to_local` or `to_remote`),
   with a floor of 0 (see [Fee Payment](#fee-payment)).
3. For every offered HTLC, if it is not trimmed, add an
   [offered HTLC output](#offered-htlc-outputs).
4. For every received HTLC, if it is not trimmed, add an
   [received HTLC output](#received-htlc-outputs).
5. If the `to_local` amount is greater or equal to `dust_limit_satoshis`,
   add a [`to_local` output](#to_local-output).
6. If the `to_remote` amount is greater or equal to `dust_limit_satoshis`,
   add a [`to_remote` output](#to_remote-output).
7. Sort the outputs into [BIP 69+CLTV order](#transaction-input-and-output-ordering).

# Keys

## Key Derivation

Each commitment transaction uses a unique `localpubkey`, and a `remotepubkey`.
The HTLC-success and HTLC-timeout transactions use `local_delayedpubkey` and `revocationpubkey`.
These are changed for every transaction based on the `per_commitment_point`, with the exception of `remotepubkey` if `option_static_remotekey` is negotiated.

The reason for key change is so that trustless watching for revoked
transactions can be outsourced. Such a _watcher_ should not be able to
determine the contents of a commitment transaction — even if the _watcher_ knows
which transaction ID to watch for and can make a reasonable guess
as to which HTLCs and balances may be included. Nonetheless, to
avoid storage of every commitment transaction, a _watcher_ can be given the
`per_commitment_secret` values (which can be stored compactly) and the
`revocation_basepoint` and `delayed_payment_basepoint` used to regenerate
the scripts required for the penalty transaction; thus, a _watcher_ need only be
given (and store) the signatures for each penalty input.

Changing the `localpubkey` every time ensures that commitment
transaction ID cannot be guessed except in the trivial case where there is no
`to_local` output, as every commitment transaction uses an ID
in its output script. Splitting the `local_delayedpubkey`, which is required for
the penalty transaction, allows it to be shared with the _watcher_ without
revealing `localpubkey`; even if both peers use the same _watcher_, nothing is revealed.

Finally, even in the case of normal unilateral close, the HTLC-success
and/or HTLC-timeout transactions do not reveal anything to the
_watcher_, as it does not know the corresponding `per_commitment_secret` and
cannot relate the `local_delayedpubkey` or `revocationpubkey` with their bases.

For efficiency, keys are generated from a series of per-commitment secrets
that are generated from a single seed, which allows the receiver to compactly
store them (see [below](#efficient-per-commitment-secret-storage)).

### `localpubkey`, `local_htlcpubkey`, `remote_htlcpubkey`, `local_delayedpubkey`, and `remote_delayedpubkey` Derivation

These pubkeys are simply generated by addition from their base points:

	pubkey = basepoint + SHA256(per_commitment_point || basepoint) * G

The `localpubkey` uses the local node's `payment_basepoint`;
the `local_htlcpubkey` uses the local node's `htlc_basepoint`;
the `remote_htlcpubkey` uses the remote node's `htlc_basepoint`;
the `local_delayedpubkey` uses the local node's `delayed_payment_basepoint`;
and the `remote_delayedpubkey` uses the remote node's `delayed_payment_basepoint`.

The corresponding private keys can be similarly derived, if the basepoint
secrets are known (i.e. the private keys corresponding to `localpubkey`, `local_htlcpubkey`, and `local_delayedpubkey` only):

    privkey = basepoint_secret + SHA256(per_commitment_point || basepoint)

### `remotepubkey` Derivation

If `option_static_remotekey` is negotiated the `remotepubkey` is simply the
remote node's `payment_basepoint`, otherwise it is calculated as above using
the remote node's `payment_basepoint`.

The simplified derivation means that a node can spend a commitment
transaction even if it has lost data and doesn't know the
corresponding `per_commitment_point`.  A watchtower could correlate
transactions given to it which only have a `to_remote` output if it
sees one of them onchain, but such transactions do not need any
enforcement and should not be handed to a watchtower.

### `revocationpubkey` Derivation

The `revocationpubkey` is a blinded key: when the local node wishes to create a new
commitment for the remote node, it uses its own `revocation_basepoint` and the remote
node's `per_commitment_point` to derive a new `revocationpubkey` for the
commitment. After the remote node reveals the
`per_commitment_secret` used (thereby revoking that commitment), the local node
can then derive the `revocationprivkey`, as it now knows the two secrets
necessary to derive the key (`revocation_basepoint_secret` and
`per_commitment_secret`).

The `per_commitment_point` is generated using elliptic-curve multiplication:

	per_commitment_point = per_commitment_secret * G

And this is used to derive the revocation pubkey from the remote node's
`revocation_basepoint`:

	revocationpubkey = revocation_basepoint * SHA256(revocation_basepoint || per_commitment_point) + per_commitment_point * SHA256(per_commitment_point || revocation_basepoint)

This construction ensures that neither the node providing the
basepoint nor the node providing the `per_commitment_point` can know the
private key without the other node's secret.

The corresponding private key can be derived once the `per_commitment_secret`
is known:

    revocationprivkey = revocation_basepoint_secret * SHA256(revocation_basepoint || per_commitment_point) + per_commitment_secret * SHA256(per_commitment_point || revocation_basepoint)

### Per-commitment Secret Requirements

A node:
  - MUST select an unguessable 256-bit seed for each connection,
  - MUST NOT reveal the seed.

Up to (2^48 - 1) per-commitment secrets can be generated.

The first secret used:
  - MUST be index 281474976710655,
    - and from there, the index is decremented.

The I'th secret P:
  - MUST match the output of this algorithm:
```
generate_from_seed(seed, I):
    P = seed
    for B in 47 down to 0:
        if B set in I:
            flip(B) in P
            P = SHA256(P)
    return P
```

Where "flip(B)" alternates the B'th least significant bit in the value P.

The receiving node:
  - MAY store all previous per-commitment secrets.
  - MAY calculate them from a compact representation, as described below.

## Efficient Per-commitment Secret Storage

The receiver of a series of secrets can store them compactly in an
array of 49 (value,index) pairs. Because, for a given secret on a
2^X boundary, all secrets up to the next 2^X boundary can be derived;
and secrets are always received in descending order starting at
`0xFFFFFFFFFFFF`.

In binary, it's helpful to think of any index in terms of a *prefix*,
followed by some trailing 0s. You can derive the secret for any
index that matches this *prefix*.

For example, secret `0xFFFFFFFFFFF0` allows the secrets to be derived for
`0xFFFFFFFFFFF1` through `0xFFFFFFFFFFFF`, inclusive; and secret `0xFFFFFFFFFF08`
allows the secrets to be derived for `0xFFFFFFFFFF09` through `0xFFFFFFFFFF0F`,
inclusive.

This is done using a slight generalization of `generate_from_seed` above:

    # Return I'th secret given base secret whose index has bits..47 the same.
    derive_secret(base, bits, I):
        P = base
        for B in bits - 1 down to 0:
            if B set in I:
                flip(B) in P
                P = SHA256(P)
        return P

Only one secret for each unique prefix need be saved; in effect, the number of
trailing 0s is counted, and this determines where in the storage array the
secret is stored:

    # a.k.a. count trailing 0s
    where_to_put_secret(I):
        for B in 0 to 47:
            if testbit(I) in B == 1:
                return B
        # I = 0, this is the seed.
        return 48

A double-check, that all previous secrets derive correctly, is needed;
if this check fails, the secrets were not generated from the same seed:

    insert_secret(secret, I):
        B = where_to_put_secret(secret, I)

        # This tracks the index of the secret in each bucket across the traversal.
        for b in 0 to B:
            if derive_secret(secret, B, known[b].index) != known[b].secret:
                error The secret for I is incorrect
                return

        # Assuming this automatically extends known[] as required.
        known[B].index = I
        known[B].secret = secret

Finally, if an unknown secret at index `I` needs be derived, it must be
discovered which known secret can be used to derive it. The simplest
method is iterating over all the known secrets, and testing if each
can be used to derive the unknown secret:

    derive_old_secret(I):
        for b in 0 to len(secrets):
            # Mask off the non-zero prefix of the index.
            MASK = ~((1 << b) - 1)
            if (I & MASK) == secrets[b].index:
                return derive_secret(known, i, I)
        error Index 'I' hasn't been received yet.

This looks complicated, but remember that the index in entry `b` has
`b` trailing 0s; the mask and compare simply checks if the index
at each bucket is a prefix of the desired index.

# Appendix A: Expected Weights

## Expected Weight of the Funding Transaction (v2 Channel Establishment)

The *expected weight* of a funding transaction is calculated as follows:

      inputs: 40 bytes + var_int + `scriptlen`
		- previous_out_point: 36 bytes
			- hash: 32 bytes
			- index: 4 bytes
		- var_int: ? bytes (dependent on `scriptlen`)
		- script_sig: `scriptlen`
		- witness <----	Cost for "witness" data calculated separately.
		- sequence: 4 bytes

       non_funding_outputs: 8 bytes + var_int + `scriptlen`
                - value: 8 bytes
                - var_int: ? bytes (dependent on `scriptlen`)
                - script_sig: `scriptlen`

       funding_output: 43 bytes
                - value: 8 bytes
                - var_int: 1 byte
                - script: 34 bytes
		  - OP_0: 1 byte
		  - PUSHDATA(32-byte-hash): 33 bytes

Multiplying non-witness data by 4 results in a weight of:

	// transaction_fields = 10 (version, input count, output count, locktime)
	// segwit_fields = 2 (marker + flag)
	// funding_transaction = 43 + num_inputs * 40 + num_outputs * 8
        //                       + sum(scriptlen) + sum(var_ints) +
	funding_transaction_weight = 4 * (funding_transaction + transaction_fields) + segwit_fields

	witness_weight = sum(max_witness_len)

	overall_weight = funding_transaction_weight + witness_weight


## Expected Weight of the Commitment Transaction

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
		- witness <----	"witness" is used instead of "script_sig" for
	 			transaction validation; however, "witness" is stored
	 			separately, and the cost for its size is smaller. So,
	 		    the calculation of ordinary data is separated
	 			from the witness data.
		- sequence: 4 bytes

	output_paying_to_local: 43 bytes
		- value: 8 bytes
		- var_int: 1 byte (pk_script length)
		- pk_script (p2wsh): 34 bytes

	output_paying_to_remote: 31 bytes
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
			output_paying_to_remote,
			output_paying_to_local,
			....htlc_output's...
		- lock_time: 4 bytes

Multiplying non-witness data by 4 results in a weight of:

	// 500 + 172 * num-htlc-outputs weight
	commitment_transaction_weight = 4 * commitment_transaction

	// 224 weight
	witness_weight = witness_header + witness

	overall_weight = 500 + 172 * num-htlc-outputs + 224 weight

## Expected Weight of HTLC-timeout and HTLC-success Transactions

The *expected weight* of an HTLC transaction is calculated as follows:

    accepted_htlc_script: 139 bytes
        - OP_DUP: 1 byte
        - OP_HASH160: 1 byte
        - OP_DATA: 1 byte (RIPEMD160(SHA256(revocationpubkey)) length)
        - RIPEMD160(SHA256(revocationpubkey)): 20 bytes
        - OP_EQUAL: 1 byte
        - OP_IF: 1 byte
        - OP_CHECKSIG: 1 byte
        - OP_ELSE: 1 byte
        - OP_DATA: 1 byte (remotepubkey length)
        - remotepubkey: 33 bytes
        - OP_SWAP: 1 byte
        - OP_SIZE: 1 byte
        - OP_DATA: 1 byte (32 length)
        - 32: 1 byte
        - OP_EQUAL: 1 byte
        - OP_IF: 1 byte
        - OP_HASH160: 1 byte
		- OP_DATA: 1 byte (RIPEMD160(payment_hash) length)
		- RIPEMD160(payment_hash): 20 bytes
        - OP_EQUALVERIFY: 1 byte
        - 2: 1 byte
        - OP_SWAP: 1 byte
		- OP_DATA: 1 byte (localpubkey length)
		- localpubkey: 33 bytes
        - 2: 1 byte
        - OP_CHECKMULTISIG: 1 byte
        - OP_ELSE: 1 byte
        - OP_DROP: 1 byte
		- OP_DATA: 1 byte (cltv_expiry length)
		- cltv_expiry: 3 bytes
        - OP_CHECKLOCKTIMEVERIFY: 1 byte
        - OP_DROP: 1 byte
        - OP_CHECKSIG: 1 byte
        - OP_ENDIF: 1 byte
        - OP_ENDIF: 1 byte

    offered_htlc_script: 133 bytes
        - OP_DUP: 1 byte
        - OP_HASH160: 1 byte
        - OP_DATA: 1 byte (RIPEMD160(SHA256(revocationpubkey)) length)
        - RIPEMD160(SHA256(revocationpubkey)): 20 bytes
        - OP_EQUAL: 1 byte
        - OP_IF: 1 byte
        - OP_CHECKSIG: 1 byte
        - OP_ELSE: 1 byte
		- OP_DATA: 1 byte (remotepubkey length)
		- remotepubkey: 33 bytes
		- OP_SWAP: 1 byte
		- OP_SIZE: 1 byte
		- OP_DATA: 1 byte (32 length)
		- 32: 1 byte
		- OP_EQUAL: 1 byte
		- OP_NOTIF: 1 byte
		- OP_DROP: 1 byte
		- 2: 1 byte
		- OP_SWAP: 1 byte
		- OP_DATA: 1 byte (localpubkey length)
		- localpubkey: 33 bytes
		- 2: 1 byte
		- OP_CHECKMULTISIG: 1 byte
		- OP_ELSE: 1 byte
		- OP_HASH160: 1 byte
		- OP_DATA: 1 byte (RIPEMD160(payment_hash) length)
		- RIPEMD160(payment_hash): 20 bytes
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

Multiplying non-witness data by 4 results in a weight of 376. Adding
the witness data for each case (285 + 2 for HTLC-timeout, 325 + 2 for
HTLC-success) results in weights of:

	663 (HTLC-timeout)
	703 (HTLC-success)

# Appendix B: Funding Transaction Test Vectors

In the following:
 - It's assumed that *local* is the funder.
 - Private keys are displayed as 32 bytes plus a trailing 1 (Bitcoin's convention for "compressed" private keys, i.e. keys for which the public key is compressed).
 - Transaction signatures are all deterministic, using RFC6979 (using HMAC-SHA256). A valid signature MUST sign all inputs and outputs of the relevant transaction (i.e. MUST be created with a `SIGHASH_ALL` [signature hash](https://bitcoin.org/en/glossary/signature-hash)), unless explicitly stated otherwise. Note that clients MUST send the signature in compact encoding and not in Bitcoin-script format, thus the signature hash byte is not transmitted.

The input for the funding transaction was created using a test chain
with the following first two blocks; the second block contains a spendable
coinbase (note that such a P2PKH input is inadvisable, as detailed in [BOLT #2](02-peer-protocol.md#the-funding_created-message), but provides the simplest example):

    Block 0 (genesis): 0100000000000000000000000000000000000000000000000000000000000000000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4adae5494dffff7f20020000000101000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4d04ffff001d0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e206272696e6b206f66207365636f6e64206261696c6f757420666f722062616e6b73ffffffff0100f2052a01000000434104678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5fac00000000
    Block 1: 0000002006226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910fadbb20ea41a8423ea937e76e8151636bf6093b70eaff942930d20576600521fdc30f9858ffff7f20000000000101000000010000000000000000000000000000000000000000000000000000000000000000ffffffff03510101ffffffff0100f2052a010000001976a9143ca33c2e4446f4a305f23c80df8ad1afdcf652f988ac00000000
    Block 1 coinbase transaction: 01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff03510101ffffffff0100f2052a010000001976a9143ca33c2e4446f4a305f23c80df8ad1afdcf652f988ac00000000
    Block 1 coinbase privkey: 6bd078650fcee8444e4e09825227b801a1ca928debb750eb36e6d56124bb20e801
    # privkey in base58: cRCH7YNcarfvaiY1GWUKQrRGmoezvfAiqHtdRvxe16shzbd7LDMz
    # pubkey in base68: mm3aPLSv9fBrbS68JzurAMp4xGoddJ6pSf

The funding transaction is paid to the following pubkeys:

    local_funding_pubkey: 023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb
    remote_funding_pubkey: 030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c1
    # funding witness script = 5221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae

The funding transaction has a single input and a change output (order
determined by BIP69 in this case):

    input txid: fd2105607605d2302994ffea703b09f66b6351816ee737a93e42a841ea20bbad
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
 - *local* transactions are considered, which implies that all payments to *local* are delayed.
 - It's assumed that *local* is the opener.
 - Private keys are displayed as 32 bytes plus a trailing 1 (Bitcoin's convention for "compressed" private keys, i.e. keys for which the public key is compressed).
 - Transaction signatures are all deterministic, using RFC6979 (using HMAC-SHA256).

To start, common basic parameters for each test vector are defined: the
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

<!-- The test vector values are derived, as per Key Derivation, though it's not
     required for this test. They're included here for completeness and
	 in case someone wants to reproduce the test vectors themselves:

INTERNAL: remote_funding_privkey: 1552dfba4f6cf29a62a0af13c8d6981d36d0ef8d61ba10fb0fe90da7634d7e1301
INTERNAL: local_payment_basepoint_secret: 111111111111111111111111111111111111111111111111111111111111111101
INTERNAL: remote_revocation_basepoint_secret: 222222222222222222222222222222222222222222222222222222222222222201
INTERNAL: local_delayed_payment_basepoint_secret: 333333333333333333333333333333333333333333333333333333333333333301
INTERNAL: remote_payment_basepoint_secret: 444444444444444444444444444444444444444444444444444444444444444401
x_local_per_commitment_secret: 1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a0908070605040302010001
# From remote_revocation_basepoint_secret
INTERNAL: remote_revocation_basepoint: 02466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27
# From local_delayed_payment_basepoint_secret
INTERNAL: local_delayed_payment_basepoint: 023c72addb4fdf09af94f0c94d7fe92a386a7e70cf8a1d85916386bb2535c7b1b1
INTERNAL: local_per_commitment_point: 025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486
INTERNAL: remote_privkey: 8deba327a7cc6d638ab0eb025770400a6184afcba6713c210d8d10e199ff2fda01
# From local_delayed_payment_basepoint_secret, local_per_commitment_point and local_delayed_payment_basepoint
INTERNAL: local_delayed_privkey: adf3464ce9c2f230fd2582fda4c6965e4993ca5524e8c9580e3df0cf226981ad01
-->

Here are the points used to derive the obscuring factor for the commitment number:

    local_payment_basepoint: 034f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa
    remote_payment_basepoint: 032c0b7cf95324a07d05398b240174dc0c2be444d96b159aa6c7f7b1e668680991
    # obscured commitment number = 0x2bb038521914 ^ 42

And, here are the keys needed to create the transactions:

    local_funding_privkey: 30ff4956bbdd3222d44cc5e8a1261dab1e07957bdac5ae88fe3261ef321f374901
    local_funding_pubkey: 023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb
    remote_funding_pubkey: 030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c1
    local_privkey: bb13b121cdc357cd2e608b0aea294afca36e2b34cf958e2e6451a2f27469449101
    localpubkey: 030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e7
    remotepubkey: 0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b
    local_delayedpubkey: 03fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c
    local_revocation_pubkey: 0212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b19
    # funding wscript = 5221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae

And, here are the test vectors themselves:

    name: simple commitment tx with no HTLCs
    to_local_msat: 7000000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 15000
    # base commitment transaction fee = 10860
    # actual commitment transaction fee = 10860
    # to_local amount 6989140 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100f51d2e566a70ba740fc5d8c0f07b9b93d2ed741c3c0860c613173de7d39e7968022041376d520e9c0e1ad52248ddf4b22e12be8763007df977253ef45a4ca3bdb7c0
    # local_signature = 3044022051b75c73198c6deee1a875871c3961832909acd297c6b908d59e3319e5185a46022055c419379c5051a78d00dbbce11b5b664a0c22815fbcc6fcef6b1937c3836939
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8002c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311054a56a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022051b75c73198c6deee1a875871c3961832909acd297c6b908d59e3319e5185a46022055c419379c5051a78d00dbbce11b5b664a0c22815fbcc6fcef6b1937c383693901483045022100f51d2e566a70ba740fc5d8c0f07b9b93d2ed741c3c0860c613173de7d39e7968022041376d520e9c0e1ad52248ddf4b22e12be8763007df977253ef45a4ca3bdb7c001475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

    name: commitment tx with all five HTLCs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 0
    # base commitment transaction fee = 0
    # actual commitment transaction fee = 0
    # HTLC 2 offered amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868
    # HTLC 3 offered amount 3000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868
    # HTLC 0 received amount 1000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac6868
    # HTLC 1 received amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6868
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6988000 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 304402204fd4928835db1ccdfc40f5c78ce9bd65249b16348df81f0c44328dcdefc97d630220194d3869c38bc732dd87d13d2958015e2fc16829e74cd4377f84d215c0b70606
    # local_signature = 30440220275b0c325a5e9355650dc30c0eccfbc7efb23987c24b556b9dfdd40effca18d202206caceb2c067836c51f296740c7ae807ffcbfbf1dd3a0d56b6de9a5b247985f06
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8007e80300000000000022002052bfef0479d7b293c27e0f1eb294bea154c63a3294ef092c19af51409bce0e2ad007000000000000220020403d394747cae42e98ff01734ad5c08f82ba123d3d9a620abda88989651e2ab5d007000000000000220020748eba944fedc8827f6b06bc44678f93c0f9e6078b35c6331ed31e75f8ce0c2db80b000000000000220020c20b5d1f8584fd90443e7b7b720136174fa4b9333c261d04dbbd012635c0f419a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110e0a06a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004730440220275b0c325a5e9355650dc30c0eccfbc7efb23987c24b556b9dfdd40effca18d202206caceb2c067836c51f296740c7ae807ffcbfbf1dd3a0d56b6de9a5b247985f060147304402204fd4928835db1ccdfc40f5c78ce9bd65249b16348df81f0c44328dcdefc97d630220194d3869c38bc732dd87d13d2958015e2fc16829e74cd4377f84d215c0b7060601475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (HTLC 0)
    remote_htlc_signature = 304402206a6e59f18764a5bf8d4fa45eebc591566689441229c918b480fb2af8cc6a4aeb02205248f273be447684b33e3c8d1d85a8e0ca9fa0bae9ae33f0527ada9c162919a6
    # signature for output 1 (HTLC 2)
    remote_htlc_signature = 3045022100d5275b3619953cb0c3b5aa577f04bc512380e60fa551762ce3d7a1bb7401cff9022037237ab0dac3fe100cde094e82e2bed9ba0ed1bb40154b48e56aa70f259e608b
    # signature for output 2 (HTLC 1)
    remote_htlc_signature = 304402201b63ec807771baf4fdff523c644080de17f1da478989308ad13a58b51db91d360220568939d38c9ce295adba15665fa68f51d967e8ed14a007b751540a80b325f202
    # signature for output 3 (HTLC 3)
    remote_htlc_signature = 3045022100daee1808f9861b6c3ecd14f7b707eca02dd6bdfc714ba2f33bc8cdba507bb182022026654bf8863af77d74f51f4e0b62d461a019561bb12acb120d3f7195d148a554
    # signature for output 4 (HTLC 4)
    remote_htlc_signature = 304402207e0410e45454b0978a623f36a10626ef17b27d9ad44e2760f98cfa3efb37924f0220220bd8acd43ecaa916a80bd4f919c495a2c58982ce7c8625153f8596692a801d
    # local_signature = 304402207cb324fa0de88f452ffa9389678127ebcf4cabe1dd848b8e076c1a1962bf34720220116ed922b12311bd602d67e60d2529917f21c5b82f25ff6506c0f87886b4dfd5
    output htlc_success_tx 0: 020000000001018154ecccf11a5fb56c39654c4deb4d2296f83c69268280b94d021370c94e219700000000000000000001e8030000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402206a6e59f18764a5bf8d4fa45eebc591566689441229c918b480fb2af8cc6a4aeb02205248f273be447684b33e3c8d1d85a8e0ca9fa0bae9ae33f0527ada9c162919a60147304402207cb324fa0de88f452ffa9389678127ebcf4cabe1dd848b8e076c1a1962bf34720220116ed922b12311bd602d67e60d2529917f21c5b82f25ff6506c0f87886b4dfd5012000000000000000000000000000000000000000000000000000000000000000008a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac686800000000
    # local_signature = 3045022100c89172099507ff50f4c925e6c5150e871fb6e83dd73ff9fbb72f6ce829a9633f02203a63821d9162e99f9be712a68f9e589483994feae2661e4546cd5b6cec007be5
    output htlc_timeout_tx 2: 020000000001018154ecccf11a5fb56c39654c4deb4d2296f83c69268280b94d021370c94e219701000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d5275b3619953cb0c3b5aa577f04bc512380e60fa551762ce3d7a1bb7401cff9022037237ab0dac3fe100cde094e82e2bed9ba0ed1bb40154b48e56aa70f259e608b01483045022100c89172099507ff50f4c925e6c5150e871fb6e83dd73ff9fbb72f6ce829a9633f02203a63821d9162e99f9be712a68f9e589483994feae2661e4546cd5b6cec007be501008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868f6010000
    # local_signature = 3045022100def389deab09cee69eaa1ec14d9428770e45bcbe9feb46468ecf481371165c2f022015d2e3c46600b2ebba8dcc899768874cc6851fd1ecb3fffd15db1cc3de7e10da
    output htlc_success_tx 1: 020000000001018154ecccf11a5fb56c39654c4deb4d2296f83c69268280b94d021370c94e219702000000000000000001d0070000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402201b63ec807771baf4fdff523c644080de17f1da478989308ad13a58b51db91d360220568939d38c9ce295adba15665fa68f51d967e8ed14a007b751540a80b325f20201483045022100def389deab09cee69eaa1ec14d9428770e45bcbe9feb46468ecf481371165c2f022015d2e3c46600b2ebba8dcc899768874cc6851fd1ecb3fffd15db1cc3de7e10da012001010101010101010101010101010101010101010101010101010101010101018a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac686800000000
    # local_signature = 30440220643aacb19bbb72bd2b635bc3f7375481f5981bace78cdd8319b2988ffcc6704202203d27784ec8ad51ed3bd517a05525a5139bb0b755dd719e0054332d186ac08727
    output htlc_timeout_tx 3: 020000000001018154ecccf11a5fb56c39654c4deb4d2296f83c69268280b94d021370c94e219703000000000000000001b80b0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100daee1808f9861b6c3ecd14f7b707eca02dd6bdfc714ba2f33bc8cdba507bb182022026654bf8863af77d74f51f4e0b62d461a019561bb12acb120d3f7195d148a554014730440220643aacb19bbb72bd2b635bc3f7375481f5981bace78cdd8319b2988ffcc6704202203d27784ec8ad51ed3bd517a05525a5139bb0b755dd719e0054332d186ac0872701008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868f7010000
    # local_signature = 30440220549e80b4496803cbc4a1d09d46df50109f546d43fbbf86cd90b174b1484acd5402205f12a4f995cb9bded597eabfee195a285986aa6d93ae5bb72507ebc6a4e2349e
    output htlc_success_tx 4: 020000000001018154ecccf11a5fb56c39654c4deb4d2296f83c69268280b94d021370c94e219704000000000000000001a00f0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402207e0410e45454b0978a623f36a10626ef17b27d9ad44e2760f98cfa3efb37924f0220220bd8acd43ecaa916a80bd4f919c495a2c58982ce7c8625153f8596692a801d014730440220549e80b4496803cbc4a1d09d46df50109f546d43fbbf86cd90b174b1484acd5402205f12a4f995cb9bded597eabfee195a285986aa6d93ae5bb72507ebc6a4e2349e012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with seven outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 647
    # base commitment transaction fee = 1024
    # actual commitment transaction fee = 1024
    # HTLC 2 offered amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868
    # HTLC 3 offered amount 3000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868
    # HTLC 0 received amount 1000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac6868
    # HTLC 1 received amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6868
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6986976 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100a5c01383d3ec646d97e40f44318d49def817fcd61a0ef18008a665b3e151785502203e648efddd5838981ef55ec954be69c4a652d021e6081a100d034de366815e9b
    # local_signature = 304502210094bfd8f5572ac0157ec76a9551b6c5216a4538c07cd13a51af4a54cb26fa14320220768efce8ce6f4a5efac875142ff19237c011343670adf9c7ac69704a120d1163
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8007e80300000000000022002052bfef0479d7b293c27e0f1eb294bea154c63a3294ef092c19af51409bce0e2ad007000000000000220020403d394747cae42e98ff01734ad5c08f82ba123d3d9a620abda88989651e2ab5d007000000000000220020748eba944fedc8827f6b06bc44678f93c0f9e6078b35c6331ed31e75f8ce0c2db80b000000000000220020c20b5d1f8584fd90443e7b7b720136174fa4b9333c261d04dbbd012635c0f419a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110e09c6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040048304502210094bfd8f5572ac0157ec76a9551b6c5216a4538c07cd13a51af4a54cb26fa14320220768efce8ce6f4a5efac875142ff19237c011343670adf9c7ac69704a120d116301483045022100a5c01383d3ec646d97e40f44318d49def817fcd61a0ef18008a665b3e151785502203e648efddd5838981ef55ec954be69c4a652d021e6081a100d034de366815e9b01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 5
    # signature for output 0 (HTLC 0)
    remote_htlc_signature = 30440220385a5afe75632f50128cbb029ee95c80156b5b4744beddc729ad339c9ca432c802202ba5f48550cad3379ac75b9b4fedb86a35baa6947f16ba5037fb8b11ab343740
    # signature for output 1 (HTLC 2)
    remote_htlc_signature = 304402207ceb6678d4db33d2401fdc409959e57c16a6cb97a30261d9c61f29b8c58d34b90220084b4a17b4ca0e86f2d798b3698ca52de5621f2ce86f80bed79afa66874511b0
    # signature for output 2 (HTLC 1)
    remote_htlc_signature = 304402206a401b29a0dff0d18ec903502c13d83e7ec019450113f4a7655a4ce40d1f65ba0220217723a084e727b6ca0cc8b6c69c014a7e4a01fcdcba3e3993f462a3c574d833
    # signature for output 3 (HTLC 3)
    remote_htlc_signature = 30450221009b1c987ba599ee3bde1dbca776b85481d70a78b681a8d84206723e2795c7cac002207aac84ad910f8598c4d1c0ea2e3399cf6627a4e3e90131315bc9f038451ce39d
    # signature for output 4 (HTLC 4)
    remote_htlc_signature = 3045022100cc28030b59f0914f45b84caa983b6f8effa900c952310708c2b5b00781117022022027ba2ccdf94d03c6d48b327f183f6e28c8a214d089b9227f94ac4f85315274f0
    # local_signature = 304402205999590b8a79fa346e003a68fd40366397119b2b0cdf37b149968d6bc6fbcc4702202b1e1fb5ab7864931caed4e732c359e0fe3d86a548b557be2246efb1708d579a
    output htlc_success_tx 0: 020000000001018323148ce2419f21ca3d6780053747715832e18ac780931a514b187768882bb60000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220385a5afe75632f50128cbb029ee95c80156b5b4744beddc729ad339c9ca432c802202ba5f48550cad3379ac75b9b4fedb86a35baa6947f16ba5037fb8b11ab3437400147304402205999590b8a79fa346e003a68fd40366397119b2b0cdf37b149968d6bc6fbcc4702202b1e1fb5ab7864931caed4e732c359e0fe3d86a548b557be2246efb1708d579a012000000000000000000000000000000000000000000000000000000000000000008a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a914b8bcb07f6344b42ab04250c86a6e8b75d3fdbbc688527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f401b175ac686800000000
    # local_signature = 304402207ff03eb0127fc7c6cae49cc29e2a586b98d1e8969cf4a17dfa50b9c2647720b902205e2ecfda2252956c0ca32f175080e75e4e390e433feb1f8ce9f2ba55648a1dac
    output htlc_timeout_tx 2: 020000000001018323148ce2419f21ca3d6780053747715832e18ac780931a514b187768882bb60100000000000000000124060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402207ceb6678d4db33d2401fdc409959e57c16a6cb97a30261d9c61f29b8c58d34b90220084b4a17b4ca0e86f2d798b3698ca52de5621f2ce86f80bed79afa66874511b00147304402207ff03eb0127fc7c6cae49cc29e2a586b98d1e8969cf4a17dfa50b9c2647720b902205e2ecfda2252956c0ca32f175080e75e4e390e433feb1f8ce9f2ba55648a1dac01008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868f6010000
    # local_signature = 3045022100d50d067ca625d54e62df533a8f9291736678d0b86c28a61bb2a80cf42e702d6e02202373dde7e00218eacdafb9415fe0e1071beec1857d1af3c6a201a44cbc47c877
    output htlc_success_tx 1: 020000000001018323148ce2419f21ca3d6780053747715832e18ac780931a514b187768882bb6020000000000000000010a060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e050047304402206a401b29a0dff0d18ec903502c13d83e7ec019450113f4a7655a4ce40d1f65ba0220217723a084e727b6ca0cc8b6c69c014a7e4a01fcdcba3e3993f462a3c574d83301483045022100d50d067ca625d54e62df533a8f9291736678d0b86c28a61bb2a80cf42e702d6e02202373dde7e00218eacdafb9415fe0e1071beec1857d1af3c6a201a44cbc47c877012001010101010101010101010101010101010101010101010101010101010101018a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac686800000000
    # local_signature = 3045022100db9dc65291077a52728c622987e9895b7241d4394d6dcb916d7600a3e8728c22022036ee3ee717ba0bb5c45ee84bc7bbf85c0f90f26ae4e4a25a6b4241afa8a3f1cb
    output htlc_timeout_tx 3: 020000000001018323148ce2419f21ca3d6780053747715832e18ac780931a514b187768882bb6030000000000000000010c0a0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221009b1c987ba599ee3bde1dbca776b85481d70a78b681a8d84206723e2795c7cac002207aac84ad910f8598c4d1c0ea2e3399cf6627a4e3e90131315bc9f038451ce39d01483045022100db9dc65291077a52728c622987e9895b7241d4394d6dcb916d7600a3e8728c22022036ee3ee717ba0bb5c45ee84bc7bbf85c0f90f26ae4e4a25a6b4241afa8a3f1cb01008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868f7010000
    # local_signature = 304402202d1a3c0d31200265d2a2def2753ead4959ae20b4083e19553acfffa5dfab60bf022020ede134149504e15b88ab261a066de49848411e15e70f9e6a5462aec2949f8f
    output htlc_success_tx 4: 020000000001018323148ce2419f21ca3d6780053747715832e18ac780931a514b187768882bb604000000000000000001da0d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100cc28030b59f0914f45b84caa983b6f8effa900c952310708c2b5b00781117022022027ba2ccdf94d03c6d48b327f183f6e28c8a214d089b9227f94ac4f85315274f00147304402202d1a3c0d31200265d2a2def2753ead4959ae20b4083e19553acfffa5dfab60bf022020ede134149504e15b88ab261a066de49848411e15e70f9e6a5462aec2949f8f012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with six outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 648
    # base commitment transaction fee = 914
    # actual commitment transaction fee = 1914
    # HTLC 2 offered amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868
    # HTLC 3 offered amount 3000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868
    # HTLC 1 received amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6868
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6987086 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022072714e2fbb93cdd1c42eb0828b4f2eff143f717d8f26e79d6ada4f0dcb681bbe02200911be4e5161dd6ebe59ff1c58e1997c4aea804f81db6b698821db6093d7b057
    # local_signature = 3045022100a2270d5950c89ae0841233f6efea9c951898b301b2e89e0adbd2c687b9f32efa02207943d90f95b9610458e7c65a576e149750ff3accaacad004cd85e70b235e27de
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d007000000000000220020403d394747cae42e98ff01734ad5c08f82ba123d3d9a620abda88989651e2ab5d007000000000000220020748eba944fedc8827f6b06bc44678f93c0f9e6078b35c6331ed31e75f8ce0c2db80b000000000000220020c20b5d1f8584fd90443e7b7b720136174fa4b9333c261d04dbbd012635c0f419a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de8431104e9d6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100a2270d5950c89ae0841233f6efea9c951898b301b2e89e0adbd2c687b9f32efa02207943d90f95b9610458e7c65a576e149750ff3accaacad004cd85e70b235e27de01473044022072714e2fbb93cdd1c42eb0828b4f2eff143f717d8f26e79d6ada4f0dcb681bbe02200911be4e5161dd6ebe59ff1c58e1997c4aea804f81db6b698821db6093d7b05701475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (HTLC 2)
    remote_htlc_signature = 3044022062ef2e77591409d60d7817d9bb1e71d3c4a2931d1a6c7c8307422c84f001a251022022dad9726b0ae3fe92bda745a06f2c00f92342a186d84518588cf65f4dfaada8
    # signature for output 1 (HTLC 1)
    remote_htlc_signature = 3045022100e968cbbb5f402ed389fdc7f6cd2a80ed650bb42c79aeb2a5678444af94f6c78502204b47a1cb24ab5b0b6fe69fe9cfc7dba07b9dd0d8b95f372c1d9435146a88f8d4
    # signature for output 2 (HTLC 3)
    remote_htlc_signature = 3045022100aa91932e305292cf9969cc23502bbf6cef83a5df39c95ad04a707c4f4fed5c7702207099fc0f3a9bfe1e7683c0e9aa5e76c5432eb20693bf4cb182f04d383dc9c8c2
    # signature for output 3 (HTLC 4)
    remote_htlc_signature = 3044022035cac88040a5bba420b1c4257235d5015309113460bc33f2853cd81ca36e632402202fc94fd3e81e9d34a9d01782a0284f3044370d03d60f3fc041e2da088d2de58f
    # local_signature = 3045022100a4c574f00411dd2f978ca5cdc1b848c311cd7849c087ad2f21a5bce5e8cc5ae90220090ae39a9bce2fb8bc879d7e9f9022df249f41e25e51f1a9bf6447a9eeffc098
    output htlc_timeout_tx 2: 02000000000101579c183eca9e8236a5d7f5dcd79cfec32c497fdc0ec61533cde99ecd436cadd10000000000000000000123060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022062ef2e77591409d60d7817d9bb1e71d3c4a2931d1a6c7c8307422c84f001a251022022dad9726b0ae3fe92bda745a06f2c00f92342a186d84518588cf65f4dfaada801483045022100a4c574f00411dd2f978ca5cdc1b848c311cd7849c087ad2f21a5bce5e8cc5ae90220090ae39a9bce2fb8bc879d7e9f9022df249f41e25e51f1a9bf6447a9eeffc09801008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868f6010000
    # local_signature = 304402207679cf19790bea76a733d2fa0672bd43ab455687a068f815a3d237581f57139a0220683a1a799e102071c206b207735ca80f627ab83d6616b4bcd017c5d79ef3e7d0
    output htlc_success_tx 1: 02000000000101579c183eca9e8236a5d7f5dcd79cfec32c497fdc0ec61533cde99ecd436cadd10100000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e968cbbb5f402ed389fdc7f6cd2a80ed650bb42c79aeb2a5678444af94f6c78502204b47a1cb24ab5b0b6fe69fe9cfc7dba07b9dd0d8b95f372c1d9435146a88f8d40147304402207679cf19790bea76a733d2fa0672bd43ab455687a068f815a3d237581f57139a0220683a1a799e102071c206b207735ca80f627ab83d6616b4bcd017c5d79ef3e7d0012001010101010101010101010101010101010101010101010101010101010101018a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac686800000000
    # local_signature = 304402200df76fea718745f3c529bac7fd37923e7309ce38b25c0781e4cf514dd9ef8dc802204172295739dbae9fe0474dcee3608e3433b4b2af3a2e6787108b02f894dcdda3
    output htlc_timeout_tx 3: 02000000000101579c183eca9e8236a5d7f5dcd79cfec32c497fdc0ec61533cde99ecd436cadd1020000000000000000010b0a0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100aa91932e305292cf9969cc23502bbf6cef83a5df39c95ad04a707c4f4fed5c7702207099fc0f3a9bfe1e7683c0e9aa5e76c5432eb20693bf4cb182f04d383dc9c8c20147304402200df76fea718745f3c529bac7fd37923e7309ce38b25c0781e4cf514dd9ef8dc802204172295739dbae9fe0474dcee3608e3433b4b2af3a2e6787108b02f894dcdda301008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868f7010000
    # local_signature = 304402200daf2eb7afd355b4caf6fb08387b5f031940ea29d1a9f35071288a839c9039e4022067201b562456e7948616c13acb876b386b511599b58ac1d94d127f91c50463a6
    output htlc_success_tx 4: 02000000000101579c183eca9e8236a5d7f5dcd79cfec32c497fdc0ec61533cde99ecd436cadd103000000000000000001d90d0000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022035cac88040a5bba420b1c4257235d5015309113460bc33f2853cd81ca36e632402202fc94fd3e81e9d34a9d01782a0284f3044370d03d60f3fc041e2da088d2de58f0147304402200daf2eb7afd355b4caf6fb08387b5f031940ea29d1a9f35071288a839c9039e4022067201b562456e7948616c13acb876b386b511599b58ac1d94d127f91c50463a6012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with six outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2069
    # base commitment transaction fee = 2921
    # actual commitment transaction fee = 3921
    # HTLC 2 offered amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868
    # HTLC 3 offered amount 3000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868
    # HTLC 1 received amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac6868
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6985079 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022001d55e488b8b035b2dd29d50b65b530923a416d47f377284145bc8767b1b6a75022019bb53ddfe1cefaf156f924777eaaf8fdca1810695a7d0a247ad2afba8232eb4
    # local_signature = 304402203ca8f31c6a47519f83255dc69f1894d9a6d7476a19f498d31eaf0cd3a85eeb63022026fd92dc752b33905c4c838c528b692a8ad4ced959990b5d5ee2ff940fa90eea
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8006d007000000000000220020403d394747cae42e98ff01734ad5c08f82ba123d3d9a620abda88989651e2ab5d007000000000000220020748eba944fedc8827f6b06bc44678f93c0f9e6078b35c6331ed31e75f8ce0c2db80b000000000000220020c20b5d1f8584fd90443e7b7b720136174fa4b9333c261d04dbbd012635c0f419a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311077956a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402203ca8f31c6a47519f83255dc69f1894d9a6d7476a19f498d31eaf0cd3a85eeb63022026fd92dc752b33905c4c838c528b692a8ad4ced959990b5d5ee2ff940fa90eea01473044022001d55e488b8b035b2dd29d50b65b530923a416d47f377284145bc8767b1b6a75022019bb53ddfe1cefaf156f924777eaaf8fdca1810695a7d0a247ad2afba8232eb401475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 4
    # signature for output 0 (HTLC 2)
    remote_htlc_signature = 3045022100d1cf354de41c1369336cf85b225ed033f1f8982a01be503668df756a7e668b66022001254144fb4d0eecc61908fccc3388891ba17c5d7a1a8c62bdd307e5a513f992
    # signature for output 1 (HTLC 1)
    remote_htlc_signature = 3045022100d065569dcb94f090345402736385efeb8ea265131804beac06dd84d15dd2d6880220664feb0b4b2eb985fadb6ec7dc58c9334ea88ce599a9be760554a2d4b3b5d9f4
    # signature for output 2 (HTLC 3)
    remote_htlc_signature = 3045022100d4e69d363de993684eae7b37853c40722a4c1b4a7b588ad7b5d8a9b5006137a102207a069c628170ee34be5612747051bdcc087466dbaa68d5756ea81c10155aef18
    # signature for output 3 (HTLC 4)
    remote_htlc_signature = 30450221008ec888e36e4a4b3dc2ed6b823319855b2ae03006ca6ae0d9aa7e24bfc1d6f07102203b0f78885472a67ff4fe5916c0bb669487d659527509516fc3a08e87a2cc0a7c
    # local_signature = 3044022056eb1af429660e45a1b0b66568cb8c4a3aa7e4c9c292d5d6c47f86ebf2c8838f022065c3ac4ebe980ca7a41148569be4ad8751b0a724a41405697ec55035dae66402
    output htlc_timeout_tx 2: 02000000000101ca94a9ad516ebc0c4bdd7b6254871babfa978d5accafb554214137d398bfcf6a0000000000000000000175020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d1cf354de41c1369336cf85b225ed033f1f8982a01be503668df756a7e668b66022001254144fb4d0eecc61908fccc3388891ba17c5d7a1a8c62bdd307e5a513f99201473044022056eb1af429660e45a1b0b66568cb8c4a3aa7e4c9c292d5d6c47f86ebf2c8838f022065c3ac4ebe980ca7a41148569be4ad8751b0a724a41405697ec55035dae6640201008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868f6010000
    # local_signature = 3045022100914bb232cd4b2690ee3d6cb8c3713c4ac9c4fb925323068d8b07f67c8541f8d9022057152f5f1615b793d2d45aac7518989ae4fe970f28b9b5c77504799d25433f7f
    output htlc_success_tx 1: 02000000000101ca94a9ad516ebc0c4bdd7b6254871babfa978d5accafb554214137d398bfcf6a0100000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d065569dcb94f090345402736385efeb8ea265131804beac06dd84d15dd2d6880220664feb0b4b2eb985fadb6ec7dc58c9334ea88ce599a9be760554a2d4b3b5d9f401483045022100914bb232cd4b2690ee3d6cb8c3713c4ac9c4fb925323068d8b07f67c8541f8d9022057152f5f1615b793d2d45aac7518989ae4fe970f28b9b5c77504799d25433f7f012001010101010101010101010101010101010101010101010101010101010101018a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a9144b6b2e5444c2639cc0fb7bcea5afba3f3cdce23988527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f501b175ac686800000000
    # local_signature = 304402200e362443f7af830b419771e8e1614fc391db3a4eb799989abfc5ab26d6fcd032022039ab0cad1c14dfbe9446bf847965e56fe016e0cbcf719fd18c1bfbf53ecbd9f9
    output htlc_timeout_tx 3: 02000000000101ca94a9ad516ebc0c4bdd7b6254871babfa978d5accafb554214137d398bfcf6a020000000000000000015d060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100d4e69d363de993684eae7b37853c40722a4c1b4a7b588ad7b5d8a9b5006137a102207a069c628170ee34be5612747051bdcc087466dbaa68d5756ea81c10155aef180147304402200e362443f7af830b419771e8e1614fc391db3a4eb799989abfc5ab26d6fcd032022039ab0cad1c14dfbe9446bf847965e56fe016e0cbcf719fd18c1bfbf53ecbd9f901008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868f7010000
    # local_signature = 304402202c3e14282b84b02705dfd00a6da396c9fe8a8bcb1d3fdb4b20a4feba09440e8b02202b058b39aa9b0c865b22095edcd9ff1f71bbfe20aa4993755e54d042755ed0d5
    output htlc_success_tx 4: 02000000000101ca94a9ad516ebc0c4bdd7b6254871babfa978d5accafb554214137d398bfcf6a03000000000000000001f2090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221008ec888e36e4a4b3dc2ed6b823319855b2ae03006ca6ae0d9aa7e24bfc1d6f07102203b0f78885472a67ff4fe5916c0bb669487d659527509516fc3a08e87a2cc0a7c0147304402202c3e14282b84b02705dfd00a6da396c9fe8a8bcb1d3fdb4b20a4feba09440e8b02202b058b39aa9b0c865b22095edcd9ff1f71bbfe20aa4993755e54d042755ed0d5012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with five outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2070
    # base commitment transaction fee = 2566
    # actual commitment transaction fee = 5566
    # HTLC 2 offered amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868
    # HTLC 3 offered amount 3000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6985434 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100f2377f7a67b7fc7f4e2c0c9e3a7de935c32417f5668eda31ea1db401b7dc53030220415fdbc8e91d0f735e70c21952342742e25249b0d062d43efbfc564499f37526
    # local_signature = 30440220443cb07f650aebbba14b8bc8d81e096712590f524c5991ac0ed3bbc8fd3bd0c7022028a635f548e3ca64b19b69b1ea00f05b22752f91daf0b6dab78e62ba52eb7fd0
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d007000000000000220020403d394747cae42e98ff01734ad5c08f82ba123d3d9a620abda88989651e2ab5b80b000000000000220020c20b5d1f8584fd90443e7b7b720136174fa4b9333c261d04dbbd012635c0f419a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110da966a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e04004730440220443cb07f650aebbba14b8bc8d81e096712590f524c5991ac0ed3bbc8fd3bd0c7022028a635f548e3ca64b19b69b1ea00f05b22752f91daf0b6dab78e62ba52eb7fd001483045022100f2377f7a67b7fc7f4e2c0c9e3a7de935c32417f5668eda31ea1db401b7dc53030220415fdbc8e91d0f735e70c21952342742e25249b0d062d43efbfc564499f3752601475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (HTLC 2)
    remote_htlc_signature = 3045022100eed143b1ee4bed5dc3cde40afa5db3e7354cbf9c44054b5f713f729356f08cf7022077161d171c2bbd9badf3c9934de65a4918de03bbac1450f715275f75b103f891
    # signature for output 1 (HTLC 3)
    remote_htlc_signature = 3044022071e9357619fd8d29a411dc053b326a5224c5d11268070e88ecb981b174747c7a02202b763ae29a9d0732fa8836dd8597439460b50472183f420021b768981b4f7cf6
    # signature for output 2 (HTLC 4)
    remote_htlc_signature = 3045022100c9458a4d2cbb741705577deb0a890e5cb90ee141be0400d3162e533727c9cb2102206edcf765c5dc5e5f9b976ea8149bf8607b5a0efb30691138e1231302b640d2a4
    # local_signature = 3045022100a0d043ed533e7fb1911e0553d31a8e2f3e6de19dbc035257f29d747c5e02f1f5022030cd38d8e84282175d49c1ebe0470db3ebd59768cf40780a784e248a43904fb8
    output htlc_timeout_tx 2: 0200000000010140a83ce364747ff277f4d7595d8d15f708418798922c40bc2b056aca5485a2180000000000000000000174020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100eed143b1ee4bed5dc3cde40afa5db3e7354cbf9c44054b5f713f729356f08cf7022077161d171c2bbd9badf3c9934de65a4918de03bbac1450f715275f75b103f89101483045022100a0d043ed533e7fb1911e0553d31a8e2f3e6de19dbc035257f29d747c5e02f1f5022030cd38d8e84282175d49c1ebe0470db3ebd59768cf40780a784e248a43904fb801008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868f6010000
    # local_signature = 3045022100adb1d679f65f96178b59f23ed37d3b70443118f345224a07ecb043eee2acc157022034d24524fe857144a3bcfff3065a9994d0a6ec5f11c681e49431d573e242612d
    output htlc_timeout_tx 3: 0200000000010140a83ce364747ff277f4d7595d8d15f708418798922c40bc2b056aca5485a218010000000000000000015c060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022071e9357619fd8d29a411dc053b326a5224c5d11268070e88ecb981b174747c7a02202b763ae29a9d0732fa8836dd8597439460b50472183f420021b768981b4f7cf601483045022100adb1d679f65f96178b59f23ed37d3b70443118f345224a07ecb043eee2acc157022034d24524fe857144a3bcfff3065a9994d0a6ec5f11c681e49431d573e242612d01008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868f7010000
    # local_signature = 304402200831422aa4e1ee6d55e0b894201770a8f8817a189356f2d70be76633ffa6a6f602200dd1b84a4855dc6727dd46c98daae43dfc70889d1ba7ef0087529a57c06e5e04
    output htlc_success_tx 4: 0200000000010140a83ce364747ff277f4d7595d8d15f708418798922c40bc2b056aca5485a21802000000000000000001f1090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100c9458a4d2cbb741705577deb0a890e5cb90ee141be0400d3162e533727c9cb2102206edcf765c5dc5e5f9b976ea8149bf8607b5a0efb30691138e1231302b640d2a40147304402200831422aa4e1ee6d55e0b894201770a8f8817a189356f2d70be76633ffa6a6f602200dd1b84a4855dc6727dd46c98daae43dfc70889d1ba7ef0087529a57c06e5e04012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with five outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2194
    # base commitment transaction fee = 2720
    # actual commitment transaction fee = 5720
    # HTLC 2 offered amount 2000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868
    # HTLC 3 offered amount 3000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6985280 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100d33c4e541aa1d255d41ea9a3b443b3b822ad8f7f86862638aac1f69f8f760577022007e2a18e6931ce3d3a804b1c78eda1de17dbe1fb7a95488c9a4ec86203953348
    # local_signature = 304402203b1b010c109c2ecbe7feb2d259b9c4126bd5dc99ee693c422ec0a5781fe161ba0220571fe4e2c649dea9c7aaf7e49b382962f6a3494963c97d80fef9a430ca3f7061
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8005d007000000000000220020403d394747cae42e98ff01734ad5c08f82ba123d3d9a620abda88989651e2ab5b80b000000000000220020c20b5d1f8584fd90443e7b7b720136174fa4b9333c261d04dbbd012635c0f419a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311040966a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402203b1b010c109c2ecbe7feb2d259b9c4126bd5dc99ee693c422ec0a5781fe161ba0220571fe4e2c649dea9c7aaf7e49b382962f6a3494963c97d80fef9a430ca3f706101483045022100d33c4e541aa1d255d41ea9a3b443b3b822ad8f7f86862638aac1f69f8f760577022007e2a18e6931ce3d3a804b1c78eda1de17dbe1fb7a95488c9a4ec8620395334801475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 3
    # signature for output 0 (HTLC 2)
    remote_htlc_signature = 30450221009ed2f0a67f99e29c3c8cf45c08207b765980697781bb727fe0b1416de0e7622902206052684229bc171419ed290f4b615c943f819c0262414e43c5b91dcf72ddcf44
    # signature for output 1 (HTLC 3)
    remote_htlc_signature = 30440220155d3b90c67c33a8321996a9be5b82431b0c126613be751d400669da9d5c696702204318448bcd48824439d2c6a70be6e5747446be47ff45977cf41672bdc9b6b12d
    # signature for output 2 (HTLC 4)
    remote_htlc_signature = 3045022100a12a9a473ece548584aabdd051779025a5ed4077c4b7aa376ec7a0b1645e5a48022039490b333f53b5b3e2ddde1d809e492cba2b3e5fc3a436cd3ffb4cd3d500fa5a
    # local_signature = 3044022004ad5f04ae69c71b3b141d4db9d0d4c38d84009fb3cfeeae6efdad414487a9a0022042d3fe1388c1ff517d1da7fb4025663d372c14728ed52dc88608363450ff6a2f
    output htlc_timeout_tx 2: 02000000000101fb824d4e4dafc0f567789dee3a6bce8d411fe80f5563d8cdfdcc7d7e4447d43a0000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004830450221009ed2f0a67f99e29c3c8cf45c08207b765980697781bb727fe0b1416de0e7622902206052684229bc171419ed290f4b615c943f819c0262414e43c5b91dcf72ddcf4401473044022004ad5f04ae69c71b3b141d4db9d0d4c38d84009fb3cfeeae6efdad414487a9a0022042d3fe1388c1ff517d1da7fb4025663d372c14728ed52dc88608363450ff6a2f01008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a914b43e1b38138a41b37f7cd9a1d274bc63e3a9b5d188ac6868f6010000
    # local_signature = 304402201707050c870c1f77cc3ed58d6d71bf281de239e9eabd8ef0955bad0d7fe38dcc02204d36d80d0019b3a71e646a08fa4a5607761d341ae8be371946ebe437c289c915
    output htlc_timeout_tx 3: 02000000000101fb824d4e4dafc0f567789dee3a6bce8d411fe80f5563d8cdfdcc7d7e4447d43a010000000000000000010a060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e05004730440220155d3b90c67c33a8321996a9be5b82431b0c126613be751d400669da9d5c696702204318448bcd48824439d2c6a70be6e5747446be47ff45977cf41672bdc9b6b12d0147304402201707050c870c1f77cc3ed58d6d71bf281de239e9eabd8ef0955bad0d7fe38dcc02204d36d80d0019b3a71e646a08fa4a5607761d341ae8be371946ebe437c289c91501008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868f7010000
    # local_signature = 3045022100ff200bc934ab26ce9a559e998ceb0aee53bc40368e114ab9d3054d9960546e2802202496856ca163ac12c143110b6b3ac9d598df7254f2e17b3b94c3ab5301f4c3b0
    output htlc_success_tx 4: 02000000000101fb824d4e4dafc0f567789dee3a6bce8d411fe80f5563d8cdfdcc7d7e4447d43a020000000000000000019a090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a12a9a473ece548584aabdd051779025a5ed4077c4b7aa376ec7a0b1645e5a48022039490b333f53b5b3e2ddde1d809e492cba2b3e5fc3a436cd3ffb4cd3d500fa5a01483045022100ff200bc934ab26ce9a559e998ceb0aee53bc40368e114ab9d3054d9960546e2802202496856ca163ac12c143110b6b3ac9d598df7254f2e17b3b94c3ab5301f4c3b0012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with four outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 2195
    # base commitment transaction fee = 2344
    # actual commitment transaction fee = 7344
    # HTLC 3 offered amount 3000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6985656 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 304402205e2f76d4657fb732c0dfc820a18a7301e368f5799e06b7828007633741bda6df0220458009ae59d0c6246065c419359e05eb2a4b4ef4a1b310cc912db44eb7924298
    # local_signature = 304402203b12d44254244b8ff3bb4129b0920fd45120ab42f553d9976394b099d500c99e02205e95bb7a3164852ef0c48f9e0eaf145218f8e2c41251b231f03cbdc4f29a5429
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b000000000000220020c20b5d1f8584fd90443e7b7b720136174fa4b9333c261d04dbbd012635c0f419a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110b8976a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402203b12d44254244b8ff3bb4129b0920fd45120ab42f553d9976394b099d500c99e02205e95bb7a3164852ef0c48f9e0eaf145218f8e2c41251b231f03cbdc4f29a54290147304402205e2f76d4657fb732c0dfc820a18a7301e368f5799e06b7828007633741bda6df0220458009ae59d0c6246065c419359e05eb2a4b4ef4a1b310cc912db44eb792429801475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (HTLC 3)
    remote_htlc_signature = 3045022100a8a78fa1016a5c5c3704f2e8908715a3cef66723fb95f3132ec4d2d05cd84fb4022025ac49287b0861ec21932405f5600cbce94313dbde0e6c5d5af1b3366d8afbfc
    # signature for output 1 (HTLC 4)
    remote_htlc_signature = 3045022100e769cb156aa2f7515d126cef7a69968629620ce82afcaa9e210969de6850df4602200b16b3f3486a229a48aadde520dbee31ae340dbadaffae74fbb56681fef27b92
    # local_signature = 3045022100be6ae1977fd7b630a53623f3f25c542317ccfc2b971782802a4f1ef538eb22b402207edc4d0408f8f38fd3c7365d1cfc26511b7cd2d4fecd8b005fba3cd5bc704390
    output htlc_timeout_tx 3: 020000000001014e16c488fa158431c1a82e8f661240ec0a71ba0ce92f2721a6538c510226ad5c0000000000000000000109060000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100a8a78fa1016a5c5c3704f2e8908715a3cef66723fb95f3132ec4d2d05cd84fb4022025ac49287b0861ec21932405f5600cbce94313dbde0e6c5d5af1b3366d8afbfc01483045022100be6ae1977fd7b630a53623f3f25c542317ccfc2b971782802a4f1ef538eb22b402207edc4d0408f8f38fd3c7365d1cfc26511b7cd2d4fecd8b005fba3cd5bc70439001008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868f7010000
    # local_signature = 30440220665b9cb4a978c09d1ca8977a534999bc8a49da624d0c5439451dd69cde1a003d022070eae0620f01f3c1bd029cc1488da13fb40fdab76f396ccd335479a11c5276d8
    output htlc_success_tx 4: 020000000001014e16c488fa158431c1a82e8f661240ec0a71ba0ce92f2721a6538c510226ad5c0100000000000000000199090000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100e769cb156aa2f7515d126cef7a69968629620ce82afcaa9e210969de6850df4602200b16b3f3486a229a48aadde520dbee31ae340dbadaffae74fbb56681fef27b92014730440220665b9cb4a978c09d1ca8977a534999bc8a49da624d0c5439451dd69cde1a003d022070eae0620f01f3c1bd029cc1488da13fb40fdab76f396ccd335479a11c5276d8012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with four outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3702
    # base commitment transaction fee = 3953
    # actual commitment transaction fee = 8953
    # HTLC 3 offered amount 3000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6984047 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3045022100c1a3b0b60ca092ed5080121f26a74a20cec6bdee3f8e47bae973fcdceb3eda5502207d467a9873c939bf3aa758014ae67295fedbca52412633f7e5b2670fc7c381c1
    # local_signature = 304402200e930a43c7951162dc15a2b7344f48091c74c70f7024e7116e900d8bcfba861c022066fa6cbda3929e21daa2e7e16a4b948db7e8919ef978402360d1095ffdaff7b0
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8004b80b000000000000220020c20b5d1f8584fd90443e7b7b720136174fa4b9333c261d04dbbd012635c0f419a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de8431106f916a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402200e930a43c7951162dc15a2b7344f48091c74c70f7024e7116e900d8bcfba861c022066fa6cbda3929e21daa2e7e16a4b948db7e8919ef978402360d1095ffdaff7b001483045022100c1a3b0b60ca092ed5080121f26a74a20cec6bdee3f8e47bae973fcdceb3eda5502207d467a9873c939bf3aa758014ae67295fedbca52412633f7e5b2670fc7c381c101475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 2
    # signature for output 0 (HTLC 3)
    remote_htlc_signature = 3045022100dfb73b4fe961b31a859b2bb1f4f15cabab9265016dd0272323dc6a9e85885c54022059a7b87c02861ee70662907f25ce11597d7b68d3399443a831ae40e777b76bdb
    # signature for output 1 (HTLC 4)
    remote_htlc_signature = 3045022100ea9dc2a7c3c3640334dab733bb4e036e32a3106dc707b24227874fa4f7da746802204d672f7ac0fe765931a8df10b81e53a3242dd32bd9dc9331eb4a596da87954e9
    # local_signature = 304402202765b9c9ece4f127fa5407faf66da4c5ce2719cdbe47cd3175fc7d48b482e43d02205605125925e07bad1e41c618a4b434d72c88a164981c4b8af5eaf4ee9142ec3a
    output htlc_timeout_tx 3: 02000000000101b8de11eb51c22498fe39722c7227b6e55ff1a94146cf638458cb9bc6a060d3a30000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100dfb73b4fe961b31a859b2bb1f4f15cabab9265016dd0272323dc6a9e85885c54022059a7b87c02861ee70662907f25ce11597d7b68d3399443a831ae40e777b76bdb0147304402202765b9c9ece4f127fa5407faf66da4c5ce2719cdbe47cd3175fc7d48b482e43d02205605125925e07bad1e41c618a4b434d72c88a164981c4b8af5eaf4ee9142ec3a01008576a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c820120876475527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae67a9148a486ff2e31d6158bf39e2608864d63fefd09d5b88ac6868f7010000
    # local_signature = 30440220048a41c660c4841693de037d00a407810389f4574b3286afb7bc392a438fa3f802200401d71fa87c64fe621b49ac07e3bf85157ac680acb977124da28652cc7f1a5c
    output htlc_success_tx 4: 02000000000101b8de11eb51c22498fe39722c7227b6e55ff1a94146cf638458cb9bc6a060d3a30100000000000000000176050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100ea9dc2a7c3c3640334dab733bb4e036e32a3106dc707b24227874fa4f7da746802204d672f7ac0fe765931a8df10b81e53a3242dd32bd9dc9331eb4a596da87954e9014730440220048a41c660c4841693de037d00a407810389f4574b3286afb7bc392a438fa3f802200401d71fa87c64fe621b49ac07e3bf85157ac680acb977124da28652cc7f1a5c012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with three outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 3703
    # base commitment transaction fee = 3317
    # actual commitment transaction fee = 11317
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6984683 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 30450221008b7c191dd46893b67b628e618d2dc8e81169d38bade310181ab77d7c94c6675e02203b4dd131fd7c9deb299560983dcdc485545c98f989f7ae8180c28289f9e6bdb0
    # local_signature = 3044022047305531dd44391dce03ae20f8735005c615eb077a974edb0059ea1a311857d602202e0ed6972fbdd1e8cb542b06e0929bc41b2ddf236e04cb75edd56151f4197506
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110eb936a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400473044022047305531dd44391dce03ae20f8735005c615eb077a974edb0059ea1a311857d602202e0ed6972fbdd1e8cb542b06e0929bc41b2ddf236e04cb75edd56151f4197506014830450221008b7c191dd46893b67b628e618d2dc8e81169d38bade310181ab77d7c94c6675e02203b4dd131fd7c9deb299560983dcdc485545c98f989f7ae8180c28289f9e6bdb001475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (HTLC 4)
    remote_htlc_signature = 3044022044f65cf833afdcb9d18795ca93f7230005777662539815b8a601eeb3e57129a902206a4bf3e53392affbba52640627defa8dc8af61c958c9e827b2798ab45828abdd
    # local_signature = 3045022100b94d931a811b32eeb885c28ddcf999ae1981893b21dd1329929543fe87ce793002206370107fdd151c5f2384f9ceb71b3107c69c74c8ed5a28a94a4ab2d27d3b0724
    output htlc_success_tx 4: 020000000001011c076aa7fb3d7460d10df69432c904227ea84bbf3134d4ceee5fb0f135ef206d0000000000000000000175050000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500473044022044f65cf833afdcb9d18795ca93f7230005777662539815b8a601eeb3e57129a902206a4bf3e53392affbba52640627defa8dc8af61c958c9e827b2798ab45828abdd01483045022100b94d931a811b32eeb885c28ddcf999ae1981893b21dd1329929543fe87ce793002206370107fdd151c5f2384f9ceb71b3107c69c74c8ed5a28a94a4ab2d27d3b0724012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with three outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 4914
    # base commitment transaction fee = 4402
    # actual commitment transaction fee = 12402
    # HTLC 4 received amount 4000 wscript 76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac6868
    # to_local amount 6983598 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 304402206d6cb93969d39177a09d5d45b583f34966195b77c7e585cf47ac5cce0c90cefb022031d71ae4e33a4e80df7f981d696fbdee517337806a3c7138b7491e2cbb077a0e
    # local_signature = 304402206a2679efa3c7aaffd2a447fd0df7aba8792858b589750f6a1203f9259173198a022008d52a0e77a99ab533c36206cb15ad7aeb2aa72b93d4b571e728cb5ec2f6fe26
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8003a00f0000000000002200208c48d15160397c9731df9bc3b236656efb6665fbfe92b4a6878e88a499f741c4c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110ae8f6a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e040047304402206a2679efa3c7aaffd2a447fd0df7aba8792858b589750f6a1203f9259173198a022008d52a0e77a99ab533c36206cb15ad7aeb2aa72b93d4b571e728cb5ec2f6fe260147304402206d6cb93969d39177a09d5d45b583f34966195b77c7e585cf47ac5cce0c90cefb022031d71ae4e33a4e80df7f981d696fbdee517337806a3c7138b7491e2cbb077a0e01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 1
    # signature for output 0 (HTLC 4)
    remote_htlc_signature = 3045022100fcb38506bfa11c02874092a843d0cc0a8613c23b639832564a5f69020cb0f6ba02206508b9e91eaa001425c190c68ee5f887e1ad5b1b314002e74db9dbd9e42dbecf
    # local_signature = 304502210086e76b460ddd3cea10525fba298405d3fe11383e56966a5091811368362f689a02200f72ee75657915e0ede89c28709acd113ede9e1b7be520e3bc5cda425ecd6e68
    output htlc_success_tx 4: 0200000000010110a3fdcbcd5db477cd3ad465e7f501ffa8c437e8301f00a6061138590add757f0000000000000000000122020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0500483045022100fcb38506bfa11c02874092a843d0cc0a8613c23b639832564a5f69020cb0f6ba02206508b9e91eaa001425c190c68ee5f887e1ad5b1b314002e74db9dbd9e42dbecf0148304502210086e76b460ddd3cea10525fba298405d3fe11383e56966a5091811368362f689a02200f72ee75657915e0ede89c28709acd113ede9e1b7be520e3bc5cda425ecd6e68012004040404040404040404040404040404040404040404040404040404040404048a76a91414011f7254d96b819c76986c277d115efce6f7b58763ac67210394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b7c8201208763a91418bc1a114ccf9c052d3d23e28d3b0a9d1227434288527c21030d417a46946384f88d5f3337267c5e579765875dc4daca813e21734b140639e752ae677502f801b175ac686800000000

    name: commitment tx with two outputs untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 4915
    # base commitment transaction fee = 3558
    # actual commitment transaction fee = 15558
    # to_local amount 6984442 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 304402200769ba89c7330dfa4feba447b6e322305f12ac7dac70ec6ba997ed7c1b598d0802204fe8d337e7fee781f9b7b1a06e580b22f4f79d740059560191d7db53f8765552
    # local_signature = 3045022100a012691ba6cea2f73fa8bac37750477e66363c6d28813b0bb6da77c8eb3fb0270220365e99c51304b0b1a6ab9ea1c8500db186693e39ec1ad5743ee231b0138384b9
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8002c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de843110fa926a00000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80e0400483045022100a012691ba6cea2f73fa8bac37750477e66363c6d28813b0bb6da77c8eb3fb0270220365e99c51304b0b1a6ab9ea1c8500db186693e39ec1ad5743ee231b0138384b90147304402200769ba89c7330dfa4feba447b6e322305f12ac7dac70ec6ba997ed7c1b598d0802204fe8d337e7fee781f9b7b1a06e580b22f4f79d740059560191d7db53f876555201475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

    name: commitment tx with two outputs untrimmed (maximum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651180
    # base commitment transaction fee = 6987454
    # actual commitment transaction fee = 6999454
    # to_local amount 546 wscript 63210212a140cd0c6539d07cd08dfe09984dec3251ea808b892efeac3ede9402bf2b1967029000b2752103fd5960528dc152014952efdb702a88f71e3c1653b2314431701ec77e57fde83c68ac
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022037f83ff00c8e5fb18ae1f918ffc24e54581775a20ff1ae719297ef066c71caa9022039c529cccd89ff6c5ed1db799614533844bd6d101da503761c45c713996e3bbd
    # local_signature = 30440220514f977bf7edc442de8ce43ace9686e5ebdc0f893033f13e40fb46c8b8c6e1f90220188006227d175f5c35da0b092c57bea82537aed89f7778204dc5bacf4f29f2b9
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b800222020000000000002200204adb4e2f00643db396dd120d4e7dc17625f5f2c11a40d857accc862d6b7dd80ec0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de84311004004730440220514f977bf7edc442de8ce43ace9686e5ebdc0f893033f13e40fb46c8b8c6e1f90220188006227d175f5c35da0b092c57bea82537aed89f7778204dc5bacf4f29f2b901473044022037f83ff00c8e5fb18ae1f918ffc24e54581775a20ff1ae719297ef066c71caa9022039c529cccd89ff6c5ed1db799614533844bd6d101da503761c45c713996e3bbd01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

    name: commitment tx with one output untrimmed (minimum feerate)
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651181
    # base commitment transaction fee = 6987455
    # actual commitment transaction fee = 7000000
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022064901950be922e62cbe3f2ab93de2b99f37cff9fc473e73e394b27f88ef0731d02206d1dfa227527b4df44a07599289e207d6fd9cca60c0365682dcd3deaf739567e
    # local_signature = 3044022031a82b51bd014915fe68928d1abf4b9885353fb896cac10c3fdd88d7f9c7f2e00220716bda819641d2c63e65d3549b6120112e1aeaf1742eed94a471488e79e206b1
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8001c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de8431100400473044022031a82b51bd014915fe68928d1abf4b9885353fb896cac10c3fdd88d7f9c7f2e00220716bda819641d2c63e65d3549b6120112e1aeaf1742eed94a471488e79e206b101473044022064901950be922e62cbe3f2ab93de2b99f37cff9fc473e73e394b27f88ef0731d02206d1dfa227527b4df44a07599289e207d6fd9cca60c0365682dcd3deaf739567e01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

    name: commitment tx with fee greater than funder amount
    to_local_msat: 6988000000
    to_remote_msat: 3000000000
    local_feerate_per_kw: 9651936
    # base commitment transaction fee = 6988001
    # actual commitment transaction fee = 7000000
    # to_remote amount 3000000 P2WPKH(0394854aa6eab5b2a8122cc726e9dded053a2184d88256816826d6231c068d4a5b)
    remote_signature = 3044022064901950be922e62cbe3f2ab93de2b99f37cff9fc473e73e394b27f88ef0731d02206d1dfa227527b4df44a07599289e207d6fd9cca60c0365682dcd3deaf739567e
    # local_signature = 3044022031a82b51bd014915fe68928d1abf4b9885353fb896cac10c3fdd88d7f9c7f2e00220716bda819641d2c63e65d3549b6120112e1aeaf1742eed94a471488e79e206b1
    output commit_tx: 02000000000101bef67e4e2fb9ddeeb3461973cd4c62abb35050b1add772995b820b584a488489000000000038b02b8001c0c62d0000000000160014ccf1af2f2aabee14bb40fa3851ab2301de8431100400473044022031a82b51bd014915fe68928d1abf4b9885353fb896cac10c3fdd88d7f9c7f2e00220716bda819641d2c63e65d3549b6120112e1aeaf1742eed94a471488e79e206b101473044022064901950be922e62cbe3f2ab93de2b99f37cff9fc473e73e394b27f88ef0731d02206d1dfa227527b4df44a07599289e207d6fd9cca60c0365682dcd3deaf739567e01475221023da092f6980e58d2c037173180e9a465476026ee50f96695963e8efe436f54eb21030e9f7b623d2ccc7c9bd44d66d5ce21ce504c0acf6385a132cec6d3c39fa711c152ae3e195220
    num_htlcs: 0

# Appendix D: Per-commitment Secret Generation Test Vectors

These test the generation algorithm that all nodes use.

## Generation Tests

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

## Storage Tests

These test the optional compact storage system. In many cases, an
incorrect entry cannot be determined until its parent is revealed: an entry is
specifically corrupted, along with all its children.

For
these tests a seed of `0xFFF...FF` is used, and incorrect entries are
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

These test the derivation for `localpubkey`, `remotepubkey`, `local_htlcpubkey`, `remote_htlcpubkey`, `local_delayedpubkey`, and
`remote_delayedpubkey` (which use the same formula), as well as the `revocationpubkey`.

All of them use the following secrets (and thus the derived points):

    base_secret: 0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
    per_commitment_secret: 0x1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a09080706050403020100
    base_point: 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2
    per_commitment_point: 0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486

    name: derivation of pubkey from basepoint and per_commitment_point
    # SHA256(per_commitment_point || basepoint)
    # => SHA256(0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486 || 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0xcbcdd70fcfad15ea8e9e5c5a12365cf00912504f08ce01593689dd426bca9ff0
    # + basepoint (0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0x0235f2dbfaa89b57ec7b055afe29849ef7ddfeb1cefdb9ebdc43f5494984db29e5
    localpubkey: 0x0235f2dbfaa89b57ec7b055afe29849ef7ddfeb1cefdb9ebdc43f5494984db29e5

    name: derivation of private key from basepoint secret and per_commitment_secret
	# SHA256(per_commitment_point || basepoint)
    # => SHA256(0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486 || 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0xcbcdd70fcfad15ea8e9e5c5a12365cf00912504f08ce01593689dd426bca9ff0
    # + basepoint_secret (0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f)
    # = 0xcbced912d3b21bf196a766651e436aff192362621ce317704ea2f75d87e7be0f
    localprivkey: 0xcbced912d3b21bf196a766651e436aff192362621ce317704ea2f75d87e7be0f

    name: derivation of revocation pubkey from basepoint and per_commitment_point
    # SHA256(revocation_basepoint || per_commitment_point)
    # => SHA256(0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2 || 0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486)
    # = 0xefbf7ba5a074276701798376950a64a90f698997cce0dff4d24a6d2785d20963
    # x revocation_basepoint = 0x02c00c4aadc536290422a807250824a8d87f19d18da9d610d45621df22510db8ce
    # SHA256(per_commitment_point || revocation_basepoint)
    # => SHA256(0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486 || 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0xcbcdd70fcfad15ea8e9e5c5a12365cf00912504f08ce01593689dd426bca9ff0
    # x per_commitment_point = 0x0325ee7d3323ce52c4b33d4e0a73ab637711057dd8866e3b51202a04112f054c43
    # 0x02c00c4aadc536290422a807250824a8d87f19d18da9d610d45621df22510db8ce + 0x0325ee7d3323ce52c4b33d4e0a73ab637711057dd8866e3b51202a04112f054c43 => 0x02916e326636d19c33f13e8c0c3a03dd157f332f3e99c317c141dd865eb01f8ff0
    revocationpubkey: 0x02916e326636d19c33f13e8c0c3a03dd157f332f3e99c317c141dd865eb01f8ff0

    name: derivation of revocation secret from basepoint_secret and per_commitment_secret
    # SHA256(revocation_basepoint || per_commitment_point)
    # => SHA256(0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2 || 0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486)
    # = 0xefbf7ba5a074276701798376950a64a90f698997cce0dff4d24a6d2785d20963
    # * revocation_basepoint_secret (0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f)# = 0x44bfd55f845f885b8e60b2dca4b30272d5343be048d79ce87879d9863dedc842
    # SHA256(per_commitment_point || revocation_basepoint)
    # => SHA256(0x025f7117a78150fe2ef97db7cfc83bd57b2e2c0d0dd25eaf467a4a1c2a45ce1486 || 0x036d6caac248af96f6afa7f904f550253a0f3ef3f5aa2fe6838a95b216691468e2)
    # = 0xcbcdd70fcfad15ea8e9e5c5a12365cf00912504f08ce01593689dd426bca9ff0
    # * per_commitment_secret (0x1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a09080706050403020100)# = 0x8be02a96a97b9a3c1c9f59ebb718401128b72ec009d85ee1656319b52319b8ce
    # => 0xd09ffff62ddb2297ab000cc85bcb4283fdeb6aa052affbc9dddcf33b61078110
    revocationprivkey: 0xd09ffff62ddb2297ab000cc85bcb4283fdeb6aa052affbc9dddcf33b61078110

# Appendix F: Dual Funded Transaction Test Vectors

## Funding Transaction Construction
### Preliminaries:

```
Genesis block 0:
0100000000000000000000000000000000000000000000000000000000000000000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4adae5494dffff7f20020000000101000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4d04ffff001d0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e206272696e6b206f66207365636f6e64206261696c6f757420666f722062616e6b73ffffffff0100f2052a01000000434104678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5fac00000000

Block 1:0000002006226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910ff86fd1d0db3ac5a72df968622f31e6b5e6566a09e29206d7c7a55df90e181de8be86815cffff7f200000000001020000000001010000000000000000000000000000000000000000000000000000000000000000ffffffff03510101ffffffff0200f2052a0100000017a914113ca7e584fe1575b6fc39abae991529f66eda58870000000000000000266a24aa21a9ede2f61c3f71d1defd3fa999dfa36953755c690689799962b48bebd836974e8cf90120000000000000000000000000000000000000000000000000000000000000000000000000
Coinbase address pubkey: 2MtpN8zCxTp8AWSg7VBjBX7vU6x73bVCKP8
Coinbase address privkey: cPxFtfE1w3ptFnsZvvFeWji21kTArYa9GXwMkYsoQHdaJKrjUTek

Parent transaction (spends coinbase of block 1):
02000000000101f86fd1d0db3ac5a72df968622f31e6b5e6566a09e29206d7c7a55df90e181de800000000171600141fb9623ffd0d422eacc450fd1e967efc477b83ccffffffff0580b2e60e00000000220020fd89acf65485df89797d9ba7ba7a33624ac4452f00db08107f34257d33e5b94680b2e60e0000000017a9146a235d064786b49e7043e4a042d4cc429f7eb6948780b2e60e00000000160014fbb4db9d85fba5e301f4399e3038928e44e37d3280b2e60e0000000017a9147ecd1b519326bc13b0ec716e469b58ed02b112a087f0006bee0000000017a914f856a70093da3a5b5c4302ade033d4c2171705d387024730440220696f6cee2929f1feb3fd6adf024ca0f9aa2f4920ed6d35fb9ec5b78c8408475302201641afae11242160101c6f9932aeb4fcd1f13a9c6df5d1386def000ea259a35001210381d7d5b1bc0d7600565d827242576d9cb793bfe0754334af82289ee8b65d137600000000
```

### Funding transaction (spends parent's outputs):

Inputs:
```
4303ca8ff10c6c345b9299672a66f111c5b81ae027cc5b0d4d39d09c66b032b9 0
	witness_data:
	  preimage: 20 68656c6c6f2074686572652c2074686973206973206120626974636f6e212121
	  witness_script: 27 82012088a820add57dfe5277079d069ca4ad4893c96de91f88ffb981fdc6a2a34d5336c66aff87
	scriptPubKey: 0020fd89acf65485df89797d9ba7ba7a33624ac4452f00db08107f34257d33e5b946
	address: bcrt1qlky6eaj5sh0cj7tanwnm573nvf9vg3f0qrdssyrlxsjh6vl9h9rql40v2g

4303ca8ff10c6c345b9299672a66f111c5b81ae027cc5b0d4d39d09c66b032b9 1
	redeemScript: 0020fd89acf65485df89797d9ba7ba7a33624ac4452f00db08107f34257d33e5b946
	witness_data:
	  preimage: 20 68656c6c6f2074686572652c2074686973206973206120626974636f6e212121
	  witness_script: 27 82012088a820add57dfe5277079d069ca4ad4893c96de91f88ffb981fdc6a2a34d5336c66aff87
	scriptPubKey: a9146a235d064786b49e7043e4a042d4cc429f7eb69487
	address: 2N2vRyi3cm5VYpw218MJJrJWK1Jd4qbaefW

4303ca8ff10c6c345b9299672a66f111c5b81ae027cc5b0d4d39d09c66b032b9 2
	pubkey: 034695f5b7864c580bf11f9f8cb1a94eb336f2ce9ef872d2ae1a90ee276c772484
	privkey: cUM8Dr33wK4uFmw3Tz8sbQ7BiBNgX5BthRurU7RkgXVvNUPcWrJf
	witness_program: fbb4db9d85fba5e301f4399e3038928e44e37d32
	scriptPubKey: 0014fbb4db9d85fba5e301f4399e3038928e44e37d32
	address: bcrt1qlw6dh8v9lwj7xq058x0rqwyj3ezwxlfjxsy7er

4303ca8ff10c6c345b9299672a66f111c5b81ae027cc5b0d4d39d09c66b032b9 3
	pubkey: 034695f5b7864c580bf11f9f8cb1a94eb336f2ce9ef872d2ae1a90ee276c772484
	privkey: cUM8Dr33wK4uFmw3Tz8sbQ7BiBNgX5BthRurU7RkgXVvNUPcWrJf
	redeemScript: 0014fbb4db9d85fba5e301f4399e3038928e44e37d32
	witness_program: fbb4db9d85fba5e301f4399e3038928e44e37d32
	scriptPubKey: a9147ecd1b519326bc13b0ec716e469b58ed02b112a087
	address: 2N4ogqX3kaLTT2jjxi18nAiyWdwKtE5PxLF
```

Expected Opener's `funding_compose.input_info` (inputs 0+1 above):
```
  num_inputs: 2
  input_info:[
    {
      satoshis: 250000000,
      prev_txid: 4303ca8ff10c6c345b9299672a66f111c5b81ae027cc5b0d4d39d09c66b032b9,
      prev_vout: 0,
      prev_scriptpubkey_len: 34,
      prev_scriptpubkey: 0020fd89acf65485df89797d9ba7ba7a33624ac4452f00db08107f34257d33e5b946,
      max_witness_len: 75,
      scriptlen: 0,
      script: null
    },{
      satoshis: 250000000,
      prev_txid: 4303ca8ff10c6c345b9299672a66f111c5b81ae027cc5b0d4d39d09c66b032b9,
      prev_vout: 1,
      prev_scriptpubkey_len: 23,
      prev_scriptpubkey: a9146a235d064786b49e7043e4a042d4cc429f7eb69487,
      max_witness_len: 75,
      scriptlen: 34,
      script: 0020fd89acf65485df89797d9ba7ba7a33624ac4452f00db08107f34257d33e5b946
    }
  ]
```

Expected Accepter's `funding_compose.input_info` (inputs 2+3 above):
```
  num_inputs: 2
  input_info:[
    {
      satoshis: 250000000,
      prev_txid: 4303ca8ff10c6c345b9299672a66f111c5b81ae027cc5b0d4d39d09c66b032b9,
      prev_vout: 2,
      prev_scriptpubkey_len: 22,
      prev_scriptpubkey: 0014fbb4db9d85fba5e301f4399e3038928e44e37d32,
      max_witness_len: 109,
      scriptlen: 0,
      script: null
    },{
      satoshis: 250000000,
      prev_txid: 4303ca8ff10c6c345b9299672a66f111c5b81ae027cc5b0d4d39d09c66b032b9,
      prev_vout: 3,
      prev_scriptpubkey_len: 23,
      prev_scriptpubkey: a9147ecd1b519326bc13b0ec716e469b58ed02b112a087,
      max_witness_len: 109,
      scriptlen: 22,
      script: 0014fbb4db9d85fba5e301f4399e3038928e44e37d32
    }
  ]
```

Outputs: (scriptPubKeys)
```
# opener's change address
pubkey: 0206e626a4c6d4392d4030bc78bd93f728d1ba61214a77c63adc17d71e32ded3df
# privkey: cSpC1KYEV1vsUFBwTdcuRkncbwfipY1m5zuQ9CjgAYwiVvbQ4fc1
scriptPubKey: 00141ca1cca8855bad6bc1ea5436edd8cff10b7e448b
address: bcrt1qrjsue2y9twkkhs022smwmkx07y9hu3ytshgjmj

# accepter's change address
pubkey: 028f3978c211f4c0bf4d20674f345ae14e08871b25b2c957b4bdbd42e9726278fc
privkey: cQ1HXnbAE4wGhuB2b9rJEydV5ayeEmMqxf1dvHPZmyMTPkwvZJyg
scriptPubKey: 001444cb0c39f93ecc372b5851725bd29d865d333b10
address: bcrt1qgn9scw0e8mxrw26c29e9h55asewnxwcsdxdp50

# the 2-of-2s
pubkey1: 0292edb5f7bbf9e900f7e024be1c1339c6d149c11930e613af3a983d2565f4e41e
pubkey2: 02e16172a41e928cbd78f761bd1c657c4afc7495a1244f7f30166b654fbf7661e3
script_def: multi(2,0292edb5f7bbf9e900f7e024be1c1339c6d149c11930e613af3a983d2565f4e41e,02e16172a41e928cbd78f761bd1c657c4afc7495a1244f7f30166b654fbf7661e3)
script: 52210292edb5f7bbf9e900f7e024be1c1339c6d149c11930e613af3a983d2565f4e41e2102e16172a41e928cbd78f761bd1c657c4afc7495a1244f7f30166b654fbf7661e352ae
scriptPubKey: 0020297b92c238163e820b82486084634b4846b86a3c658d87b9384192e6bea98ec5
address: bcrt1q99ae9s3czclgyzuzfpsggc6tfprts63uvkxc0wfcgxfwd04f3mzs3asq6l
```

Unsigned Funding Transaction:
```
0200000004b932b0669cd0394d0d5bcc27e01ab8c511f1662a6799925b346c0cf18fca03430000000000ffffffffb932b0669cd0394d0d5bcc27e01ab8c511f1662a6799925b346c0cf18fca03430100000000ffffffffb932b0669cd0394d0d5bcc27e01ab8c511f1662a6799925b346c0cf18fca03430200000000ffffffffb932b0669cd0394d0d5bcc27e01ab8c511f1662a6799925b346c0cf18fca03430300000000ffffffff03ea7f0100000000001600141ca1cca8855bad6bc1ea5436edd8cff10b7e448b00c2eb0b0000000016001444cb0c39f93ecc372b5851725bd29d865d333b106081ad2f00000000220020297b92c238163e820b82486084634b4846b86a3c658d87b9384192e6bea98ec500000000
```

Signed Funding Transaction:
```
02000000000104b932b0669cd0394d0d5bcc27e01ab8c511f1662a6799925b346c0cf18fca03430000000000ffffffffb932b0669cd0394d0d5bcc27e01ab8c511f1662a6799925b346c0cf18fca03430100000023220020fd89acf65485df89797d9ba7ba7a33624ac4452f00db08107f34257d33e5b946ffffffffb932b0669cd0394d0d5bcc27e01ab8c511f1662a6799925b346c0cf18fca03430200000000ffffffffb932b0669cd0394d0d5bcc27e01ab8c511f1662a6799925b346c0cf18fca03430300000017160014fbb4db9d85fba5e301f4399e3038928e44e37d32ffffffff03ea7f0100000000001600141ca1cca8855bad6bc1ea5436edd8cff10b7e448b00c2eb0b0000000016001444cb0c39f93ecc372b5851725bd29d865d333b106081ad2f00000000220020297b92c238163e820b82486084634b4846b86a3c658d87b9384192e6bea98ec5022068656c6c6f2074686572652c2074686973206973206120626974636f6e2121212782012088a820add57dfe5277079d069ca4ad4893c96de91f88ffb981fdc6a2a34d5336c66aff87022068656c6c6f2074686572652c2074686973206973206120626974636f6e2121212782012088a820add57dfe5277079d069ca4ad4893c96de91f88ffb981fdc6a2a34d5336c66aff870247304402204bd649762ff5620cd67b5b90a382dd528ae1e35063f3fdabc6f035df04bb17a502200afb3369cdf014615261e2ce2226b851809b19e678847c9780c7f25f151209cf0121034695f5b7864c580bf11f9f8cb1a94eb336f2ce9ef872d2ae1a90ee276c7724840247304402207c7e66be6518d5ad6b7f314fd392cfb7a3d980d9270cc3c0ec10e9fd752f20280220687233cbec066b71fa96434197e88e04dde2ccfd1b17c78e4d50e4bbcf6df1860121034695f5b7864c580bf11f9f8cb1a94eb336f2ce9ef872d2ae1a90ee276c77248400000000
```

Weight Count:
```
  Max Witness Len: 368\* + 2 Segwit bytes (flag + marker)
  Non-Witness Data Byte Count: 337
  Total Weight: 370 + 337 * 4 = 1718
```
\* The signatures calculated for this transaction come to 71-bytes.


## Fee Calculation
Assuming a total of 10 Bitcoin inputs, 5btc from each peer.

Opener's `funding_satoshi` is `499900000` (4.999btc), with a single
change output provided.
Accepter `funding_satoshi` is `300000000` (3btc), with `200000000` (2btc)
to their change address.

Output1 is Opener's change address output.
Output2 is the Accepter's output.
Output3 is the Channel Funding output.

All fractional fees are rounded down.

### Example A: Positive Change Value
With `feerate_per_kw_funding` communicated at `1000 sats/kw`:

```
  Fee:      0.00001716 btc
  Output1:  0.00098284 btc
  Output2:  2.0        btc
  Output3:  7.999      btc

  Opener (A) Starting Balance:   4.999 btc
  Accepter (B) Starting Balance: 3     btc
```

### Example B: Negative Change on Round 1, Negative Change on Round 2
With `feerate_per_kw_funding` communicated at `100k sats/kw`:

Round1:
```
  Fee:      0.00171600 btc
  Output1: -0.00071600 btc
  Output2:  2.0        btc
  Output3:  7.999      btc
```

Round2, Re-calculate transaction, with Output1 removed:

```
  Max Witness Len: 368
  Non-Witness Data Byte Count: 306
  Total Weight: 1592
```

```
  Fee: 	    0.00159200 btc
  Output2:  2.0        btc
  Output3:  7.99840800 btc

  Opener (A) Starting Balance:   4.99850800 btc
  Accepter (B) Starting Balance: 3          btc
```

### Example C: Negative Change on Round 1, Positive Change on Round 2
With `feerate_per_kw_funding` communicated at `60k sats/kw`:

Round1:
```
  Fee:      0.00102960 btc
  Output1: -0.00002960 btc
  Output2:  2.0        btc
  Output3:  7.999      btc
```

Round2:
```
  Max Witness Len: 368
  Non-Witness Data Byte Count: 306
  Total Weight: 1592
```

```
  Fee: 	    0.00095520 btc
  Output2:  2.0        btc
  Output3:  7.99904480 btc

  Opener (A) Starting Balance:   4.99904480 btc
  Accepter (B) Starting Balance: 3          btc
```


# References

# Authors

[ FIXME: ]

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).

