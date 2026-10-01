---
title: File share
---

# File share

The **File share** module serves folders on a managed Linux, Windows or Mac machine over SMB, and every client mounts them with one button. On Linux it installs and runs Samba. On Windows and macOS it drives the SMB server the system already has, so **Install** downloads nothing there.

Before you start, select **Install** and then **Configure** on the **File share** tab of the [Modules](../modules.md) page. The **Shares**, **Users** and **Now serving** sections open under the tab.

## Add a share

1. Under **Shares**, select **Add share**.
1. Fill **Name** and **Path**, the folder on the machine.
1. Optional: fill **Comment**.
1. Optional: turn on **Read only** to refuse writes from everyone.
1. Under **Who may use it**, pick the users the share accepts.
1. Select **Apply shares**. The machine saves the shares and reloads its SMB server.

With no user picked, every account under **Users** has the share. On Windows, a share with no accounts at all is open to the machine's administrators only. The copy button beside a share's name copies its `smb://` address.

## Add users

Users are the accounts a client signs in with. **Add user** stages a name and a password together, and **Apply users** creates the accounts, sets the staged passwords and revokes the removed ones. To replace a password, remove the user and add it again.

A user row reads **created on apply** or **password set on apply** until you apply, then **ready**. Passwords exist only in the machine's own account store. After a restore from backup, a user reads **no password yet** until you add it again.

## Allowed subnets

The hub works out which networks a machine's shares answer. It takes them from the [Network](../../hub/network.md) page: the subnets the hub serves, its exposed interfaces and its exposed overlays. In the server shape, every network the box holds an address on counts. To change the list, change the **Network** page; when the network changes, the hub sends the new list to every online machine.

| System  | How the machine fences SMB to those subnets                                                      |
| ------- | ------------------------------------------------------------------------------------------------ |
| Linux   | Samba's `hosts allow`, with `127.0.0.1` added                                                    |
| Windows | a firewall rule named **Neutrino file share fence** that blocks TCP 445 from every other address |
| macOS   | a pf anchor, `com.apple/neutrino_smb`, loaded again each time the agent starts                   |

::: warning
On Windows and macOS the fence covers every share on the machine, including shares you made yourself outside the hub.
:::

## On Windows and macOS

The module changes only the shares and accounts it made, and leaves your own shares and accounts as they are. The first **Configure** takes over only the shares and accounts this module made earlier. The **Shares** section reads **This machine serves these shares with its system's own SMB server.**

![The File share tab of a Windows machine, with its shares](/guide/en/shares_windows.webp)

- On Windows, each account is local, in no group and hidden from the sign-in screen. It cannot sign in at the console or over Remote Desktop.
- On macOS, each account has no login shell and no home folder, and is hidden.
- **Uninstall** removes the module's shares, disables its accounts and deletes the fence.

macOS guards the Desktop, Documents and Downloads folders of every account. To share a folder inside one of them, add the SMB server under **System Settings** > **Privacy & Security** > **Full Disk Access**. A folder elsewhere, such as one under `/Users/Shared`, works as it is.

## Now serving

**Now serving** lists the connections open on the machine right now: the user, the client's name or address, and the shares it holds open. Under the list, a bar for each share shows how full its disk is. With nobody connected, the list reads **Nobody is connected.**

## Where it is published

Each share is a row under **Files** on the [Services](../../hub/services.md) page, described as published by the samba module on that machine. In the [Desktop client](../../client/desktop.md), it is an entry in the **Files** panel, mounted with **Config** and **Mount**. On Android, it is a location in the system's Files app.
