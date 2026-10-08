---
title: Install a client
---

# Install a client

After this page, the client runs on your computer or Android phone and has joined your hub. The hub's row in the client reads **Connected ·** with the way the client reached it. A computer runs one person's client at a time.

## Before you start

- The device runs one of these systems:
  - Linux with a desktop session: Debian 12 or newer, Ubuntu 22.04 or newer, Fedora 41 or newer, or the RHEL 9 family
  - macOS 12.3 or newer
  - Windows 10 1809 or newer on x86-64
  - Android 8.0 or newer on a 64-bit ARM phone
- On a computer, you run the client from your own account. The client rejects root with `root_refused`.
- The device reaches the hub's port 8443, on your network or through a way in from [Access](../hub/overlay.md).

## Install the desktop client with one command

The install script picks the client package for the computer, checks it against the release's `SHA256SUMS` and installs it. When your account has joined no hub yet, the script ends by printing the `nclient join` line to run next.

### Linux and macOS

For the full edition, run:

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- client
```

For the mainland edition, run:

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh -s -- client
```

### Windows

Open PowerShell and run the command for your edition. The script prompts Windows for administrator rights and installs from the PowerShell window that Windows opens as administrator. Run `nclient join` later in a PowerShell of your own.

For the full edition:

```powershell
& ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) client
```

For the mainland edition:

```powershell
& ([scriptblock]::Create((irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1))) client
```

## Install the desktop client from the package file

Download the client's file for your computer from the [releases page](https://github.com/iffiX/neutrino/releases), then install it:

::: code-group

```bash [Debian, Ubuntu]
sudo apt install ./neutrino-client_0.5.0_amd64.deb
```

```bash [Fedora, RHEL family]
sudo dnf install ./neutrino-client-0.5.0-1.x86_64.rpm
```

```powershell [Windows]
msiexec /i neutrino-client-0.5.0-windows-amd64.msi
```

```bash [macOS]
sudo installer -pkg neutrino-client-0.5.0-macos-arm64.pkg -target /
```

:::

On a 64-bit ARM Linux computer, the file name says `arm64` for the `.deb` and `aarch64` for the `.rpm`. On an Intel Mac the file is `neutrino-client-0.5.0-macos-amd64.pkg`. `apt` and `dnf` install the dependencies with the package: WebKitGTK, the tray library, `cifs-utils` and polkit.

::: warning
`dpkg -i` and `rpm -i` install none of the dependencies. After either one, run `sudo apt -f install` on Debian, or `sudo dnf install` with the missing packages on Fedora and RHEL.
:::

On Windows, opening the `.msi` from File Explorer runs the same installer. Its **Add the Neutrino Client to PATH** box puts the `nclient` command in every terminal. When the WebView2 runtime is missing, the installer runs Microsoft's installer for it. The removal dialog has a **Keep my configuration** box, and a kept configuration joins the same hub again on the next install.

![The Windows installer of the client](/guide/os/win_msi_installer.webp)

On macOS the installer puts **Neutrino Client** in `/Applications` and links `nclient` into `/usr/local/bin`. The app has an ad hoc signature, so Gatekeeper shows a confirmation the first time it opens.

Every package also registers the system services of the virtual networks: the NetBird daemon and the client's EasyTier daemon. The mainland edition's package has the EasyTier daemon alone. On Windows the package registers one more service, `NeutrinoClientFiles`, which puts a share on a drive letter. An install over a running client closes it, then starts it again in the same person's session when the install ends.

## Install the Android app

1. On the phone, download `neutrino-client-0.5.0-android.apk` from the release.
1. Open the file. If Android shows a prompt, allow your browser or file manager to install apps.
1. Select **Install**.
1. Open **Neutrino**.

The mainland edition's apk is on the Gitee release page and has no NetBird.

The project signs every release apk with its own key, and Android updates an installed app only from an apk with the same key. To check a downloaded apk on a computer with the Android SDK build tools, run:

```bash
apksigner verify --print-certs neutrino-client-0.5.0-android.apk
```

```text
Signer #1 certificate SHA-256 digest: 0e20b8b4542f329c4d3ed91632f3ea90730cb99472c46c31585780d046ee612d
...
```

Build tools 37 and newer print the line as `V2 Signer: certificate SHA-256 digest:` followed by the same digest.

::: danger
If the digest differs, delete the apk without installing it.
:::

## Make a client link

1. In the hub's panel, open **Clients**.
1. Select **New client link**.
1. Type a name for the device.
1. Select **Create link**.

![The client link with its QR code on the Clients page](/guide/en/clients_link_qr.webp)

The notice shows the link, **Copy**, and a QR code of the same link. The link works for thirty minutes and joins one device, and a restart of the hub keeps it. [Clients](../hub/clients.md) sets what each device can use.

## Join from a computer

1. Open the client: **Neutrino Client** in the application menu on Linux or the Start menu on Windows, or the app on macOS. **Hubs** reads **No hub joined yet**.
1. Paste the link into the field of the **Join a hub** row.
1. Select **Join**.

![The client window joined to a hub](/guide/en/client_connected.webp)

The hub's row reads **Joined; the hub has not been reached yet** until one address in the link answers. It then reads **Connected · LAN**, or the name of another way in, with the hub's address and the package it runs. In a terminal, `nclient join '<client-link>'` does the same, with the copied link in place of `<client-link>`.

| Code                  | Cause                                           | Fix                                                          |
| --------------------- | ----------------------------------------------- | ------------------------------------------------------------ |
| `link_not_for_client` | the link comes from the hub's **Devices** page  | make a link on **Clients**                                   |
| `link_unreadable`     | the pasted link is cut off                      | copy the whole link again                                    |
| `ticket_spent`        | the link is used or older than thirty minutes   | select **Leave** on the row, then join with a new link       |
| `admission_paused`    | the hub paused joins after too many failed ones | wait the seconds the code names; the client joins again then |

## Join from a phone

1. In the app, on **Hubs**, select **Join a hub**.
1. Select **Allow the camera**, then allow it in Android's prompt.
1. Point the camera at the QR code on the hub's **Clients** page.

![The QR scanner on the Join a hub screen](/guide/en/app_join_scan.webp)

To paste the link instead, put it into the field under **or** and select **Join**. On mobile data away from home, the row reads **Joined; the hub has not been reached yet** until one address in the link answers.

## Join another hub

Make a client link in the other hub's panel, and join with it through **Join a hub** again. Each hub keeps its own name for the device and publishes its own services.
