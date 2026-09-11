<div align="center">

<img src="images/web/banner.webp" width="100%" alt="Neutrino" />

# 家里一台常开的中枢，管住你的所有小玩意。

[English](README.md) · **中文**

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![version](https://img.shields.io/badge/version-0.2.0-0891b2.svg)](https://github.com/iffiX/neutrino/releases)
[![hub](https://img.shields.io/badge/hub-Linux%20x86--64%20%C2%B7%20ARM64-555.svg)](#什么跑在哪里)
[![agent](https://img.shields.io/badge/agent-Linux-555.svg)](#什么跑在哪里)
[![client](https://img.shields.io/badge/client-Linux%20%C2%B7%20Windows-555.svg)](#什么跑在哪里)

**[安装](#安装)** · **[文档](https://iffix.github.io/neutrino/zh-CN/)** · [展示](#一次发布处处可用) · [面板](#面板) · [缘起](#我为什么做它)

微子能穿透一切，却什么也不碰。<br/>
障碍都还在，只是再也碍不着你了。

</div>

微子是一套自托管的控制面，管你自己名下的机器：一个中枢、若干被控端、若干客户端。在中枢上发布一次，你每台机器的客户端窗口里就多一个按钮，打开、连接、配置加应用、挂载、连接。中枢可以是一台刷好的电视盒子或者树莓派，NAS、工作站和显卡机器各干各的活，装一个被控端就行。

中枢和被控端只跑在 Linux 上，客户端跑 Linux 和 Windows，macOS 这三个包都不支持。中枢自己不承载任何模块，三个包共用一个版本号。

<div align="center">

<img src="images/web/one_click.webp" width="100%" alt="面板的服务页与客户端窗口" />

左边在中枢的服务页发布，右边是同一台机器上客户端窗口里的按钮。

</div>

## 安装

### 中枢

```bash
sudo apt install ./neutrino-hub_0.2.0_amd64.deb && sudo nhub setup
```

向导一共六屏：语言、密码与口令、形态、网口、代理、就绪。选服务器形态时，机器上每个网口都保留现有地址，局域网不动。装完面板在 `http://<hub>:8080`。

### 被控端

在面板的设备页点「按链接添加」，链接五分钟内有效，然后在那台机器上运行：

```bash
sudo nagent connect '<链接>'
```

也可以在设备抽屉里让中枢通过 SSH 把被控端装过去。

### 客户端

在面板的客户端页点「新建客户端链接」，把链接粘进客户端窗口。

中枢的 rpm 和 Arch 包、客户端的 deb、rpm 和 msi，都在 [Releases](https://github.com/iffiX/neutrino/releases) 里。

带截图的完整流程见[《快速上手》](https://iffix.github.io/neutrino/zh-CN/quick-start.html)。

## 文档

- [快速上手](https://iffix.github.io/neutrino/zh-CN/quick-start.html)
- [使用指南](https://iffix.github.io/neutrino/zh-CN/overview.html)
- [命令行参考](https://iffix.github.io/neutrino/zh-CN/cli.html)

## 一次发布，处处可用

不用再把同一把 API 密钥抄到每台机器上，不用再记住某个共享挂在哪个地址，不用每次手开一条 SSH 隧道，不用翻聊天记录找 RustDesk ID，也不用一台一台地配代理。

| 面板     | 条目从哪来                       | 客户端上的按钮       |
| -------- | -------------------------------- | -------------------- |
| 网页     | Gitea 模块，或者手动声明         | 「打开」             |
| 端口     | 容器发布的端口，或者手动声明     | 「连接」             |
| AI       | AI 网关                          | 「配置」然后「应用」 |
| 文件     | Samba 模块，或者手动声明         | 「挂载」             |
| 远程桌面 | 面板上不用设，由那台机器自己共享 | 「连接」             |

<div align="center">

|                                                                                        |                                                                                               |                                                                                                |
| -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| <img src="images/screenshots/client_web.webp" width="100%" alt="客户端的网页面板" />   | <img src="images/screenshots/client_ports.webp" width="100%" alt="客户端的端口面板" />        | <img src="images/screenshots/client_ai.webp" width="100%" alt="客户端的 AI 面板" />            |
| <img src="images/screenshots/client_files.webp" width="100%" alt="客户端的文件面板" /> | <img src="images/screenshots/client_desktops.webp" width="100%" alt="客户端的远程桌面面板" /> | <img src="images/screenshots/client_windows.webp" width="100%" alt="Windows 上的同一个窗口" /> |

</div>

- AI 密钥按客户端单独发放，用量按窗口计量，在面板的 AI 页看得到。
- 「配置」通过 cc-switch 把机器上的三个 AI 命令行切到网关，关掉时把它们各自的配置还回去。
- 共享在 Linux 上挂到家目录下，在 Windows 上挂成一个盘符，比如 `N:`。
- 端口转发到本机的 `127.0.0.1:<端口>`，应用照着连就行。
- 远程桌面那一次性的座位密码由中枢保管，界面上从不显示。
- Linux 和 Windows 上是同一个窗口，同样五个面板。

## 面板

| 截图                                                                           | 这一页做的一件事               |
| ------------------------------------------------------------------------------ | ------------------------------ |
| <img src="images/screenshots/dashboard.webp" width="100%" alt="总览页" />      | 总览：中枢此刻在转发什么       |
| <img src="images/screenshots/devices.webp" width="100%" alt="设备页" />        | 设备：用一条链接接入一台机器   |
| <img src="images/screenshots/services.webp" width="100%" alt="服务页" />       | 服务：手动声明一个服务         |
| <img src="images/screenshots/ai_accounts.webp" width="100%" alt="AI 账号页" /> | AI：订阅账号登录一次           |
| <img src="images/screenshots/proxy.webp" width="100%" alt="代理页" />          | 代理：从分享链接加一个出口节点 |
| <img src="images/screenshots/samba.webp" width="100%" alt="Samba 页" />        | Samba：发布一个共享            |

<div align="center">

|                                                                                            |                                                                                        |                                                                                     |                                                                                           |
| ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| <img src="images/screenshots/dashboard_portrait.webp" width="100%" alt="手机上的总览页" /> | <img src="images/screenshots/proxy_portrait.webp" width="100%" alt="手机上的代理页" /> | <img src="images/screenshots/ai_portrait.webp" width="100%" alt="手机上的 AI 页" /> | <img src="images/screenshots/services_portrait.webp" width="100%" alt="手机上的服务页" /> |

</div>

手机宽度下这几页照样能用，路上改一条规则不用开电脑。

## 什么跑在哪里

| 包                | 平台                | 身份                         | 干什么                                                                           |
| ----------------- | ------------------- | ---------------------------- | -------------------------------------------------------------------------------- |
| `neutrino-hub`    | Linux x86-64、ARM64 | root，面板加若干单元         | 路由（xray、nftables、dnsmasq）、AI 网关、虚拟网、发现、中转、客户端、凭据       |
| `neutrino-agent`  | 只有 Linux          | root，无窗口，不监听任何端口 | 在一台机器上承载 Samba、Gitea、Podman、ZFS 和 RustDesk 主机，中枢这台也算        |
| `neutrino-client` | Linux、Windows      | 登录用户，从不是 root        | 一个常驻进程、一个托盘和一个窗口：挂共享、开服务、转端口、连远程桌面、切 AI 工具 |

三个包共用一个版本号，对不上时只会要求升级，不做协商。中枢自己不承载模块，所以那台机器可以很小。

## 安全

<div align="center">

<img src="images/web/warning_zh.webp" width="100%" alt="安全" />

</div>

- 中枢和被控端以 root 运行，客户端从不是 root，它唯一一次提权是挂载共享用的 polkit 助手。
- 面板走 HTTP，从局域网里访问它，或者从你自己的虚拟网上访问。
- 接入链接五分钟过期且只能用一次，通道的 TLS 由链接里的指纹钉住，凭据保险库由初始化时那句口令封存。

## 我为什么做它

微子最初是给我自己的工作站、笔记本和家里几台小机器用的，现在是我的开发环境。

<table>
<tr valign="top">
<td width="50%" align="center"><img src="images/web/panel_0.webp" width="220" alt="微子的狼面对一道网络屏障" /><p><b>最先卡住的，是连不上工具。</b></p></td>
<td width="50%" align="center"><img src="images/web/panel_5.webp" width="220" alt="狼在外面用笔记本，连不回家里的网络" /><p><b>我出门旅行，工作站只能待家里。</b></p></td>
</tr>
<tr valign="top">
<td align="center"><img src="images/web/panel_4.webp" width="220" alt="狼被一堆电脑和缠在一起的线包围" /><p><b>单台机器都不难伺候，全凑一块儿就难了。</b></p></td>
<td align="center"><img src="images/web/panel_2.webp" width="220" alt="狼在整理越来越多的硬盘" /><p><b>数据是悄悄长起来的。</b></p></td>
</tr>
<tr valign="top">
<td align="center"><img src="images/web/panel_3.webp" width="220" alt="Git、SSH、文件和容器的图标各自散落在狼周围" /><p><b>每样东西都能用，只是各住各的。</b></p></td>
<td align="center"><img src="images/web/panel_1.webp" width="220" alt="狼夹在两个各自独立的 AI 接口之间" /><p><b>我受够了到处复制同一把 key。</b></p></td>
</tr>
</table>

<details>
<summary><b>架构</b></summary>

<img src="images/web/architecture_zh.svg" width="100%" alt="架构" />

**设计**

- **唯一事实源**：`config/`；每次改动都是渲染、校验、应用；面板和 `nhub apply` 走同一条路；没有迁移
- **中枢不承载模块**：Samba、Gitea、Podman、ZFS、RustDesk 跑在拥有磁盘或显卡的那台机器的被控端下
- **一条通道**：被控端向中枢开一条 WebSocket，TLS 由接入链接的指纹钉住；中枢从不主动拨号；SSH 只用于安装
- **期望状态**：每台设备一份文档，由 `config/` 组合；被控端连上后比对并应用差异；离线设备的改动被拒绝，不排队
- **发布的服务**：模块产生的条目，加手动声明的条目，推给每个客户端
- **一张虚拟网**：无、NetBird 或 EasyTier；这是 `config/router/network.json` 里的一行，防火墙也读它
- **权限**：中枢和被控端是 root，客户端从不是；客户端唯一一次提权是挂载共享的 polkit 助手
- **一个版本号**：三个包共用；对不上就要求升级

**组件**

- **中枢**：路由（xray、nftables、dnsmasq，三种模式）· AI 网关（CLIProxyAPI，按客户端发密钥，计量）· 虚拟网（NetBird 客户端、EasyTier 引擎）· 面板（FastAPI、React、`/ws/events`）· 保险库
- **被控端**：samba · gitea · podman · zfs · RustDesk 主机 · 终端流与文件流
- **客户端**：托盘与窗口 · 端口转发 · 挂载助手 · cc-switch · RustDesk 查看器

</details>

<details>
<summary><b>开发</b></summary>

**环境**：Python 3.12+、Node 24+、black、pytest。

**命令**

```bash
pip install -e "hub[dev]"
pip install -e agent
pip install -e client
black --check hub agent client
cd hub && pytest -q
cd hub/frontend && npm run build
nhub apply --dry-run
```

**目录**

- `hub/`：中枢包与面板前端
- `agent/`：被控端包
- `client/`：客户端包与它的窗口
- `config/`：运行时的事实源，真文件不入库
- `docs/`：文档站与项目记录
- `packaging/`：三个包的打包线

改代码前先读 [AGENTS.md](AGENTS.md)。

</details>

## 致谢

微子站在这些项目上：[Xray-core](https://github.com/XTLS/Xray-core)、[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)、[cpa-usage-keeper](https://github.com/Willxup/cpa-usage-keeper)、[NetBird](https://netbird.io)、[EasyTier](https://github.com/EasyTier/EasyTier)、[cc-switch](https://github.com/SaladDay/cc-switch-cli)、[RustDesk](https://rustdesk.com)、[Gitea](https://about.gitea.com)、[Samba](https://www.samba.org)、[Podman](https://podman.io)、[OpenZFS](https://openzfs.org)、[dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html)、[hostapd](https://w1.fi/hostapd/)，以及 [v2fly 的 geodata](https://github.com/v2fly)。Claude Code 和 ChatGPT 参与了编码，每个发布版本由作者本人过一遍。

## 许可证

[MIT](LICENSE)。

<div align="center">

<img src="images/web/outro.webp" width="100%" alt="Neutrino" />

# 让创造重新变得有趣。

少花点时间维护环境。<br/>
多花点时间，做当初让你搭起这套环境的事。

</div>
