# Install and development

Who does what when a hub is installed, and what a checkout does differently.
Three stages act on a real machine, each does one thing, and none of them does
another's.

| Stage | Does | Never does |
| --- | --- | --- |
| The package | Installs everything the hub cannot run without, and lays the payload down | Configures anything, starts anything |
| `nhub setup` | Asks what this machine is for, writes `config/`, renders, installs the units and starts the services | Installs a system package |
| The panel | Installs what somebody chose, and configures it | Runs before a hub is set up |

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
refuses with the command to install them if they are not — printed for the
package manager this machine actually runs — and it installs nothing itself,
on any path.

`setup` runs once. A box with a panel password is a box somebody configured,
and `nhub reset all` is how one goes back to fresh.

## The panel installs what somebody chose

Samba, Gitea, NetBird, podman and ZFS are capabilities, not parts of a
gateway. Each has a provisioner that installs its own system packages, its own
vendor binary and its own unit at the moment somebody asks for it, and each
declares its packages in its own `<PREFIX>_PACKAGES`. `git` belongs to Gitea
this way; the hub itself never runs it.

A provisioner that would do more than install — build a kernel module, add a
third-party repository, replace a system service — returns that as a consent
code and its parameters, and the panel asks before it proceeds.

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

The units on a real machine start the same command one process at a time —
`nhub run --only-web`, `--only-xray`, `--only-cliproxyapi` — so systemd keeps
deciding who each daemon runs as and what it may reach for, and a working copy
still runs the same code path.

**Deleting `hub_dev_root/` undoes the hub, not the machine.** The
configuration, the rendered files, the databases and the panel password go
with it, and the next `nhub --dev setup` starts from nothing — including the
run-once rule, which reads the password from that root. What stays is what
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
