# BOLT #13: Deputy Payment Processing

Some use cases require a third party (e.g. an offline point of sale) to issue valid invoices and verify whether they have been paid. This BOLT defines how such invoices can be generated and paid using `deputy payment processing`.

`deputy payment processing` relies on a deterministic preimage generation process. This allows a point of sale to generate valid invoices and validate whether they have been paid without the necessity of communicating with the recipient node at any time of the payment process.

## Requirements

The point of sale supporting `deputy payment processing`
* MUST issue a valid invoice corresponding to BOLT-11
* if it requires `deputy payment processing`:
    * MUST set the feature bit `22` in the invoice.
* otherwise:
    * MUST set the feature bit `23` in the invoice.
* MUST set a non-existing node ("deputy node") as a recipient node.
* MUST add the recipient node as last routing hint.
* MUST deterministically generate the preimage based on
  * a random nonce of 32 bytes ("preimage nonce").
  * the requested amount corresponding tho the `amount` field of the invoice.
* MUST ensure that no one else except the recipient node is able to reconstruct the generated preimage.
* MUST expose preimage nonce as field `0` in the invoice.
* MUST expose its supported offline data transmission mediums using odd feature bits according to BOLT-12.
* if the generated preimage is presented through offline data transmission:
    * MUST grant access to the purchase.
* otherwise:
    * MUST NOT grant access to the purchase.

The sender
* if the recipient requires `deputy payment processing`:
    * if it supports `deputy payment processing`:
        * MUST use `deputy payment processing`.
    * otherwise:
        * MUST NOT initiate the payment.
* if the recipient optionally supprts `deputy payment processing`:
    * if it supports `deputy payment processing`:
        * MAY use `deputy payment processing`.
    * otherwise:
        * MAY use regular payment processing.

If the payment shall be processed using `deputy payment processing`, the sender
* if it supports none of the offline data transmission mediums supported by the receiver:
    * MUST NOT initiate the payment using `deputy payment processing`.
* if no routing hint was specified:
    * MUST NOT initiate the payment using `deputy payment processing`.
* if the invoice does not specify a field `0`:
    * MUST NOT initiate the payment using `deputy payment processing`.
* otherwise:
    * MUST add a `dpp` onion record to the hop of the last routing hint with
        * `preimagenonce` set to the value of field `0` of the invoice.
        * `invoiceamount` set to the amount requested by the invoice in msat; `0` if the invoice does not specify a minimal amount.
* if the payment was successful:
    * MAY present the preimage using offline data transmission and the `deputy payment preimage message`.

A recipient node supporting `deputy payment processing`:
* MUST set the feature bit `23` in its `init` and `node_announcement` message
* if the `dpp` onion payload is set:
    * if the received amount is less than the `invoiceamount`  specified in the `dpp` payload:
        * MUST fail the payment with `incorrect_or_unknown_payment_details`
    * if the preimage can be successfully reconstructed:
        * MUST claim the payment
    * otherwise:
        * MUST fail the payment with `incorrect_or_unknown_payment_details`



## Payload for the last Routing Hint

For the recipient node to be able to reconstruct the preimage of a `dpp` payment, additional information is required. This is transmitted using the `dpp` onion payload with type number `12`.

A`dpp` onion payload consists of the following parts:
* [`2*byte` : `preimagenonce`]: set to the preimage nonce exposed as field `0` in the invoice
* [`u64` : `invoiceamount`]: set to the amount in msat requested by the invoice

## Proof of Payment

In order to prove a successful payment and get access to the purchase, the `deputy payment preimage message` is used. This is an offline data transmission message (see BOLT-12) sent by the payer to the point of sale using a transmission medium supported by both parties.

The message consists of the following parts:
* [`2*byte`:`type`]: set to `0x0`
* [`32*byte`:`preimage`]: the preimage of the payment

## Deterministic preimage generation

As only the point of sale and the recipient node MUST use the same preimage generation process, this process itself shall not be part of the LN specification. However, there are certain things to consider when implementing such a process:

* The minimal requested amount SHOULD be used as input parameter for the preimage generation. Thereby it is ensured that the recipient node will generate a wrong preimage and therefore fail the payment when a fraudulent sender specifies a different amount in the `invoiceamount` part of the `dpp` onion payload.
* The preimage generation process SHOULD ensure that two invoices with the same amount do not have the same preimage. The random generated preimage nonce (field `0` in the invoices / `preimagenonce` part of the `dpp` onion payload) MAY be used for this.
* Only the point of sale and the recipient node SHOULD be able to generate the same preimage. In order to achieve this, some sort of shared secret MAY be used as an input parameter for the preimage generation.

## Data Flow

The following diagram shows the data flow of a DPP payment:

```
 ┌────────────────┐                                                                                                                            
 │Recipient Device│             ┌─────────────┐          ┌───────────┐          ┌─────────────────┐          ┌──────────────┐                  
 │(offline)       │             │Sender Device│          │Sender Node│          │Lightning Network│          │Recipient Node│                  
 └───────┬────────┘             └──────┬──────┘          └─────┬─────┘          └────────┬────────┘          └──────┬───────┘                  
         │────┐                        │                       │                         │                          │                          
         │    │ generate invoice       │                       │                         │                          │                          
         │<───┘                        │                       │                         │                          │                          
         │                             │                       │                         │                          │                          
         │       present invoice       │                       │                         │                          │                          
         │ ────────────────────────────>                       │                         │                          │                          
         │                             │                       │                         │                          │                          
         │                             │      send invoice     │                         │                          │                          
         │                             │ ──────────────────────>                         │                          │                          
         │                             │                       │                         │                          │                          
         │                             │                       │   initiate dpp payment  │                          │                          
         │                             │                       │ ────────────────────────>                          │                          
         │                             │                       │                         │                          │                          
         │                             │                       │                         │     route payment        │                          
         │                             │                       │                         │     (with dpp record)    │                          
         │                             │                       │                         │ ─────────────────────────>                          
         │                             │                       │                         │                          │                          
         │                             │                       │                         │                          │────┐                     
         │                             │                       │                         │                          │    │ re-generate preimage
         │                             │                       │                         │                          │<───┘ (using dpp record)  
         │                             │                       │                         │                          │                          
         │                             │                       │                         │                          │                          
         │                             │                       │                         │         preimage         │                          
         │                             │                       │                         │ <─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─                          
         │                             │                       │                         │                          │                          
         │                             │                       │         preimage        │                          │                          
         │                             │                       │ <─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─                           │                          
         │                             │                       │                         │                          │                          
         │                             │        preimage       │                         │                          │                          
         │                             │ <─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─                          │                          │                          
         │                             │                       │                         │                          │                          
         │ request preimage            │                       │                         │                          │                          
         │ (through a supported offline│                       │                         │                          │                          
         │ data transfer medium)       │                       │                         │                          │                          
         │ ────────────────────────────>                       │                         │                          │                          
         │                             │                       │                         │                          │                          
         │           preimage          │                       │                         │                          │                          
         │ <─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─                        │                         │                          │                          
 ┌───────┴────────┐             ┌──────┴──────┐          ┌─────┴─────┐          ┌────────┴────────┐          ┌──────┴───────┐                  
 │Recipient Device│             │Sender Device│          │Sender Node│          │Lightning Network│          │Recipient Node│                  
 │(offline)       │             └─────────────┘          └───────────┘          └─────────────────┘          └──────────────┘                  
 └────────────────┘                                                                                                                            
```


### Example
The following preimage formula meets all of the above requirements:

`preimage = sha256( concat( s, n, a))`

Whereas the parameters are defined as follows:
* `s`: shared secret only known by the point of sale and the recipient node
* `n`: preimage nonce (field `0` in the invoices / `preimagenonce` part of the `dpp` onion payload)
* `a`: minimal requested amount in msat (`amount` in the invoices / `invoiceamount` part of the `dpp` onion record)

`sha256` is used to always get a preimage of `32 * byte` length.

#### Point of Sale: Invoice generation example in JavaScript
```javascript
const sharedSecret = toUtf8Bytes('Sup3rS3cur3!');
const preimageNonce = crypto.randomBytes(32);
const amountMsat = 1000;

const preimage = sha256.create();
preimage.update(
    sharedSecret
        .concat(Array.from(preimageNonce))
        .concat(this.amountInMiliSatoshisBytes)
);
```

#### recipient Node: Preimage reconstruction example in Go
```go
secret := []byte("Sup3rS3cur3!")
var amount = make([]byte, 8)
binary.BigEndian.PutUint64(
    amount,
    payload.DeputyPaymentProcessing().InvoiceAmount(),
)
nonce := payload.DeputyPaymentProcessing().PreimageNonce()

preimageBase := secret
preimageBase = append(preimageBase, nonce[:]...)
preimageBase = append(preimageBase, amount...)

preimageInput := sha256.Sum256(preimageBase)
preimage, err := lntypes.MakePreimage(preimageInput[:])
```


## Example Invoices
TODO
