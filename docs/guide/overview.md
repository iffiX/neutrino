---
title: Overview
---

# Overview

Neutrino is a control plane for one person's machines. A hub runs on one always-on Linux box. An agent runs on each Linux machine the hub manages, and a client on each computer a person sits at. This page places each layer, separates the providers from the consumers, and follows a service from the hub to a button in a window.

## Four layers on one machine

The hub box has four layers, in the order of the table. Each layer needs only the layers before it.

| Layer         | What it is                                                                                                                                                 | Who needs it                                          |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| Network model | The box's shape. A server keeps the network as it is, a side gateway forwards for hosts that name it, and a router serves networks of its own.             | everyone; server mode is enough for every other layer |
| Overlay       | A private network across the internet, on NetBird or EasyTier, through which the box and the LAN behind it are reachable from outside.                     | anyone who leaves the building                        |
| Proxy         | The proxy engine, xray, on the box: exit nodes, SOCKS ports and split routing. It serves the box itself and, in the routing shapes, the devices behind it. | anyone with an exit node                              |
| AI gateway    | One endpoint on the box in front of API providers and subscription accounts, with a key per client and usage per key.                                      | anyone with several machines running AI tools         |

![The hub at the centre, reached over the overlay, driving agents, the AI gateway, storage and services](/guide/architecture.svg)

A server-mode hub keeps every address the machine had, so the first layer is the one choice that touches the rest of your network. [The Network page](./hub/network.md) describes the shapes.

## Providers and consumers

Every module runs under an agent, on the machine that has the disk or the GPU. Samba shares are on the machine with the drives, and Gitea on the one that keeps the repositories. Containers run on the one with the GPU, and a desktop is shared wherever a person is signed in. A client consumes what those machines provide: it mounts a share, opens a link, forwards a port and connects to a desktop. The hub's own machine runs an agent too, so it provides a module as one device among the others; the one service the hub provides by itself is the AI gateway.

The panel's sidebar draws the split: the **Hub** group is the box, and the **Agent** group is what the box drives on a machine running the agent.

## From the hub to a button

A service reaches a client window from a module, from a declaration, or from the machine itself. A module the hub configures on a device publishes its own entries: the Samba module publishes its shares, the Gitea module its address, a container its published host ports. The **Services** page publishes what you declare by hand: a web address, a TCP port, an SMB share on a server the hub does not manage. A machine reports its own shared desktop while `sudo nagent rdp start` is running on it.

Each entry has a kind, and the client draws one panel per kind:

| Kind            | Published by                                   | The client's button        |
| --------------- | ---------------------------------------------- | -------------------------- |
| Web             | the Gitea module, or a declaration             | **Open**                   |
| Ports           | a container's published port, or a declaration | **Connect**                |
| AI              | the AI gateway                                 | **Config**, then **Apply** |
| Files           | the Samba module, or a declaration             | **Config**, then **Mount** |
| Remote desktops | the machine's own agent                        | **Connect**                |

![The Services page with the Web, Ports, AI and Files groups](/guide/en/services_list.webp)

![The client window connected, with the five panels](/guide/en/client_connected.webp)

The Services page groups Web, Ports, AI and Files; a shared desktop appears on clients and in the device's drawer.

## Three packages, one tag

| Package           | Runs on                             | Runs as                          |
| ----------------- | ----------------------------------- | -------------------------------- |
| `neutrino-hub`    | one Linux box, x86-64 or ARM64      | root, as the panel and its units |
| `neutrino-agent`  | every Linux machine the hub manages | root, headless                   |
| `neutrino-client` | Linux, Windows and macOS            | a person's session               |

One tag releases the three packages together, and what has to match between them is the protocol number each build speaks, not its version. A hub admits an agent or a client whose number is between its own `PROTOCOL_MIN` and `PROTOCOL`, and rejects anything outside that range with `protocol_too_old` or `protocol_too_new`, after which the peer keeps its binding and tries again a minute later. The number moves only on a new minor version, and `config/` has no migrations, so [the Settings page](./hub/settings.md) gives the order: hub first, then agents, then clients. [The channel](./protocol/channel.md) holds the numbers and the rules that move them.

## The panel and this site

The panel has two page groups, and this site follows them. The **Hub** group (Dashboard, Network, Overlay, Proxy, AI, Devices, Clients, Services, Credentials, Settings) is the box itself. The **Agent** group (Terminals, Files, Modules) acts on one managed machine at a time. Both groups are under **Hub** in this site's sidebar, in the panel's order, because both are driven from the panel. Modules has one page per module here: Samba, Gitea, Containers and ZFS. The client's window has a group of its own, one page per panel plus the tray.

![The Dashboard with live traffic, active exits and DNS queries](/guide/en/dashboard.webp)
