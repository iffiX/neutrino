---
title: Network
---

# Network

The **Network** page holds the box's mode, the role of each interface, the addresses it gives out, and the networks it accepts connections on. Each section has its own apply bar. To turn a Linux hub into a router or a side gateway step by step, follow [Make the hub a router or side gateway](../scenarios/router_or_gateway.md).

| Section              | Shown in             |
| -------------------- | -------------------- |
| **Mode**             | every mode           |
| **Upstream gateway** | side gateway         |
| **Topology**         | router               |
| the interface tabs   | router               |
| **Fixed addresses**  | router, with a LAN   |
| **Known networks**   | router, with a radio |
| **Routing behavior** | router               |
| **Exposure**         | every mode           |
| **Panel ports**      | every mode           |

On macOS and Windows the hub runs in server mode only, and the page holds **Mode**, **Exposure** and **Panel ports**.

## Mode

![The Mode section with the three modes](/guide/en/network_modes.webp)

| Mode             | What it does                                       | Addresses on the machine     |
| ---------------- | -------------------------------------------------- | ---------------------------- |
| **Server**       | Serves on the networks it is connected to.         | kept as the machine set them |
| **Side gateway** | Forwards for hosts that name it as their gateway.  | kept as the machine set them |
| **Router**       | Routes between uplinks and the networks it serves. | set by the hub               |

The setup wizard also offers a one-arm router, which routes on one wired trunk. The page shows it as **Router**, with the trunk in the **Split** role. The current mode has the **active** badge, and the apply bar names the cost of a change before **Apply mode**.

## Upstream gateway

In side gateway mode, **Upstream gateway** holds the address of the network's own router, where the box sends what it forwards. Type the address and select **Apply upstream gateway**.

## Interface roles

In router mode each interface has a tab, and its **Role** is one of these:

| Role         | Meaning                      |
| ------------ | ---------------------------- |
| **WAN**      | An uplink to the internet    |
| **LAN**      | A network the gateway serves |
| **Split**    | A trunk sliced into VLANs    |
| **Disabled** | Stopped, with its link down  |

A WAN interface takes its address by **DHCP**, or by **Static** with an **Address**, a **Prefix length** and a **Gateway**. A static uplink has a **DNS** list, one address or `address:port` per row. An empty list reads **Built-in resolvers: 223.5.5.5, 119.29.29.29**.

**Priority** ranks the uplinks: **Automatic**, **Prefer this one**, or **Backup only**, which leaves the uplink unused while another one is up. **Clone MAC** replaces the interface's hardware address.

A LAN interface has a **Gateway address** and a **Prefix length**. The first served network is `192.168.8.0/24`, with the box at `192.168.8.1`. Select **Apply to** followed by the interface's name to apply one tab.

A **Split** trunk adds one interface per tag under **VLANs**, each with its own tab after you apply the trunk.

**Routing behavior** holds two switches for the whole gateway. **Spread traffic across uplinks** spreads connections across the uplinks. **Networks reach each other** sets whether a device on one served network reaches a device on another. Select **Apply routing behavior** to apply them.

## DHCP and DNS

The **DHCP** part of a LAN tab has these fields:

| Field                                | Meaning                                                                   |
| ------------------------------------ | ------------------------------------------------------------------------- |
| **Allocate address on this network** | whether the network gives out addresses                                   |
| **Range start**, **Range end**       | the pool, `.100` to `.200` by default; the box's own address lies outside |
| **Lease time**                       | a duration such as `12h`, `30m` or `1d`; `12h` by default                 |

The box answers DNS on every served network, and `hub.neutrino.internal` resolves to the box there. A box in server mode serves no network and runs neither DHCP nor DNS for other machines.

The box forwards each query to the uplinks' resolvers, in the uplinks' priority order, and to the built-in pair when no uplink names one. The resolver lists on the [Proxy](./proxy.md) page apply to the traffic a proxy switch covers.

**Fixed addresses** gives a device the same address every time. Select **Add address**, fill the **MAC address**, the **Address** and an optional **Name**, then select **Apply fixed addresses**. The device moves to that address at its next lease renewal.

## Wireless

A radio in the WAN role joins a network. On the radio's tab, select **Scan for networks**, pick the network, type its passphrase and select **Join**.

**Known networks** lists the networks a WAN radio joins, the highest one in range first. **Forget** deletes a stored passphrase.

A radio in the LAN role publishes a network from its **Access point** fields:

| Field            | What it takes                                                  |
| ---------------- | -------------------------------------------------------------- |
| **Network name** | the name devices see                                           |
| **Passphrase**   | 8 to 63 characters, WPA2 only                                  |
| **Country code** | two capital letters of the country the box is in, such as `DE` |
| **Band**         | **2.4 GHz**, or **5 GHz** after a country code is filled in    |

## Exposure

**Exposure** lists the networks on which the box accepts connections to its own services: the panel, SSH, DNS and the shares. Each overlay that is turned on adds a row marked **overlay**. SOCKS ports and an overlay's peer port follow the same list.

![The Exposure section](/guide/en/network_exposure.webp)

Tick each network the box answers on and select **Apply exposure**. The apply bar warns before each loss. An exposed uplink accepts connections from the internet on every port the box listens on. For an unticked network, the warning counts the managed devices that reach the hub through it.

On Linux, a card plugged in after setup appears switched off, with the badge **New, not in use until turned on and applied**. On macOS and Windows, an adapter the system adds counts as exposed until you untick it. In router mode an exposed interface needs a role other than **Disabled**.

## Panel ports

The panel listens on **HTTP port**, `8080` by default, and **HTTPS port**, `443` by default, on every exposed interface.

1. Under **Panel ports**, type the new **HTTP port**, the new **HTTPS port**, or both. The two must differ.
1. Select **Apply panel port**.

The panel restarts, and the page reads **Moving to** the new address, where you sign in again. A page that reads **No answer at** the new address is open from a network the box does not expose. [HTTPS](./settings.md#https) on the **Settings** page sets whether the HTTP port sends browsers to the HTTPS port.

A network setting the hub rejects shows a code; the codes are on [Troubleshooting](../reference/troubleshooting.md#network-settings-are-refused).
