---
title: Quick start
---

# Quick start

At the end of this page, your phone on mobile data reaches your computer at home. It shows the computer's desktop, opens a folder shared from it in the Files app, and runs a terminal on it. The whole path takes about forty minutes and costs nothing, because the way in from outside is the free tier of the EasyTier console.

<!-- 待核: the time of the whole path (outline item 13) and the number of devices the EasyTier console's free tier allows (outline item 2) -->

## Before you start

- Your computer stays on, has a desktop, and has somebody signed in at its screen. It runs one of these systems:
  - Linux with a desktop: Debian 12 or newer, Ubuntu 22.04 or newer, Fedora 41 or newer, or the RHEL 9 family
  - macOS 12.3 or newer
  - Windows 10 1809 or newer on x86-64
- You have an administrator account on your computer, and it reaches the internet.
- Your phone runs Android 8.0 or newer on a 64-bit ARM processor.
- You have an account on the EasyTier console.
- Your phone and your computer are on the same Wi-Fi network.

<!-- 待核: the EasyTier console's sign-up address (outline item 2) -->

## Install the hub

On Linux, open a terminal and run:

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

On macOS, open **Terminal** and run:

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

On Windows, open PowerShell and run:

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

The script prompts once for administrator rights. On Windows it continues in a new PowerShell window that Windows opens as administrator, and that window prints the addresses. When the install finishes, the terminal prints one address for each network your computer is on, each ending in a one-time token.

In mainland China, take the mainland edition's command from [Install the hub](./install/hub.md).

## Open the wizard

1. In a browser on your computer, open the first address the terminal printed, with its token.
1. Select **Set this box up**.

## Answer the wizard

Each screen ends in **Next**, and the wizard writes nothing until the last screen:

1. On **Language**, keep **English**.
1. Type a **Panel password** of at least 8 characters, and type it again under **Again**.
1. Type a **Vault passphrase** of at least 16 characters, with lowercase and uppercase letters, digits and symbols, and type it again under **Again**.
1. Leave **HTTPS for the panel** off.
1. On **What is this machine for?**, select **Server**. On macOS and Windows it is the only shape listed.
1. On **Which ports?**, keep the ports as they are.
1. On **Going out through a proxy**, leave **Set it up here** off.
1. On **Ready**, select **Set this box up**.

The steps run on the screen, and the title changes to **This hub is set up**.

::: warning
The vault passphrase seals every credential the hub holds, and restoring a backup requires it. Write it down somewhere other than your computer.
:::

## Sign in to the panel

1. Select **Open the panel**.
1. Type the panel password in **Panel password**.
1. Select **Sign in**.
1. In the sidebar, open **Devices**.

**Managed devices** lists your computer, because the wizard installed your computer's agent and joined it to the hub.

## Turn on EasyTier

1. In the sidebar, open **Access**.
1. On the **EasyTier** card, turn on **Enable**.
1. Select **Apply access**.
1. Select the **EasyTier** card.
1. Under **Settings**, select **EasyTier console**.
1. In the EasyTier console, copy your console address.
1. In the panel, paste it into **Console address**.
1. Select **Apply EasyTier settings**.

<!-- 待核: where the EasyTier console shows the console address, and whether it is the whole tcp:// address or the token alone (outline item 2) -->

The card reads **Waiting for the console**. Your computer is now registered with the console and on no network yet.

![The EasyTier card in console mode, waiting for the console](/guide/en/overlay_easytier_console_waiting.webp)

## Attach your computer in the console

1. In the EasyTier console, open the list of devices. Your computer is listed there.
1. Create a network for your computer: a name, a password, an address range, and a public server to meet at.
1. Run the network on your computer.

<!-- 待核: the console's labels for the device list, the network form and running a network (outline item 2) -->

![The EasyTier console's device list with your computer registered](/guide/console/console_easytier_devices.webp)

![The EasyTier console's form that creates a network](/guide/console/console_easytier_network_create.webp)

In the panel, the EasyTier badge on **Access** reads **connected** or **no peers yet**, and **Networks from the console** lists the network.

<!-- 待核: which of the two badges shows while your computer is the only device on the network (outline item 4) -->

![The network from the console listed on the Access page](/guide/en/overlay_easytier_console_networks.webp)

## Share your computer's desktop

1. In the sidebar, under **Agent**, open **Modules**.
1. Select your computer among the machines at the top of the page.
1. Select the **Remote desktop** tab.
1. Turn on **Share this machine's desktop**.
1. Select **Apply remote desktop**.

![The Remote desktop tab with the desktop shared](/guide/en/modules_remote_desktop_tab.webp)

On macOS, your computer's screen shows a prompt for RustDesk. In **System Settings** > **Privacy & Security**, turn on RustDesk under **Screen Recording** and under **Accessibility**. On Linux with a Wayland session, allow the screen sharing once at your computer's screen.

## Install the file share

1. On **Modules**, select the **File share** tab. If the tab is missing, select **+** beside the tabs and tick **File share**.
1. Select **Install**, and wait until the tab no longer reads **installing**.
1. Select **Configure**.

On Linux the install fetches Samba. On macOS and Windows the file share drives the SMB server that comes with the system.

## Add a user and a share

1. Under **Users**, type a user name and a password in the two fields.
1. Select **Add user**.
1. Select **Apply users**. The user's row reads **ready**.
1. Under **Shares**, select **Add share**.
1. Type a name for the share in **Name**.
1. Type the path of a folder that exists on your computer in **Path**. On Windows the path starts at a drive, as in `C:\Users\Public\Documents`.
1. Select **Apply shares**.

## Install the app and join

1. On your phone, download `https://github.com/iffiX/neutrino/releases/download/v0.5.0/neutrino-client-0.5.0-android.apk`.
1. Open the file and select **Install**. If Android shows a prompt first, allow your browser to install apps.
1. Open **Neutrino**.
1. In the panel, open **Clients**, then select **New client link**.
1. Type a name for your phone, then select **Create link**. A QR code of the link appears.
1. In the app, on **Hubs**, select **Join a hub**.
1. Select **Allow the camera**, then allow it in Android's prompt.
1. Point the camera at the QR code in the panel.

![The client link with its QR code on the Clients page](/guide/en/clients_link_qr.webp)

![The app's QR scanner on the Join a hub screen](/guide/en/app_join_scan.webp)

The hub's row in the app reads **Connected · LAN**.

## Connect your phone's virtual network

1. On the hub's row, on the **Virtual network** line, select **Connect**.
1. In Android's VPN connection request, select **OK**. The line reads **Connecting…** with **This machine is registered with the console. Attach it to a network there.** under it.
1. In the EasyTier console, attach your phone to the network your computer is on.

<!-- 待核: the console's label for attaching a device, and the name the phone has in the console (outline item 2) -->

![Android's VPN connection request](/guide/en/app_vpn_prompt.webp)

![The virtual network line waiting for the console](/guide/en/app_hub_console_waiting.webp)

![The EasyTier console attaching the phone to the network](/guide/console/console_easytier_device_attach.webp)

The line reads **Connected ·** and your phone's address on the network.

## Use your computer from mobile data

Every step from here runs on your phone, away from your Wi-Fi.

### Leave the Wi-Fi

- Turn off Wi-Fi on your phone.

The hub's row reads **Connected · EasyTier** with the round trip in milliseconds. The app now reaches the hub through the EasyTier network your phone and your computer are on.

![The hub row connected through EasyTier](/guide/en/app_hub.webp)

### See the desktop

1. Open **Remote desktops**.
1. On your computer's row, select **Connect**.

The viewer fills the screen with your computer's desktop. Three round buttons at the top right open the keyboard, send special keys, and end the session.

![Your computer's desktop in the app's viewer](/guide/en/app_rdp_viewer.webp)

### Open the shared folder

1. Open **Files**.
1. On the share's row, select **Open in Files**.
1. Type the user name in **Share username** and its password in **Share password**.
1. Leave **Remember** ticked.
1. Select **Connect**.

The share appears in Android's Files app, and the folder's files open from there.

![The share in Android's Files app](/guide/en/app_files_provider.webp)

### Open a terminal

1. Open **Terminals**.
1. Select your computer.
1. Select **New terminal**.
1. Type `ls` and press Enter.

The terminal lists the files of the folder it starts in. On Windows the terminal is PowerShell, and on Linux and macOS it is root's login shell.

![A terminal on your computer in the app](/guide/en/app_terminal.webp)
