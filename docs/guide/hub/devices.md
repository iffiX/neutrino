---
title: Devices
---

# Devices

The **Devices** page lists every machine the hub has found. From it you enroll Linux, Windows and Mac machines, read their vitals, power them, and see who shares a desktop.

![Managed Linux, Windows and Mac machines on the Devices page](/guide/en/devices_managed.webp)

## Device states

The page has two sections, **Managed devices** and **Unmanaged devices**. Each tile shows one of the states below, and the filters **All**, **Agent**, **SSH**, **Scanned only**, **Online** and **Offline** narrow the list.

| State       | Meaning                                                            | Next action       |
| ----------- | ------------------------------------------------------------------ | ----------------- |
| **Agent**   | Managed: the agent reports the machine's vitals and takes modules. | open its drawer   |
| **SSH**     | Unmanaged, with a stored login: one action installs the agent.     | **Install agent** |
| **Scanned** | Unmanaged, with no credentials: it joins by an enrollment link.    | **Get link**      |
| **Offline** | Not answering; its credentials keep working when it returns.       | wait, or wake it  |

**Scan LAN** finds the machines connected to the networks the hub serves. The page badge reads how many are managed, as **2 of 5 managed**. The hub box itself is under **Managed devices** from the first sign-in, because `nhub setup` installs the agent there as it finishes.

## Before you enroll a machine

Every enrollment needs the following:

- The machine runs a system listed on [Supported platforms](../reference/platforms.md).
- You have root on it, or an administrator's account on Windows.
- It reaches the hub's agent port, 8443 by default.

An enrollment link is a `neutrino://enroll/` link that works for thirty minutes. **Add by link** at the top of the page makes one, and **Get link** in an unmanaged machine's drawer makes one for that row. A new link replaces the previous one.

![The enrollment link with its Copy button](/guide/en/devices_enroll_link.webp)

## Enroll a Linux machine by link

Download the agent package for the machine from the [releases page](https://github.com/iffiX/neutrino/releases), then:

1. On the machine, install the package with the command for its family.

   ::: code-group

   ```bash [Debian, Ubuntu, Raspberry Pi OS]
   sudo apt install ./neutrino-agent_0.5.0_amd64.deb
   ```

   ```bash [Fedora, RHEL family]
   sudo dnf install ./neutrino-agent-0.5.0-1.x86_64.rpm
   ```

   :::

1. In the panel, on **Devices**, select **Add by link**, then select **Copy**.
1. On the machine, run the join command, with the copied link in place of `<enroll-link>`:

   ```bash
   sudo nagent join <enroll-link>
   ```

Within seconds the machine appears under **Managed devices**. On ARM64 the files end in `_arm64.deb` and `.aarch64.rpm`. `apt` and `dnf` install the dependencies with the package, and `dpkg -i` or `rpm -i` install none of them.

`nagent join` with no link prompts for one. `--yes` replaces a binding the machine already has. The hub rejects a link that is spent, unknown or older than thirty minutes with `ticket_spent`.

## Install the agent over SSH

The hub can sign in to a Linux machine and install the agent itself. Store an SSH key or a login on [Credentials](./credentials.md) first, or add one from the dialog.

1. Under **Unmanaged devices**, open the machine's drawer.
1. Select **Install agent**.
1. Fill **Host**, **Port** and **Username**.
1. Under **Credential**, choose **SSH key** or **Password**, then pick the stored key or login.
1. Optional: under **Sudo password**, pick the login whose password `sudo` prompts for. Leave it empty for passwordless `sudo`.
1. Select **Install agent**.

![The SSH install dialog with host, port, username and credential](/guide/en/devices_install_ssh.webp)

**Install output** shows the installer as it runs, and the installer enrolls the machine with a link of its own. The hub reads the system first and rejects anything other than Linux with `unsupported_remote_install`. A wrong login fails inside the task, and **Install output** shows why.

## Enroll a Windows machine

The installer is `neutrino-agent-0.5.0-windows-amd64.msi`, for Windows 10 1809 or newer on x86-64. It registers the `neutrino_agent` service, which runs as LocalSystem at boot, and puts `nagent` on the system `PATH`. It also installs RustDesk with its own service and firewall rules.

1. Download the `.msi` from the releases page and run it.
1. Open a new terminal as administrator, so that it reads the new `PATH`.
1. In the panel, select **Add by link**, then select **Copy**.
1. In the terminal, run `nagent join` followed by the copied link.

For a silent install, run `msiexec /i neutrino-agent-0.5.0-windows-amd64.msi /qn` as administrator. The agent keeps its binding and its log, `agent.log`, under `C:\ProgramData\Neutrino\agent`, readable by SYSTEM and administrators only. Removing **Neutrino Agent** under **Apps** removes RustDesk too.

## Enroll a Mac

The installer is `neutrino-agent-0.5.0-macos-arm64.pkg`, for macOS 12.3 or newer on Apple silicon. It puts the agent under `/Library/Application Support/Neutrino/agent`, links `nagent` into `/usr/local/bin`, and adds `RustDesk.app` to `/Applications`. The `com.neutrino.agent` LaunchDaemon runs the agent as root and writes to `/Library/Logs/neutrino_agent.log`.

1. Install the package:

   ```bash
   sudo installer -pkg neutrino-agent-0.5.0-macos-arm64.pkg -target /
   ```

1. In the panel, select **Add by link**, then select **Copy**.
1. Run `sudo nagent join` followed by the copied link.
1. In **System Settings** > **Privacy & Security**, turn on RustDesk under **Screen Recording** and under **Accessibility**.

Until RustDesk holds both permissions, the drawer shows `rdp_permissions_needed` and a viewer sees nothing.

Windows and Macs run the file share, VS Code and the remote desktop; Gitea, containers and ZFS are Linux only. [Modules](../agent/modules.md) greys out what a machine cannot run. Every `nagent` subcommand is on [nagent commands](../commands/nagent.md).

## The drawer

Selecting a machine opens its drawer. A managed machine shows a **Live monitor** first: CPU, memory, disk, load, uptime and the busiest processes, each with **Kill process**. Windows rejects killing a process from here.

Below the monitor come **Identity**, with **Display name** and **Icon**, then **Actions**, **Remote desktop**, **Action output** and **Agent command results**. **Terminal** and **Files** at the top open those pages on this machine.

| Action              | What happens                                                                                                                                                                                                                                       |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Reinstall agent** | A reporting agent installs the hub's package again; a silent one gets the SSH dialog.                                                                                                                                                              |
| **Reboot**          | The machine restarts at once.                                                                                                                                                                                                                      |
| **Shut down**       | The machine powers off at once.                                                                                                                                                                                                                    |
| **Wake-on-LAN**     | The hub sends a magic packet to UDP 9 on every network it serves, or, set up as a server, on every network it is exposed on; never across NetBird or EasyTier. The machine wakes only with Wake-on-LAN armed in its firmware and its network card. |
| **Forget device**   | The row and its SSH settings leave the hub; keys and logins stay on Credentials.                                                                                                                                                                   |

**Reboot** and **Shut down** open a confirmation first, and anything unsaved on the machine is lost. An action on a machine that is not answering returns `agent_offline`. A forgotten machine keeps its agent, and a fresh link enrolls it again.

## Share a desktop

The remote desktop is RustDesk, included in the agent package. The machine's [Remote desktop](../agent/modules/remote_desktop.md) switch on the Modules page starts and stops the share, and the hub sets and keeps the seat password.

1. On the machine's **Remote desktop** tab, turn on **Share this machine's desktop** and select **Apply remote desktop**. The drawer's link **Sharing is set on the machine's Remote desktop tab.** opens that tab.
1. In the drawer, read **Remote desktop**: the **ID**, **Direct port 21118**, **Shared by** and the number of viewers.
1. In a client, under **Remote desktops**, select **Connect**.

![The drawer's Remote desktop section with ID, direct port and sharing account](/guide/en/devices_drawer_rdp.webp)

The shared desktop is the one of whoever is signed in at the screen. Turning the switch off ends the share. **Reset seat password** gives the machine a new password at once, and every connected viewer connects again.

The drawer shows `rdp_nobody_seated` when nobody is signed in at the screen. It shows `rdp_screen_not_allowed` when a Wayland session has not allowed screen sharing; allow it once at that screen. Where AnyDesk or TeamViewer is installed, the same section shows its ID and **Set unattended password**.

## A machine on a different version

The drawer and the tile show **This agent is a different version from the hub.** An agent that the hub admits updates itself to the hub's version when it connects. When that update fails, **Reinstall agent** in the drawer installs the hub's version.

From 0.5.0 the hub admits only protocol 3, so a 0.3 or 0.4 agent is rejected with `protocol_too_old` and stays **Offline**. Its binding survives, and the machine connects again after its package is replaced:

| Machine                  | How the agent is replaced                                                |
| ------------------------ | ------------------------------------------------------------------------ |
| Linux reachable over SSH | **Reinstall agent** in the drawer, which opens the SSH dialog            |
| Linux without one        | the new package installed with `apt` or `dnf`, as in the first procedure |
| Windows                  | the new `.msi` run over the old one                                      |
| Mac                      | the new `.pkg` installed over the old one                                |

On the machine, `sudo nagent status` names the rejection while it lasts. The order that keeps hub, agents and clients talking is on [Settings](./settings.md#upgrade-from-0-4).
