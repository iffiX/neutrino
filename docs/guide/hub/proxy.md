---
title: Proxy
---

# Proxy

On the **Proxy** page you choose which devices and destinations go out to the internet through an exit node. Everything else goes out directly through the uplink. The page writes `config/xray/`. Every apply on the page restarts the proxy, and connections through the proxy drop for a moment.

## Switches and nodes

**Route** holds two switches. **Send LAN traffic through the proxy** sends the traffic of the devices behind the box, and **Send Neutrino Hub's own traffic through the proxy** sends the box's own. In server mode the box forwards no device's traffic, and the first switch's description reads that there is no LAN to send.

**Exit nodes** are the servers proxied traffic goes out through. To add one:

1. Select **Add node**.
1. Paste the **Share link** as the provider gives it, `ss://` or `vless://`, and select **Add**.
1. Pick a **Balancer strategy**: `leastPing` for the lowest latency, `random` per connection, or `roundRobin` through the nodes.
1. Select **Apply nodes**.

![The exit nodes with latency and a balancer strategy](/guide/en/proxy_nodes.webp)

**Test** probes one node and **Test all** probes every node. A node's card reads **unreachable**, **no answer yet** or **not probed**. **Probe interval (s)** sets how often the proxy probes the nodes on its own. Removing a node deletes its share link with it.

## SOCKS ports

**Ports** are SOCKS5 listeners on every exposed interface, for applications that point at a proxy themselves. Each port is either an **Exit node** port, split the way forwarded traffic is, or a **Direct** port, which goes straight out through the uplink.

1. Under **Ports**, type a port, pick **Exit node** or **Direct**, and select **Add**. The hub rejects a port that is already in use with `port_already_in_use`.
1. Select **Apply ports**.

![The SOCKS ports](/guide/en/proxy_socks.webp)

The default port is `1080`. A port listens on the networks ticked under **Exposure** on the **Network** page.

## Split routing

With **GeoIP split routing** on, domains and IPs matching the direct lists go straight out through the WAN. Everything else sent to the proxy goes through the exit-node balancer. With the switch off, everything sent to the proxy goes through the exit nodes.

| List               | Syntax                                              |
| ------------------ | --------------------------------------------------- |
| **Direct domains** | `geosite:cn`, `domain:example.com`, `keyword:baidu` |
| **Direct IPs**     | `geoip:cn`, `geoip:private`, `10.0.0.0/8`           |

**DNS** has two resolvers. The **Direct resolver** answers the names on the direct lists, and every name while the LAN switch is off. The **Remote resolver** answers every other name, and the query reaches it through the exit node.

**Let traffic out directly when no exit node answers** is off by default. While it is off and every enabled node is unreachable, traffic sent to the proxy fails. The LAN's names fail with it, because they are resolved at the exit. With it on, that traffic goes out through the WAN under the box's own address, and the direct resolver answers the names. **Apply route** rewrites the routing rules.

![The route section with the direct lists](/guide/en/proxy_routing.webp)

## This box's own traffic

**Send Neutrino Hub's own traffic through the proxy** works in any shape and independently of the LAN switch. It is the switch for a hub that cannot reach NetBird's management plane from where it sits. It also serves the AI gateway's providers when they are reachable only through the exit.

## Check it

From a machine that uses the proxy, or from the box itself with the local switch on:

```bash
curl ifconfig.me
```

The output is the exit node's address. Through a SOCKS port from any machine on an exposed network:

```bash
curl --socks5 <hub>:1080 ifconfig.me
```

`<hub>` is the box's address. `sudo nhub apply --only xray --dry-run` renders the proxy's configuration from `config/` and prints it, without touching the running proxy.
