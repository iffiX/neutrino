# Minimum support

The floor of a package is the highest requirement measured in what that package
installs. Every number here is read off a built tree or off the files a build
stages, and a distribution enters the tables after a package has run on it.

A package installs on a machine with the glibc its compiled files name and the
packages its dependency fields spell. The programs it then drives have their
own minimum versions. A change to a dependency, to a build container, or to a
`Depends` or `Requires` line moves one of these. The tables here are where the
new floor is written down.

## Where each package starts

| Package | glibc | What sets it | Oldest system |
| --- | --- | --- | --- |
| hub `.deb`, `.rpm` | 2.34 | the cryptography and bcrypt extensions in the environment the package installs (`hub/packaging/venv_tree.py:80`) | Debian 12, Ubuntu 22.04, RHEL 9 |
| hub `.msi` | none | the agent `.msi` it carries and installs on its own machine at setup | Windows 10 1809 |
| hub `.pkg` | none | `neutrino_transport`, built by Go 1.27, which names macOS 13 as its least system ("The Go programs") | macOS 13, arm64 and amd64 |
| agent `.deb`, `.rpm` | 2.34 | the same floor as the hub's (`agent/packaging/constants.py`), chosen so the two packages require one system; the RustDesk host binary needs 2.27 and Codeg's binaries 2.34 | Debian 12, Ubuntu 22.04, RHEL 9 |
| agent `.msi` | none | the pseudo console the shell stream runs PowerShell on (`agent/neutrino_agent/streams/windows_shell.py:76`) | Windows 10 1809 |
| agent `.pkg` | none | `neutrino_transport` and `neutrino_ssh_server`, built by Go 1.27 for macOS 13; the RustDesk app asks for 12.3 (`packaging/shared/rustdesk_assets.py:41`) | macOS 13, arm64 and amd64 |
| client `.deb` | 2.34 | `nclient` and `mount_helper`, compiled in `debian:12` (`packaging/build/build_client_desktop.py:40`) | Debian 12, Ubuntu 22.04 |
| client `.rpm` | 2.34 | the same two binaries out of the same container (`packaging/build/build_client_desktop.py:50`) | RHEL 9, AlmaLinux 9 |
| client `.pkg` | none | `neutrino_transport`, built by Go 1.27 for macOS 13; the RustDesk app asks for 12.3 (`packaging/shared/rustdesk_assets.py:41`) | macOS 13, arm64 and amd64 |
| client `.msi` | none | the WebView2 Evergreen runtime and CPython 3.13 (`packaging/build/build_client_windows.py:41`, `packaging/build/build_client_windows.py:90`) | Windows 10 1809 |
| client `.apk` | none | `openProxyFileDescriptor`, which the Files provider serves a share's file through, from API level 26 (`minSdk` in `client/android/`) | Android 8.0 |
| client `.ipa` | none | the deployment target 16.0 in `client/ios/project.yml`; iOS 16 is the last system of the iPhone X, the oldest phone the app is tested on | iOS 16 |

Ubuntu 22.04 has glibc 2.35, above all four Linux floors, and the hub's `.deb`
reaches it because the DHCP client is named `dhcpcd-base | dhcpcd5`
(`hub/neutrino_hub/system/constants.py:134`): Ubuntu has the first name from
24.04 and the same daemon in the second before it, whose unit the takeover
stands down with every other manager's. One table spells the names for every
family, and both the control field of the `.deb` and the packages `nhub setup`
checks read it (`hub/neutrino_hub/system/package_manager.py:420`), so a
machine installs and is checked against whichever of the two names its
repositories carry (`hub/neutrino_hub/system/package_manager.py:128`).

The frpc every hub package carries moves no floor: upstream builds it with
cgo off, so it is linked statically and names no glibc.

The cc-switch the agent fetches from the hub (`data/manifests/cc_switch.json`)
moves no floor. On Linux it is
upstream's musl build, which is linked statically and names no glibc
(`client/desktop/packaging/bundled.py:42`), and on Windows and macOS it is
the build the client's `.msi` and `.pkg` already carry on the same floors.

On the RHEL family every `.rpm` names a package that is in EPEL: the hub's
`fail2ban` and `arp-scan` (`hub/neutrino_hub/system/constants.py`), and the
agent's and the client's `xdotool` (`agent/packaging/build_rpm.py:41`,
`client/desktop/packaging/build_rpm.py:65`). EPEL is therefore a requirement
of all three there, and `install.sh` and the hub's install of an agent over
SSH enable it, with CRB, before they install
([../agent_work_rule/release.md](../agent_work_rule/release.md), "Hub").

The client's `.rpm` reaches RHEL 9 and AlmaLinux 9 because either WebKit2 ABI
satisfies it, and RHEL 9 has 4.0 (`client/desktop/packaging/build_rpm.py:54`).
The introspection library on RHEL 9 is older than the bindings need, so the
package installs its own (`client/desktop/packaging/payload.py:127`).

The amd64 macOS packages are built on GitHub's `macos-15-intel` runner, in
both editions. GitHub provides its Intel macOS runners until autumn 2027, and
macOS Tahoe 26 is the last macOS for Intel Macs; whether the amd64 packages
continue is decided then.

The two phone rows are the floor each app's build declares: `minSdk 26` in
the Gradle project and a deployment target of 16.0 in `project.yml`. The
phone's installer rejects the app on an older system, so the floor is
enforced by the declaration itself.

## The Go programs

`neutrino_transport` and `neutrino_ssh_server` are built with Go 1.27.3,
the toolchain `packaging/build` pins, and the Android and iOS libraries with
gomobile from `golang.org/x/mobile` at the version `transport/go.mod` pins
([../coding_style/go.md](../coding_style/go.md)).

| Target | What sets the floor | Floor |
| --- | --- | --- |
| Linux, amd64, arm64 and armhf | `CGO_ENABLED=0`: the binaries are static and name no glibc; Go's own floor is a 3.2 kernel | below every package's |
| Windows, amd64 | Go 1.27's own floor | Windows 10, below the packages' 1809 |
| macOS, arm64 and amd64 | Go 1.27's linker writes macOS 13 as the binary's least system (`macOS = 13.0` in `cmd/link`), the oldest macOS Go 1.27 supports | macOS 13, which raises the hub's, the agent's and the client's `.pkg` from 12.3 |
| Android | gomobile's `-androidapi`, which the build sets to 26, the app's `minSdk` | Android 8.0, the app's own |
| iOS | gomobile's `-iosversion`, which the build sets to 16.0, the app's deployment target | iOS 16, the app's own |

The macOS floor follows the toolchain: a later Go that drops macOS 13 moves
every `.pkg` with it, and the release that moves the toolchain says so.
Containers on macOS already needs 13, so a machine that runs Containers
loses nothing.

## What each package holds and depends on

A package either holds a part or names it as a dependency, and the choice
follows from who can install the part safely.

### The hub's package

`nftables`, `dnsmasq`, `iproute2`, NetworkManager, `fail2ban`, `iw`,
`arp-scan` and `curl` are the hub's dependencies, declared in the
`Depends:` of the `.deb`, the `Requires:` of the `.rpm` and the `depends=` of
the Arch package. All three are generated from `SYSTEM_RUNTIME_PACKAGES` in
[`system/constants.py`](../../../hub/neutrino_hub/system/constants.py), so a
dependency field and what the hub believes it needs cannot say different
things. `hostapd` is a recommendation: a gateway with no radio routes
without it.

The package manager installs them, and the hub's own setup never does.
Installing NetworkManager from a process that runs on the machine takes the
machine's network down while it runs, and on a gateway that is the network.
It happened once here, and the box needed a reboot. A package manager
installs before anything of the hub runs, the one moment when taking the
network down costs nothing. On macOS and Windows the hub's package names no
dependency and holds every program it drives ([files.md](files.md),
"/opt/neutrino: what the packages put here").

### The agent's package

The agent's package lays the payload down, `nagent join` joins a hub, and
the hub's state says what the machine hosts. The package holds an
interpreter under `/opt/neutrino/agent` with the agent installed beside it,
and the RustDesk host, both built for one machine. It holds no cc-switch:
the agent fetches it from the hub the first time the machine's AI tools
setting needs it ([agent/ai_tools.md](agent/ai_tools.md)). The hub's
`data/manifests/cc_switch.json` pins the client's version, the one
`packaging/shared/constants.py` holds, with the same files and digests, and
a hub test keeps the two the same. The agent draws no window, so it holds no
bindings and depends on nothing named `python`.

The interpreter is held because the system's is no fit. The agent is
standard library only, so one architecture-independent package once ran on
whatever Python a device already had. A project that installs into
somebody's system Python is what `EXTERNALLY-MANAGED` exists to stop, and a
machine's own interpreter is not one this project can pin. A checkout pays
none of it: `pip install -e agent` installs the agent alone.

### The client's package

The client is a person's application: it runs when the person opens it, in
their own session, never as root. Its packages hold the client compiled by
Nuitka, with the interpreter compiled in, so none of them holds a Python
tree and none depends on one: `nclient` on Linux under `/opt/neutrino/client`
with the root mount helper compiled under its `libexec` at the path polkit
pins, `nclient.exe` from the Windows installer, `Neutrino Client.app` from
the macOS one. Beside the binary are the two tools it drives, cc-switch and
the RustDesk viewer, pinned by digest; the hub's manifest for the agent's
copy of cc-switch repeats the same pin.

A machine still supplies the window's toolkit. On Linux that is the
WebKitGTK 4.1 stack and the appindicator library, plain dependencies of the
deb and the rpm; on Windows the WebView2 runtime, for which the installer
runs Microsoft's bootstrapper when the machine has none; on macOS WKWebView,
which is the system's. The compile is native, so each package comes off a
machine of its own architecture. A checkout pays none of it: `pip install -e
client` runs on the checkout's interpreter, and `nclient gui` uses whatever
can import `gi`.

## What the hub drives

The hub's renderers and its units require these versions of the software a
distribution provides.

| Program | Minimum | What needs it | Where |
| --- | --- | --- | --- |
| nftables | 0.9 | `socket transparent` and `tproxy` in the proxy chains | `hub/neutrino_hub/modules/router/nft_renderer.py:118` |
| dnsmasq | 2.73 | `min-cache-ttl`, the floor under every cached answer's TTL | `hub/neutrino_hub/modules/router/dnsmasq_renderer.py:63` |
| systemd | 245 | `ProtectClock=` in the panel's unit, the newest directive any unit uses | `hub/neutrino_hub/data/services/neutrino_hub_web.service:28` |
| iproute2 | 4.13 | `ip -json` for links, addresses and routes | `hub/neutrino_hub/modules/router/link_status.py:322` |
| fail2ban | 0.11 | the `nftables-multiport` ban action the SSH jail sets | `hub/neutrino_hub/system/constants.py:166` |
| wpa_supplicant, hostapd | 2.9 | SAE with `ieee80211w` for a WPA3 network; the access point renders WPA2 only | `hub/neutrino_hub/modules/router/supplicant_renderer.py:101` |
| dhcpcd | 7.1 | `nohook`, which keeps the client off resolv.conf and the hostname | `hub/neutrino_hub/modules/router/dhcp_renderer.py:58` |
| frpc | 0.52.0 | the TOML file the hub writes, which frpc reads from 0.52.0; SakuraFrp's and OpenFrp's config APIs return TOML for it | frpc's file ([hub_components/network.md](hub_components/network.md), "Picking a tunnel"); the carried `FRP_VERSION` is at or above it |
| OpenSSH client | 7.6 | `StrictHostKeyChecking=accept-new` in the relay's `ssh` start line | the relay's start line ([hub_components/network.md](hub_components/network.md)) |
| OpenSSH client, a relay with a password | 8.4, or `DISPLAY` set before it | `SSH_ASKPASS_REQUIRE=force`, which makes ssh ask the askpass program and never a terminal; an older client asks it when it has no terminal and `DISPLAY` is set, and the start line sets both | the relay's password start line ([hub_components/network.md](hub_components/network.md), "What the hub runs") |

The relay needs an OpenSSH client on every system the hub runs on, and each
system has one from its own vendor:

| System | Where `ssh` comes from | Oldest supported release has |
| --- | --- | --- |
| Debian family | `openssh-client`, a dependency of the hub's `.deb` | Debian 12: 9.2 |
| Fedora and RHEL family | `openssh-clients`, a dependency of the `.rpm` | RHEL 9: 8.7 |
| Arch family | `openssh`, a dependency of the Arch package | a rolling release |
| macOS | `/usr/bin/ssh`, part of the system | macOS 12: 8.6 |
| Windows | `%SystemRoot%\System32\OpenSSH\ssh.exe`, the optional feature `OpenSSH.Client`, installed by default since Windows 10 1803 | Windows 10 1809: 7.7 |

A relay that logs in with a password was proven with Debian 12's 9.2 and
Windows 11's `OpenSSH_for_Windows_9.5p2`, which runs an askpass `.cmd`.
Whether Windows 10 1809's 7.7 takes `SSH_ASKPASS` through `DISPLAY` is not
proven; a relay with a key needs neither.

On Linux the name is one more entry in `SYSTEM_RUNTIME_PACKAGES`, spelled
per family in `SYSTEM_PACKAGE_NAMES`
(`hub/neutrino_hub/system/constants.py`), so the dependency fields and
`nhub setup`'s check name it alike. On macOS and Windows the hub's package
names no dependency.

## What the agent drives

A managed machine runs whatever its distribution gives it, and those machines
are older than the hub's, so the agent reads both the podman and the Samba
releases a supported family provides.

| Program | Minimum | What needs it | Where |
| --- | --- | --- | --- |
| podman on Linux | 3.4 | every container is one systemd unit that runs `podman run` with flags Podman 3.4 has, and reads its environment with `--env-file`; nothing splits by Podman version; the floor is Linux's alone | `agent/neutrino_agent/modules/podman/renderer.py` |
| runc on Linux | the distribution's, any | every container's unit runs `podman run --runtime runc`, installed with `podman` on every family; the crun 0.17 of Ubuntu 22.04 answers EPERM to `fchmodat2`, which an image built on glibc 2.39 or later calls at its start; the Podman machine on Windows and macOS keeps its image's own runtime | `agent/neutrino_agent/modules/podman/renderer.py`, `hub/neutrino_hub/data/manifests/podman.json` |
| Podman on Windows and macOS | the tested version each platform entry of `podman.json` names, or the version the machine chose: 6.1.4 for Windows amd64, a 6.x release for macOS arm64, a 5.8.x release for macOS amd64 | Containers there; Podman inside the machine is the machine image's own, and runs the same units as Linux | `hub/neutrino_hub/data/manifests/podman.json` |
| WSL | 2, from the WSL msi the Windows entry pins at 3.0.3, on Windows 10 2004, build 19041, or later | the Podman machine on Windows; Podman's msi refuses an older build, and the entry's `min_version` is 19041 | `hub/neutrino_hub/data/manifests/podman.json` |
| macOS, for Containers | 13 | the Podman machine on applehv; the macOS entries' `min_version` | `hub/neutrino_hub/data/manifests/podman.json` |
| The Podman machine's memory, for Ayakaleaf | 2 GiB, Podman's default | Ayakaleaf's three containers, about 1.6 GB idle; in the default 2 GiB machine on Windows the app started and compiled with about 0.7 GB left, so a second container module beside it needs more memory in the Containers tab's Run settings ([agent/modules/ayakaleaf.md](agent/modules/ayakaleaf.md), "Memory and disk") | `hub/neutrino_hub/data/manifests/ayakaleaf.json` |
| Samba | 4.15 | the session list; `smbstatus --json` exists from 4.16, and below it the text tables of `-p` and `-S` are parsed | `agent/neutrino_agent/modules/samba/applier.py:356` |
| systemd | 236 | `systemd-run --collect` for the transient unit a self-update runs in | `agent/neutrino_agent/core/self_update.py:216` |
| systemd | 243 | `OOMPolicy=` on the transient service a CloudCLI install runs as; systemd 249 refuses it on a scope | `agent/neutrino_agent/modules/cloudcli/linux_applier.py` |
| util-linux | any | `runuser` for stepping down to an account | `agent/neutrino_agent/platforms/linux.py:211` |
| Windows PowerShell | 5.1, with the SmbShare, NetSecurity, ScheduledTasks and LocalAccounts modules, all in Windows 10 1607 | the PowerShell host's function library on Windows: the file share, the scheduled tasks, the thermal zones | `agent/neutrino_agent/data/windows/powershell_host.ps1` |
| `sharing`, `sysadminctl`, `pwpolicy`, `dscl`, `pfctl` | macOS 12 | the file share on macOS | `agent/neutrino_agent/modules/samba/darwin_applier.py` |
| git | 2.0, Gitea's own floor | Gitea on every system; the machine's own on macOS and Windows, never installed by the module there | `agent/neutrino_agent/modules/gitea/` |
| Gitea's release binaries | macOS 10.12 and Windows 10 by their builds, below the agent's own floors | the Gitea module on macOS and Windows | `hub/neutrino_hub/data/manifests/gitea.json` |
| glibc | 2.28, below the agent's floor | the VS Code server Microsoft's CLI downloads for `serve-web`, the Node.js build CloudCLI runs on, and code-server's standalone release builds (with `GLIBCXX_3.4.21`); the agent's own 2.34 covers them, so their Linux entries name no `min_version` | `hub/neutrino_hub/data/manifests/vscode.json`, `cloudcli.json`, `code_server.json` |
| glibc | 2.34, the agent's floor | Codeg's `codeg-server`, `codeg-mcp` and `codeg-computer-helper`, x64 and arm64 | `hub/neutrino_hub/data/manifests/codeg.json`, which names no `min_version` since the floor is the same |
| glibc | none | SiYuan's kernel, a static-pie ELF on amd64 and arm64 | `hub/neutrino_hub/data/manifests/siyuan.json`, whose Linux entries name no `min_version` |
| `tar.exe` on Windows | the build whose `tar.exe` reads LZMA inside a 7z archive; build 26100's, bsdtar 3.8.9 with liblzma, does | SiYuan's Windows installer, which the agent unpacks with it ([agent/modules/siyuan.md](agent/modules/siyuan.md)) | the Windows entry's `min_version` in `hub/neutrino_hub/data/manifests/siyuan.json` |

Containers on Windows was proven on build 26100 alone. Build 19041 is what
both msi files accept: Podman's refuses an older build with a launch
condition, the WSL msi checks no build, and Microsoft states 19041 as WSL's
floor. Podman 6 supports Windows 11 alone, so a Windows 10 machine runs a
Podman its publisher no longer supports there. The macOS floor of 13 is not
proven by a run: the `podman_macos` CI job installs Podman and makes a
machine on macOS 15, on `macos-15` for arm64 and `macos-15-intel` for amd64,
and starts no machine. A lower or a proven floor moves the entry's
`min_version` and this row together.

A floor in these tables is the tested version's. `min_version` belongs to a
platform entry and holds for every version a machine chooses there. A
version that does not run on the machine ends `install_failed` with the
failure's code ([agent/module_install.md](agent/module_install.md), "Module
versions").

## What the client's window loads

| Component | Minimum | What needs it | Where |
| --- | --- | --- | --- |
| WebKitGTK | the 4.0 or the 4.1 ABI | the window itself; `ctypes.CDLL` opens the newest library the machine has and pins the bindings to that API version | `client/desktop/neutrino_client/constants.py:88`, `client/desktop/neutrino_client/gui/webkitgtk.py:196` |
| girepository | 1.72, installed by the package | PyGObject 3.50 compiles against calls that arrived in 1.72, and RHEL 9 has 1.68 | `client/desktop/packaging/payload.py:127` |
| libffi | 8 | the bindings compiled in `debian:12` link it | `client/desktop/packaging/payload.py:136` |
| AyatanaAppIndicator3 | optional | the tray; without `libayatana-appindicator3.so.1` the tray is drawn as a GTK status icon | `client/desktop/neutrino_client/gui/tray_linux.py:17`, `client/desktop/neutrino_client/gui/tray_linux.py:98` |
| pyobjc | 12.2.2, from wheels tagged macOS 10.13 | the macOS window | `packaging/build/build_client_macos.py:131` |
| Windows Installer | 5.0 | the `.msi`, which WiX 6 writes at that version by default | `packaging/shared/wix_build.py:28` |

## Why the client's floor comes from its build container

The client is the one package that compiles C where it is built. Nuitka
generates C for `nclient` and for `mount_helper`, and the container's linker
binds every libc call to the newest symbol version that container's glibc
defines (`packaging/shared/nuitka_build.py:57`). An older machine refuses those
symbol versions whatever its distribution is called.

Building the `.rpm` in `fedora:41` produced a package RHEL 9 could not load:
glibc 2.40 resolves `strtol` and `sscanf` to the `__isoc23_*` symbols that
arrived in 2.38, so the binaries asked for 2.38 on a family whose oldest
member has 2.34. Both Linux clients are built in `debian:12` now
(`packaging/build/build_client_desktop.py:27`), which puts every symbol at 2.34 or below
and leaves the RHEL-family names to the spec file.

The hub and the agent compile nothing in their containers. The hub installs
wheels and an interpreter build, the agent copies upstream binaries, and the
floor of each is the highest version those files name. The hub's `.msi` and
`.pkg` are compiled by Nuitka on the runner, as the agent's are.

## How the floor is kept

**Nothing is compiled during a hub build.** The pip install passes
`--only-binary=:all:` (`hub/packaging/venv_tree.py:355`), so a dependency
with no wheel for the machine fails the build instead of being compiled
quietly against the container's glibc. Every package the hub declares has a
cp313 wheel for x86-64 and for aarch64, the highest tag among them being
`manylinux_2_28`. The macOS and Windows builds pass the same flag, and the
macOS build reads every Mach-O of the finished tree back with `otool -L`: a
reference to `/usr/local/`, `/opt/homebrew/` or any path outside the
system's own libraries fails the build, since a wheel linked against the
runner's Homebrew OpenSSL loads on the runner and on nothing else.

**Every finished tree is read back.** `require_glibc_floor` walks each ELF in
the staged tree, takes the highest `GLIBC_` version any of them names, and
exits when it is above `PACKAGING_GLIBC_FLOOR`
(`hub/packaging/venv_tree.py:633`, `agent/packaging/payload.py:343`,
`client/desktop/packaging/payload.py:437`). The constant is 2.34 in all three
packages (`hub/packaging/constants.py:13`, `agent/packaging/constants.py:12`,
`client/desktop/packaging/constants.py:13`). A build whose tree needs more than
that fails at that line, before anything is published.

**The two formats declare the floor differently.** An `.rpm` gets its glibc
requirement from a scan of its own payload, with only the interpreter's library
excluded (`client/desktop/packaging/build_rpm.py:97`), so `dnf` rejects a
package the machine is too old for. A `.deb` declares no libc dependency at
all, and `apt` installs it on a machine below the floor, where the first run
fails on the missing symbol version. The assertion at build time takes the
place of the declaration the format omits.

**A VM of the oldest system is the proof.**
`packaging/lab/setup_vms.sh ubuntu 22.04` builds that machine
(`packaging/lab/setup_vms.sh:50`), and `run_mode_matrix.sh` installs
the packages on it and exercises the modes. A floor in this page moves after
that run has passed on the system it names.
