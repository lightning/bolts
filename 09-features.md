# BOLT #9: Assigned feature flags

This document tracks the assignment of `localfeatures` and `globalfeatures` flags in the `init` message ([BOLT #1](01-messaging.md)), as well as the `features` field in the `channel_announcement` message and `node_announcement` message ([BOLT #7](07-routing-gossip.md)).
They are tracked separately since new flags will likely be added over time.

The `features` flags in the routing messages are a subset of the `globalfeatures` flags, since the `localfeatures` are by definition only of interest to direct peers.

## Assigned `localfeatures` flags

This flags may only be used in the `init` message.

| Bits | Description                                     | Link                                                                |
|------|-------------------------------------------------|---------------------------------------------------------------------|
| 1    | The sending node wishes to announce the channel | [BOLT #7](07-routing-gossip.md#the-announcement_signatures-message) |

## Assigned `globalfeatures` flags
