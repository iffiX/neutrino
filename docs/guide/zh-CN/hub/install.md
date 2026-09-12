---
title: 安装 hub
---

# 安装 hub

hub 装在家里一台常开的 Linux 机器上。一条安装命令加一次初始化向导之后，面板在 `http://<hub-address>:8080` 应答，其中 `<hub-address>` 是这台机器的地址。这一页只装 hub；被控端和客户端各有自己的安装页。

## 开始之前

- 一台常开的 Linux 机器，带 systemd，x86-64 或 ARM64。支持的发行版在[支持的平台](../reference/platforms.md)里。
- root 权限。`nhub setup` 以 root 运行。
- 这台机器能出网。初始化要下载 xray-core、geodata 和 AI 网关。
- 选 **服务器**（Server）形态时，机器上现有的地址和路由一个都不改。

## 安装包

从 [Releases](https://github.com/iffiX/neutrino/releases) 下载对应的包，然后安装。

::: code-group

```bash [Debian、Ubuntu、树莓派 OS]
sudo apt install ./neutrino-hub_0.2.0_amd64.deb
```

```bash [Fedora、RHEL 系]
sudo dnf install -y epel-release
sudo dnf install ./neutrino-hub-0.2.0-1.x86_64.rpm
```

```bash [Arch]
sudo pacman -U neutrino-hub-0.2.0-1-x86_64.pkg.tar.zst
```

:::

ARM64 机器换成 `_arm64.deb` 或 `.aarch64.rpm`。第一条 `epel-release` 只有 RHEL 系需要，因为 fail2ban、arp-scan 和 vnstat 来自 EPEL；Fedora 跳过这一条命令。包自带 Python，在 `/opt/neutrino/python` 下，与发行版的 Python 无关。

## 运行初始化

1. 运行向导。

   ```bash
   sudo nhub setup
   ```

1. 打开终端打印的地址。地址里带一次性令牌；缺少令牌的请求，向导以 403 拒绝。
1. 点 **开始配置这台机器**（Set this box up）。

![向导的欢迎页](/guide/zh/setup_welcome.webp)

这台机器没有浏览器时，同一个网里的任何一台电脑都能打开那个地址。在终端里按回车，同样的六屏改在终端里显示，只是始终是英文。最后一屏确认之前什么都不写入，**返回**（Back）可以改前面的回答。

## 六屏逐屏

### 第 1 屏：语言

面板显示所用的语言，两个选项：English 和简体中文。终端始终是英文。

### 第 2 屏：面板密码，以及保险库口令

![密码屏](/guide/zh/setup_secrets.webp)

**面板密码**（Panel password）用来登录面板。**保险库主口令**（Vault master passphrase）封存这台机器保管的每一份凭据，恢复备份时还要输一次。

::: warning
主口令丢失后，保险库里的内容再也打不开，每份凭据和每个 AI 账号都要重新录入。记在这台机器之外。
:::

### 第 3 屏：这台机器做什么

![形态屏](/guide/zh/setup_shape.webp)

| 形态                           | 做什么                                         | 需要的网口   |
| ------------------------------ | ---------------------------------------------- | ------------ |
| **服务器**（Server）           | 不做路由，在收到请求的网口上应答               | 1            |
| **旁路网关**（Side gateway）   | 为把它设为网关的主机转发流量                   | 1            |
| **路由器**（Router）           | 在上行网口和它服务的网络之间路由               | 2            |
| **单臂路由**（One-arm router） | 一根网线上路由：不带标签出网，带 VLAN 标签入内 | 1 根有线网口 |

网口不够的形态不会出现在这一屏。单臂路由要求接入的交换机透传 VLAN 标签；在剥掉标签的交换机上，这一形态配好后也不通。只有路由器和单臂路由接管网口上的地址。

### 第 4 屏：用哪些网口

![网口屏](/guide/zh/setup_ports.webp)

这一屏随形态变化：

- 服务器：不给任何网口指定角色，每个网口保留现有地址；只填 **面板监听端口**（Panel answers on port），默认 8080。
- 旁路网关：选 **接入该网络的网口**（Port on that network），填 **这台机器的地址**（This box's address）、**前缀长度**（Prefix length）和 **该网络自己的路由器**（That network's own router）。
- 路由器：选 **对外出网**（Out to the internet）和 **对内接设备**（In to your devices）两个网口，填服务网络的地址和前缀，默认 `192.168.8.1/24`。
- 单臂路由：选 **单臂网口，出入合一**（The one port, out and in），填 **设备所在的 VLAN 标签**（VLAN tag for your devices），默认 3。

这里只设置主出网口和主服务网络，更多的网口之后在面板的[网络](./network.md)页添加。

### 第 5 屏：通过代理出网

![代理屏](/guide/zh/setup_proxy.webp)

这一屏可以跳过，之后在[代理](./proxy.md)页随时打开。要在这里设置，勾选 **在这里设置**（Set it up here），粘贴 `ss://` 或 `vless://` 链接，填 **应用连接的 SOCKS 端口**（SOCKS port applications point at）。

### 第 6 屏：就绪

![就绪屏](/guide/zh/setup_review.webp)

这一屏列出形态、语言、应答网口、面板端口和代理。确认之后防火墙加载，服务启动；路由器形态还会改网口。屏上写着面板之后的地址和日志的路径。路由器形态下网络可能短暂中断，中断时刷新页面重新连上。

## 初始化完成

![初始化完成](/guide/zh/setup_done.webp)

步骤列表跑完后标题变成 **这台机器已是网关**（This box is a gateway），页面几秒后转到面板；也可以点 **打开面板**（Open the panel）。

![登录页](/guide/zh/login.webp)

登录页只有一个 **面板密码**（Panel password）输入框。登录后打开 **设备**（Devices）页，这台机器自己已经在 **已管理的设备**（Managed devices）里：初始化的最后一步给它装了被控端。

![设备页里的本机](/guide/zh/devices_managed.webp)

## 之后的设置

| 想做的事                         | 去哪一页                                                                             |
| -------------------------------- | ------------------------------------------------------------------------------------ |
| 换形态，或给网口改角色           | [网络](./network.md)，换形态要先 `nhub reset all`                                    |
| 在外面进家里的局域网             | [虚拟网：NetBird](./overlay-netbird.md) 或 [虚拟网：EasyTier](./overlay-easytier.md) |
| 让选定的设备和目标经出口节点出网 | [代理](./proxy.md)                                                                   |
| 接入第二台机器                   | [安装被控端](../agent/install.md)                                                    |
