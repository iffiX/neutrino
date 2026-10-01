---
title: Android app
---

# Android app

The Android app joins a phone to your hubs with the client link from each hub's **Clients** page. The hub's virtual network, web pages, ports, AI gateway, shares and terminals then open on the phone. The hub side of the link, and what each client can use, is on [Clients](../hub/clients.md).

## Install the app

Before you start, check the phone:

- It runs Android 8.0 or newer.
- It has a 64-bit ARM processor. The release has one `arm64-v8a` apk.
- It reaches port 8443 on the hub.

To install:

1. On the phone, download `neutrino-client-0.5.0-android.apk` from the release.
1. Open the file. If Android shows a prompt, allow your browser or file manager to install apps.
1. Select **Install**, then open **Neutrino**.

The project signs every release apk with its own key, and Android updates an installed app only from an apk with the same key. To check a downloaded apk on a computer with the Android SDK build tools, run:

```bash
apksigner verify --print-certs neutrino-client-0.5.0-android.apk
```

```text
Signer #1 certificate SHA-256 digest: 0e20b8b4542f329c4d3ed91632f3ea90730cb99472c46c31585780d046ee612d
...
```

::: warning
If the digest differs, delete the apk. The release workflow checks the same digest before it attaches the file.
:::

## Join a hub

Before you start, create a client link in the hub's panel. Open **Clients**, select **New client link**, type a name for the phone, and select **Create link**. The notice shows the link with **Copy** and a QR code of the same link beside them. The link works for five minutes.

To join:

1. In the app, on the **Hubs** screen, select **Join a hub**.
1. Select **Allow the camera**, and allow it in the Android prompt.
1. Point the camera at the QR code on the hub's **Clients** page. The app joins as soon as it reads the code.

![The QR scanner on the Join a hub screen](/guide/en/app_join_scan.webp)

To paste instead, put the link into the field under **or** and select **Join**. The app rejects a link from the hub's **Devices** page with `link_not_for_client`, and an expired or spent link with `enroll_refused`.

To join another hub, select **Join a hub** again with that hub's link. Each hub keeps its own name for the phone and publishes its own services.

## Hubs

The **Hubs** screen holds one row per hub: its name, its state, its address and the package it runs. In portrait, a bar at the bottom opens **Hubs**, **Web**, **Ports**, **AI**, **Files**, **Terminals**, **Remote desktops** and **Settings**. In a wide horizontal window, a sidebar replaces the bar.

### Leave and reconnect

**Leave** on a row opens a confirmation, which names the hub and warns that the phone forgets its link and its key. Select **Leave** again to remove the hub, or **Cancel** to keep it. A row reading **Replaced by another client** also has **Reconnect**.

### Virtual network

A hub that publishes a virtual network shows a chip on its row. Select the chip to join, and select it again to leave. The first join opens Android's VPN connection request; select **OK** so the app can run NetBird or EasyTier inside Android's VPN service.

![A hub row with its virtual network chip](/guide/en/app_hub.webp)

The chip reads **joining…**, then **on** with NetBird or EasyTier and the phone's address on that network. The top bar of every screen shows **Virtual network** with that address, or **off**. When the join fails, the chip reads **failed** and the code shows under it.

The phone is on one hub's network at a time. Turning on the chip of a second hub turns off the first hub's chip.

When the hub publishes more than one network, a picker beside the chip names the one in use, NetBird or EasyTier. Picking the other moves the phone to it. When the hub's channel stays lost for 30 seconds, the app moves the phone to the hub's next network.

## Web

The **Web** screen lists the web pages the joined hubs publish. Select a row to open its address in the phone's browser.

A VS Code entry opens only from a desktop client, through that computer's localhost. On the phone its row is greyed, shows the **Desktop only** badge, and does not open.

## Ports

The **Ports** screen lists each port the hubs publish, with its address and port number. The phone forwards nothing: a program on the phone connects to that address directly. Select **Copy** to copy the address and port.

## AI

The **AI** screen shows one card per hub that runs an AI gateway. Each card holds the **Gateway address** and **This client's key**, each with **Copy**. The key shows its first six characters; the eye button shows or hides the rest.

Under them, a QR code holds the address, the key and the first model the gateway serves. A third-party chat app that takes an OpenAI-compatible endpoint can scan it. When the hub cannot open this phone's key, the card shows `vault_locked`.

## Files

The **Files** screen turns each share the hubs publish into a location in Android's Files app. A row without a saved password shows the **Password not saved** badge.

1. On the **Files** screen, select **Open in Files** on the share.
1. Pick or type the **Share username**, and type the **Share password**.
1. Keep **Remember** checked to keep the password in the Android Keystore. Unchecked, the app holds it until it stops.
1. Select **Connect**. The app tries the login on the share, then opens the share in Files.

![A share as a location in the Files app](/guide/en/app_files_provider.webp)

In Files, the share's location has the share's name, with the hub and the machine under it. You can open, write, create and delete files there, and a video plays while it reads. A share without a password reads **Give this share's password on the Files screen first.** A host that does not answer returns `share_unreachable`.

## Terminals

The **Terminals** screen opens a shell on a machine a hub manages. The hub's **Clients** page must let this phone open terminals.

1. Pick the machine among the chips on top. A green dot marks a machine that is online.
1. Select **New terminal**.

![A terminal with the key row](/guide/en/app_terminal.webp)

The shell opens in a tab named after the machine and a number. Under it, a row adds the keys a phone keyboard lacks: **Esc**, **Tab**, **Ctrl**, the four arrows and **Paste**. **Ctrl** stays lit until the next key you type, which it modifies. **Paste** sends the clipboard's text to the shell.

The **Persistent** switch under the shell keeps the session on the machine while the phone is away. A persistent tab returns when the app starts again, with the line **Detached; it attaches again once the hub answers.** Its **×** opens a confirmation; **End** stops the shell on the machine, and **Cancel** keeps it. [Terminals](../agent/terminals.md) covers the same sessions in the panel.

## Settings

On the **Settings** screen, pick the **Language** and the **Theme**, then select **Save**. **About** shows the app's version, its AGPL-3.0 licence, and the cores built into the app.
