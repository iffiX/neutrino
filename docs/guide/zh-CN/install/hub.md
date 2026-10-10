---
title: 安装中枢
---

# 安装中枢

这一页列出中枢的两种装法，一条命令和包文件，各分完整版和国内版，以及设置向导每一屏要填什么。只想照一条路走的话，用[第零步](../quick-start.md)。

## 开始之前

- 系统是下面之一：
  - Linux，任意网络模式：Debian 12、Ubuntu 22.04、64 位树莓派 OS、Fedora 41、RHEL 9 系，或 x86-64 上的 Arch。
  - macOS 12.3 或更新版本，Apple 芯片或 Intel，只有服务器模式。
  - x86-64 上的 Windows 10 1809 或更新版本，只有服务器模式。
- 你有这台机器的 root 权限，Windows 上是管理员权限。
- 这台机器能上网。

每个安装包对应哪个系统，见[支持的平台](../reference/platforms.md)。

## 选版本

| 版本   | 发布在哪                                            | 有什么                                           |
| ------ | --------------------------------------------------- | ------------------------------------------------ |
| 完整版 | `github.com/iffiX/neutrino/releases`，每一版都保留  | 全部功能                                         |
| 国内版 | `gitee.com/iffiX/neutrino/releases`，只保留最新一版 | 没有代理、NetBird 和旁路网关模式；下载走国内镜像 |

国内版没有 `.rpm`、Arch 和 Intel Mac 的包，这些机器只能装完整版。

## 一条命令安装

安装脚本按系统和处理器选出安装包，用 `SHA256SUMS` 核对后安装，只要一次管理员权限。中枢已经设置过时，脚本最后打印面板的地址。没设置过时，脚本接着运行 `nhub setup`：终端打印向导地址，最后一行是 `Press Enter to begin:`，命令保持运行。在浏览器里做完向导，终端打印 `The hub was set up in the browser; its panel is at` 和面板地址，命令随即结束。

### Linux 和 macOS

完整版：

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

国内版：

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh
```

下载开始之前，在 `sudo` 的提示下输入一次密码。Debian 和 Ubuntu 上，apt 安装时打印一行 `N: Download is performed unsandboxed as root…`，这是 apt 的提示，安装照常完成。

### Windows

打开 PowerShell。完整版：

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

国内版：

```powershell
irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1 | iex
```

Windows 弹出一次授权框，脚本在新开的管理员窗口里接着运行。

## 用包文件安装

从发布页下载这台机器对应的文件，用系统自己的安装工具装。

### Linux

::: code-group

```bash [Debian、Ubuntu、树莓派 OS]
sudo apt install ./neutrino-hub_0.5.0_amd64.deb
```

```bash [Fedora]
sudo dnf install ./neutrino-hub-0.5.0-1.x86_64.rpm
```

```bash [RHEL、AlmaLinux、Rocky]
sudo dnf install -y epel-release
sudo dnf install ./neutrino-hub-0.5.0-1.x86_64.rpm
```

```bash [Arch、EndeavourOS、Manjaro]
sudo pacman -U neutrino-hub-0.5.0-1-x86_64.pkg.tar.zst
```

:::

ARM64 机器用文件名带 `arm64` 或 `aarch64` 的包，Arch 的包只有 x86-64。RHEL 系先装 `epel-release`。

::: warning
用 `apt`、`dnf` 或 `pacman` 安装，它们一起装上依赖。`dpkg -i` 和 `rpm -i` 不装依赖；已经用了的话，Debian 系运行 `sudo apt -f install` 补齐。
:::

### macOS

Apple 芯片的 Mac 运行下面的命令，Intel 的 Mac 用 `neutrino-hub-0.5.0-macos-amd64.pkg`：

```bash
sudo installer -pkg neutrino-hub-0.5.0-macos-arm64.pkg -target /
```

### Windows

双击 `neutrino-hub-0.5.0-windows-amd64.msi`。静默安装时，在管理员 PowerShell 里运行：

```powershell
msiexec /i neutrino-hub-0.5.0-windows-amd64.msi /qn
```

安装程序把 `nhub` 加进系统的 `PATH`。

## 打开设置向导

向导地址末尾要带一次性令牌。没带令牌打开时，页面读 **这台机器正等待配置**。

Linux 上：

1. 运行 `sudo nhub setup`。终端为这台机器的每个地址打印一行向导地址。
1. 在任意一台能访问这台机器的电脑上，用浏览器打开其中一个地址。
1. 选择 **开始配置这台机器**。

macOS 和 Windows 上，打开“应用程序”文件夹或开始菜单里的 **Neutrino Hub**，它在默认浏览器里打开向导；在终端里运行 `nhub open` 也一样。再选择 **开始配置这台机器**。

`nhub setup` 停在欢迎屏时按回车，就改在终端里用英文回答同样的问题。

## 回答向导

**下一步** 往后走，**返回** 往回走。最后一屏确认之前，向导不写入任何东西。

### 语言

在 **语言** 里选 **English** 或 **简体中文**，面板用这种语言显示。

### 密码与 HTTPS

![面板密码、保险库口令和 HTTPS 开关](/guide/zh/setup_secrets.webp)

1. 在 **面板密码** 和 **再输一次** 里填同一个密码，至少 8 个字符。
1. 在 **保险库口令** 和它的 **再输一次** 里填同一个口令，至少 16 个字符，混用小写、大写、数字和符号。
1. 可选：打开 **面板使用 HTTPS**。

恢复备份时还要输入保险库口令。HTTPS 以后能在[设置](../hub/settings.md)页开关。

### 形态

![形态屏上选中了服务器](/guide/zh/setup_shape.webp)

Linux 上，**这台机器做什么？** 只列出网口数量够用的形态：

| 形态         | 做什么                                         |
| ------------ | ---------------------------------------------- |
| **服务器**   | 在它所连的网络上提供服务，不做路由             |
| **旁路网关** | 为把它设为网关的主机转发流量；国内版没有       |
| **路由器**   | 在上行网口和它服务的网络之间路由               |
| **单臂路由** | 单根网线上路由：不带标签出网，带 VLAN 标签入内 |

服务器和旁路网关保留机器原有的地址，路由器和单臂路由接管网口。macOS 和 Windows 上只有 **服务器**。以后换模式，见[把中枢配置成路由器或旁路网关](../scenarios/router_or_gateway.md)。

### 网口

**用哪些网口？** 按所选形态列出要填的项。每种形态都有 **面板端口** 和 **HTTPS 端口**，两个端口不能相同。

| 形态     | 另外要填的项                                                                   |
| -------- | ------------------------------------------------------------------------------ |
| 服务器   | 没有；每个网口保留现有地址，并在上面提供服务                                   |
| 旁路网关 | **接入该网络的网口**、**这台机器的地址**、**前缀长度**、**该网络自己的路由器** |
| 路由器   | **对外出网**、**对内接设备**、**这台机器的地址**、**前缀长度**                 |
| 单臂路由 | **单臂网口**、**设备所在的 VLAN 标签**、**这台机器的地址**、**前缀长度**       |

路由器在向导里只设一个上行网口和一个服务网口，更多网口在面板的网络页添加。

### 代理

**通过代理出网** 这一屏只在完整版里有，可以跳过，同样的设置在[代理](../hub/proxy.md)页都有。现在就设置的话，打开 **在这里设置**，在 **出口节点链接** 里逐条粘贴 `ss://` 或 `vless://` 链接。

| 项                                  | 出现在   | 作用                            |
| ----------------------------------- | -------- | ------------------------------- |
| **应用连接的 SOCKS 端口**           | 服务器   | 一个经出口节点出网的 SOCKS 端口 |
| **同时开一个绕过代理的 SOCKS 端口** | 其余形态 | 再开一个直接出网的 SOCKS 端口   |
| **这台机器自己的流量也走代理**      | 所有形态 | 本机自己的连接走出口节点        |

### 就绪

**就绪** 列出你的回答。核对之后，选择 **开始配置这台机器**。

路由器和单臂路由多一条提示，写着面板的新地址。网口切换时页面断开，打开那个新地址，配置照常跑完。

## 看着步骤跑完

页面标题变成 **正在配置**，逐条列出正在跑的步骤。

![配置完成的页面，提供证书下载](/guide/zh/setup_done.webp)

标题变成 **这个中枢已配置好** 以后：

- HTTPS 关着时，页面 5 秒后转到面板，选择 **打开面板** 马上过去。
- HTTPS 开着时，页面出现 **在这台设备上安装证书**。按当前设备的标签装好证书颁发机构，核对它的指纹和 **SHA-256** 一行相同，重启浏览器，打开面板的 `https://` 地址。

每次运行的完整记录写在日志里：

| 系统    | 日志                                        |
| ------- | ------------------------------------------- |
| Linux   | `/var/log/neutrino/hub/setup.log`           |
| macOS   | `/Library/Logs/Neutrino/hub/setup.log`      |
| Windows | `C:\ProgramData\Neutrino\hub\log\setup.log` |

向导失败时，见[故障排查](../reference/troubleshooting.md#向导和恢复备份)。

## 登录

![登录页](/guide/zh/login.webp)

1. 打开面板地址。HTTPS 关着时，是 `http://` 加这台机器的地址和面板端口；开着时，是 `https://` 加这台机器的地址，HTTPS 端口不是 443 时再加端口。
1. 在 **面板密码** 里填你设的密码，选择 **登录**。

登录后进入[总览](../hub/dashboard.md)页。连续输错密码后，登录页读 **多次失败后已锁定。** 在中枢这台机器上运行 `sudo nhub unlock` 解锁；Windows 上在管理员 PowerShell 里运行 `nhub unlock`。
