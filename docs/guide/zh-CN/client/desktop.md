---
title: 桌面客户端
---

# 桌面客户端

桌面客户端装在你自己的电脑上，Linux、Windows、macOS 都能用。每个 hub 发一条链接，粘进窗口就加入了那个 hub。之后这个 hub 的网页、端口、AI 网关、共享、终端和远程桌面，都在同一个窗口里打开。终端里做同样的事用 `nclient`，见 [nclient 命令](../commands/nclient.md)。

## 安装客户端

开始之前，确认这台电脑满足下列条件：

- 系统是下面之一，完整列表见[支持的平台](../reference/platforms.md)：
  - Debian 12、Ubuntu 22.04 或更新版本，带桌面会话
  - RHEL 9、AlmaLinux 9、Fedora 41 或更新版本，带桌面会话
  - x86-64 上的 Windows 10 1809 或更新版本，或 Windows 11
  - Apple 芯片上的 macOS 12.3 或更新版本
- 用你自己的普通账户运行。以 root 运行时，客户端返回 `root_refused`。
- 能访问要加入的每个 hub 的 8443 端口。

从发布页下载对应系统的包，然后安装。64 位 ARM 的 Linux 机器上，`.deb` 文件名里写 `arm64`，`.rpm` 文件名里写 `aarch64`。

::: code-group

```bash [Debian、Ubuntu]
sudo apt install ./neutrino-client_0.5.0_amd64.deb
```

```bash [RHEL、AlmaLinux、Fedora]
sudo dnf install ./neutrino-client-0.5.0-1.x86_64.rpm
```

```powershell [Windows]
msiexec /i neutrino-client-0.5.0-windows-amd64.msi
```

```bash [macOS]
sudo installer -pkg neutrino-client-0.5.0-macos-arm64.pkg -target /
```

:::

`apt` 和 `dnf` 把依赖和包一起装上：WebKitGTK、托盘库、`cifs-utils`、polkit，以及自带的 RustDesk 查看器要加载的库。

::: warning
`dpkg -i` 和 `rpm -i` 不装依赖。已经用了的话，Debian 系运行 `sudo apt -f install`，RHEL 系用 `sudo dnf install` 装上它列出的包。
:::

Windows 上双击 `.msi` 也是同一个安装程序。勾选 **Add the Neutrino Client to PATH**，任何终端里都能用 `nclient` 命令。机器上缺 WebView2 运行时的话，安装程序会运行微软的引导程序装上它。卸载对话框里有 **Keep my configuration** 一项；勾选它保留配置，下次安装后直接回到原来的 hub。

![Windows 安装程序](/guide/os/win_msi_installer.webp)

macOS 上，安装程序把 **Neutrino Client** 放进 `/Applications`，把 `nclient` 链接到 `/usr/local/bin`。应用只有临时签名，第一次打开时 Gatekeeper 会确认一次。

每个包都登记两个系统服务，供虚拟网使用：NetBird 守护进程，和客户端自带的 EasyTier 守护进程。Linux 上这个包与 `netbird` 包冲突。macOS 上已经装了 NetBird 的，客户端直接用它。

## 加入 hub

开始之前，先在 hub 的面板里建一条客户端链接：打开 **客户端**（Clients），选 **新建客户端链接**（New client link），填这台电脑的名字，再选 **创建链接**（Create link）。链接五分钟内有效，只能加入一台电脑。这台电脑能用哪些服务，在[客户端](../hub/clients.md)页上设置。

加入的步骤：

1. 打开客户端：Linux 上在应用菜单里，Windows 上在开始菜单里，macOS 上点应用图标。**中枢**（Hubs）页写着 **尚未加入任何 hub**（No hub joined yet），下面是 **加入 hub**（Join a hub）一行。
1. 把链接粘进那一行的输入框，选 **加入**（Join）。

这个 hub 多出一行，写着 **已连接**（Connected）、它的地址和它运行的软件包。

![加入 hub 之后的客户端窗口](/guide/zh/client_connected.webp)

粘的是 hub **设备**（Devices）页发的链接时，客户端返回 `link_not_for_client`；链接过期或已用过时，返回 `enroll_refused`。

要再加入一个 hub，在那个 hub 的面板里建一条链接，粘进同一行 **加入 hub**。每个 hub 各记各的电脑名字，各发布各的服务。每个服务页都按加入的先后列出各个 hub。

## 中枢

窗口标题是 **微子·客户端**（Neutrino client）。左边侧栏依次是 **中枢**、**网页**（Web）、**端口**（Ports）、**AI**、**文件**（Files）、**终端**（Terminals）、**远程桌面**（Remote desktops），隔一条线是 **设置**（Settings）。侧栏底部写着本机名字、平台和客户端版本。右上角的 **↻** 让连着的 hub 立刻收到一份报告，断开的 hub 立刻重连。

### 行的状态

**中枢** 页上一行是一个 hub，写着名字、状态、地址和它运行的软件包。名字前的圆点用颜色表示状态：

| 圆点       | 含义                                                            |
| ---------- | --------------------------------------------------------------- |
| 绿色       | 通道开着                                                        |
| 黄色、转圈 | 正在重连一个连上过的 hub                                        |
| 黄色       | 连不上，但没有东西坏，例如 `hub_unreachable`、`client_disabled` |
| 红色       | 要有人改东西才会好，例如 `hub_untrusted`、`binding_unknown`     |
| 灰色       | 还没连上过这个 hub                                              |

每行都有 **离开**（Leave），选它这一行立刻消失。这个 hub 在本机发布的东西随之撤销：挂载、端口转发、查看器，以及别的 hub 不用的虚拟网。写着 **已被另一个客户端取代**（Replaced by another client）的行上，还有 **重新连接**（Reconnect）。

hub 拒绝时，这一行留着并写出错误码，客户端隔一段时间再试，最长隔一分钟。只有一个码会让这一行消失：

| 错误码             | 含义                                         | 怎么办                   |
| ------------------ | -------------------------------------------- | ------------------------ |
| `protocol_too_old` | 客户端的协议号低于 hub 接受的下限            | 装新版客户端             |
| `protocol_too_new` | 客户端的协议号高于 hub 的                    | 先升级 hub               |
| `hub_untrusted`    | 那个地址上的证书不是链接钉住的那张           | hub 重置过，用新链接加入 |
| `binding_unknown`  | hub 的客户端页里已经没有这个客户端，这行消失 | 用新链接重新加入         |

### 虚拟网

hub 发布了虚拟网，并且它的客户端页允许这个客户端使用时，这一行上有 **虚拟网**（Virtual network）标签。标签上写着状态，分到地址后再写本机在这个网络里的地址。

选这个标签就加入，再选一次就离开。客户端为每个 hub 记住你的选择，客户端重启后本机自动回到网络。守护进程是系统服务，客户端退出后本机仍在网络里。

| 状态                                             | 含义                                                             |
| ------------------------------------------------ | ---------------------------------------------------------------- |
| **未加入**（off）                                | 本机不在这个网络里                                               |
| **加入中…**（joining…）、**离开中…**（leaving…） | 正在进行，标签变灰                                               |
| **等待控制台挂载**（Waiting for the console）    | hub 的 EasyTier 控制台登记了本机，还没挂到网络上；去控制台里挂载 |
| **已加入**（on）                                 | 本机在这个网络里                                                 |
| **失败**（failed）                               | 上一步失败，错误码写在 hub 名字下面                              |

hub 发布了不止一个网络时，标签旁边多一个选择框，显示正在用的 NetBird 或 EasyTier。选另一个，本机先离开当前网络，再加入选中的那个。

![hub 那一行上的虚拟网选择框](/guide/zh/client_network_picker.webp)

hub 的通道断开满 30 秒时，客户端离开当前网络，加入这个 hub 的下一个网络。通道一直不通，就每过 30 秒再换一次，直到通道恢复。

| 错误码                    | 含义                                                             |
| ------------------------- | ---------------------------------------------------------------- |
| `overlay_other_network`   | 本机在另一个 NetBird 网络里，或接着别的 hub 的控制台，先离开那个 |
| `overlay_daemon_down`     | NetBird 或 EasyTier 守护进程没有运行，重装客户端                 |
| `bundle_missing`          | 这份安装里没有 NetBird 或 EasyTier，重装客户端                   |
| `overlay_join_failed`     | NetBird 或 EasyTier 没让本机加入，码后面是它自己的原话           |
| `overlay_console_invalid` | hub 给的 EasyTier 控制台地址，EasyTier 用不了                    |

## 网页

**网页** 页列出各个 hub 发布的网址：Gitea、VS Code，以及在 hub **服务**（Services）页手动声明的网址。每个地址下面一行写着 hub、机器和模块，例如 **由 Neutrino:Argon:Gitea 提供**。选 **打开**（Open），地址在默认浏览器里打开。

VS Code 条目只能经 localhost 打开，按钮写的是 **本机打开**（Open locally）。选它，客户端把条目地址转发到本机的 `127.0.0.1`，再向 hub 取一个令牌，然后带着令牌在浏览器里打开这个转发。客户端退出时转发关闭。hub 没给令牌时，这一行写出 `web_token_missing`。

hub 访问不到的条目变灰，写着 **当前无法访问**（not reachable now）。页面里一个条目都没有时，写着 **没有提供网页服务**。

## 端口

**端口** 页把 hub 发布的端口转到本机的回环地址上。条目来自受管机器上容器的主机端口，以及 hub **服务** 页里手动声明的 TCP 端口。

- 在条目上选 **连接**（Connect）。

这一行写出 `127.0.0.1` 和本机端口，按钮变成 **断开**（Disconnect）。条目自己的端口号空闲时，本机就用这个号；已有程序占用时，换任意一个空闲端口。转发开着期间，本机所有程序和账户都能连上它。选 **断开**、离开 hub 或退出客户端，转发才关闭。

## AI

**AI** 页让本机的 Claude Code、Codex 和 Gemini CLI 指向某个 hub 的 AI 网关。每个带网关的 hub 有一个条目。条目上有 **配置**（Config）和 **AI 工具使用此网关**（The AI tools use this gateway）开关。同一时间最多开一个。

在要用的网关上打开开关。条目先写 **正在切换工具…**，再写 **工具已指向 hub**，原来开着的开关随之关上。客户端用自带的 cc-switch 改写三个工具各自的配置，其中一个写不进去，三个都保持原样。再选一次开关，每个工具恢复第一次切换前的配置。

只有连着的 hub 能打开开关，否则客户端返回 `no_exit_hub`。hub 还没给这个客户端发密钥时，返回 `no_endpoint`，到 hub 的 **AI** 页发一把。

选模型的步骤：

1. 在条目上选 **配置**，打开 **AI 工具配置**（AI tool configuration）。
1. 在 **Claude Code** 下，选 **默认模型**（Default model）、**Opus 档位**（Opus slot）、**Sonnet 档位**（Sonnet slot）和 **Haiku 档位**（Haiku slot）。
1. 在 **Codex** 下，选 **模型**（Model）和 **推理强度**（Reasoning effort）：`minimal`、`low`、`medium` 或 `high`。
1. 在 **Gemini** 下，选 **模型**。
1. 选 **保存**（Save）。

每一项都能选 **网关默认**（gateway default）。列出的模型是那个 hub 自己的。正在用的网关上，保存后立刻改写工具；别的网关上，选择等到打开它的开关时才生效。

## 文件

**文件** 页把 hub 发布的 SMB 共享挂到本机：Linux 和 macOS 上挂到家目录下，Windows 上挂到一个盘符。条目来自受管机器上 Samba 模块的共享，以及 hub **服务** 页里手动声明的共享。

挂载的步骤：

1. 在条目上选 **配置**（Config）。
1. 填 **共享用户名**（Share username）和 **共享密码**（Share password），也就是这个共享接受的账号。
1. Linux 和 macOS 上，保留或修改 **挂载路径**（Mount path），它是家目录下的文件夹，例如 `~/nas/media`。**浏览…**（Browse…）可以选或新建文件夹。Windows 上选 **盘符**（Drive）。
1. 选 **挂载**（Mount）。按钮依次显示 **等待挂载…**、**正在挂载…**，最后变成 **卸载**（Unmount）。

![共享已挂载的文件页](/guide/zh/client_files_mounted.webp)

![文件资源管理器里映射的盘符](/guide/os/win_explorer_mapped.webp)

登录信息存在一个只有你的账户能读的凭据文件里，下次 **挂载** 不用再填密码。**卸载** 摘掉共享，登录信息保留。

| 错误码                        | 含义                                                    |
| ----------------------------- | ------------------------------------------------------- |
| `mountpoint_invalid`          | 路径不在家目录下                                        |
| `mountpoint_not_empty`        | 文件夹里有东西                                          |
| `mountpoint_not_drive_letter` | Windows 上选的不是空闲盘符                              |
| `mountpoint_in_use`           | 这个路径上已经有另一条共享，无论它来自哪个 hub          |
| `credentials_missing`         | 保存的登录信息丢了，在 **配置** 里重新填                |
| `share_login_rejected`        | 用户名或密码不对；**挂载** 会打开 **配置** 并填好用户名 |
| `share_access_denied`         | 登录对了，但这个账号不能用这个共享                      |
| `share_not_found`             | 主机上没有这个共享名                                    |
| `share_unreachable`           | 主机没有应答；它恢复后客户端自己再挂载                  |
| `share_session_conflict`      | Windows 已经用另一个账号连着这台服务器，先断开那个连接  |

Linux 上挂载 CIFS 需要 root，客户端用 `pkexec` 运行自带的挂载助手，polkit 弹一次授权。关掉授权窗口，返回 `mount_not_authorized`；机器上缺 `mount.cifs`，返回 `mount_tooling_missing`。macOS 上客户端以你的身份用 `mount_smbfs` 挂载，Windows 上挂成映射盘。

## 终端

**终端** 页在受管机器上开一个 shell，显示在窗口的标签页里。hub 的客户端页要允许这个客户端打开终端。

1. 在 **终端** 页上方一排里选中机器。绿色圆点表示机器在线。
1. 选 **新终端**（New terminal）。

shell 在新标签页里打开，敲的每个键都发到那台机器。窗口用客户端自带的 MesloLGS NF 字体显示 shell，powerlevel10k 提示符的图标能正常显示。

![客户端里一个持久终端标签页](/guide/zh/client_terminal.webp)

粘贴时，在 shell 上点右键，或按 Ctrl+Shift+V；macOS 上按 Cmd+V。客户端读不到剪贴板时，shell 下面一行写出 `clipboard_unreadable`。

shell 下面一行的末尾是 **持久**（Persistent）开关。打开后，没有窗口连着时机器仍保留这个会话，例如客户端退出之后。保留的会话显示成一个灰色圆点的标签页，选它就连回去，先显示 shell 最近的输出。持久标签页上的 **×** 按一次变成 **结束会话？**（End session?），再按一次，机器上的 shell 才结束。面板里同样的会话见[终端](../agent/terminals.md)。

| 错误码              | 含义                                       |
| ------------------- | ------------------------------------------ |
| `permission_denied` | hub 的客户端页不允许这个客户端打开终端     |
| `agent_offline`     | 那台机器现在没有连到 hub                   |
| `unknown_terminal`  | hub 没有提供那台机器的终端                 |
| `session_not_owned` | 会话是别的查看者打开的，开关不归这个客户端 |
| `session_unknown`   | 那台机器已经不保留这个会话                 |

## 远程桌面

**远程桌面** 页用客户端自带的 RustDesk 查看器，打开另一台机器的屏幕。受管机器运行 `sudo nagent rdp start` 共享桌面时，条目出现；停止共享或机器离线时，条目消失。

- 在条目上选 **连接**（Connect）。

按钮显示 **正在连接…**，查看器打开那台机器的桌面，这一行写 **查看器已打开**（viewer open）。座位密码由 hub 设定，随这一次点击交给查看器。查看器直连那台机器的 21118 端口。

| 看到的现象                          | 原因                               |
| ----------------------------------- | ---------------------------------- |
| 页面写着 **当前没有共享的远程桌面** | 没有机器在共享，或共享的机器离线了 |
| `rdp_not_shared`                    | 那台机器停止了共享                 |
| `rdp_no_address`                    | 那台机器没有发布本机能连的地址     |
| `rdp_no_desktop`                    | 本机这个会话没有屏幕给查看器用     |
| `rdp_launch_failed`                 | 查看器没能启动，码后面是原因       |

## 设置

1. 选侧栏分隔线下面的 **设置**。
1. 在 **客户端设置**（Client settings）面板里，选 **语言**（Language）和 **主题**（Theme）：**跟随系统**（System）、**深色**（Dark）或 **浅色**（Light）。
1. 选 **保存**。

语言和主题只管这个窗口，面板有自己的设置。

## 托盘

关闭窗口只是把它藏起来，客户端继续运行，每个 hub 都保持连接。托盘图标在 Windows 任务栏的角落，Linux 顶栏的指示器区，macOS 的菜单栏。图标菜单里有 **打开**（Open）和 **退出**（Quit）：前者显示窗口，后者停止客户端。

![Windows 上的托盘菜单](/guide/os/win_tray_flyout.webp)
