# BOLT #9: Assigned Feature Flags

This document tracks the assignment of `localfeatures` and `globalfeatures`
flags in the `init` message ([BOLT #1](01-messaging.md)) along with the
`features` flag fields in the `channel_announcement` and `node_announcement`
messages ([BOLT #7](07-routing-gossip.md)).
The flags are tracked separately, since new flags will likely be added over time.

The `features` flags in the routing messages are a subset of the
`globalfeatures` flags, as `localfeatures`, by definition, are only of interest
to direct peers.

Flags are numbered from the least-significant bit, at bit 0 (i.e. 0x1,
an _even_ bit). They are generally assigned in pairs so that features
can be introduced as optional (_odd_ bits) and later upgraded to be compulsory
(_even_ bits), which will be refused by outdated nodes:
see [BOLT #1: The `init` Message](01-messaging.md#the-init-message).

## Assigned `localfeatures` flags

These flags may only be used in the `init` message:

| Bits | Name                             | Description                                                               | Link                   |
|------|----------------------------------|---------------------------------------------------------------------------|------------------------|
| 0/1  | `option_data_loss_protect`       | Requires or supports extra `channel_reestablish` fields                   | [BOLT #2][bolt02]      |
| 3    | `initial_routing_sync`           | Indicates that the sending node needs a complete routing information dump | [BOLT #7][bolt07]      |
| 4/5  | `option_upfront_shutdown_script` | Commits to a shutdown scriptpubkey when opening channel                   | [BOLT #2][bolt02open]  |
| 6/7  | `gossip_queries`                 | More sophisticated gossip control                                         | [BOLT #7][bolt07query] |

## Assigned `globalfeatures` flags

The following `globalfeatures` bits are currently assigned by this specification:

| Bits | Name              | Description                                                 | Link                                  |
|------|-------------------|-------------------------------------------------------------|---------------------------------------|
| 8/9  | `var_onion_optin` | This node requires/supports variable payload routing onions | [routing onion specification][bolt04] |


## Requirements

The requirements for receiving specific bits are defined in the linked sections in the table above.
The requirements for feature bits that are not defined
above can be found in [BOLT #1: The `init` Message](01-messaging.md#the-init-message).

## Rationale

There is no _even_ bit for `initial_routing_sync`, as there would be little
point: a local node can't determine if a remote node complies, and it must
interpret the flag, as defined in the initial spec.

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
[bolt02]: 02-peer-protocol.md#message-retransmission
[bolt02open]: 02-peer-protocol.md#the-open_channel-message
[bolt04]: 04-onion-routing.md
[bolt07]: 07-routing-gossip.md#initial-sync
[bolt07query]: 07-routing-gossip.md#query-messages
