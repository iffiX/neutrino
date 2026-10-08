---
title: Devices
---

# Devices

The **Devices** page lists every machine the hub has found, managed or not. From a machine's drawer you read its vitals, restart, shut down or wake it, and see who shares its desktop.

![The Devices page with hub, server, desktop and laptop online](/guide/en/devices_managed.webp)

## Device states

The page has two sections, **Managed devices** and **Unmanaged devices**. Each tile shows one of these states:

| State       | Meaning                                                            | Next action       |
| ----------- | ------------------------------------------------------------------ | ----------------- |
| **Agent**   | Managed: the agent reports the machine's vitals and takes modules. | open its drawer   |
| **SSH**     | Unmanaged, with a stored login: one action installs the agent.     | **Install agent** |
| **Scanned** | Unmanaged, with no credentials: it joins with an enrollment link.  | **Get link**      |
| **Offline** | Not answering. Its binding keeps working when it returns.          | wake it           |

The filters **All**, **Agent**, **SSH**, **Scanned only**, **Online** and **Offline** narrow the list. **Scan LAN** finds the machines on the networks the hub serves, and the page badge counts them, as **2 of 5 managed**.

The hub box is under **Managed devices** from the first sign-in, in the row `hub`, because `nhub setup` installs its agent.

## Add a machine

A machine joins the hub through **Add by link** at the top of the page, or **Get link** or **Install agent** in its drawer. The steps for Linux, Windows and macOS are in [Install an agent](../install/agent.md).

## The drawer

Selecting a machine opens its drawer. A managed machine shows a **Live monitor** first: CPU, memory, disk, load, uptime and the busiest processes, each with **Kill process**. Windows rejects killing a process from here.

Under the monitor come **Identity**, with **Display name** and **Icon**, then **Actions**, **Remote desktop**, **Action output** and **Agent command results**. **Terminal** and **Files** at the top open those pages on this machine.

| Action              | What happens                                                                                                     |
| ------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **Reinstall agent** | A reporting agent installs the hub's agent package again; a silent Linux machine gets the SSH dialog.            |
| **Reboot**          | The machine restarts at once.                                                                                    |
| **Shut down**       | The machine powers off at once.                                                                                  |
| **Wake-on-LAN**     | The hub sends a wake packet to the machine on the networks it serves, or in server mode on its exposed networks. |
| **Forget device**   | The row and its SSH settings leave the hub; keys and logins stay on the **Credentials** page.                    |

**Reboot** and **Shut down** open a confirmation, and anything unsaved on the machine is lost. A wake packet never crosses NetBird or EasyTier, and the machine wakes only with Wake-on-LAN armed in its firmware and network card. An action on a machine that is not answering returns `agent_offline`. A forgotten machine keeps its agent, and a new link adds it again.

## Share a desktop

The remote desktop is RustDesk, included in the agent package. The **Share this machine's desktop** switch on the machine's **Remote desktop** tab starts and stops the share, as described in [Remote desktop](../agent/modules/remote_desktop.md). The drawer line **Sharing is set on the machine's Remote desktop tab.** opens that tab.

![The drawer's Remote desktop section with ID, direct port and sharing account](/guide/en/devices_drawer_rdp.webp)

The drawer's **Remote desktop** section shows the machine's **ID**, **Direct port 21118**, **Shared by** with the account at the screen, and the number of viewers. The shared desktop belongs to whoever is signed in at the screen. **Reset seat password** gives the machine a new password at once, and every connected viewer connects again.

The section shows a code when the desktop cannot be shared:

| Code                     | Cause                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------- |
| `rdp_nobody_seated`      | Nobody is signed in at the machine's screen.                                                   |
| `rdp_screen_not_allowed` | A Wayland session has not allowed screen sharing; allow it once at that screen.                |
| `rdp_permissions_needed` | On a Mac, RustDesk lacks **Screen Recording** and **Accessibility** in **Privacy & Security**. |

Where AnyDesk or TeamViewer is installed, the same section shows its ID and **Set unattended password**.

## Which modules a system runs

Windows and Macs run the file share, the terminal, the remote desktop, Gitea, VS Code and CloudCLI, and Macs also run code-server. Containers and ZFS storage run on Linux only. The **Modules** page greys out what a machine cannot run, and the full table is in [Supported platforms](../reference/platforms.md).

## A machine on another version

The drawer and the tile show **This agent is a different version from the hub.** An agent the hub admits updates itself to the hub's version when it connects. When that update fails, select **Reinstall agent** in the drawer.

The 0.5.0 hub rejects a 0.3 or 0.4 agent with `protocol_too_old`, and the machine stays **Offline**. Such an agent cannot update from the hub. Install the 0.5.0 agent package on the machine and join it with a new link, as described in [Install an agent](../install/agent.md).
