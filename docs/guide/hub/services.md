---
title: Services
---

# Services

A service is one entry the hub publishes to clients: a web page, a port, the AI gateway, a share or a shared desktop. The **Services** page lists the entries the hub found on its own, and the ones you declare by hand.

![The Services page with its Web, Ports, AI and Files groups](/guide/en/services_list.webp)

## Kinds and buttons

Each kind has a group here and a page in the client:

| Kind           | Group on this page | Comes from                                              | Client page and button                     |
| -------------- | ------------------ | ------------------------------------------------------- | ------------------------------------------ |
| Web            | **Web**            | Gitea, VS Code, code-server, CloudCLI, or a declaration | **Web**: **Open**, in the browser          |
| Port           | **Ports**          | a container's published port, or a declaration          | **Ports**: **Connect**                     |
| AI             | **AI**             | the hub's AI gateway                                    | **AI**: **Configure** and the tools switch |
| File           | **Files**          | the file share module, or a declaration                 | **Files**: **Configure**, then **Mount**   |
| Remote desktop | none               | a machine whose **Remote desktop** switch is on         | **Remote desktops**: **Connect**           |

The client's **Terminals** page lists the managed machines it can open a shell on. Permissions on [Clients](./clients.md) set which kinds and devices a client sees. The client reaches every entry through the hub's port 8443 and dials none of the addresses this page shows.

## Discovered entries

A module on a managed machine publishes its entries by itself. These rows have the **module** chip, name the module and the host, and follow the module's configuration.

## Token entries

A VS Code, code-server or CloudCLI entry is a token entry. Its instance listens only on its own machine, so its address opens nothing in a browser.

Each time a person selects **Open** on such an entry, the client fetches a token from the hub for that one opening. A code-server or CloudCLI token lasts 60 seconds and works once. Setting up an instance is on [VS Code](../agent/modules/vscode.md).

## Declare a service by hand

A declaration publishes something the hub does not manage: a web page, a TCP or UDP port, or an SMB share on another server.

1. Select **Declare service**.
1. Fill **Name** and pick the **Kind**: **Web**, **Port** or **File**.
1. Fill **Host** and **Port**.
1. If the kind is **Port**, pick the **Protocol**: **TCP**, the default, or **UDP**.
1. If the kind is **Web**, pick the **Scheme** and fill the **Path**.
1. If the kind is **File**, select **Scan host** to list the server's shares, or type each name under **Shares**.
1. Select **Declare**.

![The New declared service form](/guide/en/services_add.webp)

A file service with no port uses 445. A host of `127.0.0.1`, `localhost` or `0.0.0.0` means the hub itself. A port number used on both protocols is declared twice. **Delete** removes a declaration and its rows.

## UDP ports

A UDP port is a **Port** entry of its own, from a declaration with the protocol **UDP** or from a container port published with `/udp`. A client forwards it to a UDP port on its own `127.0.0.1`, and a program there sends its datagrams to that address.

Every stream a client opens goes through one TCP connection to the hub. A lost packet therefore holds up every stream on that connection until it is sent again, the UDP ones too. A UDP port through the hub suits question-and-answer traffic of small volume: DNS, time, discovery, a small game server.

Voice, video and fast games need a direct path to the machine: a subnet route in the overlay's own console, NetBird's or EasyTier's.

## Health

Each row has a status dot and a state word:

| Source       | State words                                                    |
| ------------ | -------------------------------------------------------------- |
| **module**   | **serving**, **not serving**                                   |
| **declared** | **reachable**, **unreachable**, **checking…**, **not checked** |

A UDP port reads **not checked**, and clients can still use it. **Test** checks a row again now. In a client, an unhealthy entry is greyed and reads **not reachable now**.
