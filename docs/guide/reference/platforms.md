---
title: Supported platforms
---

# Supported platforms

The three packages of one release run on the systems in the tables that follow; every file is on the [releases page](https://github.com/iffiX/neutrino/releases), beside `SHA256SUMS` and the source archive. There is no 32-bit build of anything.

## Hub

| System                                                                                   | Architecture | File                                      |
| ---------------------------------------------------------------------------------------- | ------------ | ----------------------------------------- |
| Debian 12 and newer, Ubuntu 24.04 and newer, Raspberry Pi OS 64-bit (bookworm and newer) | x86-64       | `neutrino-hub_0.2.0_amd64.deb`            |
| the same                                                                                 | ARM64        | `neutrino-hub_0.2.0_arm64.deb`            |
| Fedora 41 and newer; RHEL 9 family (AlmaLinux, Rocky) with EPEL enabled first            | x86-64       | `neutrino-hub-0.2.0-1.x86_64.rpm`         |
| the same                                                                                 | ARM64        | `neutrino-hub-0.2.0-1.aarch64.rpm`        |
| Arch, EndeavourOS, Manjaro                                                               | x86-64       | `neutrino-hub-0.2.0-1-x86_64.pkg.tar.zst` |

The hub package includes its own Python under `/opt/neutrino/python` and depends on systemd, nftables, dnsmasq, iproute2, wpa_supplicant, dhcpcd, fail2ban, iw, arp-scan, vnstat, curl and smbclient, with hostapd recommended for a wireless LAN.

## Agent

| System                                                              | Architecture | File                                 |
| ------------------------------------------------------------------- | ------------ | ------------------------------------ |
| Debian 12 and newer, Ubuntu 24.04 and newer, Raspberry Pi OS 64-bit | x86-64       | `neutrino-agent_0.2.0_amd64.deb`     |
| the same                                                            | ARM64        | `neutrino-agent_0.2.0_arm64.deb`     |
| Fedora 41 and newer; RHEL 9 family                                  | x86-64       | `neutrino-agent-0.2.0-1.x86_64.rpm`  |
| the same                                                            | ARM64        | `neutrino-agent-0.2.0-1.aarch64.rpm` |

The agent is Linux only, runs as root and has no window; its package includes its own interpreter and the RustDesk host.

## Client

| System                                                              | Architecture | File                                      |
| ------------------------------------------------------------------- | ------------ | ----------------------------------------- |
| Debian 12 and newer, Ubuntu 24.04 and newer, with a desktop session | x86-64       | `neutrino-client_0.2.0_amd64.deb`         |
| the same                                                            | ARM64        | `neutrino-client_0.2.0_arm64.deb`         |
| Fedora 41 and newer; RHEL 9 family, with a desktop session          | x86-64       | `neutrino-client-0.2.0-1.x86_64.rpm`      |
| the same                                                            | ARM64        | `neutrino-client-0.2.0-1.aarch64.rpm`     |
| Windows 10 and 11                                                   | x86-64       | `neutrino-client-0.2.0-windows-amd64.msi` |
| macOS on Apple silicon                                              | ARM64        | `neutrino-client-0.2.0-macos-arm64.pkg`   |

The Linux client is compiled and depends on WebKitGTK, the appindicator library, `cifs-utils` and polkit. The Windows build is x86-64 only, because cc-switch has no Windows ARM64 build, and it bootstraps WebView2 when the runtime is absent. The macOS build is Apple silicon only.

## Which package

| Machine                                   | Package                                         |
| ----------------------------------------- | ----------------------------------------------- |
| the one always-on Linux box               | the hub, once; setup installs its agent with it |
| every other Linux machine the hub manages | the agent                                       |
| every computer a person sits at           | the client, on Linux, Windows or macOS          |

The three packages share one version number, and an agent or client on another version than the hub shows an upgrade action.
