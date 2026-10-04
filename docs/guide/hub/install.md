---
title: Install the hub
---

# Install the hub

At the end of this page the hub package is on your always-on Linux box, and you are signed in to its panel. Between the two, `sudo nhub setup` shows six question screens and runs its steps. The panel then serves HTTP on the port you chose, `8080` unless you change it, and HTTPS on a second port, `443` unless you change it.

## Before you start

The box must meet these conditions:

- It runs Debian 12 or newer, Ubuntu 22.04 or newer, Raspberry Pi OS 64-bit, Fedora, the RHEL 9 family, or Arch on x86-64.
- You have root on it.
- It reaches the internet, because setup fetches the AI gateway, and in the full edition xray-core and its geodata.

[Supported platforms](../reference/platforms.md) lists every file of the release and the system each one installs on.

## Pick an edition

Every release comes in two editions built from one source:

| Edition  | Where it is published                                                                        | What it has                                |
| -------- | -------------------------------------------------------------------------------------------- | ------------------------------------------ |
| full     | GitHub, the [releases page](https://github.com/iffiX/neutrino/releases)                      | every feature                              |
| mainland | Gitee, [gitee.com/iffiX/neutrino](https://gitee.com/iffiX/neutrino), the latest release only | every feature except the proxy and NetBird |

The mainland edition fetches its downloads from mirrors in mainland China. For a Linux hub it publishes the `.deb` for amd64 and arm64. To install it with one command, run:

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh
```

The script checks the package against the release's `SHA256SUMS`, installs it, and prints the setup wizard's address with its token. The mainland wizard skips the **Going out through a proxy** screen, and its shapes leave out **Side gateway**.

Each edition updates from its own release page, so an update from **Settings** or `nhub update` keeps a mainland hub mainland. The rest of this page installs the full edition.

## Install the package

Download the file for your system from the [releases page](https://github.com/iffiX/neutrino/releases), then install it with the system's package manager:

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

On ARM64 the file is `neutrino-hub_0.5.0_arm64.deb` or `neutrino-hub-0.5.0-1.aarch64.rpm`; the Arch package is x86-64 only. The RHEL family runs `epel-release` as a line of its own, because fail2ban, arp-scan and vnstat come from EPEL. The package includes its own Python under `/opt/neutrino/python`.

::: warning
Install with `apt`, `dnf` or `pacman`. `dpkg -i` and `rpm -i` install none of the dependencies; after one of them, run `sudo apt -f install` on the Debian family to finish.
:::

## Start the wizard

1. Run `sudo nhub setup`. The terminal prints one address per network the box is on, each with a one-time token. Where the box has a browser, the first address opens there.
1. Open a printed address in a browser on any machine that reaches the box.
1. Select **Set this box up**.

The token is good for this run only. A page opened without it reads **This box is waiting to be set up**. To answer in the terminal instead, press Enter at **Continue in terminal (will close server)**; the same screens then run there, in English.

## Answer the wizard

**Next** moves on, **Back** returns, and nothing is written until the last screen.

### Language

Pick **English** or **简体中文** under **Language**. The panel is drawn in this language; the terminal stays English.

### Passwords and HTTPS

![The secrets screen with the HTTPS switch](/guide/en/setup_secrets.webp)

1. Type the **Panel password** twice. It has at least 8 characters, and it signs you in to the panel.
1. Type the **Vault master passphrase** twice. It has at least 16 characters with a lowercase letter, an uppercase letter, a digit and a symbol.
1. Optional: turn on **HTTPS for the panel**.

The passphrase seals every credential the box holds, and restoring a backup requires it again. With HTTPS on, the HTTP port sends every browser to the HTTPS port. The hub makes the panel's certificates either way, and [Settings](./settings.md#https) switches HTTPS later.

### Shape

![The shape screen with Server picked](/guide/en/setup_shape.webp)

**What is this machine for?** lists the shapes this machine has enough ports for:

| Shape              | What it does                                       |
| ------------------ | -------------------------------------------------- |
| **Server**         | Routes nothing; answers where it is reached.       |
| **Side gateway**   | Forwards for hosts that name it as their gateway.  |
| **Router**         | Routes between uplinks and the networks it serves. |
| **One-arm router** | Routes on one wire: untagged out, tagged VLAN in.  |

Server and side gateway keep every address on the machine. Router and one-arm router take the interfaces over. [Network](./network.md) describes each shape and changes it later.

### Ports

**Which ports?** shows the fields the chosen shape needs. Every shape has **Panel answers on port** for HTTP and **HTTPS port**, and the two must differ.

| Shape          | Fields                                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| Server         | none beyond the panel ports; every port keeps its address and answers                                  |
| Side gateway   | **Port on that network**, **This box's address**, **Prefix length**, **That network's own router**     |
| Router         | **Out to the internet**, **In to your devices**, **This box's address**, **Prefix length**             |
| One-arm router | **The one port, out and in**, **VLAN tag for your devices**, **This box's address**, **Prefix length** |

A router sets only its first uplink and its first served network here.

### Proxy

**Going out through a proxy** is optional, and [Proxy](./proxy.md) holds the same settings later. To set it up now, turn on **Set it up here** and paste each `ss://` or `vless://` link under **Exit node links**.

| Field                                                 | Shape            | What it sets                              |
| ----------------------------------------------------- | ---------------- | ----------------------------------------- |
| **SOCKS port applications point at**                  | Server           | a SOCKS port that leaves through the exit |
| **Also publish a SOCKS port that bypasses the proxy** | the other shapes | a second SOCKS port that leaves directly  |
| **Send this box's own traffic through it**            | every shape      | the box's own connections go to the exit  |

### Ready

**Ready** lists the shape, the language, the ports, the panel port, the HTTPS port, **HTTPS** on or off, and the proxy. Read it and select **Set this box up**. For a router or a one-arm router, a warning names the panel's new address and the log file, `/var/log/neutrino/setup.log`. The network can drop while the interfaces change; refresh the page to reconnect.

## Watch the steps

The screen reads **Making it so** and lists each step as it runs, from **Checking the packages the hub needs** to **Installing this machine's agent**. **Generating the panel's certificates** makes the hub's own certificate authority and the panel's certificate, on every run. The terminal shows the same steps.

![The finished screen offering the certificate](/guide/en/setup_done.webp)

When the title reads **This box is a gateway**, the next action depends on the HTTPS answer:

- With HTTPS off, the page moves to the panel by itself after a few seconds. **Open the panel** goes there at once.
- With HTTPS on, the page shows **Install the certificate on this device** with an **Install certificate** button. Under it is one tab per system, with your device's tab selected and its steps shown. Install the authority and check its fingerprint against the **SHA-256** line. Restart the browser, then open the panel's `https://` address.

The terminal prints the panel's address, and with HTTPS on, the authority's download address on the HTTP port and its fingerprint.

## Sign in

![The sign-in page](/guide/en/login.webp)

1. Open the panel's address. With HTTPS off, it is `http://` followed by the box's address and the panel port. With HTTPS on, it is `https://` followed by the box's address, and the HTTPS port when that is not `443`.
1. Type the **Panel password** and select **Sign in**.

The panel opens on the [Dashboard](./dashboard.md). After repeated wrong passwords, the sign-in page reads **Locked after repeated failures.**, and `sudo nhub unlock` on the box clears the lock.
