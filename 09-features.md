# BOLT #9: Assigned Feature Flags

This document tracks the assignment of `localfeatures` and `globalfeatures` flags in the `init` message ([BOLT #1](01-messaging.md)), as well as the `features` field in the `channel_announcement` message and `node_announcement` message ([BOLT #7](07-routing-gossip.md)).
They are tracked separately since new flags will likely be added over time.

The `features` flags in the routing messages are a subset of the `globalfeatures` flags, since the `localfeatures` are by definition only of interest to direct peers.

## Assigned `localfeatures` flags

These flags may only be used in the `init` message, and are generally assigned in pairs.

Flags begin at bit 0 (ie. 0x1), and odd-numbered flags (eg. 0x2) are optional.


| Bits | Name             |Description                                     | Link                                                                |  Feature bits semantic |
|------|------------------|------------------------------------------------|---------------------------------------------------------------------|---|
| 0/1  | `channels_public` | The sending node wishes to announce channels | [BOLT #7](07-routing-gossip.md#the-announcement_signatures-message) | Default |
| 2/3  | `initial_routing_sync` | The sending node needs a complete routing information dump | [BOLT #7](07-routing-gossip.md#initial-sync) | Default |

## Assigned `globalfeatures` flags


![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
