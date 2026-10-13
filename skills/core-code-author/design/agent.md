# The device agent

The agent is the hub's presence on a managed Linux, Windows or macOS
machine: one root service with one socket open to the hub. It hosts the
modules the hub's state names, reports what is true, and shares the
machine's desktop when told. It draws no window, and the only ports it
listens on are the forwarders in front of the programs run as an account,
CloudCLI, code-server and Codeg, on `127.0.0.1`
([modules/template.md](agent/modules/template.md), "The run"). Its own
code is pure standard library. The
package includes the interpreter that runs it, so it installs on a machine
with no Python and touches none the machine already has.

Everything a person does with what the hub publishes belongs to the client,
a separate package in that person's own session
([architecture.md](architecture.md), "The shape of the system"). The client
also joins the hub's virtual network as an ordinary peer, through the NetBird
and EasyTier daemons its own package registers as services. A terminal it
opens on a managed machine is a `shell` stream the hub bridges to that
machine's agent, the same shell the panel's terminal reaches; a command it
runs there is an `exec` stream bridged the same way; and every other
connection it makes to a service on a machine is a `connect` stream
the hub relays to that machine's agent. This page is
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
  Podman, ZFS, VS Code, code-server, CloudCLI, Codeg, and the two the
  agent's own package carries, Terminal and Remote desktop, of four kinds
  ("The four kinds of module"). The hub says what is wanted and sends
  the bytes; the agent observes, installs and configures. A device's Modules
  page writes one `want` per module into `config/devices/<id>/modules.json`.
  The state the agent receives names, per module, that `want`, the
  configuration, and the install and uninstall recipes for its platform
  ([protocol.md](protocol.md), "The channel").
- **Services** are what the hub publishes and what a client consumes: a web
  link, a port, the AI gateway, a share, a shared desktop. The agent composes
  none of them and renders none of them. Its only part is the one entry a
  machine declares once its Remote desktop module serves
  ([modules/remote_desktop.md](agent/modules/remote_desktop.md)).

The machine's AI tools are neither: a setting the hub sends and the agent
makes true for the accounts it names ([ai_tools.md](agent/ai_tools.md)).

| The hub may | Root on the machine may |
| --- | --- |
| Push the state and open `shell`, `exec`, `file`, `command` and `connect` streams | Bind the machine to a hub, or unbind it |
| Say which modules are absent, installed, stopped or running, and configure them | Send a report now (`nagent sync`) |
| Reboot, shut down, reinstall the agent | |
| Read and set up a person's own AnyDesk or TeamViewer | Read the binding and status |
| | Start and stop the agent's service |

Root is uid 0. `nagent` refuses any other account, with two exceptions:
`nagent --version`, and `nagent answer`, which the agent runs as an account
on Windows ([ai_tools.md](agent/ai_tools.md)).

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

The hub opens `shell`, `exec`, `file`, `command` and `connect` streams to an agent;
the agent opens `log` and `package` streams to the hub. A `command` names a
module and a verb (`{agent, reboot}`, `{samba, reload}`, `{zfs,
validate}`). Every stream sits behind a credit window, so a long transfer
never starves the reader, and a stream's result is its close.

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
failed module is tried again only when its own entry in the state changes,
and until then the report says why with a code. **An edit to a module of an
offline device is rejected with `agent_offline`, never queued**: the person
is told the machine is away, and asks again when it is back.

**One module at a time.** The agent applies the modules a state mentions one
after another, in the fixed order `APPLY_ORDER` names: ZFS, the file share,
Terminal, Gitea, Containers, VS Code, code-server, CloudCLI, Codeg, Remote
desktop.
While it applies one, each other module whose `want` differs from its last
reported state reports `queued`, until the agent reaches it.

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
code and is not repeated while its entry in the state is unchanged; trying
again is a person's word, never a timer's.

**A retry is the same press again.** The agent tries each module's entry
once and keeps, for each module and for the `ai_tools` section, the hash of
the entry it tried on disk, so a restart does not try it again. The mark
holds for one install and one binding: `nagent service uninstall`, which
every package's removal runs, deletes it, and so do a join and a leave, so
the next agent that holds the same state applies it again after a removal
undid it. An upgrade replaces the package without either and applies
nothing again. When a
person presses a module's own action again on a module whose last report is
`failed`, the hub writes a fresh `retry_mark` into that module's entry of
the state. The mark means nothing to the agent; it changes that entry's
hash, so the hash the agent tried for that module no longer matches and that
module alone is tried again. A change to one module's entry, or a mark on it,
never runs another module's failed step again.
The machine's AI tools take the same mark on the `ai_tools` section when a
press asks again while an account's result is `failed`. A press on a module
that did not fail writes no mark and asks for nothing new.

Software somebody installs or removes by hand is displayed, never fought. A
hand-installed Samba reports `installed`; its shares and users become the
hub's configuration at the machine's first report on a socket, and the
first **Configure** imports them when that report found none
([protocol.md](protocol.md), "The modules section"). A failure
exists only in the report, and a hub restart loses nothing, because `want` is
in `config/`. Machinery whose only purpose is surviving a restart is removed
on sight ([../kill_on_sight.md](../kill_on_sight.md), "Unasked survival
machinery").

The file share's own rules, what it changes on each system and what a
removal of the agent leaves, are
[modules/file_share.md](agent/modules/file_share.md).

`nagent service uninstall` stops the agent's service first and disables it
(the Linux unit disabled, the macOS job unloaded, the Windows service's start
type `disabled`), as the package's own removal leaves it, so no apply of its
own runs beside what follows and nothing starts it at the next boot; then it
switches every account's AI tools
back ([ai_tools.md](agent/ai_tools.md)) and removes the copy of cc-switch it
ran, before it removes anything else.

**Status is typed.** A module reports `state`, `is_active` and
`{code, params}`, never an English sentence, and every surface does its own
wording. The agent's `error` section crosses the socket the same way, so a
device that is unhappy says why on the panel. Module states are one closed
table on every surface:

| Steady | Transient | Shared |
| --- | --- | --- |
| `absent`, `installed`, `stopped`, `running` | `installing`, `uninstalling`, `queued` | `failed`, `unsupported` |

`installed` is present and never configured by the hub; `stopped` and
`running` are configured by the hub and told apart by the unit; `installing`
also covers a module's own install that runs inside its apply or as a task
the apply left running, and a state waiting on such a task is applied again
every 30 seconds under the same hash until the task ends. `queued` is a
module the agent reaches after the one it is applying ("One module at a
time").

**An install that leaves nothing behind ends absent.** An install that fails
on a machine where the module's check then finds nothing installed reports
`absent` with the failure's `{code, params}`, never `failed`, and the agent
deletes its tried hash for that module, so the next install of the same entry
runs. The hub drops the module's `want` and its retry mark
([protocol.md](protocol.md), "The modules section"), and **Install** is the
next press, a fresh install. A step that fails on a module the machine has
(start, stop, configure, uninstall) reports `failed` and keeps it. No button
cancels a step.

A surface that meets a token outside the state table shows "waiting for the
agent", the word for a machine that has not reported. Wherever a state is
drawn:

- Every transient token is in the surface's busy set, or a row mid-step
  offers the opposite button.
- A surface's optimistic step after a press holds until the machine reports
  the module in a state other than the one it showed at the press, at most
  two minutes; then the machine's own report, or its silence, takes over.
- A new `code` arrives with its wording in the same change, which the
  catalog completeness test enforces.

## The four kinds of module

Every module is of one of four kinds, and the kind decides what the
machinery does for it and what the module itself supplies. The whole flow,
from the manifest to the published entry, is
[modules/template.md](agent/modules/template.md); each module's own page
is linked from the table.

| Kind | Modules | Install | Run |
| --- | --- | --- | --- |
| carried by the agent | [Terminal](agent/modules/terminal.md), [Remote desktop](agent/modules/remote_desktop.md), which also detects a person's own AnyDesk and TeamViewer | nothing: the agent's package holds what each needs, on every system | the module's own applier per system |
| installed from the system's own sources | [File share](agent/modules/file_share.md), [Containers](agent/modules/containers.md), [ZFS storage](agent/modules/zfs.md) | the system's package manager, by the `system_package` recipe; on Windows and macOS the file share drives the system's SMB server and installs nothing | the module's own applier |
| a service with a system account of its own | [Gitea](agent/modules/gitea.md) | the release binary from the hub's cache, down `package {module}` | the account and the service the module makes, in the publisher's layout on every system |
| a program run as a person's account | [VS Code](agent/modules/vscode.md), [code-server](agent/modules/code_server.md), [CloudCLI](agent/modules/cloudcli.md), [Codeg](agent/modules/codeg.md) | each component from the hub's cache, down `package {module, component}`, unpacked and sealed under `agent/<module>/<component>/` | one account service per instance, the forwarder in front of it, one `web` entry per running instance |

An install is the hub's cache and the agent's unpack. For the two kinds the
hub fetches, the cache fetches each archive the manifest names, checks it
against the pinned sha256 and streams it down `package`; the agent unpacks
it under the state root into a directory of the module's own name, one
subdirectory per component, sealed read-only to every account and on no
`PATH`, and runs the manifest's `verify` command. A module from the
system's own sources asks the hub for no bytes: the platform installs the
named packages with its own tooling. Terminal and Remote desktop install
nothing: their manifests name the tier `agent`, their state entries name no
recipe, they are never in the Modules page's picker, always a tab, and take
none of the four presses ([protocol.md](protocol.md), "The modules section,
one entry per module"); the hub composes both from their own files under
`config/devices/<id>/`, not from `modules.json`.

A run is the module's own applier for the first three kinds, one per system
where the systems differ, under `modules/<module>/`: the agent's code for
the two it carries is `modules/terminal/` and `modules/remote_desktop/`,
each with its config, constants and runner, the latter with one applier per
system (`linux_applier.py`, `windows_applier.py`, `darwin_applier.py`) and
`rdp/` under it, which keeps the seat and RustDesk's settings files; their
constants carry the prefixes `TERMINAL_` and `REMOTE_DESKTOP_`, and the hub
names the modules `DEVICE_TERMINAL_MODULE` and `DEVICE_REMOTE_DESKTOP_MODULE`.
A program run as a person's account keeps `config.py`, `constants.py` and
`hooks.py` under `modules/<module>/` and nothing else:
`modules/shared/instances.py` runs every instance through the module's
hooks, the account service layer
`modules/shared/account_service/`, one file per system, writes the service
definition and starts, stops, removes and queries it, and
`modules/shared/http_forward.py` is in front of each instance on
`127.0.0.1`. `modules/shared/` is the one package of what every module
runner shares, each file one concept.

## The connect stream

A `connect {port, protocol}` stream is one TCP connection the hub relays
for a client to a service on this machine, or, with `protocol` `udp`, every
datagram of one UDP entry ([protocol.md](protocol.md), "The connect
stream"); `protocol` absent means `tcp`. For TCP the agent dials
`127.0.0.1:<port>`, within `AGENT_CONNECT_DIAL_TIMEOUT_S`, and relays bytes
both ways under credit until either socket ends. It serves only a port the
machine publishes at that moment on the stream's protocol:

| Published while | The port |
| --- | --- |
| the file share reports a share | 445, the SMB port |
| the desktop is shared | the RustDesk direct port the `desktop` section reports |
| the Gitea module reports its URL | that URL's port |
| a VS Code, code-server, CloudCLI or Codeg instance is configured | the instance's port |
| a running Podman container publishes a host port | that port on the protocol it is published on, dialled on the host address it is published on when it names one; a stopped container's ports are not published, so a stream on one ends `port_not_published` within a second of the stop |

Every other port in the table is published on TCP alone. Any other port,
and a number published on the other protocol alone, is refused
`port_not_published {port}` and nothing is dialled. A dial that fails closes
the stream `connect_failed {reason}`, `reason` being `refused`, `timeout` or
`unreachable`.

What the Podman report gives this stream is
[modules/containers.md](agent/modules/containers.md).

A UDP stream keeps a table from each datagram's `source` to one UDP socket
connected to the target, `127.0.0.1` or the address the binding names, so
it reads only the target's replies:

| Rule | Value |
| --- | --- |
| a datagram whose `source` has no socket | gets one; a reply read from a source's socket goes into the stream with that `source` |
| a source with no datagram either way | its socket is closed and forgotten after `AGENT_UDP_IDLE_TIMEOUT_S`, 60 seconds; a later datagram gets a new one |
| sources one stream keeps | at most `AGENT_UDP_SOURCES_MAX`, 64; one more replaces the one idle the longest |
| an error on a source's socket | loses that datagram alone, and the stream stays open |
| a datagram without the credit its frame needs | dropped, with no wait and no queue; credit taken is granted back once a datagram is passed on or dropped |
| the stream's end | none while idle; it ends with the hub's close, the hub's socket, or `port_not_published {port}` once the port is no longer published |

The two constants have the hub's values ([protocol.md](protocol.md), "The
timings"); the agent imports nothing from the hub.

A machine's own services stay reachable on its LAN at their own ports, under
each service's own login ([connection.md](connection.md), "One port, one
connection"), and each also answers the agent's dial on loopback:

| Service | Where it listens |
| --- | --- |
| Samba on Linux | every address; `hosts allow` names the networks the hub composed and `127.0.0.1` |
| the file share on Windows and macOS | the system's SMB server on every address; the fence blocks every network outside the composed ones and leaves `127.0.0.0/8` and `::1` out of what it blocks |
| Gitea | every address (`HTTP_ADDR = 0.0.0.0`); on Windows the system firewall decides who on the LAN reaches it, and the module opens no port in it |
| RustDesk's direct port | every address, as RustDesk opens it; the share is declared once the port answers on `127.0.0.1` |
| a Podman container's published port | every address, or the one address it is published on, which the agent dials |
| VS Code | `127.0.0.1` alone |
| the CloudCLI, code-server and Codeg forwarders | `127.0.0.1` alone, in front of CloudCLI and Codeg on loopback and code-server on its account's socket |

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
| `start`, `stop` | start and stop the agent's service through systemd, the service control manager or launchd; the binding is not touched |
| `run` | the foreground entry systemd and launchd start; `service run` is Windows' |
| `answer --prompt <text> --answer <keys> -- <program…>` | starts the program on a terminal of its own, types the keys and Enter once the text shows, prints what the terminal drew, and exits with the program's code; it does not reach this socket, and any account may run it ([ai_tools.md](agent/ai_tools.md)) |

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
([privilege.md](privilege.md)). That reach is three things. One is the seat
whose desktop is shared, whose RustDesk configuration lives in that
account's own session. Another is the programs run as an account, VS Code,
code-server, CloudCLI and Codeg, whose instances the account service layer,
`modules/shared/account_service/`, starts through the system's own service
manager: a systemd unit with `User=` on Linux, a LaunchDaemon with
`UserName` on macOS, and on Windows a scheduled task registered with the
account's login, because LocalSystem cannot start a process as another
account without its password. Every instance listens on `127.0.0.1` alone
and the module opens no port in any firewall, since the hub reaches it
through the agent's `connect` stream
([modules/template.md](agent/modules/template.md), "The run"). The third is the
machine's AI tools, pointed at the gateway by cc-switch run as each account
([ai_tools.md](agent/ai_tools.md)). The fourth is a terminal or a command for
the account the Terminal module names, on Linux and macOS: the shell, or the
command an
`exec` stream names, runs through the platform's step-down with that
account's home and environment, the shell as a login shell on a
pseudo-terminal the agent makes. Everything else the agent does is root's
own work.

## The platform layer

`neutrino_agent/platforms/` holds one class per platform behind one
contract: `linux.py`, `windows.py` and `darwin.py`, and `detect_platform`
returns the one for the running system. The contract names intents, not
mechanisms: enumerate human accounts, resolve an account's home, run a
process as an account, control the agent's own service, power actions, read
host metrics, read the machine's interfaces, read the machine id, install and
remove a package of a kind, and where the agent keeps its state and its work.

A platform advertises the capabilities it has; invoking an absent one is
refused with `{"code": "unsupported_platform"}`, never guessed at. Every
system has `run_as`: the contract's `run_as_account`, and
`run_as_account_answering` for a program that reads a reply from its
terminal, each done the way the "Running as an account" row below says.
Linux and macOS also have `account_shell`, the contract's `account_process`,
which hands back how a long-lived process starts as an account by the same
step-down without running it; the shell stream starts the Terminal
module's shell for an account with it. The engine
builds the package-backed runners only on a platform with `packages`. A
platform with `smb_server` gets the file share, driving the SMB server the
system carries, with nothing to install or uninstall; there, any other
module the state names reads `unsupported`, never `failed`, beside the
Terminal and Remote desktop rows every platform has. A platform with
`hub_packages` gets Gitea and the programs run as an account, VS Code,
CloudCLI and Codeg, and macOS code-server beside them; on Linux all of them
are among the runners `packages` builds. On every system, software the hub
sends down a package stream is unpacked into a directory of the module's
own name under the state root, one subdirectory per component, cc-switch into
`ai_tools/bin/`, and that directory alone is opened to every account to read and run: mode 755, and on Windows
read and execute for the Users group. Every import
only POSIX has is guarded, so one package imports on all three systems.

| | Linux | Windows | macOS |
| --- | --- | --- | --- |
| Program | `/opt/neutrino/agent` | `C:\Program Files\Neutrino\agent` | `/Library/Application Support/Neutrino/agent/app` |
| Configuration root: the binding, the credentials, the desired state | `/etc/neutrino/agent` | `%ProgramData%\Neutrino\agent\config`, under `%ProgramData%\Neutrino\agent`, whose ACL, SYSTEM and the administrators alone, the `.msi` sets | `/Library/Application Support/Neutrino/agent/config`, mode 700 |
| State root: configured marks, packages, the last reinstall, `vscode/`, `code_server/`, `cloudcli/`, `codeg/`, `ai_tools/`, and on Windows and macOS `gitea/` and `gitea_data/` | `/var/lib/neutrino/agent` | `%ProgramData%\Neutrino\agent\state` | `/Library/Application Support/Neutrino/agent/state`, mode 755 |
| Log | the journal | `%ProgramData%\Neutrino\agent\log\agent.log` | `/Library/Logs/Neutrino/agent/agent.log` |
| Service | systemd `neutrino_agent.service` runs `nagent run` | the `neutrino_agent` service, LocalSystem, runs `nagent service run` | the `com.neutrino.agent` LaunchDaemon runs `nagent run` |
| Control transport | Unix socket `/run/neutrino/agent/agent.sock` | named pipe `\\.\pipe\neutrino_agent`, its descriptor SYSTEM and the administrators | Unix socket `/var/run/neutrino/agent/agent.sock` |
| Metrics | `/proc`, `/sys`, `nvidia-smi` | kernel32 `GetSystemTimes`, `GlobalMemoryStatusEx`, `GetTickCount64` and the system drive; per-core CPU and the process table from `NtQuerySystemInformation`, rated against the previous report; GPUs from `nvidia-smi` where it is installed, else the PDH counters `GPU Engine` (the busiest engine type per adapter, the way Task Manager reads it) and `GPU Adapter Memory`, with the adapter's name and total memory from the graphics kernel (`D3DKMTEnumAdapters2`, `D3DKMTQueryAdapterInfo`); a temperature from WMI `MSAcpi_ThermalZoneTemperature` through the PowerShell host where the firmware exposes one, else none; no load average | `host_statistics`, `vm_stat`, `sysctl` and `/`; per-core CPU from `host_processor_info`; the process table from `ps -axo pid,user,%cpu,%mem,comm`, the command last so `ps` does not cut it; GPUs from the `PerformanceStatistics` of `ioreg -r -c IOAccelerator`; a temperature from `powermetrics --samplers smc`, which root may run |
| Interfaces | `ip -j addr` | `GetAdaptersAddresses` through iphlpapi, loopback and tunnel adapters left out | `ifconfig -a` |
| Machine id | `/etc/machine-id` | the registry's `MachineGuid` | `IOPlatformUUID` from `ioreg` |
| Accounts | uid 1000 and above with a login shell | the enabled local accounts from `NetUserEnum`, without Administrator, Guest, DefaultAccount, WDAGUtilityAccount and the file share's own; the home is the `ProfileImagePath` under the account's SID in the registry's `ProfileList` | `dscl`, uid 501 and above, home under `/Users` |
| Power | `systemctl reboot` or `poweroff --force` | `shutdown /r` or `/s /t 0` | `shutdown -r` or `-h now` |
| Running as an account | `runuser -u <account> --`, with the account's home and environment; an answered run on a pseudo-terminal the agent makes | a one-shot scheduled task `neutrino_run_as_<account>`, registered through the PowerShell host with the login the Credentials page holds for the account's instance and a limited token, started in the account's profile; its script, standard input, output and exit code are files in `state\run_as\<account>\`, whose ACL grants the account modify and SYSTEM and the administrators full control; the task and the files are removed once the exit code is read, and an uninstall removes a task or files a stopped run left; a login Windows rejects at registration (`0x8007052E`) is `credential_invalid {account}`, an account with no login `credential_missing {account}`; an answered run is `nagent answer` inside the task | a child process with the account's uid and group and no other groups, in its home, with `HOME`, `USER` and `LOGNAME` set; an answered run on a pseudo-terminal the agent makes |
| Refused | nothing | packages | packages |
| Kill | SIGTERM, then SIGKILL after two seconds | `OpenProcess` with `PROCESS_TERMINATE` and `TerminateProcess` | SIGTERM, then SIGKILL after two seconds |
| Shell stream, the Terminal module's settings empty | the login shell on a pseudo-terminal, which is its controlling terminal so a resize reaches it as `SIGWINCH`, started in root's home | PowerShell on a pseudo console, in a job that kills it on close, started in the signed-in account's profile directory, and in the system drive's root when nobody is signed in or the profile cannot be found (a domain account, a directory that is not there), never in the service's own directory | `zsh -il` on a pseudo-terminal, its controlling terminal as on Linux, started in root's home |
| Seat | `loginctl`, `/proc/net/tcp`, the Wayland token | the console session's user through WTS, `netstat` | the system configuration's console user, `State:/Users/ConsoleUser` through `scutil`, the login window, root and no name being nobody, and the owner of `/dev/console` only when `scutil` cannot be asked, since under auto-login that owner stays root while a person is signed in; `netstat`; the privacy grants |
| Shell stream, the Terminal module's account set | `runuser -u <account> -- <shell> -l` on the pseudo-terminal, started in the account's home with its environment | no account: SYSTEM, as above, with the module's shell program | the account's uid and group in the child, its home, `HOME`, `USER` and `LOGNAME`, `<shell> -l` |
| RustDesk, the agent's copy | `/usr/lib/neutrino/agent/rustdesk/rustdesk`; with the switch on the agent writes `/etc/systemd/system/rustdesk.service`, which overrides upstream's packaged `rustdesk.service` under `/usr/lib/systemd/system`, and enables and starts it; off, it disables it and deletes the file; `kept/service.json` records whether a packaged `rustdesk.service` was enabled and active, and a unit file of that name in `/etc` that is not the agent's is moved to `kept/`. The host is stopped with `systemctl kill`, never `systemctl stop` of upstream's unit, whose `ExecStop` is `pkill -f "rustdesk --"` and ends a person's viewers too. Upstream's own package deletes `/etc/systemd/system/rustdesk.service` when it is installed, upgraded or removed, so doing that while the switch is on takes the agent's registration away until the switch is applied again | `C:\Program Files\Neutrino\agent\rustdesk\rustdesk.exe` with its files; the service `RustDesk`, `AUTO_START` as LocalSystem, its `ImagePath` `"<copy>" --service`, created when none exists; `kept\service.json` holds a service found before (its `ImagePath`, start type and whether it ran); the service's configuration is read from the service control manager, and RustDesk's processes from the process table | `/Library/Application Support/Neutrino/agent/app/rustdesk/RustDesk.app`; `/Library/LaunchDaemons/com.carriez.RustDesk_service.plist`, label `com.carriez.RustDesk_service`, the copy's `Contents/MacOS/service`, system domain; `/Library/LaunchAgents/com.carriez.RustDesk_server.plist`, label `com.carriez.RustDesk_server`, the copy's `Contents/MacOS/RustDesk --server`, `LimitLoadToSessionType` `Aqua` and `LoginWindow`, `RunAtLoad`, `KeepAlive` true; files found under those names are moved to `kept/` first |
| RustDesk's settings | root's and the seat's `~/.config/rustdesk/RustDesk2.toml` and `RustDesk.toml` | LocalService's `C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\RustDesk2.toml` and `RustDesk.toml` | root's and the seated account's `~/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml` and `RustDesk.toml` |
| File share | Samba, `smb.conf` rendered whole | the SMB server through the PowerShell host, one function per operation and the password inside the request: shares whose description starts `neutrino:`, local accounts in no group, hidden from the sign-in screen and denied the console and RDP through `LsaAddAccountRights`, folders granted with `icacls`, and the block rule `neutrino_smb_fence` for TCP 445 from every address outside the allowed subnets | Apple's smbd through `launchctl enable` and `kickstart`: share points made with `sharing` under the record prefix `neutrino_`, SMB only, no guest, no encryption; accounts made with `sysadminctl` without a shell or a home, hidden, in `com.apple.access_smb` where it exists, the NT hash turned on before `dscl -passwd`; folders granted with `chmod +a`; the pf sub-anchor `com.apple/neutrino_smb`, loaded from a file under the state root at every apply and when the agent starts |
| VS Code | the CLI in `/var/lib/neutrino/agent/vscode`, the unit `neutrino_vscode@<account>.service` with `User=`, environment and token files in `/var/lib/neutrino/agent/vscode/tokens`, and `/etc/sysctl.d/90-neutrino-vscode.conf` when the machine's inotify watch or instance limit is under the module's floor (524288 and 512), since a served home directory runs a distribution's default out | the CLI in `%ProgramData%\Neutrino\agent\state\vscode`, the task `neutrino_vscode_<account>` registered with the account's login, at startup, no time limit, a limited token; a stop ends the task's whole process tree, so the port is free for the next start | the CLI in `/Library/Application Support/Neutrino/agent/state/vscode`, the LaunchDaemon `com.neutrino.vscode.<account>` with `UserName` |
| Self-update | `systemd-run` of `dpkg` or `dnf` | a detached PowerShell running `msiexec` | `launchctl submit` of `installer`. On every system the package the hub streamed is renamed from its temporary name to the file name its release gave it, which the hub sends with the stream, before the installer sees it: Windows Installer reinstalls a product only from a file named as the one it was installed from. A refused reinstall ends with its code on the output's last line and a non-zero exit. An install that goes through restarts the agent, so the hub's task ends when the agent is back on the channel and has reported the install's result, and that result is the task's exit |

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
256 KB, and sends it first to a stream that attaches, with every
sequence that asks the terminal to answer taken out (device attributes,
status, mode, version and capability requests, window reports, OSC
queries), since a terminal answers each one again and the answer lands on
the shell's line. Any number of streams
attach to one shell at once: each receives all the output, input from any
reaches the shell, and the terminal takes the smallest window's size. A
shell that `persist` marked persistent or shared keeps running when its last
stream closes; any other ends with it. The agent keeps the `owner` the hub
stamped on the open as given. The report's `machine` section lists every
kept shell, and the process holds them, so a restart ends them all ([protocol.md](protocol.md), "The
verbs on a `command` stream").

**A command runs once and is never kept.** An `exec {argv, is_tty, cols,
rows}` stream runs `argv` as given, with no shell between, as the account a
new shell would run as: the Terminal module's account through the same
step-down as its shell, in that account's home with its environment, else
root in root's home, and on Windows SYSTEM in the directory the "Shell
stream" row names. The module's shell program is not read. An empty `argv`,
or one whose program the agent cannot find on the `PATH` the process gets or
cannot run, is refused `shell_program_unusable {path}` before anything
starts, and an account the machine does not have `account_unknown
{account}`, as for a shell ([protocol.md](protocol.md), "The exec stream").

| `is_tty` | The agent |
| --- | --- |
| false | starts the process with stdin, stdout and stderr on three pipes; reads stdout and stderr apart and sends each on its own `fd`, `1` and `2`, under the hub's credit; writes the frames up to stdin in order and closes stdin on the `eof` frame; closes with `params: {exit_code}` once the process ended and both pipes reached end of file |
| true | runs `argv` on the pseudo-terminal path a shell takes, a pseudo console on Windows, at `cols` by `rows`, every frame down `fd` `1`; ignores `eof`; closes with `params: {exit_code}` once the process ends |

The exit code is the process's own, or 128 plus the signal's number when a
signal ended it. A stream the hub closes first ends the process and
everything it started, as a shell's end does. An `exec` keeps no session id,
no output and no place in the report's `sessions`.

### Which modules each system runs

A module runs on a system when its manifest has a branch for the machine's
platform and the machine's `version` is not below that branch's
`min_version` ([protocol.md](protocol.md), "The modules section, one entry
per module"). The Modules page greys out every other module in its picker
and never shows it as a tab. The agent's minimum system stays where it is; a
module a system cannot run is left out on that system.

| Module | Linux | Windows | macOS |
| --- | --- | --- | --- |
| [File share](agent/modules/file_share.md) | Samba | the system's own SMB server | the system's own SMB server |
| [Gitea](agent/modules/gitea.md) | amd64 and arm64 | amd64 | arm64 and amd64 |
| [Containers](agent/modules/containers.md) (Podman) | yes | no | no |
| [ZFS storage](agent/modules/zfs.md) | yes | no | no |
| [VS Code](agent/modules/vscode.md) | amd64 and arm64 | amd64 | arm64 and amd64 |
| [code-server](agent/modules/code_server.md) | amd64 and arm64 | no | arm64 and amd64 |
| [CloudCLI](agent/modules/cloudcli.md) | amd64 and arm64 | amd64 and arm64 | arm64 and amd64 |
| [Codeg](agent/modules/codeg.md) | glibc 2.34, the agent's own floor, amd64 and arm64 | amd64 | arm64 and amd64 |
| [Terminal](agent/modules/terminal.md) | yes | the shell program alone | yes |
| [Remote desktop](agent/modules/remote_desktop.md) (the agent's RustDesk; the detection of a person's own AnyDesk or TeamViewer runs on every system) | yes | amd64 | yes |

A module's log, the answer to its `journal` verb, is the journal of its
systemd units on Linux. Windows and macOS run no module under a unit, so
each module there reads its own sources first and then the agent's own log
lines that name the module, from `agent.log` under the log root (the rotated
`agent.log.1` read before it) on Windows and
`/Library/Logs/Neutrino/agent/agent.log` on macOS; the agent's lines take at
most half the box, and a box is empty only while the agent has logged
nothing about the module. Which sources a module reads there is on its own
page: [file_share.md](agent/modules/file_share.md),
[gitea.md](agent/modules/gitea.md), [vscode.md](agent/modules/vscode.md),
[code_server.md](agent/modules/code_server.md),
[cloudcli.md](agent/modules/cloudcli.md) and
[codeg.md](agent/modules/codeg.md).
A source that cannot be read leaves one line in the agent's log naming it,
so the next journal shows why. `journal` answers while an apply runs; it
does not wait for the state to settle. Every log comes oldest line first,
at most the number of lines the verb asked for. A journal never shows a
secret: a token in a URL (`?tkn=`) or on a line of its own is masked before
the text leaves the agent, and a reinstall's output goes through the same
mask.

The hub's own machine on macOS and Windows runs the local agent
`nhub setup` installs ([install_and_dev.md](install_and_dev.md)), so its
shares and VS Code are that agent's modules, as on any device.

Each module's own page is under `agent/modules/`, linked from the table of
"The four kinds of module", and the flow they share is
[modules/template.md](agent/modules/template.md).

### The PowerShell host on Windows

The PowerShell host is one `powershell.exe` that the agent keeps as its
child on Windows to run cmdlets and WMI queries. Starting `powershell.exe`
and loading a cmdlet's module costs about half a second of CPU, and more
where antivirus scans every new process. The agent therefore starts one host
and keeps it, and reads interfaces, accounts, processes and services through
Win32 in its own process.

| Work on Windows | Runs in |
| --- | --- |
| The scheduled tasks: registering one with an account's password, starting, stopping and deleting it, reading its state and last result, and the one-shot task that runs a program as an account | the host |
| The file share: the shares and their access, the share accounts with their sign-in denial and hiding, the fence rule, the passwords, the server log | the host |
| The thermal zones, read from WMI | the host |
| The uninstall's cleanup of what the agent added under its prefix | the host |
| The interfaces, the accounts and their homes, whether an instance's own process listens on its port, RustDesk's service configuration and processes, a file read as an account | the agent's own process, through Win32 with ctypes |
| Granting a folder to accounts | `icacls.exe`, started directly |
| The self-update | a detached PowerShell of its own, which outlives the service |
| The terminal's shell | PowerShell on a pseudo console, one per shell |

The agent starts the host on the first request and talks to it over the
host's inherited standard input and output alone. No other account on the
machine holds those handles. A password the agent sets or registers
therefore reaches the host inside a request, never on a command line
([privilege.md](privilege.md)).

Each request is one JSON line, `{id, op, args}`, and each answer one line
with the request's `id` and the host's `private_bytes`. A result comes back
as `ok: true, value`, a refusal as `ok: false, kind: "refusal", code, params`,
and an error as `ok: false, kind: "error", message`. Requests run one at a
time, each under its own timeout. A timeout or a broken pipe fails the request and ends
the host, and the next request starts a new one.

The function library, `neutrino_agent/data/windows/powershell_host.ps1`,
holds one function per operation and no `exit`, because an `exit` ends the
host. Every request runs in the host's one runspace, and a function returns
a refusal as a value.

The host runs in a job object the agent holds, so Windows kills it when the
agent stops. The agent stops the host after 10 minutes without a request,
and once it has read an answer that reports `private_bytes` over 200 MB. The
ceiling bounds the modules cmdlets load, which stay in the host's memory
until the host exits.

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
([network.md](hub_components/network.md), "Outside Linux, the system firewall").

## Joining: one ticket, thirty minutes, spent in one step

Generation happens on the panel port, behind the session: the Devices page's
per-device link, the blank link `nhub setup` prints, and the SSH install
action all call one path. A ticket is `secrets.token_urlsafe(18)`
(144 bits), dead after **thirty minutes**, `ENROLLMENT_TTL_S`. It is on
disk as its SHA-256 from the moment it is made, in
`<state>/enrollment_tickets.json`, mode 0600, and the ticket itself is
written nowhere ([protocol.md](protocol.md), "The hub group"). That is long
enough to walk to another machine, or to raise a network on a phone, and
short enough that a forgotten link is not a standing invitation.

**Generating replaces whatever ticket of its kind was out**: there is
exactly one open device invitation and one open client invitation at a time.
The machine the link was made for is the only one that can join, and
refreshing the page quietly retires the link before it. A hub restart keeps
an open ticket: the hub reads the file back when it starts and drops the
entries past their expiry.

The link is `neutrino://enroll/<base64url payload>`, the payload one JSON
object written with no spaces, compressed with zlib and encoded base64url
without padding ([protocol.md](protocol.md), "The link and the two
endpoints"); `nagent join` inflates it before it reads:

```json
{"urls": ["https://192.168.93.1:8443", "..."], "token": "...", "fp": "<sha256 hex>", "role": "agent"}
```

`urls` is every exposed address on the agent port, because only one of them
is on the joining machine's network and neither end knows which. The link
`nhub setup` makes for the hub's own agent names `https://127.0.0.1:<agent-port>`
first and the exposed addresses after it, so that agent joins over loopback
even when nothing is exposed, and every state the hub sends it keeps loopback
first in `urls`. A client
link is the same object with `"role": "client"`, generated on the Clients
page; the client rejects a device link and the agent a client one. The
base64url alphabet holds no character a shell splits or a URL escapes, so the
link pastes anywhere unquoted.

The agent tries each URL in turn, at enrolment and on every reconnect, from
the start: the name `hub.neutrino.internal` where the network resolves it,
then the set in the hub's order, `AGENT_ROTATE_DELAY_S` apart. The address
that answered last is not preferred, and while the socket is connected
nothing moves it
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
protocol spends no ticket. Then the hub spends the ticket **atomically**:
the entry with the ticket's hash leaves the file and the memory in the same
step that fetches it, then it is judged. Expired and unknown read identically as 401 `ticket_spent`, so two
machines racing one link cannot both join.

A ticket generated for a device names its row. A blank ticket is matched to
the row whose `machine_id` the request names, or a new row is created. The
`machine_id` decides **which row**, never **whether**. The ticket is the whole
authenticator, which is why a link is treated like a password and lasts
thirty minutes.

The reply is `{id, token}`, the token `secrets.token_urlsafe(24)` (192 bits).
The agent stores `{gateway_url, id, token, fingerprint, machine_id}` in its
binding file, root-owned mode 0600, and a file missing any field is an
unbound agent. Beside them it stores `gateway_urls`, the link's set at first
and the `urls` of the last state afterwards; a file with none holds
`[gateway_url]`. `nagent leave` posts `{id, token}` to `/api/channel/leave` and
deletes the file; the hub keeps the device's row and its
`config/devices/<id>/`, which only the Devices page's remove deletes.

`nagent join` and `nagent leave` run in their own process and reach a
running service through the binding file, not by restarting it: the
service reads the file's stamp at every report while connected and every two
seconds while it waits between attempts, a failing hub's backoff included,
so a new binding is taken within seconds. Taking it drops the old socket and
starts a round from the top of the new binding's addresses.

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
The agent then deletes its binding file, switches the AI tools back, turns
the desktop share off
([modules/remote_desktop.md](agent/modules/remote_desktop.md), "The desktop
is the hub's order") and is bound again
by a fresh link.

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

**Holding a captured link**: an unspent link within its thirty minutes joins
their machine as the device the link was generated for; the link *is* the
credential. Everything narrows that window: one outstanding ticket of each
kind, thirty minutes, single atomic spend, and the SSH install path generating and spending
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
read. The agent's only local ports are the CloudCLI, code-server and Codeg
forwarders on `127.0.0.1`, which answer 401 to a request carrying neither a
token the hub minted nor a login the forwarder set, so neither the account
nor a website in their browser reaches an instance through them.

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
