---
title: code-server
---

# code-server

**code-server** 模块给受管机器上的每个账户运行一个 code-server，机器要是 Linux 或 Mac。code-server 是浏览器版的 VS Code，由 Coder 以 MIT 许可发布。你从 Coder 那里把它装到这台机器上：模块的安装程序取来 Coder 独立发布包的一个固定版本，由被控端解包并运行。

| 系统    | 能运行它的机器                    |
| ------- | --------------------------------- |
| Linux   | amd64 和 arm64，glibc 2.28 及以上 |
| macOS   | Apple 芯片和 Intel                |
| Windows | 不支持，列表里是灰的              |

国内版的安装程序改从中科大镜像取同一个发布包，镜像是 `mirrors.ustc.edu.cn`，用 SHA-256 核对固定的那一版。镜像上已经没有这一版时，安装程序改装镜像上的最新版，只靠 HTTPS 核对。

## 启用

1. 在[模块](../modules.md)页的 **code-server** 标签上，选择 **安装**（Install）。
1. 选择 **配置**（Configure）。标签下面随即展开 **实例**（Instances）。

**实例** 顶上一行写着 **你在这台机器上安装 code-server，它是 Coder 以 MIT 许可发布的编辑器。**（You install code-server, Coder's MIT-licensed editor, on this machine.）。机器上报版本后，这一行后面再跟 **已安装：**（Installed:）和版本号。

## 添加实例

1. 在 **实例** 下选择 **添加实例**（Add instance）。
1. 在 **账户**（Account）里填这台机器上的一个账户名。
1. 可选：改 **端口**（Port）。第一个实例用 8443，之后每个新实例用已占用的最大端口加一。
1. 选择 **应用 code-server**（Apply code-server）。机器保存实例，为每个账户启动 code-server。

每个实例以它的账户身份运行，它建的文件归这个账户所有。设置和扩展放在这个账户主目录下 code-server 自己的文件夹里。实例那一行写着 **运行中**（running）或 **未运行**（not running）；机器上报了原因时，原因写在这一行下面。

端口是被控端的转发器在机器回环地址上监听的端口，和中枢自己的 8443 端口无关。code-server 本身监听一个套接字，只有它的账户和 root 能打开。

## 扩展

编辑器从 Open VSX 装扩展，这是 code-server 默认的扩展库。Claude Code 和 Codex 的扩展都在上面。和 VS Code 一样，在编辑器的 **扩展**（Extensions）视图里搜索就能装。

## 应用时的拒绝

| 错误码                        | 原因                               |
| ----------------------------- | ---------------------------------- |
| `account_unknown`             | 机器上没有这个名字的账户           |
| `account_invalid`             | 这个名字在那台机器上不能做账户名   |
| `account_duplicate`           | 两个实例填了同一个账户             |
| `port_duplicate`              | 两个实例用了同一个端口             |
| `port_invalid`                | 端口不在 1024～65535 之内          |
| `secret_missing`              | 中枢没有给这个实例发令牌密钥       |
| `code_server_download_failed` | 发布包没能下载或解包               |
| `code_server_port_taken`      | 机器上另一个程序占着这个实例的端口 |

## 让它的 AI 工具走网关

实例所属账户的 Claude Code、Codex 和 Gemini 也能改用中枢的 AI 网关，打开方法见[把一台机器的 AI 工具指向网关](./ai_tools.md)。

## 从客户端打开

每个运行中的实例，都是[服务](../../hub/services.md)页 **网页**（Web）组里的一行，标题是 **code-server** 加括号里的账户名。客户端要有那台机器的网页权限才能打开它，权限在[客户端](../../hub/clients.md)页上设。

在客户端的 **网页** 页上选择 **打开**（Open），客户端经中枢建一个转发，带上新取的令牌在浏览器里打开实例。令牌 60 秒内有效，只能用一次。之后转发器在这个浏览器里设一个登录 cookie，有效期七天；过期后再选一次 **打开**。
