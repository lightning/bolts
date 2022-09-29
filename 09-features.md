# BOLT #9: Assigned Feature Flags

This document tracks the assignment of `features` flags in the `init`
message ([BOLT #1](01-messaging.md)), as well as `features` fields in
the `channel_announcement` and `node_announcement` messages ([BOLT
#7](07-routing-gossip.md)).  The flags are tracked separately, since
new flags will likely be added over time.

Flags are numbered from the least-significant bit, at bit 0 (i.e. 0x1,
an _even_ bit). They are generally assigned in pairs so that features
can be introduced as optional (_odd_ bits) and later upgraded to be compulsory
(_even_ bits), which will be refused by outdated nodes:
see [BOLT #1: The `init` Message](01-messaging.md#the-init-message).

Some features don't make sense on a per-channels or per-node basis, so
each feature defines how it is presented in those contexts.  Some
features may be required for opening a channel, but not a requirement
for use of the channel, so the presentation of those features depends
on the feature itself.

The Context column decodes as follows:
* `I`: presented in the `init` message.
* `N`: presented in the `node_announcement` messages
* `C`: presented in the `channel_announcement` message.
* `C-`: presented in the `channel_announcement` message, but always odd (optional).
* `C+`: presented in the `channel_announcement` message, but always even (required).
* `9`: presented in [BOLT 11](11-payment-encoding.md) invoices.

| Bits  | Name                             | Description                                               | Context  | Dependencies      | Link                                  |
|-------|----------------------------------|-----------------------------------------------------------|----------|-------------------|---------------------------------------|
| 0/1   | `option_data_loss_protect`       | Requires or supports extra `channel_reestablish` fields   | IN       |                   | [BOLT #2][bolt02-retransmit]          |
| 3     | `initial_routing_sync`           | Sending node needs a complete routing information dump    | I        |                   | [BOLT #7][bolt07-sync]                |
| 4/5   | `option_upfront_shutdown_script` | Commits to a shutdown scriptpubkey when opening channel   | IN       |                   | [BOLT #2][bolt02-open]                |
| 6/7   | `gossip_queries`                 | More sophisticated gossip control                         | IN       |                   | [BOLT #7][bolt07-query]               |
| 8/9   | `var_onion_optin`                | Requires/supports variable-length routing onion payloads  | IN9      |                   | [Routing Onion Specification][bolt04] |
| 10/11 | `gossip_queries_ex`              | Gossip queries can include additional information         | IN       | `gossip_queries`  | [BOLT #7][bolt07-query]               |
| 12/13 | `option_static_remotekey`        | Static key for remote output                              | IN       |                   | [BOLT #3](03-transactions.md)         |
| 14/15 | `payment_secret`                 | Node supports `payment_secret` field                      | IN9      | `var_onion_optin` | [Routing Onion Specification][bolt04] |
| 16/17 | `basic_mpp`                      | Node can receive basic multi-part payments                | IN9      | `payment_secret`  | [BOLT #4][bolt04-mpp]                 |
| 18/19 | `option_support_large_channel`   | Can create large channels                                 | IN       |                   | [BOLT #2](02-peer-protocol.md#the-open_channel-message) |
| 20/21 | `option_anchor_outputs`          | Anchor outputs                                            | IN       | `option_static_remotekey` | [BOLT #3](03-transactions.md)         |
| 22/23 | `option_anchors_zero_fee_htlc_tx` | Anchor commitment type with zero fee HTLC transactions   | IN       | `option_static_remotekey` | [BOLT #3][bolt03-htlc-tx], [lightning-dev][ml-sighash-single-harmful]|
| 26/27 | `option_shutdown_anysegwit`         | Future segwit versions allowed in `shutdown`              | IN       |                   | [BOLT #2][bolt02-shutdown]   |
| 44/45 | `option_channel_type`            | Node supports the `channel_type` field in open/accept     | IN       |                   | [BOLT #2](02-peer-protocol.md#the-open_channel-message) |
| 46/47 | `option_scid_alias`              | Supply channel aliases for routing                        | IN       |                   | [BOLT #2][bolt02-channel-ready]   |
| 48/49 | `option_payment_metadata` | Payment metadata in tlv record | 9 | | [BOLT #11](11-payment-encoding.md#tagged-fields)
| 50/51 | `option_zeroconf`                | Understands zeroconf channel types                        | IN       | `option_scid_alias` | [BOLT #2][bolt02-channel-ready]   |

## Definitions

We define `option_anchors` as `option_anchor_outputs || option_anchors_zero_fee_htlc_tx`.

## Requirements

The origin node:
  * If it supports a feature above, SHOULD set the corresponding odd
    bit in all feature fields indicated by the Context column unless
	indicated that it must set the even feature bit instead.
  * If it requires a feature above, MUST set the corresponding even
    feature bit in all feature fields indicated by the Context column,
    unless indicated that it must set the odd feature bit instead.
  * MUST NOT set feature bits it does not support.
  * MUST NOT set feature bits in fields not specified by the table above.
  * MUST set all transitive feature dependencies.

The origin node MUST support:
  * `var_onion_optin`

The requirements for receiving specific bits are defined in the linked sections in the table above.
The requirements for feature bits that are not defined
above can be found in [BOLT #1: The `init` Message](01-messaging.md#the-init-message).

## Rationale

There is no _even_ bit for `initial_routing_sync`, as there would be little
point: a local node can't determine if a remote node complies, and it must
interpret the flag, as defined in the initial spec.

Note that for feature flags which are available in both the `node_announcement`
and [BOLT 11](11-payment-encoding.md) invoice contexts, the features as set in
the [BOLT 11](11-payment-encoding.md) invoice should override those set in the
`node_announcement`. This keeps things consistent with the unknown features
behavior as specified in [BOLT 7](07-routing-gossip.md#the-node_announcement-message).

The origin must set all transitive feature dependencies in order to create a
well-formed feature vector. By validating all known dependencies up front, this
simplifies logic gated on a single feature bit; the feature's dependencies are
known to be set, and do not need to be validated at every feature gate.

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).

[bolt02-retransmit]: 02-peer-protocol.md#message-retransmission
[bolt02-open]: 02-peer-protocol.md#the-open_channel-message
[bolt03-htlc-tx]: 03-transactions.md#htlc-timeout-and-htlc-success-transactions
[bolt02-shutdown]: 02-peer-protocol.md#closing-initiation-shutdown
[bolt02-channel-ready]: 02-peer-protocol.md#the-channel_ready-message
[bolt04]: 04-onion-routing.md
[bolt07-sync]: 07-routing-gossip.md#initial-sync
[bolt07-query]: 07-routing-gossip.md#query-messages
[bolt04-mpp]: 04-onion-routing.md#basic-multi-part-payments
[ml-sighash-single-harmful]: https://lists.linuxfoundation.org/pipermail/lightning-dev/2020-September/002796.html
