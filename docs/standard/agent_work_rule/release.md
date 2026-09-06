# Releases

A release is one tag, one version, and one set of packages built from it. The
hub and the agent are versioned together and released together.

Wording rules for the entries themselves are in
[../coding_style/comment_style.md](../coding_style/comment_style.md); who may
commit and when is in [commit.md](commit.md).

## One version, no compatibility window

The hub and the agent of the same version work together. Nothing else is
supported, and no compatibility table is kept.

This is a deliberate choice, not an omission. The agent is small and installs
in seconds, so upgrading it is cheaper than reasoning about which combinations
work. A hub that sees an agent reporting a different version says so on the
device card and offers to upgrade it; it does not try to interoperate.

Both packages read their version from package metadata. It is never written
into the source twice.

## Tags

```
v<major>.<minor>.<patch>
```

`v0.4.0`, `v1.2.3`. No prefixes per component, no separate agent tags — one tag
builds everything.

- **major** — the config format or the hub-agent protocol changed in a way that
  a fresh install would not notice but an upgrade would. Say so at the top of
  the notes.
- **minor** — a feature.
- **patch** — fixes only.

Pre-releases append `-rc1`, `-rc2`. They are marked pre-release on GitHub so
the hub's own update check ignores them.

## Changelog entries

One line per change, prefixed by what kind it is, in this order:

```
feature: ...
fix: ...
docs: ...
```

Nothing else gets a section. Refactors, test changes and dependency bumps do
not appear — a reader of release notes is asking what changed for them, and
those did not.

Each line is a sentence in the same register as a commit message: what it does
now, not what was wrong before.

```text
# GOOD
feature: devices report GPU utilisation and per-process memory
feature: cc-switch is installed and pointed at the hub from the panel
fix: restoring a backup no longer accepts paths outside config/
fix: a device's SSH host key is checked on every connection, not just the first
docs: the documentation style now covers reference, usage and development guides

# BAD — vague, or written from the developer's side
fix: various bug fixes and improvements
fix: fixed the bug in the settings router where the tarfile member check was
     insufficient because it only used startswith
feature: refactored the device drawer
```

A release with nothing under a heading omits the heading.

## What goes in a release

Two sections, so nobody downloads the wrong thing. Name the platform in words,
not only in the filename.

### Hub

The hub runs on Debian, Fedora and Arch family Linux. Each package carries its
own Python environment and touches nothing the system installed; everything
else it needs is named in the package's dependencies, so installing the file
installs the appliance's prerequisites with it.

There is no 32-bit ARM package. The boards that would need one — Allwinner H3,
Raspberry Pi 2 and older — have no prebuilt wheels for the hub's dependencies,
so the environment would have to be compiled from source under emulation.

| File | For |
| --- | --- |
| `neutrino-hub_<version>_amd64.deb` | Debian, Ubuntu, Raspberry Pi OS on x86-64 |
| `neutrino-hub_<version>_arm64.deb` | Raspberry Pi 4/5, and other 64-bit ARM boards |
| `neutrino-hub-<version>-1.x86_64.rpm` | Fedora, RHEL, AlmaLinux, Rocky |
| `neutrino-hub-<version>-1-x86_64.pkg.tar.zst` | Arch, EndeavourOS, Manjaro |

```bash
sudo apt install ./neutrino-hub_<version>_amd64.deb      # Debian family
sudo dnf install ./neutrino-hub-<version>-1.x86_64.rpm   # Fedora family
sudo pacman -U neutrino-hub-<version>-1-x86_64.pkg.tar.zst
sudo nhub setup
```

RHEL 9 and its rebuilds need EPEL enabled first, because `fail2ban`,
`arp-scan` and `vnstat` are there rather than in the base repositories:

```bash
sudo dnf install -y epel-release
```

Enabling it in the same transaction does not work — the new repository's
metadata is not read until the transaction that added it has finished — so it
is its own line, and only on RHEL rebuilds. Fedora carries all three itself.

### Agent

The agent runs on the machines the hub manages. Every package carries its own
interpreter and the Python bindings its window draws through, so there is one
per platform and machine and none of them asks for a Python.

| File | For |
| --- | --- |
| `neutrino-agent_<version>_amd64.deb` | Debian, Ubuntu, Raspberry Pi OS on x86-64 |
| `neutrino-agent_<version>_arm64.deb` | The same on ARM64 |
| `neutrino-agent-<version>-1.x86_64.rpm` | Fedora, RHEL, CentOS on x86-64 |
| `neutrino-agent-<version>-1.aarch64.rpm` | The same on ARM64 |
| `neutrino-agent-<version>-amd64.msi` | Windows 10 or newer, x86-64 |
| `neutrino-agent-<version>-arm64.msi` | The same on ARM64 |
| `neutrino-agent-<version>.pkg` | macOS 12 or newer, one universal build for Intel and Apple Silicon |

32-bit ARM is not published: no interpreter build is, and neither are the
bindings. The `.pkg` is not built yet.

The Linux packages install under `/opt/neutrino_agent`, not into
site-packages: what is there is an interpreter of the agent's own, and
`/usr/bin/nagent` and the unit run it. They depend on C libraries only —
`gir1.2-webkit2-4.1` on the Debian family and `webkit2gtk4.1` on the RHEL
family, each pulling the rest of the stack — and on no distribution package
named `python`. A headless machine carries the web view too, deliberately: one
package, one dependency field, no second build to choose between.

The Windows installer carries python.org's embeddable interpreter, pinned by
hash, and registers a real service: the agent's own entry answers the service
control manager over a ctypes handshake, so nothing needs a wrapper binary.
It also carries Microsoft's WebView2 bootstrapper and runs it when the
machine's registry says the Evergreen runtime is absent, which is LTSC and
Server editions.

Each package is tens of megabytes where the old architecture-independent one
was tens of kilobytes. That is what a window costs, and it is paid once per
machine.

```bash
sudo apt install ./neutrino-agent_<version>_amd64.deb
nagent connect https://<hub-address>
```

Most people never download these: the hub fetches the right one and installs it
over SSH from the Devices page.

### Source code

GitHub attaches `Source code (zip)` and `Source code (tar.gz)` to every release
on its own. They are the tagged tree, and they are not what anybody should
install from — building the hub package from source needs a Node toolchain for
the panel and a matching build environment for the embedded Python. Point
people at the packages above.

## Every asset carries a checksum

`SHA256SUMS` is attached alongside the packages. The hub verifies it before
installing an agent on a device, so a truncated or tampered download fails
loudly rather than half-installing.

## Building the packages

```bash
python3 packaging/build_release.py --output-dir dist/
```

One command, and it writes `SHA256SUMS` beside what it built. Both packages
are built in containers now — the agent's as well, since it compiles the
window's bindings against the family's own C libraries — so podman or docker
is not optional for either.

`--architecture arm64` builds for the other architecture by running those
containers under emulation; the host needs QEMU registered with binfmt_misc
first. `--only` builds one part at a time — `hub`, `agent`, or `checksums`
over a directory the parts were collected into — which is how the tag workflow
splits the work across runners. `--families` chooses which; the agent has no
Arch package and says so rather than failing.

The agent packages a hub package carries are built inside the hub's own build
container, for the hub's own machine. A hub serving devices of a second
architecture is given those packages by hand, under
`config/devices/packages`, where they win over the baked ones; the hub picks
by the machine each device reports.

Two things bind a hub package to the machine that built it, and both are why
the container is not optional:

- **The virtual environment carries no standard library.** It has a copy of
  the interpreter binary, so the target must have the very version it was
  built against. This is why the package depends on `python3.11` rather than
  `python3 (>= 3.11)`: the looser form is satisfied by 3.12 and then fails at
  run time with *could not find platform independent libraries*.
- **glibc only works forwards.** Built on Ubuntu 26.04 the package wants
  GLIBC 2.38 and installs on nothing older; built on Debian 12 it wants 2.35
  and installs on Debian 12, Ubuntu 22.04 and everything newer.

Building the hub on a developer's own machine produces a package that installs
only on machines like it. That is the mistake this container exists to stop.

The Windows `.msi` needs Windows and WiX (`dotnet tool install --global
wix`); `agent/packaging/build_msi.py` builds it, and `--stage-only` writes and
checks the whole payload without one. The macOS `.pkg` needs macOS:
`agent/packaging/build_pkg.py` expands python.org's universal2 framework,
moves its install names off `/Library/Frameworks` and signs what it moved.

## The release itself

Tagging is what triggers everything; nothing is built by hand.

```bash
git tag -a v0.4.0 -m "v0.4.0"
git push origin v0.4.0
```

`.github/workflows/release.yml` builds the hub and the agent for both
architectures, and the Windows installer, generates `SHA256SUMS`, and opens a
draft release. The Windows job installs what it built, runs the agent from it
and uninstalls again, so a broken installer fails the build rather than the
person who downloads it. Fill in the
changelog, check the section headings still match what shipped, and publish.

Running the same workflow from the Actions tab builds the packages and attaches
them as artifacts without creating a release, which is how a change to the
pipeline is tried before a tag depends on it.

Draft, not published, is deliberate: the notes are written by a person who knows
what the release is for.
