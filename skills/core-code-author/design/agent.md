# The device agent

The agent is the hub's presence on a managed Linux, Windows or macOS
machine: one root service with one socket open to the hub. It hosts the
modules the hub's state names, reports what is true, and shares the
machine's desktop when told. It draws no window. Every port it listens on
is on `127.0.0.1`: the forwarders in front of the programs run as an
account, CloudCLI, code-server and Codeg
([module_template.md](agent/module_template.md), "The run"), and the AI
gateway forward, 8317, on every machine but the hub's own ("The AI gateway
forward"). For the machine's containers it opens the same ports on the
gateway of each Podman bridge on Linux, and on the computer's address on
WSL's vEthernet adapter on Windows ("The listeners a container reaches").
Its own
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
  agent's own package carries, Terminal and Remote desktop, of the kinds
  in "The kinds of module". The hub says what is wanted and sends
  the bytes; the agent observes, installs and configures. A device's Modules
  page writes one `want` per module into `config/devices/<id>/modules.json`.
  The state the agent receives names, per module, that `want`, the
  configuration, and the recipe for its platform
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
the agent opens `log`, `package` and, for the AI gateway forward, `connect`
streams to the hub. A `command` names a
module and a verb (`{agent, reboot}`, `{samba, reload}`, `{zfs,
validate}`). Every stream sits behind a credit window, so a long transfer
never starves the reader, and a stream's result is its close.

**Presence is memory only.** Online, version and last seen are in the hub's
session registry. A hub restart forgets every machine until it reports again,
and nothing about a socket reaches `config/`.

**The state is one document per device.** The hub composes it from
`config/devices/<id>/`: `modules.json` with each module's `want`, one file per
module with its configuration, and `rdp.json` with the sealed seat password.
The recipe of each module, resolved for the machine's platform and its
chosen version as `{runner, method, params}`, is added to it, and it is sent
under one hash. The agent keeps a root-only copy,
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
failed module is tried again only when its own entry in the state changes
or an agent of another build starts, and until then the report says why
with a code. **An edit to a module of an
offline device is rejected with `agent_offline`, never queued**: the person
is told the machine is away, and asks again when it is back.

**One module at a time.** The agent applies the modules a state mentions one
after another, in the fixed order `APPLY_ORDER` names: ZFS, the file share,
Terminal, Gitea, Containers, Hermes WebUI, VS Code, code-server, CloudCLI,
Codeg, Remote desktop.
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
the machine reports afterwards is shown. The agent keeps no retry policy. A
step that failed is reported with its code and is not repeated while its
entry in the state and the agent's build are unchanged; trying again is a
person's word, never a timer's. The agent keeps each module's last failure on disk, so a restart
reports it unchanged ("A failure outlives a restart").

**A retry is the same press again.** The agent tries each module's entry
once and keeps, for each module and for the `ai_tools` section, the hash of
the entry it tried on disk, so a restart does not try it again. The mark
holds for one install, one build and one binding: `nagent service
uninstall`, which every package's removal runs, deletes it, and so do a join
and a leave, so the next agent that holds the same state applies it again
after a removal undid it. The file keeps the build that wrote it, the
agent's version and the time its package was built, which the packaging
stamps into `_version.py` as `AGENT_BUILT_AT`; an agent of another build,
after an upgrade or a reinstall of another package, uses none of the
hashes, so every module the state names and the `ai_tools` section are
applied once again, whatever their hashes. A reinstall of the same package
is the same build and applies nothing again. When a
person presses a module's own action again on a module whose last report is
`failed` or `install_failed`, the hub writes a fresh `retry_mark` into that
module's entry of the state. A press of **Install**, **Start**, **Stop** or
**Uninstall**, or a module panel's apply, on a module whose last report is
`absent`, `installed`, `stopped` or `running` and is not its `want` after
the press, such as `running` wanted while it reads `installed`, writes the
same mark. The mark means nothing to the agent; it changes
that entry's hash, so the hash the agent tried for that module no longer
matches and that module alone is tried again. A change to one module's entry, or a mark on it,
never runs another module's failed step again.
The machine's AI tools take the same mark on the `ai_tools` section when a
press asks again while an account's result is `failed`. A press on a module
that reads its `want`, or is in transit, writes no mark and asks for
nothing new.

Software somebody installs or removes by hand is displayed, never fought. A
hand-installed Samba reports `installed`; its shares and users become the
hub's configuration at the machine's first report on a socket, and the
first **Configure** imports them when that report found none
([protocol.md](protocol.md), "The modules section"). A failure is
in the machine's report and in the agent's record of it, and a hub restart
loses nothing, because `want` is in `config/`. Machinery whose only purpose
is surviving a restart, beyond that record and the tried hash, is removed on
sight ([../kill_on_sight.md](../kill_on_sight.md), "Unasked survival
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
| `absent`, `installed`, `stopped`, `running`, `install_failed` | `installing`, `uninstalling`, `queued` | `failed`, `unsupported` |

`installed` is present and never configured by the hub; `install_failed` is
a module whose last install failed, whatever that install left on the
machine ("An install that fails ends install_failed"); `stopped` and
`running` are configured by the hub and told apart by the unit; `installing`
also covers a module's own install that runs inside its apply or as a task
the apply left running, and a state waiting on such a task is applied again
every 30 seconds under the same hash until the task ends. An `installing`
row can hold `{code, params}` naming what holds up the install:
`reboot_required` while a Windows machine owes the restart that the Windows
features of Containers asked for. The agent never restarts the machine; a
person does, from the module's tab or the device, and the same 30-second
apply goes on with the install after it
([modules/containers.md](agent/modules/containers.md)). An `absent` row
can hold `{code, params}` naming the part missing while the rest of the
software is there: `zfs_kernel_module_missing {kernel}` while the ZFS tools
are installed and the running kernel has no ZFS module
([modules/zfs.md](agent/modules/zfs.md)); a kept failure's code takes its
place ("A failure outlives a restart"). `queued` is a
module the agent reaches after the one it is applying ("One module at a
time").

**An install that fails ends install_failed.** An install that fails
reports `install_failed` with the failure's `{code, params}`, whether the
module's check then finds the software or not, and never `installed`,
`absent` or `failed`. The agent keeps the tried hash for that module, and the
hub keeps the module's `want` ([protocol.md](protocol.md), "The modules
section"). **Install** is the next press: its retry mark changes the entry,
and the agent runs the install again even where the module's check passes.
**Uninstall** runs the module's uninstall on whatever the install left; on
software the check does not find, a step of it that fails is a line in the
log, and the outcome is what the check finds afterwards. A step that fails
on a module the machine has (start, stop, configure, uninstall) reports
`failed`. No button cancels a step.

**A failure outlives a restart.** The agent keeps each module's last failed
step, its state (`install_failed` or `failed`) and its `{code, params}`,
root-only in `failures/<module>.json` under the state root, and reports the
module from it after a restart: a module whose install failed reads
`install_failed`, and one whose configure, start, stop or uninstall failed
reads `failed` while its software is there. The module's next attempt
replaces the record, and deletes it when the attempt took; a state that no
longer names the module, a join and a leave delete it as well. A failure the
socket caused, `hub_unreachable`, is kept like any other, and its tried hash
is not, so the next state runs the step again.

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

## The kinds of module

Every module is of one kind by how it runs, and each platform entry of its
manifest names one runner and one install method. The flow every module
shares, from the manifest to the published entry, is
[module_template.md](agent/module_template.md); the install methods, the
presence check and what an uninstall removes are
[module_install.md](agent/module_install.md); each module's own page is
linked from the table.

| Kind | Modules | Install method | Run |
| --- | --- | --- | --- |
| carried by the agent | [Terminal](agent/modules/terminal.md), [Remote desktop](agent/modules/remote_desktop.md), which also detects a person's own AnyDesk and TeamViewer | `agent`, on every system | the module's own applier per system |
| software the module configures | [File share](agent/modules/file_share.md), [Containers](agent/modules/containers.md), [ZFS storage](agent/modules/zfs.md) | `system`; on Windows and macOS the file share's SMB server is `builtin`, and Containers is `hub` | the module's own applier; for Containers on Windows and macOS, inside a Podman machine of one account |
| a service with a system account of its own | [Gitea](agent/modules/gitea.md) | `hub` | the account and the service the module makes, in the publisher's layout on every system |
| a program run as a person's account | [VS Code](agent/modules/vscode.md), [code-server](agent/modules/code_server.md), [CloudCLI](agent/modules/cloudcli.md), [Codeg](agent/modules/codeg.md) | `hub`, each archive unpacked and sealed under `agent/<module>/<directory>/` | one account service per instance, the forwarder in front of it, one `web` entry per running instance |
| container images | [Hermes WebUI](agent/modules/hermes_webui.md) | `container`, pulled by the Containers module's Podman | hub containers on the Containers module, which the module needs |

Terminal and Remote desktop install nothing: their platform entries name the
method `agent`, they are never in the Modules page's picker, always a tab,
and take none of the four presses ([protocol.md](protocol.md), "The modules
section, one entry per module"); the hub composes both from their own files
under `config/devices/<id>/`, not from `modules.json`.

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
| the Hermes WebUI module is configured | its forwarder's port |
| a running Podman container publishes a host port, other than a hub container's `page_port` ([modules/containers.md](agent/modules/containers.md), "Hub containers") | that port on the protocol it is published on, dialled on the host address it is published on when it names one, and on Windows and macOS dialled on `127.0.0.1` whatever it names, since the Podman machine's ports reach the computer there; a stopped container's ports are not published, so a stream on one ends `port_not_published` within a second of the stop |

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
| a Podman container's published port | every address, or the one address it is published on, which the agent dials; on Windows `127.0.0.1` alone, through WSL's forwarding from the Podman machine, and on macOS where Podman's forwarder listens, `127.0.0.1` among them |
| VS Code | `127.0.0.1` alone |
| the CloudCLI, code-server and Codeg forwarders | `127.0.0.1` alone, in front of CloudCLI and Codeg on loopback and code-server on its account's socket |
| the Hermes WebUI forwarder | `127.0.0.1` alone, in front of the webui's port published on loopback ([modules/hermes_webui.md](agent/modules/hermes_webui.md)) |

## The AI gateway forward

The hub's AI gateway listens on the hub's own loopback alone
([hub_components/ai.md](hub_components/ai.md), "What serves"), so a managed
machine's AI tools reach it through the agent. While the `ai_tools`
section's `is_forwarded` is true, the agent listens on `127.0.0.1:8317`,
and the endpoint the switch writes into each tool is that port
([ai_tools.md](agent/ai_tools.md)). For
each connection it accepts there, the agent opens `connect {id}` to the
hub, `id` being the `ai` entry's id, the same kind and arguments a client's
AI forward opens; the hub joins it to the gateway on the hub's loopback
([protocol.md](protocol.md), "The connect stream").

| Rule | Reason |
| --- | --- |
| The forward listens on `127.0.0.1`, and for the machine's containers on the Podman bridges on Linux and on WSL's vEthernet adapter on Windows, each relay with the firewall rule it needs there ("The listeners a container reaches"). It closes when its `is_forwarded` turns false. | The gateway serves the hub's own machine, its clients, its managed machines and their containers, and no other host on the LAN; a port on a LAN address opens it to the LAN. |
| While the agent has no channel to the hub, the forward stops accepting new connections and stays bound; the connections waiting in its listen queue are served once the channel is back. | A client's forward does the same ([client.md](client.md), "The local port table"), for the same reason: a connection accepted with no channel can only be closed at once. |
| The hub closes the stream `permission_denied {kind: ai}` while that machine's AI tools setting is off and no container module that uses the gateway is installed there. | The setting and the container modules are the machine's permissions for the gateway. |
| The forward adds no key and reads none; each request holds the device's own key, which the switch wrote into the tool, and the gateway checks it. | The gateway's key check is the one gate on it, wherever a request comes from. |
| The hub sends `is_forwarded` false to the agent on its own machine, which opens no forward. Its tools are pointed at the gateway's own loopback port, `listen_port`. | The gateway already listens on that machine's loopback, at 8317 by default, the port a forward there takes. The hub knows which device is its own machine by the machine id; the agent is told, and reads it from nothing else. |
| On a managed machine `is_forwarded` is true while the machine's AI tools setting is on, or while a container module that uses the gateway is installed. | A container module's key works whatever the AI tools setting says ([modules/containers.md](agent/modules/containers.md), "Reaching the machine"), and the gateway's key check is the one gate on every request. |
| A port the agent cannot listen on is one line in its log, and the agent tries it again every report interval while the section asks for the forward. | Another program can hold 8317 for a while, and the forward is there once it lets go. |
| Bytes go both ways under the channel's credit, and either socket's end closes the stream. | It is a `connect` stream like any other, in the other direction. |

## The listeners a container reaches

Every container on a machine reaches the agent's `127.0.0.1` listeners at
`host.containers.internal`, on the same port. On Linux and Windows the agent
makes that true itself with a relay; on macOS the Podman machine's own
network does ([modules/containers.md](agent/modules/containers.md), "Reaching the
machine").

| Rule | Reason |
| --- | --- |
| On Linux the agent opens each of its loopback listeners also on the gateway address of every Podman bridge on the machine, bound to that bridge with `SO_BINDTODEVICE`. It relays each connection to `127.0.0.1` on the same port. | A container's loopback is its own, and its way to the machine is its bridge's gateway. Binding to the bridge keeps the port off every other interface. |
| On Windows the agent opens each of them also on the computer's address on WSL's vEthernet adapter, the adapter whose name starts `vEthernet (WSL`, and relays each connection to `127.0.0.1` on the same port. | The Podman machine runs in WSL's NAT mode, where `host.containers.internal` is that address. A listener on Windows' `127.0.0.1` alone timed out from a container. |
| The listeners relayed are the AI gateway forward and the forwarders of the programs run as an account. | They are the agent's own; VS Code's listener belongs to VS Code. |
| The agent reads the bridges, and on Windows the adapter's address, every report interval, and opens and closes the relays to match. | A bridge appears with its first container, and WSL picks the adapter's network when it starts. |
| A bridge is known by its name and its interface index. A bridge that netavark or CNI makes again has a new index, and the agent closes the relay on the old index and opens it on the new one. | A socket bound with `SO_BINDTODEVICE` stays on the index it was bound to. On the lab machines netavark made the bridge again when its last container stopped and one started, and at `podman network reload`, and the old relay reached nothing. |
| On the hub's own machine, where the agent opens no AI forward, it relays the gateway's own port the same way, the port the `ai_tools` section names as `gateway_port`. | A container on the hub's machine reaches the gateway at the same address as one on a managed machine. |
| A relayed connection meets the check of the listener behind it: a forwarder's token or login, and the gateway's key. | The relay adds a way in for the machine's containers, and no way past a check. |

Each relay gets one rule in the machine's firewall where the firewall drops
its traffic, and the rule goes when the relay closes:

| Firewall | The rule for one relayed port |
| --- | --- |
| ufw, where `ufw status` says `Status: active` | `ufw allow in on <bridge> to <gateway> port <port> proto tcp comment neutrino_agent_relay` |
| firewalld, where `firewall-cmd --state` says `running` | the rich rule `rule family="ipv4" source address="<subnet>" destination address="<gateway>/32" port port="<port>" protocol="tcp" accept`, in the zone of the bridge, the default zone while the bridge is in none |
| plain nftables, where neither runs | none |
| Windows Firewall | the inbound allow rule `neutrino_agent_relay_<port>` for TCP to the port, scoped to the vEthernet adapter by `-InterfaceAlias` |

| Rule | Reason |
| --- | --- |
| A rule names the bridge or the adapter, the relay's address and its one port. | A rule wider than the relay opens the port to senders the relay does not serve. |
| ufw and firewalld are each given the rule in their own language. | A packet passes only when every base chain on its hook accepts it. An accept in an nftables table of the agent's own passed nothing that ufw's `INPUT` policy or firewalld's zone dropped. |
| The firewalld rule is written to the runtime and to the permanent configuration. | A runtime rule alone is lost at firewalld's next reload, and that reload also drops netavark's binding of the subnet to the trusted zone; a permanent rule alone waits for a reload. |
| On plain nftables the agent adds no rule. | No base chain on the input hook drops the relay's traffic there: on the lab's Debian 12 a container reached the relay with nothing added. |
| The agent compares its rules with its relays every report interval and removes each rule whose relay it no longer opens, its own stop among them. It finds its rules by the comment `neutrino_agent_relay` in ufw, by the rule's text in firewalld, and by the name in Windows Firewall. | A rule kept after its relay closed opens a port that nothing of the agent's serves. |

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
([privilege.md](privilege.md)). The agent reaches an account in the cases
that follow and in no other. One is the seat
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
([module_template.md](agent/module_template.md), "The run"). The third is the
machine's AI tools, pointed at the gateway by cc-switch run as each account
([ai_tools.md](agent/ai_tools.md)). The fourth is a terminal or a command for
the account the Terminal module names, on Linux and macOS: the shell, or the
command an
`exec` stream names, runs through the platform's step-down with that
account's home and environment, the shell as a login shell on a
pseudo-terminal the agent makes. The fifth is Containers on Windows and
macOS, whose Podman machine is the default machine of the account the Run
settings name: every `podman machine` and `wsl` command, and the root
script that writes into the machine, run as that account through
`run_as_account`; the
keeper that starts the machine at boot is an account service; and the
agent reads the machine itself, as SYSTEM or root, with that account's
machine key ([modules/containers.md](agent/modules/containers.md)).
Everything else the agent does is root's own work.

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
module's shell for an account with it. Windows alone has `act_as`, the
contract's `as_account`, under which the calling thread acts as the account
through `LogonUserW` and impersonation for the AI tools' file steps. The engine
builds the package-backed runners only on a platform with `packages`. A
platform with `smb_server` gets the file share, driving the SMB server the
system carries, with nothing to install or uninstall; there, any other
module the state names reads `unsupported`, never `failed`, beside the
Terminal and Remote desktop rows every platform has. A platform with
`hub_packages` gets Gitea and the programs run as an account, VS Code,
CloudCLI and Codeg, and macOS code-server beside them, and Containers as
`PodmanMachineModuleRunner`, runner `podman_machine`, which runs Podman inside
a Podman machine of one account; on Linux all of them are among the runners
`packages` builds, Containers as `PodmanModuleRunner`, runner `podman`, by
the `system` method ([modules/containers.md](agent/modules/containers.md)). On every system, software the hub
sends down a package stream is unpacked into a directory of the module's
own name under the state root, one subdirectory per artifact, cc-switch into
`ai_tools/bin/`, and that directory alone is opened to every account to read and run: mode 755, and on Windows
read and execute for the Users group. Every import
only POSIX has is guarded, so one package imports on all three systems.

| | Linux | Windows | macOS |
| --- | --- | --- | --- |
| Program | `/opt/neutrino/agent` | `C:\Program Files\Neutrino\agent` | `/Library/Application Support/Neutrino/agent/app` |
| Configuration root: the binding, the credentials, the desired state | `/etc/neutrino/agent` | `%ProgramData%\Neutrino\agent\config`, under `%ProgramData%\Neutrino\agent`, whose ACL, SYSTEM and the administrators alone, the `.msi` sets | `/Library/Application Support/Neutrino/agent/config`, mode 700 |
| State root: configured marks, the modules' kept failures, packages, the last reinstall, `vscode/`, `code_server/`, `cloudcli/`, `codeg/`, `ai_tools/`, and on Windows and macOS `gitea/`, `gitea_data/` and `podman/` | `/var/lib/neutrino/agent` | `%ProgramData%\Neutrino\agent\state` | `/Library/Application Support/Neutrino/agent/state`, mode 755 |
| Log | the journal | `%ProgramData%\Neutrino\agent\log\agent.log` | `/Library/Logs/Neutrino/agent/agent.log` |
| Service | systemd `neutrino_agent.service` runs `nagent run` | the `neutrino_agent` service, LocalSystem, runs `nagent service run` | the `com.neutrino.agent` LaunchDaemon runs `nagent run` |
| Control transport | Unix socket `/run/neutrino/agent/agent.sock` | named pipe `\\.\pipe\neutrino_agent`, its descriptor SYSTEM and the administrators | Unix socket `/var/run/neutrino/agent/agent.sock` |
| Metrics | `/proc`, `/sys`, `nvidia-smi` | kernel32 `GetSystemTimes`, `GlobalMemoryStatusEx`, `GetTickCount64` and the system drive; per-core CPU and the process table from `NtQuerySystemInformation`, rated against the previous report; GPUs from `nvidia-smi` where it is installed, else the PDH counters `GPU Engine` (the busiest engine type per adapter, the way Task Manager reads it) and `GPU Adapter Memory`, with the adapter's name and total memory from the graphics kernel (`D3DKMTEnumAdapters2`, `D3DKMTQueryAdapterInfo`); a temperature from WMI `MSAcpi_ThermalZoneTemperature` through the PowerShell host where the firmware exposes one, else none; no load average | `host_statistics`, `vm_stat`, `sysctl` and `/`; per-core CPU from `host_processor_info`; the process table from `ps -axo pid,user,%cpu,%mem,comm`, the command last so `ps` does not cut it; GPUs from the `PerformanceStatistics` of `ioreg -r -c IOAccelerator`; a temperature from `powermetrics --samplers smc`, which root may run |
| Interfaces | `ip -j addr` | `GetAdaptersAddresses` through iphlpapi, loopback and tunnel adapters left out | `ifconfig -a` |
| Machine id | `/etc/machine-id` | the registry's `MachineGuid` | `IOPlatformUUID` from `ioreg` |
| Accounts | uid 1000 and above with a login shell | the enabled local accounts from `NetUserEnum`, without Administrator, Guest, DefaultAccount, WDAGUtilityAccount and the file share's own; the home is the `ProfileImagePath` under the account's SID in the registry's `ProfileList` | `dscl`, uid 501 and above, home under `/Users` |
| Power | `systemctl reboot` or `poweroff --force` | `shutdown /r` or `/s /t 0` | `shutdown -r` or `-h now` |
| Running as an account | `runuser -u <account> --`, with the account's home and environment; an answered run on a pseudo-terminal the agent makes | a one-shot scheduled task `neutrino_run_as_<account>`, registered through the PowerShell host with the login the Credentials page holds for the account's instance and a limited token, started in the account's profile; its script, standard input, output and exit code are files in `state\run_as\<account>\`, whose ACL grants the account modify and SYSTEM and the administrators full control; the task and the files are removed once the exit code is read, and an uninstall removes a task or files a stopped run left; two runs for one account take turns under a lock per account, since they share the task's name and its directory; a login Windows rejects at registration (`0x8007052E`) is `credential_invalid {account}`, an account with no login `credential_missing {account}`; an answered run is `nagent answer` inside the task | a child process with the account's uid and group and no other groups, in its home, with `HOME`, `USER` and `LOGNAME` set; an answered run on a pseudo-terminal the agent makes |
| Refused | nothing | packages | packages |
| Kill | SIGTERM, then SIGKILL after two seconds | `OpenProcess` with `PROCESS_TERMINATE` and `TerminateProcess` | SIGTERM, then SIGKILL after two seconds |
| Shell stream, the Terminal module's settings empty | the login shell on a pseudo-terminal, which is its controlling terminal so a resize reaches it as `SIGWINCH`, started in root's home | PowerShell on a pseudo console, in a job that kills it on close, started in the signed-in account's profile directory, and in the system drive's root when nobody is signed in or the profile cannot be found (a domain account, a directory that is not there), never in the service's own directory | `zsh -il` on a pseudo-terminal, its controlling terminal as on Linux, started in root's home |
| Seat | `loginctl`, `/proc/net/tcp`, the Wayland token | the console session's user through WTS, `netstat` | the system configuration's console user, `State:/Users/ConsoleUser` through `scutil`, the login window, root and no name being nobody, and the owner of `/dev/console` only when `scutil` cannot be asked, since under auto-login that owner stays root while a person is signed in; `netstat`; the privacy grants |
| Shell stream, the Terminal module's account set | `runuser -u <account> -- <shell> -l` on the pseudo-terminal, started in the account's home with its environment | no account: SYSTEM, as above, with the module's shell program | the account's uid and group in the child, its home, `HOME`, `USER` and `LOGNAME`, `<shell> -l` |
| RustDesk, the agent's copy | `/usr/lib/neutrino/agent/rustdesk/rustdesk`; with the switch on the agent writes `/etc/systemd/system/rustdesk.service`, which overrides upstream's packaged `rustdesk.service` under `/usr/lib/systemd/system`, and enables and starts it; off, it disables it and deletes the file; `kept/service.json` records whether a packaged `rustdesk.service` was enabled and active, and a unit file of that name in `/etc` that is not the agent's is moved to `kept/`. The host is stopped with `systemctl kill`, never `systemctl stop` of upstream's unit, whose `ExecStop` is `pkill -f "rustdesk --"` and ends a person's viewers too. Upstream's own package deletes `/etc/systemd/system/rustdesk.service` when it is installed, upgraded or removed, so doing that while the switch is on takes the agent's registration away until the switch is applied again | `C:\Program Files\Neutrino\agent\rustdesk\rustdesk.exe` with its files; the service `RustDesk`, `AUTO_START` as LocalSystem, its `ImagePath` `"<copy>" --service`, created when none exists; `kept\service.json` holds a service found before (its `ImagePath`, start type and whether it ran); the service's configuration is read from the service control manager, and RustDesk's processes from the process table | `/Library/Application Support/Neutrino/agent/app/rustdesk/RustDesk.app`; `/Library/LaunchDaemons/com.carriez.RustDesk_service.plist`, label `com.carriez.RustDesk_service`, the copy's `Contents/MacOS/service`, system domain; `/Library/LaunchAgents/com.carriez.RustDesk_server.plist`, label `com.carriez.RustDesk_server`, the copy's `Contents/MacOS/RustDesk --server`, `LimitLoadToSessionType` `Aqua` and `LoginWindow`, `RunAtLoad`, `KeepAlive` true; files found under those names are moved to `kept/` first |
| RustDesk's settings | root's and the seat's `~/.config/rustdesk/RustDesk2.toml` and `RustDesk.toml` | LocalService's `C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\RustDesk2.toml` and `RustDesk.toml` | root's and the seated account's `~/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml` and `RustDesk.toml` |
| File share | Samba, `smb.conf` rendered whole | the SMB server through the PowerShell host, one function per operation and the password inside the request: shares whose description starts `neutrino:`, local accounts in no group, hidden from the sign-in screen and denied the console and RDP through `LsaAddAccountRights`, folders granted with `icacls`, and the block rule `neutrino_smb_fence` for TCP 445 from every address outside the allowed subnets | Apple's smbd through `launchctl enable` and `kickstart`: share points made with `sharing` under the record prefix `neutrino_`, SMB only, no guest, no encryption; accounts made with `sysadminctl` without a shell or a home, hidden, in `com.apple.access_smb` where it exists, the NT hash turned on before `dscl -passwd`; folders granted with `chmod +a`; the pf sub-anchor `com.apple/neutrino_smb`, loaded from a file under the state root at every apply and when the agent starts |
| VS Code | the CLI in `/var/lib/neutrino/agent/vscode`, the unit `neutrino_vscode@<account>.service` with `User=`, environment and token files in `/var/lib/neutrino/agent/vscode/tokens`, and `/etc/sysctl.d/90-neutrino-vscode.conf` when the machine's inotify watch or instance limit is under the module's floor (524288 and 512), since a served home directory runs a distribution's default out | the CLI in `%ProgramData%\Neutrino\agent\state\vscode`, the task `neutrino_vscode_<account>` registered with the account's login, at startup, no time limit, a limited token; a stop ends the task's whole process tree, so the port is free for the next start | the CLI in `/Library/Application Support/Neutrino/agent/state/vscode`, the LaunchDaemon `com.neutrino.vscode.<account>` with `UserName` |
| Self-update | `systemd-run` of `apt-get` or `dnf` | a detached PowerShell running `msiexec` | `launchctl submit` of `installer`. On every system the package the hub streamed is renamed from its temporary name to the file name its release gave it, which the hub sends with the stream: Windows Installer reinstalls a product only from a file named as the one it was installed from, and msiexec installs that file. On Linux and macOS the script links it to `update.<kind>` beside itself and installs the link, because an agent that starts clears the packages directory. A refused reinstall ends with its code on the output's last line and a non-zero exit. An install that goes through restarts the agent, so the hub's task ends when the agent is back on the channel and has reported the install's result, and that result is the task's exit |

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

A module runs on a system when its manifest has a platform entry for the
machine and the machine's `version` is not below that entry's
`min_version` ([module_install.md](agent/module_install.md), "The
manifest"). The Modules page greys out every other module in its picker
and never shows it as a tab. The agent's minimum system stays where it is; a
module a system cannot run is left out on that system.

| Module | Linux | Windows | macOS |
| --- | --- | --- | --- |
| [File share](agent/modules/file_share.md) | Samba | the system's own SMB server | the system's own SMB server |
| [Gitea](agent/modules/gitea.md) | amd64 and arm64 | amd64 | arm64 and amd64 |
| [Containers](agent/modules/containers.md) (Podman) | yes | amd64, build 19041 or later, on WSL 2 | arm64 with Podman 6.x and amd64 with Podman 5.8.x, macOS 13 or later |
| [ZFS storage](agent/modules/zfs.md) | yes | no | no |
| [VS Code](agent/modules/vscode.md) | amd64 and arm64 | amd64 | arm64 and amd64 |
| [code-server](agent/modules/code_server.md) | amd64 and arm64 | no | arm64 and amd64 |
| [CloudCLI](agent/modules/cloudcli.md) | amd64 and arm64 | amd64 and arm64 | arm64 and amd64 |
| [Codeg](agent/modules/codeg.md) | glibc 2.34, the agent's own floor, amd64 and arm64 | amd64 | arm64 and amd64 |
| [Hermes WebUI](agent/modules/hermes_webui.md) | wherever Containers runs, amd64 and arm64 | amd64, on Containers | arm64 and amd64, on Containers |
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
[gitea.md](agent/modules/gitea.md),
[containers.md](agent/modules/containers.md), [vscode.md](agent/modules/vscode.md),
[code_server.md](agent/modules/code_server.md),
[cloudcli.md](agent/modules/cloudcli.md),
[codeg.md](agent/modules/codeg.md) and
[hermes_webui.md](agent/modules/hermes_webui.md).
A source that cannot be read leaves one line in the agent's log naming it,
so the next journal shows why. `journal` answers while an apply runs; it
does not wait for the state to settle. Every log comes oldest line first,
at most the number of lines the verb asked for. A journal never shows a
secret: a token in a URL (`?tkn=`) or on a line of its own is masked before
the text leaves the agent, and a reinstall's output goes through the same
mask.

The hub's own machine on macOS and Windows runs the local agent
`nhub setup` installs ([architecture.md](architecture.md), "`nhub setup`
configures and starts, and installs nothing"), so its
shares and VS Code are that agent's modules, as on any device.

Each module's own page is under `agent/modules/`, linked from the table of
"The kinds of module", the flow they share is
[module_template.md](agent/module_template.md), and where their software
comes from is [module_install.md](agent/module_install.md).

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
until the host exits. The agent also stops the host after each request that
changes the system, because PowerShell releases the memory such a request
leaves slowly.

## Two ports, one process

The hub's panel answers HTTP on one port and HTTPS under the hub's own
certificate authority on another, behind a session, and its agent port is
pinned TLS serving `/api/channel` alone. All three are uvicorn servers in one
process. The ports, the certificate, the fingerprint and the hub's own
identity are in [protocol.md](protocol.md), "Three ports, two audiences".

Exposure is the only control plane for the hub's ports. The agent port
answers a sender inside every exposed segment, an uplink's included, and on
every exposed overlay, on Linux, macOS and Windows alike; a served LAN whose
segment is not exposed gets DHCP and forwarding only. A device on such a LAN
is enrolled after its segment is exposed
([network.md](hub_components/network.md), "What answers, and where").

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

`urls` is the hub's address in every exposed segment, because only one of them
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
[protocol.md](protocol.md), "Admission and the binding". An agent of 0.5,
one number behind, is admitted for that upgrade alone and connects with
the new number after it ([protocol.md](protocol.md), "An agent of 0.5").

## The agent's packages come from the hub

Every hub package holds one agent package, the one of its own system,
architecture and package family, in `/var/lib/neutrino/hub/agent_cache/`.
That package installs the hub's own local agent, and enrolls and updates
every device of the same platform with no network of its own. The Arch
package holds none, because no agent package is published for Arch.

Another platform's agent package is fetched when a device of that platform
needs it, for an install over SSH or for a self-update:

1. The hub reads the platform's entry in `agent_packages.json`: the file
   name, and the digest that the release's `SHA256SUMS` lists for the file.
1. It fetches the file from the release sites, at the release the hub came
   from, with the method every download uses
   ([module_install.md](agent/module_install.md), "Choosing a source").
1. It keeps a file that matches the digest in the cache. When no site
   serves one, the fetch fails `download_failed {file, sources}`.

A platform the manifest does not name is refused with `agent_package_missing`,
never served another machine's build. A package dropped under
`config/devices/packages` wins over both. Where those files are and what an
upgrade does to them is in [files.md](files.md).

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
read. The agent's only local ports are on `127.0.0.1`, and the same ports
on the Podman bridges on Linux and on WSL's vEthernet adapter on Windows,
each relay with a firewall rule scoped to that interface; anything inside
WSL on the computer reaches the adapter's address as a container does. On
macOS gvproxy gives every container in the Podman machine every port on the
Mac's loopback, the agent's listeners and every other program's loopback
service alike. The CloudCLI, code-server, Codeg and Hermes WebUI
forwarders answer 401 to a request holding neither a token the hub
generated nor a login the forwarder set, so neither the account, nor a
website in their browser, nor a process in a container reaches an instance
through them. Hermes WebUI's own password guards the port the webui is
published at behind its forwarder. The AI gateway forward passes a request to the gateway, which
answers it only with a key it knows: the device's, held in the tool files of
the accounts the setting names, or a container module's, held in that
module's containers.

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
