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
| the hub itself | `is_local_proxy_enabled` | the box's own connections, every process except xray and the hub's own overlay engines | `output` marks the packet, it hairpins through `lo`, TPROXY takes it; a packet from the NetBird or EasyTier unit's cgroup is accepted before the mark | the TUN below, with the engines' endpoints kept out | every mode |

The hub opens no proxy port to anyone. What a person sends to the exits is
what these scopes and the direct lists decide. The loopback inbounds
`socks_local_in` and `socks_probe_in` serve the TUN and the measurement, and
nothing about them reaches a person.

The hub-itself scope never diverts what an overlay's WireGuard sends. A
kernel WireGuard device sends from no socket, so no cgroup row names it, and
diverted, its packets reach the peer from the exit node's address, which the
peer's NAT drops. So before the mark, `output` returns every packet that
already carries a mark, which only another subsystem sets there, NetBird's
`0x1bd00` included, and every UDP packet from NetBird's peer port, the
engine table's `peer_port`, for a device that sets no mark. EasyTier sends
from its own process in userspace, so its cgroup row covers it; a kernel
device of its own would need its port returned the same way.

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
that has to stay out: every exit node's address, every direct resolver, the
reference host, and everything the running overlay engines talk to, which
is their servers as the engines report them, EasyTier's console and its
peer-resolve host, and every peer endpoint the engines hold now; a name
among them is resolved by the direct resolver, and by the system's when that
one has no answer. The engines' endpoints change as peers come and go, so
the keeper reads them again on every tick (`netbird status --json`,
`easytier-cli peer`) and adds and withdraws host routes to match; the first
packets to a peer the engines did not name yet may still cross the exit. On
every system the hub's own engines never go through xray: through xray a
tunnel's handshakes leave from the exit's address and its peers see two
addresses for one machine. On Linux the output chain names an engine's
cgroup only while its unit runs, since nft refuses a cgroup that does not
exist and takes a new one's id only when it loads, and the panel loads the
ruleset again within half a minute of a unit starting; until then the
engine's first packets may still cross the exit. The local networks
need no route, since the link's own route is longer than a half. xray's
`direct` and node outbounds are bound to the uplink with
`sockopt.interface`, so a connection the split sends direct never enters
the TUN; on Linux the egress mark does that work. The probe round's own
sockets that leave past xray are bound to the same uplink: a host route
covers the one address the hub's lookup returned, and the reference host's
addresses rotate ("The two measurements"). On macOS the hub also adds
the uplink's default route scoped to the uplink (`route add -ifscope`): a
socket bound to an interface is routed by that interface's own routes, and
without the scoped default a bound outbound or socket has no route to any
address the halves cover. The device is `utun225`
on macOS and the adapter `neutrino_tun` on Windows, with a /30 from the
benchmark range of RFC 2544.
The routes are the machine's, so with the overlay scope on alone the box's
own traffic enters the TUN as well: those systems have no routing by
source interface. The scope then reads `hub`, beside `overlay` while an
exposed overlay runs.

With both scopes off there is no TUN device and no route. When xray stops,
the supervisor stops `tun2socks` and withdraws the route, so the machine's
traffic leaves direct rather than into a device nothing reads. The overlay
scope there turns IP forwarding on for the overlay interfaces, and a member
whose exit this box is follows the same default route into the TUN.

The rendered xray configuration on those systems has no `tproxy_in`
inbound and no `sockopt.mark` on any outbound. `socks_probe_in`,
`socks_local_in`, `api_in`, the balancer, the geodata and the exit measurement
are the same on every system.

The overlay interface of EasyTier in console mode is the one holding the
console network's address, found at run time;
[network.md](network.md) says how.

Off, a forwarded scope is forwarded and masqueraded like any router's. The
firewall's `input` chain accepts what TPROXY diverted from any served
network, exposed or not: the mark is set on the way in and on nothing else.

Destinations inside `reserved_v4` (private, link-local, loopback, multicast)
leave undiverted, whatever the scope.

One more listener reaches xray outside every scope: `socks_probe_in`, on
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
covers everything. The member's traffic then leaves through the box's own
uplink, or through the exit nodes with `is_overlay_proxy_enabled` on.

The hub builds no gateway feature for overlays.

## What setup writes

Setup writes the scopes from the proxy screen's answers, on the terminal and
in the browser alike.

| Mode | Exit nodes given | The hub's own traffic | With that answer off |
| --- | --- | --- | --- |
| `router`, `one_arm_router`, `side_gateway` | the served networks' scope on | asked, off by default | the served networks' scope alone |
| `server` | nothing by themselves: no network is served | asked, on by default | the nodes are saved, every scope is off, and the review and the status strip say the proxy is not used |

An answers document states `is_local` itself, and false when it names none,
so a document that gives a server nodes alone turns no scope on. On macOS and
Windows the answer sets the overlay scope as well, since one TUN carries both.
The **Proxy** page turns any scope on or off later.

## A configuration from an earlier build

A `routing.json` written by 0.5 or by an earlier 0.6 build may hold
`socks_ports`. It loads with no error and nothing reads the key. A save on the
**Proxy** page drops it, and the other writes of that file keep it. A backup
that holds it restores the same way.

A Linux package's script runs `nhub apply` and so a routing pass. The macOS and
Windows packages run none, so the ports stay open until the next pass. The
panel's address sample runs one when the box's networks differ from the last
pass's record. A hub of 0.5 has no such record, so the first sample, within half
a minute of the panel's start, runs one. A pass restarts xray with no such
inbound and closes what those ports opened:

| System | How |
| --- | --- |
| Linux | the nftables ruleset and firewalld's rich rules are rendered with no such port, and firewalld loses every rule of the hub's it no longer renders |
| Windows | every `neutrino_hub_*` rule no purpose names is removed, `neutrino_hub_socks_<port>_<protocol>` and its `_link` rule among them |
| macOS | the pf anchor is rendered with no such port, and `xray` goes from the application firewall's list |

An uninstall removes the same rules by the same prefix and takes `xray` off
the same list, whether a routing pass ran first or not.

An answers document that still names `socks_proxy_port`,
`is_socks_direct_enabled` or `socks_direct_port` reads as if it did not.
`wizard.from_document` refuses every other key it does not know.

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

The round's sockets that leave past xray are the reference fetch, the direct
resolver's query for a name, and the connect to a node's port. On Linux each
carries the egress mark. On Windows and macOS, while a TUN scope is on, each
is bound to the uplink xray's outbounds are bound to: `IP_UNICAST_IF` with
the interface's index in network byte order on Windows, `IP_BOUND_IF` with
its index on macOS. The reference host can answer a different address on
each lookup: `www.msftconnecttest.com` sits on a CDN that rotates them. The
hub's host route covers only the address its own lookup returned, so the
fetch's own lookup can land on an address with no route, enter the TUN and
leave by the exit. A route per address cannot follow a name whose addresses
change, so the socket is bound to the uplink, as the egress mark keeps it out
on Linux. The host routes stay as they are.

### A failed dial

A failed dial to the pinned exit starts a measurement of that exit at once,
between two rounds. xray writes a failed dial only at log level `info`, as one
line that names the address it dialed:

```
[Info] [1602768036] app/proxyman/outbound: app/proxyman/outbound: failed to process outbound traffic > proxy/shadowsocks: failed to find an available destination > common/retry: [dial tcp 192.168.122.167:5800: connect: connection refused] > common/retry: all retry attempts failed
```

| Rule | Reason |
| --- | --- |
| xray logs at `info`. On Linux `nhub run --only-xray` runs xray as its child and writes on every line xray writes, except the lines of `info` and `debug`. A failed dial is the one `info` line it keeps, at most once in ten seconds for each address. | At `warning`, xray 26.3.27 wrote nothing when a dial to a dead exit failed. At `info` it writes four or five lines for every connection, which the journal would keep. |
| Outside Linux the child's log file takes every line xray writes, and the hub's one service rotates it. | The file is bounded at four files of 8 MiB. |
| The panel follows that log: `journalctl -f` of the xray unit on Linux, the child's log file elsewhere. | |
| A failed dial to the pinned exit's address and port starts one measurement of that exit while its latest sample succeeded and no such measurement runs. A node named by a host name matches on its port alone. The measurement is a Test of that node, its second measurement included. | A failed dial is a hint: one refused connection says nothing about the exit, and once the exit is marked failed a failed dial adds nothing. |
| Only the measurement marks the exit failed. A failed dial whose measurement succeeds changes nothing. | |
| The round every `balancer.probe_interval_s` seconds stays as it is. | It measures every node and brings a failed exit back. |

Measured on the lab hub: with the exit's xray stopped, the hub's own traffic
stopped at once, and the status strip turned warn 63 seconds later, at the
next round.

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
stands where it is, except an override at `direct`: it moves to the first
enabled node xray carries, so the traffic sent to the proxy fails. Measured on
the lab hub: the fallback turned off while every exit was down left `direct`
pinned, and the hub's own requests kept leaving through the uplink.

`/var/lib/neutrino/hub/xray_node_health.json` holds the samples, so a panel
restart and an xray restart both keep them. After an apply restarts xray, the
hub sets the override again within a second.

## Where names resolve

Names resolve in two layers. The network's resolvers are the machine's and
its served networks' wherever no proxy scope covers the traffic. The proxy's
resolvers decide only for traffic a scope covers; they are an override, and
an edition built without the proxy has the first layer alone.

**The network's resolvers** belong to the uplink and live in
`config/router/`. An uplink that takes its address by DHCP uses the
resolvers its lease names. A static uplink lists its own under its address,
prefix and gateway, one row each. With several uplinks, each one's resolvers
are used in the uplinks' order of priority. When an uplink names none, two
built-in fallbacks answer: `223.5.5.5` and `119.29.29.29`. dnsmasq forwards <!-- scan: allow -->
to these.

**The proxy's resolvers** are two lists in `config/xray/routing.json`, one
row each on the Proxy page: `remote_dns`, asked through the exit for names
whose traffic goes through it, and `direct_dns`, asked out the uplink for
names whose traffic stays direct. An empty `direct_dns` means the network's
resolvers. A file written before the lists holds one address under
`direct_dns`: it reads as a list of that address, and as an empty list when
the address is the former default `223.5.5.5`.

Resolution is where a proxy loops on itself, so every lookup has one
assigned resolver. "Direct" in the table is `direct_dns`, or the network's
resolvers while that list is empty.

| Lookup | Resolver | Path |
| --- | --- | --- |
| an exit node's own name | direct | xray's resolver, out the uplink, under the egress mark |
| the hub's probe host | direct | the same |
| the hub's connect measurement | direct | a plain A query from the hub, under the egress mark |
| a served network's names, LAN scope on | the split below | dnsmasq → xray `dns_in` → `dns_out` → xray's resolver |
| a served network's names, LAN scope off | the network's resolvers | dnsmasq → the uplink |
| the hub's own names | dnsmasq | the row above that matches; with the hub scope on the query to a direct resolver is diverted like any other |
| the names xray resolves for the split | direct for `direct_domains`, `remote_dns` otherwise | the query to `remote_dns` follows the balancer |

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
| every enabled exit node down while the scope reads `lan`, `overlay`, `hub` or several | the **Dashboard** and the **Proxy** page show `ui.proxy.dead_exits`, or `ui.proxy.dead_exits_fallback` while traffic falls back; a scope reading `off` or `unused` sends nothing to the exits and shows no notice |
| the frame that first shows every enabled exit node down, or the `direct` exit pinned, while a scope takes traffic | the status strip's proxy chip and the **Proxy** page's badges turn warn and read `<scope> → state.exit_down_cut` while the fallback is off, `<scope> → state.exit_down_direct` while traffic falls back |
| the exit node goes down | the first failed dial through it starts a measurement at once ("A failed dial"); the hub measures the failure twice, then overrides the balancer with the next node by score |
| a node other than the exit goes down | the hub records the failure and drops that node from the candidates |
| the panel process stops | the override xray holds stays in place; a restart of xray drops it and `roundRobin` takes over |
| a node whose newest measurement failed at the last apply | the rendered balancer's selector leaves it out, unless every node failed, which keeps them all; this matters only between an xray restart and the hub's next override |
| hub scope on | the hub's updates, package installs and overlay management traffic go through the exit; a dead exit takes them with it |
| xray stops on macOS or Windows while a TUN scope is on | the supervisor stops `tun2socks` and withdraws the route; the machine's traffic leaves direct until xray is back |
| an exit named by a hostname that `direct_dns` cannot resolve | the node is unreachable to the probe and to xray alike, and reads so on the Proxy page |
| the geoip split on | names in `direct_domains` and addresses in `direct_ips` leave through the uplink whatever the scope |
