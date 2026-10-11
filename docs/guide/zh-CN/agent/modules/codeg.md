---
title: Codeg
---

# Codeg

Codeg 是一个网页，里面能用 Claude Code、Codex、Gemini CLI 和另外 12 种 AI 编程工具。这些工具在磁盘上留下的会话，也能导进 Codeg 接着聊。**Codeg** 模块在受管机器上给每个账户运行一个 Codeg 服务端。你在机器上安装的是 Codeg 发布的服务端，版本固定在 0.35.1，许可证是 Apache-2.0。浏览器里运行会话的另一个模块是 [CloudCLI](./cloudcli.md)。

| 系统    | 能运行它的机器                                                  |
| ------- | --------------------------------------------------------------- |
| Linux   | amd64 和 arm64，glibc 2.34 及以上，被控端的安装包也要求这个版本 |
| macOS   | Apple 芯片和 Intel                                              |
| Windows | amd64                                                           |

## 添加实例

1. 在[模块](../modules.md)页的 **Codeg** 标签下，选择 **安装**。软件装到机器上之前，标签读 **安装中**。
1. 选择 **配置**，右边展开 **实例**。
1. 选择 **添加实例**。
1. 在 **账户** 里填机器上一个账户的名字。
1. 可选：改 **端口**。第一个实例用 3101。
1. Windows 机器上，在账户名加 **的 Windows 登录** 那一栏里选这个账户的登录信息。
1. 选择 **应用 Codeg**。

![server 的 Codeg 标签，一个实例在运行](/guide/zh/codeg_panel.webp)

模块的安装程序从 GitHub 取 Codeg 的服务端包，从 nodejs.org 取 Node.js，两个包共约 110 MB。被控端把它们解包到自己的目录里，所有账户共用。国内版改从 npmmirror 取 Node.js，服务端包仍从 GitHub 取，在国内下载慢。Codeg 自己的 **Software Update** 页改不了这份安装，新版本的 Codeg 随新版本的中枢一起来。

每个实例以它的账户身份运行，那一行读 **运行中** 或 **未运行**。Windows 的登录信息先存进 **凭据** 页，再在实例上选它。安装或应用失败时，那一行写出错误码，见故障排查的[模块页上的错误](../../reference/troubleshooting.md#模块页上的错误)。

## 服务的 PATH 里有什么

Codeg 和它启动的 AI 编程工具，都在实例服务的 `PATH` 里找程序，git 也在其中。这个 `PATH` 由模块写好，顺序如下：

| 系统    | `PATH` 的顺序                                                                                               |
| ------- | ----------------------------------------------------------------------------------------------------------- |
| Linux   | 模块自带的 Node.js 目录、`~/.local/bin`、`~/bin`、`/usr/local/bin`、`/usr/bin`、`/bin`                      |
| macOS   | 模块自带的 Node.js 目录、`~/.local/bin`、`~/bin`、`/opt/homebrew/bin`、`/usr/local/bin`、`/usr/bin`、`/bin` |
| Windows | 模块自带的 Node.js 目录、`%APPDATA%\npm`，再接账户自己的 `PATH`                                             |

Codeg 自己用 npm 从 registry.npmjs.org 装 AI 编程工具，装在它的数据目录里。要给这些工具另外装程序时，以这个账户装进上面某个目录。

## 从客户端打开

实例运行起来之后，[服务](../../hub/services.md)页的 **网页** 组里多出一行 **Codeg**，括号里是账户名。客户端要有那台机器的网页权限，权限在[客户端](../../hub/clients.md)页上设。

在客户端的 **网页** 页上选择 **打开**。Codeg 前面是被控端的转发器：它核对客户端带来的一次性令牌，把 Codeg 自己的令牌存进浏览器，浏览器就直接进到工作区，已经登录。浏览器里的这个令牌丢了时，Codeg 显示自己的登录页，上面有一个令牌输入框；这时再选一次 **打开**，令牌就重新存上。

![手机浏览器里 Codeg 的工作区](/guide/zh/app_codeg_workspace.webp)

## 第一次打开

第一次用某个 AI 编程工具开会话时，Codeg 自己用 npm 从 npmjs.org 装这个工具的适配器，国内版也一样，要 1～2 分钟。每个工具的适配器装到哪一步，在 **Settings** 的 **Agents** 页里看。

![Codeg 的 Agents 设置页，Claude Code 的适配器已装好](/guide/zh/app_codeg_agents.webp)

**Claude Code** 和 **Codex** 两项是 ACP 适配器，读的是账户自己的工具设置文件 `~/.claude/settings.json` 和 `~/.codex/config.toml`。[把一台机器的 AI 工具指向网关](./ai_tools.md)里的开关改写的正是这两个文件，所以开关打开后，这两项的请求也走中枢的网关。Codeg 自己的 **Model Providers** 设置写的也是这两个文件，开关开着时，下一次应用再把它们写回去。

## 终端里的会话

你以这个账户在终端里用 Claude Code 或 Codex 聊过的会话，都留在机器的磁盘上，Codeg 能把它们读进来：

1. 在工作区里选择 **Import local sessions**。

   ![Codeg 导入本地会话的列表，列着这个账户的 Claude Code 会话](/guide/zh/app_codeg_import.webp)

1. 打开导进来的会话，在底部输入框里接着聊。

## 内存

一个开着的会话，在机器上占大约 300 MB。页面关掉几分钟后，这个会话的 AI 编程工具退出，内存就释放了。

## 日志

模块页上的输出框显示 Codeg 自己的日志，一天一个文件，`logs/codeg-server.<date>.log`，放在账户的数据目录下：

| 系统    | Codeg 的数据目录                                      |
| ------- | ----------------------------------------------------- |
| Linux   | `~/.local/share/neutrino/agent/codeg/`                |
| macOS   | `~/Library/Application Support/Neutrino/agent/codeg/` |
| Windows | `%LOCALAPPDATA%\Neutrino\agent\codeg\`                |

数据目录里还有 Codeg 的数据库、上传的文件和它装的 AI 编程工具。**卸载** 只删掉服务端包和 Node.js，数据目录留在机器上。
