---
title: Network
---

# Network

The **Network** page sets what the hub box is to your network. It holds the box's shape, each interface's role, the addresses it gives out, and where it accepts connections. Each section has its own apply bar and changes only what that section shows.

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

On macOS and Windows the hub runs in server mode alone, and the page holds **Mode**, **Exposure** and **Panel ports**.

## Choose the shape

![The Mode section with the three shapes](/guide/en/network_modes.webp)

| Shape            | What it does                                       | Addresses on the machine     |
| ---------------- | -------------------------------------------------- | ---------------------------- |
| **Server**       | Serves on the networks it is connected to.         | kept as the machine set them |
| **Side gateway** | Forwards for hosts that name it as their gateway.  | kept as the machine set them |
| **Router**       | Routes between uplinks and the networks it serves. | set by the hub               |

The setup wizard also offers a one-arm router, which routes on one wired trunk: untagged out, a VLAN tag in. The page shows it as **Router**, with the trunk in the **Split** role.

To change the shape:

1. Under **Mode**, select the shape. The current one has the **active** badge.
1. Read the warning in the apply bar.
1. Select **Apply mode**.

Each change of shape has a cost, and the apply bar names it before you apply:

- Entering router mode moves the interfaces from the machine's own network manager to the hub. A DHCP uplink takes a new lease and can come back on a new address.
- Leaving router mode returns the interfaces to the machine's network manager. The served networks end, and their devices lose DHCP, DNS and their gateway.
- Leaving side gateway mode cuts off the hosts that named the box as their gateway.

A server that becomes a router keeps the exposure of each interface and starts with no roles. Before the router serves anything, pick a role for every exposed interface on its tab and apply it.

## Upstream gateway

In side gateway mode, a device reaches the proxy by naming this box as its gateway, and the network's own router keeps giving out leases. **Upstream gateway** holds that router's address, where the box sends what it forwards. Type the address and select **Apply upstream gateway**.

## Interface roles

In router mode each interface has a tab, and its **Role** is one of these:

| Role         | Meaning                      |
| ------------ | ---------------------------- |
| **WAN**      | An uplink to the internet    |
| **LAN**      | A network the gateway serves |
| **Split**    | A trunk sliced into VLANs    |
| **Disabled** | Stopped, with its link down  |

A WAN interface takes its address by **DHCP** from the upstream network, or by **Static** with an **Address**, a **Prefix length** and a **Gateway**. A static uplink has a **DNS** list under the gateway, one address or `address:port` per row. An empty list reads **Built-in resolvers: 223.5.5.5, 119.29.29.29**.

**Priority** ranks the uplinks. **Automatic** leaves the ranking to the gateway, **Prefer this one** puts this uplink first, and **Backup only** keeps it dark while another uplink is up. **Clone MAC** replaces the interface's hardware address.

A LAN interface has a **Gateway address** and a **Prefix length**. The first served network is `192.168.8.0/24`, with the box at `192.168.8.1`. Select **Apply to** followed by the interface's name to apply one tab.

A **Split** trunk keeps its untagged traffic on the main interface and adds one interface per tag under **VLANs**. Each VLAN gets a tab of its own after you apply the trunk.

**Routing behavior** holds two switches for the whole gateway. **Spread traffic across uplinks** spreads connections across separate upstream lines. **Networks reach each other** decides whether a device on one served network reaches a device on another. Select **Apply routing behavior** after changing either.

## DHCP and DNS

On each served network the box gives DHCP clients its own address as their gateway and resolver. The **DHCP** part of a LAN tab has these fields:

| Field                                | Meaning                                                                   |
| ------------------------------------ | ------------------------------------------------------------------------- |
| **Allocate address on this network** | whether the network gives out addresses                                   |
| **Range start**, **Range end**       | the pool, `.100` to `.200` by default; the box's own address lies outside |
| **Lease time**                       | a duration such as `12h`, `30m` or `1d`; `12h` by default                 |

The box answers DNS on every served network, with or without DHCP. On each of them, `hub.neutrino.internal` resolves to the box's address on that network. A server-mode box serves no network, so it runs neither DHCP nor DNS for other machines.

DNS works in two layers. The network layer forwards each query to the uplinks' resolvers: a DHCP uplink's come from its lease, and a static uplink's are its **DNS** rows. With several uplinks, their resolvers follow the uplinks' priority, and with none named the built-in pair answers. The resolver lists on the [Proxy](./proxy.md) page are a second layer for the traffic a proxy switch covers.

**Fixed addresses** gives a device the same address every time:

1. Under **Fixed addresses**, select **Add address**.
1. Type the **MAC address**, or pick a discovered device from the list.
1. Type the **Address** and, optionally, a **Name**.
1. Select **Apply fixed addresses**.

A device with a dynamic lease moves to its fixed address at its next renewal. Its name resolves on every served network.

## Wireless

A radio in the WAN role joins a network. On the radio's tab, select **Scan for networks**, pick the network, type its passphrase and select **Join**. Joining sets the interface to WAN.

**Known networks** lists the networks a WAN radio joins, the highest one in range first. A network marked **needs a passphrase** has a key the hub cannot read; pick it from a scan to type one. **Forget** deletes the stored passphrase.

A radio in the LAN role publishes a network from its **Access point** fields:

| Field            | What it takes                                                  |
| ---------------- | -------------------------------------------------------------- |
| **Network name** | the name devices see                                           |
| **Passphrase**   | 8 to 63 characters, WPA2 only                                  |
| **Country code** | two capital letters of the country the box is in, such as `DE` |
| **Band**         | **2.4 GHz**, or **5 GHz** after a country code is filled in    |

The 5 GHz band requires a country code, because the country's rules set which channels a radio uses. Without one the access point runs on 2.4 GHz. Choosing 5 GHz with no code makes the field read **Two letters, such as DE. 5 GHz needs one.** On apply the hub sets the system's wireless country and writes it into the access point's configuration. A card with no access-point mode cannot take the LAN role.

## Exposure

**Exposure** lists the networks on which the box accepts connections to its own services: the panel, SSH, DNS and the shares. Each overlay that is turned on adds a row marked **overlay**. A SOCKS port and an overlay's peer port are reachable on the same networks.

![The Exposure section](/guide/en/network_exposure.webp)

To change where the box answers:

1. Under **Exposure**, tick each network the box answers on.
1. Read the warnings in the apply bar.
1. Select **Apply exposure**. The section reads **Applied.**

The apply bar warns before each kind of loss. An exposed uplink accepts connections from the internet on every port the box listens on. An unticked network stops reaching the box, and the warning counts the managed devices that reach the hub through it.

On Linux, a card plugged in after setup appears with its switch off and the badge **New, not in use until turned on and applied**. It accepts nothing until you turn it on and apply. On macOS and Windows, an adapter the system adds counts as exposed until you untick it.

In router mode an exposed interface needs a role other than **Disabled**. Turning on a disabled interface puts a role choice in the same row: **WAN**, or **LAN** for a wired port. The hub rejects an exposed interface left at **Disabled** with `network_invalid`, and the message names the interface that cannot answer with that role.

## Panel ports

The panel listens on two TCP ports on every exposed interface: **HTTP port**, `8080` unless setup chose another, and **HTTPS port**, `443` unless setup chose another. Both ports serve the panel whether HTTPS is on or off. Under each field the page shows the address that port is reached at.

1. Under **Panel ports**, type the new **HTTP port**, the new **HTTPS port**, or both. The two must differ.
1. Select **Apply panel port**.

The panel restarts. The page reads **Moving to** the new address, where you sign in again. When that address is unreachable from where you are, the page reads **No answer at** it. Whether the HTTP port sends browsers to the HTTPS port is set under [HTTPS](./settings.md#https) on the **Settings** page.
