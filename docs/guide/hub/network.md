---
title: Network
---

# Network

The **Network** page sets the box's shape, the role of each interface and the networks the panel is reachable on. Read this page to learn what each shape does to your network before you change it. The page's sections, in order:

| Section            | What it sets                                                  |
| ------------------ | ------------------------------------------------------------- |
| **Mode**           | the box's shape                                               |
| **Topology**       | the role and address of each interface, in the routing shapes |
| **Known networks** | the networks a WAN radio joins                                |
| **Exposure**       | the networks the box accepts connections on                   |
| **Panel port**     | the port the panel listens on                                 |

## The shapes

The setup wizard's **What is this machine for?** screen offers four shapes. The page's **Mode** section shows three, because a one-arm router is stored as a router.

| Shape          | What it does                                       | What it takes over                                  | Ports needed |
| -------------- | -------------------------------------------------- | --------------------------------------------------- | ------------ |
| Server         | Routes nothing; answers where it is reached.       | nothing; every address stays as the machine set it  | 1            |
| Side gateway   | Forwards for hosts that name it as their gateway.  | nothing addressed; the hosts point at it themselves | 1            |
| Router         | Routes between uplinks and the networks it serves. | the interface roles and the addresses on them       | 2            |
| One-arm router | Routes on one wire: untagged out, tagged VLAN in.  | as a router, on one wired trunk                     | 1 wired      |

![The Mode section with the three shapes](/guide/en/network_modes.webp)

![The wizard's shape screen](/guide/en/setup_shape.webp)

Only the router shape takes over addressing. The wizard lists only the shapes the machine has enough ports for. **Apply mode** rewrites the interface roles and reloads the firewall.

::: danger
A one-arm router needs a switch that passes VLAN tags. On a plain switch the configuration looks right and every tagged packet is dropped.
:::

## Interface roles

In the routing shapes each interface has a **Role**:

| Role         | Meaning                      |
| ------------ | ---------------------------- |
| **WAN**      | An uplink to the internet    |
| **LAN**      | A network the gateway serves |
| **Split**    | A trunk sliced into VLANs    |
| **Disabled** | Left alone                   |

A WAN interface takes its **Address** by **DHCP** from the upstream network, or a **Static** address with a **Gateway**. A LAN interface has a **Gateway address** and a **Prefix length**; the served network is `192.168.8.0/24` with the box at `192.168.8.1` unless you change it, a range the upstream router is unlikely to use. A split trunk has one **untagged** main interface, named after the trunk, and one VLAN interface per tag. Select **Apply to** the trunk first; each VLAN interface then has a tab of its own.

::: warning
Changing a served network reassigns its address and reissues every lease on it; the panel says so before applying.
:::

A side gateway adds one field, **Upstream gateway**, which holds the address of the router on the network the box forwards for. **Routing behavior** holds two switches for the routing shapes, **Networks reach each other** and **Spread traffic across uplinks**.

## DHCP and DNS

On each served network, the box gives its DHCP clients its own address as their gateway and their resolver. The **DHCP** panel of a LAN interface has the switch **Allocate address on this network**, a **Range start** and **Range end**, and a **Lease time**. The lease time is in dnsmasq form, `12h` for example. The pool runs from host `.100` to `.200` unless you change it, and the box's own address must lie outside it.

With the switch on, the box assigns addresses on the network. The box serves DNS on the network whether or not the switch is on. In server mode the box serves no network, so it runs neither DHCP nor DNS.

## Wireless

A radio in the WAN role joins a network; a radio in the LAN role publishes one.

**Known networks** lists the networks a WAN radio joins. The radio prefers the one highest in the list. Networks read from the machine's own configuration are marked **Read from this machine's** source; one whose key was kept where the hub could not read it is marked **needs a passphrase**, and picking it from **Scan for networks** opens a field for the passphrase. **Join** on a scanned network sets the interface to WAN, and **Forget** deletes the passphrase.

A LAN radio has an **Access point** panel with a **Network name**, a **Passphrase** and a **Band**. The passphrase is 8 to 63 characters, WPA2 only, and the band is 2.4 GHz or 5 GHz. A trunk cannot be a radio, because 802.1Q tags are not transmitted over a radio.

## Exposure and the panel port

**Exposure** is the list of networks on which the box accepts connections to its own services: the panel, SSH, DNS, the shares. A SOCKS port and the overlay's listener are reachable on the same networks.

1. Under **Exposure**, tick each network the box is reachable on.
1. Select **Apply exposure**. The panel reloads the firewall input chain and reports **Applied to the firewall.**

![The Exposure section](/guide/en/network_exposure.webp)

An exposed uplink accepts connections from the internet on every port the box listens on. The panel shows a warning before it applies such an exposure. The panel's own port is under **Panel port**:

1. Under **Panel port**, type the new **Port**.
1. Select **Apply panel port**. The panel restarts on the new port and the browser follows it; when the new address is unreachable from where you are, the page reads **No answer at** that address.

## Changing the shape

A shape is chosen at setup, and changing it is a reset:

```bash
sudo nhub reset all
sudo nhub setup
```

`nhub reset all` hands the network back first, then replaces `config/` with the examples, removes every key and token the box collected, and stops the services; `/etc/neutrino/agent` stays, because it belongs to the agent package. Every interface keeps its address through the reset, so the session that ran it keeps its connection. [The Settings page](./settings.md) has a backup to take first.
