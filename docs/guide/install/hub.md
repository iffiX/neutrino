---
title: Install the hub
---

# Install the hub

This page takes one machine from a fresh system to a running hub whose panel you are signed in to. The panel then serves HTTP on port `8080` and HTTPS on port `443`, unless you pick other ports in the setup wizard.

## Before you start

- The machine runs one of these systems:
  - Debian 12 or newer, Ubuntu 22.04 or newer, or Raspberry Pi OS 64-bit, in any network shape
  - Fedora 41 or newer, the RHEL 9 family, or Arch on x86-64, in any network shape
  - macOS 12.3 or newer on Apple silicon or Intel, in the server shape
  - Windows 10 1809 or newer on x86-64, in the server shape
- You have root on it, or an administrator account on macOS and Windows.
- It reaches the internet.

[Supported platforms](../reference/platforms.md) lists every file of the release and the system each one installs on.

## Pick an edition

Every release comes in two editions built from one source:

| Edition  | Published on                   | What it has                                                                    |
| -------- | ------------------------------ | ------------------------------------------------------------------------------ |
| full     | GitHub, every release kept     | every feature                                                                  |
| mainland | Gitee, the latest release only | every feature except the proxy, NetBird and the **Side gateway** network shape |

The mainland edition fetches its downloads from mirrors in mainland China. It publishes the hub for Debian, Ubuntu and Raspberry Pi OS on x86-64 and ARM64, for Windows, and for Macs with Apple silicon. Each edition updates from its own release page, so an update keeps a mainland hub mainland.

## Install with one command

The install script picks the package for the machine, checks it against the release's `SHA256SUMS`, and prompts once for administrator rights. When the script runs in a terminal, it goes on into `nhub setup`, which prints the wizard's address. Without a terminal, it prints the wizard's address with its token and ends. Over a hub that is already set up, it prints the panel's address.

### Linux and macOS

For the full edition, run:

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

For the mainland edition, run:

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh
```

### Windows

Open PowerShell and run the command for your edition. The script prompts Windows for administrator rights and continues in the PowerShell window that Windows opens as administrator.

For the full edition:

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

For the mainland edition:

```powershell
irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1 | iex
```

## Install from the package file

Download the file for your system from the [releases page](https://github.com/iffiX/neutrino/releases). The mainland edition's files are on the [Gitee releases page](https://gitee.com/iffiX/neutrino/releases).

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

On ARM64 the files are `neutrino-hub_0.5.0_arm64.deb` and `neutrino-hub-0.5.0-1.aarch64.rpm`, and the Arch package is for x86-64 alone. The RHEL family installs `epel-release` in a line of its own, because fail2ban, arp-scan and vnstat come from EPEL. The package includes its own Python under `/opt/neutrino/hub/python`.

::: warning
Install with `apt`, `dnf` or `pacman`. `dpkg -i` and `rpm -i` install none of the dependencies; after `dpkg -i`, run `sudo apt -f install` to finish.
:::

### macOS

Install the package from a terminal:

```bash
sudo installer -pkg neutrino-hub-0.5.0-macos-arm64.pkg -target /
```

On an Intel Mac the file is `neutrino-hub-0.5.0-macos-amd64.pkg`. The installer registers the hub's service, starts it, and links `nhub` into `/usr/local/bin`.

### Windows

Open `neutrino-hub-0.5.0-windows-amd64.msi`. For a silent install, run this in PowerShell as administrator:

```powershell
msiexec /i neutrino-hub-0.5.0-windows-amd64.msi /qn
```

The installer registers the `neutrino_hub` service and starts it.

## Open the wizard

Until the machine is set up, the hub's service serves the setup wizard on the panel's HTTP port, behind a one-time token. Open it in one of these ways:

- On the machine itself, open **Neutrino Hub** from the application menu on Linux, the Start menu on Windows, or **Applications** on macOS. It opens the wizard in the default browser, and prompts for the administrator password only when the hub's service is stopped. `nhub open` in a terminal does the same.
- From another machine, run `sudo nhub setup` on the hub's machine, or `nhub setup` in an administrator PowerShell on Windows. It prints one address for each network the machine is on, each ending in the token. Open one of them in a browser on any machine that reaches the hub.

On the first screen, select **Set this box up**. A page opened without the token reads **This box is waiting to be set up**. To answer in the terminal instead, press Enter at `Press Enter to begin`; the same questions follow there, in English.

## Answer the wizard

**Next** moves on and **Back** returns. The wizard writes nothing until you confirm the last screen.

### Language

Select **English** or **简体中文** under **Language**. The panel uses this language, and the terminal stays in English.

### Passwords and HTTPS

![The secrets screen with the HTTPS switch](/guide/en/setup_secrets.webp)

1. Type a **Panel password** of at least 8 characters, and type it again under **Again**.
1. Type a **Vault passphrase** of at least 16 characters, with lowercase and uppercase letters, digits and symbols, and type it again under **Again**.
1. Optional: turn on **HTTPS for the panel**.

The passphrase seals every credential the hub holds, and restoring a backup requires it. With HTTPS on, the HTTP port sends every browser to the HTTPS port. [Settings](../hub/settings.md#https) turns HTTPS on or off later.

### Shape

![The shape screen with Server picked](/guide/en/setup_shape.webp)

**What is this machine for?** lists the shapes the machine has enough ports for:

| Shape              | What it does                                       |
| ------------------ | -------------------------------------------------- |
| **Server**         | Serves on the networks it is connected to.         |
| **Side gateway**   | Forwards for hosts that name it as their gateway.  |
| **Router**         | Routes between uplinks and the networks it serves. |
| **One-arm router** | Routes on one wire: untagged out, tagged VLAN in.  |

On macOS and Windows the screen lists **Server** alone, and the mainland edition lists no **Side gateway**. Server and side gateway keep every address on the machine, and router and one-arm router take its interfaces over. [Network](../hub/network.md) describes each shape and changes it later.

### Ports

**Which ports?** shows the fields the chosen shape needs. Every shape also has **Panel port** for HTTP and **HTTPS port**, and the two must differ.

| Shape          | Fields                                                                                             |
| -------------- | -------------------------------------------------------------------------------------------------- |
| Server         | the list of the machine's ports, each keeping its address                                          |
| Side gateway   | **Port on that network**, **This box's address**, **Prefix length**, **That network's own router** |
| Router         | **Out to the internet**, **In to your devices**, **This box's address**, **Prefix length**         |
| One-arm router | **One-arm port**, **VLAN tag for your devices**, **This box's address**, **Prefix length**         |

A router sets one uplink and one served network here, and the panel's **Network** page adds more.

### Proxy

**Going out through a proxy** appears in the full edition and is optional; [Proxy](../hub/proxy.md) holds the same settings later. To set it up now, turn on **Set it up here** and paste each `ss://` or `vless://` link under **Exit node links**.

| Field                                                 | Shape            | What it sets                               |
| ----------------------------------------------------- | ---------------- | ------------------------------------------ |
| **SOCKS port applications point at**                  | Server           | a SOCKS port that leaves through the exit  |
| **Also publish a SOCKS port that bypasses the proxy** | the other shapes | a second SOCKS port that leaves directly   |
| **Send this box's own traffic through it**            | every shape      | the machine's own connections use the exit |

### Ready

**Ready** lists every answer. Check them, then select **Set this box up**. For a router or a one-arm router, the screen names the panel's new address and the log file. The network can drop while the interfaces change; refresh the page when it does.

## Watch the steps

The title reads **Setting up**. The list shows each step as it runs, from **Checking the packages the hub needs** to **Setting the panel password**; this machine's agent is installed right after, in the background. **Generating the panel's certificates** makes the hub's own certificate authority and the panel's certificate. When the last step finishes, the title reads **This hub is set up**.

![The finished screen offering the certificate](/guide/en/setup_done.webp)

What comes next depends on the HTTPS answer:

- With HTTPS off, the page moves to the panel after five seconds, and **Open the panel** goes there at once.
- With HTTPS on, the page shows **Install the certificate on this device**, with **Install certificate** and the authority's SHA-256 fingerprint. Install the authority, check its fingerprint, restart the browser, then open the panel's `https://` address.

Each run writes its log to `setup.log`:

| System  | Log                                         |
| ------- | ------------------------------------------- |
| Linux   | `/var/log/neutrino/hub/setup.log`           |
| macOS   | `/Library/Logs/Neutrino/hub/setup.log`      |
| Windows | `C:\ProgramData\Neutrino\hub\log\setup.log` |

## Sign in

![The sign-in page](/guide/en/login.webp)

1. Open the panel's address. With HTTPS off it is `http://`, the machine's address and the panel port. With HTTPS on it is `https://` and the machine's address, with the HTTPS port when it is not `443`.
1. Type the **Panel password**.
1. Select **Sign in**.

The panel opens on the **Dashboard**. After repeated wrong passwords, the page reads **Locked after repeated failures.**, and `sudo nhub unlock` on the hub's machine removes the lock. On Windows, run `nhub unlock` in an administrator PowerShell.
