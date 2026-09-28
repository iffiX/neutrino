---
title: Install the agent
---

# Install the agent

A machine joins the hub with a link pasted on it or with an SSH install from the panel. Either way it ends up under **Managed devices** on the **Devices** page, ready to take modules.

## Before you start

The machine needs all of the following:

- It runs Linux, x86-64 or ARM64: Debian 12 or newer, Ubuntu 22.04 or newer, Raspberry Pi OS 64-bit, Fedora 41 or newer, or the RHEL 9 family. It can also run Windows 10 1809 or newer on x86-64, or macOS 12.3 or newer on Apple silicon.
- You have root on it, or an administrator's account on Windows. Every `nagent` command runs as root or as an administrator.
- It reaches port 8443 on the hub, the channel the agent connects on.

The agent is headless. It runs as a service and opens one connection to the hub, over which the panel drives it. There is one link per hub at a time, and a new link replaces the previous one.

The binding holds every address the hub listens on, from the link and then from the hub itself. When the connection drops, the agent connects to each in turn, the name `hub.neutrino.internal` first on a network the hub serves.

## Enroll with a link

1. In the panel, open **Devices**.
1. Select **Add by link**. The notice holds a `neutrino://enroll/` link and a **Copy** button; the link is valid for five minutes.
   ![The enrollment link notice](/guide/en/devices_enroll_link.webp)
1. On the machine, install the package as in [Install the package by hand](#install-the-package-by-hand), [Install on Windows](#install-on-windows) or [Install on macOS](#install-on-macos).
1. On the machine, run `sudo nagent join '<link>'`, where `<link>` is the copied link. On Windows, run `nagent join <link>` in a terminal opened as administrator. The command returns, and within seconds the machine is listed under **Managed devices**.

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
sudo apt install ./neutrino-agent_0.3.0_amd64.deb
```

```bash [Fedora, RHEL, AlmaLinux, Rocky]
sudo dnf install ./neutrino-agent-0.3.0-1.x86_64.rpm
```

:::

`apt` and `dnf` install the dependencies with the package.

::: warning
Do not install with `dpkg -i` or `rpm -i`: they install none of the dependencies. If you already did, run `sudo apt -f install` (Debian family) or `sudo dnf install <the packages it named>` (Fedora family) to finish the install.
:::

On ARM64 the file is `neutrino-agent_0.3.0_arm64.deb` or `neutrino-agent-0.3.0-1.aarch64.rpm`. The package includes its own interpreter and the RustDesk host; the desktop libraries it depends on are for that host. The service starts on install and binds to a hub with `sudo nagent join '<link>'`; `--yes` replaces an existing binding.

## Install on Windows

The Windows installer is `neutrino-agent-0.3.0-windows-amd64.msi`, for Windows 10 1809 or newer on x86-64. It installs the agent as the `neutrino_agent` service, which runs as LocalSystem and starts at boot, and puts `nagent` on the system `PATH`. It also runs RustDesk's own installer, which adds the `RustDesk` service and its firewall rules.

1. Download the `.msi` from the [releases page](https://github.com/iffiX/neutrino/releases) and run it, or run `msiexec /i neutrino-agent-0.3.0-windows-amd64.msi /qn` from a terminal opened as administrator.
1. Open a new terminal as administrator, so that it reads the new `PATH`.
1. Run `nagent join <link>` with the link from the **Devices** page.

The agent keeps its binding and state under `C:\ProgramData\Neutrino\agent`, readable by SYSTEM and administrators only, and writes its log to `agent.log` there. Removing **Neutrino Agent** under **Apps** also removes RustDesk.

## Install on macOS

The macOS installer is `neutrino-agent-0.3.0-macos-arm64.pkg`, for macOS 12.3 or newer on Apple silicon. It installs the agent under `/Library/Application Support/Neutrino/agent` with `nagent` linked into `/usr/local/bin`, and `RustDesk.app` under `/Applications`. The `com.neutrino.agent` LaunchDaemon runs the agent as root at boot and writes its output to `/Library/Logs/neutrino_agent.log`.

1. Run `sudo installer -pkg neutrino-agent-0.3.0-macos-arm64.pkg -target /`.
1. Run `sudo nagent join '<link>'` with the link from the **Devices** page.
1. In **System Settings** > **Privacy & Security**, turn on RustDesk under **Screen Recording** and under **Accessibility**.

Until RustDesk has both permissions, a shared desktop shows a viewer nothing, and the device drawer shows the `rdp_permissions_needed` attention. The agent reads the permissions from the system's privacy database; where macOS keeps that database from root, the attention stays.

## Windows and macOS machines

On Windows and macOS the agent reports the machine's status and metrics, opens a terminal, and shares the desktop. The Samba, Gitea, container and ZFS modules are Linux only, and the SSH installer does not reach these machines.

| Item          | Windows                                          | macOS                                              |
| ------------- | ------------------------------------------------ | -------------------------------------------------- |
| Terminal      | PowerShell                                       | `zsh` as a login shell                             |
| Oldest system | Windows 10 1809, the first with a pseudo console | macOS 12.3, the oldest the RustDesk app runs on    |
| Update        | the hub's release `.msi`, installed by `msiexec` | the hub's release `.pkg`, installed by `installer` |

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
