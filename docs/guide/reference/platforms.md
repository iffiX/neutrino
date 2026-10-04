---
title: Supported platforms
---

# Supported platforms

Neutrino 0.5.0 has a hub, an agent, a desktop client and an Android app, and each table on this page names the systems one of them installs on and the release file for each. Every file is on the [releases page](https://github.com/iffiX/neutrino/releases), beside `SHA256SUMS` and the source archive. Every build is 64-bit.

## Hub

| System                                                                                   | Architecture | File                                      |
| ---------------------------------------------------------------------------------------- | ------------ | ----------------------------------------- |
| Debian 12 and newer, Ubuntu 22.04 and newer, Raspberry Pi OS 64-bit (bookworm and newer) | x86-64       | `neutrino-hub_0.5.0_amd64.deb`            |
| the same                                                                                 | ARM64        | `neutrino-hub_0.5.0_arm64.deb`            |
| Fedora 41 and newer; RHEL 9 family (AlmaLinux, Rocky) with EPEL enabled first            | x86-64       | `neutrino-hub-0.5.0-1.x86_64.rpm`         |
| the same                                                                                 | ARM64        | `neutrino-hub-0.5.0-1.aarch64.rpm`        |
| Arch, EndeavourOS, Manjaro                                                               | x86-64       | `neutrino-hub-0.5.0-1-x86_64.pkg.tar.zst` |

The hub package includes its own Python and depends on systemd, nftables, dnsmasq, iproute2, wpa_supplicant, dhcpcd, fail2ban, iw, arp-scan, vnstat, curl and smbclient. It recommends hostapd for a box that serves Wi-Fi. On the Debian family the dhcpcd dependency is `dhcpcd-base | dhcpcd5`, because Ubuntu 22.04 has the daemon under the second name.

## Agent

| System                                                              | Architecture | File                                     |
| ------------------------------------------------------------------- | ------------ | ---------------------------------------- |
| Debian 12 and newer, Ubuntu 22.04 and newer, Raspberry Pi OS 64-bit | x86-64       | `neutrino-agent_0.5.0_amd64.deb`         |
| the same                                                            | ARM64        | `neutrino-agent_0.5.0_arm64.deb`         |
| Fedora 41 and newer; RHEL 9 family                                  | x86-64       | `neutrino-agent-0.5.0-1.x86_64.rpm`      |
| the same                                                            | ARM64        | `neutrino-agent-0.5.0-1.aarch64.rpm`     |
| Windows 10 1809 and newer, Windows 11                               | x86-64       | `neutrino-agent-0.5.0-windows-amd64.msi` |
| macOS 12.3 and newer on Apple silicon                               | ARM64        | `neutrino-agent-0.5.0-macos-arm64.pkg`   |

The agent has no window. On Linux it runs as root, and its package includes its own interpreter and the RustDesk host. On Windows it runs as a LocalSystem service and on macOS as a root LaunchDaemon; both installers include the compiled agent and RustDesk. Windows 10 1809 is the first release with the pseudo console the terminal runs on. The Windows build is x86-64 only, because RustDesk publishes no Windows ARM64 build.

## Desktop client

| System                                                                           | Architecture | File                                      |
| -------------------------------------------------------------------------------- | ------------ | ----------------------------------------- |
| Debian 12 and newer, Ubuntu 22.04 and newer, with a desktop session              | x86-64       | `neutrino-client_0.5.0_amd64.deb`         |
| the same                                                                         | ARM64        | `neutrino-client_0.5.0_arm64.deb`         |
| RHEL 9 family (AlmaLinux, Rocky) and Fedora 41 and newer, with a desktop session | x86-64       | `neutrino-client-0.5.0-1.x86_64.rpm`      |
| the same                                                                         | ARM64        | `neutrino-client-0.5.0-1.aarch64.rpm`     |
| Windows 10 1809 and newer, Windows 11                                            | x86-64       | `neutrino-client-0.5.0-windows-amd64.msi` |
| macOS 12.3 and newer on Apple silicon                                            | ARM64        | `neutrino-client-0.5.0-macos-arm64.pkg`   |

The Linux client opens its window on either WebKitGTK ABI, 4.1 or 4.0, and needs `cifs-utils` and polkit for shares. Without the appindicator library the tray is drawn as a GTK status icon. The Windows build is x86-64 only, because cc-switch publishes no Windows ARM64 build, and it installs WebView2 when the runtime is absent.

## Android app

| System                | Architecture | File                                |
| --------------------- | ------------ | ----------------------------------- |
| Android 8.0 and newer | arm64-v8a    | `neutrino-client-0.5.0-android.apk` |

Android 8.0 is API level 26, the `minSdk` the app declares, and the phone's installer rejects the app on an older system.

## Modules by system

A module the machine's system cannot run is greyed out in the **Modules** page's picker with **This machine's system cannot run it**. The table reads from the module manifests the hub carries.

| Module                                                 | Linux                                               | Windows                     | macOS                       |
| ------------------------------------------------------ | --------------------------------------------------- | --------------------------- | --------------------------- |
| File share                                             | Samba from the distribution's packages              | the system's own SMB server | the system's own SMB server |
| Gitea                                                  | x86-64 and ARM64                                    | no                          | no                          |
| Containers                                             | Podman from the distribution's packages             | no                          | no                          |
| ZFS storage                                            | OpenZFS from the repository each family keeps it in | no                          | no                          |
| VS Code                                                | x86-64 and ARM64, glibc 2.28 and newer              | x86-64                      | Apple silicon               |
| code-server                                            | x86-64 and ARM64, glibc 2.28 and newer              | no                          | Apple silicon and Intel     |
| CloudCLI                                               | x86-64 and ARM64, glibc 2.28 and newer              | x86-64 and ARM64            | Apple silicon and Intel     |
| AnyDesk, TeamViewer, as remote desktops on **Devices** | detected when a person installed it                 | the same                    | the same                    |

The agent reads its modules at these versions of what the machine provides:

| Program            | Oldest version                              |
| ------------------ | ------------------------------------------- |
| Podman             | 3.4; from 4.4 a container is a Quadlet file |
| Samba              | 4.15                                        |
| ZFS                | 2.1                                         |
| Windows PowerShell | 5.1, for the file share on Windows          |
| macOS              | 12, for the file share on macOS             |
