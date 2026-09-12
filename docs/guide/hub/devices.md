---
title: Devices
---

# Devices

Every machine the hub has seen is on the **Devices** page. There you enroll a machine, read its vitals, reboot or wake it, and open its shared desktop. The agent is Linux only.

## The three states

The page has two sections, **Managed devices** and **Unmanaged devices**, and every machine is in one of three states, with a filter for each:

| State       | Meaning                                                         | Next action       |
| ----------- | --------------------------------------------------------------- | ----------------- |
| **Agent**   | Managed: reports its own vitals and takes modules from the hub. | open its drawer   |
| **SSH**     | Unmanaged with credentials: one action installs the agent.      | **Install agent** |
| **Scanned** | Unmanaged with no credentials: send it an enrollment link.      | **Get link**      |

An **Offline** machine is one that is not answering; its credentials keep working when it returns. **Scan LAN** finds the machines connected to the LAN. The badge reads how many of them are managed, as **2 of 5 managed**.

![The Devices page with managed and unmanaged machines](/guide/en/devices_overview.webp)

## Enroll a machine

**Add by link** shows a `neutrino://enroll/` link that is valid for five minutes. On the machine, `sudo nagent connect '<link>'` joins the hub, where `<link>` is the link shown. **Install agent**, in an unmanaged machine's drawer, makes the hub sign in over SSH with a stored credential and run the installer. The installer enrolls the machine. Both procedures are on [the agent's install page](../agent/install.md).

![The enrollment link](/guide/en/devices_enroll_link.webp)

![The SSH install dialog](/guide/en/devices_install_ssh.webp)

The hub dials a machine over SSH only to install or reinstall the agent; everything else goes over the connection the agent opens.

## The drawer

Selecting a managed machine opens its drawer: **Identity**, **Actions**, **Remote desktop**, **Terminal**, **Files**, **Action output** and **Agent command results**, with the machine's vitals at the top.

![The device drawer](/guide/en/devices_drawer.webp)

| Action              | What the machine does                                    |
| ------------------- | -------------------------------------------------------- |
| **Reboot**          | reboots at once                                          |
| **Shut down**       | powers off at once                                       |
| **Wake-on-LAN**     | receives a magic packet on UDP 9 on every served network |
| **Reinstall agent** | receives the installer again over SSH                    |
| **Forget device**   | is deleted from the box with its saved credentials       |

A power action is immediate, and anything unsaved on the machine is lost; the confirmation says so. An offline machine is rejected with `agent_offline`. A forgotten machine keeps its agent, and a fresh link enrolls it again.

## Share a desktop

The remote desktop is RustDesk. The agent package includes the host and the client package includes the viewer. The hub sets the seat password and keeps it.

1. On the machine, run `sudo nagent rdp start`. With no `--user`, the command shares the desktop of the account that ran `sudo`; when none did, it shares the one account signed in at the screen.
1. In the drawer, read **Remote desktop**: the **ID**, **Direct port 21118** and **Shared by** the account.
   ![The drawer's remote desktop panel](/guide/en/devices_drawer_rdp.webp)
1. In the client window, under **Remote desktops**, select **Connect**. The viewer opens on that desktop.
   ![The client's Remote desktops panel](/guide/en/client_desktop_connect.webp)

**Reset seat password** gives the machine a new password at once, and every viewer connected at that moment must connect again. `sudo nagent rdp stop` ends the share, and the entry leaves the clients. The panel marks a machine where nobody is signed in with `rdp_nobody_seated`. A machine whose Wayland session has not granted screen sharing is marked `rdp_screen_not_allowed`; the grant is given once at the machine's own screen.

## A different version

An agent on another version than the hub is marked in the drawer with **This agent is a different version from the hub.** With a stored SSH credential, **Reinstall agent** brings it to the hub's version; without one, a fresh link from **Add by link** does. An agent newer than the hub is rejected with `agent_newer_than_hub`, and the hub is upgraded first.
