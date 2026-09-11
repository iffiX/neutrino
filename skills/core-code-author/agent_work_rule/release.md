# Releases

A release is one tag, one version, and one set of packages built from it. The
hub, the agent and the client are versioned together and released together.

Wording rules for the entries themselves are in
[../coding_style/comment_style.md](../coding_style/comment_style.md); who may
commit and when is in [commit.md](commit.md).

## One version, no compatibility window

The hub, the agent and the client of the same version work together. Nothing
else is supported, and no compatibility table is kept.

This is a deliberate choice, not an omission. The agent is small and installs
in seconds, so upgrading it is cheaper than reasoning about which combinations
work. A hub that sees an agent reporting a different version says so on the
device card and offers to upgrade it; it does not try to interoperate.

Every package reads its version from package metadata. It is never written
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

Three sections, one per package, so nobody downloads the wrong thing. Name the
platform in words, not only in the filename.

### Hub

The hub runs on Debian, Fedora and Arch family Linux. Each package carries its
own Python environment and touches nothing the system installed; everything
else it needs is named in the package's dependencies, so installing the file
installs the appliance's prerequisites with it.

There is no 32-bit ARM package. The boards that would need one have no
prebuilt wheels for the hub's dependencies, so the environment would have to
be compiled from source under emulation. Arch Linux is x86-64 only; Arch Linux
ARM is another project.

| File | For |
| --- | --- |
| `neutrino-hub_<version>_amd64.deb` | Debian, Ubuntu, Raspberry Pi OS on x86-64 |
| `neutrino-hub_<version>_arm64.deb` | Raspberry Pi 4/5, and other 64-bit ARM boards |
| `neutrino-hub-<version>-1.x86_64.rpm` | Fedora, RHEL, AlmaLinux, Rocky |
| `neutrino-hub-<version>-1.aarch64.rpm` | The same on ARM64 |
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

Enabling it in the same transaction does not work: the new repository's
metadata is not read until the transaction that added it has finished, so it
is its own line, and only on RHEL rebuilds. Fedora carries all three itself.

### Agent

The agent runs on the Linux machines the hub manages, as root and headless:
it draws no window and listens on nothing. Each package carries its own
interpreter under `/opt/neutrino_agent` and the RustDesk host, and depends on
no distribution package named `python`.

| File | For |
| --- | --- |
| `neutrino-agent_<version>_amd64.deb` | Debian, Ubuntu, Raspberry Pi OS on x86-64 |
| `neutrino-agent_<version>_arm64.deb` | The same on ARM64 |
| `neutrino-agent-<version>-1.x86_64.rpm` | Fedora, RHEL, AlmaLinux, Rocky |
| `neutrino-agent-<version>-1.aarch64.rpm` | The same on ARM64 |

There is no Windows or macOS agent: what a person's machine runs is the
client. 32-bit ARM is not published, because no interpreter build is.

```bash
sudo apt install ./neutrino-agent_<version>_amd64.deb
sudo nagent connect '<enrollment link from the Devices page>'
```

Most people never download these: the hub carries them, and installs the right
one over SSH from the Devices page.

### Client

The client runs in a person's own session, never as root, on Linux, Windows
and macOS. It is compiled with Nuitka, so the packages carry no interpreter
of their own; each carries cc-switch and the RustDesk viewer. The Linux
packages depend on the WebKitGTK stack and the appindicator library for the
window and the tray.

| File | For |
| --- | --- |
| `neutrino-client_<version>_amd64.deb` | Debian, Ubuntu on x86-64 |
| `neutrino-client_<version>_arm64.deb` | The same on ARM64 |
| `neutrino-client-<version>-1.x86_64.rpm` | Fedora, RHEL, AlmaLinux, Rocky |
| `neutrino-client-<version>-1.aarch64.rpm` | The same on ARM64 |
| `neutrino-client-<version>-windows-amd64.msi` | Windows 10 or newer, x86-64 |
| `neutrino-client-<version>-macos-arm64.pkg` | macOS on Apple silicon |

Windows is x86-64 only: cc-switch publishes no Windows ARM64 build, so there
is nothing to carry for that machine. macOS is Apple silicon only, which is
what the build runner is.

```bash
sudo apt install ./neutrino-client_<version>_amd64.deb
nclient connect '<client link from the Clients page>'
```

### Source archive

`neutrino-<version>-source.tar.gz` is this tree at the tagged commit, with
`third_party/` beside it holding the upstream archives of everything the
packages carry, at the exact tags the binaries were built from: RustDesk,
EasyTier, NetBird, Xray-core, CLIProxyAPI and cc-switch. It exists because
some of those are copyleft and a binary release owes its source; it is not
what anybody installs from. GitHub's own `Source code (zip)` and `(tar.gz)`
carry the tree alone.

## Every asset carries a checksum

`SHA256SUMS` is attached alongside the packages and covers every one of them.
The hub verifies it before installing an agent on a device, so a truncated or
tampered download fails loudly rather than half-installing.

## Building the packages

```bash
python3 packaging/build_release.py --output-dir dist/
```

One command builds everything for the host's architecture and writes
`SHA256SUMS` beside it. `--only` builds one part: `hub`, `agent`, `client`,
`sources`, or `checksums` over a directory the parts were collected into,
which is how the tag workflow splits the work across runners. `--families`
chooses the distribution families; the agent and the client have no Arch
package and say so rather than failing.

The hub and the agent are built in containers of the target family, because
each carries an interpreter compiled against that family's C libraries, so
podman or docker is not optional. `--architecture arm64` runs those containers
under emulation; the host needs QEMU registered with binfmt_misc first.

The client is compiled, and Nuitka under emulation takes hours, so its Linux
packages are built on a machine of their own architecture. The Windows
`.msi` needs Windows and WiX (`dotnet tool install --global wix`):
`client/packaging/build_msi.py` builds it, and `--stage-only` writes and
checks the whole payload without one. The macOS `.pkg` needs macOS:
`client/packaging/build_pkg.py`.

The agent packages a hub package carries are built inside the hub's own build
container and land under `/var/lib/neutrino/agent_cache/`, with
`agent_packages.json` beside them naming every platform this release publishes
an agent for, the file name each is published under, and its hash. A hub
serving devices of a second architecture fetches that platform's package once
from the release the manifest names; `--agent-package-url-base` stamps those
URLs, and a build given none carries the entries it seeded and refuses the
rest by name. A package dropped under `config/devices/packages` still wins
over both.

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

## The release itself

Tagging is what triggers everything; nothing is built by hand.

```bash
git tag -a v0.4.0 -m "v0.4.0"
git push origin v0.4.0
```

`.github/workflows/release.yml` builds the hub and the agent for both
architectures in containers, the client's Linux packages on native runners of
each architecture, the Windows installer, the macOS installer and the source
archive, generates `SHA256SUMS` over all of it, and opens a draft release. The
Windows job installs what it built, runs the client from it and uninstalls
again; the macOS job installs its package and runs `nclient` from it; a broken
installer fails the build rather than the person who downloads it. Fill in the
changelog, check the section headings still match what shipped, and publish.

Running the same workflow from the Actions tab builds the packages and attaches
them as artifacts without creating a release, which is how a change to the
pipeline is tried before a tag depends on it.

Draft, not published, is deliberate: the notes are written by a person who knows
what the release is for.
