---
title: Desktop client
---

# Desktop client

With the desktop client installed on a Linux, Windows or macOS computer, the services of every hub you joined open from one window. A link from each hub joins the computer to it. The window then shows that hub's web pages, ports, AI gateway, shares, terminals and remote desktops. The same work runs from a terminal through the commands in [nclient commands](../commands/nclient.md).

## Install the client

Before you start, check the computer:

- It runs one of these systems, as [Supported platforms](../reference/platforms.md) lists in full:
  - Debian 12 or Ubuntu 22.04 or newer, with a desktop session
  - RHEL 9, AlmaLinux 9, or Fedora 41 or newer, with a desktop session
  - Windows 10 version 1809 or newer, or Windows 11, on x86-64
  - macOS 12.3 or newer on Apple silicon
- You run the client from your own account. The client rejects root with `root_refused`.
- It reaches port 8443 on every hub it joins.

Download the package for your system from the release and install it. On a 64-bit ARM Linux machine, the file name says `arm64` for the `.deb` and `aarch64` for the `.rpm`.

::: code-group

```bash [Debian, Ubuntu]
sudo apt install ./neutrino-client_0.5.0_amd64.deb
```

```bash [RHEL, AlmaLinux, Fedora]
sudo dnf install ./neutrino-client-0.5.0-1.x86_64.rpm
```

```powershell [Windows]
msiexec /i neutrino-client-0.5.0-windows-amd64.msi
```

```bash [macOS]
sudo installer -pkg neutrino-client-0.5.0-macos-arm64.pkg -target /
```

:::

`apt` and `dnf` install the dependencies with the package: WebKitGTK, the tray library, `cifs-utils`, polkit and the libraries the bundled RustDesk viewer loads.

::: warning
`dpkg -i` and `rpm -i` install none of the dependencies. After either one, run `sudo apt -f install` on Debian, or `sudo dnf install` with the missing packages on RHEL.
:::

On Windows, double-clicking the `.msi` runs the same installer. Its **Add the Neutrino Client to PATH** box puts the `nclient` command in every terminal. When the WebView2 runtime is missing, the installer runs Microsoft's bootstrapper for it. The removal dialog has a **Keep my configuration** box, and a kept configuration rejoins the same hub on the next install.

![The Windows installer](/guide/os/win_msi_installer.webp)

On macOS, the installer puts **Neutrino Client** in `/Applications` and links `nclient` into `/usr/local/bin`. The app has an ad hoc signature, so Gatekeeper shows a confirmation the first time it opens.

Every package also registers two system services for virtual networks: the NetBird daemon and the client's own EasyTier daemon. On Linux the package conflicts with the `netbird` package. On macOS, a NetBird already installed stays in use as it is.

## Join a hub

Before you start, create a client link in the hub's panel. Open **Clients**, select **New client link**, type a name for this computer, and select **Create link**. The link works for five minutes and joins one computer. [Clients](../hub/clients.md) sets what the computer can use.

To join:

1. Open the client: **Neutrino Client** in the application menu on Linux, the Start menu on Windows, or the app on macOS. The **Hubs** page reads **No hub joined yet**, with a **Join a hub** row under it.
1. Paste the link into the field of that row and select **Join**.

The hub gets a row reading **Connected**, with its address and the package it runs.

![The client window joined to a hub](/guide/en/client_connected.webp)

The client rejects a link from the hub's **Devices** page with `link_not_for_client`, and an expired or spent link with `enroll_refused`.

To join a second hub, create a link in that hub's panel and paste it into the same **Join a hub** row. Each hub keeps its own name for this computer and publishes its own services. Every service page lists the hubs in the order you joined them.

## Hubs

The window, titled **Neutrino client**, has a sidebar with **Hubs**, **Web**, **Ports**, **AI**, **Files**, **Terminals** and **Remote desktops**, then **Settings** under a rule. The **↻** button at the top right reports to every connected hub and reconnects every hub whose channel is down.

### Row states

On the **Hubs** page, each row holds one hub: its name, its state, its address and the package it runs. The dot before the name shows the state:

| Dot            | Meaning                                                                                           |
| -------------- | ------------------------------------------------------------------------------------------------- |
| green          | the channel is open                                                                               |
| amber, turning | the client is reconnecting to a hub it reached before                                             |
| amber          | the hub is out of reach and nothing is broken, for example `hub_unreachable` or `client_disabled` |
| red            | a person has to change something, for example `hub_untrusted` or `binding_unknown`                |
| grey           | the client has not reached the hub yet                                                            |

Each row has **Leave**, which removes the row at once. Leaving undoes what the hub published on this computer: its mounts, port forwards, viewers, and a virtual network no other hub names. A row reading **Replaced by another client** also has **Reconnect**.

After a refusal, the row stays and shows the code, and the client connects again with up to a minute between tries. One code removes the row:

| Code               | Meaning                                                              | What to do                               |
| ------------------ | -------------------------------------------------------------------- | ---------------------------------------- |
| `protocol_too_old` | this client speaks an older protocol number than the hub accepts     | install a newer client                   |
| `protocol_too_new` | this client speaks a newer protocol number than the hub              | update the hub                           |
| `hub_untrusted`    | the certificate at that address is not the one the link pinned       | join again with a new link after a reset |
| `binding_unknown`  | the hub's **Clients** page no longer holds this client; the row goes | join again with a new link               |

### Virtual network

A hub that publishes a virtual network, to a client its **Clients** page lets use one, shows a **Virtual network** chip on its row. The chip reads the state and, when the network has given one, this computer's address on it.

Select the chip to join the network, and select it again to leave. The client keeps your choice for each hub, so the computer rejoins after the client restarts. The daemons are system services: the computer stays on the network after the client quits.

| State                       | Meaning                                                                                              |
| --------------------------- | ---------------------------------------------------------------------------------------------------- |
| **off**                     | this computer is not on the network                                                                  |
| **joining…**, **leaving…**  | a step is running and the chip is grey                                                               |
| **Waiting for the console** | the hub's EasyTier console holds this computer but has not attached it to a network; attach it there |
| **on**                      | this computer is on the network                                                                      |
| **failed**                  | the last step failed, and the code shows under the hub's name                                        |

When the hub publishes more than one network, a picker beside the chip names the network in use, NetBird or EasyTier. Picking the other one leaves the current network and joins the picked one.

![The virtual network picker on a hub row](/guide/en/client_network_picker.webp)

When the hub's channel stays lost for 30 seconds, the client leaves the current network and joins the hub's next one. It moves on again after each further 30 seconds until the channel opens.

| Code                      | Meaning                                                                                       |
| ------------------------- | --------------------------------------------------------------------------------------------- |
| `overlay_other_network`   | this computer is on another NetBird network or another hub's EasyTier console; leave it first |
| `overlay_daemon_down`     | the NetBird or EasyTier daemon is not running; reinstall the client                           |
| `bundle_missing`          | this install has no NetBird or EasyTier; reinstall the client                                 |
| `overlay_join_failed`     | NetBird or EasyTier rejected the join, with its own words after the code                      |
| `overlay_console_invalid` | EasyTier cannot use the console address the hub named                                         |

## Web

The **Web** page lists every web address the joined hubs publish: Gitea, VS Code, and addresses declared by hand on a hub's **Services** page. The line under each address names the hub, the machine and the module, such as **from Neutrino:Argon:Gitea**. **Open** opens the address in your default browser.

A VS Code entry opens only through localhost, and its button reads **Open locally**. Selecting it forwards the entry's address to `127.0.0.1` on this computer and takes a token from the hub. Your browser then opens the forward with that token.

The forward closes when the client quits. When the hub sends no token, the row shows `web_token_missing`.

An entry the hub cannot reach is greyed and reads **not reachable now**. A page with no entry reads **no web service is offered**.

## Ports

The **Ports** page relays a port a hub publishes to this computer's loopback address. An entry is a container's host port on a managed machine, or a TCP port declared by hand on the hub's **Services** page.

- Select **Connect** on the entry.

The row shows `127.0.0.1` and the local port, and the button reads **Disconnect**. The local port is the entry's own number when that number is free, and any free port otherwise. Every program and every account on this computer can reach the relay until you select **Disconnect**, leave the hub, or quit the client.

## AI

The **AI** page points Claude Code, Codex and Gemini CLI on this computer at one hub's AI gateway. Each hub with a gateway has one entry, with **Config** and a **The AI tools use this gateway** switch. One switch at most is on.

Select the switch on the gateway you want. The entry reads **switching the tools…**, then **the tools point at the hub**, and the switch that was on goes off. The bundled cc-switch rewrites each tool's own configuration, and a failure in one tool leaves all three unchanged. Select the switch again to restore each tool's configuration from before the first switch.

The switch works only on a connected hub; otherwise the client returns `no_exit_hub`. A hub that has issued this client no key returns `no_endpoint`, and its **AI** page issues one.

To choose the models:

1. Select **Config** on the entry. The **AI tool configuration** dialog opens.
1. Under **Claude Code**, pick the **Default model**, **Opus slot**, **Sonnet slot** and **Haiku slot**.
1. Under **Codex**, pick the **Model** and the **Reasoning effort**: `minimal`, `low`, `medium` or `high`.
1. Under **Gemini**, pick the **Model**.
1. Select **Save**.

Each picker also offers **gateway default**, and the models listed are that hub's own. On the gateway in use, **Save** rewrites the tools at once; on another, the choice applies when you switch to it.

## Files

The **Files** page mounts an SMB share a hub publishes: under your home on Linux and macOS, or on a drive letter on Windows. An entry is a share of the Samba module on a managed machine, or a share declared by hand on the hub's **Services** page.

To mount a share:

1. Select **Config** on the entry.
1. Type the **Share username** and **Share password** the share accepts.
1. On Linux and macOS, keep or change the **Mount path**, a folder under your home such as `~/nas/media`. **Browse…** picks or creates the folder. On Windows, pick the **Drive**.
1. Select **Mount**. The button reads **waiting to mount…**, then **mounting…**, then **Unmount**.

![The Files page with a share mounted](/guide/en/client_files_mounted.webp)

![The mapped drive in File Explorer](/guide/os/win_explorer_mapped.webp)

The client keeps the login in a credentials file only your account reads, so the next **Mount** uses the saved password. **Unmount** detaches the share and keeps the login.

| Code                          | Meaning                                                                                   |
| ----------------------------- | ----------------------------------------------------------------------------------------- |
| `mountpoint_invalid`          | the path is outside your home                                                             |
| `mountpoint_not_empty`        | the folder holds files                                                                    |
| `mountpoint_not_drive_letter` | on Windows, the drive is not an unused letter                                             |
| `mountpoint_in_use`           | another entry, from any hub, mounts at that path                                          |
| `credentials_missing`         | the saved login is gone; type it again in **Config**                                      |
| `share_login_rejected`        | the username or password is wrong; **Mount** opens **Config** with the username filled in |
| `share_access_denied`         | the share accepts the login but does not admit that account                               |
| `share_not_found`             | the host has no share by that name                                                        |
| `share_unreachable`           | the host does not answer; the client mounts again when it does                            |
| `share_session_conflict`      | Windows holds a connection to that server under another login; disconnect it first        |

On Linux a CIFS mount needs root, so the client runs its own mount helper under `pkexec`, and polkit shows its password prompt once. Dismissing that prompt gives `mount_not_authorized`, and a machine without `mount.cifs` gives `mount_tooling_missing`. On macOS the client mounts with `mount_smbfs` as you, and on Windows as a mapped drive.

## Terminals

The **Terminals** page opens a shell on a machine a hub manages, in a tab of the window. The hub's **Clients** page must let this client open terminals.

1. On the **Terminals** page, pick the machine in the strip on top. A green dot marks a machine that is online.
1. Select **New terminal**.

The shell opens in a new tab, and every key you type goes to the machine. The window draws the shell in MesloLGS NF, which the client includes, so a powerlevel10k prompt shows its icons.

![A persistent terminal tab in the client](/guide/en/client_terminal.webp)

To paste, press the right mouse button on the shell, or press Ctrl+Shift+V, or Cmd+V on macOS. When the client cannot read the clipboard, the line under the shell shows `clipboard_unreadable`.

The **Persistent** switch is at the end of the line under the shell. When it is on, the machine keeps the session while no window is attached, for example after the client quits.

A kept session shows as a tab with a grey dot. Select that tab to attach, and the shell's recent output appears first. When a hub's channel drops and comes back, each tab whose session the machine still keeps attaches again by itself. A tab whose session is gone reads **Ended**. The **×** on a persistent tab reads **End session?** after one press, and a second press ends the shell on the machine. [Terminals](../agent/terminals.md) covers the same sessions in the panel.

| Code                | Meaning                                                                  |
| ------------------- | ------------------------------------------------------------------------ |
| `permission_denied` | the hub's **Clients** page does not let this client open terminals       |
| `agent_offline`     | the machine is not connected to its hub                                  |
| `unknown_terminal`  | the hub offers no terminal on that machine                               |
| `session_not_owned` | another viewer opened the session, so its switches are not this client's |
| `session_unknown`   | the machine no longer keeps the session                                  |

## Remote desktops

The **Remote desktops** page opens another machine's screen in the RustDesk viewer the client includes. An entry appears while a managed machine shares its desktop with `sudo nagent rdp start`, and goes when it stops or goes offline.

- Select **Connect** on the entry.

The button reads **connecting…**, the viewer opens on that desktop, and the row reads **viewer open**. The hub sets the seat password and hands it to the viewer with that one press. The viewer connects straight to port 21118 of that machine.

Text copied on either machine pastes on the other. To copy a file to the remote machine, choose **Transfer file** in the viewer's toolbar and drop the file on the remote side of that window.

| What you see                                             | Cause                                                    |
| -------------------------------------------------------- | -------------------------------------------------------- |
| the page reads **no remote desktop is shared right now** | no machine is sharing, or the sharing machine is offline |
| `rdp_not_shared`                                         | the machine stopped sharing                              |
| `rdp_no_address`                                         | the machine published no address this computer reaches   |
| `rdp_no_desktop`                                         | this session has no screen to open a viewer on           |
| `rdp_launch_failed`                                      | the viewer did not start, with the reason after the code |

## Settings

1. Select **Settings** under the rule in the sidebar.
1. On the **Client settings** panel, pick the **Language** and the **Theme**: **System**, **Dark** or **Light**.
1. Select **Save**.

The language and theme belong to this window; the panel keeps its own.

The **About** card under the settings lists this computer's name, its platform, the client's version, the licence and the source links.

## The tray

Closing the window hides it, and the client keeps every hub connected. The tray icon is in the taskbar corner on Windows, the indicator area of the top bar on Linux, and the menu bar on macOS. Its menu has **Open**, which shows the window, and **Quit**, which stops the client.

![The tray menu on Windows](/guide/os/win_tray_flyout.webp)
