---
title: The window
---

# The window

The window, titled **Neutrino client**, has a **Status** section and a **Services** section. This page names every part of both and covers connecting, disconnecting and the language.

## The status card

| The card reads              | Meaning                                                                                               |
| --------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Connected**               | joined, with the hub's address and `hub` followed by its version, and a **Disconnect** button         |
| **Not connected**           | not joined, with a field that takes the link from the hub's **Clients** page and a **Connect** button |
| **Reconnecting to the hub** | joined, and the hub is not answering right now; the client keeps trying by itself                     |
| **Switched off by the hub** | disabled on the **Clients** page; every button is greyed until the hub enables it again               |

![The window connected](/guide/en/client_connected.webp)

![The window before joining](/guide/en/client_disconnected.webp)

**Disconnect** leaves the hub, and the **Services** section then reads **Services appear once you join a hub.** From a terminal, `nclient connect '<link>'` joins, where `<link>` is the link from the **Clients** page, and `nclient disconnect` leaves.

## The five panels

**Services** draws five panels in a fixed order, whether or not each has entries: **Web**, **Ports**, **AI**, **Files** and **Remote desktops**. An empty panel reads a line such as **no port is published**. An entry the hub cannot reach right now is greyed and reads **not reachable now**. The line under each entry names its source:

| The line reads                              | The source                                   |
| ------------------------------------------- | -------------------------------------------- |
| **published by the Samba module on** a host | a Samba share on that host                   |
| **published by container** and its image    | a container's host port                      |
| **published by the AI gateway**             | the hub's AI gateway                         |
| **declared by hand**                        | a declaration on the hub's **Services** page |
| **shared from** a device                    | that device's desktop                        |

## Settings

1. Select **Settings** at the top of the window.
1. In the **Client settings** dialog, pick the **Language**, **English** or **中文**, and select **Save**.

![The client settings dialog](/guide/en/client_settings_language.webp)

The window's language is the client's own; the panel's language is set on the hub.

## The tray

Closing the window hides it, and the client keeps running. **Open** in the tray icon's menu shows the window again, and **Quit** stops the client. On Windows the icon is in the taskbar corner, on Linux in the indicator area of the panel, and on macOS in the menu bar. `nclient gui --hidden` starts the client in the tray with no window, and `nclient quit` stops it from a terminal.

![The tray menu on Windows](/guide/os/win_tray_flyout.webp)

## A different version

The three packages share one version number. A client newer than the hub is rejected with `client_newer_than_hub` and leaves the hub. Its window then reads that the hub is upgraded first and a fresh link pasted afterwards. A client older than the hub is offered an upgrade. A hub that was reset or reinstalled rejects the old binding with `hub_untrusted`, and a fresh link joins again.
