---
title: Overview
---

# Overview

Neutrino splits your machines by role. One hub runs the network and publishes services, agents host those services, and clients use them. This page places each role on your network and follows a service from the machine that hosts it to a button in the client.

## The hub's layers

The hub runs on Linux in any network shape, and in server mode on macOS and Windows. The hub box stacks its layers in the order of the table. Each layer needs only the layers before it, and the last three work in server mode.

| Layer         | What it is                                                                                                                                                                                            | When it is off                                              |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Network shape | Where the box is in your network. **Server** routes nothing, **Side gateway** forwards for hosts that name it as their gateway, and **Router** routes between its uplinks and the networks it serves. | Every box has one; server keeps the box's network as it is. |
| Access        | The ways in from outside: a private network across the internet on NetBird or EasyTier, or an SSH Relay on a server you own. Machines outside reach the box through any of them.                      | Only machines on your own network reach the box.            |
| Proxy         | One xray process with exit nodes imported from share links. It diverts the box's own traffic and its SOCKS ports, and in the routing shapes the devices behind it.                                    | Every connection leaves through the box's own uplink.       |
| AI gateway    | One endpoint, port 8317 by default, in front of API keys and subscription accounts, with a key and a usage count per client.                                                                          | Each AI tool keeps its own configuration.                   |

![The hub at the centre, reached over the overlay, driving agents, the AI gateway, storage and services](/guide/architecture.svg)

Only the router shape takes over the box's interfaces and serves networks of its own. Server and side gateway leave every address and every connection on the box as they are. [Network](./hub/network.md) describes each shape and how to change it.

With both overlay engines on, the hub keeps their networks apart. It rejects an engine whose network overlaps the other one or the box's own with `overlay_subnet_overlap`. It deletes a default route that an overlay pushes and shows `overlay_default_route_refused` on the page. [Access](./hub/overlay.md) covers each engine.

## Providers and consumers

Every module runs under an agent, on the machine that has what the module needs: the drives for the file share, the repositories for Gitea, the GPU for containers. A Linux machine runs every module. A Windows machine or a Mac runs the file share on the system's SMB server, VS Code, CloudCLI and a shared desktop, and a Mac also runs code-server. [Supported platforms](./reference/platforms.md) has the full table.

A client consumes what those machines provide. It opens a page, forwards a port, points AI tools at the gateway, mounts a share, connects to a desktop and opens a shell. `nhub setup` installs an agent on the hub's own box, so that box hosts modules as one managed machine among the others. The AI gateway is the one service the hub provides itself.

A client reaches every one of these services through the hub. Each connection to a port on the client's own loopback address becomes a stream to the hub's port 8443. The hub passes the stream to the agent of the machine that provides the service, or connects itself to the AI gateway and to a service declared by hand. The client therefore needs one address of the hub, on the LAN or through a way in from [Access](./hub/overlay.md), and no route to the machine itself.

The panel's sidebar follows the same split. Its **Hub** group, from **Dashboard** to **Settings**, acts on the box. Its **Agent** group, **Terminals**, **Files** and **Modules**, acts on one managed machine at a time.

## From a machine to a button

A service reaches a client from a module, from a declaration, or from the machine itself:

- A module publishes its own entries. The file share publishes each share, Gitea its address, VS Code, code-server and CloudCLI each instance, and a container each host port it publishes.
- The **Services** page publishes what you declare by hand: a web address, a TCP port, or an SMB share on a server the hub does not manage.
- A machine reports its own shared desktop while its **Remote desktop** switch on the Modules page is on.

Each entry has a kind, and the client draws one panel per kind with a button for each entry:

| Panel               | Published by                                                 | The client's button                                                           |
| ------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| **Web**             | Gitea, VS Code, code-server, CloudCLI, or a declared address | **Open**, which forwards the entry to `127.0.0.1` and opens it in the browser |
| **Ports**           | a container's published port, or a declared TCP port         | **Connect**, which forwards the port to `127.0.0.1`                           |
| **AI**              | the AI gateway                                               | **Configure**, and the switch **The AI tools use this gateway**               |
| **Files**           | the file share module, or a declared SMB share               | **Configure**, then **Mount**                                                 |
| **Remote desktops** | the machine's own agent                                      | **Connect**                                                                   |

The **Terminals** panel lists the managed machines this client can open a shell on, and **New terminal** opens one. The hub sends each client only the kinds and machines that its permissions on the **Clients** page allow. [Services](./hub/services.md) lists every entry the hub publishes, and [Desktop client](./client/desktop.md) shows each panel.

## The packages and protocol 3

One release tag publishes the hub, agent and client packages together:

| Package           | Runs on                                                                                    | Runs as                                                  |
| ----------------- | ------------------------------------------------------------------------------------------ | -------------------------------------------------------- |
| `neutrino-hub`    | one box: Linux on x86-64 or ARM64 in any network shape, or macOS or Windows in server mode | root, as the panel and its units; LocalSystem on Windows |
| `neutrino-agent`  | each managed machine: Linux, Windows 10 or 11, or macOS on Apple silicon or Intel          | a root service, LocalSystem on Windows, with no window   |
| `neutrino-client` | a person's Linux, Windows or macOS computer                                                | that person's own account                                |

The Android app is a separate apk of the same release. What has to match between all of them is the protocol number each build speaks, and every 0.5.0 package speaks protocol 3. A 0.5.0 hub accepts peers from its `PROTOCOL_MIN` to its `PROTOCOL`, both 3, and rejects any other with `protocol_too_old` or `protocol_too_new`. The rejected peer keeps its binding and connects again a minute later. An agent inside the range updates itself when the hub names a newer version.

An agent or client from 0.3 or 0.4 speaks protocol 1 or 2, so a 0.5.0 hub rejects it with `protocol_too_old`. Such a peer does not update itself. The hub's update reinstalls the agent on its own box, and you reinstall every other one. [Settings](./hub/settings.md) gives the upgrade order, hub first, and [The channel](./protocol/channel.md) holds the rules that move the number.
