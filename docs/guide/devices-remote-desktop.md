---
title: Devices and remote desktop
---

# Devices and remote desktop

A device is a machine the hub manages through an agent. This page enrolls one,
drives it from the drawer, opens a shell and a file browser on it, shares its
desktop, and forgets it.

Six things to settle first:

- The agent is Linux only. There is no Windows agent and no macOS agent, so a
  Windows machine is a client and never a device.
- There is no agent window. The panel's own hints still mention `nagent gui`;
  that command does not exist. Use the terminal.
- An enrollment link lasts five minutes, is consumed once, and generating a new
  one cancels the old.
- Editing a module of an offline device is refused, not queued.
- The seat password for a shared desktop is never shown. It can only be reset.
- The hub never dials a device. SSH installs an agent, and nothing more.

## Enroll by link

Open **Devices**.

Expect: two sections, "Managed devices" and "Unmanaged devices", with a badge
reading "{managed} of {total} managed". "Scan LAN" fills the unmanaged section
with what is connected.

![The Devices page with managed and unmanaged machines and the filter row](/guide/en/devices_overview.webp)

The legend says what each state means:

| State                         | What the panel says                                               |
| ----------------------------- | ----------------------------------------------------------------- |
| Managed                       | "Managed: reports its own vitals and takes modules from the hub." |
| Unmanaged with credentials    | "Unmanaged with credentials: one action installs the agent."      |
| Unmanaged with no credentials | "Unmanaged with no credentials: send it an enrollment link."      |
| Offline                       | "Not answering. Its credentials keep working once it returns."    |

Press "Add by link".

Expect: a notice carrying the `neutrino://enroll/…` link and a Copy button. It
works for five minutes.

![The enrollment notice with the neutrino://enroll link and a Copy button](/guide/en/devices_enroll_link.webp)

Run it on the machine:

```bash
sudo nagent connect 'neutrino://enroll/PLACEHOLDER_LINK'
```

Expect: the command returns, and the machine shows up under Managed devices
within seconds. Root is required, because the command writes the binding and
starts the service. Running `sudo nagent connect` with no link prompts for a
paste instead.

::: tip
The payload rides base64url, whose alphabet holds no character a shell splits
or a URL escapes, so the link pastes unquoted. The quotes above are habit, not
need.
:::

::: warning One invitation at a time
One invitation is open at a time. Generating a link clears whatever link was
out, so a machine you made one for a minute ago can no longer use it.

Make the link when the machine is in front of you, and make a fresh one for the
next machine.
:::

Minting is refused where the box has no reachable address on a served network,
and where the agent channel has no certificate yet.

## Install over SSH

In Unmanaged devices, open a machine and press "Install agent".

Expect: the dialog "Install the agent on {device}", with Host, Port, Username,
Credential and Sudo password.

![The SSH install dialog with the host, username and credential fields](/guide/en/devices_install_ssh.webp)

Pick a stored SSH key or login under Credential, fill in the sudo password
where the account needs one, and press "Install agent". The field says when to
leave it empty: "The login whose password sudo is given on the device. Leave
empty when the account has passwordless sudo."

Expect: an "Install output" panel streaming the installer, ending with an exit
code. The machine joins by itself, because the installer mints the enrollment
and uses it.

A machine that does not report Linux is refused: "This machine does not report
Linux; the SSH installer is for Linux. Send it an enrollment link instead." A
port outside the range is refused with "Port must be 1–65535."

The hub reaches in over SSH to install or reinstall an agent. It dials a device
for nothing else.

## Device drawer

Click a managed device.

Expect: the drawer, carrying Identity, Actions, Remote desktop, Terminal,
Files, Action output and Agent command results.

![The device drawer with the identity, the actions row and the remote desktop panel](/guide/en/devices_drawer.webp)

| Action          | What it does                                   |
| --------------- | ---------------------------------------------- |
| Reboot          | the machine reboots at once                    |
| Shut down       | the machine powers off                         |
| Wake-on-LAN     | a magic packet to UDP port 9                   |
| Install agent   | the SSH installer                              |
| Reinstall agent | the SSH installer, over an agent already there |
| Forget device   | see the last section                           |

::: warning
Reboot and Shut down are immediate: "The machine is told to do this at once;
anything unsaved on it is lost."

An offline machine takes no action at all. The panel answers "The machine is
not answering, so nothing was started on it." and queues nothing.
:::

An agent on a different version reads "This agent is a different version from
the hub.", with "Reinstall it with the Reinstall agent action below."

## Terminals and Files

Press "Terminal" in the drawer, or open the **Terminals** page.

Expect: a shell on that machine, in a tab of its own.

![The Terminals page with a shell open on studio](/guide/en/terminals.webp)

::: tip
Keystrokes go straight to the machine, Escape included. Close a terminal with
the × on its tab.
:::

Press "Files" in the drawer, or open the **Files** page.

Expect: a file browser rooted on that machine, for browsing and moving files.

![The Files page browsing a directory on studio](/guide/en/files.webp)

## Remote desktop

The remote desktop is RustDesk, carried by the agent. Only a machine's own
agent declares that it is sharing a desktop, so there is nothing to declare on
the hub.

On the machine whose desktop you want, run:

```bash
sudo nagent rdp start --user alex
```

Expect: the drawer's Remote desktop panel fills with an ID and a Copy ID
button, "Direct port 21118", and "Shared by alex."

Leaving `--user` out shares the desktop of the account that invoked sudo, or
the one account at the screen.

![The drawer's remote desktop panel with the ID, the direct port and the sharing account](/guide/en/devices_drawer_rdp.webp)

In the client window on `laptop`, press "Connect" in the "Remote desktops"
panel.

Expect: the button reads "connecting…", the RustDesk viewer opens on that
machine's desktop, and the row reads "viewer open".

![The client's Remote desktops panel connecting to studio](/guide/en/client_desktop_connect.webp)

From a terminal on the client, the same thing:

```bash
nclient service desktop connect 1
```

Stop sharing on the machine itself:

```bash
sudo nagent rdp stop
```

Expect: the entry leaves the client's Remote desktops panel.

::: warning
The seat password is held by the hub and never shown, so a viewer that cannot
get in is fixed by replacing the password rather than reading it.

Press "Reset seat password" in the drawer: "The machine is given a new password
at once. Every viewer connected now must connect again." On an offline machine
it changes nothing, and says so.
:::

The client's own refusals name the cause: "that machine published no address to
connect to", "that desktop is not shared any more", and "this session has no
screen to open a viewer on".

## Forget a device

Press "Forget device" in the drawer and confirm.

Expect: "The device and its saved credentials are deleted from this box." The
machine still has the agent installed, and it comes back with the next
enrollment link.

That is the whole path: a machine enrolled, driven, shared and removed.
