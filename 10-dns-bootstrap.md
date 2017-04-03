# BOLT #10: DNS Bootstrap and Assisted Node Location

This specification describes a node discovery mechanism based on the Domain Name System.
Its purpose is twofold:

 - Bootstrap: the initial node discovery for nodes that have no known contacts in the network
 - Assisted Node Location: supporting nodes to discover the current network address previously known peers

A domain name server implementing this specification is called a _DNS Seed_, and answers incoming DNS queries of type `A`, `AAAA` or `SRV` as specified in RFCs 1035<sup>[1](#ref-1)</sup>, 3596<sup>[2](#ref-2)</sup> and 2782<sup>[3](#ref-3)</sup> respectively.
The DNS server is authoritative for a subdomain, called a _seed root domain_, and clients may query either the seed root domain or subdomains thereunder.

## Subdomain Structure

A client MAY query the seed root domain for either `A`, `AAAA` or `SRV` records.
Upon receiving `A` and `AAAA` queries the DNS seed MUST return a random subset of up to 25 IPv4 or IPv6 addresses of nodes that are listening for incoming connections on the default port 9735 as defined in [BOLT 01](01-messaging.md).
In accordance with the Bitcoin DNS Seed policy<sup>[4](#ref-4)</sup> the DNS seed operator MAY NOT bias the result in any form, apart from filtering non-functioning or malicious nodes from the result.
The domain name associated with the addresses returned to `A` and `AAAA` queries MUST match the domain name in the query in order not to be filtered by intermediate resolvers.

Upon receiving `SRV` queries the DNS seed MUST return a random subset of up to 5 (_virtual hostnames_, port)-tuples.
A virtual hostname is a subdomain of the seed root domain that uniquely identifies a node in the network.
It is constructed by splitting the hex encoded `node_id` of the node into two parts, each no longer than 64 characters, dropping any leading `0` characters, separating them with a single period (`.`), and prepending it as a subdomain to the seed root domain.
The DNS seed MAY additionally return the corresponding `A` and `AAAA` indicating the IP address for the `SRV` entries in the Extra section of the reply.
Due to the large size of the resulting reply it may happen that the reply is dropped by intermediate resolvers, hence the DNS seed MAY omit these additional records upon detecting a repeated query.
The DNS seed MUST also allow the `_nodes._tcp.` subdomain for `SRV` queries.
This is the standard compliant version as specified in RFC 2782<sup>[3](#ref-3)</sup>.

A client MAY ask directly for the `A` or `AAAA` record for a specific node by querying for the virtual hostname.
This may either be due to a previous `SRV` reply that omitted the extra section, or because the client is attempting to locate a specific node it was connected to before.
Upon receiving an `SRV` query for a virtual hostname, the DNS seed reconstructs the `node id` by removing the separating period and looking the IP address up in its local network view.
The DNS seed MUST return all known IP addresses for the queried `node id`.
In case of an IP class mismatch, e.g., the client asked for IPv4 addresses with an `A` query, but the result is an IPv6 `AAAA` record, then the record MUST be returned in the extra section.
This MAY result in an empty reply, with the actual result in the extra section, and clients MUST handle it accordingly.
The domain name returned in an `A` or `AAAA` reply MUST match the virtual hostname from the query in order not to be dropped by intermediate resolvers.

## Policies

The DNS seed MUST NOT return replies with a TTL lower than 60 seconds.
The DNS seed MAY filter nodes from its local views for various reasons, including faulty nodes, flaky nodes, or spam prevention.
Replies to random queries, i.e., queries to the seed root domain and the `_nodes._tcp.` alias for `SRV` queries, MUST be random samples from the set of all known good nodes and MUST NOT be biased.

## Examples

Querying for `AAAA` records:

	lseed.bitcoinstats.com. 60      IN      AAAA    2a02:aa16:1105:4a80:aead:aad2:37ce:9ca

Querying for `SRV` records:

	lseed.bitcoinstats.com. 60      IN      SRV     10 10 23202 3e2a4210722570eaa18200c3a5b5fc6f40ebd7d698724a3bf2cd5dd5fea4d93.bb.lseed.bitcoinstats.com.
	lseed.bitcoinstats.com. 60      IN      SRV     10 10 23201 314e8aff96ec581394af4e7600c7f5b3646fce8e55d56f9e82adbeeb2d9d4f6.25.lseed.bitcoinstats.com.
	lseed.bitcoinstats.com. 60      IN      SRV     10 10 23201 203b525e1096f4b06f60d93bc78da0d062aef90fb398db786285ac8911b9f8b.40.lseed.bitcoinstats.com.
	lseed.bitcoinstats.com. 60      IN      SRV     10 10 6334 2233e25e33d1e652beaf9d32f64a8383c6b63bc82fcdeb8a3588092e490ef55.7e.lseed.bitcoinstats.com.
	lseed.bitcoinstats.com. 60      IN      SRV     10 10 6331 26fad0132cdde76e2e5cd77b822ef21392b547566814ed21028d88281540ee6.36.lseed.bitcoinstats.com.

Querying for the `A` for the first virtual hostname from the previous example:

	3e2a4210722570eaa18200c3a5b5fc6f40ebd7d698724a3bf2cd5dd5fea4d93.bb.lseed.bitcoinstats.com. 60 IN A 45.32.248.251

## References
- <a id="ref-1">[RFC 1035 - Domain Names](https://www.ietf.org/rfc/rfc1035.txt)</a>
- <a id="ref-2">[RFC 3596 - DNS Extensions to Support IP Version 6](https://tools.ietf.org/html/rfc3596)</a>
- <a id="ref-3">[RFC 2782 - A DNS RR for specifying the location of services (DNS SRV)](https://www.ietf.org/rfc/rfc2782.txt)</a>
