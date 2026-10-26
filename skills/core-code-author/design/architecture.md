# Architecture

The load-bearing structural principles of this repo.

## The shape of the system

One box runs the hub: a Linux machine in any network mode, or a macOS or
Windows machine in `server` mode ([network.md](hub_components/network.md)). A Linux,
Windows or macOS machine the hub manages runs the agent, as root, headless.
A person's own machine, Linux, Windows or macOS, runs the client in that
person's session, never as root. The hub box runs its own
agent too, and hosts no module itself.

```
config/ ──render──▶ /var/lib/neutrino/hub/generated/ ──apply──▶ the daemons:
  ▲                                              xray, dnsmasq, cliproxyapi,
  │ every change is a write here                 nftables, the overlays, units
  │
web/ (FastAPI, root) ◀────── hub/frontend/ (browser, HTTP or HTTPS, password)
  ▲
  │ the local channel: questions up, commands and frames down
  │
neutrino_transport (its own account) ◀── the agent port: knock, Noise, yamux
  ▲                    ▲
  │ one session:       │ one session: the published list down,
  │ reports up,        │ a service frame for its material, streams
  │ the state down,    │
  │ streams both ways  neutrino_client (a person's session, never root):
  │                    a tray and a window, and its own transport
  │
neutrino_agent (root, stdlib only) ──── hosts modules, applies the state,
  ▲  and its own transport              shares the desktop
  │ root-only Unix socket
nagent (root, on the machine)
```

Inside the hub package the layers only reach downward:

- `modules/<name>/` — one feature each (config, renderer, ops, provisioner),
  pure library. Modules cross-reference by id rather than by embedding each
  other's data: a device names a vault SSH key, an xray node and an AI
  provider each name a vault secret, an offer names a declared service. The
  providers themselves live in `modules/ai/`, and the AI gateway renders what
  that module stores.
- `system/` — wrappers around OS invocations more than one module needs. A
  module's own effects stay in its `ops`, `apply` or `provisioner`.
- `web/` — one router file per API module, models shared with the frontend
  by field name.
- `cli/` — every entry point, one `nhub` subcommand each.
- `platforms/`: what differs between Linux, macOS and Windows, and nothing
  else: the five roots, the elevation check, the process controller, the
  opening a browser and the file lock. The firewall is `modules/firewall/`,
  a renderer and one applier per system, and the network facts outside
  Linux come from psutil inside the `system/` modules. On Windows the
  routes, the IPv6 addresses and the resolvers come from iphlpapi, through
  `system/windows_net.py`.
  `base.py`, `linux.py`, `darwin.py` and `windows.py` follow the agent's
  shape, with `win32.py` and `windows_service.py` copied from the agent, since
  the packages share no code. `detect.hub_os()` returns `linux`, `darwin` or
  `windows`, and the panel's API uses the same word.

The agent has no dependencies and listens on `127.0.0.1`, for the programs on
its own machine. For the containers there it also listens on the gateway of
each Podman bridge on Linux and on WSL's vEthernet adapter on Windows, with a
firewall rule for each where the machine's firewall drops it ([agent.md](agent.md),
"The listeners a container reaches"). Through the transport it carries, it keeps one session open to the hub and reconnects when it drops, so it survives restarts, sleep
and NAT in between. It decides nothing: the hub says in `state` what each
module is to be, and the agent observes, installs and configures until the
machine matches ("The hub says what is wanted; the agent observes, installs
and configures"). What a person does with a published service is the
client's, on that person's machine, and the agent has no part in it.

## config/ is the single source of truth

Everything the gateway does is a function of the JSON files under `config/`.
State flows one way:

```
config/<module>/*.json  ->  render (pure library)  ->  /var/lib/neutrino/hub/generated/*
                        ->  validate  ->  apply (systemctl / nft / ip)
```

- On macOS and Windows the pipeline is the same, and apply restarts a
  daemon through the supervisor and has no `nft` or `ip` step ("One service
  supervises the daemons on macOS and Windows" below).
- The web backend and `nhub apply` drive the exact same pipeline. A change
  made in the panel is a write to `config/` followed by a render+apply; there
  is no second path that edits `/etc` by hand.
- Backing up `config/` (and restoring it on a fresh machine) reproduces the
  whole appliance. Nothing load-bearing lives only in `/etc` or in a daemon's
  memory.
- Because `config/` is the contract, `config/<module>/<name>.example.json` is
  committed and documents every field; the real file may be `.gitignore`d for
  secrets. See [config.md](../misc/config.md).

## Render and apply are separate layers

Keep system effects out of the rendering logic. A renderer is a pure function
from `config/` data to a generated artifact (a dict, a string, a file); it never
runs `systemctl`, `nft`, or `ip`. A thin apply layer validates the artifact and
then touches the system.

```text
# BAD — renderer shells out; impossible to test without root and a live nft
class RouterNftRenderer:
    def render(self):
        ruleset = self._build_ruleset()
        subprocess.run(["nft", "-f", "-"], input=ruleset)   # effect inside render

# GOOD — render is pure; apply validates then applies
class RouterNftRenderer:
    def render(self) -> str:            # pure: config -> ruleset text
        return self._build_ruleset()
modules/router/routes.py  ->  RouterRulesetApplier.apply(ruleset)   # nft -c then nft -f
```

Litmus test: if you deleted systemd and nft tomorrow, every renderer should
still import, run, and pass its tests unchanged. If it would not, an effect has
leaked into the rendering layer.

## One service supervises the daemons on macOS and Windows

On Linux each daemon the hub runs is a systemd unit of its own, and that set
of units does not change; the relay's `ssh` is the unit
`neutrino_hub_relay.service` among them, and the two frpc processes are
`neutrino_hub_sakurafrp.service` and `neutrino_hub_openfrp.service`. On macOS and Windows the hub is one binary, `nhub`,
compiled by Nuitka as the agent is, and its package registers one service:
the LaunchDaemon `com.neutrino.hub`, run as root and starting `nhub run`, and
the Windows service `neutrino_hub`, run as SYSTEM and starting
`nhub service run`. That one process serves the panel and runs every daemon
as its own child:

| Child | Started as |
| --- | --- |
| xray | the rendered configuration, with no service account and no capabilities |
| CLIProxyAPI | `cli-proxy-api --config` the rendered YAML |
| NetBird | `netbird service run --config <state>/netbird/config.json --log-file <log>/netbird.log --daemon-addr` the hub's own address: `unix:///var/run/neutrino/hub/netbird.sock` on macOS, a loopback TCP port of the hub's own on Windows |
| EasyTier | `easytier-core` with its rendered file and `--rpc-portal 127.0.0.1:15888` |
| the relay | the system's OpenSSH client with the start line rendered from `config/overlay/relay.json`, while the relay is on and configured; its output in `relay.log` ([network.md](hub_components/network.md), "The relay, the third way in") |
| SakuraFrp, OpenFrp | `frpc -c <state>/<vendor>/frpc.toml`, while the vendor is on and a tunnel is picked; its output in `sakurafrp.log` or `openfrp.log` ([network.md](hub_components/network.md), "SakuraFrp and OpenFrp") |
| tun2socks | `tun2socks` on the hub's TUN device, pointed at xray's `socks_local_in`, while the box's own scope or the overlay scope is on and xray runs; it requires xray, so it is ended before xray stops or restarts and started again once xray is back, and the routes follow it ([proxy.md](hub_components/proxy.md), "The TUN on macOS and Windows") |

- Every `netbird` command the hub runs names the same `--daemon-addr`, so a
  client's NetBird on the same machine is never the one it talks to.
- A child that exits is started again after a backoff. Stopping the service
  stops every child; on Windows the children run in a job object that ends
  them with it.
- Each child's standard output and error go to `<name>.log` under the log
  root, rotated by size ([files.md](files.md)).
- EasyTier's and the relay's start lines are held by the supervisor; no
  drop-in file exists.
- No code calls `systemctl` itself. The runtime hands out one process
  controller with one set of methods (is active, show, start, stop, restart,
  enable, disable, reload, journal): `SystemdServiceController` on Linux,
  `SupervisedProcessController` on macOS and Windows. There, enabling a
  daemon writes it into `state/services.json` and starts the child, and its
  journal is the tail of its log file. A `nhub` command only writes the
  file; the service reads it again every few seconds and starts or stops
  the children whose entry changed.
- Restarting the panel there is the supervisor exiting; launchd's
  `KeepAlive` and the service control manager's failure recovery start it
  again.
- No nftables layer exists outside Linux. The hub renders its exposure into
  the system firewall instead ([network.md](hub_components/network.md), "What
  answers, and where").
- The service runs from the install. Before the box is set up it serves the
  setup wizard on the panel's HTTP port and nothing else; when the wizard's
  steps finish, the process exits and the service manager starts it again as
  the panel. On Linux the package starts `neutrino_hub_web` the same way, and
  that unit serves the wizard until setup is done
  ([privilege.md](privilege.md), "The application entry elevates once").

## `nhub setup` configures and starts, and installs nothing

Three stages act on a machine that becomes a hub, and none of them does
another's work:

| Stage | Does | Never does |
| --- | --- | --- |
| The package | Installs everything the hub cannot run without, lays the payload down, and starts the hub's service, which serves the setup wizard until the box is set up | Configures anything |
| `nhub setup` | Asks what this machine is for, writes `config/`, renders, installs the units and starts the services | Installs a system package |
| The panel | Installs the modules somebody chose on managed machines, through their agents, and updates the hub itself | Runs before a hub is set up |

What a package holds and depends on is [min_support.md](min_support.md),
"What each package holds and depends on", and where it puts each file is
[files.md](files.md). On every system the package installs an application
entry named `Neutrino Hub`, which opens the wizard or the panel
([privilege.md](privilege.md), "The application entry elevates once").

`nhub setup` writes files under the five roots in [files.md](files.md), takes
the interfaces over, renders every daemon's configuration from `config/`,
installs the units and starts them. It checks that the dependencies are
present, and refuses with the command that installs them when they are not,
printed for the package manager this machine runs. It installs nothing
itself, on any path.

`setup` runs once. A box with a panel password is a box somebody configured,
and `nhub reset all` is how one goes back to fresh.

Every `nhub` command that changes the box, `start`, `stop`, `update` and
each form of `reset`, asks `[y/N]` before it acts and takes `--yes` to go
ahead without asking. With no terminal on stdin and no `--yes` it asks
nothing, prints one line naming `--yes` and exits 1, so every script that
runs one passes `--yes`: the deb's and the rpm's removal script and the
Windows installer's removal run `nhub reset network --yes`. The agent's
commands that change the machine do the same: `nagent start`, `stop`,
`leave`, `join` over an existing binding and `service uninstall`, and the
agent's deb removal script runs `nagent leave --yes`. A machine with no
binding is told so by `nagent leave` without a question.

The questions are answered in the terminal or in a browser. The hub's
service serves the browser's questions from the install on the panel's HTTP
port, the port that is in somebody's address bar afterwards, behind a
one-time token kept under the state root and readable by root alone; the
application entry and `nhub open` hold the token, and the package's
post-install and the install script print the address with it for a box
nobody sits at. The terminal path is `nhub setup`. Whichever path starts the
steps first holds the setup lock, and the other is refused with
`setup_in_progress`. When the steps finish, the service process exits and
comes back as the panel on the same port. A terminal that printed the
service's address and waits at its welcome checks every two seconds whether
the box became set up; when the browser's run finishes first it prints one
line with the panel's address and `nhub setup` exits 0, so the install script
that ran it ends there too. A terminal past its welcome that reaches the
steps after the browser's run finished is refused with the "already set up"
line, before any step runs. A browser that ran the wizard is sent to the
panel at the address it used, its own origin, never at an address the hub
picked from an interface.

Neither way is the source of truth for the questions: both build the same
answers document `nhub setup --stdin` reads, and `wizard.from_document`
says whether it can be used. A browser that posts one it refuses is told,
and asked again.

On macOS and Windows the package registers the one service and starts it
("One service supervises the daemons on macOS and Windows"), and
`nhub setup` does less than on Linux:

| Step | Linux | macOS and Windows |
| --- | --- | --- |
| Checking what the hub needs | the system packages | the programs the package includes are present |
| Guarding SSH with fail2ban | writes the jail | skipped |
| Creating service users and directories | both | directories only, no account |
| Installing units | writes them | skipped: the installer registered the one service |
| Applying interface roles | by the mode | skipped |
| The network mode | asks for one of three; `cn` offers `router` and `server` | `server`, with no question |
| The hub's own traffic through the proxy | asked in `intl` | asked in `intl`; it diverts through the TUN there ([hub_components/proxy.md](hub_components/proxy.md), "The TUN on macOS and Windows") |
| Starting services | each unit | the service is already running; the steps before this one write `services.json`, and the service starts each child as the file names it. From the terminal path this step is a restart of the service into the panel, after the panel password and before the local agent; from the browser path the service restarts itself; on macOS and Windows this step also writes the system firewall once, so the panel is reachable through it from the first minute |
| The local agent | from the cache by `AGENT_PACKAGE_FAMILY_OF_PLATFORM` | from the cache by `AGENT_PACKAGE_FAMILY_OF_OS`: `installer -pkg <file> -target /` or `msiexec /i <file> /qn /norestart`, then `nagent join <link> --yes` |

`nhub start`, `nhub stop` and `nhub status` drive that one service. The
machine's shares and VS Code come from its local agent, as on any device
([agent.md](agent.md)).

## The hub updates itself outside its own process

The one package the panel installs for itself is its own. Settings has an
Update panel, and `nhub update` is the same from a terminal:

1. The hub reads `latest.json` from the release sites, the newest release's
   tag ([../agent_work_rule/release.md](../agent_work_rule/release.md),
   "Release sites").
1. It takes that release's `SHA256SUMS` and its own edition's package from
   the release sites, with the method every download uses
   ([agent/module_install.md](agent/module_install.md), "Choosing a
   source").
1. It checks the package against `SHA256SUMS` and hands the install to a
   transient unit, `neutrino_hub_update`.

The unit exists because the package's maintainer script restarts the panel,
which then cannot finish an install it runs itself. The unit holds a health
gate and installs the previous version's package when the new one does not
answer.
A hub updates to its own edition's package alone, which the file's name
tells apart. [files.md](files.md) names what the directory keeps.

On macOS and Windows the install runs as the agent's self-update does: a
PowerShell started with `CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB` on
Windows, whose process id the hub writes beside `state.json`, and a job given
to `launchctl submit` on macOS, which removes itself when it ends. It installs
the `.msi` or the `.pkg`, holds the same gate (the service running,
`/api/hub/display` answering 200 on 127.0.0.1, `nhub --version` printing the
target), installs the kept previous package when the gate fails, reinstalls
the local agent, and writes each turn into `state.json`.

## Libraries carry the logic; `nhub` carries the execution

Reusable logic lives in purely functional library packages. All execution
verbosity lives in `neutrino_hub/cli/`. This is not a formatting preference: it
is what lets one rendering implementation drive both the web panel and the
command line, and what keeps every library unit-testable with no daemon
running.

- Library packages (`neutrino_hub/modules/<name>/`, `neutrino_hub/system/`,
  `neutrino_hub/web/`, `neutrino_hub/utils/`) expose composable functions and
  classes with explicit constructor keywords. No `main()`, no `argparse`, no
  wiring-config classes.
- Each tool is a `neutrino_hub/cli/<name>.py` that wires the libraries together
  with plain-variable config sections, and one `nhub` subcommand.
  `cli/entry.py` holds the subcommand table and dispatches; what each command
  does is [../../cli.md](../../../docs/cli.md).

The mechanical placement rules are in
[../coding_style/layout_style.md](../coding_style/layout_style.md).

## A left-out feature is reached through one table

A left-out feature is a feature the mainland edition `cn` builds without,
by deleting its files from the tree: the proxy, and with it the side
gateway mode ([../agent_work_rule/release.md](../agent_work_rule/release.md),
"Two editions from one source"). The code that stays must import, start and
pass its tests in a tree without those files, so it reaches a left-out
feature through one table and through no other import.

| Rule | Reason |
| --- | --- |
| A left-out feature's files are its own: a module package, its routers, its frontend files, its examples and unit templates, and its mirrored tests, each listed in `PACKAGING_CN_LEFT_OUT_PATHS`. | Deleting the listed paths is the whole of what makes the mainland tree. |
| No file outside a left-out feature's own files imports them, except the edition table. | One static import of a deleted package breaks the import of everything above it. |
| The edition table imports none of them when it loads; it names each hook by its dotted path and imports it on the first lookup. | A table that imported the features would fail in the tree it exists for, and every layer can read it, renderers included, without importing `web/`. |
| A feature is present when its package imports, and absent when that package is missing from the tree. | The tree is the one truth about what a package carries; `EDITION` chooses where a package fetches from and never which features exist. |
| A lookup returns the hooks of the present features only, and an absent feature contributes nothing: no route, no step, no page, no rule in a rendered file. | The code that stays has one path for both trees and never tests for an edition. |

| Feature | Its own files in the hub |
| --- | --- |
| `proxy` | `modules/xray/`, `modules/tun/`, `web/routers/hub/proxy.py`, `web/routers/hub/proxy_node.py`, the **Proxy** page and the panels only it shows |

The hub is the one package that leaves something out, and its one table is
`hub/neutrino_hub/edition.py`. `has_feature(<name>)` answers whether a
feature is present, by the name `proxy`. The desktop client, the Android app
and the agent leave nothing out: NetBird is in every edition of each, so the
desktop client and the Android app keep no NetBird hook table in
`edition.py` or `Edition.kt`, no source set added only when its directory
exists, and no part script inlined only when the tree holds it. Their
`EDITION` stamp stays for what reads it, the repository a client's
**Source** links open ([client.md](client.md), "The Settings page"); no
download reads it ([agent/module_install.md](agent/module_install.md),
"Sources").

Every place the hub registers something today takes a left-out feature's
part from the table:

| Where the hub registers | What it holds for every edition | What it adds from the table |
| --- | --- | --- |
| `web/app.py`, `API_ROUTERS` | the routers every edition has | the proxy's routers (`proxy.py`, `proxy_node.py`) |
| `cli/run.py`, the processes `nhub run` starts | the panel and the AI gateway | xray and its `--only-xray` |
| `cli/setup.py`, `CORE_STEPS`, and the wizard's questions | every other step | the proxy's steps and its question about the hub's own traffic |
| The network modes setup and the **Network** page offer | `router` and `server` | `side_gateway`, which the proxy adds |
| `nhub apply`'s component list and the panel's converge steps | every other component | xray, the proxy TUN |
| The router's renderers (`nft_renderer.py`, `dnsmasq_renderer.py`) | the rules and the files with no proxy part | the proxy's chains, its marks and the forward to xray's DNS inbound, from a hook the proxy gives |
| `hub/frontend/src/nav_items.ts` and the routes in `authenticated_routes.tsx` | every other page | the **Proxy** page, which `hub/frontend/src/edition.ts` finds with `import.meta.glob` over its files; a file the glob does not find adds nothing |

The side gateway mode exists to divert through the proxy, so the proxy
registers it, and `cn` offers `router` and `server` alone.

Two checks hold the rule. `hub/tests/test_edition.py` reads every Python
file of the hub and fails on an import of a left-out package from outside
that feature's own files and the table. The tests also run once on the
full tree and once on the mainland tree ([tests.md](tests.md), "Editions").

## Services are the person's to take; modules are the hub's to install

Two different things leave the hub, and confusing them is what the
modules/services split exists to prevent
([agent.md](agent.md), "Who may tell the agent what").

- **A module** is software a managed machine hosts. The hub administers it:
  the panel's Samba, Gitea, Containers and ZFS pages pick the devices, the
  hub fetches and installs, the agent executes. Nothing about a module is the
  machine's own choice.
- **A service** is something the hub publishes for a person to use from
  their own machine: a link to open, a port to forward, the AI gateway to
  point their tools at, a share to mount, a desktop to view. The hub says
  what exists; the client on that person's machine is where every choice is
  made, and the panel does not render those choices at all.

A service is anything the hub can publish: a device's Samba shares, its
Gitea, a container's published port, a machine's SSH server, the hub's own
AI gateway, a desktop a machine is sharing, and the apps somebody declares by
hand on machines the hub does not run. A module's entries live only while
the module runs on an enabled device; a hand-declared entry is probed, a UDP
port excepted; a desktop entry is the machine's own word and lives only
while it keeps reporting. Every `web`, `port` and `ssh` entry belongs to one
app, the thing a person uses ([protocol.md](protocol.md), "Apps").

```
module on a device (samba, gitea, podman)   -> service entries, an app's
the hub's AI gateway                        -> the one ai entry
a machine sharing its desktop               -> an rdp entry, from its reports
an app declared by hand (web, port)         -> the same shape, probed
                                                (a UDP port never)
  service entry: {id, type, title, payload, is_healthy, source, description,
                  app_id, name, local_port}
  types: web | port | ssh | ai | file | rdp
```

**The service list carries no secrets.** It is composed once, fingerprinted,
and pushed to every client resolved for the address that client reaches the
hub on. Every secret a service takes from the hub travels one at a time, as
the answer to one `service` frame of one client: its own gateway key, a
desktop's seat password, a page's token, a share's password, an account's
SSH key ([protocol.md](protocol.md), "The service frame"). The panel's Services page shows
the four kinds it can declare or module-publish; a shared desktop appears
only in the machine page's Remote desktop tab and on clients.

**What a person does with a service is their machine's state.** A mount's
login and path, which tools point at the gateway, which ports are
forwarded: all of it lives in the client's own store on that machine, and
appears in no hub backup.

## Managed is a completed handshake

A device becomes managed two ways — the hub installs the agent over SSH and
hands it a token, or the owner pastes an enrollment link into the agent — and
either way management begins at the same moment: the first heartbeat the hub
authenticates. A generated token is an offer, not a relationship; an install
that fails after generating leaves a dangling offer that shows nowhere and is
overwritten by the next attempt.

Three states, and no fourth:

| State | Holds when | The page shows |
| --- | --- | --- |
| unmanaged | no token, or a token never authenticated | the Unmanaged section — a scan finds routers and printers, and they belong here |
| managed, reporting | token, authenticated, heartbeat inside the window | the Managed section, with live gauges |
| managed, quiet | token, authenticated, heartbeat stale | the Managed section, with when it was last seen — the hub cannot tell a machine that is off from one that is gone, and says so |

Severing propagates from whichever end acts, over no channel but the ones
that exist:

- **The hub lets go by saying it holds no such binding** — the row was
  removed on the panel, so the session is ended with `binding_unknown`, the
  one refusal that unbinds. The agent deletes its binding, goes back to
  waiting for a link, and says why in `nagent status`. Every other refusal
  keeps the binding: the agent records it and sends `hello` again a minute
  later ([protocol.md](protocol.md), "Admission and the binding").
- **The device lets go by leaving** — `nagent leave` or the package's
  own removal — which tells the hub first; the hub drops
  the token and keeps the row with everything the owner typed, the module
  configuration included, until the Agents page's **Forget** deletes it.
- A device that joins a different hub cannot tell the first one, which keeps
  a managed-and-quiet row until somebody forgets it there.

The agent mirrors the three states: unbound and waiting for a link, bound and
reporting, and bound but rejected, which stays bound until the hub ends the
session with `binding_unknown`. Its binding lives in one file, and the
running service adopts what another process writes there, so the CLI and the
page need no service restart.

## The hub says what is wanted; the agent observes, installs and configures

A managed machine's agent has no dependencies and must keep none, so it is
given the smallest job that can be done well. **It observes what is true,
makes the machine match the state, and reports the result.** Whether a
module is wanted, where its package comes from and whether to try again are
settled on the hub. That is where there is a configuration directory, a
vault, and one place to look when something goes wrong.

What is wanted is one word per module, `want`, in
`config/devices/<id>/modules.json`: `absent`, `installed`, `stopped` or
`running`. The machine page writes it directly. The hub composes it with the
module's configuration and the recipes for the machine's platform into the
`state` it pushes ([protocol.md](protocol.md), "The channel").

There is no queue between the page and the machine. The state is the whole
of what a press leaves behind, and `config/` is where it is.

The agent observes each module it has a runner for, whoever installed it. It
reads whether the package is present, whether the unit is active, and whether
the hub's configuration has ever been applied. From those facts it reports
one of the closed states, and it makes each module the state mentions match
its `want`.

The bytes of a `hub` module come from the hub. The agent opens a `package`
stream for each artifact, and the hub serves it from its own cache,
`/var/lib/neutrino/hub/agent_module_cache/`. The cache fetches a file once for
every device of that platform and version, presenting a browser's TLS
fingerprint where a vendor gates on one. Losing it costs a download and
nothing else. A container image and an npm package are fetched by the
machine itself, from the source the agent chose among the ones the state
names ([agent/module_install.md](agent/module_install.md), "Sources").

Every way software moves on a managed machine is one serialized stream, and
its output is one stream too. Package operations on one machine run one at a
time, serialized on the agent, because `dpkg` and its equivalents hold a
machine-wide lock. The SSH bootstrap that puts the agent on a machine takes
the same lock.

During an install or an uninstall the agent opens a `log` stream and sends
the output line by line, success included. The module's tab shows
the hub's copy of it as it arrives, so no surface tells a different story
about what is happening to the machine.

A change therefore walks one way and never loops back:

```text
a person presses a button on the machine page
  → want is written to config/devices/<id>/modules.json
  → the hub pushes the state with the configuration and the recipes
  → the agent opens a package stream, installs, configures, starts or stops
  → the agent reports the observed state; the page shows it
```

**Retry is a person's word, never a timer's.** A step that failed is reported
`failed` with its code and is not retried while the state's hash is
unchanged. A vendor refusing now refuses in a minute, and a machine that
retries every minute spends the night doing it. Trying again is a change to
the state, from a person's press or a new configuration, or a new build of
the agent, never from a timer.

Software somebody installs or removes by hand is observed and shown, never
fought. A hand-installed module reports `installed`; at a machine's first
report on a session the hub imports what the machine already has into its
own configuration, and **Configure** does the same for a module whose import
was empty then. The hub keeps no record of a failure beyond the machine's own
report. A hub restart loses nothing, because `want` is in `config/`
([kill_on_sight.md](../kill_on_sight.md), "Unasked survival machinery").

What the agent keeps is only what it can answer for. That is which modules
are present, the state of each, whether the hub's configuration was applied,
and the output of the last thing it ran.

That output is shown beside the step it came from. A person reading "the
download failed" and a person reading the
vendor's own words are not equally able to fix it. A person watching an
install wants to see it work.

## The network the hub assumes

Every enrolled machine — on the LAN, on NetBird, on EasyTier, on whatever overlay comes
later — is somebody's own: locally administered, deliberately joined. The hub
is not multi-tenant and does not defend one enrolled machine from another.

The wire gets no such trust. A "LAN" can be a campus network with a thousand
strangers on it, so the hub's ports answer only senders inside a segment
deliberately exposed, a running overlay's among them
([network.md](hub_components/network.md), "What answers, and where"), the
panel behind a password, and the agent channel carries its secrets inside
a Noise session under the hub's pinned static key. Trusting the machines and
distrusting the wire is the whole model.

## The agent channel is pinned by a key; the panel is verified by a chain

Desired state carries real secrets, so the wire between hub and agent is
treated as hostile even where the machines on it are not. The channel is
served on its own port by the transport, a Go process of its own: a knock,
then a Noise handshake under the hub's static key, which the transport
generates and keeps. The enrollment link carries that key's public half, and
every peer pins it. Verification is the key, never a chain, so no device
installs a CA and no name has to match.

The transport carries every byte and decides nothing: every permission, and
every ticket, token and secret, stays with the hub's Python, which the
transport asks over the local channel at a session's start and at each
stream's open ([protocol.md](protocol.md), "The local channel"). One record
of who can do what is kept, and it is in `config/`.

The panel a browser reads speaks plain HTTP on its own port until somebody
turns its HTTPS on. A browser verifies by chain and by name, never by a
pinned key, so the panel's certificate is signed by the hub's own
certificate authority, which a browser installs once. The authority's name
constraints permit private and CGNAT addresses and a few private names only,
so installing it trusts nothing public. Two audiences, two transports,
because they verify differently.

The wire itself is [protocol.md](protocol.md): which port serves what, the
frames, admission by protocol number, and, in "Admission and the binding",
what each refusal does to the binding. The enrolment ticket and what an
attacker in each position gets are [agent.md](agent.md).

## The credential vault

Every secret the hub keeps for somebody is sealed in one store:
`config/credentials/vault.json`. The file has two members and nothing
readable — the wrapped data key, and one AES-256-GCM ciphertext sealing
every record whole, names, kinds, metadata and timestamps included, so the
file does not even say what it holds. The rest of `config/` holds
references — `key_id`, `password_id`, `sudo_password_id`, `login_id`,
`secret_id` — and no secret material at all.

| kind | sealed |
| --- | --- |
| `token` | value |
| `login` | password, username |
| `ssh_key` | private_key, passphrase |

An `ssh_key`'s type and fingerprint are annotations rather than material, so
the panel reads them back without the key itself ever being opened. Inside
the outer seal each object is a ciphertext of its own, its
AAD binding it to its id and kind; two objects cannot be swapped. A locked
vault therefore hides even the list — the panel shows that credentials exist
to be unlocked, not what they are.

The data key never sits in `config/`. The store carries it wrapped under the
master passphrase chosen at setup (scrypt → AES-256-GCM), so backing up
`config/` produces a file that is safe as it stands; the working copy the
panel decrypts with — with nobody at the keyboard — is state at
`/var/lib/neutrino/hub/vault.key` (mode 0600). A box without that state file is a
locked vault: every operation that needs the key refuses with
`vault_locked`, and a restore is what unlocks it, proving the archive —
name, manifest, every member's digest, the wrapped key opening under the
passphrase — before anything touches disk and writing the unwrapped key
last. On the box itself the panel is root and the vault claims nothing
against root.

Secrets travel one way through the API: written in, listed back as ids,
fingerprints and reference counts, never read out. A delete is allowed and
cascades: every reference to the object is cleared in the same step — devices
lose the key, shares and providers lose theirs, a token-keyed proxy node is
disabled because it cannot serve — and the answer says how many of each.

Two things stay out. The panel password and a device's heartbeat token are
verifiers rather than secrets — one kept as a scrypt hash, the other as a
SHA-256 digest, and neither ever needed back.

The CLIProxyAPI client keys are not vault records either: the hub generates
them itself and the panel shows them in full to their owner. They are still
sealed under the data key where they are stored, so
`config/cliproxyapi/cliproxyapi.json` carries no key material, and they unseal
at use — rendering the gateway's config, answering the AI page, handing a
managed device its key. A stored record without a seal is dropped when the
file is read, and the device holding it is issued a fresh key on its next
heartbeat.

`nhub vault rekey` wraps the data key under a new passphrase; nothing sealed
is re-encrypted.

## The AI gateway is metered at the hub

CLIProxyAPI's management API answers loopback callers only, unlocked by a
key sealed under the vault's data key. The panel drains its per-request
queue and accumulates what it held — requests and tokens, per client key and
per upstream provider — under `/var/lib/neutrino/hub/cliproxyapi/`, and a client
key belongs to a device, so usage lands on the subscription that spent it.
The dashboard, the AI page and the status strip all read that one store.

An upstream is reached two ways. A **provider** is an API key somebody typed,
which lives in the vault and is rendered into the gateway's YAML like every
other setting. An **account** is a subscription somebody signed into: the
panel starts the flow through the same management API, hands the person the
URL to open, passes the code back, and the gateway writes a token file into
`/var/lib/neutrino/hub/cliproxyapi/auth/` and serves with it without a restart.

**Auth files are the one deliberate exception to "backing up `config/`
reproduces the appliance."** They are live provider credentials that no render
produces and no apply installs, so they sit in the state root and a downloaded
backup does not carry them: a restored box signs in again. Putting them in
`config/` would put refresh tokens for somebody's Claude and ChatGPT
subscriptions into a file that travels — the vault protects what the hub was
given, and nothing protects an archive once it has left the box. Signing in is
therefore never a configuration change, and nothing about it lights an apply
bar.

Both kinds land in one pool per upstream, and the gateway rotates across it
rather than ranking accounts above keys or below them. The panel does not
model an order it does not control: it lists accounts beside providers and
says what the gateway does.

## The panel heals itself; nothing ever asks for a manual refresh

The panel is a single-page app, and the machine under it restarts — a
restored backup, a package upgrade, an operator's restart — while pages sit
open. Every open page, the login page included, watches one signal: the
unauthenticated session endpoint carries `panel_started_at`, a constant of
the server process. A page remembers the first value it saw; a later answer
with a different one means a restarted panel — new code, and sessions gone
with the old process — and the page reloads itself once. Nothing polls for
it. A restart always drops the event socket, so the page reads the value
each time that socket opens; it reads again when the tab comes back to the
front, when the login page loads, and after a login before the page moves
on. An unreachable backend is only ever waited out, and the same identity
answering again is a network blip: the page's own channels resume in place.
Downtime and 401s are deliberately not signals: a signed-out answer cannot
be told from a lockout.

## One identifier shape

A stored record is keyed by a UUIDv4 hex string, generated at creation and
meaning nothing. The exception is a device, keyed by what the network knows it
by: its MAC address, or the `id:`-prefixed machine id of a machine enrolled
from behind someone else's NAT.

## The web backend runs as root, and that is a boundary, not a habit

`neutrino_hub_web.service` runs as root because it must edit nftables, restart
services, and scan the LAN. That privilege is why the panel sits behind a
password — a scrypt hash, never the password itself — and why what reaches it
is narrowed in the nftables input chain rather than left to what the process
binds. Do not spread root-requiring calls through the codebase: they live in the
`neutrino_hub/system/` and `*/ops`/`apply` layers behind named operations, so
the surface that needs privilege is small and auditable. What the unit narrows,
and what it deliberately does not, is [privilege.md](privilege.md). On macOS
and Windows the one service runs as root and as SYSTEM, and no input chain
narrows what reaches the panel: it answers on every interface, behind the
same password ([network.md](hub_components/network.md)). If this
ever becomes multi-user or WAN-exposed, split the privileged helper out then —
the apply layer is already the seam to split on.
