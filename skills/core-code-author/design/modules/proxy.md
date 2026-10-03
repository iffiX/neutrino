# The proxy the hub runs

The proxy is one xray process on the hub, a set of exit nodes, and three
switches that each send one scope of traffic to those exits. The firewall
states what reaches xray, dnsmasq states where the served networks' names
resolve, and the hub states which exit a connection takes. This page holds
each of those rules and what follows from it.

## Scopes

A scope is one source of traffic and one switch in `config/xray/routing.json`.
Each stands alone; every one needs an enabled exit node, and with none enabled
the panel writes all of them off.

| Scope | Switch | What reaches xray | How on Linux | How on macOS and Windows | Modes |
| --- | --- | --- | --- | --- | --- |
| served networks | `is_proxy_enabled` | every TCP and UDP connection forwarded from a LAN interface to a public address | `prerouting` TPROXY on the LAN interfaces | no such scope | router and side_gateway; the switch is not drawn in server mode |
| overlays | `is_overlay_proxy_enabled` | the same, forwarded from an exposed interface of any running overlay | every running overlay's exposed interfaces join the TPROXY set, NetBird's and EasyTier's alike when both run | the TUN below, with forwarding on the overlay interfaces | every mode |
| the hub itself | `is_local_proxy_enabled` | the box's own connections, every process except xray | `output` marks the packet, it hairpins through `lo`, TPROXY takes it | the TUN below | every mode |
| SOCKS ports | `socks_ports[].is_proxied` | what an application is pointed at | a SOCKS inbound per port | the same | every mode |

### The TUN on macOS and Windows

Those systems have no nftables, so the two scopes that divert the machine's
own packets there go through a TUN device. `tun2socks` runs as a child of
the supervising service ([../architecture.md](../architecture.md)) while
either scope is on and xray runs. It owns one TUN device (`utun` on macOS,
a wintun adapter on Windows) and hands every TCP connection and UDP flow
that enters it to `socks_local_in`, a SOCKS inbound of xray's on loopback
with sniffing on, so the domain rules of the split apply as they do to
`tproxy_in`. The hub routes the two halves of the IPv4 space (`0.0.0.0/1`
and its upper twin) at the device, which win over the uplink's default route without touching
it, and keeps a host route through the uplink's gateway for every address
that has to stay out: every exit node's address, `direct_dns`, the
reference host, and the servers of the running overlays. The local networks
need no route, since the link's own route is longer than a half. xray's
`direct` and node outbounds are bound to the uplink with
`sockopt.interface`, so a connection the split sends direct never enters
the TUN; on Linux the egress mark does that work. The device is `utun225`
on macOS and the adapter `neutrino_tun` on Windows, with a /30 from the
benchmark range of RFC 2544.
The routes are the machine's, so with the overlay scope on alone the box's
own traffic enters the TUN as well: those systems have no routing by
source interface.

With both scopes off there is no TUN device and no route. When xray stops,
the supervisor stops `tun2socks` and withdraws the route, so the machine's
traffic leaves direct rather than into a device nothing reads. The overlay
scope there turns IP forwarding on for the overlay interfaces, and a member
whose exit this box is follows the same default route into the TUN.

The rendered xray configuration on those systems has no `tproxy_in`
inbound and no `sockopt.mark` on any outbound. The SOCKS ports,
`socks_probe_in`, `socks_local_in`, `api_in`, the balancer, the geodata and
the exit measurement are the same on every system.

The overlay interface of EasyTier in console mode is the one holding the
console network's address, found at run time;
[network.md](network.md) says how.

Off, a forwarded scope is forwarded and masqueraded like any router's. The
firewall's `input` chain accepts what TPROXY diverted from any served
network, exposed or not: the mark is set on the way in and on nothing else.

Destinations inside `reserved_v4` (private, link-local, loopback, multicast)
leave undiverted, whatever the scope.

A fourth listener reaches xray outside every scope: `socks_probe_in`, on
loopback, which carries the hub's own measurement of each node. "Exit
selection" holds it.

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

Every node with a readable secret is an outbound tagged `node_<id>`, switched
on or off. The hub picks one of them and sets it as the balancer's override
with `xray api bo`. `is_enabled` states whether a node is eligible for that
pick, and nothing else.

The rendered balancer `proxy_balance` holds `roundRobin` over the eligible
tags. It applies in the seconds between an xray restart and the hub's next
override, and it reads no measurement from xray.

### The two measurements

Every `balancer.probe_interval_s` seconds the hub measures every node,
switched on or off:

| Number | How the hub takes it | What it states |
| --- | --- | --- |
| `connect_ms` | a timed TCP connect to the node's address and port, under the egress mark | whether the node's port accepts a connection |
| `request_ms` | one HTTP request to `balancer.probe_url` through that node | what one connection through this node costs |

The request reaches the node through `socks_probe_in`, a SOCKS listener on
loopback with one account per node. Each account takes the name of that node's
outbound tag, and one routing rule per account sends its traffic out that
node. Those rules sit ahead of every rule that matches on a destination, so a
probe URL inside `geoip:cn` still leaves through the exit.

Each round also fetches `balancer.reference_url` out the uplink, past xray.
The hub records a node's failure against that node when the reference
succeeded in the same round. When both fail, the round reports the uplink as
unreachable and records nothing. The reference URL answers without the proxy,
so it names a different host from the probe URL.

### The score and the switch

Each node holds its last twenty samples, none older than an hour. They give a
success rate, a median delay and a jitter, and one score orders the nodes:

```
score_ms = median_ms + jitter_ms + 2000 * (1 - success_rate)
```

A node is a candidate while it is switched on, present in the running xray,
and its latest sample succeeded. The hub moves the exit at once when the
current one stops being a candidate.

Moving off a node that still answers takes three conditions together. The
challenger scores a fifth lower, it scores thirty milliseconds lower, and the
current exit has held for five minutes. A failure of the pinned node is
measured a second time in the same round before it counts.

With no candidate and `is_direct_fallback_enabled` on, the hub overrides the
balancer with `direct`. With no candidate and the fallback off, the override
stands where it is.

`/var/lib/neutrino/hub/xray_node_health.json` holds the samples, so a panel
restart and an xray restart both keep them. After an apply restarts xray, the
hub sets the override again within a second.

## Where names resolve

Resolution is where a proxy loops on itself, so every lookup has one
assigned resolver.

| Lookup | Resolver | Path |
| --- | --- | --- |
| an exit node's own name | `direct_dns` | xray's resolver, out the uplink, under the egress mark |
| the hub's probe host | `direct_dns` | the same |
| the hub's connect measurement | `direct_dns` | a plain A query from the hub, under the egress mark |
| a served network's names, LAN scope on | the split below | dnsmasq → xray `dns_in` → `dns_out` → xray's resolver |
| a served network's names, LAN scope off | `direct_dns` | dnsmasq → the uplink |
| the hub's own names | dnsmasq | the row above that matches; with the hub scope on the query to `direct_dns` is diverted like any other |
| the names xray resolves for the split | `direct_dns` for `direct_domains`, `remote_dns` otherwise | the query to `remote_dns` follows the balancer |

The first three are the proxy's own lookups: a lookup for an exit's address
that goes through an exit waits on its own answer. They take no switch into
account. Every other lookup follows the scope its traffic is in, which is
what the hub scope's description promises: with it on, the box's own names
resolve at the exit.

On macOS and Windows no dnsmasq runs and no socket is marked. The hub's own
names resolve with the system's resolver; with the hub scope on, that
resolver's queries enter the TUN like any other packet and the split
decides where they resolve. The measurements and the lookup of an exit's
own name leave by the direct routes the TUN section names.

An overlay member's names are its own resolver's: dnsmasq serves the served
networks only, and the member's query to a public resolver is diverted like
any other connection when the overlay scope is on.

The direct resolver's query is one packet per name: xray asks for A records
only, and a NAT router in front of the uplink was measured dropping the
second of two queries sent at once on a fresh UDP flow.

The hub runs its overlays for addresses only. NetBird's DNS management is
off on the hub, `--disable-dns` on every `netbird up`, and EasyTier's is
never turned on, so the box's own resolver stays its dnsmasq whatever the
served network's address becomes, and the overlay's own names are not
resolved on the hub. An overlay's DNS is a member's tool: a client that
roams names the hub as its exit and takes the overlay's DNS to reach the
networks behind the hub, and the hub takes no DNS from the overlay. Measured
on NetBird 0.78.1: its forwarder reads the upstream from the copy it keeps
of the original file once, at start, so a hub whose served network changed
address resolved nothing until the daemon restarted.

## Consequences

| State | Effect |
| --- | --- |
| every exit node down, direct fallback off | forwarded and hub-scope traffic fails, and so do the served networks' names; the panel and the proxy's own lookups keep working |
| every exit node down, direct fallback on | that traffic leaves through the uplink; dnsmasq asks `direct_dns` after xray does not answer |
| the exit node goes down | the hub measures the failure twice, then overrides the balancer with the next node by score |
| a node other than the exit goes down | the hub records the failure and drops that node from the candidates |
| the panel process stops | the override xray holds stays in place; a restart of xray drops it and `roundRobin` takes over |
| a node whose newest measurement failed at the last apply | the rendered balancer's selector leaves it out, unless every node failed, which keeps them all; this matters only between an xray restart and the hub's next override |
| hub scope on | the hub's updates, package installs and overlay management traffic go through the exit; a dead exit takes them with it |
| xray stops on macOS or Windows while a TUN scope is on | the supervisor stops `tun2socks` and withdraws the route; the machine's traffic leaves direct until xray is back |
| an exit named by a hostname that `direct_dns` cannot resolve | the node is unreachable to the probe and to xray alike, and reads so on the Proxy page |
| the geoip split on | names in `direct_domains` and addresses in `direct_ips` leave through the uplink whatever the scope |
