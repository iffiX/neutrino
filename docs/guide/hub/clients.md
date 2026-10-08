---
title: Clients
---

# Clients

A client is the program on one person's computer or phone that uses what the hub publishes. The **Clients** page admits each client with a link, sets what it can use, and switches it off or removes it.

## Make a client link

1. On **Clients**, select **New client link**.
1. Type a name that says whose program it is, such as `alice-laptop`.
1. Select **Create link**. The notice shows the link with **Copy**, and the same link as a QR code.

![The new client link with its Copy button and its QR code](/guide/en/clients_link_qr.webp)

The link works for 30 minutes and works one time. The hub keeps an unused link on disk, so it survives a restart of the hub within those 30 minutes. How the person installs the client and joins with the link is in [Install a client](../install/client.md).

The link and its QR code hold what the client needs to join the hub's virtual networks. That is the NetBird setup key, and the EasyTier secret or console address. A one-time NetBird key therefore lets one client join and fails for the next. To give clients a reusable key, follow [Join the hub to NetBird](./netbird.md).

A computer that joins again returns to the row it had, under the name in the new link. The page badge counts the clients online, as **2 of 3 online**.

## The client list

Each row shows the client's **Name**, **Hostname**, **Platform**, **Version**, **Status** and **Last seen**. A **disabled** chip marks a client that is switched off, and an **own permissions** chip marks one with permissions of its own.

## Permissions

**Default permissions**, at the top of the page, sets what every client without permissions of its own can use. **Permissions** on a row opens that client's drawer, where **Follow the default** stays on until you turn it off.

![One client's permissions with Follow the default off](/guide/en/clients_permissions_panel.webp)

Each kind has its own switch:

| Kind                               | What the client gets                                                                   |
| ---------------------------------- | -------------------------------------------------------------------------------------- |
| **Virtual network**                | joins the hub's overlay networks as a peer                                             |
| **Web pages**                      | the web entries, opened in a browser                                                   |
| **Ports**                          | TCP ports forwarded to the computer's `127.0.0.1`                                      |
| **AI gateway**                     | its own key and the gateway's address                                                  |
| **Files**                          | SMB shares to mount                                                                    |
| **Terminals**                      | shells on managed machines                                                             |
| **Remote desktops**                | the desktops machines share                                                            |
| **Hub panel without the password** | the **Panel** button on the client's hub row, which opens this panel already signed in |

Every kind but **Hub panel without the password** is on by default. That kind gives the client everything this panel can change, so turn it on only for a device of your own. Unlocking the vault still asks for the vault's passphrase, and changing the panel password still asks for the current one.

After changing switches, select **Apply permissions**. The hub sends the new list to that client, or to every client that follows the default.

## Device filters

Beside every switch but **Virtual network** and **Hub panel without the password**, a filter reads **All agents**. To narrow a kind to some machines:

1. Select the filter beside the kind.
1. Tick the managed devices whose entries the client can reach.
1. Select **Apply permissions**.

With no device ticked, the kind reaches every device. The hub's own services count as the hub box's device, and a declared service counts as the device at its address. Forgetting a device on the [Devices](./devices.md) page takes it out of every filter, and a kind whose filter named only that device is switched off.

## Each client's AI key

A client that joins gets a gateway key named `client/` followed by its name. The hub sends the key with the client's state, so nobody types it, and usage is counted per key on the **AI** page. **Revoke** there cuts the client off at once, and the hub gives it a new key.

## Disable or delete a client

**Disable** switches a client off. The hub revokes its gateway key, and the client's hub row reads **Disabled by the hub** with every entry greyed. **Enable** switches it back on with a new key.

**Delete** revokes the client's key and removes its row. The program on that computer loses the hub and joins again only with a new link.

Both actions end at once every connection the client holds: its terminals, its forwarded streams and its panel sessions.
