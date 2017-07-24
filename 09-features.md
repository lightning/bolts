# BOLT #9: Assigned Feature Flags

This document tracks the assignment of `localfeatures` and `globalfeatures` flags in the `init` message ([BOLT #1](01-messaging.md)), as well as the `features` field in the `channel_announcement` message and `node_announcement` message ([BOLT #7](07-routing-gossip.md)).
They are tracked separately since new flags will likely be added over time.

The `features` flags in the routing messages are a subset of the `globalfeatures` flags, since the `localfeatures` are by definition only of interest to direct peers.

Flags are numbered from the least-significant bit at bit 0 (ie. 0x1,
an even bit).  They are generally assigned in pairs, so that features
can be introduced as optional (odd bits), and later upgraded to refuse
old nodes (even bits).  See [BOLT #1: The `init` message](#the-init-message).

## Assigned `localfeatures` flags

These flags may only be used in the `init` message:


| Bits  | Name                   |Description                                                 | Link                                         |
|-------|------------------------|------------------------------------------------------------|----------------------------------------------|
| 0x03  | `initial_routing_sync` | The sending node needs a complete routing information dump | [BOLT #7](07-routing-gossip.md#initial-sync) |

The bits are expressed as a bitmask that can be used to check for the presence of a flag.
For example bits `0x03` means that both bit 0 and bit 1 are used to signal, bit 0 indicates mandatory support, while bit 1 indicates optional support.

## Assigned `globalfeatures` flags

## Requirements

(Note that the requirements for feature bits which are not defined
above, can be found in [BOLT #1: The `init` message](#the-init-message)).  The requirements when receiving set bits are defined in the linked section in the table above).

## Rationale

There's little point insisting on an `initial_routing_sync` (you can't
tell if the remote node complies, and it has to know what it means as
it's defined in the initial spec) so there's no even bit for that.

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
