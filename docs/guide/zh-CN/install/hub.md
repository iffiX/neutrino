---
title: 安装中枢
---

# 安装中枢

照这一页做完，中枢就在你的机器上运行了，你也登录进了面板。面板的 HTTP 端口默认是 8080，HTTPS 端口默认是 443，两个都能在向导里改。

## 开始之前

- 系统是下面之一：
  - Linux，任意网络形态：Debian 12、Ubuntu 22.04、64 位树莓派 OS、Fedora 41、RHEL 9 系，或 x86-64 上的 Arch。
  - macOS 12.3 或更新版本，Apple 芯片或 Intel，只有服务器形态。
  - x86-64 上的 Windows 10 1809 或更新版本，只有服务器形态。
- 你有这台机器的 root 权限，Windows 上是管理员权限。
- 这台机器能上网。

每个安装包对应哪个系统，见[支持的平台](../reference/platforms.md)。

## 选版本

每次发布都从同一份源码编出两个版本，两个版本各自只从自己的发布页更新。

| 版本   | 发布在哪                                                           | 有什么                                                                                              |
| ------ | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| 完整版 | GitHub 的发布页 `github.com/iffiX/neutrino/releases`，每一版都保留 | 全部功能                                                                                            |
| 国内版 | Gitee 的发布页 `gitee.com/iffiX/neutrino/releases`，只保留最新一版 | 没有代理、NetBird 和旁路网关形态；中枢只发 amd64 和 arm64 的 `.deb`、Windows 和 Apple 芯片 Mac 的包 |

国内版的各项下载都走国内镜像。国内版的 Linux 中枢只有 `.deb`，Mac 只有 Apple 芯片的包，所以 Fedora、RHEL、Arch 和 Intel 的 Mac 只能装完整版。

## 一条命令安装

安装脚本按这台机器的系统和处理器选出安装包，用发布页的 `SHA256SUMS` 核对，再安装。整个过程只要一次管理员权限。

在终端里运行时，脚本装好后直接进入 `nhub setup`，打印设置向导的地址。在没有终端的环境里运行时，例如由别的脚本调用，脚本只把这个地址打印出来。这台机器上的中枢已经设置过时，脚本只打印面板的地址。

### Linux 和 macOS

完整版：

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

国内版：

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh
```

下载开始之前，你在 `sudo` 的提示下输入一次密码。

### Windows

打开 PowerShell。完整版：

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

国内版：

```powershell
irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1 | iex
```

PowerShell 不是以管理员身份运行时，Windows 弹出一次授权框。你同意后，脚本在新开的管理员 PowerShell 窗口里接着运行，这个窗口运行完也不关。

## 用包文件安装

从发布页下载这台机器对应的文件，用系统自己的安装工具装。每个安装包装好后都启动中枢的服务，这个服务在设置完成之前提供设置向导。

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

ARM64 机器用 `neutrino-hub_0.5.0_arm64.deb` 或 `neutrino-hub-0.5.0-1.aarch64.rpm`。Arch 的包只有 x86-64。RHEL 系要单独先装 `epel-release`，因为 fail2ban、arp-scan 和 vnstat 在 EPEL 里。包自带 Python，装在 `/opt/neutrino/hub/python`。

::: warning
用 `apt`、`dnf` 或 `pacman` 安装，它们会一起装上依赖。`dpkg -i` 和 `rpm -i` 不装依赖；已经用了的话，Debian 系运行 `sudo apt -f install` 补齐。
:::

### macOS

Apple 芯片的 Mac 运行：

```bash
sudo installer -pkg neutrino-hub-0.5.0-macos-arm64.pkg -target /
```

Intel 的 Mac 用 `neutrino-hub-0.5.0-macos-amd64.pkg`。安装程序注册并启动中枢的服务，把 `nhub` 链接到 `/usr/local/bin`。

### Windows

双击 `neutrino-hub-0.5.0-windows-amd64.msi`。静默安装时，在管理员 PowerShell 里运行：

```powershell
msiexec /i neutrino-hub-0.5.0-windows-amd64.msi /qn
```

安装程序注册 `neutrino_hub` 服务并启动它，再把 `nhub` 加进系统的 `PATH`。

## 打开设置向导

中枢的服务在面板的 HTTP 端口上提供向导，地址末尾要带一次性令牌。没带令牌打开时，页面读 **这台机器正等待配置**（This box is waiting to be set up）。

Linux 上：

1. 运行 `sudo nhub setup`。终端为这台机器的每个地址打印一行向导地址，末尾都带着令牌。
1. 在任意一台能访问这台机器的电脑上，用浏览器打开其中一个地址。
1. 选择 **开始配置这台机器**（Set this box up）。

macOS 和 Windows 上，打开“应用程序”文件夹或开始菜单里的 **Neutrino Hub**。它在默认浏览器里打开向导，地址已经带着令牌。中枢的服务没在运行时，系统先弹出一次管理员授权框。在终端里运行 `nhub open` 也一样。向导打开后，选择 **开始配置这台机器**。

终端里的 `nhub setup` 停在欢迎屏时，按回车就改在终端里回答同样的问题。终端里的向导始终是英文。

## 回答向导

**下一步**（Next）往后走，**返回**（Back）往回走。最后一屏确认之前，向导不写入任何东西。

### 语言

在 **语言**（Language）里选 **English** 或 **简体中文**。面板用这种语言显示。

### 密码与 HTTPS

![面板密码、保险库口令和 HTTPS 开关](/guide/zh/setup_secrets.webp)

1. 在 **面板密码**（Panel password）和 **再输一次**（Again）里填同一个密码，至少 8 个字符。登录面板用它。
1. 在 **保险库口令**（Vault passphrase）和它的 **再输一次** 里填同一个口令。它至少 16 个字符，要混用小写、大写、数字和符号。
1. 可选：打开 **面板使用 HTTPS**（HTTPS for the panel）。

保险库口令封存中枢保管的每一份凭据，恢复备份时还要输入它。不管开不开 HTTPS，中枢都生成面板证书，之后能在[设置](../hub/settings.md)页随时开关。

### 形态

![形态屏上选中了服务器](/guide/zh/setup_shape.webp)

Linux 上，**这台机器做什么？**（What is this machine for?）只列出网口数量够用的形态：

| 形态                           | 做什么                                         |
| ------------------------------ | ---------------------------------------------- |
| **服务器**（Server）           | 在它所连的网络上提供服务，不做路由             |
| **旁路网关**（Side gateway）   | 为把它设为网关的主机转发流量；国内版没有       |
| **路由器**（Router）           | 在上行网口和它服务的网络之间路由               |
| **单臂路由**（One-arm router） | 单根网线上路由：不带标签出网，带 VLAN 标签入内 |

服务器和旁路网关保留机器上原有的地址。路由器和单臂路由接管网口。macOS 和 Windows 上，这一屏只有 **服务器** 一项。各形态的区别和以后怎么改，见[网络](../hub/network.md)。

### 网口

**用哪些网口？**（Which ports?）按所选形态列出要填的项。每种形态都有 **面板端口**（Panel port）和 **HTTPS 端口**（HTTPS port），两个端口不能相同。

| 形态     | 另外要填的项                                                                                                                                                               |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 服务器   | 没有；每个网口保留现有地址，并在上面提供服务                                                                                                                               |
| 旁路网关 | **接入该网络的网口**（Port on that network）、**这台机器的地址**（This box's address）、**前缀长度**（Prefix length）、**该网络自己的路由器**（That network's own router） |
| 路由器   | **对外出网**（Out to the internet）、**对内接设备**（In to your devices）、**这台机器的地址**、**前缀长度**                                                                |
| 单臂路由 | **单臂网口**（One-arm port）、**设备所在的 VLAN 标签**（VLAN tag for your devices）、**这台机器的地址**、**前缀长度**                                                      |

路由器在向导里只设一个上行网口和一个服务网口，更多网口在面板的网络页添加。

### 代理

**通过代理出网**（Going out through a proxy）这一屏只在完整版里有，可以跳过，同样的设置以后在[代理](../hub/proxy.md)页都有。现在就设置的话，打开 **在这里设置**（Set it up here），在 **出口节点链接**（Exit node links）里逐条粘贴 `ss://` 或 `vless://` 链接。

| 项                                                                                       | 出现在   | 作用                            |
| ---------------------------------------------------------------------------------------- | -------- | ------------------------------- |
| **应用连接的 SOCKS 端口**（SOCKS port applications point at）                            | 服务器   | 一个经出口节点出网的 SOCKS 端口 |
| **同时开一个绕过代理的 SOCKS 端口**（Also publish a SOCKS port that bypasses the proxy） | 其余形态 | 再开一个直接出网的 SOCKS 端口   |
| **这台机器自己的流量也走代理**（Send this box's own traffic through it）                 | 所有形态 | 本机自己的连接走出口节点        |

### 就绪

**就绪**（Ready）列出形态、语言、网口、两个面板端口、HTTPS 和代理。核对之后，选择 **开始配置这台机器**。

路由器和单臂路由多一条提示，写着面板的新地址和日志文件的位置。网口切换时，页面会断开并显示面板的新地址。在浏览器里打开这个新地址，配置照常跑完。

## 看着步骤跑完

页面标题变成 **正在配置**（Setting up），逐条列出正在跑的步骤，第一步是 **检查中枢需要的软件包**（Checking the packages the hub needs），最后一步是 **设置面板密码**（Setting the panel password）；本机的被控端在这之后自动装上。**生成面板证书**（Generating the panel's certificates）每次都跑，生成中枢自己的证书颁发机构和面板证书。

![配置完成的页面，提供证书下载](/guide/zh/setup_done.webp)

标题变成 **这个中枢已配置好**（This hub is set up）以后，页面按 HTTPS 的开关分两种：

- HTTPS 关着：页面 5 秒后转到面板，选择 **打开面板**（Open the panel）可以马上过去。
- HTTPS 开着：页面出现 **在这台设备上安装证书**（Install the certificate on this device）和 **安装证书**（Install certificate）按钮。下面每个系统一个标签，按当前设备的标签装好证书颁发机构，核对它的指纹和 **SHA-256** 一行相同。然后重启浏览器，打开面板的 `https://` 地址。

每次运行的完整记录写在日志里：

| 系统    | 日志                                        |
| ------- | ------------------------------------------- |
| Linux   | `/var/log/neutrino/hub/setup.log`           |
| macOS   | `/Library/Logs/Neutrino/hub/setup.log`      |
| Windows | `C:\ProgramData\Neutrino\hub\log\setup.log` |

## 登录

![登录页](/guide/zh/login.webp)

1. 打开面板地址。HTTPS 关着时，是 `http://` 加这台机器的地址和面板端口。开着时，是 `https://` 加这台机器的地址，HTTPS 端口不是 443 时再加端口。
1. 在 **面板密码** 里填你设的密码，选择 **登录**（Sign in）。

登录后进入[总览](../hub/dashboard.md)页。连续输错密码后，登录页读 **多次失败后已锁定。**（Locked after repeated failures.）。在中枢这台机器上运行 `sudo nhub unlock` 解锁；Windows 上在管理员 PowerShell 里运行 `nhub unlock`。
