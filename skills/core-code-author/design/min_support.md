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
| agent `.deb`, `.rpm` | 2.27 | the RustDesk host binary (`agent/packaging/constants.py:8`) | Debian 12, Ubuntu 22.04, RHEL 9 |
| client `.deb` | 2.34 | `nclient` and `mount_helper`, compiled in `debian:12` (`packaging/build_release.py:164`) | Debian 12, Ubuntu 22.04 |
| client `.rpm` | 2.34 | the same two binaries out of the same container (`packaging/build_release.py:174`) | RHEL 9, AlmaLinux 9 |
| client `.pkg` | none | the RustDesk app, built for macOS 12.3 (`client/packaging/bundled.py:78`) | macOS 12.3 on Apple silicon |
| client `.msi` | none | the WebView2 Evergreen runtime and CPython 3.13 (`client/packaging/build_msi.py:28`, `client/packaging/build_msi.py:69`) | Windows 10 1809 |

Ubuntu 22.04 has glibc 2.35, above all four Linux floors, and the hub's `.deb`
reaches it because the DHCP client is named `dhcpcd-base | dhcpcd5`
(`hub/neutrino_hub/system/constants.py:134`): Ubuntu has the first name from
24.04 and the same daemon in the second before it, whose unit the takeover
stands down with every other manager's. One table spells the names for every
family, and both the control field of the `.deb` and the packages `nhub setup`
checks read it (`hub/neutrino_hub/system/package_manager.py:420`), so a
machine installs and is checked against whichever of the two names its
repositories carry (`hub/neutrino_hub/system/package_manager.py:128`).

The client's `.rpm` reaches RHEL 9 and AlmaLinux 9 because either WebKit2 ABI
satisfies it, and RHEL 9 has 4.0 (`client/packaging/build_rpm.py:54`). The
introspection library on RHEL 9 is older than the bindings need, so the
package installs its own (`client/packaging/payload.py:130`).

## What the hub drives

The hub's renderers and its units require these versions of the software a
distribution provides.

| Program | Minimum | What needs it | Where |
| --- | --- | --- | --- |
| nftables | 0.9 | `socket transparent` and `tproxy` in the proxy chains | `hub/neutrino_hub/modules/router/nft_renderer.py:118` |
| dnsmasq | 2.55 | `bind-dynamic`, which starts on an interface that has no address yet | `hub/neutrino_hub/modules/router/dnsmasq_renderer.py:72` |
| systemd | 245 | `ProtectClock=` in the panel's unit, the newest directive any unit uses | `hub/neutrino_hub/data/services/neutrino_hub_web.service:28` |
| iproute2 | 4.13 | `ip -json` for links, addresses and routes | `hub/neutrino_hub/modules/router/link_status.py:322` |
| vnstat | 2.0 | `vnstat --json`, whose version 2 layout the traffic history parses | `hub/neutrino_hub/system/vnstat_history.py:79` |
| fail2ban | 0.11 | the `nftables-multiport` ban action the SSH jail sets | `hub/neutrino_hub/system/constants.py:166` |
| wpa_supplicant, hostapd | 2.9 | SAE with `ieee80211w` for a WPA3 network; the access point renders WPA2 only | `hub/neutrino_hub/modules/router/supplicant_renderer.py:101` |
| dhcpcd | 7.1 | `nohook`, which keeps the client off resolv.conf and the hostname | `hub/neutrino_hub/modules/router/dhcp_renderer.py:58` |

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

## What the client's window loads

| Component | Minimum | What needs it | Where |
| --- | --- | --- | --- |
| WebKitGTK | the 4.0 or the 4.1 ABI | the window itself; `ctypes.CDLL` opens the newest library the machine has and pins the bindings to that API version | `client/neutrino_client/constants.py:88`, `client/neutrino_client/gui/webkitgtk.py:196` |
| girepository | 1.72, installed by the package | PyGObject 3.50 compiles against calls that arrived in 1.72, and RHEL 9 has 1.68 | `client/packaging/payload.py:130` |
| libffi | 8 | the bindings compiled in `debian:12` link it | `client/packaging/payload.py:139` |
| AyatanaAppIndicator3 | optional | the tray; without `libayatana-appindicator3.so.1` the tray is drawn as a GTK status icon | `client/neutrino_client/gui/tray_linux.py:17`, `client/neutrino_client/gui/tray_linux.py:98` |
| pyobjc | 12.2.2, from wheels tagged macOS 10.13 | the macOS window | `client/packaging/build_pkg.py:78` |
| Windows Installer | 5.0 | the `.msi`, which WiX 6 writes at that version by default | `client/packaging/build_msi.py:204` |

## Why the client's floor comes from its build container

The client is the one package that compiles C where it is built. Nuitka
generates C for `nclient` and for `mount_helper`, and the container's linker
binds every libc call to the newest symbol version that container's glibc
defines (`client/packaging/payload.py:550`). An older machine refuses those
symbol versions whatever its distribution is called.

Building the `.rpm` in `fedora:41` produced a package RHEL 9 could not load:
glibc 2.40 resolves `strtol` and `sscanf` to the `__isoc23_*` symbols that
arrived in 2.38, so the binaries asked for 2.38 on a family whose oldest
member has 2.34. Both Linux clients are built in `debian:12` now
(`packaging/build_release.py:162`), which puts every symbol at 2.34 or below
and leaves the RHEL-family names to the spec file.

The hub and the agent compile nothing in their containers. The hub installs
wheels and an interpreter build, the agent copies upstream binaries, and the
floor of each is the highest version those files name.

## How the floor is kept

**Nothing is compiled during a hub build.** The pip install passes
`--only-binary=:all:` (`hub/packaging/venv_tree.py:355`), so a dependency
with no wheel for the machine fails the build instead of being compiled
quietly against the container's glibc. Every package the hub declares has a
cp313 wheel for x86-64 and for aarch64, the highest tag among them being
`manylinux_2_28`.

**Every finished tree is read back.** `require_glibc_floor` walks each ELF in
the staged tree, takes the highest `GLIBC_` version any of them names, and
exits when it is above `PACKAGING_GLIBC_FLOOR`
(`hub/packaging/venv_tree.py:633`, `agent/packaging/payload.py:343`,
`client/packaging/payload.py:440`). The constant is 2.34 in all three
packages (`hub/packaging/constants.py:12`, `agent/packaging/constants.py:12`,
`client/packaging/constants.py:13`). A build whose tree needs more than that
fails at that line, before anything is published.

**The two formats declare the floor differently.** An `.rpm` gets its glibc
requirement from a scan of its own payload, with only the interpreter's
library excluded (`client/packaging/build_rpm.py:97`), so `dnf` rejects a
package the machine is too old for. A `.deb` declares no libc dependency at
all, and `apt` installs it on a machine below the floor, where the first run
fails on the missing symbol version. The assertion at build time takes the
place of the declaration the format omits.

**A VM of the oldest system is the proof.**
`packaging/integration/setup_vms.sh ubuntu 22.04` builds that machine
(`packaging/integration/setup_vms.sh:48`), and `run_mode_matrix.sh` installs
the packages on it and exercises the modes. A floor in this page moves after
that run has passed on the system it names.
