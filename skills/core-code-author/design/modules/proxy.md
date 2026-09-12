# The proxy the hub runs

The proxy is one xray process on the hub, a set of exit nodes it balances
across, and three switches that each send one scope of traffic to those
exits. The firewall decides what reaches xray, dnsmasq decides where the
served networks' names resolve, and xray decides which exit a connection
takes. This page states each of those decisions and what follows from it.

## Scopes

A scope is one source of traffic and one switch in `config/xray/routing.json`.
Each stands alone; every one needs an enabled exit node, and with none enabled
the panel writes all of them off.

| Scope | Switch | What reaches xray | How |
| --- | --- | --- | --- |
| served networks | `is_proxy_enabled` | every TCP and UDP connection forwarded from a LAN interface to a public address | `prerouting` TPROXY on the LAN interfaces |
| overlays | `is_overlay_proxy_enabled` | the same, forwarded from an exposed overlay interface | the overlay interface joins the TPROXY set |
| the hub itself | `is_local_proxy_enabled` | the box's own connections, every process except xray | `output` marks the packet, it hairpins through `lo`, TPROXY takes it |
| SOCKS ports | `socks_ports[].is_proxied` | what an application is pointed at | a SOCKS inbound per port |

Off, a forwarded scope is forwarded and masqueraded like any router's. The
firewall's `input` chain accepts what TPROXY diverted from any served
network, exposed or not: the mark is set on the way in and on nothing else.

Destinations inside `reserved_v4` (private, link-local, loopback, multicast)
are never diverted, whatever the scope.

## What an overlay member can and cannot do

An overlay interface is a WireGuard tunnel: it has no ARP, and a packet
enters it only when a peer's AllowedIPs covers the destination. An overlay
member that sets this box as its gateway sends its internet traffic into a
tunnel that drops it. The overlay itself has to name this box an exit node
(NetBird: a network route for `0.0.0.0/0` with this box as the routing
peer; EasyTier: this box published as an exit node). NetBird then adds its
own forward and masquerade rules for that route, and the member's AllowedIPs
covers everything.

| The member wants | Route | Exit it gets |
| --- | --- | --- |
| all traffic through the box | the overlay names the box an exit node | the box's own uplink, or the exit nodes with `is_overlay_proxy_enabled` |
| one application through the box | a SOCKS port over the overlay | the port's own setting: the uplink or the exit nodes |

The hub builds no gateway feature for overlays. The SOCKS port over the
overlay is the case a laptop away from home has.

## Exit selection

Every enabled node with a readable secret is an outbound tagged `node_<id>`,
and the balancer `proxy_balance` selects among them by
`config/xray/nodes.json`'s `balancer.strategy`.

| Strategy | Picks | Needs the observatory |
| --- | --- | --- |
| `leastPing` | the alive node with the lowest measured delay | yes |
| `roundRobin`, `random` | in turn, or at random, alive or not | only with the direct fallback |

The observatory fetches `balancer.probe_url` through every node at once,
every `balancer.probe_interval_s` seconds, in xray's burst form: the
sequential form sleeps the interval between one node and the next, and with
six nodes notices a dead one six intervals later. A node whose fetch fails
is not alive and `leastPing` skips it within one interval. With no alive
node `leastPing` names nothing, and xray sends the connection to the first
outbound; with `is_direct_fallback_enabled` it sends it out the uplink
instead.

The panel's own probe is separate: a TCP connect to each node's port every
30 seconds, under xray's egress mark. It is the delay the Proxy page shows
and the liveness the status strip reads; it does not choose the exit.

## Where names resolve

Resolution is where a proxy loops on itself, so every lookup has one
assigned resolver.

| Lookup | Resolver | Path |
| --- | --- | --- |
| an exit node's own name | `direct_dns` | xray's resolver, out the uplink, under the egress mark |
| the observatory's probe host | `direct_dns` | the same |
| the panel's node probe | `direct_dns` | a plain A query from the hub, under the egress mark |
| a served network's names, LAN scope on | `remote_dns` | dnsmasq → xray `dns_in` → the balancer → the exit |
| a served network's names, LAN scope off | `direct_dns` | dnsmasq → the uplink |
| the hub's own names | dnsmasq | the row above that matches; with the hub scope on the query to `direct_dns` is diverted like any other |
| the names xray resolves for the split | `direct_dns` for `direct_domains`, `remote_dns` otherwise | the query to `remote_dns` follows the balancer |

The first three are the proxy's own lookups: a lookup for an exit's address
that goes through an exit waits on its own answer. They take no switch into
account. Every other lookup follows the scope its traffic is in, which is
what the hub scope's description promises: with it on, the box's own names
resolve at the exit.

An overlay member's names are its own resolver's: dnsmasq serves the served
networks only, and the member's query to a public resolver is diverted like
any other connection when the overlay scope is on.

The direct resolver's query is one packet per name: xray asks for A records
only, and a NAT router in front of the uplink was measured dropping the
second of two queries sent at once on a fresh UDP flow.

NetBird puts its own resolver in front of `/etc/resolv.conf` and forwards
every name outside its domain to the servers in the copy it kept of the
original file. On such a box the hub writes its resolver into that copy, so
the box resolves at dnsmasq behind NetBird's resolver.

## Consequences

| State | Effect |
| --- | --- |
| every exit node down, direct fallback off | forwarded and hub-scope traffic fails, and so do the served networks' names; the panel and the proxy's own lookups keep working |
| every exit node down, direct fallback on | that traffic leaves through the uplink; dnsmasq asks `direct_dns` after xray does not answer |
| one exit node down under `leastPing` | the observatory marks it dead within one probe interval and the balancer skips it |
| one exit node down under `roundRobin` | every n-th connection fails |
| hub scope on | the hub's updates, package installs and overlay management traffic go through the exit; a dead exit takes them with it |
| an exit named by a hostname that `direct_dns` cannot resolve | the node is unreachable to the probe and to xray alike, and reads so on the Proxy page |
| the geoip split on | names in `direct_domains` and addresses in `direct_ips` leave through the uplink whatever the scope |
