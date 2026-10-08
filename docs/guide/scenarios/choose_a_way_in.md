---
title: Choose a way in
---

# Which way in fits your network

A client away from home reaches your hub by Direct, the SSH Relay, NetBird or EasyTier, and each way in needs something different from you. A client dials only the hub's port 8443, and every way in leads to that port. You turn each one on with its card on the hub's **Access** page.

![The four cards on the Access page, all turned on](/guide/en/overlay_switches.webp)

## Compare the ways in

| Way in        | What you prepare                                                                                                | Suits                                                          | Set it up                                                |
| ------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------- |
| **Direct**    | A public IPv4 address at home, and a router that forwards one public port to the hub's 8443                     | a home line with its own public address                        | [Access](../hub/overlay.md#turn-on-direct)               |
| **SSH Relay** | A server of your own with a public address that runs OpenSSH                                                    | a home without a public address, with a VPS you rent           | [Reach home through your own VPS](./vps_relay.md)        |
| **NetBird**   | A netbird.io account or your own NetBird server, and a reusable setup key. The mainland edition has no NetBird. | a home without a public address; the client link holds the key | [Join the hub to NetBird](../hub/netbird.md)             |
| **EasyTier**  | An EasyTier console account, where you attach each client one time; or manual bootstrap peers                   | a home without a public address, in either edition             | [Put the hub on an EasyTier network](../hub/easytier.md) |

With manual bootstrap peers, EasyTier also needs port 11010 of the hub's uplink address open from outside. That takes a public address or a VPS.

## Run several at once

You can turn on several ways at once, and each client uses one that reaches the hub. Its hub row in the app or the client window names the way, such as **Connected · NetBird**.

To switch, turn the new way on beside the old one and set it up on its page. Then turn the old card off on **Access** and select **Apply access**. With the phone's Wi-Fi off, its hub row names the new way. Each card keeps its settings while off, so turning the old one on again brings it back.

## When you need a subnet route

A subnet route matters only for a LAN device that runs no agent, such as a printer or a NAS admin page. Direct and the SSH Relay reach port 8443 alone, so such a device needs NetBird or EasyTier. [Reach LAN devices without an agent through NetBird](./netbird_lan_routes.md) sets the route up on NetBird. [Reach LAN devices without an agent through EasyTier](./easytier_lan_routes.md) sets it up on EasyTier.
