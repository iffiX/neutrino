---
title: "Overlay: EasyTier"
---

# Overlay: EasyTier

An EasyTier network is a name and a secret the hub generates. This page brings a second machine onto it, through a rendezvous node when both are behind NAT. EasyTier is one of the two overlay engines; the box runs one overlay at a time, and [NetBird](./overlay-netbird.md) is the other.

## What EasyTier is

EasyTier is peer to peer, with no management plane of its own. A network is a name and a secret: every machine configured with both is on it, and the secret is also the key its traffic is encrypted under. A machine starting up reaches one that is already on the network. When both machines are behind NAT, they meet at a rendezvous node: a machine with a public address that relays for the network. The peers speak on port 11010, TCP and UDP.

## Choose EasyTier and generate a network

1. In the panel, open **Overlay**.
1. Under **Engine**, pick **EasyTier** and select **Apply engine**. The hub installs the engine on the box when it is absent.
   ![The engine chooser](/guide/en/overlay_chooser.webp)
1. Under **This gateway on the network**, select **Generate**. **Network name** fills with a generated name, and **Network secret** fills with a masked secret. **This box's address** fills with an address such as `10.0.0.1/24`.
1. Select **Apply network**. The engine restarts on this network, and the badge reads **connected** or **no peers yet**.

::: warning
A different secret is a different network: every other machine stays on the old one until its secret is changed too.
:::

## Bootstrap peers and exported networks

**Bootstrap peers** are the addresses a starting machine dials: `tcp://`, `udp://`, `ws://`, `wss://` or `quic://` for a peer, `http://`, `https://`, `txt://` or `srv://` for a list that returns addresses. With none, the section reads **Nothing to reach yet, so this box waits to be reached.** Add the rendezvous node here as `tcp://198.51.100.7:11010`, then select **Apply peers**; the engine restarts and dials them.

**Exported networks** are the subnets that machines on the overlay reach through this box, `10.20.0.0/24` for example. Add each one and select **Apply networks**; the engine restarts and announces them.

![The running network with bootstrap peers and exported networks](/guide/en/overlay_easytier_running.webp)

## Commands for another machine

**Commands for another machine** shows two command lines with the secret masked, each with a **Copy with the secret** button that puts the real secret on the clipboard.

The first joins a plain node to the network through this hub's address:

```bash
easytier-core -d --network-name <name> --network-secret <secret> -p tcp://<hub>:11010
```

The second runs a rendezvous node of your own on a machine with a public address; it relays only this network's traffic and rejects every peer without the secret:

```bash
easytier-core --private-mode true --network-name <name> --network-secret <secret> \
  --relay-network-whitelist <name> -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010
```

`<name>` and `<secret>` are the generated pair, and `<hub>` is an address the other machine reaches this box on. Run the first command on the second machine; that machine appears in **Peers** within seconds.

![The two commands with the secret masked](/guide/en/overlay_easytier_commands.webp)

## The peer table

**Peers** lists one row per machine and reloads every five seconds. With no peer, the table reads **No machine has joined yet.** The box accepts EasyTier peers only on the networks ticked under **Exposure** on the **Network** page.

![The EasyTier peer table](/guide/en/overlay_easytier_peers.webp)

## Where the secret is

The secret is sealed under the vault's data key, in `config/`. The page shows the secret masked, and **Copy with the secret** is the one action that reads it out. Of the engine's own reads, the hub calls only the peer table; the `node` read prints the secret in the clear. A backup of `config/` holds it as ciphertext, opened by the vault passphrase.
