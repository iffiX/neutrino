# Access devices without an agent

You can access devices that cannot install software, such as printers and routers, from an outside network.

If you need only their web pages, try [Add existing services](/en/deploy/services) first, which works without routes. The method here connects your device directly to the network segment of the hub. Of the access methods, only [NetBird](/en/access/netbird) and [EasyTier](/en/access/easytier) support it.

You set the routes by hand in the NetBird or EasyTier console, and the hub manages none of them. Apps, terminals, files and remote desktop work without routes, because those connections go through the hub.

## Prerequisites

Check that the following holds:

- The hub has joined this virtual network, and your device is connected to it.
- You have administrator rights in the console of your NetBird or EasyTier account.
- You know the network segment to access, such as `192.168.1.0/24`.

To look up a segment, open the **NetBird** card on the **Access** page of the panel and read **LAN routes**. It lists each network segment of the computer the hub runs on, and selecting a segment copies it.

![The LAN routes field of the NetBird card](/guide/en/access_netbird_05_routes.webp)

## NetBird

Take the following steps in the NetBird console:

1. Open the NetBird console, go to **Networks**, select **Add Network** and enter a name.

   ![A network in the NetBird console, holding one resource named home LAN](/guide/zh/deploy_without_agent_01_netbird_network.webp)

1. Select **Add Resource**, and paste the segment you copied into **Address**.

1. Select **Add Policy**. Choose the group of the client as the source, this resource as the destination and **All** as the protocol. The group of the client shows in the **Groups** column of the **Setup Keys** list in the console.

1. Select **Add Routing Peer**, choose the hub, and select **Submit**.

For how each step looks in the NetBird console, see the official NetBird [Networks](https://docs.netbird.io/manage/networks) guide.

## EasyTier

If you use the console, take these steps:

1. Open the EasyTier console, choose the network of the hub under **Networks**, and open **Subnet Routes**.

   ![The Subnet Routes of the EasyTier console, listing one route through the hub](/guide/zh/deploy_without_agent_05_easytier_subnet.webp)

1. Select **Add Route** and fill in **Target subnet**. Choose the hub as the device the route goes through, then select **Create Route**.

1. Return to the **EasyTier** card in the panel. The **Subnet routes** field of **Networks from the console** lists this segment.

   ![Networks from the console, with 192.168.1.0/24 in the Subnet routes field marked in red](/guide/en/deploy_without_agent_07_easytier_routes.webp)

If you chose **Manual bootstrap peers**, there is no console. In that case, select the segment in **Exported networks** on the card, then select **Apply EasyTier settings**.

## Verify the connection

1. Take your device off the local network of the hub, for example by switching your phone to mobile data.
1. Check that the **Virtual network** row in the client shows **Connected**.
1. Open the local network address of the device in a browser. If the page opens, the setup works.

On Android, the system shows a permission dialog the first time you connect to the virtual network, and you must choose to allow it. The iPhone app has no virtual network row, so join with the NetBird or EasyTier app instead.

## Troubleshoot the connection

If you use NetBird, check that the console has a policy that permits this group.

If you use EasyTier and the client keeps showing **Connecting…**, the client is not yet attached to a network. Attach it to the network in the console.

If red text appears at the top of the **Access** page of the panel, a route overlaps the network segment of the hub. See [Troubleshooting](/en/reference/troubleshooting).

The hub deletes the default route `0.0.0.0/0`, so add only specific segments.

## Risks

This connection method bypasses the permission checks of the hub. Every member of this virtual network can access every port of every device on this segment, protected only by the device's own sign-in.
