---
title: LAN devices over NetBird
---

# Reach LAN devices without an agent through NetBird

These steps route your home LAN over NetBird to reach the devices that run no agent, such as a printer or a NAS admin page. A client away from home then opens each one at its own LAN address. The mainland edition has no NetBird; its route page is the EasyTier one.

Before you start, check these:

- The hub has joined NetBird, as [Join the hub to NetBird](../hub/netbird.md) describes, and a client reaches the hub through NetBird.
- The hub runs in router or side gateway mode, as [Make the hub a router or side gateway](./router_or_gateway.md) describes.
- You are an administrator of the NetBird account in its console.

## Read the subnets the hub serves

1. In the panel, open the **Access** page.
1. Select the **NetBird** card.
1. Under **LAN routes**, select the subnet that holds the device's address, such as `192.168.10.0/24` for a printer at `192.168.10.20`. The panel copies the subnet.

![The LAN routes list on the NetBird card, with one subnet](/guide/en/overlay_netbird_routes.webp)

## Add the subnet as a resource

The console's **Add Network** wizard asks for the network, its resource, a policy, then the routing peer, and the next three sections follow it.

1. In the NetBird console, open **Network Routing** > **Networks**.
1. Select **Add Network**.
1. Type a **Name** for the network, then continue to **Add Resource**.
1. Type a **Name** for the resource.
1. Paste the subnet into **Address**.
1. Continue to the access control step.

## Allow the clients' group

Every client of the hub joins NetBird with the hub's setup key, so it is in the group that key assigns. The **Setup Keys** list shows that group in the key's **Groups** column.

1. In the access control step, select **Add Policy**.
1. Set the source to the group your setup key assigns.
1. Set the destination to the resource you added.
1. Set the protocol to **All**.
1. Select **Continue**.
1. Select **Submit**.

![A NetBird policy from the setup key's group to the LAN resource](/guide/console/console_netbird_policy.webp)

## Make the hub a routing peer

1. In **Add Routing Peer**, pick the hub's peer from the list. Leave **Install NetBird** alone.
1. Select **Continue**.
1. Select **Submit**.

The network's page lists its resource, its routing peer and its policy.

![A NetBird network with the hub as its routing peer and the LAN subnet as its resource](/guide/console/console_netbird_network.webp)

## Check from a client

In the desktop client or the Android app, away from home:

1. On the **Hubs** page, find the virtual network line under the hub's row.
1. If the line reads **Not connected**, select **Connect**. A line that was already connected takes the new route itself.
1. In a browser, open the device's LAN address, such as `http://192.168.10.20`.

## When the device stays unreachable

If the virtual network line reads **Connected ·** with an address and the device does not answer, check the policy in [Allow the clients' group](#allow-the-clients-group). A red line on the **Access** page names a route problem, and [Troubleshooting](../reference/troubleshooting.md#access) has its fix.
