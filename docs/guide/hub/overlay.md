---
title: Access
---

# Access

An overlay is a private network laid over the internet. Through it, a machine outside your building reaches the hub and the LAN behind it. The **Access** page runs NetBird, EasyTier, or both at once, each with its own switch and its own settings.

## Turn an engine on

![The two engine cards, both switched on](/guide/en/overlay_switches.webp)

**Engine** holds one card per engine. The switch on a card, **Run NetBird** or **Run EasyTier**, says whether the engine runs. Selecting the card itself only picks which engine's settings show under the cards.

1. Turn on the engine's switch.
1. Select **Apply overlays**. The hub installs the engine when it is absent, starts the engines turned on, then stops the ones turned off.

A card marked **active** has its engine running. A card that reads **No build for this machine** cannot be turned on. With no engine on, the page reads **No overlay runs, so nothing reaches this box from outside.**

The hub rejects turning an engine on with `overlay_subnet_overlap` when its network overlaps another network. That is the other overlay's network, or any network this box holds an address on. NetBird's network is `100.64.0.0/10`. EasyTier's is the network of this box's address on it.

## Join NetBird

Before you start, you need a NetBird account with its management console open; **Open console** on the NetBird section opens app.netbird.io. NetBird must be on and running, or the apply bar reads **NetBird is not running yet.**

In the console, prepare a network and a setup key:

1. Open **Networks** and select **Add Network**.
1. On the new network, under **Routing Peers**, select **Add**, then **Install NetBird**.
1. Copy the setup key the console shows.

![The NetBird settings with the setup key field](/guide/en/overlay_netbird_settings.webp)

In the panel, join with that key:

1. Select the **NetBird** card.
1. Under **Settings**, paste the setup key. Leave the management URL empty for netbird.io.
1. Select **Join**.

The badge beside **NetBird** reads **joining**, then **connected**, and **Settings** shows the **Overlay address**, **Name** and **Management**. The key stays saved, sealed under the vault, and **Setup key** reads **Saved**. Clients allowed on the overlay receive it and join the same network; **Replace** and **Forget** change or remove it. [Clients](./clients.md) sets which clients can use the overlay.

| Badge                      | Meaning                                                                               |
| -------------------------- | ------------------------------------------------------------------------------------- |
| **connecting**             | the daemon is reconnecting after a restart                                            |
| **not joined**             | the box has no NetBird identity, or its last login expired; join again with a new key |
| **management unreachable** | the box cannot reach the management plane                                             |

Behind a filter that blocks the management plane, turn on **Send Neutrino Hub's own traffic through the proxy** on the [Proxy](./proxy.md) page and join again.

With the box joined, the apply bar's button reads **Re-enroll**: a new setup key gives the box a new identity, and you delete the old peer in the console. **Leave** deletes the box from the network after you confirm.

**LAN routes** lists each subnet the box serves. In the console under **Networks**, add each one as a **Resource** of your network and give it an **Access Control Policy**; a peer then reaches that subnet's machines by their LAN addresses. A server-mode box reads **No interface has the LAN role.**

## Set up EasyTier

An EasyTier network is a name and a secret: every machine with both is on it, and the secret is also the key that encrypts its traffic. Peers speak on port 11010, TCP and UDP.

![The EasyTier settings in manual mode](/guide/en/overlay_easytier_settings.webp)

Select the **EasyTier** card. Its **Settings** panel picks where the network comes from, and one apply bar, **Apply EasyTier settings**, applies everything in it.

### EasyTier console

In this mode EasyTier's official console sets the network, the box's address, its bootstrap peers and its subnet routes.

1. In the EasyTier console, copy the address a device joins with, of the form `tcp://et-web.console.easytier.net:22020/` followed by your account's token.
1. In the panel, under **Settings**, select **EasyTier console**.
1. Paste the address into **Console address**.
1. Optional: turn on **Secure mode** when the console's network runs in EasyTier's secure mode.
1. Select **Apply EasyTier settings**.

The badge reads **Waiting for the console** until you attach the box to a network in the console. **Networks from the console** then shows each network's name, this box's address and name, and its **Subnet routes**. To export the box's LANs, add each one in the console as a subnet route of this device.

### Manual bootstrap peers

In this mode the box holds the network's name and secret and dials the peers you list.

1. Under **Settings**, select **Manual bootstrap peers**.
1. Select **Generate**. **Network name**, **Network secret** and **This box's address** fill in.
1. Under **Bootstrap peers**, add the address of a machine already on the network, such as `tcp://198.51.100.7:11010`.
1. Optional: under **Exported networks**, add each subnet that overlay machines reach through this box.
1. Select **Apply EasyTier settings**.

With no bootstrap peer, the box only accepts peers that dial it. The badge reads **connected**, or **no peers yet** while nobody else is on the network.

::: warning
A different secret is a different network. Every other machine stays on the old network until its secret changes too.
:::

**Commands for another machine** shows two command lines with the secret masked, and **Copy with the secret** copies a line with the real secret. In the lines, `<network-name>` and `<secret>` are the network's pair, and `<hub-address>` is an address the other machine reaches this box on; the copied line has all three filled in. The first line joins a machine to this network through this box:

```bash
easytier-core -d --network-name <network-name> --network-secret <secret> -p tcp://<hub-address>:11010
```

The second runs a rendezvous node of your own on a machine with a public address. It relays only this network and admits only machines with the secret:

```bash
easytier-core --private-mode true --network-name <network-name> --network-secret <secret> \
  --relay-network-whitelist <network-name> -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010
```

## Run both at once

Turn on both switches and select **Apply overlays**. Each engine keeps its own settings, peers and clients, and the hub keeps them apart:

- The hub rejects an overlapping network with `overlay_subnet_overlap`, as when one engine is turned on. Saving an EasyTier address while EasyTier runs is checked the same way.
- The hub drops packets that enter on one overlay and leave by the other.
- A route an overlay installs that overlaps another network appears in red at the top of the page. The hub deselects a NetBird route; an EasyTier route is only reported, and the page says to change it where the overlay is managed.
- A default route through an overlay appears as `overlay_default_route_refused`: the hub deletes it and keeps its own uplink as the way out.

## Turn an engine off

1. Turn off the engine's switch.
1. Read the warning in the apply bar.
1. Select **Apply overlays**.

![The apply bar warning about online clients](/guide/en/overlay_off_warning.webp)

The warning counts the online clients connected through that engine, and says that the way into this box through it closes. The engine stops after the hub sends every client and device its new state.

::: info
Turning an engine off stops its service and keeps its settings. Turning it on again starts it on the same settings.
:::

## Read the peer tables

Each engine's section ends with **Peers**, read again every five seconds. A row shows the peer's name and overlay address, and whether the link is **direct** or **relayed**. Both engines add the latency and the bytes received and sent. NetBird adds the time since the last handshake, and EasyTier adds the protocol and the packet loss.

An empty NetBird table reads **No peers yet. Log in on another device with the NetBird app.** An empty EasyTier table reads **No machine has joined yet.**

**Topology** above the settings draws the box, its LANs and its peers after the box joins a network. Whether the box answers its own services on an overlay is set under **Exposure** on the [Network](./network.md) page.
