# BOLT #14: Authorized Payment Initiation

Some use cases require the ability to directly request a payment from a specific node. This BOLT defines how such payments can be initiated using `authorized payment initiation`.

`authorized payment initiation` relies on token based authorization. Any node can request a payment from another node using the `initiate_payment` message described in this BOLT and by presenting a valid authorization token.


### The `initiate_payment` message

An `initiate_payment` message MUST have the following format:

1. type: 45001 (`initiate_payment`)
1. data:
    * [`u16`:`tlen`]
    * [`tlen*byte`:`token`]
    * [`u16`:`ilen`]
    * [`ilen*byte`: `invoice`]

### Requirements

The sending node:
* MUST set `invoice` to a valid payment request / invoice.
* MUST set `token` to the received authorization token.


The receiving node:
* if the `invoice` is not valid according to BOLT-11
    * SHOULD NOT initiate the payment.
    * SHOULD respond with a `reject_payment` message.
* otherwise, if the `token` is valid for `invoice`
    * SHOULD initiate the payment.
* otherwise
    * SHOULD NOT initiate the payment.
    * SHOULD respond with a `reject_payment` message.

### The `reject_payment` message

1. type: 45003 (`reject_payment`)
1. data:
    * [`32*byte`:`tokenhash`]
    * [`u16`:`ilen`]
    * [`ilen*byte`: `invoice`]

The sending node:
* if no peer connection is established:
    * MUST establish a peer connection before sending.
    * SHOULD terminate the peer connection after sending
* otherwise:
    * MUST use the already existing peer connection.
    * SHOULD NOT terminate the peer connection after sending.
* MUST set `invoice` to the invoice received by the `initiate_payment` message.
* MUST set `tokenhash` to the sha256 hash of the authorization token received by the `initiate_payment` message.

The receiving node:
* MAY retry initiating the payment using a different token.

## Token Transfer using Offline Data Transmission

Authorization Tokens MAY be transmitted through Offline Data Transmission according to BOLT-12 using the `payment authorization` message.


The message consists of the following parts:
* [`2 * byte`:`type`]: set to `0x1`
* [`u16`:`ulen`]: the length of `uri`
* [`ulen*byte`:`uri`]: the URI of the node where to request the payment in the format `pubkey`@`host`:`port`
* [`u16`:`tlen`]: the lenght of `token`
* [`tlen*byte`:`token`]: the autorization token


### Requirements

A message sender
* MUST set `uri` to a valid node URI, specifiying the node where the payment MAY be requested.
* MUST set `token` to a valid token.

A message receiver
* MUST know which payment the token is intended for.
* MAY use the token to initiate the corresponding payment.
* SHOULD request the payment from no different node than the one specified in the `uri` part.


## Token Validity
As the receiving node of a `initiate_payment` message is the only one which MUST be able to validate authorization tokens, their concrete characteristics is not part of this specification. Therefore, node implementations are free to choose their own way(s) on deciding whether a token is valid. For example, one could require the token to be a trusted ECC signature of the respective invoice. Another approach could be limiting the tokens usage by the invoice amount or its usage frequency.


## Data Flow

The following diagram shows the data flow of a payment using Authorized Payment Initiation:

```
 ┌─────────────┐                                                                                                                          
 │Sender Device│             ┌────────────────┐          ┌──────────────┐              ┌───────────┐          ┌─────────────────┐         
 │(offline)    │             │Recipient Device│          │Recipient Node│              │Sender Node│          │Lightning Network│         
 └──────┬──────┘             └───────┬────────┘          └──────┬───────┘              └─────┬─────┘          └────────┬────────┘         
        │      request invoice       │                          │                            │                         │                  
        │────────────────────────────>                          │                            │                         │                  
        │                            │                          │                            │                         │                  
        │present invoice             │                          │                            │                         │                  
        │(through a supported offline│                          │                            │                         │                  
        │data transfer medium)       │                          │                            │                         │                  
        │<─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─                           │                            │                         │                  
        │                            │                          │                            │                         │                  
        ────┐                        │                          │                            │                         │                  
            │ generate auth token    │                          │                            │                         │                  
        <───┘                        │                          │                            │                         │                  
        │                            │                          │                            │                         │                  
        │send token                  │                          │                            │                         │                  
        │(through a supported offline│                          │                            │                         │                  
        │data transfer medium)       │                          │                            │                         │                  
        │────────────────────────────>                          │                            │                         │                  
        │                            │                          │                            │                         │                  
        │                            │        send token        │                            │                         │                  
        │                            │ ─────────────────────────>                            │                         │                  
        │                            │                          │                            │                         │                  
        │                            │                          │    open peer connection    │                         │                  
        │                            │                          │    (if necessary)          │                         │                  
        │                            │                          │ ──────────────────────────>│                         │                  
        │                            │                          │                            │                         │                  
        │                            │                          │        feature bits        │                         │                  
        │                            │                          │ <─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │                         │                  
        │                            │                          │                            │                         │                  
        │                            │                          │────┐                       │                         │                  
        │                            │                          │    │ validate feature bits │                         │                  
        │                            │                          │<───┘                       │                         │                  
        │                            │                          │                            │                         │                  
        │                            │                          │ initiatate payment         │                         │                  
        │                            │                          │ (initiate_payment message) │                         │                  
        │                            │                          │ ──────────────────────────>│                         │                  
        │                            │                          │                            │                         │                  
        │                            │                          │                            ────┐                     │                  
        │                            │                          │                                │ validate token      │                  
        │                            │                          │                            <───┘                     │                  
        │                            │                          │                            │                         │                  
        │                            │                          │                            │                         │                  
        │                            │         ╔══════╤═════════╪════════════════════════════╪═════════════════════════╪═════════════════╗
        │                            │         ║ ALT  │  token is valid                      │                         │                 ║
        │                            │         ╟──────┘         │                            │                         │                 ║
        │                            │         ║                │                            │    initiate payment     │                 ║
        │                            │         ║                │                            │────────────────────────>│                 ║
        │                            │         ╠════════════════╪════════════════════════════╪═════════════════════════╪═════════════════╣
        │                            │         ║ [token is not valid]                        │                         │                 ║
        │                            │         ║                │  reject payment            │                         │                 ║
        │                            │         ║                │  (reject_payment message)  │                         │                 ║
        │                            │         ║                │ <──────────────────────────│                         │                 ║
        │                            │         ╚════════════════╪════════════════════════════╪═════════════════════════╪═════════════════╝
 ┌──────┴──────┐             ┌───────┴────────┐          ┌──────┴───────┐              ┌─────┴─────┐          ┌────────┴────────┐         
 │Sender Device│             │Recipient Device│          │Recipient Node│              │Sender Node│          │Lightning Network│         
 │(offline)    │             └────────────────┘          └──────────────┘              └───────────┘          └─────────────────┘         
 └─────────────┘                                                                                                                                                                                                                                                     
```
