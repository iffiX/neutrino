---
title: 支持的平台
---

# 支持的平台

这一页列出 0.2.0 的每个包对应的系统、架构和文件名。三个包共用一个版本号，都从 [Releases](https://github.com/iffiX/neutrino/releases) 下载；没有 32 位 ARM 的包。

## hub

| 系统                                                                            | 架构   | 文件                                      |
| ------------------------------------------------------------------------------- | ------ | ----------------------------------------- |
| Debian 12 及以上、Ubuntu 24.04 及以上、Raspberry Pi OS 64 位（bookworm 及以上） | x86-64 | `neutrino-hub_0.2.0_amd64.deb`            |
| 同上                                                                            | ARM64  | `neutrino-hub_0.2.0_arm64.deb`            |
| Fedora 41 及以上、RHEL 9 系（AlmaLinux、Rocky），先启用 EPEL                    | x86-64 | `neutrino-hub-0.2.0-1.x86_64.rpm`         |
| 同上                                                                            | ARM64  | `neutrino-hub-0.2.0-1.aarch64.rpm`        |
| Arch、EndeavourOS、Manjaro                                                      | x86-64 | `neutrino-hub-0.2.0-1-x86_64.pkg.tar.zst` |

包自带 Python，装在 `/opt/neutrino/python`，与发行版的 Python 无关。

| 依赖           | 软件包                                                                                                                 |
| -------------- | ---------------------------------------------------------------------------------------------------------------------- |
| deb 必需       | systemd、nftables、dnsmasq-base、iproute2、wpasupplicant、dhcpcd-base、fail2ban、iw、arp-scan、vnstat、curl、smbclient |
| deb 推荐       | hostapd                                                                                                                |
| RHEL 系的 EPEL | fail2ban、arp-scan、vnstat                                                                                             |

## 被控端

| 系统                                                         | 架构   | 文件                                 |
| ------------------------------------------------------------ | ------ | ------------------------------------ |
| Debian 12 及以上、Ubuntu 24.04 及以上、Raspberry Pi OS 64 位 | x86-64 | `neutrino-agent_0.2.0_amd64.deb`     |
| 同上                                                         | ARM64  | `neutrino-agent_0.2.0_arm64.deb`     |
| Fedora 41 及以上、RHEL 9 系                                  | x86-64 | `neutrino-agent-0.2.0-1.x86_64.rpm`  |
| 同上                                                         | ARM64  | `neutrino-agent-0.2.0-1.aarch64.rpm` |

被控端只有 Linux 版本，以 root 运行，没有窗口。包自带解释器和 RustDesk 主机。

## 客户端

| 系统                                              | 架构   | 文件                                      |
| ------------------------------------------------- | ------ | ----------------------------------------- |
| Debian 12 及以上、Ubuntu 24.04 及以上，带桌面会话 | x86-64 | `neutrino-client_0.2.0_amd64.deb`         |
| 同上                                              | ARM64  | `neutrino-client_0.2.0_arm64.deb`         |
| Fedora 41 及以上、RHEL 9 系，带桌面会话           | x86-64 | `neutrino-client-0.2.0-1.x86_64.rpm`      |
| 同上                                              | ARM64  | `neutrino-client-0.2.0-1.aarch64.rpm`     |
| Windows 10、Windows 11                            | x86-64 | `neutrino-client-0.2.0-windows-amd64.msi` |
| macOS，Apple 芯片                                 | ARM64  | `neutrino-client-0.2.0-macos-arm64.pkg`   |

客户端是编译好的程序，不带解释器。Linux 包依赖 gir1.2-webkit2-4.1、libgirepository-1.0-1、gir1.2-ayatanaappindicator3-0.1、cifs-utils 和 polkitd。Windows 没有 ARM64 包，因为 cc-switch 没有 Windows ARM64 构建；macOS 没有 Intel 包。源码包 `neutrino-0.2.0-source.tar.gz` 和 `SHA256SUMS` 与它们放在一起。

## 选哪个包

| 机器                   | 包                                     |
| ---------------------- | -------------------------------------- |
| 家里那一台常开的 Linux | hub，只装一台                          |
| 每台要管的 Linux       | 被控端；hub 那台机器在初始化时已经装上 |
| 每个人的电脑           | 客户端，每台电脑一个                   |
