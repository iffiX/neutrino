# Install

Who does what when a hub is installed. Three stages act, each does one thing,
and none of them does another's.

| Stage | Does | Never does |
| --- | --- | --- |
| The package | Installs everything the hub cannot run without, and lays the payload down | Configures anything, starts anything |
| `nhub setup` | Asks what this machine is for, writes `config/`, renders, starts the services | Installs a system package |
| The panel | Installs what somebody chose, and configures it | Runs without a hub already set up |

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

Its steps write files under the five roots in [files.md](files.md), render
every daemon's configuration from `config/`, and enable and start the units.
It checks that the dependencies are present and refuses with the command to
run if they are not — it does not install them, on any path.

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

## A checkout has no package

Development runs from the tree rather than from a package, so nothing
installed the dependencies. `nhub setup` names them and stops; installing them
is one command, and it is the developer's to run.

The interpreter is the same story upside down: a package carries its own, so
it needs no system Python at all, while a checkout builds a virtual
environment because there is nobody else to do it.
