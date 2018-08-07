# BOLT #10: DNS Bootstrap and Assisted Node Location

## Overview

This specification describes a node discovery mechanism based on the Domain Name System (DNS).
Its purpose is twofold:

 - Bootstrap: providing the initial node discovery for nodes that have no known contacts in the network
 - Assisted Node Location: supporting nodes in discovery of the current network address of previously known peers

A domain name server implementing this specification is referred to as a
_DNS Seed_ and answers incoming DNS queries of type `A`, `AAAA`, or `SRV`, as
specified in RFCs 1035<sup>[1](#ref-1)</sup>, 3596<sup>[2](#ref-2)</sup>, and
2782<sup>[3](#ref-3)</sup>, respectively.
The DNS server is authoritative for a subdomain, referred to as a
_seed root domain_, and clients may query it for subdomains.

The subdomains consist of a number of dot-separated _conditions_ that further narrow the desired results.

## Table of Contents

  * [DNS Seed Queries](#dns-seed-queries)
    * [Query Semantics](#query-semantics)
  * [Reply Construction](#reply-construction)
  * [Policies](#policies)
  * [Examples](#examples)
  * [References](#references)
  * [Authors](#authors)

## DNS Seed Queries

A client MAY issue queries using the `A`, `AAAA`, or `SRV` query types,
specifying conditions for the desired results the seed should return.

Queries distinguish between _wildcard_ queries and _node_ queries, depending on
whether the `l`-key is set or not.

### Query Semantics

The conditions are key-value pairs: the key is a single-letter, while the
remainder of the key-value pair is the value.
The following key-value pairs MUST be supported by a DNS seed:

 - `r`: realm byte
   - used to specify what realm the returned nodes must support
   - default value: 0 (Bitcoin)
 - `a`: address types
   - a bitfield that uses the types from [BOLT #7](07-routing-gossip.md) as bit
   index
   - used to specify what address types should be returned for `SRV` queries
   - MAY only be used for `SRV` queries
   - default value: 6 (i.e. `2 || 4`, since bit 1 and bit 2 are set for IPv4 and
     IPv6, respectively)
 - `l`: `node_id`
   - a bech32-encoded `node_id` of a specific node
   - used to ask for a single node instead of a random selection
   - default value: null
 - `n`: number of desired reply records
   - default value: 25

Conditions are passed in the DNS seed query as individual, dot-separated subdomain components.

For example, a query for `r0.a2.n10.lseed.bitcoinstats.com` would imply: return
10 (`n10`) IPv4 (`a2`) records for nodes supporting Bitcoin (`r0`).

### Requirements

The DNS seed:
  - MUST evaluate the conditions from the _seed root domain_ by
  'going up-the-tree', i.e. evaluating right-to-left in a fully qualified domain
name.
    - E.g. to evaluate the above case: first evaluate `n10`, then `a2`, and finally `r0`.
  - if a condition (key) is specified more than once:
    - MUST discard any earlier value for that condition AND use the new value
    instead.
      - E.g. for `n5.r0.a2.n10.lseed.bitcoinstats.com`, the result is:
      ~~`n10`~~, `a2`, `r0`, `n5`.
  - SHOULD return results that match all conditions.
  - if it does NOT implement filtering by a given condition:
    - MAY ignore the condition altogether (i.e. the seed filtering is best effort only).
  - for `A` and `AAAA` queries:
    - MUST return only nodes listening on the default port 9735, as defined in
    [BOLT #1](01-messaging.md).
  - for `SRV` queries:
    - MAY return nodes that are listening on non-default ports, since `SRV`
    records return a _(hostname,port)_-tuple.
  - upon receiving a _wildcard_ query:
    - MUST select a random subset of up to `n` IPv4 or IPv6 addresses of nodes
    that are listening for incoming connections.
  - upon receiving a _node_ query:
    - MUST select the record matching the `node_id`, if any, AND return all
    addresses associated with that node.

Querying clients:
  - MUST NOT rely on any given condition being met by the results.

### Reply Construction

The results are serialized in a reply with a query type matching the client's
query type. For example, `A`, `AAAA`, and `SRV` queries respectively result in
`A`, `AAAA`, and `SRV` replies. Additionally, replies may be augmented with
additional records (e.g. to add `A` or `AAAA` records matching the returned
`SRV` records).

For `A` and `AAAA` queries, the reply contains the domain name and the IP
address of the results.

The domain name MUST match the domain in the query, in order not to be filtered
by intermediate resolvers.

For `SRV` queries, the reply consists of (_virtual hostnames_, port)-tuples.
A virtual hostname is a subdomain of the seed root domain that uniquely
identifies a node in the network.
It is constructed by prepending the `node_id` condition to the seed root domain.

The DNS seed:
  - MAY additionally return the corresponding `A` and `AAAA` records that
  indicate the IP address for the `SRV` entries in the additional section of the
  reply.
- MAY omit these additional records upon detecting a repeated query.
  - Reason: due to the large size of the resulting reply, the reply may be
  dropped by intermediate resolvers.
- if no entries match all the conditions:
  - MUST return an empty reply.

## Policies

The DNS seed:
  - MUST NOT return replies with a TTL less than 60 seconds.
  - MAY filter nodes from its local views for various reasons, including faulty
  nodes, flaky nodes, or spam prevention.
  - MUST reply to random queries (i.e. queries to the seed root domain and to
    the `_nodes._tcp.` alias for `SRV` queries) with _random and unbiased_
    samples from the set of all known good nodes, in accordance with the Bitcoin DNS Seed policy<sup>[4](#ref-4)</sup>.

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

	$ dig ln1qwktpe6jxltmpphyl578eax6fcjc2m807qalr76a5gfmx7k9qqfjwy4mctz.lseed.bitcoinstats.com A
	ln1qwktpe6jxltmpphyl578eax6fcjc2m807qalr76a5gfmx7k9qqfjwy4mctz.lseed.bitcoinstats.com. 60 IN A 139.59.143.87

Querying for only IPv4 nodes (`a2`) via seed filtering:

	$dig a2.lseed.bitcoinstats.com SRV
	a2.lseed.bitcoinstats.com. 59	IN	SRV	10 10 9735 ln1q2jy22cg2nckgxttjf8txmamwe9rtw325v4m04ug2dm9sxlrh9cagrrpy86.lseed.bitcoinstats.com.
	a2.lseed.bitcoinstats.com. 59	IN	SRV	10 10 9735 ln1qfrkq32xayuq63anmc2zp5vtd2jxafhdzzudmuws0hvxshtgd2zd7jsqv7f.lseed.bitcoinstats.com.

Querying for only IPv6 nodes (`a4`) supporting Bitcoin (`r0`) via seed filtering:

	$dig r0.a4.lseed.bitcoinstats.com SRV
	r0.a4.lseed.bitcoinstats.com. 59 IN	SRV	10 10 9735 ln1qwx3prnvmxuwsnaqhzwsrrpwy4pjf5m8fv4m8kcjkdvyrzymlcmj5dakwrx.lseed.bitcoinstats.com.
	r0.a4.lseed.bitcoinstats.com. 59 IN	SRV	10 10 9735 ln1qwr7x7q2gvj7kwzzr7urqq9x7mq0lf9xn6svs8dn7q8gu5q4e852znqj3j7.lseed.bitcoinstats.com.

## References
- <a id="ref-1">[RFC 1035 - Domain Names](https://www.ietf.org/rfc/rfc1035.txt)</a>
- <a id="ref-2">[RFC 3596 - DNS Extensions to Support IP Version 6](https://tools.ietf.org/html/rfc3596)</a>
- <a id="ref-3">[RFC 2782 - A DNS RR for specifying the location of services (DNS SRV)](https://www.ietf.org/rfc/rfc2782.txt)</a>
- <a id="ref-4">[Expectations for DNS Seed operators](https://github.com/bitcoin/bitcoin/blob/master/doc/dnsseed-policy.md)</a>

## Authors

[ FIXME: Insert Author List ]

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
