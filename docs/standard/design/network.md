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
- **Four modes are the whole vocabulary.** Anything a mode cannot express is a
  thing this does not do, on purpose.
- **The defaults have to be right**, because most people will press through
  them. That is why the address a port is offered is the one it already has,
  and why the mode a machine cannot be is not on the list.

A configuration surface wide enough to express every network is a surface
nobody in that description can cross.

## Guest and owner, and the mode says which

| Mode | Kind | What the machine is | What the hub owns |
| --- | --- | --- | --- |
| `server` | guest | somebody's machine — a VPS, a laptop | **nothing**: no port holds a role, and it answers on the address each already has |
| `side_gateway` | guest | a machine on a network somebody else routes | **nothing**: forwarding, masquerade and DNS are all in our own nftables and dnsmasq |
| `router` | owner | this box *is* the router | the network stack |
| `one_arm_router` | owner | this box is the router, on one wire | the network stack |

A machine is wholly one or the other. There is no half-managed state, because
every bug worth having found so far came from sharing an interface with
another manager.

`server` gives no port a role at all, which is what keeps the rest of the
layer from treating it as a router: nothing is served, so dnsmasq answers
nowhere; nothing routes, so the forward chain has no policy to enforce and is
left `accept` — docker, libvirt and whatever else forwards across that machine
are not the hub's to police, and a drop policy there cuts every one of them off
without saying so.

**The guest modes touch nothing at all.** No connection is edited, no manager
is stopped, no file outside the hub's own roots is written. `side_gateway`
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

**The owner modes own the stack**, and say so before anything is done. The
mode is stored in `config/router/network.json` and is the first thing the
Network page asks; changing it there re-plans every interface, and taking a
machine over starts from the addresses it already has. Leaving an owner mode
hands the network back the way a reset does — the managers that were stood
down are started again, and no address is taken off anything.

## What answers, and where

Every service this box runs binds every address and settles its own port in
its own tab. What is left to decide is which wires reach them, and that is one
answer per interface — `is_exposed` — rather than a port list per interface
that would have to be kept in step with what is installed.

```text
iifname { "enp1s0" } accept        # everything this box listens on
iifname "wt0" accept               # the overlay, always
```

The overlay is not in the list and cannot be closed: it is how a box that
answers nowhere else is reached at all. A served network is exposed by
definition — it is where the panel, the leases and DNS are reached — and an
uplink is closed, because remote access arrives over the overlay. Opening an
uplink opens *everything*, which is why there is no "SSH from the WAN" switch:
a per-port list on the one interface facing the internet is a list that gets
half right, and the honest control is the whole interface with what it costs
written beside it.

A guest mode starts with every interface open. That is what the machine was
already doing before the hub arrived, and a VPS that answers on nothing after
an install is a VPS nobody can reach.

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
| The overlay's `wt0` | the hub's, driven by the NetBird module rather than here |
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

The last two rows are the point: **the routing half already works this way.**
`routes.py` calls `ip` directly in eight places for the default route, the
`fwmark` rule and table 100, and `RouterDefaultRouteApplier` installs its own
multipath default route at a metric that beats whatever else is there. What
still goes through `nmcli` is addressing (`routes.py`), the Wi-Fi scan and
join (`wifi.py`, 396 lines), and what the panel's Network page reads
(`link_status.py`) — all of it on `network_manager.py`, 392 lines of nothing
else. Replacing the engines means replacing those three too, and the Wi-Fi
page is the one that goes dark first if it is forgotten.

Each engine is driven the way dnsmasq already is — our configuration, our
state, nothing of theirs:

- `wpa_supplicant`: rendered config under `/var/lib/neutrino/generated/`, one
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
hub's are in `/run/neutrino/wpa_supplicant`, so the two never meet.

What does hold a radio is `wpa_supplicant@<interface>.service`, the templated
unit systemd-networkd and ifupdown start per interface, and that is what an
owner mode stands down — one per radio it takes, rather than the machine-wide
one that owns nothing.

One thing NetworkManager gives away that this has to earn: **an address
survives a reboot because something reapplies it.** Today that is a keyfile
NetworkManager reads at boot, and `neutrino_hub_router.service` replays only
the nftables ruleset and the default route. Addressing with `ip` means that
unit replaying the interface roles too, in the slot it already holds —
`After=network-pre.target`, before anything the hub serves.

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
delete a NetworkManager profile, a netplan file or a `.network`. In an
an owner mode the manager is stopped, and a stopped manager's files are inert
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
enough to break the promise the guest modes make, with no line of the hub's own
code running: on a pristine Debian 12 managed by systemd-networkd, dpkg
configured it at 02:29:52 and four seconds later it had claimed the interface,
taken a second DHCP lease, installed a second default route and made itself
default for DNS — before the wizard asked its first question. Ubuntu passed the
same test only because it ships
`10-globally-managed-devices.conf`, which is luck rather than design. Nothing
in `SYSTEM_RUNTIME_PACKAGES` may manage a network, and on Debian even dnsmasq
is taken as `dnsmasq-base`, the same binary with no unit to start.

## The probe table

What the machine is running now, so an owner mode knows what to stop and a
guest mode knows to leave it alone. Probed one fact at a time and never keyed
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

All four modes drive the three engines above; `nmcli` is gone from the layer
and NetworkManager is not a dependency. The guest modes are verified byte for
byte on Ubuntu 24.04 and Debian 12 — four configuration trees compared before
and after an install — and the owner round trip is exercised end to end on
Debian 12: take the machine over, drive it, hand it back.
