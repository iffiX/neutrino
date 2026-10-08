---
title: Proxy
---

# Proxy

The **Proxy** page sends the devices and destinations you choose to the internet through an exit node, and everything else directly through the uplink. Every apply on the page restarts the proxy, and connections through it drop for a moment. The mainland edition has no proxy and no **Proxy** page.

## Add exit nodes

To add an exit node:

1. Under **Exit nodes**, select **Add node**.
1. Paste the **Share link** as the provider gives it, `ss://` or `vless://`, and select **Add**.
1. Select **Apply nodes**.

Traffic reaches a node only while a switch under **Route** is on.

![The exit nodes with their measurements](/guide/en/proxy_nodes.webp)

The hub measures every node and makes the enabled node it ranks highest the **current exit**. Each card shows **connect**, the time to reach the node, and **request**, the time of a whole request through it.

| Setting                | What it sets                                                                             |
| ---------------------- | ---------------------------------------------------------------------------------------- |
| **Probe URL**          | the address fetched through each node, `https://www.gstatic.com/generate_204` by default |
| **Reference URL**      | an address fetched directly, which tells a dead node from a dead uplink                  |
| **Probe interval (s)** | the seconds between rounds of measurement, 60 by default                                 |

## Choose whose traffic goes through

**Route** holds four switches, each independent of the others:

| Switch                                                 | Traffic it sends to the exit                                       |
| ------------------------------------------------------ | ------------------------------------------------------------------ |
| **Send LAN traffic through the proxy**                 | the devices on the networks this box serves; absent in server mode |
| **Send overlay traffic through the proxy**             | overlay members whose overlay names this box as their exit node    |
| **Send Neutrino Hub's own traffic through the proxy**  | the box's own connections and name lookups                         |
| **Let traffic out directly when no exit node answers** | none; it sets what happens when every enabled node is unreachable  |

The hub's NetBird and EasyTier always reach their servers directly. On macOS and Windows the overlay switch and the hub's own switch act together.

When every enabled node is unreachable, traffic sent to the proxy fails, or with the fallback switch on leaves through the WAN. The [Dashboard](./dashboard.md) and this page then show a notice at the top.

## Split by destination

![The route section with the direct lists](/guide/en/proxy_routing.webp)

With **GeoIP split routing** on, destinations on the direct lists leave straight through the WAN, and the rest goes through the exit nodes. With it off, everything sent to the proxy goes through the exit nodes.

| List               | Syntax                                              |
| ------------------ | --------------------------------------------------- |
| **Direct domains** | `geosite:cn`, `domain:example.com`, `keyword:baidu` |
| **Direct IPs**     | `geoip:cn`, `geoip:private`, `10.0.0.0/8`           |

**DNS** holds two lists of resolvers, each row an address with an optional port, 53 by default. The rows are asked in order:

- **Remote resolvers (proxied names)** answer every name that is not on a direct list, through the exit node. The list needs at least one row.
- **Direct resolvers (bypassed names)** answer the direct-list names, the exit nodes' own names and the probe host. An empty list reads **Follows the network's resolvers**, and those names go to the resolvers of the [Network](./network.md) page.

Select **Apply route** to apply the switches, the lists and the resolvers.

## Open SOCKS ports

**Ports** are SOCKS5 listeners for applications that use a proxy themselves. A **Direct** port leaves straight through the uplink.

1. Under **Ports**, type a port, pick **Exit node** or **Direct**, and select **Add**.
1. Select **Apply ports**.

Every port listens on the networks ticked under **Exposure** on the **Network** page. When the hub rejects a port or a resolver list, the code is on [Troubleshooting](../reference/troubleshooting.md).

## Check it

From a device that uses the proxy, or from the box with its own switch on, fetch your public address. The output is the exit node's address:

```bash
curl ifconfig.me
```

To test an **Exit node** SOCKS port from a machine on an exposed network, replace `<hub-address>` with the box's address and `<port>` with the port:

```bash
curl --socks5 <hub-address>:<port> ifconfig.me
```
