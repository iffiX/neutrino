---
title: 支持的平台
---

# 支持的平台

微子 0.5.0 发布 hub、被控端、桌面客户端和 Android 应用四样东西，下面每张表列出其中一样能装在哪些系统上，以及对应的发布文件。所有文件都在[发布页](https://github.com/iffiX/neutrino/releases)上，旁边有 `SHA256SUMS` 和源码包。所有组件都只有 64 位版本。

## Hub

| 系统                                                                            | 架构   | 文件                                      |
| ------------------------------------------------------------------------------- | ------ | ----------------------------------------- |
| Debian 12 及以上，Ubuntu 22.04 及以上，Raspberry Pi OS 64 位（bookworm 及以上） | x86-64 | `neutrino-hub_0.5.0_amd64.deb`            |
| 同上                                                                            | ARM64  | `neutrino-hub_0.5.0_arm64.deb`            |
| Fedora 41 及以上；RHEL 9 系（AlmaLinux、Rocky），先启用 EPEL                    | x86-64 | `neutrino-hub-0.5.0-1.x86_64.rpm`         |
| 同上                                                                            | ARM64  | `neutrino-hub-0.5.0-1.aarch64.rpm`        |
| Arch、EndeavourOS、Manjaro                                                      | x86-64 | `neutrino-hub-0.5.0-1-x86_64.pkg.tar.zst` |

hub 的安装包自带 Python，依赖 systemd、nftables、dnsmasq、iproute2、wpa_supplicant、dhcpcd、fail2ban、iw、arp-scan、vnstat、curl 和 smbclient。要发 Wi-Fi 的机器还推荐装 hostapd。Debian 系上 dhcpcd 的依赖写作 `dhcpcd-base | dhcpcd5`，因为 Ubuntu 22.04 上这个程序叫后一个名字。

## 被控端

| 系统                                                         | 架构   | 文件                                     |
| ------------------------------------------------------------ | ------ | ---------------------------------------- |
| Debian 12 及以上，Ubuntu 22.04 及以上，Raspberry Pi OS 64 位 | x86-64 | `neutrino-agent_0.5.0_amd64.deb`         |
| 同上                                                         | ARM64  | `neutrino-agent_0.5.0_arm64.deb`         |
| Fedora 41 及以上；RHEL 9 系                                  | x86-64 | `neutrino-agent-0.5.0-1.x86_64.rpm`      |
| 同上                                                         | ARM64  | `neutrino-agent-0.5.0-1.aarch64.rpm`     |
| Windows 10 1809 及以上，Windows 11                           | x86-64 | `neutrino-agent-0.5.0-windows-amd64.msi` |
| Apple 芯片上的 macOS 12.3 及以上                             | ARM64  | `neutrino-agent-0.5.0-macos-arm64.pkg`   |

被控端没有窗口。在 Linux 上它以 root 运行，安装包自带解释器和 RustDesk 主机端。在 Windows 上它是 LocalSystem 服务，在 macOS 上是以 root 运行的 LaunchDaemon；这两个安装包都带编译好的被控端和 RustDesk。终端依赖的伪控制台从 Windows 10 1809 起才有。Windows 版只有 x86-64，因为 RustDesk 没有发布 Windows ARM64 版本。

## 桌面客户端

| 系统                                                         | 架构   | 文件                                      |
| ------------------------------------------------------------ | ------ | ----------------------------------------- |
| Debian 12 及以上，Ubuntu 22.04 及以上，带桌面会话            | x86-64 | `neutrino-client_0.5.0_amd64.deb`         |
| 同上                                                         | ARM64  | `neutrino-client_0.5.0_arm64.deb`         |
| RHEL 9 系（AlmaLinux、Rocky）和 Fedora 41 及以上，带桌面会话 | x86-64 | `neutrino-client-0.5.0-1.x86_64.rpm`      |
| 同上                                                         | ARM64  | `neutrino-client-0.5.0-1.aarch64.rpm`     |
| Windows 10 1809 及以上，Windows 11                           | x86-64 | `neutrino-client-0.5.0-windows-amd64.msi` |
| Apple 芯片上的 macOS 12.3 及以上                             | ARM64  | `neutrino-client-0.5.0-macos-arm64.pkg`   |

Linux 客户端的窗口用 WebKitGTK 的 4.1 或 4.0 接口都能打开，挂载共享要用 `cifs-utils` 和 polkit。缺 appindicator 库时，托盘图标改用 GTK 状态图标画出。Windows 版只有 x86-64，因为 cc-switch 没有发布 Windows ARM64 版本；系统缺 WebView2 运行时的话，安装包会装上它。

## Android 应用

| 系统               | 架构      | 文件                                |
| ------------------ | --------- | ----------------------------------- |
| Android 8.0 及以上 | arm64-v8a | `neutrino-client-0.5.0-android.apk` |

Android 8.0 对应 API 级别 26，即应用声明的 `minSdk`；系统更旧的手机，安装程序直接拒装。

## 各系统能用的模块

机器的系统跑不了的模块，在**模块**（Modules）页的选择器里显示为灰色，写着**这台机器的系统不支持**（This machine's system cannot run it）。下表来自 hub 自带的模块清单。

| 模块                                                     | Linux                              | Windows             | macOS               |
| -------------------------------------------------------- | ---------------------------------- | ------------------- | ------------------- |
| File share                                               | 发行版软件源里的 Samba             | 系统自带的 SMB 服务 | 系统自带的 SMB 服务 |
| Gitea                                                    | x86-64 和 ARM64                    | 不支持              | 不支持              |
| Containers                                               | 发行版软件源里的 Podman            | 不支持              | 不支持              |
| ZFS storage                                              | 各发行版系列存放 OpenZFS 的软件源  | 不支持              | 不支持              |
| VS Code                                                  | x86-64 和 ARM64，glibc 2.28 及以上 | x86-64              | Apple 芯片          |
| AnyDesk、TeamViewer，作为**设备**（Devices）页的远程桌面 | 使用者自己装了才检测到             | 同左                | 同左                |

被控端读取模块状态时，对机器上的程序有以下最低版本要求：

| 程序               | 最低版本                            |
| ------------------ | ----------------------------------- |
| Podman             | 3.4；从 4.4 起容器写成 Quadlet 文件 |
| Samba              | 4.15                                |
| ZFS                | 2.1                                 |
| Windows PowerShell | 5.1，用于 Windows 上的文件共享      |
| macOS              | 12，用于 macOS 上的文件共享         |
