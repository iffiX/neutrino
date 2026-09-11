---
title: Quick start
---

# Quick start

This is the ground-up guide: every command is written out, one at a time. At
the end you have a hub with a panel, a second machine under an agent, a client
on a laptop, and a Samba share mounted on it.

This walk installs **server** mode. Nothing on the network changes: every
address the box has stays as it is, and no device is told to route through it.
If you want the hub to hand out addresses and route your LAN, read
[Network modes](./network-modes.md) first.

Four things this page does not do:

- The panel is HTTP. Reach it over the LAN, or over an overlay.
- The agent is Linux only, and it has no window. You join it from a terminal.
- On Windows you run the client, and nothing else.
- macOS runs none of the three packages.

## What you need

- A box running Linux with systemd, x86-64 or ARM64. A Pi, a TV box or an old
  laptop is enough.
- A second Linux machine to manage. It is called `studio` here.
- A laptop to run the client on. It is called `laptop` here.
- All three on one network.

## Install the hub and run setup

**1.** On the hub box, install the package:

```bash
sudo apt install ./neutrino-hub_0.2.0_amd64.deb
```

Expect: apt reports the package installed, and `nhub` is on the path.

**2.** Start setup:

```bash
sudo nhub setup
```

Expect: the terminal prints a URL carrying a one-time token and waits. On a
machine with a browser, that browser opens on the URL. Pressing Enter instead
runs the same six questions in the terminal.

![The setup welcome screen, with the line about pouring a coffee and a "Set this box up" button](/guide/en/setup_welcome.webp)

**3.** Screen 1, **Language**. Pick English or 简体中文. This is the language
the panel is drawn in; the terminal stays English.

Expect: the counter above the question reads `Config 1/6`.

**4.** Screen 2, **A password for the panel, a passphrase for the vault**. Type
a panel password, then a vault master passphrase.

Expect: both fields are accepted and Next lights up.

![The secrets screen, with the panel password field above the vault master passphrase field](/guide/en/setup_secrets.webp)

::: warning The passphrase cannot be recovered
The vault passphrase seals every credential this box will hold, and restoring a
backup asks for it again. Nothing on the box can recover it for you.

Write it down somewhere off the box before you press Next. If it is lost, the
way back is `sudo nhub reset all` and setting the box up from the beginning.
:::

**5.** Screen 3, **What is this machine for?**. Choose **Server**.

Expect: the summary under the choice reads "Routes nothing; answers where it is
reached."

![The shape screen, with Server, Side gateway, Router and One-arm router offered as cards](/guide/en/setup_shape.webp)

**6.** Screen 4, **Which ports?**. Leave "Panel answers on port" at `8080`.

Expect: the lead reads "No port is given a job. Every one of them keeps the
address it has and answers to begin with; the panel's Network page narrows that
afterwards."

![The ports screen in server mode, listing this machine's ports and the panel port field](/guide/en/setup_ports.webp)

**7.** Screen 5, **Going out through a proxy**. Skip it.

Expect: Next stays live. Skipping is a real answer, and the Proxy page turns a
proxy on later without redoing any of this.

![The proxy screen, with the exit node links field and the SOCKS port field](/guide/en/setup_proxy.webp)

**8.** Screen 6, **Ready**. Read the review and confirm.

Expect: the steps run one by one, ending on "This box is a gateway". Setup
installs this box's own agent at the end, and asks you to choose no modules.

![The review screen, listing shape, language, the ports answered on and the panel port](/guide/en/setup_review.webp)

![The done screen, headed "This box is a gateway", with an "Open the panel" button](/guide/en/setup_done.webp)

## Sign in

**9.** Open `http://<hub>:8080` in a browser.

Expect: the sign-in page, headed by the Neutrino mark and "control panel", with
one "Panel password" field and a "Sign in" button.

![The sign-in page with the Neutrino mark, the panel password field and the Sign in button](/guide/en/login.webp)

**10.** Sign in with the panel password from screen 2.

Expect: the Dashboard. The rail on the left carries two groups, Hub with ten
pages and Agent with six.

![The Dashboard with live throughput, the exits in use and DNS queries](/guide/en/dashboard.webp)

![The sidebar, with the Hub group above the Agent group](/guide/en/sidebar_groups.webp)

The panel speaks HTTP. Reach it over the LAN, or over an overlay.

## Add a second machine

**11.** Open **Devices**.

Expect: two sections, "Managed devices" and "Unmanaged devices". The hub's own
machine is already managed, because setup enrolled it.

![The Devices page, with home-hub under Managed devices and the LAN hosts below](/guide/en/devices_managed.webp)

**12.** Press "Add by link".

Expect: a notice carrying a `neutrino://enroll/…` link and a "Copy" button. The
link lasts five minutes, and one is open at a time: making a new one cancels
the old.

![The enrollment notice with the neutrino://enroll link and a Copy button](/guide/en/devices_enroll_link.webp)

**13.** On `studio`, install the agent:

```bash
sudo apt install ./neutrino-agent_0.2.0_amd64.deb
```

Expect: the package installs and its service starts.

**14.** On `studio`, join the hub with the link you copied:

```bash
sudo nagent connect 'neutrino://enroll/PLACEHOLDER_LINK'
```

Expect: the command returns, and within seconds `studio` appears under Managed
devices with a live dot beside it.

::: tip
The Devices drawer installs the agent for you over SSH, so a machine you can
already reach never needs these two commands. See
[Devices and remote desktop](./devices-remote-desktop.md).
:::

## Install the client

**15.** In the panel, open **Clients** and press "New client link".

Expect: a name field, with the placeholder "whose program this is, e.g.
alice-laptop", and a "Create link" button.

![The Clients page with the new client name field and the Create link button](/guide/en/clients_create_link.webp)

**16.** Type `laptop` and press "Create link".

Expect: a notice reading "Paste this link into the client program for laptop."
with the link and a Copy button. Five minutes again.

![The client enrollment notice with the link for laptop and a Copy button](/guide/en/clients_link_notice.webp)

**17.** On `laptop`, install the client package, then open its window:

```bash
nclient gui
```

Expect: a window headed "Neutrino client", with Status reading "Not connected"
and the line "Paste the link from the hub's Clients page".

![The client window before connecting, with the empty link field](/guide/en/client_disconnected.webp)

No `sudo` here. The client runs as you, and `nclient` refuses to run as root.

**18.** Paste the link into the field and press "Connect".

Expect: Status reads "Connected" with the hub's version, a "Disconnect" button
appears, and the Services section draws five panels: Web, Ports, AI, Files and
Remote desktops.

![The connected client window with the five service panels](/guide/en/client_connected.webp)

![The Clients page in the panel, with laptop listed as a Linux client and online](/guide/en/clients_table.webp)

## Publish a share and mount it

The Samba module runs under the agent on the machine that owns the disk. Here
that machine is the hub box itself, which has an agent like any other.

**19.** In the panel, open **Samba** under the Agent group.

Expect: an "Enabled devices" picker, and the line "samba is on no machine yet".

**20.** Tick `home-hub` and press "Apply devices".

Expect: a consent dialog naming the machine, then the module installs and the
page redraws with that machine's Samba panels.

**21.** Under "Users", press "Add user", name it `alex`, give it a password,
then press "Apply users".

Expect: the row reads "created on apply" until the apply finishes, and the
account exists afterwards.

**22.** Under "Shares", press "Add share", name it `media`, give it a directory,
then press "Apply shares".

Expect: "Saves shares and reloads the server.", and `media` joins the list.

![The Samba page with the media share and the alex user](/guide/en/samba_share.webp)

**23.** Open **Services**.

Expect: four groups, Web, Ports, AI and Files, with `media` under Files,
described "published by the samba module on home-hub".

![The Services page with the four groups and the media share under Files](/guide/en/services_list.webp)

**24.** On `laptop`, in the client window, press "Config" in the Files panel.

Expect: a form with "Share username", "Share password" and "Mount path", the
path already filled in as `<home>/nas/media`.

![The client's Files panel with the share username, password and mount path fields](/guide/en/client_files_config.webp)

**25.** Type `alex` and its password, then press "Mount".

Expect: the button becomes "Unmount", and the share is readable at
`~/nas/media`.

![The client's Files panel with media mounted and an Unmount button](/guide/en/client_files_mounted.webp)

## Next

- [Network modes](./network-modes.md)
- [Overlay with NetBird](./overlay-netbird.md) and
  [Overlay with EasyTier](./overlay-easytier.md)
- [AI gateway](./ai-gateway.md)
- [Devices and remote desktop](./devices-remote-desktop.md)
- [Backup and restore](./backup-restore.md)

That is the whole path.
