---
title: Devices
---

# Devices

The **Devices** page lists every machine the hub has found, managed or not. A machine's drawer shows its vitals, restarts, shuts down or wakes it, and shows who shares its desktop.

![The Devices page with hub, server, desktop and laptop online](/guide/en/devices_managed.webp)

## Device states

The page has two sections, **Managed devices** and **Unmanaged devices**. Each tile shows one of these states:

| State       | Meaning                                                          | Next action                                     |
| ----------- | ---------------------------------------------------------------- | ----------------------------------------------- |
| **Agent**   | Managed: the agent reports the machine and takes modules.        | open its drawer                                 |
| **SSH**     | Unmanaged, with a stored login.                                  | **Install agent**                               |
| **Scanned** | Unmanaged, with no credentials.                                  | **Get link**                                    |
| **Offline** | Not answering. It keeps its place and token for when it returns. | wake it, or install 0.5.0 on a 0.3 or 0.4 agent |

The filters above the list narrow it by state. **Scan LAN** finds the machines on the networks the hub serves. The hub box is under **Managed devices** from the first sign-in, in a row named after its hostname. To rename the row, type a **Display name** in its drawer and select **Save device**.

## Add a machine

A machine joins through **Add by link** at the top of the page, or **Get link** or **Install agent** in its drawer. The steps are in [Install an agent](../install/agent.md).

## The drawer

A managed machine's drawer opens on **Live monitor**: CPU, memory, disk, load, uptime and the busiest processes, each with **Kill process**. **Terminal** and **Files** at the top open those pages on this machine.

| Action              | What happens                                                                                  |
| ------------------- | --------------------------------------------------------------------------------------------- |
| **Reinstall agent** | The agent installs the hub's agent package again; a silent Linux machine gets the SSH dialog. |
| **Reboot**          | The machine restarts at once, after a confirmation.                                           |
| **Shut down**       | The machine powers off at once, after a confirmation.                                         |
| **Wake-on-LAN**     | The hub sends a wake packet on the networks it serves, or in server mode on its exposed ones. |
| **Forget device**   | The row and its SSH settings leave the hub; keys and logins stay on **Credentials**.          |

Wake-on-LAN works from a panel opened over a virtual network too, because the box sends the packet. A machine wakes only with Wake-on-LAN turned on in its firmware and network card, and only on the box's own networks. A forgotten machine keeps its agent, and a new link adds it again.

## Share a desktop

The remote desktop is RustDesk. The **Share this machine's desktop** switch on the machine's **Remote desktop** tab starts and stops the share, as described in [Remote desktop](../agent/modules/remote_desktop.md).

![The drawer's Remote desktop section with ID, direct port and sharing account](/guide/en/devices_drawer_rdp.webp)

The drawer's **Remote desktop** section shows the machine's **ID**, **Direct port 21118**, **Shared by** with the account at the screen, and the number of viewers. **Reset seat password** gives the machine a new password at once, and every connected viewer connects again. Where AnyDesk or TeamViewer is installed, the section shows its ID and **Set unattended password**.

When the section shows a code, the cause is on [Troubleshooting](../reference/troubleshooting.md).

## Which modules a system runs

Windows and Macs run the file share, the terminal, the remote desktop, Gitea, VS Code and CloudCLI, and Macs also run code-server. Containers and ZFS storage run on Linux only. The **Modules** page greys out what a machine cannot run, and [Supported platforms](../reference/platforms.md) has the full table.

## A machine on another version

The drawer and the tile show **This agent is a different version from the hub.** An agent updates itself to the hub's version when it connects. When that update fails, select **Reinstall agent** in the drawer.

A 0.3 or 0.4 agent stays **Offline**, because the 0.5.0 hub rejects it, and it cannot update from the hub. Install the 0.5.0 agent package on the machine and join it with a new link.
