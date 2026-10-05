# Install and development

Who does what when a hub is installed, and what a checkout does differently.
Three stages act on a real machine, each does one thing, and none of them does
another's.

| Stage | Does | Never does |
| --- | --- | --- |
| The package | Installs everything the hub cannot run without, lays the payload down, and starts the hub's service, which serves the setup wizard until the box is set up | Configures anything |
| `nhub setup` | Asks what this machine is for, writes `config/`, renders, installs the units and starts the services | Installs a system package |
| The panel | Installs what somebody chose, and configures it | Runs before a hub is set up |

On macOS and Windows the package registers the one service and starts it
("The macOS and Windows hub" below). On every system the package installs an
application entry named `Neutrino Hub`, which opens the wizard or the panel
("The application entry opens the panel" below).

## The package installs everything the hub cannot run without

`nftables`, `dnsmasq`, `iproute2`, NetworkManager, `fail2ban`, `iw`,
`arp-scan`, `vnstat` and `curl` are the hub's dependencies, declared in the
`Depends:` of the `.deb`, the `Requires:` of the `.rpm` and the `depends=` of
the Arch package. All three are generated from `SYSTEM_RUNTIME_PACKAGES` in
[`system/constants.py`](../../../hub/neutrino_hub/system/constants.py), so a
dependency field and what the hub believes it needs cannot say different
things.

`hostapd` is a recommendation rather than a dependency: a gateway with no
radio routes perfectly well without it.

**The reason this is the package manager's job and not the installer's.**
Installing NetworkManager from a process that is running on the machine takes
the machine's network down while it runs, and on a gateway that is the
network. It happened once here, and the box needed a reboot. A package manager
installs before anything of the hub is running, which is the only moment when
taking the network down costs nothing.

## `nhub setup` configures and starts, and installs nothing

Its steps write files under the five roots in [files.md](files.md), take the
interfaces over, render every daemon's configuration from `config/`, install
the units and start them. It checks that the dependencies are present and
refuses with the command to install them if they are not, printed for the
package manager this machine actually runs, and it installs nothing itself,
on any path.

`setup` runs once. A box with a panel password is a box somebody configured,
and `nhub reset all` is how one goes back to fresh.

The questions are answered in the terminal or in a browser. The hub's
service serves the browser's questions from the install on the panel's HTTP
port, the port that is in somebody's address bar afterwards, behind a
one-time token kept under the state root and readable by root alone; the
application entry and `nhub open` carry the token, and the package's
post-install and the install script print the address with it for a box
nobody sits at. The terminal path is `nhub setup`. Whichever path starts the
steps first holds the setup lock, and the other is refused with
`setup_in_progress`. When the steps finish, the service process exits and
comes back as the panel on the same port. A browser that ran the wizard is
sent to the panel at the address it used, its own origin, never at an
address the hub picked from an interface.

Neither way is the source of truth for the questions: both build the same
answers document `nhub setup --stdin` reads, and `wizard.from_document` is
what says whether it can be used. A browser that posts one this refuses is
told, and asked again.

## The macOS and Windows hub

The hub runs on macOS and Windows in `server` mode only. Its package, a
`.pkg` or an `.msi`, depends on nothing the system lacks and carries:

- `nhub`, the hub compiled by Nuitka into one binary with
  `neutrino_hub/data/` inside it;
- cli-proxy-api, easytier-core and easytier-cli, and in `intl` xray,
  tun2socks and netbird, each pinned by version and sha256 for the system and
  the architecture, and on Windows `wintun.dll` and the `packet.dll`
  stand-in beside them;
- in `intl`, the geodata;
- the agent's `.pkg` or `.msi` of the same architecture and edition, in the
  agent cache.

The installer registers the service and starts it. The `.pkg`'s
postinstall creates the directories, links `/usr/local/bin/nhub`, installs
the plist and bootstraps it; the `.msi` registers `neutrino_hub` and starts
it. Until the box is set up that service serves the wizard
([architecture.md](architecture.md), "One service supervises the daemons on
macOS and Windows").

`nhub setup` there does less than on Linux:

| Step | Linux | macOS and Windows |
| --- | --- | --- |
| Checking what the hub needs | the system packages | the programs the package carries are present |
| Guarding SSH with fail2ban | writes the jail | skipped |
| Creating service users and directories | both | directories only, no account |
| Installing units | writes them | skipped: the installer registered the one service |
| Applying interface roles | by the mode | skipped |
| The network mode | asks for one of three; `cn` offers `router` and `server` | `server`, with no question |
| The hub's own traffic through the proxy | asked in `intl` | asked in `intl`; it diverts through the TUN there ([modules/proxy.md](modules/proxy.md), "The TUN on macOS and Windows") |
| Starting services | each unit | the service is already running; the steps before this one write `services.json`, and the service starts each child as the file names it. From the terminal path this step is a restart of the service into the panel, after the panel password and before the local agent; from the browser path the service restarts itself; on macOS and Windows this step also writes the system firewall once, so the panel answers through it from the first minute |
| The local agent | from the cache by `AGENT_PACKAGE_FAMILY_OF_PLATFORM` | from the cache by `AGENT_PACKAGE_FAMILY_OF_OS`: `installer -pkg <file> -target /` or `msiexec /i <file> /qn /norestart`, then `nagent join <link> --yes` |

`nhub start`, `nhub stop` and `nhub status` drive that one service. The
machine's shares and VS Code come from its local agent, as on any device
([agent.md](agent.md)).

## The application entry opens the panel

Every hub package installs one entry named `Neutrino Hub`: the Start menu
shortcut on Windows, `/Applications/Neutrino Hub.app` on macOS, a bundle
holding a script and nothing else, and the desktop entry
`neutrino-hub.desktop` on Linux. Opening it runs two steps:

1. An elevated step starts the hub's service when it is not running and
   hands back the address to open, with the setup token while the box is
   not set up; it does nothing else. Windows asks through UAC, macOS
   through the administrator prompt of `do shell script`, Linux through
   `pkexec`.
1. The person's own session opens the default browser on
   `http://127.0.0.1:<http port>/`, with the setup token while the box is not
   set up.

`nhub open` runs the same two steps from a terminal, and skips the first
when it has no privilege to start the service. Before setup the address
shows the wizard; after it, the panel. `/` is answered by the service
according to the box's state, so there is one address to remember.

## One command installs a package

`packaging/install/install.sh`, for macOS and Linux, and
`packaging/install/install.ps1`, for Windows, are release assets, listed in
`SHA256SUMS` with the packages. `intl` fetches them from
`https://github.com/iffiX/neutrino/releases/latest/download/`:

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
```

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

`cn` fetches them from the mainland repository, where they are stamped
`EDITION="cn"`:

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh
```

```powershell
irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1 | iex
```

| Input | Effect |
| --- | --- |
| `hub`, `agent` or `client` | the package to install; `hub` when none is given |
| `NEUTRINO_VERSION` | the release to install, such as `v0.5.0`; the latest when unset. `cn` keeps the latest release only, so another version is not found there |
| `NEUTRINO_ASSET_DIR` | a directory holding `SHA256SUMS` and the packages; nothing is downloaded, which is how `packaging/ci/check.py` runs the scripts |

A script reads the system and the architecture (`uname -s` and `uname -m`,
`x86_64` naming `amd64`; on Linux `/etc/os-release` picks the deb, the rpm or
the Arch package). Stamped `cn`, it first reads the latest tag from
`https://gitee.com/api/v5/repos/iffiX/neutrino/releases/latest`, since Gitee
has no fixed address for the latest release's files. It fetches `SHA256SUMS`
and the package into a temporary directory and checks the package against
it. A mismatch, or a system and
architecture no package is published for, stops the script with one
sentence. It then installs with `sudo installer -pkg`, `sudo apt install ./`,
`sudo dnf install`, `sudo pacman -U` or `msiexec /i <file> /qn /norestart`.
For the hub it ends by printing the wizard's address with its token, and
runs `nhub setup` instead when its standard input is a terminal.
`install.ps1` checks for an administrator first and exits with one sentence
when it is not one.

## The panel installs what somebody chose

Samba, Gitea, NetBird, podman and ZFS are capabilities, not parts of a
gateway. Each has a provisioner that installs its own system packages, its own
vendor binary and its own unit at the moment somebody asks for it, and each
declares its packages in its own `<PREFIX>_PACKAGES`. `git` belongs to Gitea
this way; the hub itself never runs it. On a managed Mac or Windows machine
the Gitea module installs no `git`: the machine's owner installs it, the
developer tools or Homebrew on a Mac and Git for Windows on Windows, and the
module refuses `gitea_git_missing` until one is there
([agent.md](agent.md), "Gitea").

A provisioner that would do more than install (build a kernel module, add a
third-party repository, replace a system service) returns that as a consent
code and its parameters, and the panel asks before it proceeds.

The modules a machine hosts are chosen on the Modules page the same way: the
owner of the machine installs each one from its publisher, under the
publisher's terms, and the agent carries out the install
([agent.md](agent.md)). `code_server` is one of them: coder's code-server,
one instance per account, on Linux and macOS. Its installer fetches the
standalone release named in `data/manifests/code_server.json`, and the
editor installs extensions from Open VSX.

The one package the panel installs for itself is its own. Settings has an
Update panel, and `nhub update` is the same from a terminal: the newest
release of the hub's own edition is read from that edition's release API, its
package is downloaded and checked against the release's `SHA256SUMS`, and
the install is handed to a transient unit, `neutrino_hub_update`, because the package's maintainer script
restarts the panel that would otherwise be running it. The unit holds a
health gate and installs the previous version's package when the new one
does not answer. [files.md](files.md) names what the directory keeps.

On macOS and Windows the install runs as the agent's self-update does: a
detached PowerShell started with `DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB`
on Windows, a job given to `launchctl submit` on macOS. It installs the
`.msi` or the `.pkg`, holds the same gate (the service running,
`/api/hub/display` answering 200 on 127.0.0.1, `nhub --version` printing the
target), installs the kept previous package when the gate fails, reinstalls
the local agent, and writes each turn into `state.json`.

## Where each edition fetches from

A package reads its edition from the `EDITION` its build stamped
([../agent_work_rule/release.md](../agent_work_rule/release.md), "Two
editions from one source"), and every address it fetches from follows it. A
checkout reads the root `EDITION` file, `intl` in the GitHub repository
and `cn` in the mainland source tree.

| What | `intl` | `cn` |
| --- | --- | --- |
| The hub's update check | `https://api.github.com/repos/iffiX/neutrino/releases/latest` | `https://gitee.com/api/v5/repos/iffiX/neutrino/releases/latest` |
| A release's files | `https://github.com/iffiX/neutrino/releases/download/<tag>/` | `https://gitee.com/iffiX/neutrino/releases/download/<tag>/` |
| The install scripts | `https://github.com/iffiX/neutrino/releases/latest/download/` | `https://gitee.com/iffiX/neutrino/raw/main/packaging/install/` |
| Node.js, for CloudCLI | `https://nodejs.org/dist/` | `https://registry.npmmirror.com/-/binary/node/` |
| The npm registry, for CloudCLI | `https://registry.npmjs.org` | `https://registry.npmmirror.com` |
| better-sqlite3's prebuilt binary, for CloudCLI | its GitHub releases | `https://registry.npmmirror.com/-/binary/better-sqlite3` |
| code-server | `https://github.com/coder/code-server/releases/download/` | `https://mirrors.ustc.edu.cn/github-release/coder/code-server/` |

- An edition updates only to its own edition: the update check and the
  install scripts read that edition's release and no other.
- A manifest entry's sha256 is the publisher's file, and a mirror serves the
  same file, so one pin covers both addresses. The entry names the mirror's
  address in `cn_url` beside `url`, and a `cn` hub's installer fetches from
  `cn_url` when the entry has one.
- The hub sends the npm registry of its edition in the module's state, and
  the agent runs `npm` with the registry the state names. Beside it the
  state carries `npm_environment`, the settings `cloudcli.json` names for
  the edition: in `cn`, `npm_config_better_sqlite3_binary_host`, which
  prebuild-install reads in place of GitHub.
- A download's progress line names the host it fetched from, the mirror's
  in `cn`.
- The USTC mirror keeps the latest code-server release alone, and npmmirror
  carries none. A `cn` installer tries the pinned version at the mirror and
  checks its sha256; when the mirror no longer carries that version, it
  installs the mirror's current release, checked by HTTPS alone, and the
  module's `details` name the version installed. An `intl` installer always
  installs the pinned archive and checks its sha256.

## Development runs from a checkout, against a root of its own

```bash
git clone git@github.com:iffiX/neutrino.git && cd neutrino
python3 -m venv .venv && .venv/bin/pip install -e "hub[dev]"
sudo .venv/bin/nhub --dev setup     # names the packages to install if any are missing
sudo .venv/bin/nhub --dev run       # the panel, the proxy core and the gateway
```

`--dev`, which comes before the subcommand, moves the five roots under `hub_dev_root/` in the working copy, by
setting `NEUTRINO_DEV_ROOT`; the agent's own development root is
`agent_dev_root/` beside it. Everything the hub writes about itself goes
there:

```
hub_dev_root/
    etc/neutrino/hub/       the configuration
    var/lib/neutrino/       generated, geodata, the AI gateway's state
    var/log/neutrino/
    run/neutrino/           the login lockout
    opt/neutrino/bin/       xray and the AI gateway
```

**What `--dev` changes, and what it does not.** It is not a sandbox. A checkout
is how the routing, the firewall and the interface roles are developed, so
`--dev` takes the interfaces over and writes the firewall exactly as a real
install does. The one thing it does not do is install the hub as a service:

| Step | Package install | `--dev` |
| --- | --- | --- |
| Checking the packages the hub needs | Refuses if any are missing | Refuses, the same way |
| Guarding SSH with fail2ban | Writes the jail | Writes the jail |
| Creating service user and directories | Creates them | Creates them, under the dev root |
| Preparing the Python environment | Carried by the package | Builds `.venv` |
| Installing xray-core and geodata | Carried by the package | Fetches the pinned pair into the dev root |
| Preparing config from examples | Copies them | Copies them |
| **Installing systemd units** | **Writes them** | **Skipped** |
| Applying the interface roles | Takes the interfaces over | Takes the interfaces over |
| Rendering and applying configuration | Renders and validates | Renders and validates |
| **Enabling services at boot** | **Enables them** | **Skipped** |
| **Starting services** | **Starts them** | **Skipped** |
| **Installing the AI gateway** | **Unit, enabled and started** | **Directories and the rendered config only** |
| Setting the panel password | Stores the hash | Stores the hash |

`nhub --dev run` is what runs instead of the units: the panel, the proxy core
and the AI gateway together in the foreground, and where node is installed the
frontend's dev server beside them, with Vite proxying the API to the same port.

The units on a real machine start the same command one process at a time
(`nhub run --only-web`, `--only-xray`, `--only-cliproxyapi`), so systemd keeps
deciding who each daemon runs as and what it may reach for, and a working copy
still runs the same code path. The macOS and Windows services take the
supervising path instead, `nhub run` with no `--only` on macOS and
`nhub service run` on Windows ([architecture.md](architecture.md)).

**Deleting `hub_dev_root/` undoes the hub, not the machine.** The
configuration, the rendered files, the databases and the panel password go
with it, and the next `nhub --dev setup` starts from nothing, the run-once
rule included, which reads the password from that root. What stays is what
`--dev` did to the machine itself: the interface roles, the firewall, the
`fail2ban` jail and the `xray` service account. Those are the parts a checkout
exists to exercise, and undoing them is the machine owner's to do.

## Why a checkout installs nothing either

Nothing installed the dependencies for it, so `nhub --dev setup` names them
and stops rather than fetching them, on the same reasoning as the packaged
path: a process that reconfigures NetworkManager should never be the process
that installs it.

The interpreter is the same story upside down. A package carries its own, so
it needs no system Python at all, while a checkout builds a virtual
environment because there is nobody else to do it.

## The agent's package carries an interpreter and nothing else

The agent is installed by the same three stages, one package down: its
package lays the payload, `nagent join` joins a hub, and the hub's desired
state decides what the machine hosts. What it carries is the hub's own
answer: an interpreter under `/opt/neutrino/agent` with the agent installed
beside it, the RustDesk host, and cc-switch in `bin`, all built for one
machine. cc-switch is the client's pinned version, and
`packaging/shared/constants.py` holds the one pin both packages build from;
the agent runs it as each account its AI tools setting names
([agent.md](agent.md), "The machine's AI tools"). The agent draws no window,
so it carries no bindings and depends on nothing named `python`.

**The system's Python is not part of the story.** The agent is standard
library only, so one architecture-independent package once ran on whatever
Python a device already had. A project that installs into somebody's system
Python is the thing `EXTERNALLY-MANAGED` exists to stop, and a machine's own
interpreter is not one this project may pin, so the interpreter is carried.
A checkout pays none of it: `pip install -e agent` installs nothing but the
agent.

## The client's package is compiled

The client is a person's application: it runs when the person opens it, in
their own session, never as root. Its packages carry the client compiled by
Nuitka, with the interpreter compiled in, so none of them carries a Python
tree and none depends on one: `nclient` on Linux under `/opt/neutrino/client`
with the root mount helper compiled under its `libexec` at the path polkit pins,
`nclient.exe` from the Windows installer, `Neutrino Client.app` from the
macOS one. Beside the binary ride the two tools it drives, cc-switch and the
RustDesk viewer, pinned by hash; the cc-switch pin is the one the agent's
package takes too.

What a machine still supplies is the window's toolkit. On Linux that is the
WebKitGTK 4.1 stack and the appindicator library, plain dependencies of the
deb and the rpm; on Windows the WebView2 runtime, which the installer chains
Microsoft's bootstrapper for when the machine has none; on macOS WKWebView,
which is the system. The compile is native, so each package comes off a
machine of its own architecture. A checkout pays none of it: `pip install -e
client` runs on the checkout's interpreter, and `nclient gui` uses whatever
can import `gi`.

## A hub package carries its own agent package and fetches the others

Every hub package carries one agent package, the one of its own system,
architecture and package family, in `/var/lib/neutrino/hub/agent_cache/`.
That package installs the hub's own local agent, and enrolls and updates
every device of the same platform with no network of its own. The Arch
package carries none, because no agent package is published for Arch.

Another platform's agent package is fetched when a device of that platform
needs it, for an install over SSH or for a self-update:

1. The hub reads the platform's entry in `agent_packages.json`: the file
   name, the sha256 and the URL in its edition's release.
1. It downloads the file and checks it against the entry's sha256, which is
   the line that release's `SHA256SUMS` lists for the file.
1. It keeps a file that matches in the cache and refuses one that does not
   with `agent_package_sha256_mismatch`.

A platform the manifest does not name is refused with `agent_package_missing`,
never served another machine's build; the `cn` manifest names only the
platforms the `cn` release publishes. A `cn` release keeps only its latest
files, so a `cn` hub older than that release fails the fetch with
`agent_package_fetch_failed` until it is updated. A package dropped under
`config/devices/packages` wins over both. Where those files are and what an
upgrade does to them is in [files.md](files.md).
