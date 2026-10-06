# The device agent

The agent is the hub's presence on a managed Linux, Windows or macOS
machine: one root service with one socket open to the hub. It hosts the
modules the hub's state names, reports what is true, and shares the
machine's desktop when told. It draws no window, and the only ports it
listens on are the forwarders of CloudCLI and code-server, on `127.0.0.1`
("CloudCLI" and "code-server" below). Its own code is pure standard
library. The
package includes the interpreter that runs it, so it installs on a machine
with no Python and touches none the machine already has.

Everything a person does with what the hub publishes belongs to the client,
a separate package in that person's own session
([architecture.md](architecture.md), "The shape of the system"). The client
also joins the hub's virtual network as an ordinary peer, through the NetBird
and EasyTier daemons its own package registers as services. A terminal it
opens on a managed machine is a `shell` stream the hub bridges to that
machine's agent, the same shell the panel's terminal reaches, and every
other connection it makes to a service on a machine is a `connect` stream
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
  Podman, ZFS, VS Code, code-server, CloudCLI, and the two the agent's own
  package carries, Terminal and Remote desktop. The hub says what is wanted and sends
  the bytes; the agent observes, installs and configures. A device's Modules
  page writes one `want` per module into `config/devices/<id>/modules.json`.
  The state the agent receives names, per module, that `want`, the
  configuration, and the install and uninstall recipes for its platform
  ([protocol.md](protocol.md), "The channel").
- **Services** are what the hub publishes and what a client consumes: a web
  link, a port, the AI gateway, a share, a shared desktop. The agent composes
  none of them and renders none of them. Its only part is the one entry a
  machine declares once its Remote desktop module serves, described below.

The machine's AI tools are neither: a setting the hub sends and the agent
makes true for the accounts it names ("The machine's AI tools").

| The hub may | Root on the machine may |
| --- | --- |
| Push the state and open `shell`, `file`, `command` and `connect` streams | Bind the machine to a hub, or unbind it |
| Say which modules are absent, installed, stopped or running, and configure them | Send a report now (`nagent sync`) |
| Reboot, shut down, reinstall the agent | |
| Read and set up a person's own AnyDesk or TeamViewer | Read the binding and status |
| | Start and stop the agent's service |

Root is uid 0. `nagent` refuses any other account, with two exceptions:
`nagent --version`, and `nagent answer`, which the agent runs as an account
on Windows ("The machine's AI tools").

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

The hub opens `shell`, `file`, `command` and `connect` streams to an agent;
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

**A retry is the same press again.** The agent tries a state once and keeps
the hash it tried on disk, so a restart does not try it again. The mark
holds for one install and one binding: `nagent service uninstall`, which
every package's removal runs, deletes it, and so do a join and a leave, so
the next agent that holds the same state applies it again after a removal
undid it. An upgrade replaces the package without either and applies
nothing again. When a
person presses a module's own action again on a module whose last report is
`failed`, the hub writes a fresh `retry_mark` into that module's entry of
the state. The mark means nothing to the agent; it changes the state's hash,
so the hash the agent tried no longer matches and the state is tried again.
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

The file share on Windows and macOS is the one module that changes what the
person set up. On Linux it owns the whole `smb.conf`; on Windows and macOS it
owns who reaches the system's SMB server. It changes only the shares and
accounts it made, the ones its record under the state root lists and its
marker names, but its fence covers every share on the machine, the person's
own included.

Removing the agent's package takes away what the agent added in order to
run and to fence, and leaves what the machine serves. On every system the
shares and the accounts stay as they are and the system's SMB server goes on
serving them. The agent's own units, scheduled tasks, firewall rules and
fence go with the package, and so do its modules' Windows services, found
by name as the rest are. An agent installed again finds the shares and
accounts that were left and takes them back by the rule above: they are
displayed, and the first report imports them.

`nagent service uninstall` stops the agent's service first, so no apply of
its own runs beside what follows, then switches every account's AI tools
back ("The machine's AI tools") and removes the copy of cc-switch it ran,
before it removes anything else.

**Status is typed.** A module reports `state`, `is_active` and
`{code, params}`, never an English sentence, and every surface does its own
wording. The agent's `error` section crosses the socket the same way, so a
device that is unhappy says why on the panel. Module states are one closed
table on every surface:

| Steady | Transient | Shared |
| --- | --- | --- |
| `absent`, `installed`, `stopped`, `running` | `installing`, `uninstalling` | `failed`, `unsupported` |

`installed` is present and never configured by the hub; `stopped` and
`running` are configured by the hub and told apart by the unit; `installing`
also covers a module's own install that runs inside its apply or as a task
the apply left running, and a state waiting on such a task is applied again
every 30 seconds under the same hash until the task ends. A surface
that meets a token outside this table shows "waiting for the agent", the word
for a machine that has not reported. Wherever a state is drawn:

- Every transient token is in the surface's busy set, or a row mid-step
  offers the opposite button.
- A surface's optimistic step holds at most two minutes before the machine's
  own report, or its silence, takes over.
- A new `code` arrives with its wording in the same change, which the
  catalog completeness test enforces.

## The two modules the agent carries

Terminal and Remote desktop are modules with nothing to install: the
agent's package carries what each needs, on every system. Their manifests
name the tier `agent`, and their state entries name no recipe. They are
never in the Modules page's picker, always a tab, and take none of the four
presses ([protocol.md](protocol.md), "The modules section, one entry per
module"). The hub composes both from their own files under
`config/devices/<id>/`, not from `modules.json`. The agent's code is
`modules/terminal/` and `modules/remote_desktop/`, each with its config,
constants and runner, and the latter with one applier per system
(`linux_applier.py`, `windows_applier.py`, `darwin_applier.py`); `rdp/`
keeps the seat and RustDesk's settings files. Their constants carry the
prefixes `TERMINAL_` and `REMOTE_DESKTOP_`, and the hub names the modules
`DEVICE_TERMINAL_MODULE` and `DEVICE_REMOTE_DESKTOP_MODULE`.

**Terminal** holds two settings: the account a `shell` stream runs as, and
the path of the shell program. Both empty is the shell the platform table's
"Shell stream" row names, run as the agent runs. A shell opened afterwards,
from the panel or from a client, runs as the module says; a session already
open keeps what it runs, and a container's shell is not touched. A named
account the machine does not have refuses the open `account_unknown
{account}`, and a shell path that is missing or not executable
`shell_program_unusable {path}`; neither falls back to root or to the
default. A shell for an account starts in that account's home with that
account's environment, through `run_as_account`'s step-down ("Acting for an
account"), on a pseudo-terminal of its own as before, which is handed to
that account. On Linux and macOS the module's shell program starts as a
login shell, `<program> -l`, as the agent or as the account alike; an
account with no program named gets its own login shell. On Windows this
version sets the shell program alone: the hub sends no account, and the
shell runs as SYSTEM.

**Remote desktop** holds one switch, off on a new machine. It is the one
place a desktop share is decided: the hub writes it, the state carries it,
and the agent makes it true and keeps it true across a restart of the
machine. `nagent rdp start` and `nagent rdp stop` are gone, from the command
line and from the control socket.

## The desktop is the hub's order

With the switch on, the agent takes the machine's RustDesk over and runs its
own copy, the one in its package (the platform table's "RustDesk" row),
under RustDesk's own service names:

1. It stops RustDesk's service and session jobs and kills every RustDesk
   host on the machine whose program is not its copy. A process started with
   `--connect` is a viewer a person may be using and is left alone.
1. It keeps aside whatever is registered under RustDesk's service names and
   is not its own (a person's own RustDesk), in `remote_desktop/kept/` under
   the state root, and records what it registers in
   `remote_desktop/registered.json`.
1. It writes the settings files with the host stopped: the direct
   connection on port 21118, the rendezvous and relay servers set to the
   machine's own loopback, `127.0.0.1`, because an empty value means
   upstream's public server; and the seat password as `password = '<p>'` in
   the service's own `RustDesk.toml`, since `--password` from a copy outside
   the standard place sets nothing. The seat's host takes the password from
   the service and keeps it in the seat's `RustDesk.toml` in its own
   encrypted form, so the agent writes no password there. Every file it
   writes is copied to `kept/` before its first write and put back when the
   switch goes off.
1. It registers and starts its copy under RustDesk's names, as the
   platform table's "RustDesk" row says for each system, so the system's own
   service manager brings the host back after a restart and at each login.

With the switch off, the agent's copy does not run: it stops and removes
what `registered.json` names, kills every host of its copy, puts back what
`kept/` holds and starts it again when it ran before. No RustDesk process of
the agent's and no registration of the agent's is left. A person's own
RustDesk files are never changed or deleted. `nagent service uninstall`
turns the switch off first.

A failed step reports the module `failed` with `rdp_takeover_failed {step,
detail}` on the way on, or `rdp_restore_failed {step, detail}` on the way
off; the same press again tries it again ("A retry is the same press
again").

**The seat password is the hub's.** A machine whose switch is on is given
one, generated once and sealed under the vault's data key in that device's
`rdp.json`. It is delivered in the `desktop` section of the state. The agent
writes it into RustDesk's settings whenever it changed and keeps it in a
root-only file so it knows what it already set. It enters neither the
agent's store nor any report.

The panel never shows it: the device drawer offers **Reset seat password**,
which generates a new one and disconnects every viewer. A client that presses
**Connect** opens a `service` stream, the hub unseals the password for that
one close, and the viewer is spawned with it.

**What leaves the machine.** With the rendezvous and relay servers on the
loopback the host sends nothing to RustDesk's servers. One thing remains
that no option of RustDesk 1.4.9 turns off: when its server starts on a
machine with a global IPv6 address, it asks three public STUN servers
(`stun.l.google.com`, `stun.cloudflare.com`, `stun.nextcloud.com`) for
that address, and on every machine it looks their names up. The request
carries no id and registers nothing.

**A share is declared only once it listens.** RustDesk's root service holds
no port of its own; it spawns a second process into the session of whoever
is logged in at the seat, and that process is what listens. The agent reads
the system's socket table, as the platform table's "Seat" row does, for its
copy listening on 21118; it opens no connection to the host. So a machine
with nobody logged in has nothing listening, which `rdp_nobody_seated`
refuses in front of, and a Wayland session that has not granted screen
capture reports `rdp_screen_not_allowed` instead of a desktop nobody can
see. Whose desktop a peer sees is whoever sits at the screen; the report's
`account` names them and decides nothing.

**A share made by the old command is kept.** An agent of a version that had
`nagent rdp start` recorded a share in its store. The package that upgrades
it takes away the RustDesk the old package installed at the system's
standard place, so the agent, when it starts and finds that record, takes
the machine's RustDesk over with its own copy as the switch's way on does,
and until the first state that names `remote_desktop` it keeps that share
running and reports it.
A hub that receives `desktop.is_shared` true from a device with no
`remote_desktop.json` writes the switch on for it, so an upgrade closes no
share.

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
| a VS Code, code-server or CloudCLI instance is configured | the instance's port |
| a Podman container publishes a host port | that port on the protocol it is published on, dialled on the host address it is published on when it names one |

Every other port in the table is published on TCP alone. Any other port,
and a number published on the other protocol alone, is refused
`port_not_published {port}` and nothing is dialled. A dial that fails closes
the stream `connect_failed {reason}`, `reason` being `refused`, `timeout` or
`unreachable`.

The Podman report gives each container's `host_bindings` as one `{address,
port, protocol}` per published host port, on TCP and UDP alike, `address`
empty for every address; `published_ports` reads the ports the machine
publishes, per protocol, from it.

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
| the CloudCLI and code-server forwarders | `127.0.0.1` alone, in front of CloudCLI on loopback and code-server on its account's socket |

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
| `answer --prompt <text> --answer <keys> -- <program…>` | starts the program on a terminal of its own, types the keys and Enter once the text shows, prints what the terminal drew, and exits with the program's code; it does not reach this socket, and any account may run it ("The machine's AI tools") |

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
account's own session. Another is VS Code, whose servers run as the
accounts the module names, each started by the system's own service
manager: a systemd unit with `User=` on Linux, a LaunchDaemon with
`UserName` on macOS, and on Windows a scheduled task registered with the
account's login, because LocalSystem cannot start a process as another
account without its password. Every server listens on `127.0.0.1` alone and
the module opens no port in any firewall, since the hub reaches it through
the agent's `connect` stream. CloudCLI and code-server are reached the same
way ("CloudCLI" and "code-server" below). The third is the machine's AI
tools, pointed at the gateway by cc-switch run as each account ("The
machine's AI tools"). The fourth is a terminal for the account the Terminal
module names, on Linux and macOS: the shell runs through the platform's
step-down with that account's home, environment and login shell, on a
pseudo-terminal the agent makes. Everything else the agent does is root's
own work.

## The machine's AI tools

The `ai_tools` section of the state says whether the machine's AI tools use
the hub's gateway, and for which accounts ([protocol.md](protocol.md), "The
sections"). It is a setting, not a module: nothing is installed, started or
stopped, and it has no `want`. The agent makes it true and reports each
account's result in the `ai_tools` section of its report.

The accounts are the hub's word: every account with an instance in the
machine's VS Code, code-server or CloudCLI configuration. The agent looks
nothing up and adds no account of its own.

For each account the state names while the section is on, the agent runs
the client's steps as that account, with the copy of cc-switch the agent
fetched from the hub ([modules/ai.md](modules/ai.md), "How a client points its tools at
the gateway", and "How a managed machine's tools are pointed at the
gateway" for what differs). An account whose records already carry the
wanted settings is not run again. An account is switched back by the same
steps as the client's deactivation:

- when the section turns off, or the state names it no longer;
- by `nagent service uninstall`, once the agent's service has stopped and
  before anything is removed;
- on `nagent leave`, and when a refusal of `binding_unknown` ends the
  binding ("What a refusal means to the agent").

`nagent leave` and `nagent service uninstall` print one line per account
they switched back, `ai tools   <account>: <state> <code>`, and the agent
package's removal on Linux shows what both print.

**cc-switch comes from the hub when it is needed.** The agent's package
does not carry it. While the section is on and names an account, the agent
needs a copy of the version the section's `cc_switch_version` names. When
it has none, or one of another version, it opens `package {module:
cc_switch}` ([protocol.md](protocol.md), "The stream layer"), checks the bytes
against the `sha256` the close names, unpacks the `cc-switch` at the
archive's top (`cc-switch.exe` on Windows) into `ai_tools/bin/` under the
state root, and writes the version beside it in `version`, replacing a copy
of another version whole. The directory is root's own: every account may
read and run what is in it and none may write it, as with any software the
hub sends ("The platform layer"). A switch back while the section is off
runs whatever copy is there, and fetches the version the section names when
none is. A download or an unpack that fails gives every
account the section names, and every account it would switch back, `failed`
with `cc_switch_download_failed {detail}`, runs nothing, and leaves the
state to be tried again at the next state or the next retry.

The records are the client's, one per tool, `{is_present, previous, added}`,
kept under the state root in `ai_tools/<account>/<tool>.json`, root's own,
never in the account's home. cc-switch keeps its own store in the account's
home, as on a person's computer. An account whose records are all gone after
a switch back has its directory removed.

**The account's own files come back byte for byte.** Before a tool's first
switch, its record also keeps `is_dir_present`, whether the tool's
directory was there, and `kept`, the text of every file a switch may write
in it, read as the account, or null for one that was absent: Claude Code's
`~/.claude/settings.json`, Codex's `~/.codex/config.toml` and `auth.json`,
and Gemini's `~/.gemini/.env` and `settings.json`. cc-switch writes a tool's
files only into a directory that is there, so a switch makes the directory,
as the account, for a tool that has none, and every tool the log names as
switched has its files written and read back naming the hub. The switch
back, once cc-switch has switched away and deleted the hub's provider,
writes each kept file back as it was, takes away each that was absent, and
takes away a directory the switch made once it is empty. A switch back that
cannot run cc-switch, or cannot read its list of providers, is the
account's `failed` with `switch_failed {account, detail}`, and the records,
with the kept files, stay for the next try.

Each account's switch or switch back holds that account's lock from its
first step to its last: the file `ai_tools/.locks/<account>` under the state
root, locked with `flock` on Linux and macOS and `msvcrt.locking` on
Windows, so the service and a `nagent leave` or `nagent service uninstall`
never run cc-switch for one account at once, nor replace each other's
one-shot task on Windows. A run that finds the lock held waits up to five
minutes and then fails as `switch_failed` with the detail `another run holds
the account`, and since the system frees a lock when its process ends, a
file a killed process left behind blocks no one. Holding the lock, the agent
makes no switch once the machine has no binding: `nagent leave` and a
`binding_unknown` refusal remove the binding before they switch back, so a
service that waited on the lock finds none and switches nothing.

**Every step in an account's home runs as that account, reads included.**
cc-switch runs as the account, with the account's home and its own
environment ("Running as an account" in the platform table), and so does
each file step of the client's sequence: reading a tool's file, writing
Codex's effort into `config.toml`, removing a file cc-switch made. An
account can replace any file in its home with a link to a file only root
reads, so a read made as root would hand that file to cc-switch and through
it back to the account. On Linux and macOS the file steps are `cat`,
`test -f`, `sh -c` writing what arrives on standard input, and `rm -f`; on
Windows each is one PowerShell script in the account's task, the path
written into it as a literal.

`config common extract` and `config common set` read their input from a
file. The agent writes that input as the account to `payload` in the
account's own tree, `~/.local/share/neutrino/agent/ai_tools/` on Linux,
`~/Library/Application Support/Neutrino/agent/ai_tools/` on macOS and
`%LOCALAPPDATA%\Neutrino\agent\ai_tools\` on Windows, making the
directories it lacks. It runs the one cc-switch call that reads the file,
and straight after removes it as the account, then each of `ai_tools`,
`agent` and the Neutrino directory that is left empty, in that order, so an
account that had no Neutrino tree has none afterwards. The file holds a
tool's live configuration in the shape `extract` reads, or the shared
settings `set` stores ([files.md](files.md), "One root, three names").

**The delete is answered on a terminal.** `provider delete` prints `(y/N)`
and reads the reply from its terminal; with a pipe on its standard input it
exits with `The input device is not a TTY`, and no flag stands in for the
reply. On Linux and macOS the agent makes a pseudo-terminal itself, starts
cc-switch on it as the account, and types `y` and Enter once the prompt
shows. On Windows the agent reaches an account only through a scheduled
task, so the terminal is made inside that task: the task runs
`nagent answer --prompt "(y/N)" --answer y -- <cc-switch> --app <tool>
provider delete neutrino`, `<cc-switch>` being the path of the agent's own
cc-switch and `<tool>` the tool, and the agent's own program makes a pseudo
console there, starts cc-switch on it, types the reply, and prints what the
console drew.

On macOS a program is put in an account's GUI session as the account by
`launchctl asuser <uid> <nagent> step-down --uid <uid> --gid <gid> --
<program>`: `launchctl` starts the agent's own program in the session, and
`step-down` sets the account's group as its only supplementary group, then
its group, then its user, and replaces itself with the program. It opens
no socket and reads no state. `chroot -u` is not used: macOS kills a
program with the hardened runtime under it. A command that does not start,
or exits other than 0, leaves one line in the agent's log.

`answer` is the one `nagent` verb any account may run. It starts the
program it is given as the account that runs it, with that account's
rights and no other; it reads no binding, opens neither the control socket
nor a socket to the hub, and changes nothing the account could not change by
running the program itself.

**Windows keeps the login until the switch back.** A task runs as an account
only with the account's password, and the state carries each account's login
only while the section is on. The agent therefore keeps the login an account
was switched with in `ai_tools/<account>/login.json` under the state root,
readable by SYSTEM and the administrators alone as everything under
`%ProgramData%\Neutrino\agent` is ([files.md](files.md)), and deletes it with
the account's records. Every switch back reads it from there: after the
section turns off, after the account leaves the list, at an uninstall, at a
leave.

The report names each account the state names and each one switched back
under the current state's hash, `{account, state, code, params}`, `state`
being `switched`, `switched_back` or `failed`. A failure carries the client's
code where it fits, `switch_failed {account, detail}`, the download's
`cc_switch_download_failed {detail}`, and the module codes for an account it
cannot run as:
`account_unknown {account}`, and on Windows `credential_missing {account}`
and `credential_invalid {account}`. A failed account is not tried again
while the state's hash is unchanged, as a failed module is not.

After the agent restarts it reports each account whose records stand as
`switched` until a new state arrives, and acts on no state whose hash it
already tried, so a restart switches nothing and switches nothing back.

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
Terminal and Remote desktop rows every platform has. A platform with `hub_packages` gets the Gitea and
VS Code modules, and macOS the code-server module beside them; on Linux all
three are among
the runners `packages` builds. On every
system, software the hub sends down a package stream is unpacked into a
directory of the module's own name under the state root, cc-switch into
`ai_tools/bin/`, and that directory alone is opened to every account to read and run: mode 755, and on Windows
read and execute for the Users group. Every import
only POSIX has is guarded, so one package imports on all three systems.

| | Linux | Windows | macOS |
| --- | --- | --- | --- |
| Program | `/opt/neutrino/agent` | `C:\Program Files\Neutrino\agent` | `/Library/Application Support/Neutrino/agent/app` |
| Configuration root: the binding, the credentials, the desired state | `/etc/neutrino/agent` | `%ProgramData%\Neutrino\agent\config`, under `%ProgramData%\Neutrino\agent`, whose ACL, SYSTEM and the administrators alone, the `.msi` sets | `/Library/Application Support/Neutrino/agent/config`, mode 700 |
| State root: configured marks, packages, the last reinstall, `vscode/`, `code_server/`, `cloudcli/`, `ai_tools/`, and on Windows and macOS `gitea/` and `gitea_data/` | `/var/lib/neutrino/agent` | `%ProgramData%\Neutrino\agent\state` | `/Library/Application Support/Neutrino/agent/state`, mode 755 |
| Log | the journal | `%ProgramData%\Neutrino\agent\log\agent.log` | `/Library/Logs/Neutrino/agent/agent.log` |
| Service | systemd `neutrino_agent.service` runs `nagent run` | the `neutrino_agent` service, LocalSystem, runs `nagent service run` | the `com.neutrino.agent` LaunchDaemon runs `nagent run` |
| Control transport | Unix socket `/run/neutrino/agent/agent.sock` | named pipe `\\.\pipe\neutrino_agent`, its descriptor SYSTEM and the administrators | Unix socket `/var/run/neutrino/agent/agent.sock` |
| Metrics | `/proc`, `/sys`, `nvidia-smi` | kernel32 `GetSystemTimes`, `GlobalMemoryStatusEx`, `GetTickCount64` and the system drive; per-core CPU and the process table from `NtQuerySystemInformation`, rated against the previous report; GPUs from `nvidia-smi` where it is installed, else the PDH counters `GPU Engine` (the busiest engine type per adapter, the way Task Manager reads it) and `GPU Adapter Memory`, with the adapter's name and total memory from the graphics kernel (`D3DKMTEnumAdapters2`, `D3DKMTQueryAdapterInfo`); a temperature from WMI `MSAcpi_ThermalZoneTemperature` through PowerShell where the firmware exposes one, else none; no load average | `host_statistics`, `vm_stat`, `sysctl` and `/`; per-core CPU from `host_processor_info`; the process table from `ps -axo pid,user,%cpu,%mem,comm`, the command last so `ps` does not cut it; GPUs from the `PerformanceStatistics` of `ioreg -r -c IOAccelerator`; a temperature from `powermetrics --samplers smc`, which root may run |
| Interfaces | `ip -j addr` | one PowerShell call joining `Get-NetAdapter` to `Get-NetIPAddress`, read at most every 30 seconds | `ifconfig -a` |
| Machine id | `/etc/machine-id` | the registry's `MachineGuid` | `IOPlatformUUID` from `ioreg` |
| Accounts | uid 1000 and above with a login shell | the enabled local accounts from `Get-LocalUser`, without Administrator, Guest, DefaultAccount, WDAGUtilityAccount and the file share's own, read at most every 30 seconds; the home is the profile `Win32_UserProfile` names | `dscl`, uid 501 and above, home under `/Users` |
| Power | `systemctl reboot` or `poweroff --force` | `shutdown /r` or `/s /t 0` | `shutdown -r` or `-h now` |
| Running as an account | `runuser -u <account> --`, with the account's home and environment; an answered run on a pseudo-terminal the agent makes | a one-shot scheduled task `neutrino_run_as_<account>`, registered with the login the Credentials page holds for the account's instance and a limited token, started in the account's profile; its script, standard input, output and exit code are files in `state\run_as\<account>\`, whose ACL grants the account modify and SYSTEM and the administrators full control; the task and the files are removed once the exit code is read, and an uninstall removes a task or files a stopped run left; a login Windows rejects at registration (`0x8007052E`) is `credential_invalid {account}`, an account with no login `credential_missing {account}`; an answered run is `nagent answer` inside the task | a child process with the account's uid and group and no other groups, in its home, with `HOME`, `USER` and `LOGNAME` set; an answered run on a pseudo-terminal the agent makes |
| Refused | nothing | packages | packages |
| Kill | SIGTERM, then SIGKILL after two seconds | `OpenProcess` with `PROCESS_TERMINATE` and `TerminateProcess` | SIGTERM, then SIGKILL after two seconds |
| Shell stream, the Terminal module's settings empty | the login shell on a pseudo-terminal, which is its controlling terminal so a resize reaches it as `SIGWINCH`, started in root's home | PowerShell on a pseudo console, in a job that kills it on close, started in the signed-in account's profile directory, and in the system drive's root when nobody is signed in or the profile cannot be found (a domain account, a directory that is not there), never in the service's own directory | `zsh -il` on a pseudo-terminal, its controlling terminal as on Linux, started in root's home |
| Seat | `loginctl`, `/proc/net/tcp`, the Wayland token | the console session's user through WTS, `netstat` | the system configuration's console user, `State:/Users/ConsoleUser` through `scutil`, the login window, root and no name being nobody, and the owner of `/dev/console` only when `scutil` cannot be asked, since under auto-login that owner stays root while a person is signed in; `netstat`; the privacy grants |
| Shell stream, the Terminal module's account set | `runuser -u <account> -- <shell> -l` on the pseudo-terminal, started in the account's home with its environment | no account: SYSTEM, as above, with the module's shell program | the account's uid and group in the child, its home, `HOME`, `USER` and `LOGNAME`, `<shell> -l` |
| RustDesk, the agent's copy | `/usr/lib/neutrino/agent/rustdesk/rustdesk`; with the switch on the agent writes `/etc/systemd/system/rustdesk.service`, which overrides upstream's packaged `rustdesk.service` under `/usr/lib/systemd/system`, and enables and starts it; off, it disables it and deletes the file; `kept/service.json` records whether a packaged `rustdesk.service` was enabled and active, and a unit file of that name in `/etc` that is not the agent's is moved to `kept/`. The host is stopped with `systemctl kill`, never `systemctl stop` of upstream's unit, whose `ExecStop` is `pkill -f "rustdesk --"` and ends a person's viewers too. Upstream's own package deletes `/etc/systemd/system/rustdesk.service` when it is installed, upgraded or removed, so doing that while the switch is on takes the agent's registration away until the switch is applied again | `C:\Program Files\Neutrino\agent\rustdesk\rustdesk.exe` with its files; the service `RustDesk`, `AUTO_START` as LocalSystem, its `ImagePath` `"<copy>" --service`, created when none exists; `kept\service.json` holds a service found before (its `ImagePath`, start type and whether it ran) | `/Library/Application Support/Neutrino/agent/app/rustdesk/RustDesk.app`; `/Library/LaunchDaemons/com.carriez.RustDesk_service.plist`, label `com.carriez.RustDesk_service`, the copy's `Contents/MacOS/service`, system domain; `/Library/LaunchAgents/com.carriez.RustDesk_server.plist`, label `com.carriez.RustDesk_server`, the copy's `Contents/MacOS/RustDesk --server`, `LimitLoadToSessionType` `Aqua` and `LoginWindow`, `RunAtLoad`, `KeepAlive` true; files found under those names are moved to `kept/` first |
| RustDesk's settings | root's and the seat's `~/.config/rustdesk/RustDesk2.toml` and `RustDesk.toml` | LocalService's `C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\RustDesk2.toml` and `RustDesk.toml` | root's and the seated account's `~/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml` and `RustDesk.toml` |
| File share | Samba, `smb.conf` rendered whole | the SMB server through one PowerShell script per operation, JSON in and out and the password on standard input: shares whose description starts `neutrino:`, local accounts in no group, hidden from the sign-in screen and denied the console and RDP through `LsaAddAccountRights`, folders granted with `icacls`, and the block rule `neutrino_smb_fence` for TCP 445 from every address outside the allowed subnets | Apple's smbd through `launchctl enable` and `kickstart`: share points made with `sharing` under the record prefix `neutrino_`, SMB only, no guest, no encryption; accounts made with `sysadminctl` without a shell or a home, hidden, in `com.apple.access_smb` where it exists, the NT hash turned on before `dscl -passwd`; folders granted with `chmod +a`; the pf sub-anchor `com.apple/neutrino_smb`, loaded from a file under the state root at every apply and when the agent starts |
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
| Gitea | amd64 and arm64 | amd64 | arm64 and amd64 |
| Containers (Podman) | yes | no | no |
| ZFS storage | yes | no | no |
| VS Code | glibc 2.28 and above, amd64 and arm64 | amd64 | arm64 and amd64 |
| code-server | glibc 2.28 and above, amd64 and arm64 | no | arm64 and amd64 |
| CloudCLI | glibc 2.28 and above, amd64 and arm64 | amd64 and arm64 | arm64 and amd64 |
| Terminal | yes | the shell program alone | yes |
| Remote desktop (the agent's RustDesk) | yes | amd64 | yes |
| A person's own AnyDesk or TeamViewer | yes | yes | yes |

A module's log, the answer to its `journal` verb, is the journal of its
systemd units on Linux. Windows and macOS run no module under a unit, so
each module there reads its own sources first and then the agent's own log
lines that name the module, from `agent.log` under the log root (the rotated
`agent.log.1` read before it) on Windows and
`/Library/Logs/Neutrino/agent/agent.log` on macOS; the agent's lines take at
most half the box, and a box is empty only while the agent has logged
nothing about the module. The file share reads the SMB server's latest
events from `Microsoft-Windows-SMBServer/Operational` on Windows, or what the
unified log holds of `smbd` over the last 15 minutes on macOS. VS Code,
code-server and CloudCLI read the end of each instance's log file: on
Windows the task runs the CLI through `cmd.exe`, which appends its output
to `<account>.log` beside the CLI, and a CloudCLI install still running
shows `run\install_<account>.log`; on macOS the LaunchDaemon's
`StandardOutPath` and `StandardErrorPath` name
`/Library/Logs/Neutrino/agent/<module>_<account>.log`, `<module>` being
`vscode`, `code_server` or `cloudcli`. Gitea on Windows and macOS reads the
end of its own log, `log/gitea.log` under its data directory.
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

A VS Code instance listens on `127.0.0.1` alone, on every system. A client
reaches it through a `connect` stream ("The connect stream"), and its token
is what admits a browser.

On a Mac the connections land in the `RustDesk --server` job of the signed-in
session (the LaunchAgent `com.carriez.RustDesk_server`), not in the root
service alone. That job takes its configuration from the root service once,
when it starts, and from then on pushes what it holds in memory back to the
service whenever that changes, so a file written under a running job is
overwritten within a second. So the host configures a Mac by booting out
the job and then the service, writing both copies, and bootstrapping the
service and then the job. The two plists keep upstream's labels, under
which the root helper answers the session's host; under a label of the
agent's own the host logs that it cannot reach `ipc_service`. The session
plist's `KeepAlive` is true, so the host comes back after macOS quits and
reopens it for the Screen Recording grant, and launchd starts both at boot
and at each login from `/Library/LaunchDaemons` and `/Library/LaunchAgents`,
the only folders it reads. The share is declared only once the direct port
listens, as everywhere.

A Mac shows a peer nothing until RustDesk holds both screen recording and
accessibility, which only somebody at that Mac grants, and the privacy
database that records them is closed to root, so the seat does not read it:
its attention is empty. Instead, the switch turning on puts a dialog on
that Mac's screen, in the signed-in
session through `step-down` ("Acting for an account"), naming the two
permissions, and opens the Screen Recording pane of the system settings;
RustDesk is
started whether or not the person has granted them yet. The hub's `rdp`
entry carries the machine's `platform_os`, and a client shows a standing
hint under a Mac's entry ([client.md](client.md)).

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
`SERVER_PORT` (CloudCLI's own name for its port) and `PATH`. Nothing is
inherited from a login profile or a version manager, and nothing names the
gateway. The tools CloudCLI starts read the account's own files: Claude
Code its `~/.claude/settings.json`, Codex its `~/.codex/auth.json` and
`~/.codex/config.toml`. Pointing those at the gateway is the machine's AI
tools setting ("The machine's AI tools").

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
better-sqlite3, node-pty or bcrypt cannot fetch its prebuilt binary; both
npm codes carry `detail`, the last lines prebuild-install, node-gyp and npm
wrote. node-pty and bcrypt carry their binaries inside their npm packages;
better-sqlite3 fetches its own, from where the state's `npm_environment`
says ("Where each edition fetches from" in
[install_and_dev.md](install_and_dev.md)).

**npm cannot take the agent down.** On Linux an account's npm runs in a
transient scope of its own, `neutrino_cloudcli_install_<account>.scope`,
and the agent's unit has `OOMPolicy=continue`. When the kernel kills the
install for want of memory, the install ends
`cloudcli_install_out_of_memory {account}` and the agent keeps running. A
failed install is tried again only with a state of another hash, and the
hash last tried is kept on disk, so an agent that starts again does not try
it again either.

**The install's state is `installing` until it ends.** On Linux and macOS
npm runs inside the apply; on Windows the apply starts the install task and
leaves it running (four hours at most), reads its state on every apply, and
starts no instance until it has ended; an ended task is judged by its
result and by the app directory holding the package and the three native
modules, then unregistered. The hub publishes an instance's `web` entry
only while the device reports it running.

**The agent's forwarder stands in front of CloudCLI.** CloudCLI listens on
loopback alone. A thin HTTP forwarder of the agent's listens on
`127.0.0.1` at the configured port, where the agent's end of a `connect`
stream reaches it. The hub generates each
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

### code-server

The `code_server` module runs code-server, the browser build of VS Code
that Coder publishes (MIT), once per account on Linux and macOS. Its
extensions come from Open VSX, code-server's own default gallery. It is
an ordinary module shaped like CloudCLI,
`agent/neutrino_agent/modules/code_server/` with its config, constants,
runner, installer, forwarder and one applier per system, and its
configuration is `{instances: [{account, port, secret}]}`. Its manifest has
no Windows branch, so the Modules page greys it out on Windows.

**It runs as the account, never as root**: a unit
`neutrino_code_server@<account>.service` with `User=<account>` on Linux, and
a LaunchDaemon `com.neutrino.code_server.<account>` with `UserName` on
macOS. Its settings and extensions are in code-server's own directories
under the account's home.

**The release comes from its publisher.** `data/manifests/code_server.json`
pins the standalone release for Linux and macOS on amd64 and arm64, each
with its url and sha256, at the source the edition names. In `cn` the
installer tries the pinned version at the mirror and checks its sha256; when
the mirror no longer carries it, the installer takes the mirror's current
release, checked by HTTPS alone, and `details` name the version installed
([install_and_dev.md](install_and_dev.md), "Where each edition fetches
from"). The module's installer fetches the archive into the module cache and sends it down
`package {module: code_server}`. The agent unpacks it under its state root,
`/var/lib/neutrino/agent/code_server/` on Linux and `/Library/Application
Support/Neutrino/agent/state/code_server` on macOS: owned by root, read-only
to every account, one copy per machine, never on `PATH`. The release
includes its own Node.js.

**code-server listens on a socket only its account opens.** The service
runs `code-server --auth none --socket <run-dir>/code_server.sock
--socket-mode 600 --disable-telemetry --disable-update-check`, where
`<run-dir>` is `code_server/run/<account>/` under the state root, owned by the
account, mode 700. Root and the account alone can open the socket, so
`--auth none` admits nobody else.

**The agent's forwarder is in front of it, as in front of CloudCLI.** It
listens on `127.0.0.1` at the configured port, where the agent's end of a
`connect` stream reaches it, and passes what it admits to the socket:

| A request | The forwarder |
| --- | --- |
| carries `?tkn=<token>` that verifies | sets its own login cookie, `neutrino_code_server_<port>`, and redirects to the same path without the token |
| carries `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| carries the login cookie with a good signature and expiry | passes it on unchanged, WebSocket included |
| carries neither | 401 |

The token is CloudCLI's: the hub mints it from the instance's secret on
every `service` ask, it expires 60 seconds later, and it works once. The
login cookie is `base64url(expiry || HMAC-SHA256(key, expiry))`, the key
derived from the instance's secret, and lasts seven days. The agent keeps a
root-only record per instance, its port and its secret, so the forwarder
comes back after an agent restart.

Each instance a running module serves is published as one `web` entry,
`code_server_<device id>_<account>`, titled `code-server (<account>)`, with
`is_token_required: true` and `description_code` `code_server_module`
([protocol.md](protocol.md), "The services section, one entry per published
service").

### Gitea

The `gitea` module runs Gitea, the release binary its publisher builds
(MIT), one instance per machine, on Linux, macOS and Windows, the way
Gitea's own page "Installation from binary" describes. One applier per
system sits behind one runner in `agent/neutrino_agent/modules/gitea/`, and
the configuration, the rendered `app.ini`, the accounts made through the
gitea CLI, the published `web` entry and the verbs are the same on every
system.

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| Binary | `/usr/local/bin/gitea` | `gitea/gitea` under the state root | `gitea\gitea.exe` under the state root |
| Data: the database, the repositories, the log, `custom/` | `/var/lib/gitea` | `gitea_data/` under the state root, owned by the account, mode 700 | `gitea_data\` under the state root, SYSTEM and the administrators alone as the root is |
| `app.ini` | `/etc/gitea/app.ini`, root and the group `git`, mode 640 | `gitea_data/custom/conf/app.ini`, the account's, mode 600 | `gitea_data\custom\conf\app.ini` |
| Runs as | the system account `git` the module makes | the hidden account `neutrino_gitea`, made with `sysadminctl` the way the file share makes its accounts, with the full name `Neutrino Gitea`, the shell `/usr/bin/false` and the data directory as its home, and read back before it counts | LocalSystem, `RUN_USER` being `<computer name>$` as Gitea's page prescribes |
| Service | `neutrino_gitea.service` | the LaunchDaemon `com.neutrino.gitea` with `UserName`, its output in `/Library/Logs/Neutrino/agent/gitea.log` | the service `neutrino_gitea`, made with `sc.exe`, started at boot and again after a failure |
| Git | the distribution's `git`, installed with the binary | the command line tools' or Xcode's own `git`, else Homebrew's, never `/usr/bin/git` | Git for Windows, found on the machine's `Path` as the service reads it, else under `%ProgramFiles%\Git\cmd` |
| SSH | the system's `sshd` as `git` | none; clones and pushes over HTTP | none; clones and pushes over HTTP |

**Git is the machine's.** The module installs none on macOS and Windows: an
install or an apply there that finds no usable `git` is refused
`gitea_git_missing`, and `app.ini` names the one found in `[git] PATH`. On a
Mac without the developer tools `/usr/bin/git` is a stub that opens a dialog
on the screen, so it is never run and never named.

**The binary comes from its publisher.** `data/manifests/gitea.json` pins
the release at one version for every system: `linux-amd64`, `linux-arm64`,
`darwin-10.12-amd64`, `darwin-10.12-arm64` and `windows-4.0-amd64`, each with
the sha256 dl.gitea.com publishes beside it. The Windows build is the one
that runs `git`, as on Linux; the `gogit` build is not used. The hub's cache
fetches it and sends it down `package {module: gitea}`.

**The accounts are made through the gitea CLI as the server's own account**:
`runuser -u git` on Linux, a process with the account's uid, gid, home and
`USER` on macOS, and the agent itself on Windows, which is LocalSystem as
the service is.

**Uninstall takes what the module added and keeps the data**: the unit,
the LaunchDaemon or the service, the binary and `app.ini` go; the data
directory and the account stay, so an install afterwards serves the same
repositories and accounts. Removing the agent takes the LaunchDaemon and
the service with its own ("One socket, everything on it").

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
read. The agent's only local ports are the CloudCLI and code-server
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
