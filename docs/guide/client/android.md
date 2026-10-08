---
title: Android app
---

# Android app

With the Android app joined to a hub, its screens open that hub's web pages, ports, AI gateway, shares, terminals and remote desktops. Every screen reaches its service through the hub's port 8443, on the LAN or from outside. [Install a client](../install/client.md) covers installing the app and joining a hub.

## Hubs

In portrait, a bar at the bottom opens **Hubs**, **Web**, **Ports**, **AI**, **Files**, **Terminals**, **Remote desktops** and **Settings**. With the phone turned sideways, and on a tablet at least 720 dp wide, a sidebar takes the bar's place.

The **Hubs** screen holds one row per hub: its name, its state, its address and the package it runs. While the channel is open, the state names its path. The states are **Connected · LAN**, **Connected · Direct**, **Connected · NetBird**, **Connected · EasyTier** or **Connected · SSH Relay**. A tag such as **48 ms** beside it shows the last round trip to the hub, measured every 20 seconds.

LAN means the phone reached the hub on a network the phone is on. Direct means the phone reached the hub from outside every network the hub is on, at an address the hub exposes. [Turn on Direct](../hub/overlay.md#turn-on-direct) describes that address. SSH Relay means the phone reached the public port of a server the hub's owner set up, as [SSH Relay](../hub/relay.md) describes.

While the channel is down, the line reads **Connecting…** as the app dials every address of the hub. When no address connects, the line names the reason, then `·` and what ends it:

| State line                                                  | Meaning                                                                                                                            |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **The hub did not answer · retrying in 5 s**                | no address answered; the app dials again at 0                                                                                      |
| **The hub is not on the virtual network · retrying in 5 s** | no address answered while the phone is on the hub's virtual network                                                                |
| **No network**                                              | the phone has no network; the app dials when a network comes up                                                                    |
| **Certificate mismatch · retrying in 60 s**                 | `hub_untrusted`, the hub's certificate differs from the one in the code; after a new install of the hub, leave and scan a new code |
| **The hub pauses new devices · retrying in 60 s**           | `admission_paused`, the hub holds back new devices for the time shown; the app joins again at 0                                    |
| **The hub does not know this device**                       | `binding_unknown`; **Leave** is the row's only button, and a new code joins again                                                  |
| **Version too old**                                         | `protocol_too_old` or `protocol_too_new`; update the app or the hub, then refresh                                                  |
| **Join refused ·** and the reason                           | the hub rejected the code's ticket, as with `ticket_spent`; **Leave** is the row's only button                                     |
| **Replaced by another client · Reconnect**                  | another client connected to the hub as this phone                                                                                  |
| **Disabled by the hub**                                     | the hub switched the phone off, and the line changes when the hub switches it on                                                   |

The seconds go down one at a time, and at 0 the line reads **Connecting…**. Between automatic tries the wait starts at 5 seconds and doubles up to 60. A try that connects, or a network change, sets it back to 5 seconds.

A network change ends every wait and every dial still open, and the app dials each hub again at once. Moving between mobile data and Wi-Fi counts, as do a virtual network connecting and the hub naming new addresses. A peer joining or leaving a connected virtual network counts too.

The refresh button at the top right does the same for every hub, and a connected hub sends back a fresh report. Rows reading **Replaced by another client** or **Disabled by the hub** stay as they are through both.

The dot is green while connected, pulsing amber while dialling, amber while a line counts down or depends on the hub, and red when you have to act. A hub the app has never reached shows a grey dot while it is stopped.

### Leave and reconnect

**Leave** on a row reads **Press again to leave** after one press, and a second press within five seconds removes the hub. The phone forgets the hub's link and key, and the hub's forwards and shares on the phone end.

A row reading **Replaced by another client** also has **Reconnect**, which takes the hub back from the other client.

### Panel

When the phone's permission on the hub's **Clients** page includes **Hub panel without the password**, the row has **Panel**. Select it to open the hub's panel in the phone's browser, through a forward on the phone, signed in. The panel opens wherever the app reaches the hub, so its own ports can stay on the LAN. A refusal such as `permission_denied` shows on the row's error line.

### Virtual network

A hub that publishes NetBird or EasyTier shows a **Virtual network** line under its row, with **Connect**.

1. Select **Connect**. The first time, Android shows its VPN connection request.
1. Select **OK** in that request, so the app can run NetBird or EasyTier inside Android's VPN service.

While the engine starts, the line reads **Connecting…** with **Logging in to** and the engine's name under it, and **Cancel** stops it. When the engine has an address, the line reads **Connected ·** and the phone's address, and the button becomes **Disconnect**.

![A hub row connected through EasyTier, with its virtual network line](/guide/en/app_hub.webp)

In EasyTier's console mode, the line stays at **Connecting…** with the reason **This machine is registered with the console. Attach it to a network there.** It stays there until whoever runs the hub's EasyTier console attaches the phone to the hub's network there, as [EasyTier](../hub/easytier.md) describes. The line then turns to **Connected ·** by itself, and **Cancel** ends the wait.

![The virtual network line waiting for the EasyTier console](/guide/en/app_hub_console_waiting.webp)

A failure returns the line to **Not connected** with the code under it. The phone is on one hub's network at a time. While one hub's network is on, **Connect** on another hub is greyed with the reason `overlay_other_network`.

When the hub publishes both engines, a picker beside the button names the one to use. The picker changes only while the line reads **Not connected**.

## Forwards

A forward is a port on the phone's `127.0.0.1` that the app opens for one entry. A foreground service of the app holds every forward and every hub connection, so they keep running while you use other apps. Its notification reads **Connected to** and the number of hubs. A forwarded row shows `→ 127.0.0.1:` and the port.

On the **Web** and **Ports** screens, **Configure** on a row sets the **Local port**. **Auto** keeps the entry's own port when it is free and otherwise takes one from 20000 up. **Fixed** takes a number from 1024 to 65535. **Configure** is greyed while the entry is forwarded.

A screen whose forward cannot reach its service shows the code on the row:

| Code                 | Meaning                                                                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `connect_failed`     | the hub or the machine could not connect to the service: `refused` (nothing listens on the port), `timeout` or `unreachable` |
| `agent_offline`      | the machine that provides the entry is not connected to the hub                                                              |
| `port_not_published` | the machine has stopped publishing that port                                                                                 |
| `connect_limit`      | this phone has 256 connections open through the hub; close some and try again                                                |
| `permission_denied`  | the phone's permission on the hub's **Clients** page leaves out that kind of entry, or that machine                          |
| `service_unknown`    | the hub no longer publishes the entry                                                                                        |

## Web

The **Web** screen lists the web pages the joined hubs publish: Gitea, VS Code, code-server, CloudCLI and addresses declared on a hub's **Services** page.

Select **Open** on a row. The app makes the entry's forward and opens the page in the phone's browser on `127.0.0.1`. A VS Code, code-server or CloudCLI entry gets a fresh token from the hub on every **Open**. **Disconnect** ends the forward.

## Ports

The **Ports** screen lists each port the hubs publish, with the machine's address and port for reference.

1. Select **Connect** on the entry. The row adds `→ 127.0.0.1:` and the local port.
1. Select **Copy**, and paste the loopback address into the app on the phone that uses the port.

A UDP entry reads `host:port/udp`, and **Copy** copies its loopback address without `/udp`. An app on the phone sends its datagrams to that local address and gets the replies there. Everything the app sends goes through one TCP connection to the hub, so a lost packet holds up every stream, UDP streams included.

## AI

The **AI** screen holds one row per hub that runs an AI gateway. Select **Connect** to forward the gateway to the phone. The forwarded row shows two loopback addresses, each with its own **Copy**:

| Label                                     | Address                                |
| ----------------------------------------- | -------------------------------------- |
| **For apps that add /v1 themselves**      | the gateway's address on `127.0.0.1`   |
| **For apps that want /v1 in the address** | the same address with `/v1` at the end |

Under them, **This client's key** shows the key behind an eye button, with **Copy**. Paste one address and the key into an app on the phone that takes an OpenAI-compatible endpoint.

The line under the row reads **The tools reach the gateway only while this client runs.** The loopback address works only while the app holds the forward. When the hub's vault is locked, the hub cannot open this phone's key, and the row shows `vault_locked`.

## Files

The **Files** screen turns each share the hubs publish into a location in Android's Files app. A share opens wherever the hub's row reads **Connected**. A row without a saved password shows the **Password not saved** badge.

1. On the **Files** screen, select **Open in Files** on the share.
1. Pick or type the **Share username**, and type the **Share password**.
1. Optional: clear **Remember**. Checked, the password stays in the Android Keystore; cleared, the app keeps it until it stops.
1. Select **Connect**. The app tries the login on the share, then opens the share in Files.

![A share as a location in the Files app](/guide/en/app_files_provider.webp)

In Files, the share's location has the share's name, with the hub and the machine under it. You can open, write, create and delete files there, and a video plays while it loads. A share without a password reads **Give this share's password on the Files screen first.** **Forget password** on the row reads **Press again to forget**, and a second press removes the saved password.

## Terminals

The **Terminals** screen opens a shell on a machine a hub manages. The phone's permission on the hub's **Clients** page must include terminals.

1. Pick the machine among the chips on top. A green dot marks a machine that is online.
1. Select **New terminal**.

![A terminal with the key row](/guide/en/app_terminal.webp)

The shell opens in a tab named after the machine and a number. Above the keyboard, a row adds the keys a phone keyboard lacks: **Esc**, **Tab**, **Ctrl**, **Shift**, **Alt** and the four arrows. A modifier stays lit until the next key you type. A long press on the shell opens **Copy**, **Paste** and **Clear**, and **Clear** sends Ctrl+C and empties the screen.

The **Persistent** switch under the shell keeps the session on the machine while no terminal is attached to it, for example after the app stops. A persistent tab returns when the app starts again, reading **Detached; waiting for the hub** until the hub is back. Its **×** reads **Press again to end** after one press, and a second press ends the shell on the machine. The panel lists the same sessions on [Terminals](../agent/terminals.md).

## Remote desktops

The **Remote desktops** screen opens the desktop a managed machine shares through its **Remote desktop** module on the hub.

1. Optional: select **Configure** on the entry, pick the **Codec** and the **Quality**, and select **Save**.
1. Select **Connect**. The viewer opens on the whole screen.

![The remote desktop viewer on a phone](/guide/en/app_rdp_viewer.webp)

Three round buttons sit at the top right of the picture. **Keyboard** raises the phone's keyboard. **Keys** shows a key bar with Esc, Tab, Ctrl, Shift, Alt, Win, **Paste** and the arrows. **Disconnect** ends the session.

Drag or pinch with two fingers to reach the part of the picture the keyboard covers.

## Settings

On the **Settings** screen, pick the **Language** and the **Theme**, then select **Save**. **About** shows the app's version, its AGPL-3.0 licence, and the cores built into the app.
