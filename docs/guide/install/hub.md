---
title: Install the hub
---

# Install the hub

Besides the one command of [Step zero](../quick-start.md), the hub installs from a package file or in the mainland edition. Each screen of the setup wizard follows the install.

## Before you start

- The machine runs one of these systems:
  - Debian 12 or newer, Ubuntu 22.04 or newer, or Raspberry Pi OS 64-bit
  - Fedora 41 or newer, the RHEL 9 family, or Arch on x86-64
  - macOS 12.3 or newer on Apple silicon or Intel, in server mode only
  - Windows 10 1809 or newer on x86-64, in server mode only
- You have root on it, or an administrator account on macOS and Windows.
- It reaches the internet.

## Pick an edition

Every release comes in two editions:

| Edition  | Published on                   | What it has                                                   |
| -------- | ------------------------------ | ------------------------------------------------------------- |
| full     | GitHub, every release kept     | every feature                                                 |
| mainland | Gitee, the latest release only | every feature except the proxy, NetBird and side gateway mode |

The mainland edition downloads from mirrors in mainland China. It publishes the hub for Debian, Ubuntu and Raspberry Pi OS on x86-64 and ARM64, Windows, and Apple silicon Macs.

## Install with one command

The install script checks the package against the release's `SHA256SUMS`, installs it, and runs `nhub setup`. That command prints the wizard's address, then shows `Press Enter to begin:` and stays there. When you finish the wizard in a browser, it prints `The hub was set up in the browser; its panel is at` and the panel's address, then exits.

### Linux and macOS

For the full edition, run:

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

For the mainland edition, run:

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh
```

On Debian and Ubuntu, apt prints `N: Download is performed unsandboxed as root…` during the install. The line means apt read the package file as root, and the install goes on.

### Windows

In PowerShell, run the command for your edition, then accept the administrator prompt. For the full edition:

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

For the mainland edition:

```powershell
irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1 | iex
```

## Install from the package file

Download the file for your system from the [releases page](https://github.com/iffiX/neutrino/releases), or for the mainland edition from the [Gitee releases page](https://gitee.com/iffiX/neutrino/releases).

### Linux

Install the file with the system's package manager:

::: code-group

```bash [Debian, Ubuntu, Raspberry Pi OS]
sudo apt install ./neutrino-hub_0.5.0_amd64.deb
```

```bash [Fedora]
sudo dnf install ./neutrino-hub-0.5.0-1.x86_64.rpm
```

```bash [RHEL, AlmaLinux, Rocky]
sudo dnf install -y epel-release
sudo dnf install ./neutrino-hub-0.5.0-1.x86_64.rpm
```

```bash [Arch, EndeavourOS, Manjaro]
sudo pacman -U neutrino-hub-0.5.0-1-x86_64.pkg.tar.zst
```

:::

On ARM64 the files are `neutrino-hub_0.5.0_arm64.deb` and `neutrino-hub-0.5.0-1.aarch64.rpm`; the Arch package is for x86-64 only. The RHEL family needs EPEL for fail2ban, arp-scan and vnstat.

::: warning
Install with `apt`, `dnf` or `pacman`. `dpkg -i` and `rpm -i` install none of the dependencies; after `dpkg -i`, run `sudo apt -f install` to finish.
:::

### macOS

Install the package from a terminal:

```bash
sudo installer -pkg neutrino-hub-0.5.0-macos-arm64.pkg -target /
```

On an Intel Mac the file is `neutrino-hub-0.5.0-macos-amd64.pkg`.

### Windows

Open `neutrino-hub-0.5.0-windows-amd64.msi`. For a silent install, run this in PowerShell as administrator:

```powershell
msiexec /i neutrino-hub-0.5.0-windows-amd64.msi /qn
```

## Open the wizard

Until the machine is set up, the panel's HTTP port serves the setup wizard behind a one-time token. Open it in one of these ways:

- On the machine itself, open **Neutrino Hub** from the application menu, the Start menu or **Applications**. It opens the wizard in the default browser. `nhub open` in a terminal does the same.
- From another machine, run `sudo nhub setup` on the hub's machine, or `nhub setup` in an administrator PowerShell on Windows. Open one of the addresses it prints, each ending in the token.

On the first screen, select **Set this box up**. To answer in the terminal instead, press Enter at `Press Enter to begin`.

## Answer the wizard

The wizard writes nothing until you confirm the last screen.

### Language

Select **English** or **简体中文** under **Language**. The terminal stays in English.

### Passwords and HTTPS

![The secrets screen with the HTTPS switch](/guide/en/setup_secrets.webp)

1. Type a **Panel password** of at least 8 characters, and type it again under **Again**.
1. Type a **Vault passphrase** of at least 16 characters, mixing upper and lower case, digits and symbols, and type it again.
1. Optional: turn on **HTTPS for the panel**.

The passphrase seals every credential the hub holds, and restoring a backup requires it. [Settings](../hub/settings.md#https) turns HTTPS on or off later.

### Shape

![The shape screen with Server picked](/guide/en/setup_shape.webp)

**What is this machine for?** lists the modes the machine has enough ports for: **Server**, **Side gateway**, **Router** and **One-arm router**. On macOS and Windows the screen lists **Server** only, and the mainland edition has no **Side gateway**. A router takes over the machine's interfaces. [Network](../hub/network.md#mode) describes each mode and changes it later.

### Ports

**Which ports?** shows the fields the chosen mode needs. Every mode also has **Panel port** for HTTP and **HTTPS port**, and the two must differ.

| Mode           | Fields                                                                                             |
| -------------- | -------------------------------------------------------------------------------------------------- |
| Server         | the list of the machine's ports, each keeping its address                                          |
| Side gateway   | **Port on that network**, **This box's address**, **Prefix length**, **That network's own router** |
| Router         | **Out to the internet**, **In to your devices**, **This box's address**, **Prefix length**         |
| One-arm router | **One-arm port**, **VLAN tag for your devices**, **This box's address**, **Prefix length**         |

### Proxy

**Going out through a proxy** appears in the full edition and is optional; [Proxy](../hub/proxy.md) holds the same settings later. To set it up now, turn on **Set it up here** and paste each `ss://` or `vless://` link under **Exit node links**.

| Field                                                 | Shown for       |
| ----------------------------------------------------- | --------------- |
| **SOCKS port applications point at**                  | Server          |
| **Also publish a SOCKS port that bypasses the proxy** | the other modes |
| **Send this box's own traffic through it**            | every mode      |

### Ready

**Ready** lists every answer. Check them, then select **Set this box up**. For a router, the screen names the panel's new address; refresh the page if the network drops while the interfaces change.

## Watch the steps

The title reads **Setting up** while the steps run, then **This hub is set up**.

![The finished screen offering the certificate](/guide/en/setup_done.webp)

With HTTPS off, the page moves to the panel after five seconds. With HTTPS on, the page shows **Install certificate**. Install the authority as in [Settings](../hub/settings.md#install-the-authority), restart the browser, then open the panel's `https://` address.

Each run writes `setup.log`, in the folder [Troubleshooting](../reference/troubleshooting.md#where-the-logs-are) names.

## Sign in

![The sign-in page](/guide/en/login.webp)

1. Open the panel's address: `http://` with the machine's address and the panel port, or with HTTPS on, `https://` and the machine's address.
1. Type the **Panel password**.
1. Select **Sign in**.

After repeated wrong passwords the page reads **Locked after repeated failures.**; `sudo nhub unlock` on the hub's machine removes the lock.
