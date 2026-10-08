---
title: 支持的平台
---

# 支持的平台

微子 0.5.0 的中枢、被控端、桌面客户端和 Android 应用，各自装在下表列出的系统上，每一行对应发布页上的一个文件。完整版的文件在 [GitHub 发布页](https://github.com/iffiX/neutrino/releases)上，旁边有 `SHA256SUMS` 和源码包。所有组件都只有 64 位版本。

## 中枢

| 系统                                                                            | 架构   | 文件                                      |
| ------------------------------------------------------------------------------- | ------ | ----------------------------------------- |
| Debian 12 及以上，Ubuntu 22.04 及以上，Raspberry Pi OS 64 位（bookworm 及以上） | x86-64 | `neutrino-hub_0.5.0_amd64.deb`            |
| 同上                                                                            | ARM64  | `neutrino-hub_0.5.0_arm64.deb`            |
| Fedora 41 及以上；RHEL 9 系（AlmaLinux、Rocky），先启用 EPEL                    | x86-64 | `neutrino-hub-0.5.0-1.x86_64.rpm`         |
| 同上                                                                            | ARM64  | `neutrino-hub-0.5.0-1.aarch64.rpm`        |
| Arch、EndeavourOS、Manjaro                                                      | x86-64 | `neutrino-hub-0.5.0-1-x86_64.pkg.tar.zst` |
| Windows 10 1809 及以上，Windows 11，只有服务器形态                              | x86-64 | `neutrino-hub-0.5.0-windows-amd64.msi`    |
| Apple 芯片上的 macOS 12.3 及以上，只有服务器形态                                | ARM64  | `neutrino-hub-0.5.0-macos-arm64.pkg`      |
| Intel 芯片上的 macOS 12.3 及以上，只有服务器形态                                | x86-64 | `neutrino-hub-0.5.0-macos-amd64.pkg`      |

Linux 上的中枢包自带 Python 环境，不动系统装的任何东西，其余依赖都写在包里：systemd、nftables、dnsmasq、iproute2、wpa_supplicant、dhcpcd、fail2ban、iw、arp-scan、vnstat、curl、smbclient、OpenSSH 客户端和 pkexec。要发 Wi-Fi 的机器还推荐装 hostapd。Debian 系上 dhcpcd 写作 `dhcpcd-base | dhcpcd5`，因为 Ubuntu 22.04 上这个程序叫后一个名字；pkexec 写作 `pkexec | policykit-1`。RHEL 9 系的 fail2ban、arp-scan 和 vnstat 在 EPEL 里。

Windows 和 macOS 上的中枢只运行 **服务器**（Server）形态：只在机器所连的网络上提供服务，不当路由器。这两种系统的中枢包里有编译好的中枢，以及中枢驱动的每个程序，不依赖系统的包。包里还有本机要装的被控端。

## 被控端

| 系统                                                         | 架构   | 文件                                     |
| ------------------------------------------------------------ | ------ | ---------------------------------------- |
| Debian 12 及以上，Ubuntu 22.04 及以上，Raspberry Pi OS 64 位 | x86-64 | `neutrino-agent_0.5.0_amd64.deb`         |
| 同上                                                         | ARM64  | `neutrino-agent_0.5.0_arm64.deb`         |
| Fedora 41 及以上；RHEL 9 系                                  | x86-64 | `neutrino-agent-0.5.0-1.x86_64.rpm`      |
| 同上                                                         | ARM64  | `neutrino-agent-0.5.0-1.aarch64.rpm`     |
| Windows 10 1809 及以上，Windows 11                           | x86-64 | `neutrino-agent-0.5.0-windows-amd64.msi` |
| Apple 芯片上的 macOS 12.3 及以上                             | ARM64  | `neutrino-agent-0.5.0-macos-arm64.pkg`   |
| Intel 芯片上的 macOS 12.3 及以上                             | x86-64 | `neutrino-agent-0.5.0-macos-amd64.pkg`   |

被控端没有窗口，不监听任何端口。Linux 上它以 root 运行，包里带着自己的解释器和 RustDesk 主机端。Windows 上它是 LocalSystem 服务，macOS 上是以 root 运行的 LaunchDaemon。这两种系统的安装程序带着编译好的被控端，RustDesk 放在被控端自己的目录里，机器的 **Remote desktop** 开关打开时，被控端才登记它。

Windows 版只有 x86-64，因为 RustDesk 没有发布 Windows ARM64 版本。终端用的伪控制台从 Windows 10 1809 起才有。

## 桌面客户端

| 系统                                                         | 架构   | 文件                                      |
| ------------------------------------------------------------ | ------ | ----------------------------------------- |
| Debian 12 及以上，Ubuntu 22.04 及以上，带桌面会话            | x86-64 | `neutrino-client_0.5.0_amd64.deb`         |
| 同上                                                         | ARM64  | `neutrino-client_0.5.0_arm64.deb`         |
| RHEL 9 系（AlmaLinux、Rocky）和 Fedora 41 及以上，带桌面会话 | x86-64 | `neutrino-client-0.5.0-1.x86_64.rpm`      |
| 同上                                                         | ARM64  | `neutrino-client-0.5.0-1.aarch64.rpm`     |
| Windows 10 1809 及以上，Windows 11                           | x86-64 | `neutrino-client-0.5.0-windows-amd64.msi` |
| Apple 芯片上的 macOS 12.3 及以上                             | ARM64  | `neutrino-client-0.5.0-macos-arm64.pkg`   |
| Intel 芯片上的 macOS 12.3 及以上                             | x86-64 | `neutrino-client-0.5.0-macos-amd64.pkg`   |

Linux 客户端的窗口用 WebKitGTK，4.1 和 4.0 两种接口都行；挂载共享要用 `cifs-utils` 和 polkit。缺 appindicator 库时，托盘图标改用 GTK 状态图标画出。Windows 上的窗口用 WebView2 运行时，系统缺它时安装程序装上它。Windows 版只有 x86-64，因为 cc-switch 没有发布 Windows ARM64 版本。

## Android 应用

| 系统               | 架构      | 文件                                |
| ------------------ | --------- | ----------------------------------- |
| Android 8.0 及以上 | arm64-v8a | `neutrino-client-0.5.0-android.apk` |

Android 8.0 对应 API 级别 26，即应用声明的 `minSdk`；更旧的手机上，系统的安装程序直接拒装。

## 版本

每个发行版本都分完整版和国内版两份，文件名的写法相同，从哪个发布页下载决定是哪一版。

| 版本   | 发布页                                                                 | 发布的文件                                                                                                        |
| ------ | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 完整版 | GitHub，`https://github.com/iffiX/neutrino/releases`，保留每个发行版本 | 上面各表的全部文件                                                                                                |
| 国内版 | Gitee，`https://gitee.com/iffiX/neutrino/releases`，只留最新的发行版本 | 中枢、被控端和桌面客户端各自的 x86-64 与 ARM64 `.deb`、Windows `.msi`、Apple 芯片 Mac `.pkg`，以及 Android `.apk` |

国内版的中枢没有代理和 NetBird：没有 **代理**（Proxy）页，**外部访问**（Access）页上没有 NetBird 卡片，也没有 **旁路网关**（Side gateway）形态。国内版的桌面客户端和 Android 应用没有 NetBird。两版的被控端相同。完整版的包只升级到完整版的包，国内版的也一样。

## 各系统能用的模块

受管机器的系统跑不了的模块，在 **模块**（Modules）页的选择器里显示为灰色，写着 **这台机器的系统不支持**（This machine's system cannot run it）。模块的标签名在两种语言的面板里都是英文。

| 模块                                                      | Linux                              | Windows             | macOS               |
| --------------------------------------------------------- | ---------------------------------- | ------------------- | ------------------- |
| File share                                                | 发行版软件源里的 Samba             | 系统自带的 SMB 服务 | 系统自带的 SMB 服务 |
| Terminal                                                  | 支持                               | 只能设 shell 程序   | 支持                |
| Remote desktop                                            | 支持                               | 只有 x86-64         | 支持                |
| Gitea                                                     | x86-64 和 ARM64                    | x86-64              | Apple 芯片和 Intel  |
| Containers                                                | 发行版软件源里的 Podman            | 不支持              | 不支持              |
| ZFS storage                                               | 各发行版系列存放 OpenZFS 的软件源  | 不支持              | 不支持              |
| VS Code                                                   | x86-64 和 ARM64，glibc 2.28 及以上 | x86-64              | Apple 芯片和 Intel  |
| code-server                                               | x86-64 和 ARM64，glibc 2.28 及以上 | 不支持              | Apple 芯片和 Intel  |
| CloudCLI                                                  | x86-64 和 ARM64，glibc 2.28 及以上 | x86-64              | Apple 芯片和 Intel  |
| AnyDesk、TeamViewer，作为 **设备**（Devices）页的远程桌面 | 机器上自己装了才检测到             | 同左                | 同左                |

被控端驱动的程序有以下最低版本：

| 程序               | 最低版本                                   |
| ------------------ | ------------------------------------------ |
| Podman             | 3.4；从 4.4 起容器写成 Quadlet 文件        |
| Samba              | 4.15                                       |
| ZFS                | 2.1                                        |
| git                | 2.0，Gitea 用；macOS 和 Windows 上要自己装 |
| Windows PowerShell | 5.1，Windows 上的文件共享用                |
| macOS              | 12，macOS 上的文件共享用                   |
