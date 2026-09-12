---
title: Samba
---

# Samba

SMB shares that clients mount with one button come from the Samba module on a managed machine. On the **Samba** page you enable the module on that machine and manage its **Users**, **Shares** and **Now serving**.

## Enable a device

1. In the panel, open **Samba** under **Agent**.
1. Under **Enabled devices**, tick the machine with the disk and select **Apply devices**. A consent dialog names the packages installed on that machine; confirm it.

![The Samba page with a share on one machine](/guide/en/samba_share.webp)

Unticking a machine and applying removes the module from it: the service stops and its packages are removed. The share directories and their files stay. An offline machine is rejected with `agent_offline`.

## Shares

A share is a directory on the machine, exported under a name:

1. Under **Shares**, select **Add share**.
1. Fill **Name** and **Path**, and a **Comment** if you want one.
1. Tick **Read only** to make the share read-only for everyone. Under **Who may use it**, pick the users the share accepts; with none picked, every user has it.
1. Select **Apply shares**. The server saves the shares and reloads.

Each share row has **Copy the address**, which copies its `smb://` address.

## Users

Users are the accounts a share accepts. **Add user** stages a name and a password together, and **Apply users** creates the accounts, sets the staged passwords and revokes the removed ones. To replace a password, remove the user and add it again.

## Now serving

**Now serving** lists the sessions open on the machine right now, with the client and the share each one holds. With no session open it reads **no share open**.

## Where it is published

Each share is a row under **Files** on [the Services page](./services.md), described as published by the samba module on that machine. In a client window it is an entry in the **Files** panel, mounted with **Config** and **Mount**. The mount is under the home directory on Linux and macOS, or on a drive letter on Windows.

![The client's Files panel with the share mounted](/guide/en/client_files_mounted.webp)
