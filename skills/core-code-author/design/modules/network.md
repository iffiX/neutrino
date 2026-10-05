# The network the hub builds

The hub is a minimal routing frontend. It decides what a machine's interfaces,
routes and name service should be, and it drives three engines that already
exist on every Linux to make that true: `ip` for addressing and routing,
`wpa_supplicant` for joining a wireless network, `dhcpcd` for a lease. It does
not build on NetworkManager, netplan or systemd-networkd, and this page is why,
what it does instead, and what it refuses to touch.

## The person this is for decides the design

Whoever sets this box up is a developer, not a network engineer. Somebody who
has configured OpenWrt and a managed switch is still not a network engineer,
and still does not want to spend an evening on it. So:

- **Roles, not routing.** The wizard asks what the machine is *for* — a
  server, a router, a side gateway — and works out the interfaces, the routes,
  the NAT and the DNS from that. There is no configuration language to learn
  and none to invent.
- **Three modes are the whole vocabulary.** Anything a mode cannot express is
  a thing this does not do, on purpose.
- **The defaults have to be right**, because most people will press through
  them. That is why the address a port is offered is the one it already has,
  and why the mode a machine cannot be is not on the list.

A configuration surface wide enough to express every network is a surface
nobody in that description can cross.

## Three modes, and which of them addresses the machine

| Mode | Addressing | What the machine is | What the hub owns |
| --- | --- | --- | --- |
| `server` | the machine's own | somebody's machine on the LAN, a desktop or a laptop | **nothing**: no port holds a role, and it answers on the address each already has |
| `side_gateway` | the machine's own | a machine on a network somebody else routes | **nothing**: forwarding, masquerade and DNS are all in our own nftables and dnsmasq |
| `router` | the hub's | this box *is* the router | the network stack |

Three, and `config/router/network.json` stores one of exactly these three.
Linux runs all three. macOS and Windows run `server` alone: there the hub
owns nothing, renders no nftables table, starts no dnsmasq and writes no
route, and the mode list it offers holds `server` and nothing else
([protocol.md](../protocol.md), `NetworkView`).
Router mode is wired two ways and both are supported: the ordinary one, an
uplink port and a served port; and the **one-arm router**, a single trunk
port going out untagged and serving on a VLAN tag of the same wire. The
wizard offers that as a fourth choice because it has different questions to
ask, but what it plans is a router and what it writes says `router` — the
difference is wiring, which the interface panel already describes, and it
ends there.

A machine is wholly one or the other. There is no half-managed state, because
every bug worth having found so far came from sharing an interface with
another manager.

`server` gives no port a role at all, which is what keeps the rest of the
layer from treating it as a router: nothing is served, so dnsmasq answers
nowhere; nothing routes, so the forward chain has no policy to enforce and is
left `accept` — docker, libvirt and whatever else forwards across that machine
are not the hub's to police, and a drop policy there cuts every one of them off
without saying so.

A `server` hub's exposed networks stand where a router's served ones do for
reaching the machines around it: a Wake-on-LAN packet is broadcast on the
network of each exposed interface that holds an IPv4 address, and never on an
overlay, which has no broadcast domain.

**`server` and `side_gateway` touch nothing at all.** No connection is edited,
no manager is stopped, no file outside the hub's own roots is written. A
kernel switch is flipped only for a rule that needs it: `server` forwards
nothing and leaves `ip_forward` alone, while `side_gateway` forwards and asks
for exactly that. `side_gateway`
needs no interface configuration whatsoever: the box already has an address
and a way out — that is how it was reached — and everything it adds is a
forward rule, a masquerade, and a resolver, all of which are the hub's own:

```text
oifname "enp1s0" ip daddr != 192.168.1.0/24 masquerade
```

Masquerade rather than plain forwarding, because a device and the network's
real router are on one subnet: without it the router answers the device
directly, the reply never passes back through the box, and conntrack — which
the proxy interception depends on — never sees the other half of the session.
The `ip daddr !=` guard keeps traffic between the network's own hosts alone.

**`router` owns the stack**, and says so before anything is done. The
mode is stored in `config/router/network.json` and is the first thing the
Network page asks; changing it there re-plans every interface, and taking a
machine over starts from the addresses it already has. Leaving router mode
hands the network back the way a reset does — the managers that were stood
down are started again, and no address is taken off anything.

## Switching shapes, and what each one costs

A box is re-purposed by switching its mode, and every transition is ordinary:
none may strand the box, and each has a cost that is the transition's nature
rather than a defect. What follows is the contract the mode-matrix
integration tests hold the code to.

| Transition | What happens | What breaks, by design |
| --- | --- | --- |
| `server` ↔ `side_gateway` | roles change, addressing does not | leaving `side_gateway`, the machines that named this box as their gateway lose their way out |
| into `router` | the stack is taken over: the machine's manager is stood down, its addresses carried, and a DHCP uplink re-leases under the hub's own client identity | the uplink's address can change with the new lease, and the session that asked comes back on the new one |
| out of `router` | the hand-back: the hub's engines stop, the managers that were stood down start again, no address is taken off anything | the served networks end — their devices lose DHCP, DNS and their gateway, and live out their leases |
| two-arm ↔ one-arm | the LAN moves between a port of its own and a VLAN tag | every LAN device drops and re-leases; on a switch that does not pass tags, the one-arm LAN looks configured and carries nothing |
| one uplink ↔ several | the plan re-ranks, and balance installs or removes the multipath route | connections pinned to an uplink that lost its role break; re-balancing spreads new connections only |

The proxy's switches survive every one of these. They are the person's
answers, not the mode's: what each one *does* follows the mode — the LAN
switch means nothing on a box serving no network, and reads as `unused` on
the strip — and the diversion is re-rendered on every mode apply, so entering
`server` takes the TPROXY rules out of the kernel and returning to `router`
puts them back, with nothing retyped on the Proxy page.

## What answers, and where

Every service this box runs binds every address and settles its own port in
its own tab. What is left to decide is which wires reach them, and that is one
answer per network — `is_exposed` — rather than a port list per network that
would have to be kept in step with what is installed.

```text
iifname { "enp1s0", "wt0" } accept  # everything this box listens on
udp dport { 51820 } accept          # where the overlay's peers knock
```

A served network is exposed by definition — it is where the panel, the leases
and DNS are reached — and an uplink is closed, because remote access arrives
over an overlay or through the relay. Opening an uplink opens *everything*, which is why there is
no "SSH from the WAN" switch: a per-port list on the one interface facing the
internet is a list that gets half right, and the honest control is the whole
interface with what it costs written beside it.

`is_exposed` renders the input chain only: what it decides is which wires
reach a connection to this box's own services. The forward chain is rendered
from the roles, and its `iifname "wt0" accept` carries no `oifname`, so a
packet arriving from the overlay is forwarded anywhere this box routes, a
closed uplink's network included, and postrouting masquerades it on the way
out. The one exception is another overlay: with two running, a chain of its
own, `forward_overlays`, drops what arrives on one overlay's devices and
leaves by the other's ("Two overlays at once" below). Which peers reach which network is the overlay's management plane
(NetBird's routing peer and its network resources): NetBird filters again in
its own table and inserts its own `iifname "wt0" accept` at the top of this
table's input and forward chains. So closing an uplink closes that wire to
this box's own services, and from the overlay the box still answers on that
wire's address, its own address on it included. Read off a running box:

```text
chain input   { policy drop; ... iifname { "wt0", "enp1s0", "wlp3s0" } accept ... }
chain forward { policy drop; ... iifname "wt0" accept ... }
chain postrouting { oifname "enp2s0" masquerade }
```

An overlay is one more row in that same list, and starts open: joining one is
joining your own network, which is the whole reason somebody set it up. It
answers the same single question and gets no matrix of its own, because a
second mental model for one kind of network costs more than the control is
worth. What it does get is the cost of closing it, said before the press: how
many managed devices are reaching this hub across it right now. Closing an
overlay cuts it off rather than going quiet on it, so the box stops answering
there, the served networks stop reaching it, and its peers stop being able to
knock.

Overlays live in `overlays`, beside `interfaces` rather than in it, and are
keyed by provider, one row per engine with `is_enabled` and `is_exposed`. Any
set of engines runs at once, the empty set included, and every rule below is
rendered over the devices of the enabled rows only. A row turned off keeps
its `is_exposed` for the day it is turned on again. A row stored without
`is_enabled`, the 0.4.0 shape, is an enabled one, so a hub upgraded from
0.4.0 runs the one overlay it ran and no other. Both halves of the keying
matter. Switching modes rebuilds the interface
list, and an overlay riding in there would be dropped by a change that has
nothing to do with it; and the device name belongs to the provider, so a
configuration storing `wt0` would render rules for an interface that no longer
exists the day somebody renamed it, matching nothing, silently. A
configuration written before the switch existed reads as one open overlay,
which is exactly what the firewall did unconditionally until then: who can
reach a machine is not a thing to change behind somebody's back.

The firewall names no overlay of its own. A device name or a peer port
written into `nft_renderer.py` is the next overlay's rules being written by
hand, and a test reads the module's source to keep it that way.

EasyTier in console mode is the one provider whose device the hub does not
name: the engine brings up its own, `tun0` on Neutrino. The overlay's
interface is then the one holding the address the engine reports for the
console's network, found at run time by `overlay/ops.py` and handed to the
renderer in place of `easytier`, for the input chain, the forward chain and
the overlay scope alike. Each routing pass records which devices the loaded
ruleset names; every half minute the panel compares the devices found with
that record and runs the pass again when they differ. With no network from
the console yet, the rules name no device for it. The found name is run-time
state and never reaches `config/`.

### An overlay's daemon is a second firewall, and it wins

Rendering the rules does not close an overlay. Measured on a running NetBird
0.77.1 client on 2026-09-07: within ten seconds of any reload it inserts
`iifname "wt0" accept` at the top of whatever input chain it finds, this hub's
`inet neutrino` included, and it keeps its own `ip netbird` table where the
real decision is made — `iifname "wt0" jump netbird-acl-input-rules` followed
by `iifname "wt0" drop`, so the floor is deny and the management plane's
policy is what opens it. A switch that only rendered rules would read closed
and be open.

So closing an overlay tells its daemon too, through
`NetbirdInboundGate`, which sets NetBird's own `BlockInbound`. Three things
about it are what the client does rather than what reads well, and each was
measured rather than assumed:

- **`netbird up` is a no-op while the client is connected.** The session is
  taken down first, exactly as an enrollment does.
- **The flag is sticky.** Leaving `--block-inbound` off keeps whatever was
  stored last, so the value is always stated: `--block-inbound=true|false`.
- **`netbird status --json` does not report it.** The only readable answer is
  the daemon's own state file, named by `active_profile.json` under
  `/var/lib/netbird/`, with the older `/etc/netbird/config.json` still read
  for a box that upgraded. It is read for one reason: setting a value the
  daemon already holds costs a reconnection, and a network apply runs every
  time somebody saves an interface.

Blocked means established and related only. It is not `--disable-firewall`,
which was considered and rejected: NetBird's own rules are what make this box
usable as a routing peer, which is the thing the NetBird page sends people to
the console to set up.

A routing peer's daemon also marks packets. Measured on NetBird 0.78.1 on
2026-09-23: `netbird-mangle-prerouting`, at the mangle priority, sets
`meta mark 0x1bd22` on every new connection whose source is a network the
peer routes, whatever its destination, so that it can masquerade what
leaves through the overlay. The proxy's diversion chain sits at the same
hook and sets mark 1 on the packets it hands to xray, and the policy route
that delivers them locally looks for that mark. Two chains at one priority
run in the order they were registered, which changes whenever either side
reloads its table; with the daemon's chain last, every diverted SYN from the
served Wi-Fi network lost its mark and was dropped, and the network read as
having no internet while the panel on the same box answered. The diversion
chain is therefore rendered at `mangle + 1`: it runs after the daemon's
whatever the order of reloads, and the mark it sets is the one that stands.

`server` and `side_gateway` start with every interface open. That is what the
machine was already doing before the hub arrived, and a machine reached over
SSH that answers on nothing after an install is a machine nobody can reach.

### Outside Linux, the system firewall

macOS and Windows have the same exposure as Linux: one `is_exposed` per
interface and per overlay, drawn on the same panel, with every interface
exposed until somebody closes one. No nftables table exists there, so the
routing pass renders the answer into the system's own firewall:

| System | How | What |
| --- | --- | --- |
| Windows | `New-NetFirewallRule`, one allow rule per purpose named `neutrino_hub_<purpose>`, each scoped with `-InterfaceAlias` to the exposed interfaces; a port change rewrites the rule and an uninstall removes it. The profile's default inbound block is what closes an interface that is not listed. The rules are scoped again whenever the interface set changes, from the pass that follows the overlay devices, so an engine's adapter that comes back under a new name is listed and a dead one is dropped | the panel's HTTP and HTTPS ports, the agent port, the AI gateway's port (CLIProxyAPI's `listen_port`, as `neutrino_hub_ai_gateway`), every SOCKS port, NetBird's UDP port, EasyTier's 11010 over TCP and UDP |
| macOS | `/usr/libexec/ApplicationFirewall/socketfilterfw --add <program>` and `--unblockapp <program>`, since that firewall allows programs rather than ports, and the pf sub-anchor `com.apple/neutrino_hub`, loaded from a file under the state root at each routing pass and when the service starts, which blocks those ports on every interface that is not exposed, the way the agent's `com.apple/neutrino_smb` fences the file share | the programs `nhub`, `xray`, `cli-proxy-api`, `netbird`, `easytier-core`, and the same port list as Windows in the anchor |

A closed overlay's peer port is closed there as on Linux: the Windows rule
is disabled and the pf anchor blocks it on every interface but loopback.
A routing pass there looks up no `xray` account, sets no sysctl, adds no
`ip rule` and loads no nftables table. It still writes
`generated/router_overlay_devices.json` and still runs the NetBird inbound
gate, and `OverlayRouteGuard` reports no conflict.

The network facts come from psutil: `device_addresses()` from
`net_if_addrs()` and `net_if_stats()`, traffic counters from
`net_io_counters(pernic=True)`, listening ports from `net_connections()`,
memory from `virtual_memory()`. The default route is `route -n get default`
on macOS and `Get-NetRoute` on Windows, and the machine id is
`IOPlatformUUID` and the registry's `MachineGuid`. An overlay's device is
still found by its address, `utunN` on macOS and the adapter's name on
Windows. The traffic history and the LAN scan return nothing, and the panel
draws them empty. Linux keeps its `ip -json` path.

## Two overlays at once

NetBird and EasyTier each bring an address range, the routes their peers
publish and a daemon that edits the kernel, and neither knows the other or
the LAN. EasyTier in console mode takes its routes from the console, which
the hub does not control. What keeps the two apart is five rules:

| Rule | Mechanism |
| --- | --- |
| No two networks overlap before an engine starts | Turning an engine on is refused with `overlay_subnet_overlap {title, subnet, conflict}` when its network overlaps the other overlay's or any network this box holds an address on, the served ones included. NetBird's network is `100.64.0.0/10`; EasyTier's is the stored address's network in manual mode and the running instances' in console mode. Saving an EasyTier address while EasyTier runs is checked the same way. |
| A learned route that overlaps is named, and taken away where possible | After every converge step and every half minute, the hub reads the kernel's routes that name an overlay's devices, in every table. A route overlapping one of the box's networks or the other overlay's network is listed on the Overlay page in red. A NetBird route is deselected with `netbird routes deselect`; an EasyTier route is only reported. |
| No default route | A route for `0.0.0.0/0` through an overlay's device is deleted, NetBird is told to deselect it, and the page shows `overlay_default_route_refused`. The hub's way out is its own uplink. |
| No forwarding between overlays | `forward_overlays`, at `filter - 1`, drops every packet entering on one overlay's devices and leaving by another's. It runs ahead of `forward` because NetBird inserts its own `iifname "wt0" accept` at the top of `forward`. |
| The resolver stays the hub's | NetBird runs with `--disable-dns` on every `netbird up`. EasyTier's magic DNS is off unless a flag turns it on: the hub's manual-mode file never does, and in console mode the console's network settings decide it, so Magic DNS stays off there. `/etc/resolv.conf` is written by the hub alone ([proxy.md](proxy.md)). |

The proxy's overlay scope diverts from every running overlay's exposed
devices. With both engines running, NetBird's own policy rules sit beside the
hub's `fwmark` rule at priority 100 for table 100; which of them the kernel
reads first for a packet from each overlay is measured on a running box, not
assumed.

## The ways in from outside

A way in is how a client or an agent away from the hub's LAN reaches the
agent port. The hub offers three: NetBird, EasyTier and the relay. The panel
draws them on one page, **Access** (外部访问 in Chinese), as three cards in
that order; the configuration, the routes and the protocol keep the word
`overlay` ([ui_text.md](../ui_text.md), "Names that are fixed").

| Rule | Reason |
| --- | --- |
| The hub stands on the LAN of the machines it manages and is not placed on a public address. No way in needs an uplink exposed, and from outside a person opens the panel through a client's **Panel** entry. | The hub dials every machine's services on its own LAN for the clients; a hub on a public address is a panel and an agent port open to every scanner on the internet. |
| Every way in reaches the one agent port, and the link's and the state's `urls` hold one address per way in. | A peer tries the set in turn and pins one fingerprint, so a way in adds an address and nothing else. |
| The served networks stay offered as routes on both overlay engines: the NetBird page names them for the routing peer the person sets up in its console, and the EasyTier form lists them to export. The hub withdraws none. | A client reaches a published service as a stream through the hub and needs no route. A route reaches every port of a machine, which is the advanced use the person chooses. |

## The relay, the third way in

The relay is a reverse SSH forward from the hub to a server the person owns,
called the VPS on this page. The hub logs in to the VPS with one SSH key from
the Credentials page and has the VPS's sshd listen on a public port; every
connection to that port reaches the hub's agent port on loopback. TLS and the
fingerprint pin run end to end, so the VPS forwards ciphertext.

`config/overlay/relay.json` holds the relay:

| Key | Holds |
| --- | --- |
| `is_enabled` | whether the relay runs; written by the **Access** page's switch together with the overlay engines' |
| `host` | the VPS's name or address |
| `ssh_port` | its sshd's port, 22 by default |
| `account` | the account the hub logs in as |
| `key_id` | the id of an SSH key on the Credentials page, the same key a device's `ssh.key_id` names |
| `public_port` | the port the VPS listens on for peers, 8443 by default |

The relay is configured when `host`, `account` and `key_id` are set and the
key exists. `host` and `account` reach a command line that runs as root, so a
value that is empty, holds whitespace or starts with `-`, and an `account`
holding `@`, is refused at save.

### What the hub runs

The hub keeps one `ssh` process running while the relay is on and
configured: the unit `neutrino_hub_relay.service` on Linux, and a child of the
supervising service on macOS and Windows. The start line is rendered from
`relay.json`; on Linux it is the drop-in
`/etc/systemd/system/neutrino_hub_relay.service.d/arguments.conf`, and on
macOS and Windows the supervisor holds it as it holds EasyTier's:

```text
ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3
    -o ConnectTimeout=15 -o BatchMode=yes -o IdentitiesOnly=yes
    -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=<state>/relay/known_hosts
    -i <state>/relay/key -p <ssh-port>
    -R 0.0.0.0:<public-port>:127.0.0.1:<agent-port> <account>@<host>
```

`<state>` is the hub's state root ([files.md](../files.md)), `<agent-port>` is
`agent_listen_port`, and the other placeholders are the `relay.json` keys of
the same names. The program is the system's OpenSSH client: `ssh` on
Linux and macOS, `%SystemRoot%\System32\OpenSSH\ssh.exe` on Windows. A process
that exits is started again: by the unit's `RestartSec=10` on Linux, and on
macOS and Windows by the supervisor's backoff, `SYSTEM_CHILD_RESTART_MIN_S` 1
doubled up to `SYSTEM_CHILD_RESTART_MAX_S` 60.

| File | Written | Holds |
| --- | --- | --- |
| `<state>/relay/key` | by the converge step from the vault, mode 0600; deleted when the relay stops | the private key in OpenSSH form, without the passphrase it was stored with |
| `<state>/relay/known_hosts` | by `ssh` on its first connection, mode 0600 | the VPS's host key |

A locked vault leaves the key file unwritten and the relay in `vault_locked`.
A save that changes `host` or `ssh_port` deletes `known_hosts`, so the next
connection records the new server's key. A recorded key that no longer
matches stops every connection, and the card's **Forget host key** deletes
the file.

### The VPS is the person's

The hub runs no command on the VPS and changes nothing there: `-N` opens no
session and `-T` no terminal. The VPS's own setup is the person's: an account
for the forward, `GatewayPorts clientspecified` in its sshd, the key in that
account's `authorized_keys` behind
`restrict,port-forwarding,permitlisten="<public-port>"`, and the public port
open in the provider's firewall. A guide page lists these steps and sends the
person to their provider's terms on forwarded traffic.

### The states

The hub checks the relay from outside. `OVERLAY_RELAY_CHECK_FIRST_S` 5
seconds after the process starts, and every `OVERLAY_RELAY_CHECK_INTERVAL_S`
60 seconds after that, it dials `<host>:<public-port>` itself, completes a
TLS handshake within `OVERLAY_RELAY_CHECK_TIMEOUT_S` 10 seconds, and compares
the certificate's SHA-256 with its own agent certificate's fingerprint. The
check closes after the handshake and sends no request. The three constants
are in `modules/overlay/constants.py`.

| `state` | When |
| --- | --- |
| `disabled` | `is_enabled` is false |
| `not_configured` | on, and `host`, `account` or `key_id` is missing, or the key is gone from the vault |
| `vault_locked` | on and configured, and the vault cannot open the key |
| `connecting` | `ssh` runs and no check has finished since it started |
| `connected` | `ssh` runs and the last check met the hub's own certificate |
| `port_closed` | `ssh` runs and the last check got no answer or another certificate: the VPS's sshd binds loopback only, or a firewall closes the port |
| `auth_failed` | `ssh` exited after writing `Permission denied` |
| `host_key_changed` | `ssh` exited after writing `REMOTE HOST IDENTIFICATION HAS CHANGED` or `Host key verification failed` |
| `forward_refused` | `ssh` exited after writing `remote port forwarding failed`: the sshd refuses the forward, or the port is taken |
| `unreachable` | `ssh` exited for any other reason: no answer, a refused connection, a name that does not resolve, a keepalive left unanswered |

An exit is judged by the last lines `ssh` wrote to its standard error, which
the hub reads from the unit's journal on Linux and from `relay.log` on macOS
and Windows. Between an exit and the next start the state stays the exit's.
The state view carries the last of those lines, or the failed check's
reason, as `last_error`, and the recorded host key's fingerprint in OpenSSH's
own form, `SHA256:<base64>`, as `host_key_fingerprint`.

### The relay's address

While the relay is on and configured, `https://<host>:<public-port>` is the
last member of `urls`, in every link and in every agent's and client's state,
whatever its state; an IPv6 host is written in brackets. A peer tries it like
any other address and pins the same fingerprint. Turning the relay on or off
and saving its settings run the converge step, which pushes every peer its
new `urls`.

A socket through the relay arrives at the agent port from `127.0.0.1`, so its
scope is `link` ([protocol.md](../protocol.md), "The address a caller is
given"). The relay's `client_count` on the **Access** page is the number of
online clients whose socket comes from a loopback address.

## The agent port's limits

The agent port is reached through every way in, and through the relay every
peer arrives from loopback. So no limit on the port is keyed by the peer's
address: each one counts the whole port. The constants are in the hub's
`modules/channel/constants.py`.

| Limit | Constant | At the limit |
| --- | --- | --- |
| a TLS handshake's time | `CHANNEL_TLS_HANDSHAKE_TIMEOUT_S` 10 | the connection is closed |
| the time from accept to an admitted `hello` | `CHANNEL_ADMISSION_TIMEOUT_S` 30 | the connection is closed; a `join` or `leave` request in flight counts toward that time |
| connections that have not passed `hello` | `CHANNEL_UNADMITTED_MAX` 128 | the oldest of them is closed to make room for the new one |
| channel sockets past `hello` | `CHANNEL_SOCKETS_MAX` 512 | the next `hello` is refused `channel_full {limit}`, which a peer retries as it retries any transient refusal |
| failed admissions across the hub | `CHANNEL_ADMISSION_FAILURES_MAX` 30 within `CHANNEL_ADMISSION_WINDOW_S` 60 | `join` pauses, as the next paragraphs state |

`CHANNEL_HELLO_TIMEOUT_S` 10, a socket's time from its upgrade to its
`hello`, keeps the value the channel's timings table gives it
([protocol.md](../protocol.md), "The timings").

A failed admission is a `join` refused `ticket_spent` (an unknown, expired or
spent ticket alike) or `role_mismatch`, a
`hello` refused `binding_unknown` or `hello_invalid`, or a connection closed
by either timeout. A protocol refusal, `channel_full`, a connection closed to
make room and a connection that closes on its own are not counted.

While the window holds `CHANNEL_ADMISSION_FAILURES_MAX` failures, every
`join` is refused 409 `admission_paused {retry_after_s}` before its ticket is
looked up, so no ticket is spent or tested; `retry_after_s` is the time until
the oldest failure leaves the window. A `hello` is judged as always, so every
bound agent and client with a valid token is admitted throughout. The pause
holds back new enrolments only, and a ticket stays valid behind it.

The cap on open handshakes closes no admitted socket. A flood that keeps
`CHANNEL_UNADMITTED_MAX` handshakes open can close a reconnecting peer's
handshake to make room; that peer tries again after its own backoff, and its
binding is untouched.

The numbers sit above a home's own load. One binding holds one socket, so 512
sockets is far above the machines and clients one hub manages. After a hub
restart every peer reconnects within its backoff and each handshake takes
under a second, so 128 open handshakes is more than a home starts at once. A
home's own failures are a removed device's one refused `hello` and a client's
spent link, a few in an hour.

## The converge step

Everything derived from the set of overlays, the network and the proxy is
recomputed by one step, `PanelRuntime.converge_network`, and every writer
calls it: an overlay or the relay switched on or off, the EasyTier settings,
the relay's settings or its forgotten host key, a NetBird join, leave or setup
key, the Network page's writes, the Proxy page's apply,
and the address sampler when an overlay's device or the channel's address set
moved. It holds the router lock throughout, the lock the resident router unit
takes, and runs seven steps in this order:

| Step | What it does |
| --- | --- |
| 1 | The enabled engines start. An engine that was not running is given 20 seconds to hold an address before the step goes on. The relay's key file is written and the relay starts when it is on and configured. |
| 2 | EasyTier is restarted only when the text it would start with, its network file and its unit drop-in, differs from the text on disk, or when it is not running. The relay is restarted by the same test on its own drop-in, and when its key file changed. |
| 3 | `RouterStateController.reconcile_locked()`: the firewall, the policy route, the interfaces. |
| 4 | dnsmasq restarts only when its text changed. |
| 5 | xray restarts only when its text changed or it is not running. |
| 6 | Every online device is handed its state, whose share fence follows the new set. |
| 7 | Every client is handed its state, whose join material and addresses follow the new set. |

On macOS and Windows step 2 compares the start line the supervisor holds in
place of the drop-in, step 3 is the routing pass of "Outside Linux, the
system firewall", and step 4 does not exist.

The engines turned off stop after step 7, and so does the relay when it is
off or no longer configured. A client reaching the hub through one of them is
handed the state that no longer names it while its socket still stands; the hub does not wait for it to answer. A step that fails
stops none of the steps after it, and the failures are raised together at
the end.

`nhub apply` runs the same steps from the command line without the two
pushes. A peer is handed its state when it next reports to a running panel.

## What dnsmasq gives a served network

dnsmasq's upstreams are the network's resolvers, the uplink's own
([proxy.md](proxy.md), "Where names resolve"): the ones a DHCP uplink's
lease names, or the rows a static uplink lists under its address, prefix and
gateway. The lease client still writes no `/etc/resolv.conf`; the hub reads
the resolvers out of the lease and renders them into dnsmasq.

dnsmasq is the DHCP server and the resolver of every served network, and
nothing else on the box answers either. It gets one `dhcp-range` per LAN
whose DHCP is on, and every request is tagged with the interface it arrived
on, so the gateway and resolver options a device receives are that
interface's own address. It also answers `hub.neutrino.internal` with this
box's address on the network the query arrived from, one `interface-name`
per LAN under `localise-queries`, so a device on any served network reaches
the hub by that name whatever the address becomes.

The cache holds 5000 names. An answer, positive or negative, stays in it for
at least 300 seconds, whatever shorter TTL the upstream gave. Most names a
served network asks for resolve at the exit through xray, and a forwarded
query costs one exit round trip where a cached one costs under a millisecond.
The price of the floor is that a name whose address moves is followed up to
five minutes late.

A fixed address is one entry of `static_leases` at the top level of
`network.json`: a MAC, an address and an optional name, rendered as one
`dhcp-host` line after the pools. The address lies in a network that gives
out leases and is neither that network's own address, its broadcast address
nor the gateway's. It can sit inside the dynamic range, which dnsmasq then
keeps for that MAC, and a device holding a dynamic lease moves to its fixed
address at its next renewal. The name, when present, resolves on every
served network. The list is kept at the top level because `dhcp-host` is
global in dnsmasq and the address itself says which network it is in.

## What the proxy may divert

The proxy is one xray process, and the mode decides which traffic can reach
it. Four paths exist, each with its own mechanism, and none of them implies
another:

| Traffic | server | side_gateway | router | Diverted by |
| --- | --- | --- | --- | --- |
| Machines on a served network | — | yes | yes | the prerouting chain, into the TPROXY inbound |
| Overlay members whose exit this box is | yes | yes | yes | the prerouting chain on the overlay interfaces on Linux, behind `is_overlay_proxy_enabled`; the TUN on macOS and Windows |
| This box's own traffic | yes | yes | yes | the output chain on Linux, behind `is_local_proxy_enabled`, which accepts the hub's own NetBird and EasyTier units' packets (matched by their cgroup) before anything is marked; the TUN on macOS and Windows, with the engines' endpoints routed past it ([proxy.md](proxy.md)) |
| Applications pointed at a SOCKS port | yes | yes | yes | the port's own `is_proxied` answer |
| The served networks' DNS | — | yes | yes | dnsmasq's only upstream, the xray DNS inbound |

`server` has no row for a served network because it serves none: no
interface holds a role, so there is no network to divert, and the panel does
not draw that switch in server mode on any system. An overlay member that
named this box its exit is forwarded in every mode, by the overlay's own
rules, so that scope exists in every mode. What the panel reports is a
*scope*: off, unused, ports only, the served networks, the overlays, this
box, or several. On macOS and Windows the overlay scope and the box's own
scope divert through a TUN device rather than a chain
([proxy.md](proxy.md), "The TUN on macOS and Windows").

There is no master switch above these: each scope is its own switch, and
off is all of them off — the honest state for finding out whether the proxy
is what is broken. What every scope shares is the need for an exit: switched
on with no enabled node it renders as off, and the panel writes the switch
back rather than showing a proxy that is not there. The forwarded machines'
DNS follows the forwarded scope, because the queries belong to the traffic.

## When no exit answers

A dead exit is a dead resolver: names resolve at the exit by design, so with
every enabled node unreachable the traffic sent to the proxy fails *and* so
does every name the forwarded machines ask for — including the ones the
direct list would have answered locally. Measured on Debian 12 with one
unreachable node, proxy on: `dig @<lan address> example.com` returns nothing
at all.

`is_direct_fallback_enabled` is the answer to that, and it is the person's to
give rather than a default, because the two ways of being wrong are not equal.
Failing costs connectivity. Falling back costs the thing the proxy was for:
traffic nobody meant to send in the clear leaves under this machine's own
address. A personal appliance whose main use is reaching past a censor must
not do the second quietly, so it is **off** unless somebody turns it on, and
the panel names the state either way — the strip reads `lan → no exit` when
there is nothing to go out through.

Turned on, two things change together:

| Half | Mechanism | Why not the obvious one |
| --- | --- | --- |
| Traffic | `fallbackTag: direct` on the balancer | xray's own; nothing to build |
| Names | dnsmasq gets `strict-order` and the direct resolvers as the upstreams behind xray | letting DNS fall back through the balancer would query the *remote* resolver in plaintext — which, in the network this exists for, is answered wrongly rather than not at all |

`strict-order` is what makes the second upstream a fallback rather than a
race: without it dnsmasq asks both and every query leaks to the direct
resolver in normal operation.

Measured on the same box, one unreachable node, before and after:

| | LAN DNS | Proxied traffic |
| --- | --- | --- |
| Fallback off | no answer | fails |
| Fallback on | answers | leaves through the WAN |

## More than one way out, and the proxy

xray's egress sockets use the main routing table like any local process, so
the proxy follows whatever the uplinks decide and needs no rules of its own.
Under failover its node connections leave by the active uplink and move when
that changes. Under balance the multipath default route spreads them per
connection, ports in the hash, exactly as it spreads the direct-list traffic
beside them. A `backup_only` uplink stays dark for the proxy for the same
reason it stays dark for everything: the metric bands, not a proxy rule.

An uplink that comes alive raises a link or address event, and the router
unit rebuilds the multipath route on it. Two limits are accepted rather than
solved. An uplink's health is carrier and an address, nothing more: a line
that is up but going nowhere keeps its share until its carrier drops, because
measuring throughput means probing, and a ranking that follows a probe flaps.
And a change that raises no link, address, route or rule event, such as
another tool rewriting nftables, stays until the next event or apply.

## What gets a role, and what does not

This is a developer's hub, not a router distribution. The machines it runs on
are laptops, Raspberry Pis and self-built NAS boxes, and the list of interface
kinds it drives is short on purpose. It is a whitelist: anything not on it is
left exactly as it was found, whoever put it there.

| Kind | Driven | What it may be |
| --- | --- | --- |
| A wired port | yes | uplink, served network, or a trunk carrying VLANs |
| A Wi-Fi radio | yes | joins a network as an uplink, or publishes one through hostapd |
| A 4G/5G card in MBIM or ECM mode | yes | uplink only |
| A VLAN on a trunk | yes | the gateway builds it, so it holds a role like a port |

The card is on the list because it costs nothing and somebody will have one:
a metered link kept dark until the wire fails is what `intent: backup_only`
already exists for. In MBIM or ECM mode it presents an ethernet interface and
takes a DHCP lease exactly like a wire, so `dhcpcd` drives it with no machinery
of its own. It is uplink-only because a carrier hands up one address with no
network behind it. **The hub does not bring the bearer up** — no APN, no PIN,
no AT commands. Something else establishes the connection, and the hub uses the
interface once it carries one.

Everything else is left alone, and each for its own reason:

| Not driven | Why |
| --- | --- |
| A modem in QMI raw-IP mode | its address comes out of the bearer over QMI rather than from a lease, so nothing here can put one on it |
| PPP and PPPoE dialling | `pppd`, a chat script and credentials, for a link almost nothing still uses |
| Bluetooth tethering | `bnep0` carries no device of its own, and a 1 Mbit link is not an uplink to build on |
| A bridge, a bond, a team | somebody made it; the hub does not take a port that is already owned |
| docker's, podman's and libvirt's interfaces | theirs |
| The overlay's `wt0` | the hub's, driven by the NetBird module rather than here. It carries no role and takes no address from the hub; what it does have is an exposure row, because that is a firewall question rather than a role |
| The proxy's TUN (`utun225`, `neutrino_tun`) | the proxy's, driven by the TUN module. It is no interface the hub exposes, counts among its LAN networks, or advertises to an overlay as a route; its /30 appears nowhere but in the TUN's own state |
| CAN, IEEE 802.15.4, InfiniBand | buses, not ports. A CAN adapter offered as a way to the internet is worse than one not shown |

Adding a kind means being able to drive it end to end. Half-driving one is how
a page comes to offer a role that fails after an SSID, a passphrase and a save.

## Handing a machine back

Two rules, and both have a way of being got wrong that leaves somebody locked
out of a box they are holding.

**Hand back before the configuration is replaced.** `nhub reset all` copies
every example over the real file, and the real file is the only thing that
says which radios and which uplinks the hub had units running on. Undo the
network first, while `config/` still names them; afterwards there is nothing
left to read and the units stay up on a box that has forgotten it started them.

**A reset takes no address off anything.** Nothing the hub configured is
un-configured: every interface keeps the address it has, and only the things
the hub *started* are stopped. An interface losing its address during a reset
is how the box drops the session that asked for the reset — and on a machine
somebody is holding in another room, that is the whole box gone.

Nothing has to be restored, because nothing was taken away: the managers that
were stood down are started again from a note of which ones they were, and no
file of theirs was ever read or written.

The resolver file is the one file put back. Router mode replaces
`/etc/resolv.conf`, and the first write copies what was there to
`resolv.conf.original` under the state root, a symlink as the same symlink.
Handing back links the file to the stub of `systemd-resolved` when that unit
is enabled. Otherwise it puts the copy back and deletes it, and with no copy
it writes the network's resolvers, so the
machine still has a resolver that answers. A box that entered router mode
under 0.3.1 has no copy: its reset writes the direct resolver, and the file it
had before is lost.

An uplink's address does change once that manager is running again, and it is
the manager that changes it: it asks for a lease under its own client identity
and is given back the one it had, which is the address the machine held before
the hub ever ran. Measured on Debian 12: the box arrives on `.60`, the hub's
own client takes `.61` — a different client identity is a different lease —
and `systemd-networkd` is on `.60` again a second after the reset. The rule is
about what the hub removes, and the hub removes nothing.

## Three engines, uniform everywhere

| Layer | Engine | Why it, and not a manager |
| --- | --- | --- |
| Address, route, VLAN | `ip` | the same command on every distribution |
| Joining a wireless network | `wpa_supplicant` | `ip` cannot do a WPA handshake — association is L2 — and this is what NetworkManager drives anyway |
| A lease on an uplink | `dhcpcd` | ~22 kB, and Raspberry Pi OS ran it as the *only* manager for years, so standalone is its designed use |
| Serving a network | our dnsmasq and hostapd units | already ours, already driven this way |
| NAT, forwarding, policy routing | our nftables ruleset and `ip rule` | already ours |

The routing half and the addressing half work the same way. `routes.py`
calls `ip` for the default route, the `fwmark` rule and table 100, and
`RouterDefaultRouteApplier` installs its own multipath default route at a
metric that beats whatever else is there. Addressing goes through `links.py`
with `ip`, the Wi-Fi scan and join through `supplicant.py` with
`wpa_supplicant`, a published access point through `wifi.py` with hostapd, a
lease through `dhcp_client.py` with `dhcpcd`, and what the panel's Network
page reads through `link_status.py` with `ip`. No part of the layer calls
`nmcli`.

Each engine is driven the way dnsmasq already is — our configuration, our
state, nothing of theirs:

- `wpa_supplicant`: rendered config under `/var/lib/neutrino/hub/generated/`, one
  unit per radio, on the pattern `neutrino_hub_hostapd@.service` already sets.
- `dhcpcd`: `-f` our own config so `/etc/dhcpcd.conf` is never read — on a
  Raspberry Pi that file may hold somebody's static address — and its hooks
  turned off. Measured on Debian 12, it ships `20-resolv.conf`, `30-hostname`
  and four time-sync hooks; left on, it is not an engine that fetches a lease,
  it is a second manager with opinions. Its lease database stays where dhcpcd
  puts it: 9.4.1 has no runtime override, the directory being fixed when it is
  built, so `/var/lib/dhcpcd` holds the leases. That is regenerable state, and
  the machine's own client is stopped before ours starts.

  The package to depend on is `dhcpcd-base`, which is the binary with no unit,
  the same split `dnsmasq-base` is taken for.

Both are ordinary dependencies, because installing neither takes anything over.
Measured on 2026-09-01: Fedora and Arch enable nothing at all, and Debian
enables one unit, `wpa_supplicant.service`, which runs

```text
/sbin/wpa_supplicant -u -s -O "DIR=/run/wpa_supplicant GROUP=netdev"
```

— no `-i` and no `-c`, so it holds no interface and no configuration and waits
on D-Bus for a manager to name one. There is no manager to: NetworkManager is
not a dependency. Its control sockets are in `/run/wpa_supplicant` and the
hub's are in `/run/neutrino/hub/wpa_supplicant`, so the two never meet.

What does hold a radio is `wpa_supplicant@<interface>.service`, the templated
unit systemd-networkd and ifupdown start per interface, and that is what
router mode stands down — one per radio it takes, rather than the machine-wide
one that owns nothing.

One thing NetworkManager gives away that this has to earn: **an address
survives a reboot because something reapplies it.** That is
`neutrino_hub_router.service`, a resident unit started after
`network-pre.target` and before anything the hub serves. It applies the
routing state from `config/` when it starts, and again on every link,
address, route or rule event that moves what it tracks. Each step stands
alone:

| Result | Meaning |
| --- | --- |
| `applied` | the step changed the kernel |
| `unchanged` | the kernel already matched |
| `pending` | a precondition is missing, such as a port that is down or a lease not yet held, and the event that supplies it runs the step again |
| `failed` | the kernel refused; the step is tried again on the next event or apply |

A failed step keeps the kernel state it had, and the steps after it still
run. The unit tells systemd it is ready once the firewall step has run,
before any step that starts a unit ordered after it. Stopping it tears
nothing down, so a restart leaves no gap in the firewall. Removing the
package and `nhub reset all` hand the firewall back.

### Neither engine's configuration can be checked before it is applied

`nft -c` and `dnsmasq --test` validate a render before anything is restarted,
and there is no equivalent for these two. dhcpcd has `--test`, which is not
one: measured on 9.4.1, `dhcpcd --test <interface>` segfaults with no
configuration given at all, so it says nothing about ours. wpa_supplicant has
no dry run; a bad file is discovered when it will not start.

What stands in for it is that both files are rendered by pure code with tests
of their own, and that a unit which will not start is a unit whose journal says
why. Do not add a validation step built on `--test`.

## Why not render NetworkManager's files instead

Writing `.nmconnection`, `netplan` YAML and `.network` files is the more
conventional answer, and it has real advantages: the machine's own tooling
keeps working, the engines' behaviour — carrier, renewal, roaming, WPA3 — is
inherited free, persistence across reboot is free, and it is one more renderer
in a codebase built out of renderers. It is also incremental, where this design
is a single larger step.

It was not chosen because of what varies. NetworkManager, netplan,
systemd-networkd and iwd are still moving, and so is the map from
distribution to manager: Ubuntu went ifupdown → netplan, Fedora ifcfg →
keyfile, Raspberry Pi OS dhcpcd → NetworkManager between two releases, Arch is
drifting to iwd. Building there is not one implementation per distribution; it
is one per manager, times a mapping that changes under us, and each change
fails silently — a netplan key that is no longer read is accepted and ignored.
`ip`, `wpa_supplicant` and DHCP on the wire have not moved in fifteen years.

Two further costs decided it. **Only NetworkManager can reapply without
dropping the link**, so the panel's Save would cut the operator off on three
backends out of four. And writing into directories another program owns is
where every bug in this area came from — the loops below are permanent for
anything living inside them, rather than something met once.

The same reasoning is why no serious Linux router builds on NetworkManager:
OpenWrt's netifd drives `ip`, `wpa_supplicant` and a DHCP client directly, and
VyOS renders its own configuration to `ip` and frr.

The amount of logic we write is the same either way — deciding what the
address, the route and the association should be. The difference is only
whether the floor under it is stable.

## What is never touched

**Their configuration is read, never written.** The hub does not edit, move or
delete a NetworkManager profile, a netplan file or a `.network`. In router
mode the manager is stopped, and a stopped manager's files are inert
— so nothing has to be backed up, emptied or put back, and `nhub reset all` is
stopping ours and starting theirs. The whole class of failure that comes from
restoring somebody's configuration tree — merge or replace, a directory copied
into itself, a mirror file regenerating what was removed — does not arise.

### Where a machine already keeps its Wi-Fi keys

| Store | Read from | What it holds |
| --- | --- | --- |
| NetworkManager | `/etc/`, `/run/` and `/usr/lib/NetworkManager/system-connections/*` | INI keyfiles; `psk-flags` says whether the passphrase is in the file or in the desktop's keyring |
| netplan | `/run/netplan/wpa-<interface>.conf` | what it renders from the passphrase in its own YAML, in supplicant format — so reading it needs no YAML parser |
| iwd | `/var/lib/iwd/<ssid>.psk` and `.open` | the network's name is the filename; the key is `PreSharedKey` or `Passphrase` |
| wpa_supplicant | `/etc/wpa_supplicant/*.conf` | already the format the hub renders; what Raspberry Pi OS wrote for years |

Two things in netplan's own output broke a parser that had only read files
people wrote, and both failed silently: it writes every SSID in
wpa_supplicant's printf form, `ssid=P"name"`, and it names three key managements
at once, `key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE`. Read as a single value that
matches no scheme, so every network on an Ubuntu machine was dropped as
enterprise without a word. The fixture in `test_credentials.py` is that file,
captured rather than written from memory.

Not read: ConnMan, netctl, and NetworkManager's older ifcfg files. Each is a
format of its own for a manager these machines are unlikely to be running, and
a network that is not inherited costs one prompt rather than a failure.

**Credentials are inherited read-only.** NetworkManager keeps a wireless
password in `/etc/NetworkManager/system-connections/<name>.nmconnection`, mode
0600, and `psk-flags` says where it really is: `0` means the passphrase is in
the file in plaintext, which is what `nmcli` and netplan produce; `1` means it
is agent-owned and lives in the desktop's keyring, and the file has none. The
hub reads the first kind to render its own supplicant config, and asks once for
the second. `wpa_supplicant.conf` is already the format we want, and iwd keeps
its own under `/var/lib/iwd/`. A read that fails costs one prompt, and
association either succeeds or reports why — there is no silent half-import,
which is the only reason inheriting is safe here.

## What was measured

On pristine cloud images, 2026-09-01. The lab's `nm_takeover.sh` converted VMs
to NetworkManager before the hub ran, which is why none of this was visible
until a package was installed onto an untouched image.

| Image | Configures interfaces | Resolves | Writes config |
| --- | --- | --- | --- |
| Ubuntu Server 24.04 | systemd-networkd | systemd-resolved | cloud-init → netplan |
| Debian 12 cloud | NetworkManager | systemd-resolved | cloud-init |
| Fedora 44 | NetworkManager | systemd-resolved | cloud-init → NM keyfiles |
| AlmaLinux 9 | NetworkManager | — | cloud-init |
| Arch | NetworkManager **and** systemd-networkd, both live on one link | systemd-resolved | cloud-init |
| Raspberry Pi OS ≤ Bullseye | dhcpcd | — | `/etc/dhcpcd.conf` |

Three traps, each found by a machine and not by reading:

**Ubuntu ships NetworkManager that will not touch ethernet.**
`/usr/lib/NetworkManager/conf.d/10-globally-managed-devices.conf` restricts it
to wifi and wwan, so every `nmcli connection up` fails with `No suitable device
found for this connection (device is strictly unmanaged)`.

**Disabling a manager does not keep it down.**
`systemd-networkd.service` is `TriggeredBy=systemd-networkd.socket`: stop the
service and the socket starts it again, leaving two managers after a takeover
that reported success. Stopping means masking. Unmasking therefore has to come
before enabling, since a masked unit can be neither enabled nor started.

**Ubuntu mirrors NetworkManager edits back into netplan.** `nmcli connection
modify` on a netplan-managed connection writes `/etc/netplan/90-NM-<uuid>.yaml`,
which regenerates that configuration into `/run` on every boot — including long
after whatever wrote it is gone.

**A dependency is a change to the machine.** Declaring `network-manager` was
enough to break the promise `server` and `side_gateway` make, with no line of the hub's own
code running: on a pristine Debian 12 managed by systemd-networkd, dpkg
configured it at 02:29:52 and four seconds later it had claimed the interface,
taken a second DHCP lease, installed a second default route and made itself
default for DNS — before the wizard asked its first question. Ubuntu passed the
same test only because it ships
`10-globally-managed-devices.conf`, which is luck rather than design. Nothing
in `SYSTEM_RUNTIME_PACKAGES` may manage a network, and on Debian even dnsmasq
is taken as `dnsmasq-base`, the same binary with no unit to start.

## The probe table

What the machine is running now, so router mode knows what to stop and the
other modes know to leave it alone. Probed one fact at a time and never keyed
off the distribution: a Raspberry Pi trips `dhcpcd` on one release and nothing
on the next, and that is the same code path.

| Code | Probed by |
| --- | --- |
| `networkd` | active, and `networkctl` reports a link `configured` |
| `ifupdown` | `networking` active, or a stanza other than `lo` in `/etc/network/interfaces` |
| `dhcpcd` | active |
| `connman`, `netctl` | active |
| `nm_restricted` | a device reports `unmanaged`, or a `*globally-managed-devices*` file exists |
| `cloud_init_network` | cloud-init installed and its network config not already off |
| `iwd` | active, since it and `wpa_supplicant` cannot share a radio |
| `desktop_session` | a graphical session is logged in |

Adding a distribution means adding the rows it trips, if any. A release that
moves its default manager shows up as a row being wrong, not as a branch to
write.

## What exists today

All three modes drive the three engines above; `nmcli` is gone from the layer
and NetworkManager is not a dependency. `server` and `side_gateway` are
verified byte for byte on Ubuntu 24.04 and Debian 12 — four configuration
trees compared before and after an install — and the router round trip is
exercised end to end on Debian 12: take the machine over, drive it, hand it
back.
