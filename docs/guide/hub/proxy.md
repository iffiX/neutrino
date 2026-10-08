---
title: Proxy
---

# Proxy

The **Proxy** page sends the devices and destinations you choose to the internet through an exit node, and sends everything else directly through the uplink. Every apply on the page restarts the proxy, so connections through it drop for a moment. The badges beside the title show which traffic goes to the proxy and the name of the current exit. The mainland edition has no proxy and no **Proxy** page.

## Add exit nodes

**Exit nodes** are the servers proxied traffic leaves through. To add one:

1. Under **Exit nodes**, select **Add node**.
1. Paste the **Share link** as the provider gives it, `ss://` or `vless://`, and select **Add**.
1. Select **Apply nodes**.

A new node is enabled from the moment you add it. Traffic reaches it only while at least one switch under **Route** is on, as described in the following section.

![The exit nodes with their measurements](/guide/en/proxy_nodes.webp)

The hub measures every node and makes the enabled node it ranks highest the exit, marked **current exit**. Each card shows two times. **connect** is a connection to the node's own port, and **request** is a whole request through the node to the probe address. Under them the card shows when the node was last measured, its score and the share of measurements it answered.

A node's switch decides whether the hub can pick it as the exit. Switched-off nodes are measured too, so their numbers are readable before you switch them on.

| Setting                | What it sets                                                                                              |
| ---------------------- | --------------------------------------------------------------------------------------------------------- |
| **Test**, **Test all** | measures one node, or every node, now                                                                     |
| **Probe URL**          | the address fetched through each node, `https://www.gstatic.com/generate_204` by default                  |
| **Reference URL**      | an address fetched directly, which tells a dead node from a dead uplink; it must answer without the proxy |
| **Probe interval (s)** | the seconds between rounds of measurement, 60 by default                                                  |

Removing a node deletes its share link with it.

## Choose whose traffic goes through

**Route** holds four switches, each independent of the others:

| Switch                                                 | Traffic it sends to the exit                                                          |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| **Send LAN traffic through the proxy**                 | the devices on the networks this box serves; absent in server mode, which serves none |
| **Send overlay traffic through the proxy**             | overlay members that use this box as their exit node                                  |
| **Send Neutrino Hub's own traffic through the proxy**  | the box's own connections and name lookups                                            |
| **Let traffic out directly when no exit node answers** | none; it sets what happens when every enabled node is unreachable                     |

An overlay member reaches the exit only when the overlay itself names this box as the member's exit node. Setting this box as a gateway on the member has no effect.

The hub's own switch covers the box's other processes, such as the panel's downloads and the AI gateway. The hub's NetBird and EasyTier always reach their servers and peers directly through the uplink, whatever the switches say. On macOS and Windows the overlay switch and the hub's own switch act together.

With the fallback switch off and every enabled node unreachable, traffic sent to the proxy fails. The LAN's names fail with it, because they resolve at the exit. With the fallback switch on, that traffic leaves through the WAN under the box's own address. In both cases the [Dashboard](./dashboard.md) and this page show a notice at the top.

## Split by destination

![The route section with the direct lists](/guide/en/proxy_routing.webp)

With **GeoIP split routing** on, destinations on the direct lists leave straight through the WAN. Everything else sent to the proxy goes through the exit nodes. With it off, everything sent to the proxy goes through the exit nodes.

| List               | Syntax                                              |
| ------------------ | --------------------------------------------------- |
| **Direct domains** | `geosite:cn`, `domain:example.com`, `keyword:baidu` |
| **Direct IPs**     | `geoip:cn`, `geoip:private`, `10.0.0.0/8`           |

**Update geodata** checks for a newer release of the geoip and geosite databases and installs it. The line beside the button says whether the databases are **as the package carries them** or **taken from a release**.

**DNS** holds two lists of resolvers. Each row is an address, or an address and a port, and a row with no port uses port 53. Type a row and select **Add**. The rows are asked in order:

- **Remote resolvers (proxied names)** answer every name that is not on a direct list, through the exit node. The list needs at least one row, and the hub rejects an empty one with `resolver_required`.
- **Direct resolvers (bypassed names)** answer the direct-list names, the exit nodes' own names and the probe host. An empty list reads **Follows the network's resolvers**, and those names go to the resolvers of the [Network](./network.md) page.

Names outside every proxy switch skip both lists and go to the network's resolvers. Select **Apply route** to rewrite the routing rules.

## Open SOCKS ports

**Ports** are SOCKS5 listeners for applications set to use a proxy themselves. An **Exit node** port splits traffic the way forwarded traffic is split, and a **Direct** port leaves straight through the uplink.

1. Under **Ports**, type a port, pick **Exit node** or **Direct**, and select **Add**.
1. Select **Apply ports**.

The hub rejects a port another program already listens on with `port_already_in_use`. Every port listens on the networks ticked under **Exposure** on the **Network** page, overlays included.

## Check it

From a device that uses the proxy, or from the box with its own switch on, fetch your public address:

```bash
curl ifconfig.me
```

The output is the exit node's address. To test an **Exit node** SOCKS port from a machine on an exposed network, replace `<hub-address>` with the box's address and `<port>` with the port:

```bash
curl --socks5 <hub-address>:<port> ifconfig.me
```

To read the proxy configuration the hub renders from `config/`, run the following on the hub box. It prints the configuration and leaves the running proxy as it is:

```bash
sudo nhub apply --only xray --dry-run
```
