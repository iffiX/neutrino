---
title: Install the agent
---

# Install the agent

A machine joins the hub with a link pasted on it or with an SSH install from the panel. Either way it ends up under **Managed devices** on the **Devices** page, ready to take modules.

## Before you start

The machine needs all of the following:

- It runs Linux, x86-64 or ARM64: Debian 12 or newer, Ubuntu 24.04 or newer, Raspberry Pi OS 64-bit, Fedora 41 or newer, or the RHEL 9 family.
- You have root on it. Every `nagent` command runs as root.
- It reaches port 8443 on the hub, the channel the agent connects on.

The agent is headless. It runs as a service and opens one connection to the hub, over which the panel drives it. There is one link per hub at a time, and a new link replaces the previous one.

## Enroll with a link

1. In the panel, open **Devices**.
1. Select **Add by link**. The notice holds a `neutrino://enroll/` link and a **Copy** button; the link is valid for five minutes.
   ![The enrollment link notice](/guide/en/devices_enroll_link.webp)
1. On the machine, install the package as in [Install the package by hand](#install-the-package-by-hand).
1. On the machine, run `sudo nagent connect '<link>'`, where `<link>` is the copied link. The command returns, and within seconds the machine is listed under **Managed devices**.

![Managed devices after the enrollment](/guide/en/devices_managed.webp)

The link is base64url, so it can be pasted into a shell with or without the quotes. The hub rejects a spent or expired link with `enrollment_link_spent`.

## Install from the panel over SSH

The panel installs the agent on a machine it can sign in to. The login comes from [the Credentials page](../hub/credentials.md), where you store an **SSH key** or a **Login** first.

1. On **Devices**, find the machine under **Unmanaged devices**; **Scan LAN** discovers what is connected.
1. Open the machine's drawer and select **Install agent**.
   ![The install dialog with host, port, username and credential](/guide/en/devices_install_ssh.webp)
1. Fill **Host**, **Port** and **Username**, pick the **Credential**, and give a **Sudo password** where the account needs one for `sudo`.
1. Select **Install agent**. The **Install output** panel streams the installer, which enrolls the machine by itself.

The hub rejects a machine that reports another operating system with `unsupported_remote_install`; the SSH installer is for Linux. A login the machine turned away is rejected with `install_credentials_invalid`.

## Install the package by hand

::: code-group

```bash [Debian, Ubuntu, Raspberry Pi OS]
sudo apt install ./neutrino-agent_0.2.0_amd64.deb
```

```bash [Fedora, RHEL, AlmaLinux, Rocky]
sudo dnf install ./neutrino-agent-0.2.0-1.x86_64.rpm
```

:::

On ARM64 the file is `neutrino-agent_0.2.0_arm64.deb` or `neutrino-agent-0.2.0-1.aarch64.rpm`. The package includes its own interpreter and the RustDesk host; the desktop libraries it depends on are for that host. The service starts on install and binds to a hub with `sudo nagent connect '<link>'`; `--yes` replaces an existing binding.

## The hub's own agent

Setup installs the agent on the hub box in its last step, so the box is under **Managed devices** from the first sign-in. It takes modules like any other device: the Samba share in [the quick start](../quick-start.md) is on the hub box, hosted by that agent.

## After enrollment

Each module is enabled per device on its own page, under **Agent** in the panel's sidebar:

| Module                      | Page                                         |
| --------------------------- | -------------------------------------------- |
| A root shell on the machine | [Terminals](../hub/terminals.md)             |
| Its files                   | [Files](../hub/files.md)                     |
| SMB shares                  | [Samba](../hub/samba.md)                     |
| A private git server        | [Gitea](../hub/gitea.md)                     |
| Containers under podman     | [Containers](../hub/containers.md)           |
| Pools and datasets          | [ZFS](../hub/zfs.md)                         |
| Its desktop, shared         | [Devices](../hub/devices.md#share-a-desktop) |
