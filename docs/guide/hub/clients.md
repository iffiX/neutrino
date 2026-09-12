---
title: Clients
---

# Clients

A client link is how a person's computer joins the hub. On the **Clients** page you make the link, and later switch that client off or delete it. This page also names what each button in the person's window does.

## What a client is

A client is one program on one computer, run by one person from a normal account; it consumes what the hub publishes and hosts nothing. The client runs on Linux, Windows and macOS, and rejects root with `root_refused`. Each link makes one client, so a computer that joins twice has two rows.

## Links, enable, disable and delete

1. Select **New client link**.
1. Type a name, such as the computer's own name, and select **Create link**.

![The new client link form](/guide/en/clients_create_link.webp)

The link is valid for five minutes, and the person pastes it into the window as [the client's install page](../client/install.md) shows.

![The clients table with platform, version and status](/guide/en/clients_table.webp)

The table shows each client's **Name**, **Hostname**, **Platform**, **Status**, **Version** and **Last seen**. **Disable** switches a client off. Its window then reads **Switched off by the hub** with every button greyed, until you select **Enable**. **Delete** revokes the client's gateway key and drops the client from the hub. The program on that computer joins again only with a new link.

## Each client's AI key

A client that joins is handed a gateway key named after it, listed under **Access** on [the AI page](./ai.md). The key arrives with each poll reply, so it is never typed by hand, and usage is metered per key. Revoking the key there makes the hub generate a new key and send it to the client at once.

## On the client's side

The window shows a status card and the five panels, one per kind; [the window page](../client/window.md) names every part of it.
