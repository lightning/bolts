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


| Bits | Name             |Description                                     | Link                                                                |
|------|------------------|------------------------------------------------|---------------------------------------------------------------------|
| 0/1  | `channels_public` | The sending node wishes to announce channels | [BOLT #7](07-routing-gossip.md#the-announcement_signatures-message) |
| 3  | `initial_routing_sync` | The sending node needs a complete routing information dump | [BOLT #7](07-routing-gossip.md#initial-sync) |

## Assigned `globalfeatures` flags

## Requirements

(Note that the requirements for feature bits which are not defined
above, can be found in [BOLT #1: The `init` message](#the-init-message)).  The requirements when receiving set bits are defined in the linked section in the table above).

Additional requirements:

* `channels_public`: the sender MUST set exactly one of these bits if
   it wants to announce the channel publicly, otherwise it MUST set
   neither.  If it sets one it MUST set the even bit if will fail the
   connection if the other node does not also set one of the
   `channels_public` bits, otherwise it MUST set the odd bit.  The
   receiver MUST terminate the connection if neither `channels_public`
   bit is set and it set the even `channels_public` bit on the `init`
   message it sent, otherwise the receiver SHOULD treat either bit the
   same.

## Rationale

There's little point insisting on an `initial_routing_sync` (you can't
tell if the remote node complies, and it has to know what it means as
it's defined in the initial spec) so there's no even bit for that.

There is a some point in insisting on channels being public: a node
may not want to serve any private channels, and this gives clear
indication, so that uses both bits.  You can read these bits as "odd:
I would like the channel to be public" and "even: I require that the
channel be public".


![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
