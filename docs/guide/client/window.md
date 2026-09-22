---
title: The window
---

# The window

The window, titled **Neutrino client**, has a **Hubs** section and a **Services** section. Each hub this computer has joined holds one row in the first and one group of panels in the second. This page names every part of both.

## The Hubs section

Each row holds one hub: its name, the state it is in, its address and the package the hub runs. Each row has the **Target** radio and **Leave**. A row reading **Replaced by another client** has **Reconnect** as well, and every button acts on that hub and no other. The **Join a hub** row under them stays whether or not any hub is joined, and takes a link from any hub's **Clients** page.

![The window with a hub joined](/guide/en/client_connected.webp)

| The row reads                  | Meaning                                                                                        |
| ------------------------------ | ---------------------------------------------------------------------------------------------- |
| **Connected**                  | the channel to that hub is open and its services are in the **Services** section               |
| **Reconnecting to the hub**    | the binding is kept and the channel is down; the client opens it again on its own              |
| **Switched off by the hub**    | that hub's **Clients** page has this client switched off, and its panels are inert             |
| **Replaced by another client** | a second client took this binding, and the channel stays closed until you select **Reconnect** |

The client keeps every address a hub listens on, and a state from that hub updates the list. While the channel is down, the client connects to each address in turn, the name `hub.neutrino.internal` first on a network the hub serves. The **↻** button beside each section title sends every connected hub a report now and starts a connection round on every hub whose channel is down.

**Leave** removes that hub's row and its group at once and undoes everything it published on this computer: its mounts, its forwards and its viewers. The client then posts the leave to the hub, and every other hub is untouched. From a terminal, `nclient join '<link>'` joins a hub and `nclient leave --hub <name>` leaves one, where the name is the one in its row.

![The window with no hub joined](/guide/en/client_disconnected.webp)

## The target hub

One hub of those joined is the target, and your AI tools point at that hub's gateway. The **Target** radio on a row makes that hub the target. Its row then reads **the AI tools point at this hub**, and every other hub's AI panel names the hub they point at instead.

The first hub joined is the target until another is chosen. Leaving the target hub moves the target to the next hub joined. Only a row reading **Connected** takes the radio, and a hub whose channel is down is rejected with `no_exit_hub`. The [AI page](./ai.md) covers what the tools are pointed at.

## The Services section

Each hub's group opens with **Published by** and the hub's name. It draws five panels in a fixed order, whether or not each has entries: **Web**, **Ports**, **AI**, **Files** and **Remote desktops**. An empty panel reads a line such as **no port is published**. An entry the hub cannot reach right now is greyed and reads **not reachable now**. A group whose hub is not connected reads that hub's state in place of its panels.

The line under each entry names its source:

| The line reads                              | The source                                   |
| ------------------------------------------- | -------------------------------------------- |
| **published by the Samba module on** a host | a Samba share on that host                   |
| **published by container** and its image    | a container's host port                      |
| **published by the AI gateway**             | the hub's AI gateway                         |
| **declared by hand**                        | a declaration on the hub's **Services** page |
| **shared from** a device                    | that device's desktop                        |

## Settings

1. Select **Settings** at the top of the window.
1. In the **Client settings** dialog, pick the **Language**, **English** or **中文**, and the **Theme**, **System**, **Dark** or **Light**.
1. Select **Save**.

![The client settings dialog](/guide/en/client_settings_language.webp)

The window's language and theme are the client's own; the panel's are set on the hub. **System** takes the colour scheme from the desktop.

## The tray

Closing the window hides it, and the client keeps running with every hub joined. **Open** in the tray icon's menu shows the window again, and **Quit** stops the client. On Windows the icon is in the taskbar corner, on Linux in the indicator area of the panel, and on macOS in the menu bar. `nclient gui --hidden` starts the client in the tray with no window, and `nclient quit` stops it from a terminal.

![The tray menu on Windows](/guide/os/win_tray_flyout.webp)

## What a refusal does to the binding

A refusal keeps the binding. The row keeps its place, shows the code under the hub's name, and the client opens the channel again a minute later. One code ends the binding, and the row goes with it.

| The row shows      | What the code means                                              | The binding                                    |
| ------------------ | ---------------------------------------------------------------- | ---------------------------------------------- |
| `protocol_too_old` | this client speaks an older protocol number than the hub accepts | stays; install a newer client                  |
| `protocol_too_new` | this client speaks a newer protocol number than the hub speaks   | stays; upgrade that hub first                  |
| `hub_untrusted`    | the certificate at that address is not the one the link pinned   | stays; a hub that was reset takes a fresh link |
| `binding_unknown`  | that hub's **Clients** page no longer holds this client          | goes; a fresh link joins again                 |

Either protocol code prints the numbers, this client's and the hub's, so the row names the side that is behind. Package versions take no part in it, and a client and a hub on different versions that speak one protocol number stay connected.
