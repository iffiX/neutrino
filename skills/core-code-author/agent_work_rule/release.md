# Releases

A release is one tag, one version, and one set of packages built from it. The
hub, the agent, the desktop client and the two phone apps are versioned
together and released together.

Wording rules for the entries themselves are in
[../coding_style/comment_style.md](../coding_style/comment_style.md); who may
commit and when is in [commit.md](commit.md).

## One tag, every package, compatibility by protocol number

One tag builds the hub, the agent, the desktop client and the Android app at
one version; the iOS app is paused ("iOS app" below). Whether an agent or a client works with a hub is decided by `PROTOCOL`, the number each
package speaks; the hub accepts every number from `PROTOCOL_MIN` to its own
([../design/protocol.md](../design/protocol.md), "Versioning"). A peer outside
that range is rejected at the door with `protocol_too_old` or
`protocol_too_new` and keeps its binding.

An agent whose hub names a newer `software` upgrades itself from the package
the hub keeps; a client, on a computer or a phone, is upgraded when its person
installs the new package.

Every package reads its version from package metadata. It is never written
into the source twice.

## Two editions from one source

An edition is the set of features a package is built with. One tag builds
every package in two editions from the one source on GitHub, at the same
version and the same `PROTOCOL`:

| Edition | Features | Released on |
| --- | --- | --- |
| `intl` | every feature | GitHub, `https://github.com/iffiX/neutrino/releases`, every release kept |
| `cn` | every feature except the proxy and NetBird | Gitee, `https://gitee.com/iffiX/neutrino/releases`, the latest release only |

The mainland edition does not carry the proxy or NetBird:

| Package | What `cn` leaves out |
| --- | --- |
| hub | the proxy: xray, the proxy TUN and its `tun2socks`, the geodata, the **Proxy** page, the proxy scopes of the network modes, and the `side_gateway` mode; NetBird: its module, its unit and its card on the **Access** page |
| desktop client | NetBird and the daemon that runs it |
| Android app | the NetBird core |
| agent | nothing |

`cn` keeps EasyTier, the relay, the client's files adapter, VS Code,
code-server, CloudCLI, Gitea, Samba, Podman, ZFS and the AI gateway.

The build writes the edition into each package as `EDITION`, `intl` or `cn`,
beside the version in `neutrino_hub/_version.py`,
`neutrino_agent/_version.py` and `neutrino_client/_version.py`, and into the
Android app as `BuildConfig.EDITION`. A checkout has no stamp and reads
the file `EDITION` at the repository's root, one line holding `intl` in the
GitHub repository; the Android build reads the same file. The stamp, or
that file, chooses where a package fetches from
([../design/install_and_dev.md](../design/install_and_dev.md), "Where each
edition fetches from"). Which features a package has follows from the files
its tree holds ([../design/architecture.md](../design/architecture.md), "A
left-out feature is reached through one table").

Every script under `packaging/build/` takes `--edition intl` or
`--edition cn`, `intl` when absent; a build that runs in a container passes
it in as `NEUTRINO_EDITION`. The three phone core scripts,
`build_core_netbird.py`, `build_core_easytier.py` and
`build_core_rustdesk.py`, take none: a core is the same in both editions,
and its cache is named by the digest of the script's own bytes, so an
option added to them would rebuild every core. A package of an edition upgrades only to a
package of the same edition, because each edition's release is the only one
its update check and its install scripts read.

## The mainland source tree

`PACKAGING_CN_LEFT_OUT_PATHS` in `packaging/shared/constants.py` lists every
repository path that exists for a left-out feature alone: its packages, their
mirrored tests, its frontend files, its examples and unit templates, and the
scripts that build its programs. It is the one list of what `cn` leaves out;
no other file repeats it.

`packaging/build/build_sources.py --edition cn` writes
`neutrino-<version>-cn-source.tar.gz`. It holds the tree at the tagged
commit without the listed paths, with the root `EDITION` file holding
`cn` and `EDITION` stamped `cn` in `install.sh` and `install.ps1`, so a clone
of the Gitee repository, a development run from it and its install scripts
all read `cn`, and `third_party/` holding the upstream
source of what the `cn` packages carry. Its `README.md` is the
repository's `README.zh-CN-Gitee.md`, the page Gitee shows, and its root
holds no other README, so a tree holding `README.zh-CN-Gitee.md` is a full
tree. Every `cn` package is built from
this tree, unpacked, and never from the full checkout.

A `cn` build exits with one sentence naming the path when any listed path
exists in its tree, and an `intl` build exits the same way when one is
missing. A `cn` package therefore holds no left-out file, and the mainland
tree builds no `intl` package.

## Tags

```
v<major>.<minor>.<patch>
```

`v0.4.0`, `v1.2.3`. No prefixes per component and no separate agent tags: one
tag builds everything.

- **major**: the config format changed in a way a fresh install does not
  notice and an upgrade does. Say so at the top of the notes.
- **minor**: a feature.
- **patch**: fixes only.

The protocol number binds the tag one way. A change to `PROTOCOL` requires a
new minor before 1.0 and a new major after it; a new minor or major can keep
the number; a patch never changes `PROTOCOL`
([../design/protocol.md](../design/protocol.md), "Versioning").

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
not appear: a reader of release notes is asking what changed for them, and
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

One section per package, so nobody downloads the wrong thing. Name the
platform in words, not only in the filename.

| Platform | Hub | Agent | Client | Editions |
| --- | --- | --- | --- | --- |
| Debian, Ubuntu, Raspberry Pi OS, amd64 and arm64 | `.deb` | `.deb` | `.deb` | `intl`, `cn` |
| Fedora, RHEL, AlmaLinux, Rocky | `.rpm` | `.rpm` | `.rpm` | `intl` |
| Arch, EndeavourOS, Manjaro | `.pkg.tar.zst` | none | none | `intl` |
| Windows 10 and 11, x64 | `.msi`, `server` mode | `.msi` | `.msi` | `intl`, `cn` |
| macOS on Apple silicon | `.pkg`, `server` mode | `.pkg` | `.pkg` | `intl`, `cn` |
| macOS on Intel | `.pkg`, `server` mode | `.pkg` | `.pkg` | `intl` |
| Android 8 or newer | none | none | `.apk` | `intl`, `cn` |
| iOS | none | none | paused since 2026-10-03 | none |

`install.sh` and `install.ps1` are published beside the packages and install
any of the three by one command
([../design/install_and_dev.md](../design/install_and_dev.md)). Both
editions name their files by the same patterns; the release a file comes
from says its edition.

### Hub

The hub runs on Debian, Fedora and Arch family Linux. Each package carries its
own Python environment and touches nothing the system installed; everything
else it needs is named in the package's dependencies, so installing the file
installs the appliance's prerequisites with it. On macOS and Windows the hub
runs in `server` mode, and its package carries the hub compiled by Nuitka
with every program it drives, `tun2socks` among them in `intl` for the
proxy scopes that divert the machine's own packets there.

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
| `neutrino-hub-<version>-windows-amd64.msi` | Windows 10 1809 or newer, x86-64 |
| `neutrino-hub-<version>-macos-arm64.pkg` | macOS 12.3 or newer on Apple silicon |
| `neutrino-hub-<version>-macos-amd64.pkg` | macOS 12.3 or newer on Intel |

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

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

The agent runs on the machines the hub manages, as root or LocalSystem and
headless: it draws no window and listens on nothing. Each Linux package
carries its own interpreter under `/opt/neutrino/agent` and the RustDesk
host, and depends on no distribution package named `python`. The Windows
and macOS installers include the agent compiled with Nuitka and upstream's
RustDesk, and run the terminal and the shared desktop. No agent package
carries cc-switch: the agent fetches it from the hub when the machine's AI
tools need it, at the pin the client's packages carry.

| File | For |
| --- | --- |
| `neutrino-agent_<version>_amd64.deb` | Debian, Ubuntu, Raspberry Pi OS on x86-64 |
| `neutrino-agent_<version>_arm64.deb` | The same on ARM64 |
| `neutrino-agent-<version>-1.x86_64.rpm` | Fedora, RHEL, AlmaLinux, Rocky |
| `neutrino-agent-<version>-1.aarch64.rpm` | The same on ARM64 |
| `neutrino-agent-<version>-windows-amd64.msi` | Windows 10 1809 or newer, x86-64 |
| `neutrino-agent-<version>-macos-arm64.pkg` | macOS 12.3 or newer on Apple silicon |
| `neutrino-agent-<version>-macos-amd64.pkg` | macOS 12.3 or newer on Intel |

32-bit ARM is not published, because no interpreter build is. Windows is
x86-64 only, because RustDesk publishes no Windows ARM64 build.

```bash
sudo apt install ./neutrino-agent_<version>_amd64.deb
sudo nagent join '<enrollment link from the Devices page>'
```

Most people never download a Linux agent package: the hub installs the
right one over SSH from the Devices page, from the one its own package
carries or from its edition's release. The two installers are downloaded and
run on the machine, then `nagent join` runs in a terminal opened as
administrator on Windows and under `sudo` on macOS.

### Client

The client runs in a person's own session, never as root, on Linux, Windows
and macOS. It is compiled with Nuitka, so the packages carry no interpreter
of their own; each carries cc-switch and the RustDesk viewer. The Windows
packages of both editions also carry tun2socks for the files adapter. Its
pin is `PACKAGING_TUN2SOCKS_*` in `packaging/shared/constants.py`, which the
mainland tree holds, and the hub's macOS and Windows packages of `intl` take
the same pin for the proxy's TUN. The Linux
packages depend on the WebKitGTK stack and the appindicator library for the
window and the tray.

| File | For |
| --- | --- |
| `neutrino-client_<version>_amd64.deb` | Debian, Ubuntu on x86-64 |
| `neutrino-client_<version>_arm64.deb` | The same on ARM64 |
| `neutrino-client-<version>-1.x86_64.rpm` | Fedora, RHEL, AlmaLinux, Rocky |
| `neutrino-client-<version>-1.aarch64.rpm` | The same on ARM64 |
| `neutrino-client-<version>-windows-amd64.msi` | Windows 10 or newer, x86-64 |
| `neutrino-client-<version>-macos-arm64.pkg` | macOS 12.3 or newer on Apple silicon |
| `neutrino-client-<version>-macos-amd64.pkg` | macOS 12.3 or newer on Intel |

Windows is x86-64 only: cc-switch publishes no Windows ARM64 build, so there
is nothing to carry for that machine. Every macOS package of `intl` is
published for both architectures, `arm64` built on GitHub's `macos-15`
runner and `amd64` on `macos-15-intel`, and `cn` publishes `arm64`
alone; how long the Intel one lasts is in
[../design/min_support.md](../design/min_support.md).

```bash
sudo apt install ./neutrino-client_<version>_amd64.deb
nclient join '<client link from the Clients page>'
```

### Android app

The Android app is the client on a phone. It carries the NetBird, EasyTier
and RustDesk cores compiled from their pinned sources, and is licensed
AGPL-3.0 by `client/android/LICENSE`. A tag build and a `workflow_dispatch` build are
signed with the project's release key, so a phone upgrades from one to the
other in place; a pull request build uses the debug key. The workflow
checks the signing certificate's
fingerprint before it attaches the file. In both editions the apk stores its
native libraries compressed (`packaging.jniLibs.useLegacyPackaging = true`
in `client/android/app/build.gradle.kts`), which halves the file; the phone
unpacks them at install. The `cn` apk has no NetBird core.

| File | For |
| --- | --- |
| `neutrino-client-<version>-android.apk` | Android 8 or newer, arm64-v8a |

The person installs the `.apk` on the phone, then scans the QR code on the
**Clients** page or pastes the client link.

### iOS app

The iOS app is paused since 2026-10-03: `client/ios/` is neither built nor
released, and keeps its `LICENSE`. It is weighed again when the repository
passes 300 stars, when several issues ask for an iOS app, or when somebody
submits iOS code.

### Install scripts

| File | For |
| --- | --- |
| `install.sh` | macOS and Linux: `curl -fsSL <url> \| sh -s -- hub\|agent\|client` |
| `install.ps1` | Windows: `irm <url> \| iex` in an administrator PowerShell |

Each script holds its edition as `EDITION` near its top, `intl` in the
committed file and `cn` in the mainland tree. Both check every package
against their release's `SHA256SUMS`.

| Edition | Where a script is fetched from | Where it fetches packages from |
| --- | --- | --- |
| `intl` | `https://github.com/iffiX/neutrino/releases/latest/download/` | the same address, or `releases/download/<tag>/` for a named version |
| `cn` | `https://gitee.com/iffiX/neutrino/raw/main/packaging/install/` | `https://gitee.com/iffiX/neutrino/releases/download/<tag>/`, the tag read first from `https://gitee.com/api/v5/repos/iffiX/neutrino/releases/latest` |

Gitee has no fixed address for the latest release's files, which is why the
`cn` script reads the tag from the API before it downloads.

### Source archive

`neutrino-<version>-source.tar.gz` is this tree at the tagged commit, with
`third_party/` beside it holding the upstream archives of everything the
packages carry, at the exact tags the binaries were built from: RustDesk,
EasyTier, NetBird, Xray-core, CLIProxyAPI and cc-switch. It exists because
some of those are copyleft and a binary release owes its source; it is not
what anybody installs from. GitHub's own `Source code (zip)` and `(tar.gz)`
carry the tree alone.

`neutrino-<version>-cn-source.tar.gz` is the same for `cn`: the mainland tree
of "The mainland source tree", with the upstream source of what the `cn`
packages carry. It is attached to the Gitee release and to no GitHub release,
and every `cn` package is built from it.

## Every asset carries a checksum

`SHA256SUMS` is attached alongside the packages and covers every one of them,
and the two install scripts. Each edition's release has its own, covering
its own files.
The hub verifies an agent package before installing it on a device, so a
truncated or tampered download fails loudly rather than half-installing.

## Building the packages

Every target is one script under `packaging/build/`, and each runs the same
way on a machine that can build it as in the tag workflow. The docstring at
the top of each names the hosts it runs on, and the script stops with one
sentence when a tool it needs is missing.

| Script | Builds | Runs on |
| --- | --- | --- |
| `build_hub.py` | the hub's `.deb`, `.rpm` and Arch package | Linux with podman or docker, after `npm run build` in `hub/frontend` |
| `build_agent.py` | the agent's `.deb` and `.rpm` | Linux with podman or docker |
| `build_client_desktop.py` | the client's `.deb` and `.rpm` | Linux of the target architecture, with podman or docker |
| `build_agent_windows.py`, `build_client_windows.py` | the two `.msi` | Windows with Python 3.13 and WiX 6 |
| `build_agent_macos.py`, `build_client_macos.py` | the two `.pkg` | macOS with Python 3.13, of the architecture it builds |
| `build_hub_windows.py` | the hub's `.msi`, compiled by Nuitka, with the programs it drives and the agent's `.msi` in its cache | Windows with Python 3.13 and WiX 6 |
| `build_hub_macos.py` | the hub's `.pkg`, the same way | macOS with Python 3.13, of the architecture it builds |
| `build_client_android.py` | the `.apk`, with its cores | Linux or macOS with JDK 17 and the Android SDK |
| `build_client_ios.py` | nothing: it prints the `xcodebuild` steps; paused with the app | macOS with Xcode |
| `build_core_netbird.py`, `build_core_easytier.py`, `build_core_rustdesk.py` | one core the phones carry | Linux |
| `build_sources.py`, `build_checksums.py` | the source archive, or with `--edition cn` the mainland source tree; `SHA256SUMS` over a directory | anywhere |
| `build_cc_switch.py` | the pinned cc-switch release files under upstream's names, each checked against its pin, and their licence | anywhere |

```bash
python3 packaging/build/build_agent.py --architecture amd64 --output-dir dist/
python3 packaging/build/build_hub.py --architecture amd64 --output-dir dist/ \
    --agent-packages dist/
python3 packaging/build/build_checksums.py --output-dir dist/
```

Every asset name comes from `PACKAGING_ASSET_PATTERNS` in
`packaging/shared/constants.py`, whose `msi` and `macos_pkg` keys name the
Windows and macOS packages; the `pkg` key stays Arch's.

`--families` chooses the distribution families of the Linux builds; the agent
and the client have no Arch package and say so rather than failing.
`packaging/ci/check.py <target> <artifact>` installs a built package where it
runs, checks that it works, and removes it again; the workflow runs it after
every build.

The cores the phone apps carry are cached under
`~/.cache/neutrino/cores/<core>-<commit>-<abi>-<recipe>/`, the recipe being
eight hex digits of the digest of the core's script and patch, and the
workflow's cache uses the same names, so a core is built once per pinned
commit and recipe.

The hub and the agent are built in containers of the target family, because
each carries an interpreter compiled against that family's C libraries, so
podman or docker is not optional. `--architecture arm64` runs those containers
under emulation; the host needs QEMU registered with binfmt_misc first.

The client is compiled, and Nuitka under emulation takes hours, so its Linux
packages are built on a machine of their own architecture. The Windows `.msi`
needs Windows and WiX (`dotnet tool install --global wix`):
`packaging/build/build_client_windows.py` builds it, and `--stage-only` writes
and checks the whole payload without one. Either way it takes `--packet-dll`,
the stand-in `packet.dll` built from `client/desktop/packaging/packet_stub.c`
(MSVC in the release workflow, MinGW for the lab box), and refuses to build
without it. The macOS `.pkg` needs macOS:
`packaging/build/build_client_macos.py`.

The agent's `.msi` is built on Windows by
`packaging/build/build_agent_windows.py` and its `.pkg` on a Mac by
`packaging/build/build_agent_macos.py`, from the same Nuitka, WiX, pkg and
RustDesk builders under `packaging/shared/` the client's use.

A hub package carries one agent package: the one of its own system,
architecture and package family, of the same edition and the same workflow
run, under `/var/lib/neutrino/hub/agent_cache/`. Both editions follow this
rule.

| Hub package | The agent package it carries |
| --- | --- |
| `.deb` of an architecture | the agent `.deb` of that architecture |
| `.rpm` of an architecture | the agent `.rpm` of that architecture |
| `.msi` | the agent `.msi` |
| `.pkg` of an architecture | the agent `.pkg` of that architecture |
| Arch `.pkg.tar.zst` | none, because no agent package is published for Arch |

The build reads every agent package of its edition and writes
`agent_packages.json` beside the cache. The manifest names every platform its
edition's release publishes an agent for, the file name each is published
under, and its sha256, which is the line the same release's `SHA256SUMS`
lists for that file. `--agent-package-url-base` stamps where the release
publishes them: `https://github.com/iffiX/neutrino/releases/download/<tag>`
for `intl`, `https://gitee.com/iffiX/neutrino/releases/download/<tag>` for
`cn`. A hub fetches another platform's package from there the first time a
device of that platform needs it
([../design/install_and_dev.md](../design/install_and_dev.md)). A build given
no URL base carries the entry it seeded and refuses the rest by name. A
package dropped under `config/devices/packages` still wins over both.

What binds a hub package to the machines it installs on is glibc, which only
works forwards. Nothing is compiled during the build: the pip install passes
`--only-binary=:all:`, so the floor is the highest manylinux tag pip resolves
for the dependencies, together with the upstream binaries the package installs.
After the tree is staged, `require_glibc_floor` reads every ELF in it and fails
the build when one names a version above `PACKAGING_GLIBC_FLOOR`. The floor of
each package, and the one item that sets it, is in
[../design/min_support.md](../design/min_support.md).

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
each architecture, the Windows installers, the macOS installers for both
architectures, the apk and the source archive, generates `SHA256SUMS` over all
of it and the two install scripts, and opens a draft release. Each job runs one `packaging/build/` script and then
`packaging/ci/check.py` on what it built, so a broken package fails the build
rather than the person who downloads it: every Linux package is installed in
a fresh container of its family and its command answers `--version`; the
client's Windows job installs the `.msi`, runs the client from it and
uninstalls again, and its macOS job installs the `.pkg` and runs `nclient`
from it; the agent's Windows job installs its `.msi`, checks that
`neutrino_agent` and `RustDesk` run, and uninstalls again, and its macOS job
installs the `.pkg`, checks the LaunchDaemon runs, and removes it; the apk is
installed and launched once in an emulator; the hub's macOS and Windows jobs
set a hub up from the package and from the install script
([../design/tests.md](../design/tests.md)). The hub jobs wait for the agent's.

The same workflow builds `cn`. The `sources` job also writes the mainland
source tree, and each build job runs a second time for `cn`, only for the
platforms the `cn` release carries: it downloads that tree, unpacks it, and
runs its `packaging/build/` script inside it with `--edition cn`, then
`packaging/ci/check.py`. The `draft_cn` job fetches the pinned cc-switch
release files with `build_cc_switch.py`, writes `SHA256SUMS` over the `cn`
packages, the `cn` install scripts, the mainland source tree and those
files, runs
`packaging/ci/publish_cn.py --check-only` over them, and uploads them as the
workflow artifact `release_dist_cn`. Nothing of `cn` is attached to the
GitHub release.

Fill in the changelog, check the section headings still match what shipped,
and publish with `.github/workflows/publish.yml`, which takes the tag and the
notes. Its `publish` job publishes the GitHub draft, and its `publish_cn` job
then publishes `cn` on Gitee ("The mainland release on Gitee").

Running the same workflow from the Actions tab builds the packages and attaches
them as artifacts without creating a release, which is how a change to the
pipeline is tried before a tag depends on it.

Draft, not published, is deliberate: the notes are written by a person who knows
what the release is for.

## The mainland release on Gitee

`https://gitee.com/iffiX/neutrino` holds the mainland tree and the files of
the latest `cn` release. GitHub is the one source; nothing is built on Gitee
and nothing is committed there by hand. The install scripts on its `main`
branch are the same files as the release's attachments, and `SHA256SUMS`
lists them.

| `cn` release file | For |
| --- | --- |
| `neutrino-hub_<version>_amd64.deb`, `neutrino-hub_<version>_arm64.deb` | the hub on Debian, Ubuntu, Raspberry Pi OS |
| `neutrino-hub-<version>-windows-amd64.msi` | the hub on Windows 10 1809 or newer, x64 |
| `neutrino-hub-<version>-macos-arm64.pkg` | the hub on macOS 12.3 or newer, Apple silicon |
| `neutrino-agent_<version>_amd64.deb`, `neutrino-agent_<version>_arm64.deb` | the agent on the same Linux systems |
| `neutrino-agent-<version>-windows-amd64.msi`, `neutrino-agent-<version>-macos-arm64.pkg` | the agent on Windows x64 and Apple silicon |
| `neutrino-client_<version>_amd64.deb`, `neutrino-client_<version>_arm64.deb` | the client on Debian, Ubuntu |
| `neutrino-client-<version>-windows-amd64.msi`, `neutrino-client-<version>-macos-arm64.pkg` | the client on Windows x64 and Apple silicon |
| `neutrino-client-<version>-android.apk` | Android 8 or newer, arm64-v8a |
| `install.sh`, `install.ps1` | the one-command installers, stamped `cn` |
| `neutrino-<version>-cn-source.tar.gz` | the mainland source tree |
| `cc-switch-cli-v<cc-switch version>-<asset>`, five files | cc-switch for the agents of a mainland hub, which fetches it from here: the files `PACKAGING_CC_SWITCH_ASSETS` in `packaging/shared/constants.py` pins, under the names upstream gives them, each checked against its pin before the upload |
| `cc-switch-cli-v<cc-switch version>-LICENSE.txt` | cc-switch's MIT licence, beside the files it covers |
| `SHA256SUMS` | every file above |

The script checks Gitee's limits over every file before it changes anything
on Gitee:

| Limit | Value | Checked over |
| --- | --- | --- |
| one release attachment | 100 MB, counted as 100,000,000 bytes | each file above |
| all attachments of the repository | 1 GB, counted as 1,000,000,000 bytes | the sum of the files above |
| one file in the repository | 50 MB | each file of the mainland tree, unpacked before the commit |
| the repository's git data | 500 MB | the unpacked mainland tree |

A file over a limit fails the job before the first upload, with the file's
name, its size and the limit in the message. The build's first answer to a
package over 100 MB is stronger compression in that package's build.

`publish_cn` runs `packaging/ci/publish_cn.py` on a Linux runner, after
`publish`, for a tag with no suffix; a pre-release is published on GitHub
alone. The script:

1. Downloads `release_dist_cn` from the latest successful run of
   `release.yml` for the tag, and writes the notes `publish.yml` was given
   to a file.
1. Runs the size checks.
1. Unpacks the mainland source tree without `third_party/`, commits it as one
   commit with no parent, force-pushes it to `main` of
   `git@gitee.com:iffiX/neutrino.git` and pushes the tag `v<version>` on it.
1. Deletes the attachments of every earlier release through
   `DELETE /api/v5/repos/iffiX/neutrino/releases/<release-id>/attach_files/<file-id>`.
1. Creates the release for the tag with the same notes through
   `POST /api/v5/repos/iffiX/neutrino/releases`, or reuses the one the tag
   already has.
1. Uploads each file the release does not already hold under the same name
   and size, through
   `POST /api/v5/repos/iffiX/neutrino/releases/<release-id>/attach_files`.

The earlier attachments go first because the earlier set and the new set
together exceed 1 GB. Earlier tags and release entries stay, without files.
Between the delete and the last upload the mainland release has no packages,
and a `cn` install started then stops with the script's own sentence.
Running the job again for the same tag completes what an interrupted run
left and uploads nothing twice.

The job reads two repository secrets:

| Secret | Holds | Used for |
| --- | --- | --- |
| `GITEE_TOKEN` | a Gitee personal access token with the `projects` scope, of an account with write access to `iffiX/neutrino` | every API call |
| `GITEE_SSH_KEY` | the private SSH key whose public key is in that account's own SSH keys | the push; a Gitee deploy key is read-only |

Before it pushes, the script checks `gitee.com`'s SSH host key against
`PACKAGING_GITEE_SSH_HOST_KEY` in `packaging/shared/constants.py`.
