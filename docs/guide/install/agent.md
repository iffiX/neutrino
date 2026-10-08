---
title: Install an agent
---

# Install an agent

With the agent installed and joined, a Linux, macOS or Windows machine is listed under **Managed devices** on the hub's **Devices** page, online. You install it with one command or from the package file, and the hub can install it on a Linux machine over SSH. The hub's own machine already has its agent, from the setup wizard.

## Before you start

- The machine runs a system that [Supported platforms](../reference/platforms.md) lists for the agent.
- You have root on the machine, or an administrator account on Windows.
- The machine reaches the hub's port 8443.

## Get an enrollment link

1. In the panel, open **Devices**.
1. Select **Add by link**.
1. Select **Copy**.

![The enrollment link with its Copy button](/guide/en/devices_enroll_link.webp)

For a machine already listed under **Unmanaged devices**, **Get link** in its drawer makes a link for that row. A link works for thirty minutes and joins one machine, and a restart of the hub keeps it. A new link replaces the one before it.

## Install with one command

The install script picks the agent package for the machine, checks it against the release's `SHA256SUMS`, installs it, and prints the join command.

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

Open PowerShell and run the command for your edition. The script prompts Windows for administrator rights and continues in the PowerShell window that Windows opens as administrator.

For the full edition:

```powershell
& ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) agent
```

For the mainland edition:

```powershell
& ([scriptblock]::Create((irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1))) agent
```

In the administrator window, join the hub, with the copied link in place of `<enroll-link>`:

```powershell
nagent join '<enroll-link>'
```

## Install from the package file

Download the agent's file for the machine from the [releases page](https://github.com/iffiX/neutrino/releases). On every system the last command is `nagent join`, with the copied link in place of `<enroll-link>`.

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

On ARM64 the files are `neutrino-agent_0.5.0_arm64.deb` and `neutrino-agent-0.5.0-1.aarch64.rpm`. `apt` and `dnf` install the package's dependencies with it, and `dpkg -i` and `rpm -i` install none of them.

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
1. Open a new PowerShell as administrator, so that it reads the new `PATH`.
1. Run `nagent join '<enroll-link>'`.

For a silent install, run `msiexec /i neutrino-agent-0.5.0-windows-amd64.msi /qn` as administrator.

## Let the hub install it over SSH

For a Linux machine that the hub reaches over SSH, the hub signs in and installs the agent itself. Store the machine's SSH key or login on [Credentials](../hub/credentials.md) first.

1. On **Devices**, under **Unmanaged devices**, open the machine's drawer.
1. Select **Install agent**.
1. Fill **Host**, **Port** and **Username**.
1. Under **Credential**, choose **SSH key** or **Password**, then pick the stored key or login.
1. Optional: under **Sudo password**, pick the login whose password `sudo` prompts for.
1. Select **Install agent**.

![The SSH install dialog with host, port, username and credential](/guide/en/devices_install_ssh.webp)

**Install output** shows the installer as it runs, and the installer joins the machine with a link of its own. The hub reads the machine's system first and rejects anything other than Linux with `unsupported_remote_install`.

## Check the machine

Within seconds of the join, the machine is listed under **Managed devices**. On the machine, `sudo nagent status` names the hub it joined; on Windows, run `nagent status` in an administrator PowerShell. Its `heartbeat` line reads `ok` while the agent holds its connection to the hub.

`nagent join` without a link prompts for one, and `--yes` replaces a binding the machine already has. The hub rejects a link that is used or older than thirty minutes with `ticket_spent`; make a new link and join again.

## What the package leaves on the machine

| System  | Service                                        | Log                                           |
| ------- | ---------------------------------------------- | --------------------------------------------- |
| Linux   | the systemd unit `neutrino_agent`, as root     | the unit's journal                            |
| Windows | the service `neutrino_agent`, as LocalSystem   | `C:\ProgramData\Neutrino\agent\log\agent.log` |
| macOS   | the LaunchDaemon `com.neutrino.agent`, as root | `/Library/Logs/Neutrino/agent/agent.log`      |

Every agent package keeps its own copy of RustDesk in the agent's folder. The agent registers RustDesk's service only while the machine's **Remote desktop** switch is on. Removing the package keeps the file shares and their accounts on the machine, and an agent installed again takes them back.
