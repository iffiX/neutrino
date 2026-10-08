---
title: Choose a way in
---

# Which way in fits your network

A way in is the path a client or an agent away from home takes to port 8443 on your hub. The hub stays on your home LAN, beside the machines it manages. Each way in on the **Access** page gives an outside machine one more path to that port. The hub runs every way you turn on at the same time.

## Every feature uses one port

A client opens seven kinds of things through the hub: web pages such as VS Code and Gitea, ports, the AI gateway, files, terminals, remote desktops and the hub's panel. Each of them is a stream to the hub's port 8443. The hub connects the stream to the machine that serves it, through that machine's agent. All seven work with the hub's address alone.

So picking a way in means picking how an outside machine reaches 8443. The client's hub row names the path it took, such as **Connected · NetBird**.

## What each way in needs

| Way in                                   | What you prepare                                                                                                                                                                                                                                      | A step for each client                                                                     | Edition           |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ----------------- |
| **Direct**                               | At home, a client reaches one of the hub's interfaces. From outside, your home also needs a public IPv4 address and a router that forwards one public port to the hub's 8443. The **Public address** field on the **Direct** card holds that address. | none                                                                                       | both              |
| **SSH Relay**                            | A server with a public address that runs OpenSSH, with root access to change its SSH settings. Some providers limit forwarded traffic, so read their terms first.                                                                                     | none                                                                                       | both              |
| **NetBird**                              | A netbird.io account, or a NetBird management server of your own, and a reusable setup key.                                                                                                                                                           | none: the client link from the hub's **Clients** page includes the key                     | full edition only |
| **EasyTier**, **EasyTier console**       | An EasyTier console account. The console has a free tier.                                                                                                                                                                                             | after a client first connects, you attach it to the hub's network in the console, one time | both              |
| **EasyTier**, **Manual bootstrap peers** | The network's name and secret, which the panel generates. A client dials the hub's own uplink address, the address of its interface toward the internet, on port 11010. From outside, that address must be reachable on 11010.                        | none                                                                                       | both              |

The mainland edition has the **Direct**, **SSH Relay** and **EasyTier** cards, and the full edition adds **NetBird**. [Access](../hub/overlay.md) turns each way in on and sets it up.

## When a subnet route matters

A route matters only for a LAN device that runs no agent: a printer, your router's admin page, or the admin page of a NAS. A client opens such a device at the device's own LAN address, so the client needs a route to your LAN over a virtual network. Routes exist on NetBird and EasyTier; Direct and the SSH Relay reach only port 8443.

You set a route in the virtual network's own console. The hub's **Access** page lists the subnets the hub is on, for you to copy into that console. [Reach LAN devices without an agent through NetBird](./netbird_lan_routes.md) covers NetBird. [Reach LAN devices without an agent through EasyTier](./easytier_lan_routes.md) covers EasyTier, the one route page for the mainland edition.

## Find your page

| You have                                                       | Read                                                                   |
| -------------------------------------------------------------- | ---------------------------------------------------------------------- |
| One computer and a phone, and you use the phone away from home | [Quick start](../quick-start.md)                                       |
| A laptop at home that manages every machine on the same LAN    | [One laptop, every machine at home](./one_laptop_every_machine.md)     |
| A device without an agent that you open from outside           | the route page for your virtual network, named in the previous section |
