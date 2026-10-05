---
title: 设备
---

# 设备

中枢发现的每台机器都列在**设备**（Devices）页上。Linux、Windows 和 Mac 机器从这一页接入，接入后在这里看状态、开关机，也看谁在共享桌面。

![设备页上已管理的 Linux、Windows 和 Mac 机器](/guide/zh/devices_managed.webp)

## 设备状态

页面分**已管理的设备**（Managed devices）和**未管理的设备**（Unmanaged devices）两栏。每个设备卡片带一种状态。上方的筛选**全部**（All）、**Agent**、**SSH**、**仅扫描到**（Scanned only）、**在线**（Online）和**离线**（Offline）用来缩小列表。

| 状态   | 含义                                       | 下一步                          |
| ------ | ------------------------------------------ | ------------------------------- |
| 被控端 | 已管理：被控端上报这台机器的状态，接受模块 | 打开抽屉                        |
| SSH    | 未管理，但存了登录凭据，一步就能装被控端   | **安装被控端**（Install agent） |
| 已扫描 | 未管理，也没有凭据，靠加入链接接入         | **获取链接**（Get link）        |
| 离线   | 没有响应；机器回来后凭据照样能用           | 等它上线，或者网络唤醒          |

**扫描局域网**（Scan LAN）列出中枢服务的网络里连着的机器。页面标题旁的标记写已管理的台数，例如 **5 台中有 2 台已管理**。中枢这台机器从第一次登录起就在已管理一栏里：`nhub setup` 结束前在它上面装好了被控端。

## 接入之前

每次接入都要满足下面几条：

- 机器的系统在[支持的平台](../reference/platforms.md)里。
- 你在这台机器上有 root 权限；Windows 上是管理员账户。
- 机器能访问中枢的被控端端口，默认 8443。

加入链接形如 `neutrino://enroll/…`，三十分钟内有效。页面顶部的**用链接添加**（Add by link）生成一条；未管理机器抽屉里的**获取链接**为那一行生成一条。新链接生成后，上一条作废。

![加入链接和复制按钮](/guide/zh/devices_enroll_link.webp)

## 用链接接入 Linux 机器

先从[发布页](https://github.com/iffiX/neutrino/releases)下载这台机器对应的被控端安装包，然后：

1. 在那台机器上，按发行版家族装包。

   ::: code-group

   ```bash [Debian、Ubuntu、Raspberry Pi OS]
   sudo apt install ./neutrino-agent_0.5.0_amd64.deb
   ```

   ```bash [Fedora、RHEL 系]
   sudo dnf install ./neutrino-agent-0.5.0-1.x86_64.rpm
   ```

   :::

1. 在面板的设备页点**用链接添加**，再点**复制**（Copy）。
1. 在那台机器上运行加入命令，`<enroll-link>` 换成复制的链接：

   ```bash
   sudo nagent join <enroll-link>
   ```

几秒之内，这台机器出现在已管理一栏。ARM64 机器的文件名以 `_arm64.deb` 或 `.aarch64.rpm` 结尾。`apt` 和 `dnf` 会连同依赖一起装；`dpkg -i` 和 `rpm -i` 一个依赖都不装。

`nagent join` 不带链接时，提示你粘贴一条。机器已经绑定过中枢时，加 `--yes` 直接替换。链接用过、无效或超过三十分钟，中枢返回 `ticket_spent`。

## 经 SSH 安装被控端

中枢能登录 Linux 机器，自己把被控端装上去。先在[凭据](./credentials.md)页存一把 SSH 密钥或一条登录信息，也可以在对话框里当场添加。

1. 在未管理一栏里打开那台机器的抽屉。
1. 点**安装被控端**。
1. 填**主机**（Host）、**端口**（Port）和**用户名**（Username）。
1. 在**凭据**（Credential）里选 **SSH 密钥**（SSH key）或**密码**（Password），再选存好的密钥或登录信息。
1. 可选：在 **Sudo 密码**（Sudo password）里选 `sudo` 要用的那条登录信息。账户免密 sudo 时留空。
1. 点**安装被控端**。

![SSH 安装对话框：主机、端口、用户名和凭据](/guide/zh/devices_install_ssh.webp)

**安装输出**（Install output）实时显示安装过程。安装程序自己生成一条加入链接并用它接入。中枢先读对方的系统，不是 Linux 就返回 `unsupported_remote_install`。登录信息不对时，任务照常开始，失败原因写在安装输出里。

## 接入 Windows 机器

安装包是 `neutrino-agent-0.5.0-windows-amd64.msi`，适用于 x86-64 上的 Windows 10 1809 及更新版本。它注册 `neutrino_agent` 服务，以 LocalSystem 身份开机启动，并把 `nagent` 加进系统 `PATH`。RustDesk 也一起装上，带它自己的服务和防火墙规则。

1. 从发布页下载 `.msi` 并运行。
1. 以管理员身份新开一个终端，让它读到新的 `PATH`。
1. 在面板里点**用链接添加**，再点**复制**。
1. 在终端里运行 `nagent join`，后面跟上复制的链接。

静默安装时，以管理员身份运行 `msiexec /i neutrino-agent-0.5.0-windows-amd64.msi /qn`。被控端把绑定和日志 `agent.log` 放在 `C:\ProgramData\Neutrino\agent`，只有 SYSTEM 和管理员能读。在**应用**（Apps）里卸载 **Neutrino Agent** 时，RustDesk 一并卸掉。

## 接入 Mac

安装包是 `neutrino-agent-0.5.0-macos-arm64.pkg`，适用于 Apple 芯片上的 macOS 12.3 及更新版本。被控端装在 `/Library/Application Support/Neutrino/agent`，`nagent` 链接到 `/usr/local/bin`，`RustDesk.app` 放进 `/Applications`。LaunchDaemon `com.neutrino.agent` 以 root 运行被控端，输出写到 `/Library/Logs/neutrino_agent.log`。

1. 装包：

   ```bash
   sudo installer -pkg neutrino-agent-0.5.0-macos-arm64.pkg -target /
   ```

1. 在面板里点**用链接添加**，再点**复制**。
1. 运行 `sudo nagent join`，后面跟上复制的链接。
1. 在**系统设置** > **隐私与安全性**里，为 RustDesk 打开**屏幕录制**和**辅助功能**两项权限。

RustDesk 拿到这两项权限之前，抽屉显示 `rdp_permissions_needed`，观看者看到的是空画面。

Windows 和 Mac 上能跑文件共享、VS Code 和远程桌面；Gitea、容器和 ZFS 只有 Linux 版。[模块](../agent/modules.md)页把机器跑不了的模块显示为灰色。`nagent` 的全部子命令在 [nagent 命令](../commands/nagent.md)里。

## 抽屉

点一台机器打开它的抽屉。已管理的机器最上面是**实时监控**（Live monitor）：CPU、内存、磁盘、负载、运行时长，以及占用最高的进程。每个进程旁有**结束进程**（Kill process）；在 Windows 机器上，这个操作返回错误。

监控下面依次是**身份**（Identity），可改**显示名称**（Display name）和**图标**（Icon）；然后是**操作**（Actions）、**远程桌面**（Remote desktop）、**操作输出**（Action output）和 **Agent 命令结果**（Agent command results）。顶部的**终端**（Terminal）和**文件**（Files）打开对应页面，机器已经选好。

| 操作                                  | 结果                                                                                                                                                                                    |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **重新安装被控端**（Reinstall agent） | 在线的被控端自己重装中枢的安装包；不在线的弹出 SSH 安装对话框                                                                                                                           |
| **重启**（Reboot）                    | 机器立即重启                                                                                                                                                                            |
| **关机**（Shut down）                 | 机器立即关机                                                                                                                                                                            |
| **网络唤醒**（Wake-on-LAN）           | 路由器或旁路网关模式的中枢，向它服务的每个网络发魔术包，UDP 端口 9；服务器模式的中枢，发往它开放的每个网络；不经 NetBird 或 EasyTier 发送。机器的固件和网卡都开启了网络唤醒，才会被唤醒 |
| **忘记设备**（Forget device）         | 这一行和它的 SSH 设置从中枢删除；凭据页上的密钥和登录信息保留                                                                                                                           |

重启和关机先弹确认框，机器上没保存的内容会丢失。机器没有响应时，操作返回 `agent_offline`。忘记一台设备不动它上面的被控端，用一条新链接就能再接回来。

## 共享桌面

远程桌面用 RustDesk，随被控端安装包一起装。共享在机器本地发起，坐席密码由中枢设定并保管。

1. 在那台机器上运行共享命令。Windows 上去掉 `sudo`，在管理员终端里运行。

   ```bash
   sudo nagent rdp start
   ```

1. 在抽屉的**远程桌面**一节里，看 **ID**、**直连端口 21118**（Direct port）、**由谁共享**（Shared by）和观看人数。
1. 在客户端的**远程桌面**（Remote desktops）里点**连接**（Connect）。

![抽屉里的远程桌面一节：ID、直连端口和共享账户](/guide/zh/devices_drawer_rdp.webp)

不带 `--user` 时，共享的是运行 `sudo` 的那个账户的桌面；没有这个账户时，共享屏幕前唯一登录的账户。`sudo nagent rdp stop` 停止共享。**重置坐席密码**（Reset seat password）让机器立即换一个密码，当前连着的观看者都要重新连。

屏幕前没人登录时，抽屉显示 `rdp_nobody_seated`。Wayland 会话还没允许屏幕共享时，抽屉显示 `rdp_screen_not_allowed`，在那台机器的屏幕上允许一次即可。机器上装了 AnyDesk 或 TeamViewer 时，这一节还显示它的 ID 和**设置无人值守密码**（Set unattended password）。

## 版本不一致的机器

抽屉和卡片上写着**这个被控端与中枢的版本不一致。**（This agent is a different version from the hub.）。中枢接纳的被控端连上时，会自己更新到中枢的版本。自我更新失败时，点抽屉里的**重新安装被控端**。

0.5.0 的中枢只接纳协议 3。0.3 和 0.4 的被控端连上来，中枢返回 `protocol_too_old`，设备一直显示离线。绑定保留，换上新安装包之后机器自己连回来：

| 机器                  | 换被控端的办法                                  |
| --------------------- | ----------------------------------------------- |
| 能经 SSH 登录的 Linux | 抽屉里点**重新安装被控端**，弹出 SSH 安装对话框 |
| 其他 Linux            | 用 `apt` 或 `dnf` 装新包，命令同第一节          |
| Windows               | 在旧版本上直接运行新的 `.msi`                   |
| Mac                   | 在旧版本上直接安装新的 `.pkg`                   |

拒绝持续期间，在那台机器上运行 `sudo nagent status` 能看到原因。中枢、被控端和客户端按什么顺序升级，见[设置](./settings.md)页。
