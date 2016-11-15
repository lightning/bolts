# BOLT #3: Bitcoin Transaction and Script Formats

This details the exact format of on-chain transactions, which both sides need to agree on to ensure signatures are valid.  That is, the funding transaction output script, commitment transactions and the HTLC transactions.

## Transaction input and output ordering

Lexicographic ordering as per BIP 69.

## Funding Transaction Output

* The funding output script is a pay-to-witness-script-hash [FIXME: reference BIP] to:
   * 0 2 <key1> <key2> 2 OP_CHECKMULTISIG
* Where <key1> is the numerically lesser of the two DER-encoded `funding-pubkey` and <key2> is the greater.

## Commitment Transaction
* version: 2
* locktime: lower 24 bits are the commitment transaction number.
* txin count: 1
   * txin[0] outpoint: `txid` and `output_index` from `funding_created` message
   * txin[0] sequence: lower 24 bits are upper 24 bits of commitment transaction number.
   * txin[0] script bytes: 0
   * txin[0] witness: `<signature-for-key1>` `<signature-for-key-2>`

### Commitment Transaction Outputs

The amounts for each output are rounded down to whole satoshis.  If this amount is less than the `dust-limit-satoshis` set by the owner of the commitment transaction, the output is not produced (thus the funds add to fees).

To allow an opportunity for penalty transactions in case of a revoked commitment transaction, all outputs which return funds to the owner of the commitment transaction (aka "local node") must be delayed for `to-self-delay` blocks.  This delay is done in a second stage HTLC transaction.

The reason for the separate transaction stage for HTLC outputs is so that HTLCs can time out or be fulfilled even though they are within the `to-self-delay` `OP_CHECKSEQUENCEVERIFY` delay.  Otherwise the required minimum timeout on HTLCs is lengthened by this delay, causing longer timeouts for HTLCs traversing the network.

#### To-Local Output

This output sends funds back to the owner of this commitment transaction (ie. `<localkey>`), thus must be timelocked using OP_CSV.  The output is a version 0 P2WSH, with a witness script:

	to-self-delay OP_CHECKSEQUENCEVERIFY OP_DROP <localkey> OP_CHECKSIG

It is spent by a transaction with nSequence field set to `to-self-delay` (which can only be valid after that duration has passed), and witness script `<localsig>`.

#### To-Remote Output

This output sends funds to the other peer, thus is a simple P2PKH to `<remotekey>`.

#### Offered HTLC Outputs

This output sends funds to a HTLC-timeout transaction after the HTLC timeout, or to the remote peer on successful payment preimage.  The output is a P2WSH, with a witness script:

    <remotekey> OP_SWAP
        OP_SIZE 32 OP_EQUAL
    OP_NOTIF
        # To me via HTLC-timeout tx (timelocked).
        OP_DROP 2 OP_SWAP <localkey> 2 OP_CHECKMULTISIGVERIFY
    OP_ELSE
        # To you with preimage.
        OP_HASH160 <ripemd-of-payment-hash> OP_EQUALVERIFY
        OP_CHECKSIGVERIFY
    OP_ENDIF

The remote node can redeem the HTLC with the scriptsig:

    <remotesig> <payment-preimage>

Either node can use the HTLC-timeout transaction to time out the HTLC once the HTLC is expired, as show below.


#### Received HTLC Outputs

This output sends funds to the remote peer after the HTLC timeout, or to an HTLC-success transaction with a successful payment preimage. The output is a P2WSH, with a witness script:

    <remotekey> OP_SWAP
        OP_SIZE 32 OP_EQUAL
    OP_IF
        # To me via HTLC-success tx.
        OP_HASH160 <ripemd-of-payment-hash> OP_EQUALVERIFY
        2 OP_SWAP <localkey> 2 OP_CHECKMULTISIGVERIFY
    OP_ELSE
        # To you after timeout.
        OP_DROP <locktime> OP_CHECKLOCKTIMEVERIFY OP_DROP
        OP_CHECKSIGVERIFY
    OP_ENDIF

To timeout the htlc, the local node spends it with the scriptsig:

    <remotesig> 0

To redeem the HTLC, the HTLC-success  transaction is used as detailed below.

## HTLC-Timeout and HTLC-Success Transaction
These HTLC transactions are almost identical, except the HTLC-Timeout transaction is timelocked.  This is also the transaction which can be spent by a valid penalty transaction.

* version: 2
* txin: the commitment transaction HTLC output.
* locktime: 0 for HTLC-Success, `htlc-timeout` for HTLC-Timeout.
* txin count: 1
   * txin[0] outpoint: `txid` of the commitment transaction and `output_index` of the matching HTLC output for the HTLC transaction.
   * txin[0] sequence: 0
   * txin[0] script bytes: 0
   * txin[0] witness stack: `<localsig> <remotesig> 0` (HTLC-Timeout) or `<localsig> <remotesig> <payment-preimage>` (HTLC-success).
* txout count: 1
   * txout[0] amount: the HTLC amount minus fees (see below)
   * txout[0] script: version 0 P2WSH with witness script as below.

The witness script for the output is:

    OP_IF
        # Penalty transaction
        <revocation pubkey>
    OP_ELSE
        `to-self-delay`
        OP_CSV
        OP_DROP
        <localkey>
    OP_ENDIF
    OP_CHECKSIG

To spend this via penalty, the remote node uses a witness stack `<revocationsig> 1` and to collect the output the local node uses an input with nSequence `to-self-delay` and a witness stack `<localsig> 0`

# Key Derivation

Each commitment transaction uses a unique set of keys; <localkey>, <remotekey> and <revocationkey>.  Changing the <localkey> and <remotekey> every time ensures that commitment txids cannot be determined by a third party even it knows another commitment transaction, which helps preserve privacy in the case of outsourced penalties.  The <revocationkey> is generated such that the remote node is the only one in possession of the secret key once the commitment transaction has been revoked.

For efficiency, keys are generated from a series of per-commitment secrets which are generated from a single seed, allowing the receiver to compactly store them (see [FIXME]).

### localkey and remotekey Derivation

The localkey for a commitment transaction is generated by EC addition of the local `refund base point` and the current local `key-offset` multiplied by G (eg. secp256k1_ec_pubkey_tweak_add() from libsecp256k1).  The local node knows the secret key corresponding to `refund base point` so can similarly derive the secret key for `localkey`.

The `key-offset` is generated using HMAC(`per-commit-secret`, “R”) [FIXME: more detail!].

The remotekey is generated the same way, using the remote `refund base point` and the current `key-offset` from the remote node: this is given by `first-key-offset` (for the initial commitment transaction) and `next-key-offset` for successive transactions.

### revocationkey Derivation

The local revocation key is derived from both the remote `HAKD basepoint` and a key derived from the local per-commit secret, called the “revocation-halfkey”.

The secret key for the `revocation-halfkey` is HMAC(`per-commit-secret`, “T”) [FIXME: more detail!].  The public key corresponding to this secret key is `revocation-halfkey`.  Elliptic curve point addition of `revocation-halfkey` and `HAKD basepoint` gives the `revocationkey`.

Upon revocation, the per-commit secret is revealed to the remote node: this allows it to derive the secret key for `revocation-halfkey`, and it already knows the secret key corresponding to the `HAKD basepoint` so it can derive the secret key corresponding to `revocationkey`.


### Per-commitment Secret Requirements

A node MUST select an unguessable 256-bit seed for each connection,
and MUST NOT reveal the seed.  Up to 2^48-1 per-commitment secrets can be
generated; the first secret used MUST be index 281474976710655, and
then the index decremented.

The psecret P for index N MUST match the output of this algorithm:

    generate_from_seed(seed, N):
        P = seed
        for B in 0 to 47:
            if B set in N:
                flip(B) in P
                P = SHA256(P)
        return P

Where "flip(B)" alternates the B'th least significant bit in the value P.

The receiving node MAY store all previous R values, or MAY calculate
it from a compact representation as described in [FIXME].

# References

# Authors

FIXME




