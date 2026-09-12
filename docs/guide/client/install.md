---
title: Install the client
---

# Install the client

The client is one package per system. It joins the hub with a link pasted into its window, and then reads **Connected** with its five panels.

## Before you start

Check the computer against these requirements:

- It is a computer a person uses, on one of these systems:
  - Debian 12 or newer, or Ubuntu 24.04 or newer, with a desktop session
  - Fedora 41 or newer, or the RHEL 9 family, with a desktop session
  - Windows 10 or 11 on x86-64
  - macOS on Apple silicon
- You run the client from your own account. The client rejects root with `root_refused`.
- It reaches port 8443 on the hub, the channel the client connects on.

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

## Paste the link

1. Open the client: **Neutrino client** in the application menu on Linux, the Start menu on Windows, or its icon on macOS, or run `nclient gui` in a terminal. The window opens with **Not connected** and a field for the link.
   ![The client window before joining](/guide/en/client_disconnected.webp)
1. Paste the link into the field and select **Connect**.

The status card reads **Connected** with the hub's version, and the **Services** section draws **Web**, **Ports**, **AI**, **Files** and **Remote desktops**.

![The client window connected on Linux](/guide/en/client_connected.webp)

![The client window connected on Windows](/guide/en/win_client_connected.webp)

From a terminal, `nclient connect '<link>'` joins the same way. A link from the **Devices** page is rejected with `link_not_for_client`, and an expired one with `enroll_refused`.

## Using the services

| Panel           | Page                                    |
| --------------- | --------------------------------------- |
| Web             | [Web](./web.md)                         |
| Ports           | [Ports](./ports.md)                     |
| AI              | [AI](./ai.md)                           |
| Files           | [Files](./files.md)                     |
| Remote desktops | [Remote desktops](./remote-desktops.md) |
