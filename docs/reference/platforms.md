# 支持的平台

微子·中枢全部是 64 位，没有 32 位版。Linux、Windows 和 macOS 上都能安装中枢、被控端和客户端，手机上只有客户端。

## 中枢、被控端、客户端

找到你的系统那一行，最后三列显示要下载的安装包类型。

| 系统                                                         | 架构          | 中枢           | 被控端         | 客户端                               |
| ------------------------------------------------------------ | ------------- | -------------- | -------------- | ------------------------------------ |
| Debian 12 及以上、Ubuntu 22.04 及以上、Raspberry Pi OS 64 位 | x86-64、ARM64 | `.deb`         | `.deb`         | `.deb`                               |
| RHEL 9 系（AlmaLinux、Rocky）、Fedora                        | x86-64、ARM64 | `.rpm`         | `.rpm`         | `.rpm`                               |
| Arch、EndeavourOS、Manjaro                                   | x86-64        | `.pkg.tar.zst` | `.pkg.tar.zst` | `.pkg.tar.zst`                       |
| Windows 10 1809 及以上、Windows 11                           | x86-64        | `.msi`         | `.msi`         | `.msi`                               |
| macOS 13 及以上，Apple 芯片                                  | ARM64         | `.pkg`         | `.pkg`         | `.pkg`                               |
| macOS 13 及以上，Intel                                       | x86-64        | `.pkg`         | `.pkg`         | `.pkg`                               |
| Android 8.0 及以上                                           | arm64-v8a     | 没有           | 没有           | `.apk`                               |
| iOS 16 及以上                                                | arm64         | 没有           | 没有           | `.ipa`，没有签名，你要自行签名后安装 |

Linux 包要求的 glibc 最低是 2.34。RHEL 9 系要先启用 EPEL，安装脚本会自动启用，Fedora 不用启用。客户端在 Linux 上需要桌面会话才能运行。

Windows 版只有 x86-64，RustDesk 和 cc-switch 都没有 ARM64 版。

中枢设置完成时，同一个系统上也会安装一个被控端，Arch 上也一样。

上面这些文件和 `SHA256SUMS` 都在同一个发布标签下发布。

## 运行身份

中枢和被控端以管理员身份运行，客户端以你自己的账户运行。

| 程序         | Linux        | macOS              | Windows      |
| ------------ | ------------ | ------------------ | ------------ |
| 中枢、被控端 | root         | root，LaunchDaemon | SYSTEM       |
| 客户端       | 你自己的账户 | 你自己的账户       | 你自己的账户 |

被控端没有窗口。手机上的客户端就是 App 本身。

## 版本兼容

0.6 只兼容 0.6。0.5 的被控端和客户端连接 0.6 的中枢时，收不到任何回应，所以你要重新安装，再用新链接加入，见[从 0.5 升级](/hub/upgrade)。

## 网络模式

服务器模式三个系统都有，路由器和旁路网关只在 Linux 上有。

| 模式                 | Linux | Windows | macOS |
| -------------------- | ----- | ------- | ----- |
| 服务器               | 有    | 有      | 有    |
| 路由器（含单臂路由） | 有    | 没有    | 没有  |
| 旁路网关             | 有    | 没有    | 没有  |

各模式支持的版本见[网络形态：服务器、路由器、旁路网关](/hub/network)。

## 应用

系统不能运行的应用，在 **添加模块** 弹窗里显示为灰色。

| 应用         | Linux                        | Windows                      | macOS             | 其他要求                                           |
| ------------ | ---------------------------- | ---------------------------- | ----------------- | -------------------------------------------------- |
| 远程桌面     | 有                           | 有                           | 有                | 被控端自带                                         |
| 文件共享     | Debian、RHEL、Arch 三族      | 系统自带                     | 系统自带          | Linux 上系统的 Samba 4.15 及以上                   |
| 终端         | 有                           | 有                           | 有                | 被控端自带                                         |
| SSH 服务器   | amd64、arm64                 | amd64                        | Apple 芯片、Intel | 被控端自带                                         |
| VS Code      | amd64、arm64                 | amd64                        | Apple 芯片、Intel | 你要先接受微软的条款                               |
| code-server  | amd64、arm64                 | 没有                         | Apple 芯片、Intel |                                                    |
| Gitea        | amd64、arm64                 | amd64                        | Apple 芯片、Intel | 在 Windows、macOS 上，你要自行安装 git 2.0 及以上  |
| CloudCLI     | amd64、arm64                 | amd64                        | Apple 芯片、Intel | 自带 Claude Code，推荐打开 **AI 工具使用中枢网关** |
| Codeg        | amd64、arm64                 | amd64                        | Apple 芯片、Intel |                                                    |
| Hermes WebUI | 能运行 **容器** 的系统都支持 | amd64                        | Apple 芯片、Intel | 需要 **容器**，建议内存 1 GiB                      |
| Ayakaleaf    | 能运行 **容器** 的系统都支持 | amd64                        | Apple 芯片、Intel | 需要 **容器**，建议内存 3 GiB                      |
| 思源笔记     | amd64、arm64                 | amd64                        | Apple 芯片、Intel |                                                    |
| Claude Code  | amd64、arm64                 | amd64、arm64                 | Apple 芯片、Intel | 普通程序，在终端里运行                             |
| Codex        | amd64、arm64                 | amd64、arm64                 | Apple 芯片、Intel | 普通程序，在终端里运行                             |
| 容器         | Debian、RHEL、Arch 三族      | amd64，内部版本 19041 及以上 | 13 及以上         | Linux 上系统的 Podman 3.4 及以上                   |

不属于这三族的 Linux，比如 Alpine，没有容器，所以也不能运行 Hermes WebUI 和 Ayakaleaf。

Windows 上的容器只在内部版本 26100 上实测过，19041 是安装包接受的最低版本。

**AI 工具使用中枢网关** 使用 cc-switch，支持的系统和架构和 SSH 服务器相同。
