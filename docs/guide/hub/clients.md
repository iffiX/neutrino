---
title: Clients
---

# Clients

A client is the program on one person's computer or phone that uses what the hub publishes. On the **Clients** page you admit each one with a link, choose what it can use, and switch it off or remove it.

## Make a client link

1. On **Clients**, select **New client link**.
1. Type a name that says whose program it is, such as `alice-laptop`.
1. Select **Create link**. The notice shows the link with **Copy**, and the same link as a QR code beside them.

![The new client link with its Copy button and its QR code](/guide/en/clients_link_qr.webp)

The link works for thirty minutes and is used once. The hub keeps an unused link on disk, so a restart of the hub within those thirty minutes leaves it working. On a phone, the person scans the QR code with the app. On a computer, the person pastes the link into the client window, or runs `nclient join` with it in a terminal. Installing and joining are on [Desktop client](../client/desktop.md) and [Android app](../client/android.md).

A computer that joins again returns to the row it already had, under the name in the new link. The page badge reads how many clients are online, as **2 of 3 online**.

## The client list

Each row shows the client's **Name**, **Hostname**, **Platform**, **Version**, **Status** and **Last seen**. A **disabled** chip marks a client that is switched off, and an **own permissions** chip marks one that does not follow the default.

## Permissions

**Default permissions**, at the top of the page, sets what every client without permissions of its own can use. **Permissions** on a row opens one client's drawer, where **Follow the default** is on until you turn it off.

Each kind has its own switch:

| Kind                | What the client gets                                                                 |
| ------------------- | ------------------------------------------------------------------------------------ |
| **Virtual network** | joins the hub's overlay networks as a peer                                           |
| **Web pages**       | the web entries, opened in a browser                                                 |
| **Ports**           | TCP ports forwarded to the computer's `127.0.0.1`                                    |
| **AI gateway**      | its own key and the gateway's address                                                |
| **Files**           | SMB shares to mount                                                                  |
| **Terminals**       | shells on managed machines                                                           |
| **Remote desktops** | the desktops machines share                                                          |
| **Hub panel**       | the **Panel** button on the client's hub row, which opens this panel through the hub |

Every kind is on by default. **Hub panel** opens the panel's sign-in page and nothing more; the panel password still guards it.

After changing switches, select **Apply permissions**. The hub sends the new list to that client, or to every client that follows the default.

## Device filters

Beside every switch but **Virtual network** and **Hub panel**, a filter reads **All agents**. To narrow a kind:

1. Select the filter beside the kind.
1. Tick the managed devices whose entries the client can reach.
1. Select **Apply permissions**.

With no device ticked, the kind reaches every device. The hub's own services count as the hub box's device, and a declared service counts as the device at its address. Forgetting a device on [Devices](./devices.md) takes it out of every filter, and a kind whose filter named only that device is switched off.

## Each client's AI key

A client that joins gets a gateway key named `client/` followed by its name. The hub sends the key with the client's state, so nobody types it, and usage is counted per key under **Access** on [AI](./ai.md). **Revoke** there cuts the client off at once, and the hub gives it a new key.

## Disable or delete a client

**Disable** switches a client off. The hub revokes its gateway key, and its hub row reads **Disabled by the hub** with every entry greyed. **Enable** switches it back on with a new key.

**Delete** revokes the client's key and removes its row. The program on that computer loses the hub and joins again only with a new link.
