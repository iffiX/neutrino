---
title: Android app
---

# Android app

The Android app joins a phone to your hubs with the client link from each hub's **Clients** page. The hub's web pages, ports, AI gateway, shares, terminals and remote desktops then open on the phone. The hub side of the link, and what each client can use, is on [Clients](../hub/clients.md).

Every screen reaches its service through the hub. The app listens on the phone's loopback address, `127.0.0.1`, and sends each connection to the hub's port 8443, which connects it to the service. The phone needs that one port of the hub, on the LAN or from outside.

## Install the app

Before you start, check the phone:

- It runs Android 8.0 or newer.
- It has a 64-bit ARM processor. The release has one `arm64-v8a` apk.
- It reaches port 8443 on the hub: on the LAN, or from outside through one of the ways in that [Access](../hub/overlay.md) lists.

To install:

1. On the phone, download `neutrino-client-0.5.0-android.apk` from the release.
1. Open the file. If Android shows a prompt, allow your browser or file manager to install apps.
1. Select **Install**, then open **Neutrino**.

The apk of the mainland edition comes from the Gitee release page and has no NetBird core.

The project signs every release apk with its own key, and Android updates an installed app only from an apk with the same key. To check a downloaded apk on a computer with the Android SDK build tools, run:

```bash
apksigner verify --print-certs neutrino-client-0.5.0-android.apk
```

```text
Signer #1 certificate SHA-256 digest: 0e20b8b4542f329c4d3ed91632f3ea90730cb99472c46c31585780d046ee612d
...
```

Build tools 37 and newer print the line as `V2 Signer: certificate SHA-256 digest: …`; the digest is the same.

::: warning
If the digest differs, delete the apk. The release workflow checks the same digest before it attaches the file.
:::

## Join a hub

Before you start, create a client link in the hub's panel. Open **Clients**, select **New client link**, type a name for the phone, and select **Create link**. The notice shows the link with **Copy** and a QR code of the same link beside them. The link works for thirty minutes, also across a restart of the hub.

To join:

1. In the app, on the **Hubs** screen, select **Join a hub**.
1. Select **Allow the camera**, and allow it in the Android prompt.
1. Point the camera at the QR code on the hub's **Clients** page. The app joins as soon as it reads the code.

![The QR scanner on the Join a hub screen](/guide/en/app_join_scan.webp)

To paste instead, put the link into the field under **or** and select **Join**. The field rejects a link from the hub's **Devices** page with `link_not_for_client`.

The hub's row appears at once. On mobile data far from home, it reads **Joined; the hub has not been reached yet** until one address in the link answers. A spent or expired link puts the row in **Not connected** with `ticket_spent`; leave the hub and scan a fresh link. After too many failed joins on the hub, the row shows `admission_paused` and the app joins again after the seconds that code names.

To join another hub, select **Join a hub** again with that hub's link. Each hub keeps its own name for the phone and publishes its own services.

## Hubs

The **Hubs** screen holds one row per hub: its name, its state, its address and the package it runs. In portrait, a bar at the bottom opens **Hubs**, **Web**, **Ports**, **AI**, **Files**, **Terminals**, **Remote desktops** and **Settings**. In landscape, and on a tablet at least 720 dp wide, a sidebar replaces the bar.

While the channel is open, the state names the way it reached the hub: **Connected · LAN**, **Connected · NetBird**, **Connected · EasyTier** or **Connected · Relay**. Relay means the phone reached the public port of a server the hub's owner set up, as [Relay](../hub/relay.md) describes.

### Leave and reconnect

**Leave** on a row reads **Press again to leave** after one press, and a second press within five seconds removes the hub. The phone forgets the hub's link and key, and the hub's forwards and shares on the phone end. A row reading **Replaced by another client** also has **Reconnect**.

### Panel

When the hub's **Clients** page allows **Hub panel without the password**, the row has **Panel**. Select it to open the hub's panel in the phone's browser, through a forward on the phone, already signed in. The switch is off until somebody turns it on for this phone, and a refusal such as `permission_denied` shows on the row's error line. The panel opens wherever the app reaches the hub, so its own ports can stay on the LAN.

### Virtual network

The screens of the app need only the hub's port 8443, so a virtual network is one way in among the others. A hub that publishes NetBird or EasyTier shows a **Virtual network** line under its row, with **Connect**.

![A hub row with its virtual network line](/guide/en/app_hub.webp)

1. Select **Connect**. The first time, Android shows its VPN connection request.
1. Select **OK** in that request, so the app can run NetBird or EasyTier inside Android's VPN service.

The line reads **Connecting…** with **Logging in to** and the engine under it, then **Waiting for the hub** with the seconds counted. It reads **Connected ·** and the phone's address when the hub is reachable through the network, and the button becomes **Disconnect**. **Cancel** stops a connect that is still running. A failure returns the line to **Not connected** with the code under it.

The phone is on one hub's network at a time. While one hub's network is on, **Connect** on another hub is greyed with the reason `overlay_other_network`. When the hub publishes both engines, a picker beside the button names the one to use, and it changes only while the line reads **Not connected**.

## Forwards

A forward is the port on the phone's `127.0.0.1` that the app opens for one entry. A foreground service of the app holds every forward and every hub connection, so they keep running while you use other apps; its notification reads **Connected to** and the number of hubs. A forwarded row shows `→ 127.0.0.1:` and the port.

On the **Web** and **Ports** screens, **Configure** on a row sets the **Local port**: **Auto** keeps the entry's own port when it is free and otherwise takes one from 20000 up, and **Fixed** takes a number from 1024 to 65535. **Configure** is greyed while the entry is forwarded.

A screen whose forward cannot reach its service shows the code on the row:

| Code                 | Meaning                                                                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `connect_failed`     | the hub or the machine could not connect to the service: `refused` (nothing listens on the port), `timeout` or `unreachable` |
| `agent_offline`      | the machine that provides the entry is not connected to the hub                                                              |
| `port_not_published` | the machine does not publish that port now                                                                                   |
| `connect_limit`      | this phone has 256 connections open through the hub; close some and try again                                                |
| `permission_denied`  | the hub's **Clients** page does not let this phone use that kind of entry, or that machine                                   |
| `service_unknown`    | the hub no longer publishes the entry                                                                                        |

## Web

The **Web** screen lists the web pages the joined hubs publish: Gitea, VS Code, code-server, CloudCLI and addresses declared on the hub's **Services** page.

Select **Open** on a row. The app makes the entry's forward and opens the page in the phone's browser on `127.0.0.1`. A VS Code, code-server or CloudCLI entry gets a fresh token from the hub on every **Open**. **Disconnect** ends the forward.

## Ports

The **Ports** screen lists each port the hubs publish, with the machine's address and the port for reference.

1. Select **Connect** on the entry. The row adds `→ 127.0.0.1:` and the local port, and the button reads **Disconnect**.
1. Select **Copy** to copy that loopback address, and paste it into the app on the phone that uses the port.

## AI

The **AI** screen holds one row per hub that runs an AI gateway. Select **Connect** to forward the gateway to the phone, and **Copy** beside **Disconnect** copies its loopback address. Under the row, **This client's key** shows the key behind an eye button, with **Copy**.

Paste the address and the key into an app on the phone that takes an OpenAI-compatible endpoint. The line under the row reads **The tools reach the gateway only while this client runs.**: the loopback address answers only while the app holds the forward. When the hub cannot open this phone's key, the row shows `vault_locked`.

## Files

The **Files** screen turns each share the hubs publish into a location in Android's Files app. The app reaches the share through the hub, so a share opens wherever the hub's row reads **Connected**. A row without a saved password shows the **Password not saved** badge.

1. On the **Files** screen, select **Open in Files** on the share.
1. Pick or type the **Share username**, and type the **Share password**.
1. Keep **Remember** checked to keep the password in the Android Keystore. Unchecked, the app holds it until it stops.
1. Select **Connect**. The app tries the login on the share, then opens the share in Files.

![A share as a location in the Files app](/guide/en/app_files_provider.webp)

In Files, the share's location has the share's name, with the hub and the machine under it. You can open, write, create and delete files there, and a video plays while it reads. A share without a password reads **Give this share's password on the Files screen first.** A host that does not answer returns `share_unreachable`. **Forget password** on the row reads **Press again to forget**, and a second press removes the saved password.

## Terminals

The **Terminals** screen opens a shell on a machine a hub manages. The hub's **Clients** page must let this phone open terminals.

1. Pick the machine among the chips on top. A green dot marks a machine that is online.
1. Select **New terminal**.

![A terminal with the key row](/guide/en/app_terminal.webp)

The shell opens in a tab named after the machine and a number. Above the keyboard, a row adds the keys a phone keyboard lacks: **Esc**, **Tab**, **Ctrl**, **Shift**, **Alt** and the four arrows. A modifier stays lit until the next key you type, which it modifies. A long press on the shell opens **Copy**, **Paste** and **Clear**. **Clear** sends Ctrl+C and empties the screen, and the terminal reads **Clearing…** until the shell's output has been quiet for half a second.

The **Persistent** switch under the shell keeps the session on the machine while the phone is away. A persistent tab returns when the app starts again, with the line **Detached; waiting for the hub**. Its **×** reads **Press again to end** after one press, and a second press ends the shell on the machine. [Terminals](../agent/terminals.md) covers the same sessions in the panel.

## Remote desktops

The **Remote desktops** screen opens the desktop a managed machine shares with `sudo nagent rdp start`.

1. Optional: select **Configure** on the entry, pick the **Codec** and the **Quality**, and select **Save**.
1. Select **Connect**. The viewer opens on the whole screen.

Three round buttons at the top right stay on the picture: the first raises the keyboard, the second shows the key bar with Esc, Tab, Ctrl, Shift, Alt, Win, **Paste** and the arrows, and the third ends the session. Pinch and drag with two fingers to reach the part of the picture the keyboard covers.

## Settings

On the **Settings** screen, pick the **Language** and the **Theme**, then select **Save**. **About** shows the app's version, its AGPL-3.0 licence, and the cores built into the app.
