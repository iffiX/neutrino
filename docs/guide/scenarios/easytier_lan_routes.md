---
title: LAN devices over EasyTier
---

# Reach LAN devices without an agent through EasyTier

Through EasyTier, a client away from home reaches a LAN device that runs no agent, such as a printer or your router's admin page. The client opens the device at the device's own LAN address. The mainland edition leaves out NetBird, so its route page is this one.

Before you start, check these:

- The hub is on an EasyTier network, as [Put the hub on an EasyTier network](../hub/easytier.md) describes, and a client reaches the hub through EasyTier.
- The hub runs in router or side gateway mode.
  <!-- 待核: whether a server-mode hub works as an EasyTier subnet proxy (outline item 1) -->

The **Settings** of the **EasyTier** card on the **Access** page shows the hub's mode: **EasyTier console** or **Manual bootstrap peers**. In console mode, follow every section in order and skip the manual mode section. In manual mode, skip the two console sections.

## Find the subnet

The subnet is the network of the LAN where the device sits. In router mode, open the panel's **Network** page and read the LAN interface's **Gateway address** and **Prefix length**. A gateway address of `192.168.10.1` with a prefix length of 24 gives the subnet `192.168.10.0/24`. In side gateway mode, use the hub's own address on that LAN with its prefix: `192.168.1.20/24` gives `192.168.1.0/24`.

## Add a subnet proxy in the console

1. In the EasyTier console, open the device list.
1. Select the hub's device.
1. Open the device's network configuration.
1. Add the subnet to the subnet proxy field.
1. Save the configuration.

<!-- 待核: the EasyTier console's names for the device list, the network configuration and the subnet proxy field (outline item 2) -->

![The hub device's network configuration in the EasyTier console with a subnet proxy filled in](/guide/console/console_easytier_subnet_proxy.webp)

## Read it in the panel

1. In the panel, open the **Access** page.
1. Select the **EasyTier** card.

Under **Networks from the console**, the network's **Subnet routes** lists the subnet you added.

![Networks from the console on the EasyTier card, with the subnet under Subnet routes](/guide/en/overlay_easytier_subnet_routes.webp)

## In manual mode

1. On the **Access** page, select the **EasyTier** card.
1. Under **Exported networks**, turn on the subnet. The list shows each network the hub is on, with its interface.
1. Select **Apply EasyTier settings**. EasyTier restarts, and connections over it drop for a moment.

## Check from a client

These steps run in the desktop client or the Android app, away from home. Each client on the network gets the route from EasyTier itself.

1. Open the **Hubs** page and find the hub's virtual network line, under the hub's row.
1. If the line reads **Not connected**, select **Connect**. The line reads **Connected ·** followed by the client's EasyTier address.
1. In a browser, open the device's LAN address, such as `http://192.168.10.20`.

## When the device stays unreachable

| What you see                                                                                | Cause                                                                                                                                              | Fix                                                                                                                                    |
| ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| A red line at the top of the **Access** page with `overlay_route_overlap`, naming the route | A route another machine on the EasyTier network offers overlaps a network the hub is on. The hub reports an EasyTier route and leaves it in place. | Change or remove that route in the console, or under **Exported networks** on the machine that offers it                               |
| The hub runs in server mode                                                                 | A server-mode hub forwards no packets between networks                                                                                             | On the hub's **Network** page, switch the mode to router or side gateway                                                               |
| The client shows `overlay_other_network`                                                    | This client's machine is on another virtual network, such as another hub's EasyTier console                                                        | On the other hub's row, select **Disconnect** on its virtual network line, then connect this one                                       |
| In console mode, the client's virtual network line stays at **Connecting…**                 | The client's machine is registered with the console and is not yet attached to a network                                                           | In the console, attach the client's device to the hub's network, as [Put the hub on an EasyTier network](../hub/easytier.md) describes |
