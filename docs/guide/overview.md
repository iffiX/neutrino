---
title: Overview
---

# Overview

Neutrino gives each of your machines one of three roles. The hub runs the network and publishes services. An agent hosts services on its own machine, and a client uses them from a person's computer or phone. This page places each role on your network and follows one service from the machine that hosts it to a button in the client.

## The hub's layers

The hub runs on Linux in any of its network shapes, and on macOS and Windows in the server shape alone. The table lists the shape and the three layers above it, and each row needs only the rows before it:

| Layer         | What it is                                                                                                                                                                                            | When it is off                                                    |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Network shape | Where the box is in your network. **Server** routes nothing, **Side gateway** forwards for hosts that name it as their gateway, and **Router** routes between its uplinks and the networks it serves. | Every box has a shape; a server keeps the box's network as it is. |
| Access        | The ways in from outside your network: **Direct** to the box's own addresses, **SSH Relay** through a server you own, and the virtual networks of **NetBird** and **EasyTier**.                       | Only machines on your own network reach the box.                  |
| Proxy         | One xray process with exit nodes imported from share links, in the full edition only. It diverts the box's own traffic, its SOCKS ports, and in the routing shapes the devices behind it.             | Every connection leaves through the box's own uplink.             |
| AI gateway    | One endpoint, port 8317 by default, in front of API keys and subscription accounts, with a key and a usage count for each client.                                                                     | Each AI tool keeps its own configuration.                         |

![At home, a server and a desktop each run an agent that dials the hub's port 8443; a phone away from home reaches the same port by one of four ways in](/guide/overview_many_machines.svg)

Only the router shape takes over the box's interfaces and serves networks of its own. Server and side gateway leave every address and every connection on the box as they are. [Network](./hub/network.md) describes each shape and how to change it.

Any number of ways in can be on at once, and a client uses whichever one reaches the hub. [Choose a way in](./scenarios/choose_a_way_in.md) compares them for your network.

## Providers and consumers

Each module runs under the agent of a machine that has what it needs, such as drives for a file share or a GPU for containers. A Linux machine runs every module. A Windows machine or a Mac runs the file share, the terminal, the remote desktop, Gitea, VS Code and CloudCLI. A Mac also runs code-server, and both systems serve the file share from their own SMB server. Containers and ZFS storage run on Linux alone.

[Supported platforms](./reference/platforms.md) has the full table of modules by system.

`nhub setup` also installs an agent on the hub's own machine, so that machine hosts modules beside the hub like any other managed machine. The AI gateway is the one service the hub provides itself.

A client reaches every service through the hub. Each connection to a port on the client's loopback address becomes a stream to the hub's port 8443. The hub passes the stream to the agent of the machine that provides the service. For the AI gateway and a declared service, the hub opens the connection itself.

A client therefore needs one address of the hub and no route to the machine itself. That address is on your network, or behind a way in from [Access](./hub/overlay.md).

The panel's sidebar follows the same split. Its **Hub** group, from **Dashboard** to **Settings**, acts on the hub. Its **Agent** group, **Terminals**, **Files** and **Modules**, acts on one managed machine at a time.

## From a machine to a button

A service reaches the clients from one of these sources:

- A module publishes its own entries. The file share publishes each share, Gitea its address, VS Code, code-server and CloudCLI each instance, and a container each port it publishes.
- The **Services** page publishes what you declare by hand: a web address, a port, or an SMB share on a server outside the hub's management.
- A machine publishes its own desktop while the **Remote desktop** switch on its **Modules** page is on.

Each entry has a kind, and the client draws one page per kind with a button on each entry:

| Client page         | Published by                                                 | The client's button                                                           |
| ------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| **Web**             | Gitea, VS Code, code-server, CloudCLI, or a declared address | **Open**, which forwards the entry to `127.0.0.1` and opens it in the browser |
| **Ports**           | a container's published port, or a declared port             | **Connect**, which forwards the port to `127.0.0.1`                           |
| **AI**              | the AI gateway                                               | **Configure**, and the switch **The AI tools use this gateway**               |
| **Files**           | the file share module, or a declared SMB share               | **Configure**, then **Mount**                                                 |
| **Remote desktops** | the machine's own agent                                      | **Connect**                                                                   |

The **Terminals** page lists the managed machines this client can open a shell on, and **New terminal** opens one. The hub sends each client only the kinds and the machines that its permissions on the **Clients** page allow. [Services](./hub/services.md) lists every entry the hub publishes.

## The packages and protocol 3

One release tag publishes all of the following together:

| Package           | Runs on                                                                                         | Runs as                                                   |
| ----------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `neutrino-hub`    | one machine: Linux on x86-64 or ARM64 in any network shape, or macOS or Windows in server shape | root; LocalSystem on Windows                              |
| `neutrino-agent`  | each managed machine: Linux, Windows 10 1809 or newer, or macOS 12.3 or newer                   | a service as root, LocalSystem on Windows, with no window |
| `neutrino-client` | a person's Linux, Windows or macOS computer                                                     | that person's own account                                 |
| the Android app   | a phone with Android 8.0 or newer, as `neutrino-client-0.5.0-android.apk`                       | an app of the phone's owner                               |

Between all of them, the protocol number each build speaks has to match, and every 0.5.0 build speaks protocol 3. A 0.5.0 hub accepts protocol 3 alone and rejects any other peer with `protocol_too_old` or `protocol_too_new`. The rejected peer stays joined and connects again a minute later. An agent the hub accepts updates itself when the hub names a newer version.

An agent or client from 0.3 or 0.4 speaks protocol 1 or 2, so a 0.5.0 hub rejects it with `protocol_too_old`. Moving a 0.4 hub to 0.5.0 means removing it and installing 0.5.0 fresh. You then install the 0.5.0 agents and clients, and join each one with a new link. [Settings](./hub/settings.md#coming-from-0-4) gives the order.
