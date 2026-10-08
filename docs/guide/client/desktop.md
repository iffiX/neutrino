---
title: Desktop client
---

# Desktop client

The desktop client window opens the web pages, ports, AI gateway, shares, terminals and remote desktops of every hub this computer joined. Each page reaches its service through the hub's port 8443, so the computer needs that one port of each hub. Installing the client and joining a hub are on [Install a client](../install/client.md). The same work runs in a terminal with the commands in [nclient commands](../commands/nclient.md).

## Hubs

The window, titled **Neutrino client**, has a sidebar with **Hubs**, **Web**, **Ports**, **AI**, **Files**, **Terminals** and **Remote desktops**, then **Settings** under a rule. The **↻** button at the top right refreshes every hub. A connected hub gets a fresh report, and a hub that is down gets a new connection attempt.

The **Hubs** page holds one row per hub: its name, its state, its address and the package it runs.

### Row states

While the channel to a hub is open, the row's state names the path it took:

| State                     | The channel reached the hub through                                 |
| ------------------------- | ------------------------------------------------------------------- |
| **Connected · LAN**       | the hub's address on a network this computer is on                  |
| **Connected · Direct**    | one of the hub's own addresses, from outside the networks it serves |
| **Connected · NetBird**   | the hub's NetBird address                                           |
| **Connected · EasyTier**  | the hub's EasyTier address                                          |
| **Connected · SSH Relay** | the public port of the hub's SSH Relay server                       |

Beside the state, a tag such as **12 ms** shows the last round trip to the hub. Every 20 seconds the client sends the hub a `ping` frame and times the `pong` that comes back, so the tag changes every 20 seconds. The tag is absent until the first `pong` arrives.

![The client window connected to a hub, with the path and the round trip](/guide/en/client_connected.webp)

To connect, the client dials every address of the hub at the same moment. These are its address on each connected virtual network, its name, and the addresses it last published. The first socket to finish its TLS handshake with the pinned certificate becomes the channel, and the client closes the others.

A change of network starts a new round at once. The client counts an interface going up or down, a virtual network connecting, and a new set of hub addresses as changes. A connected hub moves to the round's winner only when that path ranks higher, in the order LAN, Direct, NetBird or EasyTier, SSH Relay. On paths of equal rank, it moves only when the new handshake was faster.

The dot before the name shows the state:

| Dot            | Meaning                                                                                                           |
| -------------- | ----------------------------------------------------------------------------------------------------------------- |
| green          | the channel is open                                                                                               |
| amber, pulsing | the client is connecting, or a job runs on the row                                                                |
| amber          | the hub is out of reach and nobody has to act, as with `hub_unreachable`, or the hub has switched this client off |
| red            | a person has to change something, as with `hub_untrusted` or `protocol_too_old`                                   |
| grey           | the client has not reached the hub yet                                                                            |

### Row buttons

| Button        | Shown                                                                                                  | What it does                                                                                                 |
| ------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Panel**     | when the client's permission on the hub's **Clients** page includes **Hub panel without the password** | reads **Opening…**, then opens the hub's panel in your browser through a forward on this computer, signed in |
| **Reconnect** | on a row reading **Replaced by another client**                                                        | takes the hub back from the other client and connects                                                        |
| **Leave**     | always                                                                                                 | reads **Press again to leave**; a second press within five seconds leaves the hub                            |

**Panel** opens the panel wherever the client reaches the hub, so the panel's own ports can stay on the LAN. The browser opens `http://panel-<hub-id>.localhost:<local-port>/?tkn=<token>`, or `http://127.0.0.1:<local-port>/?tkn=<token>` on macOS. In that address, `<hub-id>` is the hub's id, `<local-port>` the forward's port, and `<token>` a sign-in that works one time within a minute. The forward stays until you leave the hub or quit the client.

Leaving removes the row at once, whether the hub is reachable or not. It ends what the hub published on this computer: its forwards, mounts and viewers, and a virtual network no other hub uses. In a terminal, `nclient leave --yes` leaves without the question, and `nclient status --json` prints every hub's state as JSON.

After a refusal, the row keeps the code on its error line, and the client connects again with up to a minute between tries. `binding_unknown` removes the row instead:

| Code               | Meaning                                                              | What to do                                                            |
| ------------------ | -------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `protocol_too_old` | this client speaks an older protocol number than the hub accepts     | install a newer client                                                |
| `protocol_too_new` | this client speaks a newer protocol number than the hub              | update the hub                                                        |
| `hub_untrusted`    | the certificate at that address differs from the one the link pinned | after a reset or a new install of the hub, join again with a new link |
| `binding_unknown`  | the hub's **Clients** page no longer lists this client               | join again with a new link                                            |

### Virtual network

A row has a **Virtual network** line when the hub publishes NetBird or EasyTier and the client's permission includes the virtual network. The line names the network's state and, while connected, this computer's address on it. The hub row names the channel's path, which the line leaves alone.

| The line reads                                           | Meaning                                                | The button     |
| -------------------------------------------------------- | ------------------------------------------------------ | -------------- |
| **Not connected**                                        | this computer is off the network                       | **Connect**    |
| **Connecting…**, with **Logging in to NetBird** under it | the engine starts and logs in, for 90 seconds at most  | **Cancel**     |
| **Connected ·** and this computer's address              | the engine runs and has given this computer an address | **Disconnect** |

In EasyTier's console mode, the line stays at **Connecting…** after the login, with the reason **This machine is registered with the console. Attach it to a network there.** It stays there until the console's owner attaches the computer, or until you select **Cancel**.

A failure returns the line to **Not connected** with the code under it, and the client makes no second attempt by itself. A computer that was connected when the client quit connects one more time when the client starts.

When the hub publishes both engines, a picker beside the button names the engine to use. The picker changes only while the line reads **Not connected**.

![The virtual network picker on a hub row](/guide/en/client_network_picker.webp)

The NetBird and EasyTier daemons are system services, so the computer stays on the network after the client quits.

| Code                      | Meaning                                                                                       |
| ------------------------- | --------------------------------------------------------------------------------------------- |
| `overlay_other_network`   | this computer is on another NetBird network or another hub's EasyTier console; leave it first |
| `overlay_daemon_down`     | the NetBird or EasyTier daemon is stopped; reinstall the client                               |
| `bundle_missing`          | this install has no NetBird or EasyTier; reinstall the client                                 |
| `overlay_join_failed`     | NetBird or EasyTier rejected the join, with the engine's own words after the code             |
| `overlay_no_address`      | the engine gave this computer no address within 90 seconds                                    |
| `overlay_console_invalid` | EasyTier cannot use the console address the hub named                                         |

### One client per computer

One person's client runs on a computer at a time, because the virtual network, the files adapter and the local ports belong to the computer. While one account's client runs, `nclient gui` under any other account exits with no window, no tray icon and no message. Every other `nclient` command of that other account prints `client_held` with the running client's account and exits with status 1.

The computer is free for another account after the running client quits or crashes, or its session ends.

## Forwards

A forward is a port on `127.0.0.1` that the client opens for one entry. Each connection to it becomes a stream to the hub, and the hub connects that stream to the service. A forwarded row shows `→ 127.0.0.1:` and the port.

| Page                | The forward listens                                             |
| ------------------- | --------------------------------------------------------------- |
| **Web**             | from **Open** until **Disconnect**                              |
| **Ports**           | from **Connect** until **Disconnect**                           |
| **AI**              | while the client runs and the tools point at that hub           |
| **Files**           | on Linux and macOS, from **Mount** until the share is unmounted |
| **Remote desktops** | from **Connect** until the viewer closes                        |

Every program and every account on this computer can connect to a forward while it listens. Quitting the client ends every forward.

### Local port

On the **Web** and **Ports** pages, **Configure** on a row opens the **Local port** choice:

- **Auto** takes the entry's own port when nothing on this computer listens on it, on any address, for the entry's protocol. Otherwise it takes the first free port from 20000 up. The client keeps that port for the entry, also after a restart.
- **Fixed** takes the number you type, from 1024 to 65535. A number another entry of the same protocol holds is rejected with **Another entry holds port** and the number.

The client checks a **Fixed** number again each time the forward starts. One number can be held twice, once for TCP and once for UDP. **Configure** is greyed while the entry is forwarded, with the reason **Disconnect first to change the local port.**

### Codes on a forwarded row

A page whose forward cannot reach its service shows one of these codes on the row:

| Code                 | Meaning                                                                                                                       |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `connect_failed`     | the hub or the machine could not connect to the service: `refused` (nothing listens on the port), `timeout` or `unreachable`  |
| `agent_offline`      | the machine that provides the entry is not connected to the hub                                                               |
| `port_not_published` | the machine has stopped publishing that port, for example because the container or the instance stopped                       |
| `connect_limit`      | this client has 256 connections open through the hub; close some and try again                                                |
| `permission_denied`  | the client's permission on the hub's **Clients** page leaves out that kind of entry, or that machine                          |
| `service_unknown`    | the hub no longer publishes the entry                                                                                         |
| `port_taken`         | another program on this computer listens on the **Fixed** port, so the forward did not start; pick another with **Configure** |

## Web

The **Web** page lists every web address the joined hubs publish: Gitea, VS Code, code-server, CloudCLI, and addresses a hub's **Services** page declares by hand. The line under each address names the hub, the machine and the module, such as **from hub:server:Gitea**.

| Button         | What it does                                                                                       |
| -------------- | -------------------------------------------------------------------------------------------------- |
| **Open**       | reads **Opening…**, makes the entry's forward when it has none, and opens the page in your browser |
| **Configure**  | sets the forward's local port                                                                      |
| **Disconnect** | shown while the entry is forwarded; ends the forward                                               |

The browser opens `http://`, a name under `.localhost`, and the local port, so two instances keep their logins apart. On macOS the name is `127.0.0.1`, because Safari resolves no `.localhost` name.

A VS Code, code-server or CloudCLI entry opens only with a token. Each press of **Open** fetches a fresh token from the hub and adds it to the address. A code-server or CloudCLI token works one time, within 60 seconds. When the hub sends no token, the row shows `web_token_missing`.

An entry the hub cannot reach is greyed and reads **Not reachable now**. A page with no entry reads **No web services yet**.

## Ports

The **Ports** page relays a port a hub publishes to this computer's loopback address. An entry is a container's host port on a managed machine, or a TCP or UDP port the hub's **Services** page declares.

- Select **Connect** on the entry.

The button reads **Forwarding…**, then **Disconnect**, and the row adds `→ 127.0.0.1:` with the local port. Point any program on this computer at that address.

A UDP entry reads `host:port/udp`, and after **Connect** the row adds the local port with `/udp`. A program on this computer sends its datagrams to that local address and gets the replies there. A declared UDP port shows no health word, and **Connect** stays available.

Everything this client sends goes through one TCP connection to the hub. A lost packet holds up every stream on that connection until it is sent again, UDP streams included. A UDP port through the hub suits small question-and-answer traffic: DNS, time, discovery, a small game server.

## AI

The **AI** page points Claude Code, Codex and Gemini CLI on this computer at one hub's AI gateway. Each hub with a gateway has one entry, with **Configure** and a **The AI tools use this gateway** switch. At most one switch is on.

Select the switch on the gateway you want. The entry reads **Switching tools…**, then **The tools point at the hub**, and the switch that was on turns off.

The client makes the gateway's forward and points each tool at it with this client's key. The bundled cc-switch rewrites each tool's configuration, and a failure in one tool leaves all three unchanged. Turn the switch off to restore each tool's configuration from before.

The line under the entry reads **The tools reach the gateway only while this client runs.** Keep the client running in the tray while you use the tools.

The switch works only on a connected hub; otherwise the client returns `no_exit_hub`. A hub that has issued this client no key returns `no_endpoint`, and its **AI** page issues one.

To choose the models:

1. Select **Configure** on the entry. The **AI tool configuration** dialog opens.
1. Under **Claude Code**, pick the **Default model**, **Opus slot**, **Sonnet slot** and **Haiku slot**.
1. Under **Codex**, pick the **Model** and the **Reasoning effort**: `minimal`, `low`, `medium` or `high`.
1. Under **Gemini**, pick the **Model**.
1. Select **Save**.

Each picker also offers **gateway default**, and it lists that hub's own models. On the gateway in use, **Save** rewrites the tools at once; on another gateway, the choice applies when you switch to it.

When the Neutrino agent is also installed on this computer, the agent sets the AI tools, and the switch and **Configure** are greyed. Their reason line reads **This is a managed device: set its AI tools on the hub's panel, under Modules, Global configuration.** A switch that was on turns off one time and restores the tools. The hub's side of that setting is on [AI tools](../agent/modules/ai_tools.md).

## Files

The **Files** page mounts an SMB share a hub publishes. Linux mounts it in a folder under your home, macOS as a volume in the Finder, and Windows on a drive letter. An entry is a share of the file share module on a managed machine, or a share declared on the hub's **Services** page.

To mount a share:

1. Select **Configure** on the entry. A form opens under the row.
1. Type the **Share username** and **Share password** the share accepts.
1. On Linux, keep or change the **Mount path**, a folder under your home such as `~/nas/media`. On Windows, pick the **Drive**. On macOS, skip this step.
1. Select **Save**.
1. Select **Mount**. The button reads **Mounting…**, then **Unmount**.

![The Files page with a share mounted](/guide/en/client_files_mounted.webp)

The client keeps the login in a credentials file only your account reads, so the next **Mount** reuses it. **Unmount** detaches the share and keeps the login.

### How each system mounts

| System  | The mount                                                                                                                                                                                                         |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Linux   | the client's mount helper runs under `pkexec` and mounts the share from the forward's port; polkit shows a password prompt the first time                                                                         |
| macOS   | the system mounts the volume from the forward, as the Finder's **Connect to Server** does; the first mount shows a dialog to confirm the server, and the row names the mount point under `/Volumes`               |
| Windows | the files adapter gives each machine that provides a share its own address, from `198.19.255.2` up, and Windows maps the drive to that address; a drive letter keeps naming the same machine <!-- scan: allow --> |

On macOS a wrong password opens the system's login dialog, and **Cancel** there gives `mount_not_authorized`. When the system has not finished after ten minutes, the row shows `mount_timed_out`.

On Windows the adapter is a network adapter named `neutrino_files`, run by the `NeutrinoClientFiles` service. It is connected to no network and sends only the shares' connections to the hub. The adapter serves one account at a time.

![The mapped drive in File Explorer](/guide/os/win_explorer_mapped.webp)

| Code                          | Meaning                                                                                                 |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- |
| `mountpoint_invalid`          | the path is outside your home                                                                           |
| `mountpoint_not_empty`        | the folder holds files                                                                                  |
| `mountpoint_not_drive_letter` | on Windows, the drive is not an unused letter                                                           |
| `mountpoint_in_use`           | another entry, from any hub, mounts at that path                                                        |
| `credentials_missing`         | the saved login is gone; type it again in **Configure**                                                 |
| `share_login_rejected`        | the username or password is wrong; **Configure** opens with the username filled in                      |
| `share_access_denied`         | the share accepts the login and denies that account access                                              |
| `share_not_found`             | the host has no share by that name                                                                      |
| `share_unreachable`           | the host is out of reach; the client mounts again when it is back                                       |
| `share_session_conflict`      | Windows holds a connection to that server under another login; disconnect it first                      |
| `files_adapter_unavailable`   | on Windows, the `NeutrinoClientFiles` service is missing, stopped or failing                            |
| `files_adapter_in_use`        | on Windows, another account's client holds the files adapter; the mount retries after that client quits |
| `mount_not_authorized`        | the polkit prompt or the macOS login dialog was dismissed                                               |
| `mount_tooling_missing`       | on Linux, the computer has no `mount.cifs`                                                              |
| `pkexec_missing`              | on Linux, the computer has no `pkexec`; install it and mount again                                      |
| `mount_timed_out`             | on macOS, the system did not finish the mount within ten minutes; select **Mount** again                |

## Terminals

The **Terminals** page opens a shell on a machine a hub manages, in a tab of the window. The client's permission on the hub's **Clients** page must include terminals.

1. On the **Terminals** page, pick the machine in the strip on top. A green dot marks a machine that is online.
1. Select **New terminal**.

The shell opens in a new tab, and every key you type goes to the machine. The window draws the shell in MesloLGS NF, which the client includes, so a powerlevel10k prompt shows its icons.

![A persistent terminal tab in the client](/guide/en/client_terminal.webp)

To paste, press the right mouse button on the shell and choose **Paste**, or press Ctrl+Shift+V, or Cmd+V on macOS. **Clear** in the same menu sends Ctrl+C and empties the screen. The terminal reads **Clearing…** and drops new output until the shell has been quiet for half a second.

Two switches sit at the end of the line under the shell. **Persistent** keeps the session on the machine while no window is attached, for example after the client quits. **Shared** lists the session for every client with terminal rights on that machine.

A kept session shows as a tab with a grey dot. Select it to attach, and the shell's recent output appears first. When a hub's channel drops and comes back, each tab whose session still exists attaches again, and a tab whose session is gone reads **Ended**.

The **×** on a persistent tab reads **Press again to end**, and a second press ends the shell on the machine. The panel lists the same sessions on [Terminals](../agent/terminals.md).

| Code                | Meaning                                                                                         |
| ------------------- | ----------------------------------------------------------------------------------------------- |
| `permission_denied` | the client's permission leaves out terminals                                                    |
| `agent_offline`     | the machine is not connected to its hub                                                         |
| `unknown_terminal`  | the hub offers no terminal on that machine                                                      |
| `session_not_owned` | the session belongs to another viewer and is not shared; open only your own or a shared session |
| `session_unknown`   | the machine no longer keeps the session                                                         |

## Remote desktops

The **Remote desktops** page opens another machine's screen in the RustDesk viewer the client includes. An entry appears while a managed machine shares its desktop through its **Remote desktop** module on the hub.

- Select **Connect** on the entry.

The button reads **Connecting…**, the viewer opens on that desktop, and the row reads **Viewer open**. The hub hands the seat password to the viewer with that press. The viewer connects to the entry's forward on `127.0.0.1`, and the forward ends when the viewer closes.

Text copied on either machine pastes on the other. To copy a file to the remote machine, choose **Transfer file** in the viewer's toolbar. Under a Mac's entry, a line explains a black picture or a dead mouse: that Mac lacks the RustDesk grants **Screen Recording** and **Accessibility**.

| What you see                                     | Cause                                                                  |
| ------------------------------------------------ | ---------------------------------------------------------------------- |
| the page reads **No shared remote desktops yet** | no machine is sharing, or the sharing machine is offline               |
| `rdp_viewer_open`                                | a viewer is already open on this desktop; close it first               |
| `rdp_nobody_seated`                              | nobody is signed in at that machine's screen                           |
| `rdp_screen_not_allowed`                         | screen sharing has to be allowed one time at that machine's own screen |
| `rdp_not_shared`                                 | the machine stopped sharing                                            |
| `rdp_no_desktop`                                 | this session has no screen to open a viewer on                         |
| `rdp_launch_failed`                              | the viewer did not start, with the reason after the code               |

## Settings

1. Select **Settings** under the rule in the sidebar.
1. On the **Client settings** panel, pick the **Language** and the **Theme**: **System**, **Dark** or **Light**.
1. Select **Save**.

The language and theme apply to this window, and the panel keeps its own. The **About** card lists this computer under **This machine**, then under **Carried** the client and each program it includes, with version, licence and **Source** link.

## The tray

Closing the window hides it, and the client keeps every hub connected and every forward listening. The tray icon is in the taskbar corner on Windows, the indicator area of the top bar on Linux, and the menu bar on macOS. Its menu has **Open**, which shows the window, and **Quit**, which stops the client.

![The tray menu on Windows](/guide/os/win_tray_flyout.webp)
