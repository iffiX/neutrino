---
title: EasyTier
---

# Put the hub on an EasyTier network

An EasyTier network is a network name and a secret, and every machine holding both is on it. Both editions include EasyTier. Before you start, turn on the **EasyTier** card on the **Access** page, select **Apply access**, and select the card to open its **Settings**.

## Pick where the network comes from

**Settings** offers two modes, and **Apply EasyTier settings** applies the whole section:

- With an account on the EasyTier console, choose **EasyTier console**. The console sets the network, the hub's address and its routes.
- Without one, choose **Manual bootstrap peers**. The hub holds the network's name and secret, and every machine must reach its port 11010.

## Attach the hub in the console

The console is in Chinese, and the labels here are as it shows them.

### Copy the console address

1. In the EasyTier console at `https://console.easytier.net`, select **设备接入方法** (how to connect a device) at the top right.
1. Select the **开源版接入** (open-source edition) tab.
1. Under **连接 EasyTier**, pick a key in **接入秘钥** (access key).
1. In the command shown, copy the whole address after `--config-server`.

### Register the hub

1. Under **Settings**, select **EasyTier console**.
1. Paste the address into **Console address**.
1. Leave **Secure mode** off, as the first step does; the console's own join command turns it on, and the hub registers either way.
1. Select **Apply EasyTier settings**.

The section reads **Waiting for the console**.

![The EasyTier section waiting for the console](/guide/en/overlay_easytier_console_waiting.webp)

### Create the network for the hub

The hub now appears on the console's **设备** (devices) page.

![The EasyTier console's device list with the hub registered](/guide/console/console_easytier_devices.webp)

1. In the console's sidebar, open **网络** (networks).
1. Select **创建网络** (create network).
1. Type a **网络名称** (network name), and select **创建网络** at the bottom of the dialog.
1. Select the network's name to open its page.
1. Select **挂载设备** (attach device).
1. Under **入网设备** (devices to join), pick the hub.
1. Select **加入网络** (join network).

![The console's form for a new network](/guide/console/console_easytier_network_create.webp)

The hub's row on the network's page reads **运行中** (running) after a moment. The badge reads **no peers yet** while the hub is alone on the network, and **connected** when another device on it is reachable. **Networks from the console** shows each network, the hub's address on it and its **Subnet routes**.

![The networks the console gave the hub](/guide/en/overlay_easytier_console_networks.webp)

## Attach each client

In console mode a client that connects to the virtual network registers with the console, and its row reads **Connecting…**. In the console, open the hub's network, select **挂载设备**, pick the client under **入网设备** and select **加入网络**. The client's row then reads **Connected**.

![A phone being attached to the hub's network in the console](/guide/console/console_easytier_device_attach.webp)

## Export the LANs

To reach the LAN devices behind the hub, follow [LAN devices over EasyTier](../scenarios/easytier_lan_routes.md).

## Manual bootstrap peers

![The EasyTier settings in manual mode](/guide/en/overlay_easytier_settings.webp)

1. Under **Settings**, select **Manual bootstrap peers**.
1. Select **Generate**. **Network name**, **Network secret** and **This box's address** fill in.
1. Under **Bootstrap peers**, add the address of a machine on the network, such as `tcp://198.51.100.7:11010`.
1. Optional: under **Exported networks**, add each LAN that overlay machines reach through this box.
1. Select **Apply EasyTier settings**.

Each client receives the hub's uplink address with port 11010 as its bootstrap peer. A client away from home needs that port open from outside, over TCP and UDP.

::: warning
A different secret is a different network. Every other machine stays on the old network until its secret changes too.
:::

**Commands for another machine** shows two command lines, and **Copy with the secret** copies one with the real secret. In them, `<network-name>` and `<secret>` are the network's pair, and `<hub-address>` is the hub's address.

The first line joins a machine to this network through the hub:

```bash
easytier-core -d --network-name <network-name> --network-secret <secret> -p tcp://<hub-address>:11010
```

The second runs a bootstrap peer of your own on a machine with a public address:

```bash
easytier-core --private-mode true --network-name <network-name> --network-secret <secret> \
  --relay-network-whitelist <network-name> -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010
```

When the hub rejects these settings, the code is on [Troubleshooting](../reference/troubleshooting.md#access).
