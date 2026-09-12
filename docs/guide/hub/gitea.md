---
title: Gitea
---

# Gitea

Gitea on a managed machine is a private git server that every client opens with one button. The **Gitea** page enables the module on a machine, then shows that machine's **Access** and **Administrator** sections.

## Enable a device

1. In the panel, open **Gitea** under **Agent**.
1. Under **Enabled devices**, tick the machine that keeps the repositories and select **Apply devices**. A consent dialog names what is installed; confirm it.

![The Gitea page with the module on one machine](/guide/en/gitea.webp)

## Access

**Access** holds the settings the hub writes into Gitea's `app.ini`: the port, the root URL and open registration. Repositories, accounts and everything else are managed in Gitea itself.

1. Set the **Port** Gitea listens on.
1. Set the **Root URL** that is written into clone addresses, or leave it empty to derive it from the machine's address.
1. Tick **Open registration** so that visitors can register their own accounts.
1. Select **Apply access**. The machine rewrites `app.ini` and restarts Gitea.

## Administrator

1. Under **Administrator**, fill a username, a password and an optional email.
1. Select **Create administrator**.

The button is available after the service has started. **Reset password** sets a new password for that administrator later; **Open Gitea** opens the server in a new tab.

## Where it is published

Gitea appears under **Web** on [the Services page](./services.md) as published by the gitea module on that machine. The client window lists it in the **Web** panel with an **Open** button.
