---
title: 安装 hub
---

# 安装 hub

hub 装在一台常开的 Linux 机器上：装一个包，运行一次 `sudo nhub setup`，回答六屏问题，然后登录面板。面板的 HTTP 默认在 `8080` 端口，HTTPS 默认在 `443` 端口，向导里都可以改。

## 开始之前

- 系统是 Debian 12 及以上、Ubuntu 22.04 及以上、64 位树莓派 OS、Fedora、RHEL 9 系，或 x86-64 上的 Arch。
- 你有这台机器的 root 权限。
- 这台机器能出网。初始化要下载 xray-core、geodata 和 AI 网关。

每个文件对应哪个系统，见[支持的平台](../reference/platforms.md)。

## 安装包

从 [Releases 页](https://github.com/iffiX/neutrino/releases)下载对应的文件，用系统自己的包管理器安装：

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

ARM64 机器用 `neutrino-hub_0.5.0_arm64.deb` 或 `neutrino-hub-0.5.0-1.aarch64.rpm`；Arch 包只有 x86-64。RHEL 系要先单独装 `epel-release`，因为 fail2ban、arp-scan 和 vnstat 在 EPEL 里。包自带 Python，位于 `/opt/neutrino/python`。

::: warning
用 `apt`、`dnf` 或 `pacman` 安装。`dpkg -i` 和 `rpm -i` 不装依赖；如果已经用了，Debian 系运行 `sudo apt -f install` 补齐。
:::

## 启动向导

1. 运行 `sudo nhub setup`。终端为这台机器所在的每个网络打印一个地址，地址带一次性令牌；机器上有浏览器时，第一个地址直接打开。
1. 在任何一台能访问这台机器的电脑上，用浏览器打开其中一个地址。
1. 选择 **开始配置这台机器**（Set this box up）。

令牌只对这一次运行有效。没带令牌打开时，页面写着 **这台机器正等待配置**（This box is waiting to be set up）。想在终端里回答，在 **Continue in terminal (will close server)** 处按回车；同样的几屏改在终端里显示，始终是英文。

## 回答向导的问题

**下一步**（Next）往后走，**返回**（Back）往回走。最后一屏确认之前，什么都不写入。

### 语言

在 **语言**（Language）里选 **English** 或 **简体中文**。面板用这种语言显示，终端始终是英文。

### 密码与 HTTPS

![密码屏，带 HTTPS 开关](/guide/zh/setup_secrets.webp)

1. 输入两遍 **面板密码**（Panel password），至少 8 个字符，用来登录面板。
1. 输入两遍 **保险库主口令**（Vault master passphrase），至少 16 个字符，要有小写字母、大写字母、数字和符号。
1. 可选：打开 **面板使用 HTTPS**（HTTPS for the panel）。

主口令封存这台机器保管的每一份凭据，恢复备份时还要再输一次。开了 HTTPS，HTTP 端口会把每个浏览器转到 HTTPS 端口。无论开不开，hub 都生成面板证书；之后在[设置](./settings.md#https)页随时切换。

### 形态

![形态屏，选中服务器](/guide/zh/setup_shape.webp)

**这台机器做什么？**（What is this machine for?）只列出网口数量够用的形态：

| 形态                           | 做什么                                         |
| ------------------------------ | ---------------------------------------------- |
| **服务器**（Server）           | 不做路由，在别人访问它的网口上应答             |
| **旁路网关**（Side gateway）   | 为把它设为网关的主机转发流量                   |
| **路由器**（Router）           | 在上行网口和它服务的网络之间路由               |
| **单臂路由**（One-arm router） | 单根网线上路由：不带标签出网，带 VLAN 标签入内 |

服务器和旁路网关保留机器上的每个地址；路由器和单臂路由接管网口。各形态的区别和之后怎么改，见[网络](./network.md)页。

### 网口

**用哪些网口？**（Which ports?）按所选形态列出要填的项。每种形态都有 HTTP 用的 **面板监听端口**（Panel answers on port）和 **HTTPS 端口**（HTTPS port），两个端口不能相同。

| 形态     | 要填的项                                                                                                                                                                   |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 服务器   | 只有两个面板端口；每个网口保留现有地址并照常应答                                                                                                                           |
| 旁路网关 | **接入该网络的网口**（Port on that network）、**这台机器的地址**（This box's address）、**前缀长度**（Prefix length）、**该网络自己的路由器**（That network's own router） |
| 路由器   | **对外出网**（Out to the internet）、**对内接设备**（In to your devices）、**这台机器的地址**、**前缀长度**                                                                |
| 单臂路由 | **单臂网口，出入合一**（The one port, out and in）、**设备所在的 VLAN 标签**（VLAN tag for your devices）、**这台机器的地址**、**前缀长度**                                |

路由器在这里只设置第一个上行网口和第一个服务网络。

### 代理

**通过代理出网**（Going out through a proxy）这一屏可以跳过，同样的设置之后在[代理](./proxy.md)页里都有。现在就设置的话，打开 **在这里设置**（Set it up here），在 **出口节点链接**（Exit node links）里逐条粘贴 `ss://` 或 `vless://` 链接。

| 项                                                                                       | 形态     | 作用                            |
| ---------------------------------------------------------------------------------------- | -------- | ------------------------------- |
| **应用连接的 SOCKS 端口**（SOCKS port applications point at）                            | 服务器   | 一个经出口节点出网的 SOCKS 端口 |
| **同时开一个绕过代理的 SOCKS 端口**（Also publish a SOCKS port that bypasses the proxy） | 其余形态 | 再开一个直连出网的 SOCKS 端口   |
| **这台机器自己的流量也走代理**（Send this box's own traffic through it）                 | 所有形态 | 本机自己的连接走出口节点        |

### 就绪

**就绪**（Ready）列出形态、语言、网口、面板端口、HTTPS 端口、**HTTPS** 开关和代理。核对之后选择 **开始配置这台机器**。路由器和单臂路由会多一条警告，写着面板的新地址和日志文件 `/var/log/neutrino/setup.log`。网口切换时网络可能中断，刷新页面即可重新连上。

## 看着步骤跑完

页面标题变成 **正在配置**（Making it so），逐条列出正在跑的步骤，从 **检查中枢需要的软件包**（Checking the packages the hub needs）到 **安装本机被控端**（Installing this machine's agent）。**生成面板证书**（Generating the panel's certificates）这一步每次都跑，生成 hub 自己的证书颁发机构和面板证书。终端里显示同样的步骤。

![完成页，提供证书下载](/guide/zh/setup_done.webp)

标题变成 **这台机器已是网关**（This box is a gateway）之后，下一步看 HTTPS 的回答：

- HTTPS 关着：页面几秒后自动转到面板，选择 **打开面板**（Open the panel）可以立刻过去。
- HTTPS 开着：页面出现 **在这台设备上安装证书**（Install the certificate on this device），带一个 **安装证书**（Install certificate）按钮。按钮下面每个系统一个标签，当前设备的标签已选中，只显示它的步骤。装好证书颁发机构，核对它的指纹与 **SHA-256** 一行一致。然后重启浏览器，打开面板的 `https://` 地址。

终端里打印面板地址；HTTPS 开着时，还打印证书颁发机构在 HTTP 端口上的下载地址和指纹。

## 登录

![登录页](/guide/zh/login.webp)

1. 打开面板地址。HTTPS 关着时，是 `http://` 加这台机器的地址和面板端口；开着时，是 `https://` 加这台机器的地址，HTTPS 端口不是 `443` 时再加上端口。
1. 输入 **面板密码**，选择 **登录**（Sign in）。

登录后进入[总览](./dashboard.md)页。密码连续输错后，登录页写着 **多次失败后已锁定。**（Locked after repeated failures.），在这台机器上运行 `sudo nhub unlock` 解锁。
