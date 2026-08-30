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

The hub runs on Debian-family Linux. Each package carries its own Python
environment and touches nothing the system installed.

| File | For |
| --- | --- |
| `neutrino-hub_<version>_amd64.deb` | Any x86-64 box |
| `neutrino-hub_<version>_arm64.deb` | Raspberry Pi 4/5, and other 64-bit ARM boards |
| `neutrino-hub_<version>_armhf.deb` | 32-bit ARM boards |

```bash
sudo dpkg -i neutrino-hub_<version>_amd64.deb
sudo nhub setup
```

### Agent

The agent runs on the machines the hub manages. The Linux packages are
architecture-independent — one file covers x86-64, ARM64 and 32-bit ARM —
because the agent is pure Python with no dependencies beyond the standard
library.

| File | For |
| --- | --- |
| `neutrino-agent_<version>_all.deb` | Debian, Ubuntu, Raspberry Pi OS. Needs `python3`, which apt pulls in |
| `neutrino-agent-<version>.noarch.rpm` | Fedora, RHEL, CentOS |
| `neutrino-agent-<version>.pkg` | macOS 12 or newer, Intel and Apple Silicon. Carries its own Python |
| `neutrino-agent-<version>-setup.exe` | Windows 10 or newer. Carries its own Python |

```bash
sudo dpkg -i neutrino-agent_<version>_all.deb
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

One command, and it writes `SHA256SUMS` beside what it built. The agent's
package builds anywhere. The hub's is built inside `debian:12` — that needs
podman or docker, and `--agent-only` skips it.

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

macOS and Windows agent packages need those platforms and are built in CI.

## The release itself

Tagging is what triggers everything; nothing is built by hand.

```bash
git tag -a v0.4.0 -m "v0.4.0"
git push origin v0.4.0
```

CI builds every package listed above, generates `SHA256SUMS`, and opens a draft
release. Fill in the changelog, check the section headings still match what
shipped, and publish.

Draft, not published, is deliberate: the notes are written by a person who knows
what the release is for.
