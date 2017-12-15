# BOLT #10: DNS Bootstrap and Assisted Node Location

This specification describes a node discovery mechanism based on the Domain Name System (DNS).
Its purpose is twofold:

 - Bootstrap: providing the initial node discovery for nodes that have no known contacts in the network
 - Assisted Node Location: supporting nodes in discovery of the current network address of previously known peers

A domain name server implementing this specification is called a _DNS Seed_, and answers incoming DNS queries of type `A`, `AAAA`, or `SRV` as specified in RFCs 1035<sup>[1](#ref-1)</sup>, 3596<sup>[2](#ref-2)</sup> and 2782<sup>[3](#ref-3)</sup> respectively.
The DNS server is authoritative for a subdomain, called a _seed root domain_, and clients may query it for subdomains.

The subdomains consist of a number of dot-separated _conditions_ that further narrow the desired results.

## DNS Seed Queries

A client MAY issue queries using the `A`, `AAAA`, or `SRV` query types, specifying conditions for the desired results that the seed should return.

### Query Semantics

The conditions are key-value pairs with a single-letter key; the remainder of the key-value pair is the value.
The following key-value pairs MUST be supported by a DNS seed:

 - `r`: realm byte, used to specify what realm the returned nodes must support (default value: 0, Bitcoin)
 - `a`: address types, used to specify what address types should be returned for `SRV` queries. This is a bitfield that uses the types from [BOLT 7](07-routing-gossip.md) as bit index. This condition MAY only be used for `SRV` queries. (default value: 6, i.e. `2 || 4`, since bit 1 and bit 2 are set for IPv4 and IPv6, respectively) 
 - `l`: `node_id`, the bech32-encoded `node_id` of a specific node, used to ask for a single node instead of a random selection. (default: null)
 - `n`: the number of desired reply records (default: 25)

Results returned by the DNS seed SHOULD match all conditions.
If the DNS seed does not implement filtering by a given condition it MAY ignore the condition altogether (i.e. the seed filtering is best effort only).
Clients MUST NOT rely on any given condition being met by the results.

Queries distinguish between _wildcard_ queries and _node_ queries, depending on whether the `l`-key is set or not.

Upon receiving a wildcard query, the DNS seed MUST select a random subset of up to `n` IPv4 or IPv6 addresses of nodes that are listening for incoming connections.
For `A` and `AAAA` queries, only nodes listening on the default port 9735, as defined in [BOLT 01](01-messaging.md), MUST be returned.
Since `SRV` records return a _(hostname,port)_-tuple, nodes that are listening on non-default ports MAY be returned.

Upon receiving a node query, the seed MUST select the record matching the `node_id`, if any, and return all addresses associated with that node.

### Reply Construction

The results are serialized in a reply with a query type matching the client's query type, i.e. `A` queries result in `A` replies, `AAAA` queries result in `AAAA` replies, and `SRV` queries result in `SRV` replies, but they may be augmented with additional records (e.g. to add `A` or `AAAA` records matching the returned `SRV` records).

For `A` and `AAAA` queries, the reply contains the domain name and the IP address of the results.
The domain name MUST match the domain in the query in order not to be filtered by intermediate resolvers.

For `SRV` queries, the reply consists of (_virtual hostnames_, port)-tuples
A virtual hostname is a subdomain of the seed root domain that uniquely identifies a node in the network.
It is constructed by prepending the `node_id` condition to the seed root domain.
The DNS seed MAY additionally return the corresponding `A` and `AAAA` records that indicate the IP address for the `SRV` entries in the Extra section of the reply.
Due to the large size of the resulting reply, the reply may be dropped by intermediate resolvers, hence the DNS seed MAY omit these additional records upon detecting a repeated query.

Should no entries match all the conditions then an empty reply MUST be returned.

## Policies

The DNS seed MUST NOT return replies with a TTL lower than 60 seconds.
The DNS seed MAY filter nodes from its local views for various reasons, including faulty nodes, flaky nodes, or spam prevention.
In accordance with the Bitcoin DNS Seed policy<sup>[4](#ref-4)</sup>, replies to random queries (i.e. queries to the seed root domain and to the `_nodes._tcp.` alias for `SRV` queries) MUST be random samples from the set of all known good nodes and MUST NOT be biased.

## Examples

Querying for `AAAA` records:

	$ dig lseed.bitcoinstats.com AAAA
	lseed.bitcoinstats.com. 60      IN      AAAA    2a02:aa16:1105:4a80:1234:1234:37c1:9c9

Querying for `SRV` records:

	$ dig lseed.bitcoinstats.com SRV
	lseed.bitcoinstats.com. 59   IN      SRV     10 10 6331 ln1qwktpe6jxltmpphyl578eax6fcjc2m807qalr76a5gfmx7k9qqfjwy4mctz.lseed.bitcoinstats.com.
	lseed.bitcoinstats.com. 59   IN      SRV     10 10 9735 ln1qv2w3tledmzczw227nnkqrrltvmydl8gu4w4d70g9td7avke6nmz2tdefqp.lseed.bitcoinstats.com.
	lseed.bitcoinstats.com. 59   IN      SRV     10 10 9735 ln1qtynyymv99pqf0r9cuexvvqtxrlgejuecf8myfsa96vcpflgll5cqmr2xsu.lseed.bitcoinstats.com.
	lseed.bitcoinstats.com. 59   IN      SRV     10 10 4280 ln1qdfvlysfpyh96apy3w3qdwlu8jjkdhnuxa689ka540tnde6gnx86cf7ga2d.lseed.bitcoinstats.com.
	lseed.bitcoinstats.com. 59   IN      SRV     10 10 4281 ln1qwf789tlcpe4n34649xrqllxt97whsvfk5pm07ggqms3vrjwdj3cu6332zs.lseed.bitcoinstats.com.

Querying for the `A` for the first virtual hostname from the previous example:

	$dig ln1qwktpe6jxltmpphyl578eax6fcjc2m807qalr76a5gfmx7k9qqfjwy4mctz.lseed.bitcoinstats.com A
	ln1qwktpe6jxltmpphyl578eax6fcjc2m807qalr76a5gfmx7k9qqfjwy4mctz.lseed.bitcoinstats.com. 60 IN A 139.59.143.87

## References
- <a id="ref-1">[RFC 1035 - Domain Names](https://www.ietf.org/rfc/rfc1035.txt)</a>
- <a id="ref-2">[RFC 3596 - DNS Extensions to Support IP Version 6](https://tools.ietf.org/html/rfc3596)</a>
- <a id="ref-3">[RFC 2782 - A DNS RR for specifying the location of services (DNS SRV)](https://www.ietf.org/rfc/rfc2782.txt)</a>
- <a id="ref-4">[Expectations for DNS Seed operators](https://github.com/bitcoin/bitcoin/blob/master/doc/dnsseed-policy.md)</a>
