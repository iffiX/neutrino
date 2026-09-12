---
title: Services
---

# Services

This page follows a row on the **Services** page from its source to its button in a client window. It ends with declaring a row by hand. The badge on the page reads the healthy count against the total, **3 of 4 healthy** for example.

## Kinds and buttons

| Kind            | Group on the page | Where it comes from                            | The client's button        |
| --------------- | ----------------- | ---------------------------------------------- | -------------------------- |
| Web             | **Web**           | the Gitea module, or a declaration             | **Open**                   |
| Ports           | **Ports**         | a container's published port, or a declaration | **Connect**                |
| AI              | **AI**            | the hub's AI gateway                           | **Config**, then **Apply** |
| Files           | **Files**         | the Samba module, or a declaration             | **Config**, then **Mount** |
| Remote desktops | none              | a machine sharing its own desktop              | **Connect**                |

![The Services page with its four groups](/guide/en/services_list.webp)

![The client window with the five panels](/guide/en/client_connected.webp)

The page has four groups; a shared desktop is listed on clients and in the machine's drawer only. A row shows whether the source is **serving** or **not serving** and whether the hub finds it **reachable** or **unreachable**. A chip reads **module** when a module published the row and **declared** when a declaration did.

## Discovered entries

A module enabled on a device publishes without a declaration. The Samba module publishes each share as **published by the samba module on** that host. The Gitea module publishes its address, and a container publishes each host port it exposes. The hub's AI gateway publishes its endpoint. A machine publishes its desktop while `sudo nagent rdp start` is running on it; the entry disappears when the share stops.

## Declare a service by hand

A declaration publishes something the hub does not manage: a web page, a TCP port, or an SMB share on another server.

1. Select **Declare service**.
1. Fill **Name** and pick the **Kind**: **Web**, **Port** or **File**.
1. Fill **Host** and **Port**; a web kind adds a scheme and a path, and a file kind takes `445` when the port is left blank.
1. For a file kind, type a share name, or select **Scan host** to list the server's shares; each listed share is published as its own row.
1. Select **Declare**.

![The declare service form](/guide/en/services_add.webp)

A host of `127.0.0.1`, `0.0.0.0`, `::1` or `localhost` means the hub itself, and each machine receives it as the address it reaches the hub on. **Test** probes a declared row, and **Delete** removes the declaration with every row it published; the machine it points at is untouched.

## Each kind in the client

| Panel               | What the button does                                                                                           |
| ------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Web**             | **Open** opens the link in the default browser.                                                                |
| **Ports**           | **Connect** relays the port to `127.0.0.1` on the computer; **Disconnect** closes the relay.                   |
| **AI**              | **Config** picks the models per tool, **Apply** points the tools at the gateway or restores them.              |
| **Files**           | **Config** takes the share's login and a path or drive letter, **Mount** attaches it, **Unmount** detaches it. |
| **Remote desktops** | **Connect** opens the RustDesk viewer on that desktop.                                                         |

![The Ports panel forwarding a port](/guide/en/client_port_forwarding.webp)

![The Files panel's config form](/guide/en/client_files_config.webp)

![The Files panel with the share mounted](/guide/en/client_files_mounted.webp)

An unreachable row is greyed in the client and reads **not reachable now**. Each panel has a page of its own under **Client** in the sidebar.

## What the agent provides

The pages under **Agent** each enable one capability on a managed machine, and the pages that publish do so through the groups on this page:

| Page                          | What it does on a machine                                            |
| ----------------------------- | -------------------------------------------------------------------- |
| [Terminals](./terminals.md)   | opens a root shell, in tabs                                          |
| [Files](./files.md)           | browses, uploads, downloads and moves files                          |
| [Samba](./samba.md)           | serves SMB shares, published under **Files**                         |
| [Gitea](./gitea.md)           | runs a private git server, published under **Web**                   |
| [Containers](./containers.md) | runs declared containers, their host ports published under **Ports** |
| [ZFS](./zfs.md)               | builds pools and datasets, and shares a dataset through Samba        |
