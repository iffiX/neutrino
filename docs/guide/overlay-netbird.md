---
title: Overlay with NetBird
---

# Overlay with NetBird

NetBird puts this hub on a private network over the public internet, using
NetBird's own management plane. The panel joins it, announces the LAN subnets,
and lists the peers.

Four things to know before the first click:

- One overlay runs at a time. Choosing NetBird stops EasyTier, and choosing
  EasyTier stops NetBird.
- The management plane is NetBird's, not yours. A hub that cannot reach it does
  not join. For an overlay with no management plane at all, read
  [Overlay with EasyTier](./overlay-easytier.md).
- LAN routes exist only where an interface holds the `lan` role. A server-mode
  hub has none, and that section stays empty.
- Whether this box answers on the overlay is set under Network, Exposure, not
  on this page.

NetBird keeps the vendor's `/var/lib/netbird` state directory and socket, and
the hub does not relocate them. The client runs under the hub's own unit from
`/opt/neutrino/bin`, on interface `wt0`, with UDP peer port `51820`.

## Before you start

- A NetBird account, and the console open in a browser. The Overlay page has an
  "Open console" button for it.
- A hub that can reach the management plane. If it cannot, the badge reads
  "management unreachable".
- One overlay at a time: choosing NetBird takes the box off EasyTier.

![The Overlay page's engine chooser, with None, NetBird and EasyTier](/guide/en/overlay_chooser.webp)

## Choose NetBird

Open **Overlay**.

Expect: an "Engine" section with three choices, each carrying its summary.
NetBird's reads "A private network over the public internet, on NetBird's
management plane."

Pick NetBird and press "Apply engine".

Expect: when another engine is running, the confirmation reads "{title} stops
and the way into this box from outside closes." After applying, NetBird
installs if it is not installed, and the sections below the chooser become
NetBird's. Until then they read "NetBird is not installed. Applying the engine
above installs it." and "NetBird is not running yet."

The engine choice is one row in `config/router/network.json`, which the
firewall reads too.

## Join with a setup key

The panel gives the three console steps in its own order:

1. In the console, open Networks and press Add Network.
2. On the new network, under Routing Peers, press Add and choose Install
   NetBird.
3. Copy the setup key it shows and paste it below.

Paste the key into the setup key field, which reads "setup key, like
AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE". Leave the management URL empty to use
netbird.io, then press "Join".

Expect: the button reads "Joining…", then the badge turns "connected" and "This
gateway on the overlay" fills in an Overlay address, a Name and a Management
plane. An address not yet handed out reads "assigning…".

::: tip
An empty management URL means netbird.io. A management plane of your own goes
in that field, as its full address.
:::

![The join form with the setup key field and the management URL field](/guide/en/overlay_netbird_join.webp)

![The Overlay page connected, showing the gateway's overlay address and name](/guide/en/overlay_netbird_connected.webp)

::: warning
The hub joins by talking to the management plane. Behind a filter it cannot,
the badge reads "management unreachable", and nothing else on the page works.

The panel names the way out: "Management plane unreachable. If behind a filter,
enable \"Route this gateway's own traffic\" on the Proxy page."
:::

## Announce LAN routes

Read the subnets under "LAN routes". Each row has a Copy button.

Expect: one row per interface holding the `lan` role. With none, the section
reads "No interface has the LAN role.", which is what a server-mode box shows.

In the console, under Networks, add each subnet as a Resource of your network,
then give it an Access Control Policy so peers may use the route.

Expect: a peer elsewhere reaches a machine on that subnet by its LAN address.

## Peer table

Read "Peers".

Expect: one row per peer with its name, its overlay address, the last handshake
as "{duration} ago", and "{share}% lost" when packets are being dropped. With
no peers it reads "No peers yet. Log in on another device with the NetBird
app."

![The peer table with two peers, their overlay addresses and last handshakes](/guide/en/overlay_netbird_peers.webp)

## Re-enroll

Press "Re-enroll" in "This gateway on the overlay", paste a fresh setup key,
and confirm.

Expect: the confirmation reads "Re-enrolling gives this gateway a new identity
on the network. Afterwards, delete the old peer entry in the console."

The old peer entry stays in the console until you delete it there.

That is the whole path: this hub is a peer, and its LAN is reachable from
outside.
