<img src="images/web/banner.webp" width="100%" alt="Neutrino" />

# 家里一台常开的中枢，<br/>管住你的所有小玩意。

[English](README.md) · 简体中文

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![version](https://img.shields.io/badge/version-0.2.0-0891b2.svg)](https://github.com/iffiX/neutrino/releases) [![hub](https://img.shields.io/badge/hub-Linux%20x86--64%20%C2%B7%20ARM64-555.svg)](#什么跑在哪里) [![agent](https://img.shields.io/badge/agent-Linux-555.svg)](#什么跑在哪里) [![client](https://img.shields.io/badge/client-Linux%20%C2%B7%20Windows-555.svg)](#什么跑在哪里)

微子能穿透一切，却什么也不碰。<br/>
障碍都还在，只是再也碍不着你了。

[安装](#安装) · [文档](#文档) · [能干什么](#它是什么能干什么) · [面板](#面板) · [为什么做它](#我为什么做它)

## 它是什么，能干什么

中枢管理你的机器，把它们提供的服务集中发布。客户端无论在家里的局域网，还是从外面经虚拟网连上中枢，拿到的都是同一份服务。

中枢装在一台常开的 Linux 机器上，负责网络、虚拟网、代理和 AI 网关。被控端装在每台要管理的 Linux 机器上，把那台机器的共享、git、容器、存储和桌面提供出来。客户端装在每台你坐在前面的电脑上，把这些服务变成窗口里的按钮。

| 面板页 | 你能做什么                                                          | 在哪做                       |
| ------ | ------------------------------------------------------------------- | ---------------------------- |
| 网络   | 选这台机器的形态，给网口分配角色，决定面板在哪些网络上应答          | 面板 **网络**（Network）     |
| 虚拟网 | 把中枢接进 NetBird 或 EasyTier，在外面进家里的局域网                | 面板 **虚拟网**（Overlay）   |
| 代理   | 从分享链接导入出口节点，按设备和目标分流，开 SOCKS 端口             | 面板 **代理**（Proxy）       |
| AI     | 把订阅账号和 API 密钥挂在一个网关地址后面，给每台电脑发自己的密钥   | 面板 **AI**                  |
| 设备   | 用一条链接或一组 SSH 凭据接入一台机器，重启、唤醒、开 shell、进桌面 | 面板 **设备**（Devices）     |
| 客户端 | 给一个人发一条链接，启用、停用或删除这个人的客户端                  | 面板 **客户端**（Clients）   |
| 服务   | 看模块发布了什么，手动声明一个网页、端口或共享                      | 面板 **服务**（Services）    |
| 凭据   | 保存 SSH 密钥、登录信息和令牌，之后在各处引用而不再粘贴             | 面板 **凭据**（Credentials） |
| 设置   | 改密码和语言，下载和恢复配置存档，看三个组件的版本                  | 面板 **设置**（Settings）    |

<img src="images/web/one_click.webp" width="100%" alt="面板的服务页与客户端窗口" />

## 支持的平台

| 中枢 `neutrino-hub`                                          | 架构          | 包                  |
| ------------------------------------------------------------ | ------------- | ------------------- |
| Debian 12 及以上、Ubuntu 24.04 及以上、Raspberry Pi OS 64 位 | x86-64、ARM64 | `.deb`              |
| Fedora 41 及以上、RHEL 9 系（AlmaLinux、Rocky）              | x86-64、ARM64 | `.rpm`，先启用 EPEL |
| Arch、EndeavourOS、Manjaro                                   | x86-64        | `.pkg.tar.zst`      |

| 被控端 `neutrino-agent`                                      | 架构          | 包     |
| ------------------------------------------------------------ | ------------- | ------ |
| Debian 12 及以上、Ubuntu 24.04 及以上、Raspberry Pi OS 64 位 | x86-64、ARM64 | `.deb` |
| Fedora 41 及以上、RHEL 9 系                                  | x86-64、ARM64 | `.rpm` |

| 客户端 `neutrino-client`                          | 架构          | 包     |
| ------------------------------------------------- | ------------- | ------ |
| Debian 12 及以上、Ubuntu 24.04 及以上，带桌面会话 | x86-64、ARM64 | `.deb` |
| Fedora 41 及以上、RHEL 9 系，带桌面会话           | x86-64、ARM64 | `.rpm` |
| Windows 10、Windows 11                            | x86-64        | `.msi` |
| macOS，Apple 芯片                                 | ARM64         | `.pkg` |

## 安装

<details>
<summary><b>中枢</b> · Debian、Ubuntu、Raspberry Pi OS</summary>

```bash
sudo apt install ./neutrino-hub_0.2.0_amd64.deb
sudo nhub setup
```

向导在浏览器里打开；回答完六屏问题，面板就在 `http://<hub-address>:8080`，其中 `<hub-address>` 是这台机器的地址。
</details>

<details>
<summary><b>中枢</b> · Fedora、RHEL 系</summary>

```bash
sudo dnf install -y epel-release
sudo dnf install ./neutrino-hub-0.2.0-1.x86_64.rpm
sudo nhub setup
```

第一条只有 RHEL 系需要。
</details>

<details>
<summary><b>中枢</b> · Arch、EndeavourOS、Manjaro</summary>

```bash
sudo pacman -U neutrino-hub-0.2.0-1-x86_64.pkg.tar.zst
sudo nhub setup
```

选 **服务器**（Server）形态时，机器上的地址一个都不改。
</details>

<details>
<summary><b>被控端</b> · Debian 系</summary>

```bash
sudo apt install ./neutrino-agent_0.2.0_amd64.deb
sudo nagent connect '<enroll-link>'
```

链接来自面板设备页的 **用链接添加**（Add by link），五分钟内有效。
</details>

<details>
<summary><b>被控端</b> · Fedora、RHEL 系</summary>

```bash
sudo dnf install ./neutrino-agent-0.2.0-1.x86_64.rpm
sudo nagent connect '<enroll-link>'
```

连上之后，这台机器出现在设备页的 **已管理的设备**（Managed devices）里。
</details>

<details>
<summary><b>客户端</b> · Debian 系</summary>

```bash
sudo apt install ./neutrino-client_0.2.0_amd64.deb
nclient gui
```

窗口打开后，粘贴面板客户端页发的链接。`nclient` 不用 sudo。
</details>

<details>
<summary><b>客户端</b> · Fedora、RHEL 系</summary>

```bash
sudo dnf install ./neutrino-client-0.2.0-1.x86_64.rpm
nclient gui
```

同一条链接粘进窗口即可。
</details>

<details>
<summary><b>客户端</b> · Windows</summary>

```powershell
msiexec /i neutrino-client-0.2.0-windows-amd64.msi
```

安装程序显示一个把 `nclient` 加进 PATH 的选项；装完从开始菜单打开 Neutrino Client，图标进任务栏角落。
</details>

<details>
<summary><b>客户端</b> · macOS</summary>

```bash
sudo installer -pkg neutrino-client-0.2.0-macos-arm64.pkg -target /
```

也可以右键 pkg 选“打开”；应用装在 /Applications，点图标即打开窗口。
</details>

每个包的完整安装步骤在文档站：[安装中枢](https://neutrino.beyond-infinity.top/zh-CN/hub/install.html)、[安装被控端](https://neutrino.beyond-infinity.top/zh-CN/agent/install.html)、[安装客户端](https://neutrino.beyond-infinity.top/zh-CN/client/install.html)。

## 文档

- [中文文档站](https://neutrino.beyond-infinity.top/zh-CN/)：安装、面板每一页、客户端每个面板、命令行参考
- [快速上手](https://neutrino.beyond-infinity.top/zh-CN/quick-start.html)：一台中枢、一台被控端、一台客户端，挂上一个共享
- [English documentation](https://neutrino.beyond-infinity.top/)

## 五类服务

| 面板     | 条目从哪来                               | 客户端上的按钮   |
| -------- | ---------------------------------------- | ---------------- |
| 网页     | Gitea 模块，手动声明的网址               | 打开             |
| 端口     | 容器发布的端口，手动声明的 TCP 端口      | 连接、断开       |
| AI       | 中枢的 AI 网关                           | 配置、应用       |
| 文件     | Samba 模块，手动声明的共享               | 配置、挂载、卸载 |
| 远程桌面 | 机器自己用 `nagent rdp start` 共享的桌面 | 连接             |

|                                                                                        |                                                                                               |                                                                                                |
| -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| <img src="images/screenshots/client_web.webp" width="100%" alt="客户端的网页面板" />   | <img src="images/screenshots/client_ports.webp" width="100%" alt="客户端的端口面板" />        | <img src="images/screenshots/client_ai.webp" width="100%" alt="客户端的 AI 面板" />            |
| <img src="images/screenshots/client_files.webp" width="100%" alt="客户端的文件面板" /> | <img src="images/screenshots/client_desktops.webp" width="100%" alt="客户端的远程桌面面板" /> | <img src="images/screenshots/client_windows.webp" width="100%" alt="Windows 上的同一个窗口" /> |

## 面板

<table>
<tr valign="top">
<td width="50%"><a href="images/screenshots/dashboard.webp"><img src="images/screenshots/dashboard.webp" width="100%" alt="总览页" /></a><p>总览：中枢此刻在转发什么</p></td>
<td width="50%"><a href="images/screenshots/proxy.webp"><img src="images/screenshots/proxy.webp" width="100%" alt="代理页" /></a><p>代理：从分享链接加一个出口节点</p></td>
</tr>
<tr valign="top">
<td><a href="images/screenshots/ai_accounts.webp"><img src="images/screenshots/ai_accounts.webp" width="100%" alt="AI 账号页" /></a><p>AI：订阅账号登录一次</p></td>
<td><a href="images/screenshots/devices.webp"><img src="images/screenshots/devices.webp" width="100%" alt="设备页" /></a><p>设备：用一条链接接入一台机器</p></td>
</tr>
<tr valign="top">
<td><a href="images/screenshots/services.webp"><img src="images/screenshots/services.webp" width="100%" alt="服务页" /></a><p>服务：手动声明一个服务</p></td>
<td><a href="images/screenshots/samba.webp"><img src="images/screenshots/samba.webp" width="100%" alt="Samba 页" /></a><p>Samba：发布一个共享</p></td>
</tr>
</table>

<p align="center"><img src="images/screenshots/dashboard_portrait.webp" width="200" alt="手机上的总览页" /> <img src="images/screenshots/proxy_portrait.webp" width="200" alt="手机上的代理页" /> <img src="images/screenshots/ai_portrait.webp" width="200" alt="手机上的 AI 页" /> <img src="images/screenshots/services_portrait.webp" width="200" alt="手机上的服务页" /></p>

手机宽度下这几页照样能用。

## 什么跑在哪里

| 包                | 装在哪                                | 以什么身份运行       | 干什么                                                                 |
| ----------------- | ------------------------------------- | -------------------- | ---------------------------------------------------------------------- |
| `neutrino-hub`    | 一台常开的 Linux 机器                 | root，面板加几个服务 | 路由、代理、DNS、虚拟网、AI 网关、设备发现、客户端和凭据的管理         |
| `neutrino-agent`  | 每台要管的 Linux 机器                 | root，无窗口         | 在这台机器上跑 Samba、Gitea、Podman、ZFS 和 RustDesk 主机              |
| `neutrino-client` | 每个人的 Linux、Windows 或 macOS 电脑 | 这个人的普通账户     | 一个托盘和一个窗口：打开网页、转发端口、切换 AI 工具、挂载共享、连桌面 |

## 安全

- 面板走 HTTP，只在局域网或虚拟网里应答；被控端和客户端走 8443 端口的 TLS 通道，证书指纹写在加入链接里。
- SSH 密钥、登录信息和令牌保存在保险库里，用初始化时设定的主口令封存；面板只显示名字和类型。
- 客户端以普通账户运行，`nclient` 拒绝 root。中枢只在安装被控端时通过 SSH 登录设备，之后不再主动连接设备。

<img src="images/web/warning_zh.webp" width="100%" alt="安全" />

## 我为什么做它

<table>
<tr>
<td width="50%" align="center"><img src="images/web/panel_0.webp" width="220" alt="微子的狼面对一道网络屏障" /><p><b>最先卡住的，是连不上工具。</b></p></td>
<td width="50%" align="center"><img src="images/web/panel_5.webp" width="220" alt="狼在外面用笔记本，连不回家里的网络" /><p><b>我出门旅行，工作站只能待家里。</b></p></td>
</tr>
<tr>
<td align="center"><img src="images/web/panel_4.webp" width="220" alt="狼被一堆电脑和缠在一起的线包围" /><p><b>单台机器都不难伺候，全凑一块儿就难了。</b></p></td>
<td align="center"><img src="images/web/panel_2.webp" width="220" alt="狼在整理越来越多的硬盘" /><p><b>数据是悄悄长起来的。</b></p></td>
</tr>
<tr>
<td align="center"><img src="images/web/panel_3.webp" width="220" alt="Git、SSH、文件和容器的图标各自散落在狼周围" /><p><b>每样东西都能用，只是各住各的。</b></p></td>
<td align="center"><img src="images/web/panel_1.webp" width="220" alt="狼夹在两个各自独立的 AI 接口之间" /><p><b>我受够了到处复制同一把 key。</b></p></td>
</tr>
</table>

<details>
<summary><b>架构与开发</b></summary>

<img src="images/web/architecture_zh.svg" width="100%" alt="架构" />

| 目录      | 内容                                                                                                                   |
| --------- | ---------------------------------------------------------------------------------------------------------------------- |
| `hub/`    | `neutrino_hub` 包：`modules/` 每个功能一个模块，`web/` FastAPI 面板，`cli/` 全部 `nhub` 子命令，`frontend/` React 源码 |
| `agent/`  | `neutrino_agent` 包：纯标准库，Linux，root，无窗口                                                                     |
| `client/` | `neutrino_client` 包：托盘和窗口，`packaging/` 里是 deb、rpm、msi、pkg 的构建脚本                                      |

</details>

## 致谢

- [Xray-core](https://github.com/XTLS/Xray-core)：代理内核，透明代理和分流都由它执行
- [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)：AI 网关，把订阅账号和 API 密钥合成一个端点
- [cpa-usage-keeper](https://github.com/Willxup/cpa-usage-keeper)：网关的用量记录
- [NetBird](https://github.com/netbirdio/netbird)：带管理面的虚拟网
- [EasyTier](https://github.com/EasyTier/EasyTier)：去中心化的虚拟网
- [cc-switch](https://github.com/SaladDay/cc-switch-cli)：在客户端上切换 Claude Code、Codex 和 Gemini CLI 的配置
- [RustDesk](https://github.com/rustdesk/rustdesk)：远程桌面的主机和查看器
- [Gitea](https://github.com/go-gitea/gitea)：私有 git 服务器
- [Samba](https://www.samba.org/)：SMB 共享
- [Podman](https://github.com/containers/podman)：容器运行时，声明的容器成为 Quadlet 单元
- [OpenZFS](https://github.com/openzfs/zfs)：存储池和数据集
- [dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html)：局域网的 DHCP 和 DNS
- [hostapd](https://w1.fi/hostapd/)：无线接入点
- [v2fly geodata](https://github.com/v2fly/domain-list-community)：分流用的域名和 IP 列表

Claude Code 和 ChatGPT 参与了编写；每个版本发布前作者都逐项审阅。

## 许可证

[MIT](LICENSE)。

<div align="center">

<img src="images/web/outro.webp" width="100%" alt="Neutrino" />

# 让创造重新变得有趣。

少花点时间维护环境。<br/>
多花点时间，做当初让你搭起这套环境的事。

</div>
