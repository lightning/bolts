# BOLT #12: Distributed Name Mapping Storage Service (Atlas)

Atlas is a distributed, peer to peer mapping storage and retrieval system for
advertising human meaningful data.

# Table of Contents
  * [Overview](#overview)
  * [Rationale](#rationale)
  * [Example Scenario](#example-scenario)
  * [Data Types Table](#data-types-table)

# Overview

Atlas is an optional feature bit and service integrated into the Lightning daemon
that allows a node operator to use their existing channels and liquidity to advertise
information that would be useful to them (for example, "What is the public key
associated to the username Tyzbit?").  It is extensible to include more data types
in the future, and it allows for hosting, serving, and updating human meaningful
mappings in a fair, secure and distributed way.

Any node can be queried for a data mapping, and the node can serve any data mapping
it wants.  However, in order for a mapping to be trusted, the serving node must
"put its money where its mouth is" and pay out an invoice to the client making the request.

# Rationale

Nodes can host the data that they care about, such as their public keys or files
they wish to distribute.  Then random nodes on the network can be queried for
mappings they host, and pay invoices out to vouch for the accuracy of the data.
If the data proves to be accurate, a user can refund the funds as a way to thank
the hosting node for hosting the data.  

# Example Scenario

First, a Lightning node operator decides on some piece of information to advertise.
In this case, the user decides to advertise their email address and a GPG public
key for the address.  The user registers the mapping in the local database, along
with selecting parameters for how much to pay out to clients requesting the mapping.
Then the user's node announces to the network at large this new mapping availability.
The announcement also includes information about the payout ranges for the mapping.

Now, the user's friend wishes to verify the GPG key in order to send an email.
The user's friend makes an Atlas query to a random node on the Lightning network
for the mapping.  The node then responds with the mapping requested.  Then the
friend's node sends a payment request to the node that served the response.

If the node pays the invoice, then the user can be reasonably sure that the mapping
is valid.  To confirm, the friend can query another node, and check the response
it provides, along with confirming it pays an invoice supplied.

Finally, if the user finds the result was accurate, they have the option of returning
the funds to the originating node.  However, if the user finds the results were
inaccurate, the daemon automatically advertises a new Atlas mapping of type zero
that the node in question has provided an inaccurate mapping.

Type 0 Atlas messages are also distributed when a node does not pay out an invoice
for a mapping that it has advertised it was willing to pay.

# Data Types Table

Mappings should be [datatype][name][separator][data].

Constant length 2+-byte data field | Proposed Data Standard                 | Separator | Description
-----------------------------------|----------------------------------------|-----------|-------------
00                                 | Node Reputation Update                 | 0xFF      | The data advertised is the pubkey of a Lightning node that has misbehaved or refunded an Atlas payment on the Lightning network.
01                                 | Bitcoin Address                        | 0xFF      | The data advertised is a Bitcoin address is associated to the given name.
02                                 | Binary file                            | 0xFF      | The data is a binary file.
03                                 | GPG Public Key                         | 0xFF      | The data associated with the name SHOULD BE used to advertise a GPG Public Key
04                                 | Domain-validated Certificate           | 0xFF      | The data is a domain certificate for the specified name (ex: example.com)
05                                 | DNS mapping                            | 0xFF      | The data is a valid IP address.
06                                 | Tor mapping                            | 0xFF      | The data is an Tor onion address.
07                                 | Software Signing Key                   | 0xFF      | The data is a public key to verify signed software packages.
08-FF                              | Future use decided upon via consensus. | 0xFF      | Future use

# Additional usage

Atlas can be used alongside Eltoo for nodes that misbehave.  If a node broadcasts
a previous state of a channel, the honest node can themselves broadcast chain proof
that the node has misbehaved, and other nodes receiving the message can choose to
preemptively cooperatively close their channels with the offending node, if they
have them.

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
