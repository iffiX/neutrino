# Releases

A release is one tag, one version, and one set of packages built from it. The
hub, the agent, the desktop client and the two phone apps are versioned
together and released together.

Wording rules for the entries themselves are in
[../coding_style/comment_style.md](../coding_style/comment_style.md); who may
commit and when is in [commit.md](commit.md).

## One tag, every package, compatibility by protocol number

One tag builds the hub, the agent, the desktop client and the two phone apps
at one version. Whether an agent or a client works with a hub is decided by `PROTOCOL`, the number each
package speaks; the hub accepts every number from `PROTOCOL_MIN` to its own
([../design/protocol.md](../design/protocol.md), "Versioning"). A peer outside
that range is rejected at the door with `protocol_too_old` or
`protocol_too_new` and keeps its binding. An agent of 0.5 under a hub of 0.6
is the one exception: the hub admits it to update itself.

An agent whose hub names a newer `software` upgrades itself from the package
the hub keeps, an agent one protocol number behind included
([../design/protocol.md](../design/protocol.md), "An agent of 0.5"); a
client, on a computer or a phone, is upgraded when its person installs the
new package.

Every package reads its version from package metadata. It is never written
into the source twice.

## Two editions from one source

An edition is the set of features a package is built with. One tag builds
every package in two editions from the one source on GitHub, at the same
version and the same `PROTOCOL`, and one release on every release site holds
both ("Release sites"):

| Edition | Features |
| --- | --- |
| `intl` | every feature |
| `cn` | every feature except the proxy and the side gateway mode |

`cn` differs from `intl` in the proxy and the side gateway mode alone, and is
the same in everything else, downloads included. The mainland edition leaves
the proxy out:

| Package | What `cn` leaves out |
| --- | --- |
| hub | the proxy: xray, the proxy TUN and its `tun2socks`, the geodata, the **Proxy** page, the proxy scopes of the network modes, and the `side_gateway` mode |
| desktop client | nothing |
| Android app | nothing |
| iOS app | nothing |
| agent | nothing |

`cn` keeps NetBird in the hub, the desktop client and the Android app, and
keeps EasyTier, the SSH relay, SakuraFrp and OpenFrp with the frpc they
run, the client's files adapter, VS Code,
code-server, CloudCLI, Codeg, Gitea, Samba, Podman, ZFS and the AI gateway.

The build writes the edition into each package as `EDITION`, `intl` or `cn`,
beside the version in `neutrino_hub/_version.py`,
`neutrino_agent/_version.py` and `neutrino_client/_version.py`, into the
Android app as `BuildConfig.EDITION`, and into the iOS app's `Info.plist` as
`NeutrinoEdition`. The agent's `_version.py` also holds `AGENT_BUILT_AT`,
the UTC time the build staged the tree, which tells two builds of one
version apart ([../design/agent.md](../design/agent.md), "A retry is the
same press again"). A checkout has no stamp and reads
the file `EDITION` at the repository's root, one line holding `intl` in the
GitHub repository; the two phone builds read the same file. The stamp, or
that file, names which edition's package an update or an install script
takes, and no download address follows it
([../design/agent/module_install.md](../design/agent/module_install.md),
"Sources"). Which features a package has follows from the files
its tree holds ([../design/architecture.md](../design/architecture.md), "A
left-out feature is reached through one table").

Every script under `packaging/build/` takes `--edition intl` or
`--edition cn`, `intl` when absent; a build that runs in a container passes
it in as `NEUTRINO_EDITION`. The three phone core scripts,
`build_core_netbird.py`, `build_core_easytier.py` and
`build_core_rustdesk.py`, take none: a core is the same in both editions,
and its cache is named by the digest of the script's own bytes, so an
option added to them would rebuild every core. A package of an edition upgrades only to a
package of the same edition, which the update check and the install scripts
tell apart by the file's name.

## The mainland source tree

`PACKAGING_CN_LEFT_OUT_PATHS` in `packaging/shared/constants.py` lists every
repository path that exists for a left-out feature alone: its packages, their
mirrored tests, its frontend files, its examples and unit templates, and the
scripts that build its programs. It is the one list of what `cn` leaves out;
no other file repeats it.

`packaging/build/build_sources.py --edition cn` writes
`neutrino-<version>-cn-source.tar.xz`. It holds the tree at the tagged
commit without the listed paths, with the root `EDITION` file holding
`cn` and `EDITION` stamped `cn` in `install.sh` and `install.ps1`, so a clone
of the CNB repository, a development run from it and its install scripts
all read `cn`, and `third_party/` holding the upstream
source of what the `cn` packages hold. Its `README.md` is the
repository's `README.zh-CN-CNB.md`, the page CNB shows, and its root
holds no other README, so a tree holding `README.zh-CN-CNB.md` is a full
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
feature: refactored the machine page
```

A release with nothing under a heading omits the heading.

## What goes in a release

One section per package, so nobody downloads the wrong thing. Name the
platform in words, not only in the filename.

| Platform | Hub | Agent | Client |
| --- | --- | --- | --- |
| Debian, Ubuntu, Raspberry Pi OS, amd64 and arm64 | `.deb` | `.deb` | `.deb` |
| Fedora, RHEL, AlmaLinux, Rocky | `.rpm` | `.rpm` | `.rpm` |
| Arch, EndeavourOS, Manjaro | `.pkg.tar.zst` | none | none |
| Windows 10 and 11, x64 | `.msi`, `server` mode | `.msi` | `.msi` |
| macOS on Apple silicon | `.pkg`, `server` mode | `.pkg` | `.pkg` |
| macOS on Intel | `.pkg`, `server` mode | `.pkg` | `.pkg` |
| Android 8 or newer | none | none | `.apk` |
| iOS 16 or newer | none | none | `.ipa`, unsigned |

Every platform is built in both editions.

`install.sh` and `install.ps1`, and `install-cn.sh` and `install-cn.ps1` for
`cn`, are published beside the packages and install any of the three by one
command ("Install scripts"). A `cn` file's name holds `-cn`: before the
extension of a package or a script, such as
`neutrino-hub_<version>_amd64-cn.deb` and `install-cn.sh`, and as
`neutrino-<version>-cn-source.tar.xz` for the source tree. One release
therefore holds both editions.

### Hub

The hub runs on Debian, Fedora and Arch family Linux. Each package carries its
own Python environment and touches nothing the system installed; everything
else it needs is named in the package's dependencies, so installing the file
installs the appliance's prerequisites with it. Every hub package carries
`neutrino_transport`, the Go program that holds the agent port, built for its
system and architecture. On macOS and Windows the hub
runs in `server` mode, and its package carries the hub compiled by Nuitka
with every program it drives, `tun2socks` among them in `intl` for the
proxy scopes that divert the machine's own packets there. Every hub package
of both editions carries upstream frpc (fatedier/frp, Apache-2.0) at
`FRP_VERSION`, taken from its release for the system and the architecture
by `packaging/shared/hub_assets.py` and checked against the sha256
`modules/frp/constants.py` pins, as it takes NetBird and EasyTier; its
licence is `licenses/frp.txt`, and the **About** card credits it.

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
| `neutrino-hub-<version>-macos-arm64.pkg` | macOS 13 or newer on Apple silicon |
| `neutrino-hub-<version>-macos-amd64.pkg` | macOS 13 or newer on Intel |

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

```bash
sudo apt install ./neutrino-hub_<version>_amd64.deb      # Debian family
sudo dnf install ./neutrino-hub-<version>-1.x86_64.rpm   # Fedora family
sudo pacman -U neutrino-hub-<version>-1-x86_64.pkg.tar.zst
sudo nhub setup
```

The RHEL family, RHEL 9 and its rebuilds, needs EPEL for each of the three
`.rpm` packages: the hub's `fail2ban` and `arp-scan`, and the `xdotool` the
agent's and the client's `.rpm` name, are there rather than in the base
repositories. Neutrino enables it: `install.sh` before it installs any of
the three packages there, and the hub's install of an agent over SSH
before it installs the `.rpm`, each with the administrator rights it
already holds for the install. Each follows EPEL's own instructions, CRB or
CodeReady Builder first, picked by `ID` in `/etc/os-release`:

| `ID` | The steps |
| --- | --- |
| `rocky`, `almalinux`, `centos` | `dnf config-manager --set-enabled crb`, then `dnf install -y epel-release` |
| `rhel` | `subscription-manager repos --enable codeready-builder-for-rhel-<major>-<machine>-rpms`, then `dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-<major>.noarch.rpm` |

`<major>` is the part of `VERSION_ID` before its first dot and `<machine>`
is `uname -m`. A step that fails stops the install with its output, and
Fedora and every other system take no step. A package installed by hand on
Rocky or AlmaLinux needs the same two lines first:

```bash
sudo dnf config-manager --set-enabled crb
sudo dnf install -y epel-release
```

Enabling it in the same transaction does not work: the new repository's
metadata is not read until the transaction that added it has finished, so it
is its own command, and only on the RHEL family. Fedora carries these
packages itself.

### Agent

The agent runs on the machines the hub manages, as root or LocalSystem and
headless: it draws no window and listens on `127.0.0.1` alone. Each Linux package
carries its own interpreter under `/opt/neutrino/agent` and the RustDesk
host, and depends on no distribution package named `python`. The Windows
and macOS installers include the agent compiled with Nuitka and upstream's
RustDesk in the agent's own folder. Every agent package carries the two Go
programs the agent runs, `neutrino_transport` and `neutrino_ssh_server`,
under `bin/` in its program directory. The installers register nothing of
RustDesk's: the agent does when a machine's Remote desktop switch goes on. No agent package
carries cc-switch: the agent fetches it from the hub when the machine's AI
tools need it, at the pin the client's packages carry.

| File | For |
| --- | --- |
| `neutrino-agent_<version>_amd64.deb` | Debian, Ubuntu, Raspberry Pi OS on x86-64 |
| `neutrino-agent_<version>_arm64.deb` | The same on ARM64 |
| `neutrino-agent-<version>-1.x86_64.rpm` | Fedora, RHEL, AlmaLinux, Rocky |
| `neutrino-agent-<version>-1.aarch64.rpm` | The same on ARM64 |
| `neutrino-agent-<version>-windows-amd64.msi` | Windows 10 1809 or newer, x86-64 |
| `neutrino-agent-<version>-macos-arm64.pkg` | macOS 13 or newer on Apple silicon |
| `neutrino-agent-<version>-macos-amd64.pkg` | macOS 13 or newer on Intel |

32-bit ARM is not published, because no interpreter build is. Windows is
x86-64 only, because RustDesk publishes no Windows ARM64 build.

```bash
sudo apt install ./neutrino-agent_<version>_amd64.deb
sudo nagent join '<enrollment link from the Agents page>'
```

Most people never download a Linux agent package: the hub installs the
right one over SSH from the Agents page, from the one its own package
holds or from the release sites, and enables EPEL first on the RHEL family
("Hub"). The two installers are downloaded and
run on the machine, then `nagent join` runs in a terminal opened as
administrator on Windows and under `sudo` on macOS.

### Client

The client runs in a person's own session, never as root, on Linux, Windows
and macOS. It is compiled with Nuitka, so the packages carry no interpreter
of their own; each carries cc-switch, the RustDesk viewer and
`neutrino_transport`. The Windows
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
| `neutrino-client-<version>-macos-arm64.pkg` | macOS 13 or newer on Apple silicon |
| `neutrino-client-<version>-macos-amd64.pkg` | macOS 13 or newer on Intel |

Windows is x86-64 only: cc-switch publishes no Windows ARM64 build, so there
is nothing to include for that machine. Every macOS package is published for
both architectures in both editions, `arm64` built on GitHub's `macos-15`
runner and `amd64` on `macos-15-intel`; how long the Intel one lasts is in
[../design/min_support.md](../design/min_support.md).

```bash
sudo apt install ./neutrino-client_<version>_amd64.deb
nclient hub join '<client link from the Clients page>'
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
unpacks them at install.

| File | For |
| --- | --- |
| `neutrino-client-<version>-android.apk` | Android 8 or newer, arm64-v8a |

The person installs the `.apk` on the phone, then scans the QR code on the
**Clients** page or pastes the client link.

### iOS app

The iOS app is the client on an iPhone, with the pages and the limits
[../design/client.md](../design/client.md) gives it in "The iOS app". It
contains SwiftTerm, AMSMB2 and the libsmb2 it builds, and the RustDesk core
compiled from its pinned source for a device (arm64) alone, and no network
core, and is licensed AGPL-3.0 by `client/ios/LICENSE`. AMSMB2 and libsmb2
are LGPL-2.1: the app carries them as one framework of their own, linked
when the app starts. The **About** card credits AMSMB2 and libsmb2 with
their source, and RustDesk with its source and its patch. The release
attaches it unsigned, and each person signs their own copy. The release is
the only place the app is published: the project holds no Apple developer
account, so the app is in neither the App Store nor TestFlight.

| File | For |
| --- | --- |
| `neutrino-client-<version>-ios.ipa` | iOS 16 or newer, arm64, unsigned |

In the release workflow `build_client_ios.py` builds it on GitHub's
`macos-15` runner: `build_core_rustdesk_ios.py` puts the RustDesk core into
`client/ios/cores/rustdesk/`, from the cores cache the job restores or built
on a miss, XcodeGen
generates the project, `xcodebuild` builds the app for `generic/platform=iOS`
with code signing off (`CODE_SIGNING_ALLOWED=NO`), the build fails when the
app does not define `_nd_start`, the app takes its icon from
`images/icons/neutrino_ios.png`, the mark on an opaque square with square
corners, which iOS rounds, and the `.app` is zipped
under `Payload/`. The build passes the release's version to `xcodebuild`, as
the Android build passes it to Gradle.

The person signs the `.ipa` with their own Apple ID and installs it with
Sideloadly (Windows, macOS), AltStore (Windows, macOS), or Impactor or its
command line `plumesign` (Linux, macOS, Windows), turns on Developer Mode on the iPhone,
then scans the QR code on the **Clients** page or pastes the client link. A
free Apple ID's signature holds 7 days, for at most 3 such apps on the
phone, and the person signs the app again before it ends; a paid Apple ID's
signature holds a year. An upgrade is
the next release's `.ipa`, signed and installed over the app.

### Install scripts

| File | For |
| --- | --- |
| `install.sh`, `install-cn.sh` | macOS and Linux: `curl -fsSL <url> \| sh -s -- hub\|agent\|client` |
| `install.ps1`, `install-cn.ps1` | Windows: `irm <url> \| iex` in any PowerShell |

`packaging/install/install.sh` and `packaging/install/install.ps1` hold
their edition as `EDITION` near their top, `intl` in the committed files,
and the release sites the build stamped; the build writes the two `cn`
scripts with `cn`. A person fetches a script from GitHub's address of the
latest release, or the mainland one from the CNB repository, under
`packaging/install/` of the mainland tree ("The mainland site on CNB"):

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
```

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

| Input | Effect |
| --- | --- |
| `hub`, `agent` or `client` | the package to install; `hub` when none is given |
| `NEUTRINO_VERSION` | the release to install, such as `v0.5.0`; the latest when unset |
| `NEUTRINO_ASSET_DIR` | a directory holding `SHA256SUMS` and the packages; nothing is downloaded, which is how `packaging/ci/check.py` runs the scripts |

A script reads the system and the architecture (`uname -s` and `uname -m`,
`x86_64` naming `amd64`; on Linux `/etc/os-release` picks the deb, the rpm or
the Arch package). It reads the latest tag from `latest.json` on the release
sites unless `NEUTRINO_VERSION` names one, then fetches `SHA256SUMS` and its
edition's package into a temporary directory and checks the package against
it. It probes every site, starts on the fastest and moves to the next on a
stall, with no measures while a file downloads
([../design/agent/module_install.md](../design/agent/module_install.md),
"Choosing a source"). A mismatch, a system and architecture no package is
published for, or no site serving the file stops the script with one
sentence, which names each site and why it failed.

Run as a person, `install.sh` asks sudo for the password once before it
downloads anything, and asks nothing when `sudo -n true` already succeeds.
It then installs with `sudo installer -pkg`, `sudo apt install ./`,
`sudo dnf install`, `sudo pacman -U` or `msiexec /i <file> /qn /norestart`;
on the RHEL family it enables EPEL under the same sudo before `dnf install`
("Hub"). For the hub it ends by printing the wizard's address with its token, and
runs `nhub setup` in its place when its standard input is a terminal. Over a
hub already set up, one whose panel settings hold a password hash, it runs
neither and prints one line naming the panel's address. It runs `nhub` where
its package put it, `/usr/bin/nhub`, `/usr/local/bin/nhub` or
`C:\Program Files\Neutrino\hub\nhub.exe`, since a root shell's PATH can
name none of them. Run without administrator rights, `install.ps1` asks
Windows for them once and goes on in the PowerShell window Windows opens as
administrator, which stays open for the next command; a refusal stops it
with one sentence, and nothing is installed.

### Source archive

`neutrino-<version>-source.tar.xz` is this tree at the tagged commit, with
`third_party/` beside it holding the upstream archives of everything the
packages carry, at the exact tags the binaries were built from: RustDesk,
EasyTier, NetBird, Xray-core, CLIProxyAPI, frp and cc-switch. It exists because
some of those are copyleft and a binary release owes its source; it is not
what anybody installs from. GitHub's own `Source code (zip)` and `(tar.gz)`
carry the tree alone.

`neutrino-<version>-cn-source.tar.xz` is the same for `cn`: the mainland tree
of "The mainland source tree", with the upstream source of what the `cn`
packages hold. It is attached to the release beside the full tree's, and
every `cn` package is built from it.

## Every asset carries a checksum

`SHA256SUMS` is attached beside the packages and covers every file of the
release: both editions' packages, the four install scripts, the two source
archives and the cc-switch files. The hub checks an agent package before it
installs it on a device, so a cut or changed download fails with its code
and installs nothing.

## Release sites

A release site is an address that holds every file of every release, under
the names the release gives them. GitHub is the first site and CNB the
second, the mainland one. `PACKAGING_RELEASE_SITES` in
`packaging/shared/constants.py` lists them, each as two addresses:

| Site | A tag's files | `latest.json` |
| --- | --- | --- |
| GitHub | `https://github.com/iffiX/neutrino/releases/download/{tag}/` | `https://github.com/iffiX/neutrino/releases/latest/download/latest.json` |
| CNB | `https://cnb.cool/iffi-X/neutrino/-/releases/download/{tag}/` | `https://cnb.cool/iffi-X/neutrino/-/git/raw/main/latest.json` |

| Rule | Reason |
| --- | --- |
| One list names every site, GitHub first, and a site joins it by one line. | A mirror holding the same files is one more source of each of them. |
| The build stamps the list into the hub's `_version.py` as `HUB_RELEASE_SITES`, and into each install script. A checkout has no stamp and names no site. | The hub and the scripts learn the sites from the build alone ([../design/agent/module_install.md](../design/agent/module_install.md), "Sources"). |
| Every site holds the same files under the same names, both editions in one release, and one `SHA256SUMS` over all of them. | The digest makes every site equal, so the fastest one serves. |
| `latest.json` at a site's fixed address names the latest release as `{tag, version}`. On CNB it is a file of the repository. | CNB answers no API read without a login, and a file of its repository reads with no login. |
| Every release holds the cc-switch files `PACKAGING_CC_SWITCH_ASSETS` pins, under the names upstream gives them, and their licence. | The hub's cache fetches cc-switch from upstream and from the release sites. |
| A site that has lost a file is one failed source among the others. | The fetch goes on to the next site, and the failure names each site only when every one fails. |


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
| `build_client_ios.py` | the unsigned `.ipa` | macOS with Xcode and XcodeGen |
| `build_core_netbird.py`, `build_core_easytier.py`, `build_core_rustdesk.py` | one core the phones carry | Linux |
| `build_core_rustdesk_ios.py` | the RustDesk core of the iOS app, a static library for a device | macOS with Xcode |
| `build_sources.py`, `build_checksums.py` | the source archive, or with `--edition cn` the mainland source tree; `SHA256SUMS` over a directory | anywhere |
| `build_cc_switch.py` | the pinned cc-switch release files under upstream's names, each checked against its pin, and their licence | anywhere |
| `build_transport.py` | `neutrino_transport` for one system and architecture, `--target linux-amd64` and the like, cross-compiled from `transport/` with `CGO_ENABLED=0` and the version stamped by `-ldflags "-X"`, into `dist/go/<target>/` | anywhere with the pinned Go |
| `build_ssh_server.py` | `neutrino_ssh_server` from `agent/sshserver/`, the same way | anywhere with the pinned Go |
| `build_core_transport.py` | the transport's library for the phones: `Mobile.xcframework` for iOS, by gomobile `bind` with `-iosversion 16.0`, cached as every core is; on Android the transport is bound into NetBird's `.aar` by `build_core_netbird.py`, one gomobile `bind` over both modules with `-androidapi 26`, because an app loads one gomobile library | Linux or macOS with the pinned Go and gomobile, and Xcode for iOS |

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

Every package build takes the Go programs of its own target from
`dist/go/<target>/`, built by `build_transport.py` and `build_ssh_server.py`
before it, and refuses to build without them; the Android and iOS builds take
the transport's library from `build_core_transport.py` as they take every
core. The Go programs are built once per target and every package of that
target carries the same file.

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
`agent_packages.json` beside the cache. The manifest names every platform the
release publishes an agent of that edition for, the file name each is
published under, and its sha256, which is the line the release's
`SHA256SUMS` lists for that file. A hub fetches another platform's package
from the release sites the first time a device of that platform needs it
([../design/agent.md](../design/agent.md), "The agent's packages come from
the hub"). A build with no release sites holds the entry it seeded and
refuses the rest by name. A package dropped under `config/devices/packages`
still wins over both.

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
architectures, the apk, the unsigned `.ipa` and the source archive, generates `SHA256SUMS` over all
of it and the two install scripts, and opens a draft release. Each job runs one `packaging/build/` script and then
`packaging/ci/check.py` on what it built, so a broken package fails the build
rather than the person who downloads it: every Linux package is installed in
a fresh container of its family and its command answers `--version`; the
client's Windows job installs its `.msi` over the released 0.4.0 and
removes it, then installs it on its own, runs the client from it and
uninstalls again, and its macOS job installs the `.pkg` and runs `nclient`
from it; the agent's Windows job installs its `.msi` over the released
0.4.0, checks that the RustDesk 0.4.0 installed is gone and removes it, then
installs it on its own, checks that `neutrino_agent` runs and that
RustDesk's files lie in the agent's folder with nothing of RustDesk's
registered, and uninstalls again, and its macOS job
installs the `.pkg`, checks the LaunchDaemon runs, and removes it; the apk is
installed and launched once in an emulator; the `.ipa` is unpacked and its
one `Payload/Neutrino.app` must name the release's version and the bundle
id `io.github.iffix.neutrino` in its `Info.plist`; the hub's macOS and Windows jobs
set a hub up from the package and from the install script
([../design/tests.md](../design/tests.md)). The hub jobs wait for the agent's.

The same workflow builds `cn`. The `sources` job also writes the mainland
source tree, and each build job runs a second time for `cn`, for every
platform: it downloads that tree, unpacks it, and runs its
`packaging/build/` script inside it with `--edition cn`, then
`packaging/ci/check.py`. The `cn` files, the cc-switch files
`build_cc_switch.py` fetches at their pin, and `latest.json` join the same
draft, and `SHA256SUMS` covers every file of it.

Fill in the changelog, check the section headings still match what shipped,
and publish with `.github/workflows/publish.yml`, which takes the tag and the
notes. Its `publish` job publishes the GitHub draft, and then runs
`packaging/ci/publish_cn.py`, which publishes the same release to CNB ("The
mainland site on CNB").

Running the same workflow from the Actions tab builds the packages and attaches
them as artifacts without creating a release, which is how a change to the
pipeline is tried before a tag depends on it.

Draft, not published, is deliberate: the notes are written by a person who knows
what the release is for.

## The mainland site on CNB

`https://cnb.cool/iffi-X/neutrino` is the second release site. Its `main`
holds the mainland source tree of the latest release, with `latest.json` at
its root, and its release of each tag holds every file GitHub's release
holds.

`packaging/ci/publish_cn.py` publishes a tag there, for a tag with no
suffix; a pre-release is published on GitHub alone. The script:

1. Takes the release's files from the workflow run that built the tag.
1. Commits the mainland source tree, without `third_party/`, and
   `latest.json` as one commit on `main`, and pushes the tag on it.
1. Creates the tag's release, or reuses the one the tag already has.
1. Uploads each file the release does not already hold under the same name
   and size.

Running it again for the same tag completes what an interrupted run left and
uploads nothing twice.
