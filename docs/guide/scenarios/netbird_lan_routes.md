---
title: LAN devices over NetBird
---

# Reach LAN devices without an agent through NetBird

After these steps, a client on NetBird opens a device on your home LAN at the device's own address. The device runs no agent: a printer, your router's admin page, or the admin page of a NAS.

Before you start, check these:

- The hub has joined NetBird, as [Join the hub to NetBird](../hub/netbird.md) describes, and a client reaches the hub through NetBird.
- The hub runs in router or side gateway mode.
- You are an administrator of the NetBird account in its console.

## Read the subnets the hub serves

1. In the panel, open the **Access** page.
1. Select the **NetBird** card.
1. Under **LAN routes**, select the subnet that holds the device's address. The panel copies the subnet to the clipboard.

A printer at `192.168.10.20` sits in `192.168.10.0/24`, for example. **LAN routes** lists every network the hub holds an address on, with the networks it serves at the top.

![The LAN routes list on the NetBird card, with one subnet](/guide/en/overlay_netbird_routes.webp)

## Add the subnet as a resource

The console's **Add Network** wizard runs in this order: the network, its resource, a policy, then the routing peer. This section and the next two follow that order.

1. In the NetBird console, open **Network Routing** > **Networks**.
1. Select **Add Network**.
1. Type a **Name** for the network, then continue to **Add Resource**.
1. Type a **Name** for the resource.
1. Paste the subnet into **Address**.
1. Continue to the access control step.

## Allow the clients' group

Every client of the hub joins NetBird with the hub's setup key, so every client is in the group that key assigns. The **Setup Keys** list shows that group in the key's **Groups** column. A policy lets the group reach the resource.

1. In the access control step, select **Add Policy**.
1. Set the source to the group your setup key assigns.
1. Set the destination to the resource you added.
1. Set the protocol to **All**.
1. Select **Continue**.
1. Select **Submit**.

The policy then appears in the console under **Access Control** > **Policies**.

![A NetBird policy from the setup key's group to the LAN resource](/guide/console/console_netbird_policy.webp)

## Make the hub a routing peer

The hub is already a peer on NetBird, so you pick it from the console's list.

1. In **Add Routing Peer**, pick the hub's peer. Leave **Install NetBird** alone: it sets up a machine that is not on NetBird yet.
1. Select **Continue**.
1. Select **Submit**.

The network's page lists its resource, its routing peer and its policy.

![A NetBird network with the hub as its routing peer and the LAN subnet as its resource](/guide/console/console_netbird_network.webp)

## Check from a client

These steps run in the desktop client or the Android app, away from home.

1. Open the **Hubs** page and find the hub's virtual network line, under the hub's row.
1. If the line reads **Not connected**, select **Connect**. The line reads **Connected ·** followed by the client's NetBird address. A line that was already connected adds the new route on its own.
1. In a browser, open the device's LAN address, such as `http://192.168.10.20`.

## When the device stays unreachable

| What you see                                                                                   | Cause                                                                                                         | Fix                                                                      |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| The virtual network line reads **Connected ·** with an address, and the device does not answer | No policy lets the clients' group reach the resource                                                          | Add the policy in [Allow the clients' group](#allow-the-clients-group)   |
| A red line at the top of the **Access** page with `overlay_route_overlap`, naming the route    | Another NetBird peer offers a route that overlaps a network the hub is on, and the hub stops using that route | In the console, change or delete the route the red line names            |
| `overlay_default_route_refused` at the top of the **Access** page                              | The console gives the hub a route for `0.0.0.0/0`; the hub deletes it and keeps its own uplink as the way out | In the console, delete the `0.0.0.0/0` exit route from the hub           |
| The hub runs in server mode                                                                    | A server-mode hub forwards no packets between networks                                                        | On the hub's **Network** page, switch the mode to router or side gateway |
