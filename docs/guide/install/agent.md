---
title: Install an agent
---

# Install an agent

An agent goes on each machine whose terminal, files, desktop or modules you open from a client; the hub's own machine has one already. This page installs it and joins it to the hub with a link.

## Before you start

- The machine runs a system that [Supported platforms](../reference/platforms.md) lists for the agent.
- You have root on the machine, or an administrator account on Windows.
- The machine reaches the hub's port 8443.

## Get an enrollment link

1. In the panel, open **Devices**.
1. Select **Add by link**.
1. Select **Copy**.

![The enrollment link with its Copy button](/guide/en/devices_enroll_link.webp)

The link is valid for 30 minutes. For a machine listed under **Unmanaged devices**, **Get link** in its drawer makes one too.

## Install with one command

The install script checks the agent package against the release's `SHA256SUMS` and installs it.

### Linux and macOS

For the full edition, run:

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
```

For the mainland edition, run:

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh -s -- agent
```

Then join the hub, with the copied link in place of `<enroll-link>`:

```bash
sudo nagent join '<enroll-link>'
```

### Windows

In PowerShell, run the command for your edition, then accept the administrator prompt. For the full edition:

```powershell
& ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) agent
```

For the mainland edition:

```powershell
& ([scriptblock]::Create((irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1))) agent
```

In the administrator window, join the hub with the copied link:

```powershell
nagent join '<enroll-link>'
```

## Install from the package file

Download the agent's file for the machine from the [releases page](https://github.com/iffiX/neutrino/releases), or for the mainland edition from the [Gitee releases page](https://gitee.com/iffiX/neutrino/releases).

### Linux

1. Install the file with the command for the machine's family:

   ::: code-group

   ```bash [Debian, Ubuntu, Raspberry Pi OS]
   sudo apt install ./neutrino-agent_0.5.0_amd64.deb
   ```

   ```bash [Fedora, RHEL family]
   sudo dnf install ./neutrino-agent-0.5.0-1.x86_64.rpm
   ```

   :::

1. Join the hub:

   ```bash
   sudo nagent join '<enroll-link>'
   ```

On ARM64 the files are `neutrino-agent_0.5.0_arm64.deb` and `neutrino-agent-0.5.0-1.aarch64.rpm`.

### macOS

1. Install the package:

   ```bash
   sudo installer -pkg neutrino-agent-0.5.0-macos-arm64.pkg -target /
   ```

1. Join the hub:

   ```bash
   sudo nagent join '<enroll-link>'
   ```

On an Intel Mac the file is `neutrino-agent-0.5.0-macos-amd64.pkg`.

### Windows

1. Run `neutrino-agent-0.5.0-windows-amd64.msi`.
1. Open a new PowerShell as administrator.
1. Run `nagent join '<enroll-link>'`.

## Let the hub install it over SSH

The hub can sign in to a Linux machine over SSH and install the agent itself. Before you start, store the machine's SSH key or login on [Credentials](../hub/credentials.md).

1. On **Devices**, under **Unmanaged devices**, open the machine's drawer.
1. Select **Install agent**.
1. Fill **Host**, **Port** and **Username**.
1. Under **Credential**, choose **SSH key** or **Password**, then pick the stored key or login.
1. Optional: under **Sudo password**, pick the login whose password `sudo` prompts for.
1. Select **Install agent**.

![The SSH install dialog with host, port, username and credential](/guide/en/devices_install_ssh.webp)

**Install output** shows the installer as it runs, and the installer joins the machine by itself.

## Check the machine

Within seconds of the join, the machine is listed under **Managed devices**. On the machine, `sudo nagent status` names the hub it joined, and its `heartbeat` line reads `ok` while the agent is connected. When the join fails, the cause is on [Troubleshooting](../reference/troubleshooting.md).

## What the package leaves on the machine

The agent runs as a system service: `neutrino_agent` on Linux and Windows, `com.neutrino.agent` on macOS. It registers its copy of RustDesk as a service only while the machine's **Remote desktop** switch is on. Removing the agent is on [Uninstall](../uninstall.md).
