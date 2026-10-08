---
title: First step
---

# First step: install, join, reach it from outside

The first step installs the hub on your home computer, joins your phone and laptop to it, and connects them from outside through NetBird. It takes about ten minutes. Each service on the computer opens on a later page. Your Claude Code sessions, for one, open in [Your AI session on the phone](./quick-start/cloudcli.md).

## Before you start

- Your computer stays on and runs one of these systems:
  - Linux with a desktop: Debian 12 or newer, Ubuntu 22.04 or newer, Fedora 41 or newer, or the RHEL 9 family
  - macOS 12.3 or newer
  - Windows 10 1809 or newer on x86-64
- You have an administrator account on the computer, and the computer reaches the internet.
- You have an Android phone (Android 8.0 or newer, 64-bit ARM), a laptop with one of these systems, or both.
- You have an account at netbird.io.
- The phone and the laptop are on the same Wi-Fi network as the computer.

For EasyTier, Direct or your own server, follow [EasyTier](./hub/easytier.md), [Turn on Direct](./hub/overlay.md#turn-on-direct) or [Reach home through your own VPS](./scenarios/vps_relay.md) in place of both NetBird sections.

## Install the hub

On Linux or macOS, open a terminal and run:

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

On Windows, open PowerShell and run:

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

The script prompts once for administrator rights. On Windows it goes on in a new PowerShell window that Windows opens as administrator. When the install ends, the terminal prints the wizard's address on each network the computer is on.

[Install the hub](./install/hub.md) has the mainland edition's command and the package files.

## Answer the wizard

Open the first address the terminal printed in a browser on the computer. Each screen ends in **Next**, and the wizard changes nothing until the last screen:

1. Select **Set this box up**.
1. On **Language**, keep **English**.
1. Type a **Panel password** of at least 8 characters, and type it again under **Again**.
1. Type a **Vault passphrase** of at least 16 characters, with lowercase and uppercase letters, digits and symbols, and type it again under **Again**.
1. Leave **HTTPS for the panel** off.
1. On **What is this machine for?**, select **Server**.
1. On **Which ports?**, keep the ports as they are.
1. On **Going out through a proxy**, leave **Set it up here** off.
1. On **Ready**, select **Set this box up**.

![The secrets screen of the wizard](/guide/en/setup_secrets.webp)

The steps run on the screen, and the title changes to **This hub is set up**. The wizard has also installed the computer's agent, which runs the services the later pages open.

![The wizard's last screen](/guide/en/setup_done.webp)

::: warning
The vault passphrase seals every credential the hub holds, and restoring a backup requires it. Write it down somewhere other than the computer.
:::

## Sign in to the panel

1. Select **Open the panel**.
1. Type the panel password in **Panel password**.
1. Select **Sign in**.

The panel opens on the **Dashboard**. Its address is the one in the browser's address bar, and the laptop opens the panel at the same address.

## Join your phone and laptop

Each device joins with a link of its own from the panel's **Clients** page, valid for 30 minutes. Follow the part for each device you have.

### From the phone

1. On the phone, download `https://github.com/iffiX/neutrino/releases/download/v0.5.0/neutrino-client-0.5.0-android.apk`.
1. Open the file and select **Install**. If Android shows a prompt first, allow your browser to install apps.
1. Open **Neutrino**.
1. In the panel, open **Clients**, then select **New client link**.
1. Type a name for the phone, such as `phone`, then select **Create link**. A QR code of the link appears.
1. In the app, on **Hubs**, select **Join a hub**.
1. Select **Allow the camera**, then allow it in Android's prompt.
1. Point the camera at the QR code in the panel.

The app lists the hub, and its row reads **Connected · LAN**.

![The client link with its QR code on the Clients page](/guide/en/clients_link_qr.webp)

![The app's QR scanner on the Join a hub screen](/guide/en/app_join_scan.webp)

### From the laptop

On Linux or macOS, install the client from your own account with:

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- client
```

On Windows, run this in PowerShell:

```powershell
& ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) client
```

Then join the laptop:

1. In a browser on the laptop, open the panel's address and sign in.
1. On **Clients**, select **New client link**.
1. Type a name for the laptop, such as `laptop`, then select **Create link**.
1. Select **Copy**.
1. Open **Neutrino Client** from the application menu on Linux, the Start menu on Windows, or **Applications** on macOS.
1. Paste the link into the field of the **Join a hub** row.
1. Select **Join**.

The hub's row in the laptop's client window reads **Connected · LAN**.

## Join the hub to NetBird

The hub joins NetBird with a setup key and gives the same key to the phone and the laptop, so the key must be reusable.

### Create a reusable setup key

1. In the NetBird console, open **Settings** > **Setup Keys**.
1. Select **Create Key**.
1. Type a **Name**, such as the hub's name.
1. Turn on **Make this key reusable**.
1. Leave **Usage limit** empty, where it reads **Unlimited**.
1. Leave **Expires in** empty.
1. Select **Create Setup Key**.
1. In **Setup key created successfully!**, select the copy button beside the key. The console shows the key this one time.

![The Create Setup Key form filled in](/guide/console/console_netbird_key_create.webp)

![The new setup key, shown once](/guide/console/console_netbird_key_created.webp)

::: warning
The key under **Networks** > **Routing Peers** > **Add** > **Install NetBird** works one time. With it, the hub joins and the phone then fails to join.
:::

### Paste the key into the panel

1. In the panel's sidebar, open **Access**.
1. On the **NetBird** card, turn on **Enable**.
1. Select **Apply access**.
1. Select the **NetBird** card.
1. Under **Settings**, paste the key into **Setup key**.
1. Leave the management URL empty.
1. Select **Join**.

![The NetBird settings with the setup key saved](/guide/en/overlay_netbird_settings.webp)

The badge beside **NetBird** reads **joining**, then **connected**, and **Settings** shows the hub's **Overlay address**. When the badge stays on another word, [Troubleshooting](./reference/troubleshooting.md#access) has its fix.

## Put the phone and laptop on NetBird

The phone and the laptop receive the setup key from the hub, so every step for them runs on the devices themselves.

1. In the app, on the hub's row, on the **Virtual network** line, select **Connect**.
1. In Android's VPN connection request, select **OK**.
1. In the laptop's client window, on the hub's row, on the **Virtual network** line, select **Connect**.

![Android's VPN connection request](/guide/en/app_vpn_prompt.webp)

Each **Virtual network** line reads **Connecting…**, then **Connected ·** and the device's address on NetBird.

## Leave the Wi-Fi

- Turn off Wi-Fi on the phone.

The hub's row in the app reads **Connected · NetBird**, with the round trip in milliseconds beside it. The phone now reaches the hub from mobile data.

![The hub's row connected through NetBird, away from the Wi-Fi](/guide/en/app_hub_netbird.webp)

When a row reads something else, [Troubleshooting](./reference/troubleshooting.md#the-state-line-of-a-hub-row) lists each state line and its fix.
