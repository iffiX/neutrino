---
title: "Overlay: NetBird"
---

# Overlay: NetBird

NetBird puts the hub on a private network run from NetBird's management console. This page ends with a machine outside the building reaching the LAN behind the hub by the hub's overlay address. NetBird is one of the two overlay engines; the box runs one overlay at a time, and [EasyTier](./overlay-easytier.md) is the other.

## Before you start

You need a NetBird account, with its management console open in a browser; **Open console** on the **Overlay** page opens it. The hub must reach the management plane. Behind a filter the badge reads **management unreachable**; switch on **Send Neutrino Hub's own traffic through the proxy** on [the Proxy page](./proxy.md) to get past it. When EasyTier is running, choosing NetBird stops it and closes the port it listened on.

## Prepare the network in the console

1. In the console, open **Networks** and press **Add Network**.
1. On the new network, under **Routing Peers**, press **Add** and choose **Install NetBird**.
1. Copy the setup key the console shows.

The key has the form `AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE`, and the panel's field shows that shape as its placeholder.

## Choose NetBird and join

1. In the panel, open **Overlay**.
1. Under **Engine**, pick **NetBird** and select **Apply engine**. When the engine is absent, the hub installs it; the section under the chooser then becomes NetBird's.
   ![The engine chooser with None, NetBird and EasyTier](/guide/en/overlay_chooser.webp)
1. Under **Join a network**, paste the setup key, leave the management URL empty for netbird.io, and select **Join**.
   ![The join form with the setup key](/guide/en/overlay_netbird_join.webp)

The button reads **Joining…**, then the badge turns **connected**, and **This gateway on the overlay** shows an **Overlay address**, a **Name** and the **Management** plane.

## Export the LAN routes

**LAN routes** lists one subnet per interface in the LAN role, each with a **Copy** button. A server-mode box has no LAN role, and the section reads **No interface has the LAN role.**

1. In the console under **Networks**, add each listed subnet as a **Resource** of your network.
1. Give the resource an **Access Control Policy**; the policy names the peers that use the route.

A peer elsewhere then reaches a machine on that subnet by its LAN address.

![The connected state with the LAN routes](/guide/en/overlay_netbird_connected.webp)

## Read the peer table

**Peers** lists one row per peer with its name, its overlay address and whether the link is **direct** or **relayed**. The row also shows the last handshake as a duration ago and, when there is any, the packet loss as a percentage. An empty table reads **No peers yet. Log in on another device with the NetBird app.**

![The peer table](/guide/en/overlay_netbird_peers.webp)

## Join from outside and re-enroll

Another device joins through NetBird's own app: install it there and log in to the same account, and the device appears in **Peers**. **Exposure** on the **Network** page lists the networks on which the box accepts the overlay's connections.

**Re-enroll** under **This gateway on the overlay** takes a fresh setup key and gives the hub a new identity on the network; the old peer entry stays in the console until you delete it there.
