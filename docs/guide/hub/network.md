---
title: Network
---

# Network

The **Network** page holds the box's mode, the role of each interface, the addresses it gives out, which networks reach the hub's own ports, and the ports themselves. Each section has its own apply bar. To turn a Linux hub into a router or a side gateway step by step, follow [Make the hub a router or side gateway](../scenarios/router_or_gateway.md).

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
| **Ports**            | every mode           |

On macOS and Windows the hub runs in server mode only, and the page holds **Mode**, **Exposure** and **Ports**.

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

**Exposure** sets which senders reach the hub's own ports. A sender reaches them when its address is inside a segment switched on here: the IPv4 or the IPv6 networks of one interface, or one virtual network. The hub's own ports are these:

| Port                                                               | Present                         |
| ------------------------------------------------------------------ | ------------------------------- |
| the panel's **HTTP port** and **HTTPS port**                       | always                          |
| **Connection port**, 8443 by default, which agents and clients use | always                          |
| DNS, port 53 over UDP and TCP                                      | in router and side gateway mode |
| each SOCKS port of the [Proxy](./proxy.md) page                    | while the proxy has one         |

The AI gateway listens on the hub's loopback alone, so no chip covers it.

A chip is the on and off button of one segment. A chip switched on opens every port in the table to the senders in its segment. Each interface has two chips, one for its IPv4 segment and one for its IPv6 segment. Each running overlay adds one chip marked **overlay**, which starts switched on.

A chip names its interface and the networks of that family the interface holds addresses in, and in router mode its role, **lan** or **wan**. Direct opens the connection port alone to every sender, with no chip; turn it on on the [Access](./overlay.md#turn-on-direct) page.

![The Exposure section](/guide/en/network_exposure.webp)

To change the exposure:

1. Under **Exposure**, select a chip to switch it on or off.
1. Read the warnings in the apply bar.
1. Select **Apply exposure**. The section reads **Applied.**

For a chip switched off, the warning counts the managed devices that reach the hub across it. For a WAN chip switched on, it warns that every host in the uplink's networks then reaches the hub's ports. An IPv6 segment holds every IPv6 network the interface has an address in, the link-local `fe80::/64` among them, so a new IPv6 prefix keeps the chip's state.

On Linux, a card plugged in after setup appears with both chips off and the badge **New, not in use until turned on and applied**. On macOS and Windows, an adapter the system adds has both chips on until you switch them off. In router mode, switching on a chip of a port whose role is **Disabled** puts a role choice in the same row. **Apply exposure** writes the role with the exposure.

### Ports that open without a chip

These ports open with no chip, wherever they apply:

- the peer port of each running overlay engine, to every sender: NetBird's 51820 over UDP, and EasyTier's 11010 over TCP and UDP;
- DHCP, port 67 over UDP, on each network the hub gives addresses on.

The hub's rules leave every other port of the machine alone, in every mode. SSH, a file share and any service the hub does not run are the system firewall's to open or close. In router mode this covers SSH on the WAN. When the machine's SSH server listens on every address, close port 22 on the WAN in the system firewall.

### Where the rules go

| System  | The hub writes its rules into                                                                                      |
| ------- | ------------------------------------------------------------------------------------------------------------------ |
| Linux   | a chain of its own in the hub's nftables table, and, where firewalld runs, as on RHEL and Rocky, firewalld's zones |
| Windows | Windows Defender Firewall, one rule per port, each named `neutrino_hub_` and the port's purpose                    |
| macOS   | the pf anchor `com.apple/neutrino_hub`; the hub's programs are also allowed in the application firewall            |

**Apply exposure** writes the rules again, and so does a change of the addresses an exposed interface holds. `nhub reset network` and the removal of the hub package take them out.

## Ports

**Ports** holds the three TCP ports the hub listens on. The panel has **HTTP port**, `8080` by default, and **HTTPS port**, `443` by default. Agents and clients connect to **Connection port**, `8443` by default. The three must differ, and each accepts connections from the senders the **Exposure** chips let in.

### Change the panel's ports

1. Under **Ports**, type the new **HTTP port**, the new **HTTPS port**, or both.
1. Select **Apply ports**.

The panel restarts, and the page reads **Moving to** the new address, where you sign in again. A page that reads **No answer at** the new address is open from a network the box does not expose. [HTTPS](./settings.md#https) on the **Settings** page sets whether the HTTP port sends browsers to the HTTPS port.

### Change the connection port

Before you start, bring online every client and agent you want to keep. The hub gives the new port only to the ones online at that moment.

1. Under **Ports**, type the new **Connection port**.
1. Read the warning in the apply bar. It counts the clients and the agents offline now. Those lose this hub and join again with a new link from **Clients** or **Devices**.
1. Select **Apply ports**.

The hub sends the new address to every online client and agent, then restarts the panel's service, which takes agents and clients on the new port. The panel's own ports stay as they are; sign in again after the restart. With Direct on, the warning also says to change the router's port forward and Direct's **Public port** to match, on the [Access](./overlay.md#turn-on-direct) page.

A network setting the hub rejects shows a code; the codes are on [Troubleshooting](../reference/troubleshooting.md#network-settings-are-refused).
