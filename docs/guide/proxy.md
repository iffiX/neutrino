---
title: Proxy
---

# Proxy

The Proxy page decides where proxied traffic leaves the internet, which local
ports applications can point at, and which destinations are left out of the
proxy altogether.

Read this before you change anything:

- Nothing on this page edits `/etc`. `config/xray/` is the source of truth, and
  the panel and `nhub apply` write it through the same pipeline. If you want to
  write xray configuration by hand, this page is not for you.
- Every apply on this page restarts the proxy, and connections through it drop.
- In server mode the box forwards nobody's traffic, so the LAN switch has no
  LAN to send. The SOCKS ports and this box's own traffic still work.
- The geodata ships inside the package and is not updated at runtime. The
  permissive pair travels, because the fuller set is GPL-3.0.

## Nodes

Open **Proxy**.

Expect: "Exit nodes" at the top, described as "Where proxied traffic leaves the
internet. The balancer picks between the enabled ones by the strategy below."
With none added it reads "No nodes configured" and "Add one with a share link
from your provider."

Press "Add node", paste the share link as the provider gives it, and press
"Add".

Expect: a card for the node, carrying its name and an Enabled toggle. A
`ss://` or `vless://` link is what the field wants.

Pick a balancer strategy, then press "Apply nodes".

Expect: "Loads the exit nodes into the running proxy.", under the standing
warning "Restarts the proxy; connections through it drop."

The three strategies are `leastPing`, lowest latency wins; `random`, pick per
connection; and `roundRobin`, cycle through nodes. Each node has a "Test"
button, "Test all" tests every one, and "Probe interval (s)" sets how often the
hub probes them by itself.

![The Proxy page's exit nodes, with two nodes and the balancer strategy](/guide/en/proxy_nodes.webp)

::: tip
`leastPing` reads the observatory, and so does a fallback tag. A configuration
naming either without one is refused by xray with "not all dependencies are
resolved". The panel writes both together; a hand-edited `config/xray/` may
not.
:::

Removing a node says what it costs: "The exit node is deleted and its share
link is not kept."

## SOCKS ports

The Ports section publishes "SOCKS5 listeners, on every exposed interface. Each
one either leaves straight out the uplink or goes out through the exit nodes."

Type a port number, choose "Exit node" or "Direct", and press "Add".

Expect: the row appears. `1080` is the usual first one. A port already in use
is refused with "Port {port} is already listening.", and a number outside the
range with "A port is {min} to {max}."

Press "Apply ports".

Expect: "Rewrites the xray inbounds and reloads the proxy."

![The Ports section with one exit-node port and one direct port](/guide/en/proxy_socks.webp)

::: tip
Publishing a Direct port beside a proxied one gives you both paths at once, so
an application can be pointed at either without changing anything here.
:::

A Direct port "Appears to come from this network." A SOCKS port answers on
every exposed interface, and which interfaces those are is set under Network,
Exposure.

## Routing by device and destination

The Route section is "Whose traffic goes through the exit nodes, and which
destinations are left out of it."

Set the two switches: "Send LAN traffic through the proxy" and "Send Neutrino
Hub's own traffic through the proxy".

Expect: in server mode the LAN switch reads "This box forwards no one's traffic
in server mode, so there is no LAN to send."

Leave "GeoIP split routing" on, or turn it off to proxy everything that is sent
to the proxy.

Expect: the flow strip reads direct list, then everything else, then the exit
node. With the split on, "Domains and IPs matching the direct lists below leave
straight out of the WAN. Everything else that is sent to the proxy goes through
the exit-node balancer."

Edit "Direct domains" and "Direct IPs" in xray rule syntax, then press "Apply
route".

```text
geosite:cn
domain:example.com
keyword:baidu
```

```text
geoip:cn
geoip:private
10.0.0.0/8
```

Expect: "Rewrites the xray routing rules and reloads the proxy."

![The Route section with the GeoIP split on and the direct lists filled in](/guide/en/proxy_routing.webp)

Two resolvers sit below the lists. The direct resolver "Answers direct-list
names, and all names while the proxy is off." The remote resolver is "Resolved
at the exit node."

## This box's own traffic

"Send Neutrino Hub's own traffic through the proxy" is its own switch: "It
works in any network mode, and independently of the LAN switch."

It settles one case in particular. A hub that cannot reach NetBird's management
plane turns this on, and the Overlay page names the switch when it reports
"management unreachable".

## Checking

```bash
# 1. Does the configuration render? Expect no error and no restart.
sudo nhub apply --only xray --dry-run

# 2. Does the proxy path work? Expect a node's address, not your ISP's.
curl -s --socks5 127.0.0.1:1080 https://ifconfig.me; echo
```

::: warning When every exit node is down
With every enabled exit node unreachable and the fallback switch off, traffic
sent to the proxy fails, and so do the LAN's names, because they are resolved
at the exit. The panel reads "Every enabled exit node is unreachable. Traffic
sent to the proxy (the LAN's names included) fails until one answers."

Turn on "Let traffic out directly when no exit node answers", or fix a node.
With the fallback on, that traffic leaves through the WAN under this machine's
own address instead.
:::

That is the whole path: one exit node answering, one port to point an
application at, and a direct list for what should never go through it.
