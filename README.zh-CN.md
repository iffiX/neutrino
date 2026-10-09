<div align="center">

<img src="images/web/banner.webp" width="100%" alt="微子" />

# 家里的电脑，扫一次码，从任何地方接着用

我为了旅行做的小工具。

[English](README.md) · 简体中文

[![License: MIT](https://img.shields.io/badge/license-MIT-0a0e14?labelColor=0a0e14&color=22d3ee)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.5.0-0a0e14?labelColor=0a0e14&color=22d3ee)](https://github.com/iffiX/neutrino/releases)
[![Platforms](https://img.shields.io/badge/runs%20on-Linux%20%C2%B7%20macOS%20%C2%B7%20Windows%20%C2%B7%20Android-0a0e14?labelColor=0a0e14&color=a78bfa)](https://neutrino.beyond-infinity.top/zh-CN/reference/platforms.html)

[![CI](https://img.shields.io/github/actions/workflow/status/iffiX/neutrino/ci.yml?branch=main&label=CI&labelColor=0a0e14)](https://github.com/iffiX/neutrino/actions/workflows/ci.yml)
[![Release build](https://img.shields.io/github/actions/workflow/status/iffiX/neutrino/release.yml?label=release%20build&labelColor=0a0e14)](https://github.com/iffiX/neutrino/actions/workflows/release.yml)
[![Tests](https://img.shields.io/badge/tests-9886%20unit%20%C2%B7%20162%20integration-0a0e14?labelColor=0a0e14&color=22d3ee)](https://github.com/iffiX/neutrino/actions/workflows/ci.yml)
[![Code size](https://img.shields.io/github/languages/code-size/iffiX/neutrino?label=code&labelColor=0a0e14&color=a78bfa)](https://github.com/iffiX/neutrino)

**[安装](#安装)** · **[文档](https://neutrino.beyond-infinity.top/zh-CN/)** · [发布](https://github.com/iffiX/neutrino/releases)

</div>

<img src="images/web/devices.webp" width="100%" alt="电脑上是面板的服务页，手机上是同一套服务" />

## 它能做什么

- **AI 会话**：家里机器上的 CloudCLI，手机上接着聊。
- **编辑器**：VS Code、code-server 在浏览器里打开。
- **终端**：保持、共享，几台设备同一个会话。
- **远程桌面**：点一下。
- **文件**：挂成盘符或文件夹。
- **端口**：容器发布的端口，和你声明的 TCP、UDP 端口，转到本机。

全部只经中枢的一个端口，在家在外一样。AI 网关多账号配一次，每台设备同一套。

<img src="images/web/one_scan.webp" width="100%" alt="小狼把六样东西汇成一个光球" />

## 安装

中枢装在家里一台常开的机器上。Linux 和 macOS：

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

Windows：

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

要管的机器装被控端，你坐在前面的电脑装客户端，还是这条命令，末尾加 `agent` 或 `client`：

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
```

国内版和用包文件安装，见[安装中枢](https://neutrino.beyond-infinity.top/zh-CN/install/hub.html)。

想重来一遍但不卸载，就重置中枢。包还在，再运行 `sudo nhub setup` 重新配置：

```bash
sudo nhub reset all
```

要彻底卸载中枢，先重置，再卸包：

```bash
sudo apt remove neutrino-hub     # Debian、Ubuntu
sudo dnf remove neutrino-hub     # Fedora、RHEL
sudo pacman -R neutrino-hub      # Arch
```

Windows 上在 **设置** > **应用** > **安装的应用** 里卸载 **Neutrino Hub**。被控端和客户端用同样的办法卸：

```bash
sudo apt remove neutrino-agent      # 被控的机器
sudo apt remove neutrino-client     # 你坐在前面的电脑
sudo nagent service uninstall       # 只去掉模块加上的服务和规则，机器上的数据留着
```

共享、仓库和容器卷留在机器上。macOS 的命令和每一步留下什么，见文档站的[卸载](https://neutrino.beyond-infinity.top/zh-CN/uninstall.html)页。

## 扫码加入

在面板的客户端页建一条链接。手机扫码，电脑贴链接，服务就在列表里了。

## 从外面连回来

NetBird、EasyTier、自己的 VPS，或者直连\*，在面板的外部访问页上开一种就行。推荐 NetBird 或 EasyTier。每种要准备什么，见[外部访问](https://neutrino.beyond-infinity.top/zh-CN/hub/overlay.html)。

\* 直连要把 8443 开到公网上，这部分的安全性还在测试，先别在公网上用。

## 安全性

- **对外只开一个端口。** 只有 8443 对外，而且只在你打开直连\*时才开；面板的两个端口只在你勾选的网络上应答。外面的人看到的，只是一个要出示凭证的 TLS 端口。
- **只有加入过的设备能连，连上的全程加密。** 客户端和被控端到中枢的每一条连接都是 TLS。加入要用链接里的票据，链接 30 分钟有效、只能用一次；设备记住中枢的证书指纹，以后只认这一台。
- **对 DoS 做了基本的防护。** 没验证的连接只能走一次握手，连接数、握手时间和消息大小都有上限，超了就断。这部分还比较初步，欢迎提 issue。
- **面板密码防爆破。** 连续输错 5 次之后开始锁定，锁定时间逐级加长，30 秒、60 秒、5 分钟、1 小时、1 天；fail2ban 按同样的阶梯封禁反复尝试 SSH 登录的地址。
- **密钥封在保险库里。** 密钥、密码和令牌用你安装时设的主口令加密；配置文件和备份里只有密文，面板存进去之后也不再显示。
- **root 只用在该用的地方。** 中枢要改防火墙、装软件，被控端要起服务，所以这两个以 root 运行，服务单元关掉了 root 用不到的能力；客户端跑在你自己的账户下。

细节在 [design/connection.md](skills/core-code-author/design/connection.md) 和 [design/privilege.md](skills/core-code-author/design/privilege.md)。写给读者的版本在文档站的[安全](https://neutrino.beyond-infinity.top/zh-CN/security.html)页。

## 文档和许可证

[中文文档](https://neutrino.beyond-infinity.top/zh-CN/) · [English documentation](https://neutrino.beyond-infinity.top/)

[MIT](LICENSE)。`client/android/` 下的安卓应用编进了 RustDesk 的内核，这个目录按它自己的 `LICENSE` 采用 AGPL-3.0。

<details>
<summary><b>致谢</b></summary>

- [Xray-core](https://github.com/XTLS/Xray-core)：代理内核
- [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)：AI 网关
- [cpa-usage-keeper](https://github.com/Willxup/cpa-usage-keeper)：网关的用量记录
- [NetBird](https://github.com/netbirdio/netbird)：带管理面的虚拟网
- [EasyTier](https://github.com/EasyTier/EasyTier)：去中心化的虚拟网
- [cc-switch](https://github.com/SaladDay/cc-switch-cli)：切换 Claude Code、Codex 和 Gemini CLI 的配置
- [RustDesk](https://github.com/rustdesk/rustdesk)：远程桌面的主机和查看器
- [CloudCLI](https://github.com/siteboon/claudecodeui)：浏览器里的 AI 编程会话
- [code-server](https://github.com/coder/code-server)：浏览器里的 VS Code
- [Gitea](https://github.com/go-gitea/gitea)：私有 git 服务器
- [Samba](https://www.samba.org/)：SMB 共享
- [Podman](https://github.com/containers/podman)：容器运行时
- [OpenZFS](https://github.com/openzfs/zfs)：存储池和数据集
- [dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html)：局域网的 DHCP 和 DNS
- [hostapd](https://w1.fi/hostapd/)：无线接入点
- [v2fly geodata](https://github.com/v2fly/domain-list-community)：分流用的域名和 IP 列表

</details>

<div align="center">

<img src="images/web/outro.webp" width="100%" alt="微子" />

# 让创造重新变得有趣。

少花点时间维护环境。<br/>
多花点时间，做当初让你搭起这套环境的事。

</div>
