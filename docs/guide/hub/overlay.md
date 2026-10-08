---
title: Access
---

# Access

The **Access** page turns on, turns off and reports each way a client or an agent outside your network reaches the hub: Direct, SSH Relay, NetBird and EasyTier. Each way in has a card with an **Enable** switch, and any set of them runs at once. Which one suits your network is the subject of [Choose a way in](../scenarios/choose_a_way_in.md).

## Turn a way in on

![The four cards, all switched on](/guide/en/overlay_switches.webp)

**Engine** holds the cards in two rows: **Direct** and **SSH Relay**, then **NetBird** and **EasyTier**. The mainland edition has no NetBird card.

1. On the card, turn on **Enable**.
1. Select **Apply access**.

The hub installs an engine that is not installed yet, starts the engines turned on, then stops the ones turned off. A card marked **active** is running. A card that reads **No build for this machine** cannot be turned on on this system.

Selecting a card itself only picks which settings appear under the cards. A card shows its settings after it is turned on and applied.

The hub rejects turning an engine on with `overlay_subnet_overlap` when its network overlaps another overlay's network or a network this box holds an address on. NetBird's network is `100.64.0.0/10`, and EasyTier's is the network of this box's address on it.

## Turn on Direct

Direct makes the hub's agent port, 8443, answer on every enabled interface, so a client reaches the hub at the hub's own addresses. It opens that one port and no other. The panel and the AI gateway keep the exposure the [Network](./network.md) page gives them.

In router mode an enabled interface is one whose role is not **Disabled**. In server and side gateway mode it is every interface the **Network** page lists.

![The Direct settings with a public address and the addresses for clients](/guide/en/overlay_direct_settings.webp)

To add an address reachable from outside, such as one your router forwards to the hub:

1. Turn on **Direct** and select **Apply access**.
1. Under the cards, fill **Public address** with a host name or IP address, and **Public port** with its port.
1. Select **Apply Direct**.

**Addresses for clients** lists what Direct gives clients and agents: each enabled interface's address that **Exposure** does not already open, then the public address. A stable IPv6 address counts too; a temporary or link-local one is left out. The list reads **No enabled interface has an address.** when there is nothing to list. When every enabled interface is already exposed, the list says that Direct adds none of them and that a public address can still be set.

The hub rejects a public address that is neither an IP address nor a host name with `direct_host_invalid`. It rejects a port outside 1 to 65535 with `port_out_of_range`.

## Set up the other ways in

Each of the other ways in has settings and steps of its own, on a page of its own.

### SSH Relay

A server you rent or own forwards one public port to the hub over SSH, as described in [Reach the hub through your own server](./relay.md).

### NetBird

The hub joins a NetBird network with a setup key from the NetBird console, as described in [Join the hub to NetBird](./netbird.md).

### EasyTier

The hub joins an EasyTier network from its console or by name and secret, as described in [Put the hub on an EasyTier network](./easytier.md).

## Run several at once

Turn on each card and select **Apply access**. Each way in keeps its own settings, peers and clients, and the hub keeps the overlays apart:

- Turning on an overlay whose network overlaps the other's is rejected with `overlay_subnet_overlap`. Saving an EasyTier address while EasyTier runs is checked the same way.
- The hub drops packets that enter on one overlay and leave by the other.
- A route an overlay installs that overlaps another network appears in red at the top of the page. The hub deselects a NetBird route. An EasyTier route is only reported, with the instruction to remove it where the overlay is managed.
- A default route through an overlay appears as `overlay_default_route_refused`. The hub deletes it and keeps its own uplink as the way out.

A client dials every address it has for the hub at the same time and keeps the first that answers. When a better path appears, the client moves to it in this order: LAN, Direct, NetBird and EasyTier, then SSH Relay. Two paths of the same rank are compared by round trip time.

## Turn a way in off

1. On the card, turn off **Enable**.
1. Read the warning in the apply bar.
1. Select **Apply access**.

![The apply bar warning about online clients](/guide/en/overlay_off_warning.webp)

The warning counts the online clients connected through that way in, and says that the way into this box through it closes. The hub sends every client and device its new state, then stops the engine. Its settings stay stored, and turning it on again starts it with the same settings.

## Read the peers and the topology

The NetBird and EasyTier sections end with **Peers**, read again every five seconds. A row shows the peer's name, its overlay address, and whether the link is **direct** or **relayed**. It also shows the latency and the bytes received and sent. Where the engine reports no latency, the hub measures it by pinging the peer's overlay address.

NetBird adds the time since the last handshake. EasyTier adds the protocol and the share of packets lost.

An empty NetBird table reads **No peers yet. Log in on another device with the NetBird app.** An empty EasyTier table reads **No machine has joined yet.**

**Topology** draws the box, its LANs and its peers after the box joins a network. Whether the box answers its own services on an overlay is set under **Exposure** on the **Network** page.
