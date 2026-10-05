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
| hub `.pkg` | none | the agent `.pkg` it carries and installs on its own machine at setup | macOS 12.3, arm64 and amd64 |
| agent `.deb`, `.rpm` | 2.27 | the RustDesk host binary (`agent/packaging/constants.py:8`) | Debian 12, Ubuntu 22.04, RHEL 9 |
| agent `.msi` | none | the pseudo console the shell stream runs PowerShell on (`agent/neutrino_agent/streams/windows_shell.py:76`) | Windows 10 1809 |
| agent `.pkg` | none | the RustDesk app, built for macOS 12.3 (`packaging/shared/rustdesk_assets.py:41`) | macOS 12.3, arm64 and amd64 |
| client `.deb` | 2.34 | `nclient` and `mount_helper`, compiled in `debian:12` (`packaging/build/build_client_desktop.py:40`) | Debian 12, Ubuntu 22.04 |
| client `.rpm` | 2.34 | the same two binaries out of the same container (`packaging/build/build_client_desktop.py:50`) | RHEL 9, AlmaLinux 9 |
| client `.pkg` | none | the RustDesk app, built for macOS 12.3 (`packaging/shared/rustdesk_assets.py:41`) | macOS 12.3, arm64 and amd64 |
| client `.msi` | none | the WebView2 Evergreen runtime and CPython 3.13 (`packaging/build/build_client_windows.py:41`, `packaging/build/build_client_windows.py:90`) | Windows 10 1809 |
| client `.apk` | none | `openProxyFileDescriptor`, which the Files provider serves a share's file through, from API level 26 (`minSdk` in `client/android/`) | Android 8.0 |
| client iOS app, paused | none | `NSFileProviderReplicatedExtension`, the File Provider extension's base class, from iOS 16 (the deployment target in `client/ios/`) | iOS 16 |

Ubuntu 22.04 has glibc 2.35, above all four Linux floors, and the hub's `.deb`
reaches it because the DHCP client is named `dhcpcd-base | dhcpcd5`
(`hub/neutrino_hub/system/constants.py:134`): Ubuntu has the first name from
24.04 and the same daemon in the second before it, whose unit the takeover
stands down with every other manager's. One table spells the names for every
family, and both the control field of the `.deb` and the packages `nhub setup`
checks read it (`hub/neutrino_hub/system/package_manager.py:420`), so a
machine installs and is checked against whichever of the two names its
repositories carry (`hub/neutrino_hub/system/package_manager.py:128`).

The cc-switch the agent fetches from the hub (`data/manifests/cc_switch.json`)
moves no floor. On Linux it is
upstream's musl build, which is linked statically and names no glibc
(`client/desktop/packaging/bundled.py:42`), and on Windows and macOS it is
the build the client's `.msi` and `.pkg` already carry on the same floors.

The client's `.rpm` reaches RHEL 9 and AlmaLinux 9 because either WebKit2 ABI
satisfies it, and RHEL 9 has 4.0 (`client/desktop/packaging/build_rpm.py:54`).
The introspection library on RHEL 9 is older than the bindings need, so the
package installs its own (`client/desktop/packaging/payload.py:127`).

The amd64 macOS packages are built on GitHub's `macos-15-intel` runner, for
`intl` only. GitHub provides its Intel macOS runners until autumn 2027, and
macOS Tahoe 26 is the last macOS for Intel Macs; whether the amd64 packages
continue is decided then.

The two phone rows are the floor each app's build declares: `minSdk 26` in
the Gradle project and a deployment target of 16.0 in the Xcode project. The
phone's installer rejects the app on an older system, so the floor is
enforced by the declaration itself.

## What the hub drives

The hub's renderers and its units require these versions of the software a
distribution provides.

| Program | Minimum | What needs it | Where |
| --- | --- | --- | --- |
| nftables | 0.9 | `socket transparent` and `tproxy` in the proxy chains | `hub/neutrino_hub/modules/router/nft_renderer.py:118` |
| dnsmasq | 2.73 | `min-cache-ttl`, the floor under every cached answer's TTL | `hub/neutrino_hub/modules/router/dnsmasq_renderer.py:63` |
| systemd | 245 | `ProtectClock=` in the panel's unit, the newest directive any unit uses | `hub/neutrino_hub/data/services/neutrino_hub_web.service:28` |
| iproute2 | 4.13 | `ip -json` for links, addresses and routes | `hub/neutrino_hub/modules/router/link_status.py:322` |
| vnstat | 2.0 | `vnstat --json`, whose version 2 layout the traffic history parses | `hub/neutrino_hub/system/vnstat_history.py:79` |
| fail2ban | 0.11 | the `nftables-multiport` ban action the SSH jail sets | `hub/neutrino_hub/system/constants.py:166` |
| wpa_supplicant, hostapd | 2.9 | SAE with `ieee80211w` for a WPA3 network; the access point renders WPA2 only | `hub/neutrino_hub/modules/router/supplicant_renderer.py:101` |
| dhcpcd | 7.1 | `nohook`, which keeps the client off resolv.conf and the hostname | `hub/neutrino_hub/modules/router/dhcp_renderer.py:58` |
| OpenSSH client | 7.6 | `StrictHostKeyChecking=accept-new` in the relay's `ssh` start line | the relay's start line ([modules/network.md](modules/network.md)) |

The relay needs an OpenSSH client on every system the hub runs on, and each
system has one from its own vendor:

| System | Where `ssh` comes from | Oldest supported release has |
| --- | --- | --- |
| Debian family | `openssh-client`, a dependency of the hub's `.deb` | Debian 12: 9.2 |
| Fedora and RHEL family | `openssh-clients`, a dependency of the `.rpm` | RHEL 9: 8.7 |
| Arch family | `openssh`, a dependency of the Arch package | a rolling release |
| macOS | `/usr/bin/ssh`, part of the system | macOS 12: 8.6 |
| Windows | `%SystemRoot%\System32\OpenSSH\ssh.exe`, the optional feature `OpenSSH.Client`, installed by default since Windows 10 1803 | Windows 10 1809: 7.7 |

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
| podman | 3.4 | a container becomes a plain unit below 4.4 and a Quadlet `.container` file from 4.4 | `agent/neutrino_agent/modules/podman/constants.py:5`, `agent/neutrino_agent/modules/podman/applier.py:90` |
| Samba | 4.15 | the session list; `smbstatus --json` exists from 4.16, and below it the text tables of `-p` and `-S` are parsed | `agent/neutrino_agent/modules/samba/applier.py:356` |
| ZFS | 2.1 | `zpool status` and `zpool import` are read as text, because neither has a machine format on this release | `agent/neutrino_agent/modules/zfs/applier.py:4` |
| systemd | 236 | `systemd-run --collect` for the transient unit a self-update runs in | `agent/neutrino_agent/core/self_update.py:90` |
| util-linux | any | `runuser` for stepping down to an account | `agent/neutrino_agent/platforms/linux.py:211` |
| Windows PowerShell | 5.1, with the SmbShare, NetSecurity and LocalAccounts modules, all in Windows 10 1607 | the file share on Windows | `agent/neutrino_agent/modules/samba/windows_applier.py` |
| `sharing`, `sysadminctl`, `pwpolicy`, `dscl`, `pfctl` | macOS 12 | the file share on macOS | `agent/neutrino_agent/modules/samba/darwin_applier.py` |
| git | 2.0, Gitea's own floor | Gitea on every system; the machine's own on macOS and Windows, never installed by the module there | `agent/neutrino_agent/modules/gitea/` |
| Gitea's release binaries | macOS 10.12 and Windows 10 by their builds, below the agent's own floors | the Gitea module on macOS and Windows | `hub/neutrino_hub/data/manifests/gitea.json` |
| glibc | 2.28 | the VS Code server that Microsoft's CLI downloads for `serve-web`; below it the module reads as one the machine cannot run | `min_version` of the Linux entries in `hub/neutrino_hub/data/manifests/vscode.json` |
| glibc | 2.28, VS Code's `min_version` | the Node.js build CloudCLI runs on | `min_version` of the Linux entries in `hub/neutrino_hub/data/manifests/cloudcli.json` |
| glibc, libstdc++ | glibc 2.28 and `GLIBCXX_3.4.21` | code-server's standalone release builds, the only builds the module installs; on macOS they name no minimum beyond the agent's own; no Windows build is offered | `min_version` of the Linux entries in `hub/neutrino_hub/data/manifests/code_server.json` |

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
