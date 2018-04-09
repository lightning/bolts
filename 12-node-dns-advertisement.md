# BOLT #12: Node Advertisement via DNS Subdomains

This specification describes a node advertisement standard based on the
Domain Name System (DNS). Its purpose is to provide a common way to advertise
nodes officially operated by a given domain name.

A domain will advertise one or more nodes by responding to a DNS query of type
`SRV` to `_lightning._tcp.example.com` with one or more records of nodes to connect to.

This can be to connect and gossip with the node, and/or to open a channel to the node
for the purposes of future payments.

This BOLT is separate from [BOLT #10](10-dns-bootstrap.md) as the purpose is to
look up Lightning nodes for a specific domain name, not bootstrap connections to
the Lightning Network.

# DNS Records

A client MUST use DNS seeds as defined in BOLT #10 to bootstrap new nodes, and 
clients MUST NOT use DNS records as defined in this BOLT for bootstrapping purposes.

A client MAY issue a `SRV` query for `_lightning._tcp.example.com`.  The DNS server
SHOULD respond with a record containing a list of one or more nodes they intend to advertise.
The target record MUST be a `SRV` record that resolves to an `A` or `AAAA` record
as per RFC2782<sup>[1](#ref-1)</sup>.  The `SRV` record MUST be a sub-domain
of the root domain that the `bech32` encoded `node_id` of the corresponding node
for the record.

The client SHOULD respect the priority of targets presented per RFC2782.
The `SRV` MAY be more than one sub-domain deep, for example to provide a
human-identifiable intermediary sub-domain.

If intermediary sub-domains are used, the client SHOULD allow the user to choose
which nodes to connect to.

The client MAY fall-back to lower priority records for the same sub-domain. The
client SHOULD NOT automatically attempt to connect to another node with a different
intermediary sub-domain.

# Examples

Below is a record with multiple advertised nodes:

```
$ dig _lightning._tcp.example.com SRV

;; ANSWER SECTION:
_lightning._tcp.example.com. 300 IN     SRV     10 1 9735 ln1qwa2wzyxmysq4u8lh5leuxxevqyrx8y9s3ttzm36ndq7wdwxyz8777q28ls.example.com.
_lightning._tcp.example.com. 300 IN     SRV     5 1 9735 ln1qvxsm6rcnr7wtsfktk5j8990wyr307u705u4dkht469ef94kxrsfwjf5e6m.example.com.

;; ADDITIONAL SECTION:
ln1qwa2wzyxmysq4u8lh5leuxxevqyrx8y9s3ttzm36ndq7wdwxyz8777q28ls.example.com.       300     IN      A       198.51.100.2
ln1qwa2wzyxmysq4u8lh5leuxxevqyrx8y9s3ttzm36ndq7wdwxyz8777q28ls.example.com.       300     IN      AAAA    2001:db8::2
ln1qvxsm6rcnr7wtsfktk5j8990wyr307u705u4dkht469ef94kxrsfwjf5e6m.example.com.       300     IN      A       198.51.100.1
ln1qvxsm6rcnr7wtsfktk5j8990wyr307u705u4dkht469ef94kxrsfwjf5e6m.example.com.       300     IN      AAAA    2001:db8::1
```

A client will receive this record, evaluate the priority and choose to connect to
`ln1qvxsm6rcnr7wtsfktk5j8990wyr307u705u4dkht469ef94kxrsfwjf5e6m.example.com.`. The
client will then decode the `bech32` `node_id` and connect to the node at
`198.51.100.1` on port `9735`.

_______________________________________________________________

Here is a more advanced record with a human readable intermediate sub-domain:

```
$ dig _lightning._tcp.example.com SRV

;; ANSWER SECTION:
_lightning._tcp.example.com. 300 IN     SRV     10 1 9735 ln1qwa2wzyxmysq4u8lh5leuxxevqyrx8y9s3ttzm36ndq7wdwxyz8777q28ls.clothing.example.com.
_lightning._tcp.example.com. 300 IN     SRV     10 1 9735 ln1qvxsm6rcnr7wtsfktk5j8990wyr307u705u4dkht469ef94kxrsfwjf5e6m.ebooks.example.com.

;; ADDITIONAL SECTION:
ln1qwa2wzyxmysq4u8lh5leuxxevqyrx8y9s3ttzm36ndq7wdwxyz8777q28ls.clothing.example.com.       300     IN      A       198.51.100.2
ln1qwa2wzyxmysq4u8lh5leuxxevqyrx8y9s3ttzm36ndq7wdwxyz8777q28ls.clothing.example.com.       300     IN      AAAA    2001:db8::2
ln1qvxsm6rcnr7wtsfktk5j8990wyr307u705u4dkht469ef94kxrsfwjf5e6m.ebooks.example.com.       300     IN      A       198.51.100.1
ln1qvxsm6rcnr7wtsfktk5j8990wyr307u705u4dkht469ef94kxrsfwjf5e6m.ebooks.example.com.       300     IN      AAAA    2001:db8::1
```

A client will evaluate this record and present the user with the option of
connecting to either the `clothing` or the `ebooks` node.  The client will then
connect to the highest priority record for the selected intermediary sub-domain.


## References
- <a id="ref-1">[RFC 2782 - A DNS RR for specifying the location of services (DNS SRV)](https://www.ietf.org/rfc/rfc2782.txt)</a>

# Authors

[ FIXME: Authors ]

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
