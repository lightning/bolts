# BOLT #12: Offline Data Transmission

Some specific features (e.g. offline payments) require the devices of the sender and receipient of a payment to be able to communicate with each other. As those devices oftentimes are not lightning nodes, this communication cannot be done through lightning messaging as described in BOLT-1. Thereofore, BOLT-12 defines how such devices can exchange messages directly while being offline / not connected to the lightning network.


## Transfer Medium
The devices may support various mediums in order to transmit data. Therefore, it is important that sender and receiver device can choose a medium which is supported by both sides. This is done using feature bits.

The following mediums are supported:


| Feature Bit | Name    | Description                                                                                             |
| ----------- | ------- | ------------------------------------------------------------------------------------------------------- |
| `129`       | QR Code | Data is transmitted by showing a QR Code. The code consists of a HEX-string of the message to transfer. |

Feature bits corresponding to supported offline data transmission mediums SHOULD always be odd as a single medium supported by both parties is sufficient for a successful data transmission.

### Requirements

The recipient device
* MUST set the feature bits corresponding to its supported data transmission mediums in the invoice.
* MUST be ready to receive messages through offline data transmission through all of the supported transmission mediums at any time.

The sender
* if offline data transmission is required:
    * SHOULD only pay an invoice if it supports one of the data transmission mediums defined by the invoice feature bits.

## Message Format
All offline messages are of the form:
1. `type`: a 1-byte big-endian field indicating the type of message.
1. `payload`: a variable-length payload that comprises the remainder of the message and that conforms to a format matching the `type`.

### Requirements

A receipient of an offline message
* MUST not break when a message of an unknown type is received.
* MAY show a warning or error when a message of an unknown type is received.

## Message Types

As offline messages correspond to specific features, every message type is described in a dedicated BOLT of the corresponding feature. The following table gives an overview of already reserved types:

| Type  | Name                            | BOLT    |
| ----- | ------------------------------- | ------- |
| `0x0` | Deputy Payment Preimage Message | BOLT-13 |
| `0x1` | Payment Authorization Message   | BOLT-14 |
