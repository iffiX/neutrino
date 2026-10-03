# The device agent

The agent is the hub's presence on a managed Linux, Windows or macOS
machine: one root service with one socket open to the hub. It hosts the
modules the hub's state names, reports what is true, and shares the
machine's desktop when told. It draws no window and, apart from the
CloudCLI forwarder ("CloudCLI" below), listens on no port. Its own code is
pure standard library. The
package includes the interpreter that runs it, so it installs on a machine
with no Python and touches none the machine already has.

Everything a person does with what the hub publishes belongs to the client,
a separate package in that person's own session
([architecture.md](architecture.md), "The shape of the system"). The client
also joins the hub's virtual network as an ordinary peer, through the NetBird
and EasyTier daemons its own package registers as services. A terminal it
opens on a managed machine is a `shell` stream the hub bridges to that
machine's agent, the same shell the panel's terminal reaches. This page is
the agent's own design: who commands it, how state moves, how the machine's
root reaches it, and where the platform seam runs. The socket itself, its
frames, sections, kinds and admission, is [protocol.md](protocol.md).

## Who may tell the agent what

Two authorities, and nothing else: the hub over the pinned socket, and the
machine's own root over the local control socket. There is no third door and
no per-account scope: an ordinary account on the machine talks to the client,
never to the agent.

**Modules and services** are the two words that hold everywhere, on the
hub's pages, in the agent, and in the client:

- **Modules** are software the hub administers on a machine: Samba, Gitea,
  Podman, ZFS, VS Code, CloudCLI and the RustDesk host. The hub says what is wanted and sends
  the bytes; the agent observes, installs and configures. A device's Modules
  page writes one `want` per module into `config/devices/<id>/modules.json`.
  The state the agent receives names, per module, that `want`, the
  configuration, and the install and uninstall recipes for its platform
  ([protocol.md](protocol.md), "The channel").
- **Services** are what the hub publishes and what a client consumes: a web
  link, a port, the AI gateway, a share, a shared desktop. The agent composes
  none of them and renders none of them. Its only part is the one entry a
  machine declares for itself, its own desktop, described below.

| The hub may | Root on the machine may |
| --- | --- |
| Push the state and open `shell`, `file` and `command` streams | Bind the machine to a hub, or unbind it |
| Say which modules are absent, installed, stopped or running, and configure them | Send a report now (`nagent sync`) |
| Reboot, shut down, reinstall the agent | Share the desktop and stop sharing it |
| Read and set up a person's own AnyDesk or TeamViewer | Read the binding and status |
| | Start and stop the agent's service |

Root is uid 0. `nagent` refuses any other account; the one thing anybody can
run is `nagent --version`.

## One socket, everything on it

The agent opens one WebSocket to the hub over TLS pinned by the link's
fingerprint, and reconnects when it drops. The hub never dials a machine; SSH
exists only to install or reinstall an agent from the Devices page. Text
frames are JSON; a binary frame is a stream id and its bytes. The frames, the
sections and the kinds are in [protocol.md](protocol.md), "The channel".

Up: a `hello` when the socket opens, then a `report` every few seconds and
at once when something changed. A report has the machine (hostname,
platform, accounts, metrics) and the network (the link the socket runs on and
every interface). It also has each module's observed state, the desktop
declaration, and the most recent error worth showing. Down: the `state`, once when the first
report's hash differs and again whenever the hub's copy changes, and the
streams the hub opens.

The hub opens `shell`, `file` and `command` streams to an agent; the agent
opens `log` and `package` streams to the hub; `desktop` is reserved. A
`command` names a module and a verb (`{agent, reboot}`, `{samba, reload}`,
`{zfs, validate}`). Every stream sits behind a credit window, so a long
transfer never starves the reader, and a stream's result is its close.

**Presence is memory only.** Online, version and last seen are in the hub's
session registry. A hub restart forgets every machine until it reports again,
and nothing about a socket reaches `config/`.

**The state is one document per device.** The hub composes it from
`config/devices/<id>/`: `modules.json` with each module's `want`, one file per
module with its configuration, and `rdp.json` with the sealed seat password.
The install and uninstall recipes resolved for the machine's platform are
added to it, and it is sent under one hash. The agent keeps a root-only copy,
compares on connect and on every `state` frame, and makes each mentioned
module's actual state equal its `want`:

| `want` | The agent ensures |
| --- | --- |
| `absent` | the package is removed by its recipe; the configuration the hub wrote and the configured mark are deleted |
| `installed` | the package is present; nothing is configured and nothing is started |
| `stopped` | the package is present, the configuration is applied, the unit is stopped |
| `running` | the package is present, the configuration is applied, the unit is active |

A module the state does not mention is left alone, observed and reported all
the same. The applied hash moves only once every mentioned module applied. A
failed apply keeps asking only when the state changes, and until then the
report says why with a code. **An edit to a module of an offline device is
rejected with `agent_offline`, never queued**: the person is told the machine
is away, and asks again when it is back.

**The agent is handed conclusions, never a table to search.** The recipes it
receives are already resolved for its platform; it has no manifest logic and
no version table. A module it has no runner for is `unsupported`, which is an
older agent meeting a newer hub. The `software` in `welcome` names the newer
package, and the agent installs it over itself ([protocol.md](protocol.md),
"Admission and the binding").

**A press writes `want`, and the machine's report is the answer.** Pressing
a button writes the value, the agent makes the machine match it, and what
the machine reports afterwards is shown. The agent keeps no retry policy and
no memory of past failures. A step that failed is reported failed with its
code and is not repeated while the state's hash is unchanged; trying again is
a person's word, never a timer's.

Software somebody installs or removes by hand is displayed, never fought. A
hand-installed Samba reports `installed`; its shares and users become the
hub's configuration at the machine's first report on a socket, and the
first **Configure** imports them when that report found none
([protocol.md](protocol.md), "The modules section"). A failure
exists only in the report, and a hub restart loses nothing, because `want` is
in `config/`. Machinery whose only purpose is surviving a restart is removed
on sight ([../kill_on_sight.md](../kill_on_sight.md), "Unasked survival
machinery").

The file share on Windows and macOS is the one module that changes what the
person set up. On Linux it owns the whole `smb.conf`; on Windows and macOS it
owns who reaches the system's SMB server. It changes only the shares and
accounts it made, the ones its record under the state root lists and its
marker names, but its fence covers every share on the machine, the person's
own included.

**Status is typed.** A module reports `state`, `is_active` and
`{code, params}`, never an English sentence, and every surface does its own
wording. The agent's `error` section crosses the socket the same way, so a
device that is unhappy says why on the panel. Module states are one closed
table on every surface:

| Steady | Transient | Shared |
| --- | --- | --- |
| `absent`, `installed`, `stopped`, `running` | `installing`, `uninstalling` | `failed`, `unsupported` |

`installed` is present and never configured by the hub; `stopped` and
`running` are configured by the hub and told apart by the unit. A surface
that meets a token outside this table shows "waiting for the agent", the word
for a machine that has not reported. Wherever a state is drawn:

- Every transient token is in the surface's busy set, or a row mid-step
  offers the opposite button.
- A surface's optimistic step holds at most two minutes before the machine's
  own report, or its silence, takes over.
- A new `code` arrives with its wording in the same change, which the
  catalog completeness test enforces.

## The desktop is the machine's own word

Sharing a desktop is the one thing decided on the machine and reported
upward, never ordered down. `sudo nagent rdp start [--user <name>]`
configures RustDesk for direct connection on port 21118, no rendezvous
server and no relay, and `nagent rdp stop` withdraws it. With no `--user`
the seat is `SUDO_USER`, else the one account at the screen.

**The seat password is the hub's.** A machine reporting the RustDesk host
installed is given one, generated once and sealed under the vault's data key
in that device's `rdp.json`. It is delivered in the `desktop` section of the
state. The agent sets it into RustDesk whenever it changed and keeps it in a
root-only file so it knows what it already set. It enters neither the agent's
store nor any report.

The panel never shows it: the device drawer offers **Reset seat password**,
which generates a new one and disconnects every viewer. A client that presses
**Connect** opens a `service` stream, the hub unseals the password for that
one close, and the viewer is spawned with it.

**A share is declared only once it answers.** RustDesk's root service holds
no port of its own; it spawns a second process into the session of whoever
is logged in at the seat, and that process is what listens. So a machine
with nobody logged in has nothing listening, which `rdp_nobody_seated`
refuses in front of, and a Wayland session that has not granted screen
capture reports `rdp_screen_not_allowed` instead of a desktop nobody can see.

The declaration is the `desktop` section of every report,
`{is_shared, account, share_id, port, attention, connected_count}`. The hub
pairs it with the device's address, chosen for the caller's network
([protocol.md](protocol.md), "Devices on the channel"), and keeps it in
memory alone. It dies when the machine stops sharing, stops reporting, or the
hub restarts, and the next report from a machine still sharing puts it back.

A person's own AnyDesk or TeamViewer is not a module. The agent detects what
is there, brings a stopped daemon up, reads the id a peer connects to and
sets the unattended password when the drawer asks, as the seated account for
AnyDesk and as root for TeamViewer, because that is where each keeps its
configuration.

## The local control channel

One Unix socket, 0600 under a 0700 directory, so the kernel refuses anyone
but root before a request is read and no handler judges identity. `nagent`
is its only client:

| Verb | Does |
| --- | --- |
| `join <link>` | binds the machine to the hub the link names |
| `leave` | unbinds it |
| `status` | reads the binding |
| `sync` | sends a report now |
| `rdp start`, `rdp stop` | share and unshare the desktop |
| `start`, `stop` | start and stop the agent's service through systemd, the service control manager or launchd; the binding is not touched |
| `run` | the foreground entry systemd and launchd start; `service run` is Windows' |

Connections persist between requests and each is served on its own thread.
Every refusal is `{"code": ...}`; a handler exception never drops the
connection, the caller gets `agent_internal` with the exception's class name
and the traceback goes to the agent's log.

An agent that has never enrolled still serves this socket, with no binding to
report. The binding, the applied state and what the machine decided for
itself are in one root-owned store written atomically; secrets never enter
it.

## Acting for an account

The agent is root, so reaching down to an account is `runuser -u <account>
--`, never `sudo`, for the reason the hub bans it
([privilege.md](privilege.md)). That reach is two things. One is the seat
whose desktop is shared, whose RustDesk configuration lives in that
account's own session. The other is VS Code, whose servers run as the
accounts the module names, each started by the system's own service
manager: a systemd unit with `User=` on Linux, a LaunchDaemon with
`UserName` on macOS, and on Windows a scheduled task registered with the
account's login, because LocalSystem cannot start a process as another
account without its password; on Windows the module also opens each
instance's port in the firewall and closes it with the instance, since the
hub's forwards reach the server from the network. CloudCLI is reached the
same way ("CloudCLI" below). Everything else the agent does is root's own
work.

## The platform layer

`neutrino_agent/platforms/` holds one class per platform behind one
contract: `linux.py`, `windows.py` and `darwin.py`, and `detect_platform`
returns the one for the running system. The contract names intents, not
mechanisms: enumerate human accounts, resolve an account's home, run a
process as an account, control the agent's own service, power actions, read
host metrics, read the machine's interfaces, read the machine id, install and
remove a package of a kind, and where the agent keeps its state and its work.

A platform advertises the capabilities it has; invoking an absent one is
refused with `{"code": "unsupported_platform"}`, never guessed at. The engine
builds the package-backed runners only on a platform with `packages`. A
platform with `smb_server` gets the file share, driving the SMB server the
system carries, with nothing to install or uninstall; there, any other
module the state names reads `unsupported`, never `failed`, beside the
built-in RustDesk row. A platform with `hub_packages` gets the VS Code
module; on Linux VS Code is one of the runners `packages` builds. On every
system, software the hub sends down a package stream is unpacked into a
directory of the module's own name under the state root, and that directory
alone is opened to every account to read and run: mode 755, and on Windows
read and execute for the Users group. Every import
only POSIX has is guarded, so one package imports on all three systems.

| | Linux | Windows | macOS |
| --- | --- | --- | --- |
| Program | `/opt/neutrino/agent` | `C:\Program Files\Neutrino\agent` | `/Library/Application Support/Neutrino/agent/app` |
| Configuration root: the binding, the credentials, the desired state | `/etc/neutrino/agent` | `%ProgramData%\Neutrino\agent\config`, under `%ProgramData%\Neutrino\agent`, whose ACL, SYSTEM and the administrators alone, the `.msi` sets | `/Library/Application Support/Neutrino/agent/config`, mode 700 |
| State root: configured marks, packages, the last reinstall, `vscode/`, `cloudcli/` | `/var/lib/neutrino/agent` | `%ProgramData%\Neutrino\agent\state` | `/Library/Application Support/Neutrino/agent/state`, mode 755 |
| Log | the journal | `%ProgramData%\Neutrino\agent\log\agent.log` | `/Library/Logs/Neutrino/agent/agent.log` |
| Service | systemd `neutrino_agent.service` runs `nagent run` | the `neutrino_agent` service, LocalSystem, runs `nagent service run` | the `com.neutrino.agent` LaunchDaemon runs `nagent run` |
| Control transport | Unix socket `/run/neutrino/agent/agent.sock` | named pipe `\\.\pipe\neutrino_agent`, its descriptor SYSTEM and the administrators | Unix socket `/var/run/neutrino/agent/agent.sock` |
| Metrics | `/proc`, `/sys`, `nvidia-smi` | kernel32 `GetSystemTimes`, `GlobalMemoryStatusEx`, `GetTickCount64` and the system drive; per-core CPU and the process table from `NtQuerySystemInformation`, sampled twice; GPUs from `nvidia-smi` where it is installed, else the PDH counters `GPU Engine` and `GPU Adapter Memory` summed per adapter; a temperature from WMI `MSAcpi_ThermalZoneTemperature` where the firmware exposes one, else none; no load average | `host_statistics`, `vm_stat`, `sysctl` and `/`; per-core CPU from `host_processor_info`; the process table from `ps -axo pid,user,comm,%cpu,%mem`; GPUs from the `PerformanceStatistics` of `ioreg -r -c IOAccelerator`; a temperature from `powermetrics --samplers smc`, which root may run |
| Interfaces | `ip -j addr` | one PowerShell call joining `Get-NetAdapter` to `Get-NetIPAddress`, read at most every 30 seconds | `ifconfig -a` |
| Machine id | `/etc/machine-id` | the registry's `MachineGuid` | `IOPlatformUUID` from `ioreg` |
| Accounts | uid 1000 and above with a login shell | the enabled local accounts from `Get-LocalUser`, without Administrator, Guest, DefaultAccount, WDAGUtilityAccount and the file share's own, read at most every 30 seconds; the home is the profile `Win32_UserProfile` names | `dscl`, uid 501 and above, home under `/Users` |
| Power | `systemctl reboot` or `poweroff --force` | `shutdown /r` or `/s /t 0` | `shutdown -r` or `-h now` |
| Refused | nothing | stepping down, packages, the `kill` verb, but not `persist` or `stop_session` | stepping down, packages |
| Shell stream | the login shell on a pseudo-terminal | PowerShell on a pseudo console, in a job that kills it on close | `zsh -il` on a pseudo-terminal |
| Seat | `loginctl`, `/proc/net/tcp`, the Wayland token | the console session's user through WTS, `netstat` | the owner of `/dev/console`, `netstat`, the privacy grants |
| RustDesk | `/usr/lib/neutrino/agent/rustdesk/rustdesk`, unit `rustdesk`, root's and the seat's `RustDesk2.toml` | `%ProgramFiles%\RustDesk\rustdesk.exe`, service `RustDesk`, LocalService's `RustDesk2.toml` | `/Applications/RustDesk.app`, job `com.carriez.RustDesk_service`, root's and the seat's `RustDesk2.toml` |
| File share | Samba, `smb.conf` rendered whole | the SMB server through one PowerShell script per operation, JSON in and out and the password on standard input: shares whose description starts `neutrino:`, local accounts in no group, hidden from the sign-in screen and denied the console and RDP through `LsaAddAccountRights`, folders granted with `icacls`, and the block rule `neutrino_smb_fence` for TCP 445 from every address outside the allowed subnets | Apple's smbd through `launchctl enable` and `kickstart`: share points made with `sharing` under the record prefix `neutrino_`, SMB only, no guest, no encryption; accounts made with `sysadminctl` without a shell or a home, hidden, in `com.apple.access_smb` where it exists, the NT hash turned on before `dscl -passwd`; folders granted with `chmod +a`; the pf sub-anchor `com.apple/neutrino_smb`, loaded from a file under the state root at every apply and when the agent starts |
| VS Code | the CLI in `/var/lib/neutrino/agent/vscode`, the unit `neutrino_vscode@<account>.service` with `User=`, environment and token files in `/var/lib/neutrino/agent/vscode/tokens`, and `/etc/sysctl.d/90-neutrino-vscode.conf` when the machine's inotify watch or instance limit is under the module's floor (524288 and 512), since a served home directory runs a distribution's default out | the CLI in `%ProgramData%\Neutrino\agent\state\vscode`, the task `neutrino_vscode_<account>` registered with the account's login, at startup, no time limit, a limited token | the CLI in `/Library/Application Support/Neutrino/agent/state/vscode`, the LaunchDaemon `com.neutrino.vscode.<account>` with `UserName` |
| Self-update | `systemd-run` of `dpkg` or `dnf` | a detached PowerShell running `msiexec` | `launchctl submit` of `installer` |

Every system reports the same metrics document: CPU in total and per core,
memory, the system disk, a temperature where one is readable, the load
average where the system has one, the uptime, the GPUs and the process
table, and a field a system cannot read is empty rather than guessed. On
Linux the metrics come from `/proc` and `/sys` with nothing but the
standard library; NVIDIA is the one exception, read through `nvidia-smi`
where the driver installed it. The interfaces come from `ip -j addr`,
skipping `lo`, and on every system a missing or all-zero MAC is recorded as
`""` and a machine that cannot list its interfaces reports an empty list.

**A shell can outlive its stream.** A `shell` stream opened with a
`session_id` attaches to a shell the agent keeps under that id, or starts
one there. The agent reads the shell's output all the time, keeps its last
256 KB, and sends it first to a stream that attaches. Any number of streams
attach to one shell at once: each receives all the output, input from any
reaches the shell, and the terminal takes the smallest window's size. A
shell that `persist` marked persistent or shared keeps running when its last
stream closes; any other ends with it. The agent keeps the `owner` the hub
stamped on the open as given. The report's `machine` section lists every
kept shell, and the process holds them, so a restart ends them all ([protocol.md](protocol.md), "The
verbs on a `command` stream").

### Which modules each system runs

A module runs on a system when its manifest has a branch for the machine's
platform and the machine's `version` is not below that branch's
`min_version` ([protocol.md](protocol.md), "The modules section, one entry
per module"). The Modules page greys out every other module in its picker
and never shows it as a tab. The agent's minimum system stays where it is; a
module a system cannot run is left out on that system.

| Module | Linux | Windows | macOS |
| --- | --- | --- | --- |
| File share | Samba | the system's own SMB server | the system's own SMB server |
| Gitea | amd64 and arm64 | no | no |
| Containers (Podman) | yes | no | no |
| ZFS storage | yes | no | no |
| VS Code | glibc 2.28 and above, amd64 and arm64 | amd64 | arm64 and amd64 |
| CloudCLI | glibc 2.28 and above, amd64 and arm64 | amd64 and arm64 | arm64 and amd64 |
| Remote desktop (RustDesk, AnyDesk, TeamViewer) | yes | yes | yes |

A module's log, the answer to its `journal` verb, is the journal of its
systemd units on Linux. Windows and macOS run no module under a unit, so
each module there reads its own sources. The file share reads the SMB
server's latest events from `Microsoft-Windows-SMBServer/Operational` on
Windows, or what the unified log holds of `smbd` over the last 15 minutes on
macOS. After them come the agent's own log lines that name the module, from
`agent.log` under the log root on Windows and
`/Library/Logs/Neutrino/agent/agent.log` on macOS. VS Code reads the end of each
instance's log file. On Windows the task runs the CLI through `cmd.exe`,
which appends its output to `<account>.log` beside the CLI; on macOS the
LaunchDaemon's `StandardOutPath` and `StandardErrorPath` name
`/Library/Logs/Neutrino/agent/vscode_<account>.log`. Every log comes oldest line
first, at most the number of lines the verb asked for.

The hub's own machine on macOS and Windows runs the local agent
`nhub setup` installs ([install_and_dev.md](install_and_dev.md)), so its
shares and VS Code are that agent's modules, as on any device.

A VS Code instance listens on every address of the machine, on every
system; its token is what admits a browser, and the hub names the address a
client opens by that client's scope ([protocol.md](protocol.md), "The
address a caller is given").

A Mac shows a peer nothing until RustDesk holds both screen recording and
accessibility, which only somebody at that Mac grants. The seat reads the
grants from the system's privacy database, and its attention is
`rdp_permissions_needed` until both are there; a database root cannot read
reports the same.

### CloudCLI

The `cloudcli` module runs CloudCLI, the npm package `@cloudcli-ai/cloudcli`
pinned at 1.37.3 (AGPL-3.0), once per account: a web page for AI coding
sessions. It is an ordinary module shaped like VS Code,
`agent/neutrino_agent/modules/cloudcli/` with its config, constants, runner,
installer and one applier per system, and its configuration is
`{instances: [{account, port}]}`.

**It runs as the account, never as root**: a unit
`neutrino_cloudcli@<account>.service` with `User=<account>` on Linux, a
LaunchDaemon with `UserName` on macOS, and on Windows a scheduled task
registered with a login the Credentials page holds, chosen per instance as
for VS Code.

**Node.js comes from the hub and stays out of the system.**
`data/manifests/cloudcli.json`, written like `vscode.json`, pins the
nodejs.org standalone build of Node 22 LTS for Linux, macOS and Windows on
x64 and arm64, each with its url and the sha256 of `SHASUMS256.txt`. The hub
fetches it into its module cache and serves it on the `package` stream. The
agent unpacks it under its state root, `/var/lib/neutrino/agent/cloudcli/` on
Linux, `%ProgramData%\Neutrino\agent\state\cloudcli` on Windows and
`/Library/Application Support/Neutrino/agent/state/cloudcli` on macOS, the one
directory there opened to every account: owned by root, read-only, one copy
per machine. It is never put on `PATH`, in any shell
profile, or under `/usr/local`.

**CloudCLI is installed per account, apart from the account's own npm.** As
the account, with that Node, the agent runs
`npm install @cloudcli-ai/cloudcli@1.37.3 --prefix <app dir>` with
`npm_config_cache` inside the app directory and `npm_config_userconfig`
naming an empty file, so no `~/.npmrc` is read, `~/.npm` is untouched and
nothing is installed globally. The app directory is
`~/.local/share/neutrino/agent/cloudcli/app` on Linux,
`~/Library/Application Support/Neutrino/agent/cloudcli/app` on macOS and
`%LOCALAPPDATA%\Neutrino\agent\cloudcli\app` on Windows. The install reaches
nodejs.org, npm and GitHub; a LAN machine reaches them through the hub's
proxy, and no mirror is configured.

**The service's environment is written from scratch**: `HOST=127.0.0.1`,
`SERVER_PORT` (CloudCLI's own name for its port), `ANTHROPIC_BASE_URL` (the hub's gateway), `ANTHROPIC_AUTH_TOKEN` (the
device's gateway key, [modules/ai.md](modules/ai.md)), `OPENAI_BASE_URL`, and
`PATH`. Nothing is inherited from a login profile or a version manager.

**The `claude` CloudCLI starts is the account's own.** Before starting the
service the agent runs `command -v claude` in the account's login shell
(`runuser -l` on Linux, the account's shell with `-l -c` on macOS) and puts
that directory on the service's `PATH`. An account with none reports
`cloudcli_claude_missing {account}`. On Windows the task runs as the account
and has its `PATH` already.

**Node's own directory leads `PATH` for npm and for the service, on every
system.** The install scripts of the native modules call `node` by name,
and a task or a service that inherits no profile has nothing else on its
path that answers to it.

**A failed install names its step**: `cloudcli_node_download_failed`,
`cloudcli_npm_install_failed`, or `cloudcli_native_module_failed` when
better-sqlite3, node-pty or bcrypt cannot fetch its prebuilt binary.

**The agent's forwarder stands in front of CloudCLI.** CloudCLI listens on
loopback alone. A thin HTTP forwarder of the agent's listens on every address
of the device (`0.0.0.0`) at the configured port. The hub generates each
instance's password and keeps it in its vault; on CloudCLI's first start the
agent registers the account with it through CloudCLI's register endpoint,
the first account registered being its administrator, and the forwarder
answers nobody before that.

| A request | The forwarder |
| --- | --- |
| carries `?tkn=<token>` that verifies | logs in to CloudCLI with the hub's password, writes CloudCLI's login state into the browser, and redirects to the page |
| carries `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| carries CloudCLI's login state | passes it on unchanged, WebSocket included |
| carries neither | 401 |
| asks for CloudCLI's register or login endpoint | 401; those are never passed on |

**A token is verified on the device, with no call to the hub.** The hub
mints one secret per instance, keeps it sealed, and the module's desired
state carries it opened, as it carries the password; the agent keeps a
root-only record per instance (its ports, password and secret) so the
forwarder comes back after an agent restart. A token is
`base64url(expiry || nonce || HMAC-SHA256(secret, expiry || nonce))`, minted
by the hub on every `service` ask with `expiry` 60 seconds ahead ([protocol.md](protocol.md), the service material). The
forwarder checks the HMAC and the expiry itself and keeps every nonce it
accepted until that nonce's expiry, so a token works once. No token enters
the device's state, and minting one leaves the state's hash as it is
([client.md](client.md), "The Web page").

## Two ports, one process

The hub's panel answers HTTP on one port and HTTPS under the hub's own
certificate authority on another, behind a session, and its agent port is
pinned TLS serving `/api/channel` alone. All three are uvicorn servers in one
process. The ports, the certificate, the fingerprint and the hub's own
identity are in [protocol.md](protocol.md), "Three ports, two audiences".

Exposure is the only control plane. The agent port listens on every exposed
interface, WAN included, and on every exposed overlay; a served LAN that is
not exposed gets DHCP, DNS and forwarding only. A device on such a LAN is
enrolled after the LAN is exposed. A hub on macOS or Windows has no
exposure, and the agent port answers on every interface there
([network.md](modules/network.md), "Outside Linux, the system firewall").

## Joining: one ticket, five minutes, spent in one step

Generation happens on the panel port, behind the session: the Devices page's
per-device link, the blank link `nhub setup` prints, and the SSH install
action all call one path. A ticket is `secrets.token_urlsafe(18)`
(144 bits), held in panel memory only, dead after **five minutes**. That is
long enough to walk to another machine and paste, and short enough that a
forgotten link is not a standing invitation.

**Generating replaces whatever ticket was out**: there is exactly one open
invitation at a time. The machine the link was made for is the only one that
can join, and refreshing the page quietly retires the link before it. A hub
restart forgets tickets entirely.

The link is `neutrino://enroll/<base64url payload>` over one JSON object:

```json
{"urls": ["https://192.168.93.1:8443", "..."], "token": "...", "fp": "<sha256 hex>", "role": "agent"}
```

`urls` is every exposed address on the agent port, because only one of them
is on the joining machine's network and neither end knows which. A client
link is the same object with `"role": "client"`, generated on the Clients
page; the client rejects a device link and the agent a client one. The
base64url alphabet holds no character a shell splits or a URL escapes, so the
link pastes anywhere unquoted.

The agent tries each URL in turn, at enrolment and on every reconnect: the
name `hub.neutrino.internal` where the network resolves it, then the address
that last answered, then the rest of the set, `AGENT_ROTATE_DELAY_S` apart
([protocol.md](protocol.md), "The address a caller is given"). For every
`https` URL it builds a TLS connection with chain and hostname verification
off. **It checks the peer
certificate's SHA-256 digest against `fp` immediately after the handshake,
before any request bytes leave the machine.** An `https` URL with no
fingerprint to pin is not connected to at all, and the TLS floor is 1.2, set
explicitly on the client context.

A mismatch closes the socket and aborts the whole enrolment loudly, with no
move to the next address. Something answering with the wrong certificate is
being impersonated, and moving on quietly hides that.

`POST /api/channel/join` is admitted by `protocol` first, so a rejected
protocol spends no ticket. Then the hub spends the ticket **atomically**: it
is removed from the store in the same step that fetches it (`dict.pop`), then
judged. Expired and unknown read identically as 401 `ticket_spent`, so two
machines racing one link cannot both join.

A ticket generated for a device names its row. A blank ticket is matched to
the row whose `machine_id` the request names, or a new row is created. The
`machine_id` decides **which row**, never **whether**. The ticket is the whole
authenticator, which is why a link is treated like a password and lasts five
minutes.

The reply is `{id, token}`, the token `secrets.token_urlsafe(24)` (192 bits).
The agent stores `{gateway_url, id, token, fingerprint, machine_id}` in its
binding file, root-owned mode 0600, and a file missing any field is an
unbound agent. Beside them it stores `gateway_urls`, the link's set at first
and the `urls` of the last state afterwards; a file with none holds
`[gateway_url]`. `nagent leave` posts `{id, token}` to `/api/channel/leave` and
deletes the file; the hub keeps the device's row and its
`config/devices/<id>/`, which only the Devices page's remove deletes.

## Every later connection

The socket and `leave` each open a fresh pinned connection, and the
fingerprint is checked on **every** connection. The token is in the `hello`
or in the body. The hub looks the token up with `secrets.compare_digest`,
constant-time, against every stored token of that role. Nothing about an
agent is trusted from its network position; the token is the entire identity.

## What a refusal means to the agent

A refusal at the door keeps the binding. The agent records it as
`last_error`, `nagent status` says which no is being heard, and the agent
sends `hello` again a minute later. The one refusal that unbinds is
`binding_unknown`, which only the hub holding the pinned certificate can say.
The agent then deletes its binding file and is bound again by a fresh link.

Admission by `PROTOCOL`, the two protocol codes, the close codes and the
upgrade an agent performs when `welcome` names a newer `software` are in
[protocol.md](protocol.md), "Admission and the binding".

## What an attacker in each position gets

**On the wire, or owning the network** (ARP, DHCP, DNS, a squatted IP): they
can answer the agent port, and the handshake completes, but they cannot
present a certificate whose DER digests to the pinned value without the
private key, so the agent hangs up having sent nothing. Pinning an exact
identity is stronger here than a CA chain: there is no authority to mis-issue,
only a second preimage to find. Downgrade is closed the same way: the
binding's URLs came out of a link the hub generated, are `https` by
construction, `http.client` follows no redirects, and https-without-a-pin
is not connected to.

**Holding a captured link**: an unspent link within its five minutes joins
their machine as the device the link was generated for; the link *is* the
credential. Everything narrows that window: one outstanding ticket, five
minutes, single atomic spend, and the SSH install path generating and spending
in the same action. A spent or replaced link is dead.

**Impersonating an agent** without a token: enrolment needs the one live
ticket; a `hello` needs 192 bits through a constant-time compare. Neither is
guessable, and the transport gives nothing away to help.

**Replay**: enrolment is replay-proof at the application layer, because the
ticket dies on first spend. A `hello` has no nonce on purpose: every
connection is a fresh TLS handshake with fresh keys, so a captured frame can
neither be read nor re-sent (no 0-RTT early data exists on this stack), and
the only party able to replay plaintext already holds the token, to whom a
replay adds nothing. An application nonce defends only against an attacker
who can already strip TLS, who fails the fingerprint check first.

**A local account on the managed machine**: the control socket is 0600 under
a 0700 directory, so the kernel rejects their connection before a request is
read. A website in their browser gets nothing at all: the agent listens on no
local port, so there is nothing for a cross-site form to post to.

**Rooting the hub box** is outside the model: the key, the vault and the
panel all live there. The panel port itself is plain HTTP unless its HTTPS is
turned on, by [architecture.md](architecture.md)'s local-trust decision; the
agent channel is hardened separately because it crosses networks the panel
never does.

## Atomicity is a rule, not a habit

Everything the channel and the panel mutate follows two laws:

- **On disk**: every `config/` write goes through `write_config`, a
  temporary file in the same directory, then `os.replace`, so a crash
  mid-write cannot leave a truncated file.
- **In the process**: every mutation takes the one `CONFIG_WRITE_LOCK`
  (re-entrant, in `utils/json_file.py`), **re-reads its file inside the
  lock**, applies the change, and writes, never writing a snapshot taken
  before somebody else's change. One global lock instead of one per file,
  because references cross files (a provider names a vault object, a device
  names a key) and a composite operation must nest under a single lock to
  be one step. Reads take no lock; a stale read is tolerable, a lost write
  is not. In-memory stores spend-and-judge in one operation, the way the
  enrolment ticket is popped before it is inspected.

The reason it is a law: the panel's sync routes run concurrently in a thread
pool, and a report writes the same file a rename on the panel writes. The
read-modify-write that loses is the one that read before the lock.
