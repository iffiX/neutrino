---
title: EasyTier
---

# Put the hub on an EasyTier network

When this page is done, the hub is on an EasyTier network with the badge **connected**. Each client allowed on the overlay joins the same network from its link. An EasyTier network is a network name and a secret, and every machine holding both is on it. Peers talk on port 11010 over TCP and UDP. Both editions include EasyTier.

Before you start, turn on the **EasyTier** card on the **Access** page and select **Apply access**. Then select the card to open its **Settings**.

## Pick where the network comes from

**Settings** offers two modes, and one apply bar, **Apply EasyTier settings**, applies everything in the section:

- If you have an account on the EasyTier console, choose **EasyTier console**. The console sets the network, the hub's address and its routes.
- If you have no console account and every machine reaches the hub's port 11010, choose **Manual bootstrap peers**. The hub holds the network's name and secret.

Switching modes restarts EasyTier, and connections over it drop for a moment.

## Attach the hub in the console

In console mode the hub registers with the console, and you attach it to a network there.

### Copy the console address

The address a device registers with has the form `tcp://et-web.console.easytier.net:22020/<token>`, where `<token>` is your account's token. The hub also takes the token alone, and then registers with `udp://config-server.easytier.cn:22020`. It rejects anything else with `easytier_config_server_invalid`.

<!-- 待核: where the EasyTier console shows the address, and whether it gives the full address or the token alone (outline item 2) -->

### Register the hub

1. Under **Settings**, select **EasyTier console**.
1. Paste the address into **Console address**.
1. Optional: turn on **Secure mode** when the console's network runs in EasyTier's secure mode.
1. Select **Apply EasyTier settings**.

The section reads **Waiting for the console**, with **This machine is registered with the console. Attach it to a network there.**

![The EasyTier section waiting for the console](/guide/en/overlay_easytier_console_waiting.webp)

### Create the network for the hub

1. In the EasyTier console, open the device list and find the hub.
1. Create a network for the hub, with a name, a secret and an address range.
1. Start the network on the hub's device.

<!-- 待核: EasyTier console labels for the device list, the network form and starting a network (outline item 2) -->

![The EasyTier console's device list with the hub registered](/guide/console/console_easytier_devices.webp)

![The console's form for a new network](/guide/console/console_easytier_network_create.webp)

The badge reads **connected**. **Networks from the console** shows each network's name, the hub's address and name on it, and its **Subnet routes**. A value the console does not report reads **Not provided by the console**.

<!-- 待核: with the hub alone on the console's network, whether the badge reads connected or no peers yet (outline item 4) -->

![The networks the console gave the hub](/guide/en/overlay_easytier_console_networks.webp)

## Attach each client

In console mode a client registers with the same console when it connects to the virtual network. Its virtual network row reads **Connecting…**, with **This machine is registered with the console. Attach it to a network there.**

1. In the EasyTier console, open the device list and find the client.
1. Attach the client to the hub's network.

The client's row then reads **Connected**.

![A phone being attached to the hub's network in the console](/guide/console/console_easytier_device_attach.webp)

## Export the LANs

In console mode, add each LAN of the hub as a subnet route of the hub's device in the console. In manual mode, list each LAN under **Exported networks**. The full steps are in [LAN devices over EasyTier](../scenarios/easytier_lan_routes.md).

## Manual bootstrap peers

![The EasyTier settings in manual mode](/guide/en/overlay_easytier_settings.webp)

In manual mode the hub holds the network's name and secret, and dials the bootstrap peers you list:

1. Under **Settings**, select **Manual bootstrap peers**.
1. Select **Generate**. **Network name**, **Network secret** and **This box's address** fill in.
1. Under **Bootstrap peers**, add the address of a machine on the network, such as `tcp://198.51.100.7:11010`. When the hub is the first machine, list a bootstrap peer of your own, started with the second command that **Commands for another machine** shows.
1. Optional: under **Exported networks**, add each LAN that overlay machines reach through this box.
1. Select **Apply EasyTier settings**.

With no bootstrap peer listed, **Apply EasyTier settings** stays greyed, and the hub rejects the settings with `easytier_invalid`. Each client receives the hub's uplink address with port 11010 as its bootstrap peer. For a client away from home, port 11010 on the hub's uplink must be reachable from outside, over TCP and UDP.

::: warning
A different secret is a different network. Every other machine stays on the old network until its secret changes too.
:::

**Commands for another machine** shows two command lines with the network name and the hub's address filled in and the secret masked. **Copy with the secret** copies a line with the real secret in it. In the lines here, `<network-name>` and `<secret>` are the network's pair, and `<hub-address>` is an address the other machine reaches the hub on.

The first line joins a machine to this network through the hub:

```bash
easytier-core -d --network-name <network-name> --network-secret <secret> -p tcp://<hub-address>:11010
```

The second runs a bootstrap peer of your own on a machine with a public address. It relays only this network and admits only machines with the secret:

```bash
easytier-core --private-mode true --network-name <network-name> --network-secret <secret> \
  --relay-network-whitelist <network-name> -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010
```
