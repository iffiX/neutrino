---
title: Samba
---

# Samba

The Samba module exports directories on a managed machine over SMB, and a client mounts one with a button. Its **Shares**, **Users** and **Now serving** sections open under the **File share** tab of [the Modules page](./modules.md), after **Configure** on the machine with the disk.

A machine that already serves SMB reads as **installed** on that tab, and the first **Configure** takes its existing shares and accounts as the hub's configuration.

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
