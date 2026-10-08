---
title: NetBird
---

# Join the hub to NetBird

After this page, the hub is a peer on your NetBird network with the badge **connected**, and it holds a reusable setup key. The hub gives that key to every client allowed on the overlay, so each client that scans its link joins the same network. The mainland edition has no NetBird; use [EasyTier](./easytier.md) there.

Before you start, you need:

- A NetBird account at netbird.io, or a management server of your own.
- The **NetBird** card turned on and applied on the **Access** page. Until NetBird runs, its section reads **NetBird is not running yet.**

## Create a setup key several machines can use

The hub joins with this key and then gives the same key to its clients, so the key must accept many machines. Leave **Ephemeral Peers** and **Allow Extra DNS Labels** off while you fill the form.

<!-- 待核: NetBird console field names Make this key reusable, Usage limit, Expires in, Auto-assigned groups, Ephemeral Peers, Allow Extra DNS Labels, Create Setup Key, Copy (outline item 3) -->

![The Setup Keys list in the NetBird console](/guide/console/console_netbird_keys_list.webp)

To create the key:

1. In the NetBird console, open **Settings** > **Setup Keys**.
1. Select **Create Setup Key**.
1. Type a **Name**, such as the hub's name.
1. Turn on **Make this key reusable**.
1. Leave **Usage limit** empty for no limit, or set it to at least the number of clients plus one for the hub.
1. Set **Expires in** to the longest time the console offers.
1. Under **Auto-assigned groups**, create a group for the machines of this hub.
1. Select **Create Setup Key**.
1. Select **Copy** beside the key. The console shows the key only this one time.

![The Create Setup Key form filled in](/guide/console/console_netbird_key_create.webp)

![The new setup key, shown once](/guide/console/console_netbird_key_created.webp)

::: warning
The key from **Networks** > **Routing Peers** > **Add** > **Install NetBird** works one time. The hub uses it to join, and the second client to join with it fails with `overlay_join_failed`.
:::

## Join the hub

![The NetBird settings with the setup key saved](/guide/en/overlay_netbird_settings.webp)

The **Settings** part of the NetBird section repeats the console steps in three lines. The last one reads **Copy the key it shows once and paste it below.**

1. Select the **NetBird** card.
1. Under **Settings**, paste the key into **Setup key**.
1. Leave the management URL empty for netbird.io, or type the address of your own management server.
1. Select **Join**.

The badge beside **NetBird** reads **joining**, then **connected**. **Settings** then shows the hub's **Overlay address**, its **Name** and the **Management** address. **Setup key** reads **Saved**, with **Replace** and **Forget** beside it.

## Read the badge

| Badge                      | Meaning                                                                                                  |
| -------------------------- | -------------------------------------------------------------------------------------------------------- |
| **joining**                | The hub is signing in to the management server with the key.                                             |
| **connected**              | The hub is a peer on the network.                                                                        |
| **connecting**             | NetBird is connecting again, as after a restart.                                                         |
| **not joined**             | The hub has no NetBird identity, or its last login expired. Join again with a new setup key.             |
| **management unreachable** | The hub cannot reach the management server. Check this machine's uplink and DNS, and the management URL. |
| **not running**            | NetBird is stopped. Turn the card on and select **Apply access**.                                        |

## Replace the key clients get

A one-time key works for the hub's own join and fails for every client after that. To give clients a key they can use:

1. Create a reusable key as in [Create a setup key several machines can use](#create-a-setup-key-several-machines-can-use).
1. In the NetBird section, beside **Setup key**, select **Replace**.
1. Paste the new key.
1. Select **Save**.

The hub keeps its own NetBird identity and stays connected. Each client receives the new key with its next state from the hub. After **Forget**, no client can join this overlay until you save a key again.

## Publish the LAN subnets

**LAN routes** lists each network the hub serves. After you add such a network as a route in the NetBird console, a peer reaches its machines by their LAN addresses. A hub in server mode serves no network, and the list reads **No interface has the LAN role.**

![The LAN routes list with one served network](/guide/en/overlay_netbird_routes.webp)

The console steps are in [LAN devices over NetBird](../scenarios/netbird_lan_routes.md).

## Re-enroll or leave

The panel has no button that joins again in place. To give the hub a new NetBird identity:

1. In the NetBird section, select **Leave**.
1. In **Leave the NetBird network**, confirm. The hub is deleted from the network.
1. Paste a setup key into **Setup key** and select **Join**.
1. In the NetBird console, open **Peers** and delete the hub's old peer.

A person who reaches the hub only through NetBird loses that way in while the hub is out of the network. A phone that reinstalls the app registers as a new peer, and its old peer stays in **Peers** until you delete it.
