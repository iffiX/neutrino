---
title: Supported platforms
---

# Supported platforms

Each part of Neutrino 0.5.0 has a section here with the systems it installs on and its release files. Every file is on the [releases page](https://github.com/iffiX/neutrino/releases), beside `SHA256SUMS` and the source archive. Every build is 64-bit.

## Hub

| System                                                                                   | Architecture | File                                      |
| ---------------------------------------------------------------------------------------- | ------------ | ----------------------------------------- |
| Debian 12 and newer, Ubuntu 22.04 and newer, Raspberry Pi OS 64-bit, bookworm and newer  | x86-64       | `neutrino-hub_0.5.0_amd64.deb`            |
| the same                                                                                 | ARM64        | `neutrino-hub_0.5.0_arm64.deb`            |
| Fedora 41 and newer; RHEL 9 family, such as AlmaLinux and Rocky, with EPEL enabled first | x86-64       | `neutrino-hub-0.5.0-1.x86_64.rpm`         |
| the same                                                                                 | ARM64        | `neutrino-hub-0.5.0-1.aarch64.rpm`        |
| Arch, EndeavourOS, Manjaro                                                               | x86-64       | `neutrino-hub-0.5.0-1-x86_64.pkg.tar.zst` |
| Windows 10 1809 and newer, Windows 11, server mode only                                  | x86-64       | `neutrino-hub-0.5.0-windows-amd64.msi`    |
| macOS 12.3 and newer on Apple silicon, server mode only                                  | ARM64        | `neutrino-hub-0.5.0-macos-arm64.pkg`      |
| macOS 12.3 and newer on Intel, server mode only                                          | x86-64       | `neutrino-hub-0.5.0-macos-amd64.pkg`      |

The Linux hub package includes its own Python. It depends on systemd, nftables, dnsmasq, iproute2, wpa_supplicant, dhcpcd, fail2ban, iw, arp-scan, vnstat, curl, smbclient, the OpenSSH client and pkexec. It recommends hostapd for a machine that serves Wi-Fi.

On the Debian family the dhcpcd dependency reads `dhcpcd-base | dhcpcd5`, because Ubuntu 22.04 has the daemon under the second name. The pkexec dependency reads `pkexec | policykit-1` there, and on the Fedora family and Arch it is `polkit`. The Windows and macOS packages include every program the hub drives and name no dependency. Server mode, the one mode the hub has there, is described on [Network](../hub/network.md).

## Agent

| System                                                              | Architecture | File                                     |
| ------------------------------------------------------------------- | ------------ | ---------------------------------------- |
| Debian 12 and newer, Ubuntu 22.04 and newer, Raspberry Pi OS 64-bit | x86-64       | `neutrino-agent_0.5.0_amd64.deb`         |
| the same                                                            | ARM64        | `neutrino-agent_0.5.0_arm64.deb`         |
| Fedora 41 and newer; RHEL 9 family                                  | x86-64       | `neutrino-agent-0.5.0-1.x86_64.rpm`      |
| the same                                                            | ARM64        | `neutrino-agent-0.5.0-1.aarch64.rpm`     |
| Windows 10 1809 and newer, Windows 11                               | x86-64       | `neutrino-agent-0.5.0-windows-amd64.msi` |
| macOS 12.3 and newer on Apple silicon                               | ARM64        | `neutrino-agent-0.5.0-macos-arm64.pkg`   |
| macOS 12.3 and newer on Intel                                       | x86-64       | `neutrino-agent-0.5.0-macos-amd64.pkg`   |

The agent has no window. Its Linux package includes its own interpreter and the RustDesk host.

The Windows and macOS installers put RustDesk in the agent's own directory. The agent registers it with the system only while the machine's **Remote desktop** switch is on. Windows 10 1809 is the first release with the pseudo console the terminal runs on. The Windows build is x86-64 only, because RustDesk publishes no Windows ARM64 build.

## Desktop client

| System                                                                                      | Architecture | File                                      |
| ------------------------------------------------------------------------------------------- | ------------ | ----------------------------------------- |
| Debian 12 and newer, Ubuntu 22.04 and newer, with a desktop session                         | x86-64       | `neutrino-client_0.5.0_amd64.deb`         |
| the same                                                                                    | ARM64        | `neutrino-client_0.5.0_arm64.deb`         |
| RHEL 9 family, such as AlmaLinux and Rocky, and Fedora 41 and newer, with a desktop session | x86-64       | `neutrino-client-0.5.0-1.x86_64.rpm`      |
| the same                                                                                    | ARM64        | `neutrino-client-0.5.0-1.aarch64.rpm`     |
| Windows 10 1809 and newer, Windows 11                                                       | x86-64       | `neutrino-client-0.5.0-windows-amd64.msi` |
| macOS 12.3 and newer on Apple silicon                                                       | ARM64        | `neutrino-client-0.5.0-macos-arm64.pkg`   |
| macOS 12.3 and newer on Intel                                                               | x86-64       | `neutrino-client-0.5.0-macos-amd64.pkg`   |

The Linux client opens its window on either WebKitGTK ABI, 4.1 or 4.0, and needs `cifs-utils` and polkit for shares. Without the AppIndicator library, the tray is drawn as a GTK status icon. The Windows build is x86-64 only, because cc-switch publishes no Windows ARM64 build, and its installer adds WebView2 when the runtime is absent.

## Android app

| System                | Architecture | File                                |
| --------------------- | ------------ | ----------------------------------- |
| Android 8.0 and newer | arm64-v8a    | `neutrino-client-0.5.0-android.apk` |

Android 8.0 is API level 26, the `minSdk` the app declares, and the phone's installer rejects the app on an older system.

## What each part runs as

| Part              | Runs on                                                                        | Runs as                                                                                 |
| ----------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| `neutrino-hub`    | one machine: Linux in any network mode, or macOS or Windows in **Server** mode | a root service on Linux, a root LaunchDaemon on macOS, a LocalSystem service on Windows |
| `neutrino-agent`  | each managed machine, the hub's own machine included                           | the same as the hub, with no window                                                     |
| `neutrino-client` | a person's Linux, Windows or macOS computer                                    | that person's own account                                                               |
| the Android app   | a phone or a tablet                                                            | an app of the phone's owner                                                             |

`nhub setup` also installs an agent on the hub's own machine, so that machine hosts modules like any other managed machine.

## Versions and protocol

Every part of one release speaks the same protocol number, and every 0.5.0 build speaks protocol 3. A 0.5.0 hub admits protocol 3 alone. It rejects a 0.3 or 0.4 agent or client, which speaks protocol 1 or 2, and a program with a newer protocol. The rejected program keeps its binding. An agent the hub admits updates itself when the hub names a newer version, and a 0.3 or 0.4 agent does not.

[The channel](../protocol/channel.md#protocol-numbers) lists the protocol numbers.

## Editions

Each release has two editions built from one source at the same version. The full edition is on GitHub, and the mainland edition is on [Gitee](https://gitee.com/iffiX/neutrino/releases), with file names of the same pattern. The release page a file comes from names its edition.

| Edition  | Files                                                                                                                                                | Left out                                                                                    |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| full     | every file in the tables on this page                                                                                                                | nothing                                                                                     |
| mainland | for the hub, the agent and the desktop client: the `.deb` for x86-64 and ARM64, the Windows `.msi`, the Apple silicon `.pkg`; and the Android `.apk` | the hub has no proxy and no NetBird; the desktop client and the Android app have no NetBird |

The agent program is the same in both editions; the mainland release has fewer of its files. A package upgrades only to a package of its own edition.

## Modules by system

A module the machine's system cannot run is greyed in the **Modules** page's picker with **This machine's system cannot run it**. The table follows the module manifests the hub includes. A **yes** under Windows means x86-64, the one Windows agent build.

| Module                                                 | Linux                                                               | Windows                                                | macOS                       |
| ------------------------------------------------------ | ------------------------------------------------------------------- | ------------------------------------------------------ | --------------------------- |
| File share                                             | Samba from the distribution's packages                              | the system's own SMB server                            | the system's own SMB server |
| Terminal                                               | x86-64 and ARM64; the module sets the account and the shell program | yes; the module sets the shell program, and no account | Apple silicon and Intel     |
| Remote desktop                                         | x86-64 and ARM64                                                    | yes                                                    | Apple silicon and Intel     |
| Gitea                                                  | x86-64 and ARM64                                                    | yes                                                    | Apple silicon and Intel     |
| Containers                                             | Podman from the distribution's packages                             | none                                                   | none                        |
| ZFS storage                                            | OpenZFS from the repository each family keeps it in                 | none                                                   | none                        |
| VS Code                                                | x86-64 and ARM64, glibc 2.28 and newer                              | yes                                                    | Apple silicon and Intel     |
| code-server                                            | x86-64 and ARM64, glibc 2.28 and newer                              | none                                                   | Apple silicon and Intel     |
| CloudCLI                                               | x86-64 and ARM64, glibc 2.28 and newer                              | yes                                                    | Apple silicon and Intel     |
| AnyDesk, TeamViewer, as remote desktops on **Devices** | detected when a person installed it                                 | the same                                               | the same                    |

The agent drives these programs at these versions or newer:

| Program            | Oldest version                                         |
| ------------------ | ------------------------------------------------------ |
| Podman             | 3.4; from 4.4 a container is a Quadlet file            |
| Samba              | 4.15                                                   |
| ZFS                | 2.1                                                    |
| git                | 2.0, for Gitea; on Windows and macOS the machine's own |
| Windows PowerShell | 5.1, for the file share on Windows                     |
| macOS              | 12, for the file share on macOS                        |
