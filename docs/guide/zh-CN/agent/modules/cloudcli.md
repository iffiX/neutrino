---
title: CloudCLI
---

# CloudCLI

CloudCLI 是一个跑 AI 编程会话的网页。**CloudCLI** 模块给受管机器上选定的每个账户运行一个实例，客户端选 **打开** 后直接进到已登录的页面。你在机器上安装的是 npm 包 `@cloudcli-ai/cloudcli`，版本固定在 1.37.3。

| 系统    | 能运行它的机器                    |
| ------- | --------------------------------- |
| Linux   | amd64 和 arm64，glibc 2.28 及以上 |
| Windows | amd64                             |
| macOS   | Apple 芯片和 Intel                |

## 添加实例

1. 在[模块](../modules.md)页的 **CloudCLI** 标签下，选择 **安装**。
1. 选择 **配置**，标签下面展开 **实例**。
1. 选择 **添加实例**。
1. 在 **账户** 里填机器上一个账户的名字。
1. 可选：改 **端口**。第一个实例用 3001，之后每个用已占用的最大端口加一。
1. Windows 机器上，选这个账户的登录信息，那一栏的标题是账户名加 **的 Windows 登录**。
1. 选择 **应用 CloudCLI**。

![server 的 CloudCLI 标签，一个实例在运行](/guide/zh/cloudcli_panel.webp)

每个实例以它的账户身份运行。Windows 的登录信息存在[凭据](../../hub/credentials.md)页。

每个账户第一次应用时，机器以这个账户的身份用 npm 装一次 CloudCLI，装在账户自己的目录里，这时标签读 **安装中**。安装程序还取来 Node.js 22，解包到被控端的目录里，所有账户共用，系统的 `PATH` 不变。安装要访问 nodejs.org、npm 和 GitHub。

## 服务的 PATH 里有什么

CloudCLI 服务的环境变量全部重新写过，不读登录配置文件。`PATH` 的第一项是 Node 的目录，后面接这些目录：

| 系统    | Node 目录之后                                                 |
| ------- | ------------------------------------------------------------- |
| Linux   | `~/.local/bin`、`~/bin`、`/usr/local/bin`、`/usr/bin`、`/bin` |
| macOS   | `/opt/homebrew/bin`、`/usr/local/bin`、`/usr/bin`、`/bin`     |
| Windows | `%APPDATA%\npm`，再接账户自己的 `PATH`                        |

CloudCLI 启动的 Claude Code 或 Codex，要由账户自己装在这些目录里。

## 让它的 AI 工具走网关

这个账户的 Claude Code、Codex 和 Gemini 读账户自己的设置文件。要它们改用中枢的 AI 网关，见[把一台机器的 AI 工具指向网关](./ai_tools.md)。

## 从客户端打开

每个运行中的实例，都是[服务](../../hub/services.md)页 **网页** 组里的一行，标题是 **CloudCLI** 加括号里的账户名。

1. 在客户端的 **网页** 页上找到这一行。
1. 选择 **打开**。

实例端口上监听的是被控端的转发器，CloudCLI 本身只在它后面的回环地址上监听。转发器核对令牌后，用中枢生成的密码登录 CloudCLI。不带有效令牌、也没有登录状态的浏览器，打开的是 401 页。

## 失败时

中枢重置或重装后会生成新密码，CloudCLI 里却还是旧中枢建的管理员。这时被控端让这个实例换一个新的数据库文件，重新启动一次。旧文件留在机器上，新文件里没有以前的记录。

其余原因见[故障排查](../../reference/troubleshooting.md#cloudcli)。
