---
title: Network
---

# Network

On the **Network** page you choose what the box is to your network and decide where the box answers. In router mode the page also sets each interface's role, and DHCP and DNS on the networks the box serves. Each section has its own apply bar and changes only what it shows.

| Section              | Shown in             | What it sets                                        |
| -------------------- | -------------------- | --------------------------------------------------- |
| **Mode**             | every mode           | the box's shape                                     |
| **Upstream gateway** | side gateway         | the router the box forwards to                      |
| **Topology**         | router               | a drawing of the interfaces and the devices on them |
| the interface tabs   | router               | each interface's role and addresses                 |
| **Fixed addresses**  | router, with a LAN   | the devices that always get one address             |
| **Known networks**   | router, with a radio | the wireless networks a WAN radio joins             |
| **Routing behavior** | router               | how uplinks and served networks behave together     |
| **Exposure**         | every mode           | the networks the box accepts connections on         |
| **Panel ports**      | every mode           | the ports the panel serves HTTP and HTTPS on        |

## Choose the shape

![The Mode section with the three shapes](/guide/en/network_modes.webp)

| Shape            | What it does                                       | Addresses on the machine     |
| ---------------- | -------------------------------------------------- | ---------------------------- |
| **Server**       | Routes nothing; answers where it is reached.       | kept as the machine set them |
| **Side gateway** | Forwards for hosts that name it as their gateway.  | kept as the machine set them |
| **Router**       | Routes between uplinks and the networks it serves. | taken over by the hub        |

The setup wizard also offers a one-arm router, which routes on one wired trunk: untagged out, tagged VLAN in. The panel stores it as **Router**, with the trunk in the **Split** role.

To change the shape:

1. Under **Mode**, select the shape. The current one has the **active** badge.
1. Select **Apply mode**. The hub rewrites the interface roles and reloads the firewall.

Entering router mode hands the interfaces to the hub, and a DHCP uplink can come back with a new address. Leaving router mode hands them back to the machine's own network manager, and the served networks end. In both cases the apply bar warns before you apply. Leaving side gateway mode cuts off the hosts that named the box as their gateway.

## Upstream gateway

In side gateway mode, devices reach the proxy by naming this box as their gateway, and the network's own router keeps handing out leases. **Upstream gateway** holds that router's address, where the box sends what it forwards. **Apply upstream gateway** rewrites the default route and reloads the firewall.

## Interface roles

In router mode, each interface has a tab, and its **Role** is one of these:

| Role         | Meaning                      |
| ------------ | ---------------------------- |
| **WAN**      | An uplink to the internet    |
| **LAN**      | A network the gateway serves |
| **Split**    | A trunk sliced into VLANs    |
| **Disabled** | Left alone                   |

A WAN interface takes its address by **DHCP** from the upstream network, or by **Static** with an **Address**, a **Prefix length** and a **Gateway**. Under **Priority**, **Automatic** lets the gateway rank the uplinks, and **Prefer this one** puts this one first. **Backup only** keeps it for when no other uplink is left, and **Clone MAC** replaces its hardware address.

A LAN interface has a **Gateway address** and a **Prefix length**; the first served network is `192.168.8.0/24` with the box at `192.168.8.1` unless you change it. Select **Apply to** followed by the interface's name to apply one tab.

A **Split** trunk has its untagged traffic on the main interface, and one more interface per VLAN tag under **VLANs**. Each VLAN gets a tab of its own after you apply the trunk.

**Routing behavior** holds two switches for the whole gateway. **Spread traffic across uplinks** spreads connections across separate upstream lines. **Networks reach each other** lets devices on one served network reach devices on another. **Apply routing behavior** reloads the firewall and rebuilds the uplink routes.

## DHCP and DNS

On each served network the box gives its DHCP clients its own address as their gateway and resolver. The **DHCP** part of a LAN tab has these fields:

| Field                                | Meaning                                                                                |
| ------------------------------------ | -------------------------------------------------------------------------------------- |
| **Allocate address on this network** | whether the network hands out addresses                                                |
| **Range start**, **Range end**       | the pool, `.100` to `.200` unless you change it; the box's own address lies outside it |
| **Lease time**                       | a dnsmasq duration such as `12h`, `30m` or `1d`; `12h` by default                      |

The box answers DNS on every served network whether or not DHCP is on. On each of them, the name `hub.neutrino.internal` resolves to the box's address on that network. A server-mode box serves no network, so it runs neither DHCP nor DNS for others.

**Fixed addresses** binds a MAC address to one address in a network that hands out addresses:

1. Under **Fixed addresses**, select **Add address**.
1. Type the **MAC address**, or pick a discovered device from the list.
1. Type the **Address** and, optionally, a **Name**.
1. Select **Apply fixed addresses**.

A device holding a dynamic lease moves to its fixed address at its next renewal, and its name resolves on every served network.

## Wireless

A radio in the WAN role joins a network, and a radio in the LAN role publishes one.

To join a network, select **Scan for networks** on the radio's tab, pick the network, type its passphrase and select **Join**. Joining sets the interface to WAN.

**Known networks** lists the networks a WAN radio joins, preferring the one highest in the list. A network marked **needs a passphrase** has a key the hub cannot read; pick it from a scan to type one. **Forget** deletes the passphrase.

A LAN radio has an **Access point** with a **Network name**, a **Passphrase** and a **Band**. The passphrase has 8 to 63 characters, WPA2 only, and the band is 2.4 GHz or 5 GHz. A card with no access-point mode cannot take the LAN role.

## Exposure

**Exposure** lists the networks on which the box accepts connections to its own services: the panel, SSH, DNS and the shares. Each enabled overlay is one more entry, marked **overlay**. A SOCKS port and an overlay's peer port are reachable on the same networks.

1. Under **Exposure**, tick each network the box answers on.
1. Select **Apply exposure**. The page reports **Applied to the firewall.**

![The Exposure section](/guide/en/network_exposure.webp)

The apply bar warns before each kind of loss. An exposed uplink accepts connections from the internet on every port the box listens on. A network you untick stops reaching the box, and the warning counts the managed devices that reach the hub through it. Traffic the box forwards between networks is unaffected.

## Panel ports

The panel listens on two TCP ports on every exposed interface: **HTTP port**, `8080` unless setup chose another, and **HTTPS port**, `443` unless setup chose another. Both ports serve the panel whether HTTPS is on or off. Under each field the panel shows the address that port is reached at.

1. Under **Panel ports**, type the new **HTTP port**, the new **HTTPS port**, or both. The two must differ.
1. Select **Apply panel port**.

The panel restarts, and the page reads **Moving to** the new address on the scheme it was open on, where you sign in again. When that address is unreachable from where you are, the page reads **No answer at** that address. Whether the HTTP port sends browsers to the HTTPS port is set on [Settings](./settings.md#https).
