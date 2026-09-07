<div align="center">

<img src="images/web/banner.webp" width="100%" alt="Neutrino 横幅" />

# 家里一台常开的中枢，<br/>管住你的所有小玩意。

[English](README.md) · **中文**

[![License: MIT](https://img.shields.io/badge/license-MIT-0a0e14?labelColor=0a0e14&color=22d3ee)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-0a0e14?labelColor=0a0e14&color=22d3ee)](https://github.com/iffiX/neutrino/releases)
[![Hub: Linux](https://img.shields.io/badge/hub-Linux%20x86--64%20%C2%B7%20ARM64-0a0e14?labelColor=0a0e14&color=a78bfa)](#兼容性)
[![Agent: Linux](https://img.shields.io/badge/agent-Linux-0a0e14?labelColor=0a0e14&color=a78bfa)](#兼容性)
[![Agent: Windows · macOS · under testing](https://img.shields.io/badge/agent%20Windows%20%C2%B7%20macOS-under%20testing-0a0e14?labelColor=0a0e14&color=d29922)](#兼容性)

微子能穿透一切，却什么也不碰。<br/>
障碍都还在，只是再也碍不着你了。

</div>

Neutrino（微子）是一个面向个人开发者的自托管管理工具。它运行在一台常开的 Linux 机器上，通过 Web 面板管理代理、远程访问、AI 网关、文件共享和自托管服务。

这台机器称为 **Hub**。其他电脑可以安装 **Agent**，向 Hub 上报运行状态并执行软件安装任务。你也可以在 Agent 窗口中挂载共享、打开服务、配置 AI 工具。Neutrino 使用 Xray、NetBird、CLIProxyAPI、Samba 等现有软件，存储和其他服务模块按需启用。

它是给一个人的 homelab 做的控制平面。写它时，我一直记着：这东西拿着每台受管机器的管理员权限。

一块闲置的 64 位树莓派，就能先跑起来。

[功能](#功能) · [安装](#安装) · [使用范围与权限](#使用范围与权限) · [文档](#文档)

<a href="images/screenshots/dashboard.webp"><img src="images/screenshots/dashboard.webp" width="100%" alt="总览面板：流量、代理状态、DNS 查询和受管设备" /></a>

## 它到底是什么

Neutrino 把 Xray、ZFS、Gitea、Samba 等软件配成一个整体，再让其他机器用上它们提供的服务。

|                  |                                                                                                                                                                                 |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **一份配置**     | `config/` 是唯一的配置来源。每次修改都经过「渲染、校验、应用」，面板和命令行走同一套流程。备份一个目录，就能保留 Hub 的配置；共享文件和服务数据另行备份。                       |
| **一个面板**     | 网络、代理、AI、设备、凭据、存储、服务，都在同一个界面里，用同一套方式管理。                                                                                                    |
| **一个 Agent**   | 用一条链接注册设备，就能看到你发布的共享、端口、网页、AI 入口和远程桌面。支持 Linux，Windows 和 macOS 为 **under testing**。                                                    |
| **一个 AI 入口** | Claude 订阅、ChatGPT 订阅和 API key 集中在 Hub 上，每台机器的 Claude Code、Codex、Gemini CLI 都可以接到同一个地址。访问密钥按设备和本地账号分别签发，用量也在 Hub 上统计。      |
| **一条退路**     | `nhub reset all` 先撤掉 Hub 的防火墙表和策略路由，重新启用原有的网络管理器，再重置配置。接口上的地址一个不删，避免 SSH 会话因地址被移除而中断。Hub 配置会被清空，执行前先备份。 |

## 功能

Hub 管理所在的主机，并与其他机器上的 Agent 通信。外出时，可以通过 NetBird 组建的虚拟网络访问 Hub 和家中的设备。

<img src="images/web/architecture.svg" width="100%" alt="远程设备通过 NetBird 访问 Hub，Hub 连接设备、AI、存储和服务" />

### 网络与远程访问

Hub 支持路由器、旁路网关和服务器三种模式。路由器和网关模式可以接管其他设备的流量；服务器模式保留主机原有的网络配置。

代理由 Xray 提供，支持节点导入、负载均衡、分流和 DNS 配置。你可以导入分享链接，选择哪些设备和目的地址走代理。全部节点不可用时，默认不会回退到直连。NetBird 通过 WireGuard 虚拟网络连接远程设备和家庭网络。

<table>
<tr>
<td width="50%"><a href="images/screenshots/netbird.webp"><img src="images/screenshots/netbird.webp" width="100%" alt="NetBird 页面：虚拟网络中的对端和局域网设备" /></a></td>
<td width="50%"><a href="images/screenshots/proxy.webp"><img src="images/screenshots/proxy.webp" width="100%" alt="代理页面：出口节点和路由设置" /></a></td>
</tr>
<tr>
<td><b>NetBird：</b>对端拓扑、直连与中继状态。</td>
<td><b>代理：</b>节点延迟、均衡策略和分流规则。</td>
</tr>
</table>

### 设备管理

扫描局域网、保存 SSH 凭据，从面板打开终端或 SFTP 文件浏览器。安装 Agent 的设备会定期上报 CPU、内存、磁盘、温度、GPU 和进程信息。面板也提供网络唤醒、电源操作，以及通过 RustDesk 直连的远程桌面。

你可以为受管设备安装 SSH 服务、cc-switch、RustDesk 等工具。Hub 缓存下载的安装包，再交给 Agent 安装。安装任务由用户发起，手动安装的软件也会被识别和显示。

<details>
<summary>查看 Hub 终端和凭据页面</summary>

<table>
<tr>
<td width="50%"><a href="images/screenshots/terminal.webp"><img src="images/screenshots/terminal.webp" width="100%" alt="Hub 主机的终端" /></a></td>
<td width="50%"><a href="images/screenshots/credentials.webp"><img src="images/screenshots/credentials.webp" width="100%" alt="凭据页面：SSH 密钥、登录信息和令牌" /></a></td>
</tr>
<tr>
<td><b>终端：</b>在浏览器中操作 Hub 主机。</td>
<td><b>凭据：</b>管理 SSH 密钥、登录信息和 API 令牌。</td>
</tr>
</table>

</details>

### AI 网关

Hub 运行 CLIProxyAPI，可以接入 Claude、ChatGPT 等订阅账号，也可以添加兼容 Anthropic、OpenAI 或 Gemini 协议的服务商 API key。网关提供统一访问地址和模型别名，面板按提供方和客户端密钥统计用量。

在每台电脑的 Agent 中，可以选择哪些本地账号的 Claude Code、Codex 或 Gemini CLI 使用网关。访问密钥按设备和本地账号分别签发；取消激活后，会恢复工具原先保存的配置。

<table>
<tr>
<td width="50%"><a href="images/screenshots/ai.webp"><img src="images/screenshots/ai.webp" width="100%" alt="AI 用量页面：请求数和 token 统计" /></a></td>
<td width="50%"><a href="images/screenshots/ai_accounts.webp"><img src="images/screenshots/ai_accounts.webp" width="100%" alt="AI 提供方、订阅账号和网关密钥" /></a></td>
</tr>
<tr>
<td><b>用量：</b>请求数、成功率、token 和缓存使用情况。</td>
<td><b>账号：</b>上游提供方、订阅账号和客户端密钥。</td>
</tr>
</table>

### 存储与服务

可选模块提供 ZFS 池和数据集管理、磁盘健康检查、换盘操作和 Samba 共享。Hub 也可以运行 Gitea 和 Podman 容器。

Hub 会向 Agent 发布服务列表，包括可打开的网页、可转发的端口和可挂载的共享。列表中也可以添加网络内其他机器提供的服务。

<details>
<summary>查看模块、服务、共享和容器页面</summary>

<table>
<tr>
<td width="50%"><a href="images/screenshots/modules.webp"><img src="images/screenshots/modules.webp" width="100%" alt="Hub 上可安装的模块" /></a></td>
<td width="50%"><a href="images/screenshots/services.webp"><img src="images/screenshots/services.webp" width="100%" alt="发布给受管设备的服务列表" /></a></td>
</tr>
<tr>
<td><b>模块：</b>安装在 Hub 上的软件。</td>
<td><b>服务：</b>发布给 Agent 的服务条目。</td>
</tr>
<tr>
<td><a href="images/screenshots/samba.webp"><img src="images/screenshots/samba.webp" width="100%" alt="Samba 共享、用户和连接会话" /></a></td>
<td><a href="images/screenshots/containers.webp"><img src="images/screenshots/containers.webp" width="100%" alt="Podman 容器及其运行状态" /></a></td>
</tr>
<tr>
<td><b>Samba：</b>共享、用户和当前连接。</td>
<td><b>容器：</b>Podman 容器及其运行状态。</td>
</tr>
</table>

</details>

<details>
<summary>查看手机界面</summary>

面板适配手机屏幕。下图依次为总览、代理、AI 和网络页面：

<p align="center">
<a href="images/screenshots/dashboard_portrait.webp"><img src="images/screenshots/dashboard_portrait.webp" width="200" alt="手机上的总览页面" /></a>
<a href="images/screenshots/proxy_portrait.webp"><img src="images/screenshots/proxy_portrait.webp" width="200" alt="手机上的代理页面" /></a>
<a href="images/screenshots/ai_portrait.webp"><img src="images/screenshots/ai_portrait.webp" width="200" alt="手机上的 AI 页面" /></a>
<a href="images/screenshots/network_portrait.webp"><img src="images/screenshots/network_portrait.webp" width="200" alt="手机上的网络页面" /></a>
</p>

</details>

## 安装

### 兼容性

| 组件  | 平台                                                                    | 架构          |
| ----- | ----------------------------------------------------------------------- | ------------- |
| Hub   | 使用 systemd、glibc 2.34 及以上的 Linux；提供 `.deb`、`.rpm` 和 Arch 包 | x86-64、ARM64 |
| Agent | Linux；Windows、macOS **under testing**                                 | x86-64、ARM64 |

两个安装包都自带 Python 运行环境。Hub 还包含 Xray 和 CLIProxyAPI，所需的系统依赖由包管理器安装。

使用 64 位系统、配备 1 GB 内存的树莓派可以在关闭可选模块时运行核心服务。启用更多模块或增加负载后，需要相应增加内存。

### Hub

从 [Releases](https://github.com/iffiX/neutrino/releases) 下载对应系统的安装包。Debian 或 Ubuntu 上的安装方式如下，将 `<version>` 替换为下载的版本号；示例使用 x86-64（`amd64`）包。

```bash
sudo apt install "./neutrino-hub_<version>_amd64.deb"
sudo nhub setup
```

在终端或浏览器中完成向导，然后访问 `http://<hub-address>:8080`，其中 `<hub-address>` 为 Hub 的地址。选择 `server` 模式可以保留主机现有的网络配置。

### Agent

在需要管理的电脑上安装 Agent。从 Hub 的「设备」页复制注册链接，粘贴到 Agent 窗口中。Debian 或 Ubuntu 上也可以通过命令行注册：

```bash
sudo apt install "./neutrino-agent_<version>_amd64.deb"
sudo nagent connect 'neutrino://enroll/...'
```

将示例链接替换为面板生成的链接。Windows 和 macOS Agent 目前为 **under testing**，原生安装包可从 Releases 下载。对于能够通过 SSH 访问的 Linux 机器，也可以从「设备」页远程安装并注册 Agent。

## 使用范围与权限

Neutrino 面向一个人管理自己的设备。面板使用单一密码，没有独立的用户角色，也不支持高可用部署。Hub 离线时，由它提供的服务会停止。

Hub 以 root 运行，Agent 服务也需要管理员权限来安装软件和管理设备。面板本身使用 HTTP，应通过可信的局域网或 NetBird 访问，不应直接暴露到公网。

<img src="images/web/warning_zh.webp" width="100%" alt="不要将 Hub 暴露到公网、部署在不属于你的网络中，或接入不可信设备" />

Hub 与 Agent 之间使用 TLS，Agent 根据注册链接中的证书指纹验证 Hub。注册链接五分钟过期，以原子操作消费；两台机器同时使用同一条链接，也只能有一台注册成功。Hub 凭据库中的凭据经过加密，恢复时需要初始化时设置的主密码。

凭据库文件连自己装了什么都不说：名称、类型和内容一起加密，解密用的明文密钥不随配置备份导出。

## 配置与备份

Hub 的设置保存在 `config/` 中。面板和 `nhub apply` 使用同一套渲染、校验和应用流程。

「设置」页可以导出配置备份。恢复凭据时需要主密码；共享文件、Git 仓库和容器数据需要另行备份。恢复后，AI 订阅账号需要重新登录。

恢复时，在「设置」页上传配置备份并输入主密码。重置和凭据库相关命令见[命令参考](docs/cli.md)。

## 我为什么做它

我平时会用到工作站、笔记本和家里的几台小机器。Neutrino 最初是为这些机器写的，目前也用于自己的开发环境。

<table>
<tr valign="top">
<td width="50%" align="center">
<img src="images/web/panel_0.webp" width="220" alt="微子被挡在网络屏障前" />
<p><b>最先卡住的，是连不上工具。</b></p>
<p align="left">拉代码、下载依赖、连接 AI 服务，有时都要先配好代理。我不想每台机器都折腾一遍，就把代理和分流放到了 Hub 上。</p>
</td>
<td width="50%" align="center">
<img src="images/web/panel_5.webp" width="220" alt="微子在外使用笔记本，与家中网络的连接断开" />
<p><b>我出门旅行，工作站只能待家里。</b></p>
<p align="left">家里的服务照常运行，我在外面却连不上。现在通过 NetBird 连回去，手机也能打开面板。</p>
</td>
</tr>
<tr valign="top">
<td align="center">
<img src="images/web/panel_4.webp" width="220" alt="微子被多台电脑和缠绕的线缆包围" />
<p><b>单台机器都不难伺候，全凑一块儿就难了。</b></p>
<p align="left">工作站、笔记本、GPU 主机、树莓派，地址和登录方式各不相同。我想把它们放到同一页，看看谁在线，需要时直接开终端。</p>
</td>
<td align="center">
<img src="images/web/panel_2.webp" width="220" alt="微子面对逐渐增加的硬盘，不确定该如何整理" />
<p><b>数据是悄悄长起来的。</b></p>
<p align="left">硬盘一块块添，文件越放越散，后来连找东西都费劲。现在把存储池和共享放在 Hub 上，其他机器挂载来用。</p>
</td>
</tr>
<tr valign="top">
<td align="center">
<img src="images/web/panel_3.webp" width="220" alt="Git、SSH、文件和容器服务的入口分散在微子周围" />
<p><b>每样东西都能用，只是各住各的。</b></p>
<p align="left">Gitea 一个地址，容器一个端口，文件共享又在别处。把这些入口登记到 Hub，换台电脑也能找到同一张服务清单。</p>
</td>
<td align="center">
<img src="images/web/panel_1.webp" width="220" alt="微子站在两个独立的 AI API 入口之间" />
<p><b>我受够了到处复制同一把 key。</b></p>
<p align="left">换台电脑，又要配一遍 AI 服务商和工具。现在账号集中放在 Hub 上，本地工具通过 Agent 接入网关。</p>
</td>
</tr>
</table>

项目目前为 0.1，由一个人维护。仓库包含 Debian、Ubuntu、Fedora 和 Arch 的虚拟机集成测试，以及 Linux、Windows、macOS 上的 Agent 测试。遇到问题可以提交 [Issue](https://github.com/iffiX/neutrino/issues)，附上系统、版本和出错步骤。

## 文档

- [命令参考](docs/cli.md)
- [Agent 安装与命令](agent/README.md)

## 致谢

Neutrino 使用了以下项目：

- [Xray-core](https://github.com/XTLS/Xray-core)：代理路由。
- [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)：AI 网关。
- [cpa-usage-keeper](https://github.com/Willxup/cpa-usage-keeper)：AI 用量页面的设计参考。
- [NetBird](https://netbird.io)：基于 WireGuard 的远程访问。
- [cc-switch](https://github.com/SaladDay/cc-switch-cli)：AI 工具配置。
- [RustDesk](https://rustdesk.com)：远程桌面。
- [Gitea](https://about.gitea.com)：Git 托管。
- [Samba](https://www.samba.org)：文件共享。
- [Podman](https://podman.io)：容器。
- [OpenZFS](https://openzfs.org)：存储。
- [dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html)：局域网 DHCP 和 DNS。
- [hostapd](https://w1.fi/hostapd/)：Wi-Fi 接入点。
- [v2fly geodata](https://github.com/v2fly)：路由数据库。

Claude Code 和 ChatGPT 参与了实现、调试、设计讨论和文档编写。发布内容由作者审阅和维护。

## 许可证

[MIT](LICENSE)。

<div align="center">

<img src="images/web/outro.webp" width="100%" alt="微子戴着耳机，在桌前使用笔记本电脑" />

# 让创造重新变得有趣。

少花点时间维护环境。<br/>
多花点时间，做当初让你搭起这套环境的事。

</div>
