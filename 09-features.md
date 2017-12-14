# BOLT #9: Assigned Feature Flags

This document tracks the assignment of `localfeatures` and `globalfeatures` flags in the `init` message ([BOLT #1](01-messaging.md)), as well as the `features` field in the `channel_announcement` message and `node_announcement` message ([BOLT #7](07-routing-gossip.md)).
They are tracked separately since new flags will likely be added over time.

The `features` flags in the routing messages are a subset of the `globalfeatures` flags, since the `localfeatures` are by definition only of interest to direct peers.

Flags are numbered from the least-significant bit, at bit 0 (i.e. 0x1,
an even bit). They are generally assigned in pairs so that features
can be introduced as optional (odd bits) and later upgraded to be compulsory, refusing
old nodes (even bits). See [BOLT #1: The `init` Message](01-messaging.md#the-init-message).

## Assigned `localfeatures` flags

These flags may only be used in the `init` message:

| Bits | Name             |Description                                     | Link                                                                |
|------|------------------|------------------------------------------------|---------------------------------------------------------------------|
| 0/1  | `option-data-loss-protect` | Requires or supports extra `channel_reestablish` fields | [BOLT #2](02-peer-protocol.md#message-retransmission) |
| 3  | `initial_routing_sync` | Indicates that the sending node needs a complete routing information dump | [BOLT #7](07-routing-gossip.md#initial-sync) |
| 4/5  | `option_upfront_shutdown_script` | Commits to a shutdown scriptpubkey when opening | [BOLT #2](02-peer-protocol.md#the-open_channel-message) |

## Assigned `globalfeatures` flags

There are currently no `globalfeatures` flags.

## Requirements

The requirements for receiving specific bits are defined in the linked sections in the table above.
The requirements for feature bits that are not defined
above can be found in [BOLT #1: The `init` Message](01-messaging.md#the-init-message). 

## Rationale

There's little point in insisting on an `initial_routing_sync`. You can't
tell if the remote node complies, and it has to know what the flag means as
it's defined in the initial spec. So, there's no even bit for this.

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
