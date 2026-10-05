---
title: Desktop client
---

# Desktop client

With the desktop client installed on a Linux, Windows or macOS computer, the services of every hub you joined open from one window. A link from each hub joins the computer to it. The window then shows that hub's web pages, ports, AI gateway, shares, terminals and remote desktops. The same work runs from a terminal through the commands in [nclient commands](../commands/nclient.md).

Every page reaches its service through the hub. The client listens on a port of this computer's loopback address, `127.0.0.1`, and passes each connection to that port on to the hub's port 8443. The hub connects it to the service, on its own box or through the agent of the machine that provides it.

## Install the client

Before you start, check the computer:

- It runs one of these systems, as [Supported platforms](../reference/platforms.md) lists in full:
  - Debian 12 or Ubuntu 22.04 or newer, with a desktop session
  - RHEL 9, AlmaLinux 9, or Fedora 41 or newer, with a desktop session
  - Windows 10 version 1809 or newer, or Windows 11, on x86-64
  - macOS 12.3 or newer on Apple silicon
- You run the client from your own account. The client rejects root with `root_refused`.
- It reaches port 8443 on every hub it joins: on the LAN, or from outside through one of the ways in that [Access](../hub/overlay.md) lists.

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

Every package also registers system services for virtual networks: the NetBird daemon and the client's own EasyTier daemon. The mainland edition's package has the EasyTier daemon alone. On Linux the package conflicts with the `netbird` package. On macOS, a NetBird already installed stays in use as it is.

On Windows the package registers one more service, `NeutrinoClientFiles`. It runs the files adapter that puts a share on a drive letter, as [Files](#files) describes.

## Join a hub

Before you start, create a client link in the hub's panel. Open **Clients**, select **New client link**, type a name for this computer, and select **Create link**. The link works for thirty minutes, also across a restart of the hub, and joins one computer. [Clients](../hub/clients.md) sets what the computer can use.

To join:

1. Open the client: **Neutrino Client** in the application menu on Linux, the Start menu on Windows, or the app on macOS. The **Hubs** page reads **No hub joined yet**, with a **Join a hub** row under it.
1. Paste the link into the field of that row and select **Join**.

The hub gets a row at once. It reads **Joined; the hub has not been reached yet** until one address in the link answers, then **Connected · LAN** or the name of another way in, with the hub's address and the package it runs.

![The client window joined to a hub](/guide/en/client_connected.webp)

The field rejects a link from the hub's **Devices** page with `link_not_for_client`, and a cut-off paste with `link_unreadable`. A link that is spent or expired puts the row in **Not connected** with `ticket_spent`; select **Leave** on the row and join with a fresh link. After too many failed joins on the hub, the row shows `admission_paused` and joins again after the seconds that code names.

To join a second hub, create a link in that hub's panel and paste it into the same **Join a hub** row. Each hub keeps its own name for this computer and publishes its own services. Every service page lists the hubs in the order you joined them.

## Hubs

The window, titled **Neutrino client**, has a sidebar with **Hubs**, **Web**, **Ports**, **AI**, **Files**, **Terminals** and **Remote desktops**, then **Settings** under a rule. The **↻** button at the top right reports to every connected hub and reconnects every hub whose channel is down.

### Row states

On the **Hubs** page, each row holds one hub: its name, its state, its address and the package it runs. While the channel is open, the state names the way it reached the hub:

| State                     | The channel reached the hub through                                 |
| ------------------------- | ------------------------------------------------------------------- |
| **Connected · LAN**       | the hub's address on a network it serves                            |
| **Connected · Direct**    | one of the hub's own addresses, from outside the networks it serves |
| **Connected · NetBird**   | the hub's NetBird address                                           |
| **Connected · EasyTier**  | the hub's EasyTier address                                          |
| **Connected · SSH Relay** | the public port of the hub's SSH Relay server                       |

The dot before the name shows the state:

| Dot            | Meaning                                                                                           |
| -------------- | ------------------------------------------------------------------------------------------------- |
| green          | the channel is open                                                                               |
| amber, pulsing | the client is connecting, or a job runs on the row                                                |
| amber          | the hub is out of reach and nothing is broken, for example `hub_unreachable` or `client_disabled` |
| red            | a person has to change something, for example `hub_untrusted` or `binding_unknown`                |
| grey           | the client has not reached the hub yet                                                            |

### Row buttons

| Button        | Shown                                                                     | What it does                                                                                                         |
| ------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **Panel**     | when the hub's **Clients** page allows **Hub panel without the password** | reads **Opening…**, then opens the hub's panel in your browser through a forward on this computer, already signed in |
| **Reconnect** | on a row reading **Replaced by another client**                           | takes the hub back from the other client and connects                                                                |
| **Leave**     | always                                                                    | reads **Press again to leave**; a second press within five seconds leaves the hub                                    |

**Panel** opens the panel from anywhere the client reaches the hub, so the panel's own ports can stay on the LAN. **Hub panel without the password** is off until somebody turns it on for this computer on the hub's **Clients** page. The browser opens `http://panel-<hub-id>.localhost:<local-port>/?tkn=<token>`, or `http://127.0.0.1:<local-port>/?tkn=<token>` on macOS, where `<hub-id>` is the hub's id, `<local-port>` the forward's port and `<token>` a sign-in that works once, within a minute. The panel then drops `tkn` from the address. A refusal, such as `permission_denied`, shows on the row's error line. The forward stays until you leave the hub or quit the client.

From a terminal, `nclient leave --yes` leaves without the question, and `nclient status --json` prints the state of every hub as JSON. Leaving removes the row at once, whether the hub is reachable or not. It undoes what the hub published on this computer: its forwards, the panel's forward among them, its mounts, its viewers, and a virtual network no other hub names.

After a refusal, the row stays and shows the code, and the client connects again with up to a minute between tries. One code removes the row:

| Code               | Meaning                                                              | What to do                               |
| ------------------ | -------------------------------------------------------------------- | ---------------------------------------- |
| `protocol_too_old` | this client speaks an older protocol number than the hub accepts     | install a newer client                   |
| `protocol_too_new` | this client speaks a newer protocol number than the hub              | update the hub                           |
| `hub_untrusted`    | the certificate at that address is not the one the link pinned       | join again with a new link after a reset |
| `binding_unknown`  | the hub's **Clients** page no longer holds this client; the row goes | join again with a new link               |

### Virtual network

The pages of the client need only the hub's port 8443, so a virtual network is one way in among the others. When a hub publishes NetBird or EasyTier, and its **Clients** page lets this client use a virtual network, the row has a **Virtual network** line. The line reads the state and, while on, this computer's address on that network.

To join the network, select **Connect** on the row:

| The line reads                                           | Meaning                                                                                              | The button     |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------- |
| **Not connected**                                        | this computer is not on the network                                                                  | **Connect**    |
| **Connecting…**, with **Logging in to NetBird** under it | the engine starts and logs in, for 90 seconds at most                                                | **Cancel**     |
| **Connecting…**, with **Waiting for the hub** under it   | the computer has an address, and the client counts the seconds until the hub is reachable through it | **Cancel**     |
| **Connected ·** and this computer's address              | the hub is reachable through the network                                                             | **Disconnect** |

In EasyTier's console mode, the reason line reads **This machine is registered with the console. Attach it to a network there.** until the console's owner attaches it. A failure returns the line to **Not connected** with the code under it, and the client tries nothing again by itself. A computer that was connected rejoins once when the client starts.

When the hub publishes both engines, a picker beside the button names the engine to use. The picker changes only while the line reads **Not connected**.

![The virtual network picker on a hub row](/guide/en/client_network_picker.webp)

The daemons are system services: the computer stays on the network after the client quits.

| Code                      | Meaning                                                                                       |
| ------------------------- | --------------------------------------------------------------------------------------------- |
| `overlay_other_network`   | this computer is on another NetBird network or another hub's EasyTier console; leave it first |
| `overlay_daemon_down`     | the NetBird or EasyTier daemon is not running; reinstall the client                           |
| `bundle_missing`          | this install has no NetBird or EasyTier; reinstall the client                                 |
| `overlay_join_failed`     | NetBird or EasyTier rejected the join, with its own words after the code                      |
| `overlay_no_address`      | the engine gave this computer no address within 90 seconds                                    |
| `overlay_console_invalid` | EasyTier cannot use the console address the hub named                                         |

## Forwards

A forward is the port on `127.0.0.1` that the client opens for one entry. Each connection to it becomes a stream to the hub, and the hub connects that stream to the service. A forwarded row shows `→ 127.0.0.1:` and the port.

| Page                | The forward listens                                             |
| ------------------- | --------------------------------------------------------------- |
| **Web**             | from **Open** until **Disconnect**                              |
| **Ports**           | from **Connect** until **Disconnect**                           |
| **AI**              | while the client runs and the tools point at that hub           |
| **Files**           | on Linux and macOS, from **Mount** until the share is unmounted |
| **Remote desktops** | from **Connect** until the viewer closes                        |

Every program and every account on this computer can reach a forward while it listens. Quitting the client ends every forward.

### Local port

On the **Web** and **Ports** pages, **Configure** on a row opens the **Local port** choice:

- **Auto** takes the entry's own port when nothing on this computer listens on it, on any address, on the entry's protocol. Otherwise it takes the first free port from 20000 up. The client keeps that port for the entry, also after a restart.
- **Fixed** takes the number you type, from 1024 to 65535. A number another entry of the same protocol holds is rejected with **Another entry holds port** and the number. One number can be held once for TCP and once for UDP.

**Configure** is greyed while the entry is forwarded, with the reason **Disconnect first to change the local port.**

### Codes on a forwarded row

A page whose forward cannot reach its service shows one of these codes on the row:

| Code                 | Meaning                                                                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `connect_failed`     | the hub or the machine could not connect to the service: `refused` (nothing listens on the port), `timeout` or `unreachable` |
| `agent_offline`      | the machine that provides the entry is not connected to the hub                                                              |
| `port_not_published` | the machine does not publish that port now, for example because the container or the instance stopped                        |
| `connect_limit`      | this client has 256 connections open through the hub; close some and try again                                               |
| `permission_denied`  | the hub's **Clients** page does not let this client use that kind of entry, or that machine                                  |
| `service_unknown`    | the hub no longer publishes the entry                                                                                        |

## Web

The **Web** page lists every web address the joined hubs publish: Gitea, VS Code, code-server, CloudCLI, and addresses declared by hand on a hub's **Services** page. The line under each address names the hub, the machine and the module, such as **from Neutrino:Argon:Gitea**.

Each row has three buttons:

| Button         | What it does                                                                                       |
| -------------- | -------------------------------------------------------------------------------------------------- |
| **Open**       | reads **Opening…**, makes the entry's forward when it has none, and opens the page in your browser |
| **Configure**  | sets the forward's local port                                                                      |
| **Disconnect** | shown while the entry is forwarded; ends the forward                                               |

The browser opens `http://` followed by a name under `.localhost` and the local port, so two instances keep their logins apart. On macOS the name is `127.0.0.1`, since Safari resolves no `.localhost` name.

A VS Code, code-server or CloudCLI entry opens only with a token. **Open** takes a fresh token from the hub on every press and adds it to the address. A code-server or CloudCLI token works once, within 60 seconds. When the hub sends no token, the row shows `web_token_missing`.

An entry the hub cannot reach is greyed and reads **Not reachable now**. A page with no entry reads **No web services yet**.

## Ports

The **Ports** page relays a port a hub publishes to this computer's loopback address. An entry is a container's host port on a managed machine, or a TCP or UDP port declared by hand on the hub's **Services** page.

- Select **Connect** on the entry.

The button reads **Forwarding…**, then **Disconnect**, and the row adds `→ 127.0.0.1:` with the local port. Point any program on this computer at that address. Select **Disconnect** to end the forward.

A UDP entry reads `host:port/udp`, and once connected `→ 127.0.0.1:` with the local port and `/udp`. A program on this computer sends its datagrams to that local address, and the replies come back to it. A declared UDP port shows no health word, and **Connect** stays available.

Everything this client sends goes through one TCP connection to the hub. A lost packet therefore holds up every stream on it until it is sent again, the UDP ones too. A UDP port through the hub suits question-and-answer traffic of small volume: DNS, time, discovery, a small game server. Voice, video and fast games need a direct path to the machine, which you set up as a subnet route in the overlay's own console, NetBird's or EasyTier's.

## AI

The **AI** page points Claude Code, Codex and Gemini CLI on this computer at one hub's AI gateway. Each hub with a gateway has one entry, with **Configure** and a **The AI tools use this gateway** switch. One switch at most is on.

Select the switch on the gateway you want. The entry reads **Switching tools…**, then **The tools point at the hub**, and the switch that was on goes off. The client makes the gateway's forward and points each tool at `http://127.0.0.1:` and the local port, with this client's key. The bundled cc-switch rewrites each tool's own configuration, and a failure in one tool leaves all three unchanged. Select the switch again to restore each tool's configuration from before the first switch.

The line under the entry reads **The tools reach the gateway only while this client runs.** Keep the client running, in the tray, while you use the tools.

The switch works only on a connected hub; otherwise the client returns `no_exit_hub`. A hub that has issued this client no key returns `no_endpoint`, and its **AI** page issues one.

To choose the models:

1. Select **Configure** on the entry. The **AI tool configuration** dialog opens.
1. Under **Claude Code**, pick the **Default model**, **Opus slot**, **Sonnet slot** and **Haiku slot**.
1. Under **Codex**, pick the **Model** and the **Reasoning effort**: `minimal`, `low`, `medium` or `high`.
1. Under **Gemini**, pick the **Model**.
1. Select **Save**.

Each picker also offers **gateway default**, and the models listed are that hub's own. On the gateway in use, **Save** rewrites the tools at once; on another, the choice applies when you switch to it.

## Files

The **Files** page mounts an SMB share a hub publishes: in a folder under your home on Linux, as a volume in the Finder on macOS, or on a drive letter on Windows. An entry is a share of the file share module on a managed machine, or a share declared by hand on the hub's **Services** page.

To mount a share:

1. Select **Configure** on the entry. A form opens under the row.
1. Type the **Share username** and **Share password** the share accepts.
1. On Linux, keep or change the **Mount path**, a folder under your home such as `~/nas/media`. **Browse…** picks or creates the folder. On Windows, pick the **Drive**. On macOS, the form has no place to pick.
1. Select **Save**.
1. Select **Mount**. The button reads **Mounting…**, then **Unmount**.

![The Files page with a share mounted](/guide/en/client_files_mounted.webp)

The client keeps the login in a credentials file only your account reads, so the next **Mount** uses the saved password. **Unmount** detaches the share and keeps the login.

### How each system mounts

| System  | The mount                                                                                                                                                                                                                  |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Linux   | the client's mount helper runs under `pkexec` and mounts `//127.0.0.1/` and the share at the forward's port; polkit asks for your password once                                                                            |
| macOS   | the system mounts the volume from the forward, as the Finder's **Connect to Server** does; the first mount asks you to confirm the server, and the row names the mount point under `/Volumes`                              |
| Windows | the files adapter gives the machine that provides the share an address of its own, from `198.19.255.2` up, and Windows maps the drive to that address; the drive letter keeps naming the same machine <!-- scan: allow --> |

On macOS the system shows its own dialogs: a wrong password opens the system's login dialog, and **Cancel** there gives `mount_not_authorized`. When the system has not finished after ten minutes, the row shows `mount_timed_out`.

On Windows the adapter is a network adapter named `neutrino_files`, run by the `NeutrinoClientFiles` service. It connects to no network, and it sends only the shares' connections to the hub. When the service is missing, stopped or failing, the mount fails with `files_adapter_unavailable` and the service's own words after it, and nothing else on the computer changes. Start **Neutrino Client Files** in the Windows **Services** console, or reinstall the client to register the service again.

![The mapped drive in File Explorer](/guide/os/win_explorer_mapped.webp)

| Code                          | Meaning                                                                            |
| ----------------------------- | ---------------------------------------------------------------------------------- |
| `mountpoint_invalid`          | the path is outside your home                                                      |
| `mountpoint_not_empty`        | the folder holds files                                                             |
| `mountpoint_not_drive_letter` | on Windows, the drive is not an unused letter                                      |
| `mountpoint_in_use`           | another entry, from any hub, mounts at that path                                   |
| `credentials_missing`         | the saved login is gone; type it again in **Configure**                            |
| `share_login_rejected`        | the username or password is wrong; **Configure** opens with the username filled in |
| `share_access_denied`         | the share accepts the login but does not admit that account                        |
| `share_not_found`             | the host has no share by that name                                                 |
| `share_unreachable`           | the host does not answer; the client mounts again when it does                     |
| `share_session_conflict`      | Windows holds a connection to that server under another login; disconnect it first |
| `files_adapter_unavailable`   | on Windows, the `NeutrinoClientFiles` service is missing, stopped or failing       |
| `mount_not_authorized`        | the polkit prompt or the macOS login dialog was dismissed                          |
| `mount_tooling_missing`       | on Linux, the computer has no `mount.cifs`                                         |

## Terminals

The **Terminals** page opens a shell on a machine a hub manages, in a tab of the window. The hub's **Clients** page must let this client open terminals.

1. On the **Terminals** page, pick the machine in the strip on top. A green dot marks a machine that is online.
1. Select **New terminal**.

The shell opens in a new tab, and every key you type goes to the machine. The window draws the shell in MesloLGS NF, which the client includes, so a powerlevel10k prompt shows its icons.

![A persistent terminal tab in the client](/guide/en/client_terminal.webp)

To paste, press the right mouse button on the shell, or press Ctrl+Shift+V, or Cmd+V on macOS. When the client cannot read the clipboard, the line under the shell shows `clipboard_unreadable`.

**Clear** in the right-click menu sends Ctrl+C to the shell and empties the screen. Until the shell's output has been quiet for half a second, twenty seconds at most, the terminal drops what arrives and reads **Clearing…**.

The **Persistent** switch is at the end of the line under the shell. When it is on, the machine keeps the session while no window is attached, for example after the client quits.

A kept session shows as a tab with a grey dot. Select that tab to attach, and the shell's recent output appears first. When a hub's channel drops and comes back, each tab whose session the machine still keeps attaches again by itself. A tab whose session is gone reads **Ended**. The **×** on a persistent tab reads **Press again to end** after one press, and a second press ends the shell on the machine. [Terminals](../agent/terminals.md) covers the same sessions in the panel.

| Code                | Meaning                                                                  |
| ------------------- | ------------------------------------------------------------------------ |
| `permission_denied` | the hub's **Clients** page does not let this client open terminals       |
| `agent_offline`     | the machine is not connected to its hub                                  |
| `unknown_terminal`  | the hub offers no terminal on that machine                               |
| `session_not_owned` | another viewer opened the session, so its switches are not this client's |
| `session_unknown`   | the machine no longer keeps the session                                  |

## Remote desktops

The **Remote desktops** page opens another machine's screen in the RustDesk viewer the client includes. An entry appears while a managed machine shares its desktop, which its **Remote desktop** switch on the hub's Modules page turns on, and goes when it stops or goes offline.

- Select **Connect** on the entry.

The button reads **Connecting…**, the viewer opens on that desktop, and the row reads **Viewer open**. The hub sets the seat password and gives it to the viewer with that one press. The viewer connects to the entry's forward on `127.0.0.1`, and the forward ends when the viewer closes.

Text copied on either machine pastes on the other. To copy a file to the remote machine, choose **Transfer file** in the viewer's toolbar and drop the file on the remote side of that window. Under a Mac's entry, a line says that a black picture or a dead mouse means that Mac has not given RustDesk **Screen Recording** and **Accessibility**.

| What you see                                     | Cause                                                    |
| ------------------------------------------------ | -------------------------------------------------------- |
| the page reads **No shared remote desktops yet** | no machine is sharing, or the sharing machine is offline |
| `rdp_not_shared`                                 | the machine stopped sharing                              |
| `rdp_no_desktop`                                 | this session has no screen to open a viewer on           |
| `rdp_launch_failed`                              | the viewer did not start, with the reason after the code |

## Settings

1. Select **Settings** under the rule in the sidebar.
1. On the **Client settings** panel, pick the **Language** and the **Theme**: **System**, **Dark** or **Light**.
1. Select **Save**.

The language and theme belong to this window; the panel keeps its own.

The **About** card lists this computer's name and platform, the client's version and licence, and each program the client includes with its version, licence and **Source** link.

## The tray

Closing the window hides it, and the client keeps every hub connected and every forward listening. The tray icon is in the taskbar corner on Windows, the indicator area of the top bar on Linux, and the menu bar on macOS. Its menu has **Open**, which shows the window, and **Quit**, which stops the client.

![The tray menu on Windows](/guide/os/win_tray_flyout.webp)
