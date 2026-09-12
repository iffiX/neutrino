---
title: Install the hub
---

# Install the hub

Installing the hub is one package and one run of `sudo nhub setup`. When the wizard finishes, the panel is at `http://<hub>:8080`, where `<hub>` is the address of the box, and you sign in. The shape installed here is server mode, which keeps every address the box has.

## Before you start

The box must meet these conditions:

- It stays on, and it runs one of the supported systems: Debian 12 or newer, Ubuntu 24.04 or newer, Raspberry Pi OS 64-bit, Fedora 41 or newer, the RHEL 9 family, or Arch. [Supported platforms](../reference/platforms.md) has the full matrix.
- You have root on it.
- It has internet access, because the setup fetches packages.

The other shapes, side gateway and router, take over the box's interfaces; [the Network page](./network.md) describes them.

## Install the package

::: code-group

```bash [Debian, Ubuntu, Raspberry Pi OS]
sudo apt install ./neutrino-hub_0.2.0_amd64.deb
```

```bash [Fedora]
sudo dnf install ./neutrino-hub-0.2.0-1.x86_64.rpm
```

```bash [RHEL, AlmaLinux, Rocky]
sudo dnf install -y epel-release
sudo dnf install ./neutrino-hub-0.2.0-1.x86_64.rpm
```

```bash [Arch, EndeavourOS, Manjaro]
sudo pacman -U neutrino-hub-0.2.0-1-x86_64.pkg.tar.zst
```

:::

On ARM64 the file is `neutrino-hub_0.2.0_arm64.deb` or `neutrino-hub-0.2.0-1.aarch64.rpm`. The package includes its own Python under `/opt/neutrino/python`. On the RHEL family, fail2ban, arp-scan and vnstat come from EPEL.

## Start the setup wizard

1. Run `sudo nhub setup`. The command prints an address holding a one-time token and, where the box has a browser, opens the wizard there.
1. Open the printed address in a browser on the same network.
1. Select **Set this box up**.

![The setup wizard's welcome screen](/guide/en/setup_welcome.webp)

To answer in the terminal instead, press Enter at its prompt; the same screens then run in the terminal, in English.

## Answer the six screens

**Next** moves to the following screen, **Back** returns to the previous one, and nothing is written until the last screen is confirmed.

1. On **Language**, pick the language the panel is drawn in.
1. On **A password for the panel, a passphrase for the vault**, type a **Panel password** and a **Vault master passphrase**. The password signs you in; the passphrase seals every credential the box holds, and a restore from backup requires it again.
   ![The secrets screen](/guide/en/setup_secrets.webp)
1. On **What is this machine for?**, pick **Server**.
   ![The shape screen with Server picked](/guide/en/setup_shape.webp)
1. On **Which ports?**, keep **Panel answers on port** at `8080`. In server mode every interface keeps its address, and the panel listens on every interface.
   ![The ports screen in server mode](/guide/en/setup_ports.webp)
1. On **Going out through a proxy**, leave **Set it up here** off. You can set up a proxy later on [the Proxy page](./proxy.md).
   ![The proxy screen, skipped](/guide/en/setup_proxy.webp)
1. On **Ready**, read the summary and confirm it.
   ![The review screen](/guide/en/setup_review.webp)

::: warning
The vault opens only with its passphrase. A lost passphrase means every credential and AI account is entered again after a reset.
:::

## Open the panel

The steps run on the screen, from checking packages to installing this machine's own agent, and end with **This box is a gateway**. The page then moves to the panel by itself; **Open the panel** does the same.

![The done screen](/guide/en/setup_done.webp)

1. Open `http://<hub>:8080`.
   ![The sign-in page](/guide/en/login.webp)
1. Type the panel password and select **Sign in**.

The last setup step installed this machine's own agent, so **Devices** already lists the box under **Managed devices**.

![Managed devices with the hub's own machine](/guide/en/devices_managed.webp)

## After the first sign-in

| Goal                                       | Page                                                                                   |
| ------------------------------------------ | -------------------------------------------------------------------------------------- |
| Change the shape to side gateway or router | [Network](./network.md)                                                                |
| Reach the box and the LAN from outside     | [Overlay: NetBird](./overlay-netbird.md) or [Overlay: EasyTier](./overlay-easytier.md) |
| Send traffic through an exit node          | [Proxy](./proxy.md)                                                                    |
