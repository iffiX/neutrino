---
title: Install the client
---

# Install the client

The client is one package per system. A link from a hub's **Clients** page joins it to that hub, and the window holds one row per hub joined, with that hub's services under it.

## Before you start

Check the computer against these requirements:

- It is a computer a person uses, on one of these systems:
  - Debian 12 or newer, or Ubuntu 24.04 or newer, with a desktop session
  - Fedora 41 or newer, or the RHEL 9 family, with a desktop session
  - Windows 10 or 11 on x86-64
  - macOS on Apple silicon
- You run the client from your own account. The client rejects root with `root_refused`.
- It reaches port 8443 on every hub it joins, the channel each one listens on.

## Create a client link

1. In the panel, open **Clients**.
1. Select **New client link**.
   ![The new client link form](/guide/en/clients_create_link.webp)
1. Type a name for the computer, `laptop` for example, and select **Create link**.

The notice reads **Paste this link into the client program for** followed by the name you typed, and has a **Copy** button. The link in it is valid for five minutes.

![The client link notice](/guide/en/clients_link_notice.webp)

## Install the package

::: code-group

```bash [Debian, Ubuntu]
sudo apt install ./neutrino-client_0.2.0_amd64.deb
```

```bash [Fedora, RHEL, AlmaLinux, Rocky]
sudo dnf install ./neutrino-client-0.2.0-1.x86_64.rpm
```

```powershell [Windows]
msiexec /i neutrino-client-0.2.0-windows-amd64.msi
```

```bash [macOS]
sudo installer -pkg neutrino-client-0.2.0-macos-arm64.pkg -target /
```

:::

On Linux the package is compiled and depends on WebKitGTK, the appindicator library, `cifs-utils` and polkit, which the package manager installs with it.

On Windows, double-clicking the `.msi` runs the same installer. It has two checkboxes. **Add the Neutrino Client to PATH** makes `nclient` available in a terminal, and **Keep my configuration** applies on removal. When WebView2 is absent the installer runs Microsoft's bootstrapper for it. The client sits in the taskbar corner.

![The Windows installer](/guide/os/win_msi_installer.webp)

![The tray icon in the taskbar corner](/guide/os/win_tray_flyout.webp)

On macOS, Gatekeeper stops a package downloaded from a browser: open the `.pkg` from its context menu and choose **Open**. The app opens from its icon and sits in the menu bar.

## Join the first hub

1. Open the client: **Neutrino client** in the application menu on Linux, the Start menu on Windows, or its icon on macOS, or run `nclient gui` in a terminal. The **Hubs** section reads **No hub joined yet**, with a **Join a hub** row under it.
   ![The client window before joining](/guide/en/client_disconnected.webp)
1. Paste the link into the field of that row and select **Join**.

The hub gets a row of its own reading **Connected**, with its address and the package it runs. Under the hub's name, the **Services** section draws **Web**, **Ports**, **AI**, **Files** and **Remote desktops**.

![The client window joined to a hub on Linux](/guide/en/client_connected.webp)

![The client window joined to a hub on Windows](/guide/en/win_client_connected.webp)

From a terminal, `nclient join '<link>'` joins the same way, where the link is the one the **Clients** page issued. A link from the **Devices** page is rejected with `link_not_for_client`, and an expired one with `enroll_refused`.

## Join another hub

This computer belongs to as many hubs as it holds links for. Each hub issues its own link, keeps its own name for the computer, and publishes its own services; nothing is shared between them.

1. In the second hub's panel, create a client link the same way.
1. Paste it into the **Join a hub** row and select **Join**.

The **Hubs** section grows a row and the **Services** section grows a group. From a terminal, `nclient join` adds a hub and `nclient leave --hub` leaves the one you name.

## Using the services

| Panel           | Page                                    |
| --------------- | --------------------------------------- |
| Web             | [Web](./web.md)                         |
| Ports           | [Ports](./ports.md)                     |
| AI              | [AI](./ai.md)                           |
| Files           | [Files](./files.md)                     |
| Remote desktops | [Remote desktops](./remote-desktops.md) |
