---
title: Services
---

# Services

A service is one entry the hub publishes to clients: a web page, a port, the AI gateway, a share or a shared desktop. The **Services** page lists the entries the hub found on its own and lets you declare more by hand.

![The Services page with its Web, Ports, AI and Files groups](/guide/en/services_list.webp)

## Kinds and buttons

The page shows four groups. A shared desktop is the fifth kind, and it appears in the machine's drawer on the **Devices** page and in the clients.

| Kind           | Group on the page | Comes from                                     | Button in the desktop client |
| -------------- | ----------------- | ---------------------------------------------- | ---------------------------- |
| Web            | **Web**           | Gitea, VS Code, or a declaration               | **Open**                     |
| Port           | **Ports**         | a container's published port, or a declaration | **Connect**                  |
| AI             | **AI**            | the hub's AI gateway                           | **Config**                   |
| File           | **Files**         | the file share module, or a declaration        | **Mount**                    |
| Remote desktop | none              | a machine running `nagent rdp start`           | **Connect**                  |

A client sees only the kinds and devices its permissions allow, as set on [Clients](./clients.md). How each button behaves is on [Desktop client](../client/desktop.md).

## Discovered entries

A module the hub configures on a managed machine publishes its entries with no declaration. Each row says where it came from:

| Row description                                | Source                                         |
| ---------------------------------------------- | ---------------------------------------------- |
| **published by the samba module on** the host  | each share of the file share module            |
| **published by the gitea module on** the host  | the Gitea module's address                     |
| **published by the vscode module on** the host | one VS Code instance, for the account it names |
| **published by container** and the image       | each host port a container publishes           |
| **published by the AI gateway**                | the hub's AI gateway                           |

These rows have the **module** chip and follow the module's configuration on that machine.

## Local-only entries

A VS Code entry is local-only, marked `is_local_only` in what the hub sends: a browser opens it at the computer's own `127.0.0.1`. This page lists it under **Web** like any other row.

In the desktop client the entry's button reads **Open locally**. The client forwards the instance's port to its own `127.0.0.1`, fetches the instance's token from the hub, and opens the forwarded address in the browser. The Android app shows the entry greyed with a **Desktop only** chip. Setting up an instance is on [VS Code](../agent/modules/vscode.md).

## Declare a service by hand

A declaration publishes something the hub does not manage: a web page, a TCP port, or an SMB share on another server.

1. Select **Declare service**.
1. Fill **Name** and pick the **Kind**: **Web**, **Port** or **File**.
1. Fill **Host** and **Port**.
1. If the kind is **Web**, pick the **Scheme** and fill the **Path**.
1. If the kind is **File**, select **Scan host** to list the server's shares, or type each name under **Shares**.
1. Optional: fill **Description**.
1. Select **Declare**.

![The New declared service form](/guide/en/services_add.webp)

A file service with no port uses 445, and each share becomes its own row. A host of `127.0.0.1`, `localhost` or `0.0.0.0` means the hub itself. Each client receives it as the address it reaches the hub on.

**Delete** on a declared row removes the declaration and every row it published. The machine it points at is untouched.

## Health

The badge beside the title counts healthy rows against all rows, as **3 of 4 healthy**. Each row has a status dot and a state word:

| Source       | State words                                                    |
| ------------ | -------------------------------------------------------------- |
| **module**   | **serving**, **not serving**                                   |
| **declared** | **reachable**, **unreachable**, **checking…**, **not checked** |

The hub checks a declared row by connecting to it. It opens a TCP connection to a port, sends a GET to a web page, and reads a file server's share list. **Test** checks the row again now. A share the server hides from anonymous listing reads as healthy, with a line saying the name is not verified. In a client, an unhealthy entry is greyed and reads **not reachable now**.
