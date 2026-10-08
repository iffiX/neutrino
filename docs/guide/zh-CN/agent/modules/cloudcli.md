---
title: CloudCLI
---

# CloudCLI

CloudCLI 是一个跑 AI 编程会话的网页。**CloudCLI** 模块给受管机器上选定的每个账户运行一个实例，客户端选择 **打开**（Open）后直接进到已登录的页面。你在机器上安装的是 npm 包 `@cloudcli-ai/cloudcli`，版本固定在 1.37.3。

| 系统    | 能运行它的机器                    |
| ------- | --------------------------------- |
| Linux   | amd64 和 arm64，glibc 2.28 及以上 |
| Windows | amd64 和 arm64                    |
| macOS   | Apple 芯片和 Intel                |

## 添加实例

1. 在[模块](../modules.md)页的 **CloudCLI** 标签下，选择 **安装**（Install）。
1. 选择 **配置**（Configure）。标签下面随即展开 **实例**（Instances）。
1. 选择 **添加实例**（Add instance）。
1. 在 **账户**（Account）里填机器上一个账户的名字。
1. 可选：改 **端口**（Port）。第一个实例用 3001，之后每个新实例用已占用的最大端口加一。
1. 如果是 Windows 机器，选这个账户的登录信息。那一栏的标题是账户名后接 **的 Windows 登录**（Windows login for）。
1. 选择 **应用 CloudCLI**（Apply CloudCLI）。

![server 的 CloudCLI 标签，一个实例在运行](/guide/zh/cloudcli_panel.webp)

**实例** 下写着 **每个账户一个实例，各用各的端口。**（One instance per account, each on its own port.）。每个实例以它的账户身份运行。Windows 的登录信息存在[凭据](../../hub/credentials.md)页的 **登录信息**（Logins）里。

每个账户第一次应用时，机器以这个账户的身份用 npm 装一次 CloudCLI，装在账户自己的目录里。装的过程中，标签读 **安装中**（installing）。模块的安装程序还取来 Node.js 22，解包到被控端的目录里，所有账户共用一份，系统的 `PATH` 保持原样。安装要访问 nodejs.org、npm 和 GitHub；局域网里的机器经中枢的代理访问它们。

## 服务的 PATH 里有什么

CloudCLI 服务的环境变量全部重新写过，不读登录配置文件。`PATH` 的第一项是 Node 的目录，后面接这些目录：

| 系统    | Node 目录之后                                                 |
| ------- | ------------------------------------------------------------- |
| Linux   | `~/.local/bin`、`~/bin`、`/usr/local/bin`、`/usr/bin`、`/bin` |
| macOS   | `/opt/homebrew/bin`、`/usr/local/bin`、`/usr/bin`、`/bin`     |
| Windows | `%APPDATA%\npm`，再接账户自己的 `PATH`                        |

`PATH` 只列目录，被控端不检查这些目录在不在，也不指定任何工具。CloudCLI 启动的 Claude Code 或 Codex，要由账户自己装在这些目录里。

## 让它的 AI 工具走网关

这个账户的 Claude Code、Codex 和 Gemini 读账户自己的设置文件。要它们改用中枢的 AI 网关，见[把一台机器的 AI 工具指向网关](./ai_tools.md)。

## 从客户端打开

每个运行中的实例，都是[服务](../../hub/services.md)页 **网页**（Web）组里的一行，标题是 **CloudCLI** 加括号里的账户名。

1. 在客户端的 **网页** 页上找到这一行。
1. 选择 **打开**。

实例端口上监听的是被控端的转发器，CloudCLI 本身只在它后面的回环地址上监听。每次 **打开** 都取一个新令牌，60 秒内有效，只能用一次。转发器核对令牌后，用中枢生成的密码登录 CloudCLI，浏览器直接进到已登录的页面。

浏览器不带有效令牌、也没有登录状态时，转发器返回 401。CloudCLI 自己的注册和登录接口也一律返回 401。

## 失败时

| 错误码                           | 原因                                                        |
| -------------------------------- | ----------------------------------------------------------- |
| `cloudcli_node_download_failed`  | CloudCLI 用的 Node.js 没能下载或解包                        |
| `cloudcli_npm_install_failed`    | npm 为这个账户安装 CloudCLI 失败，后面带 npm 输出的最后几行 |
| `cloudcli_native_module_failed`  | better-sqlite3、node-pty 或 bcrypt 的预编译文件没能下载     |
| `cloudcli_install_out_of_memory` | npm 安装时机器的内存用完了；腾出内存后再试                  |
| `cloudcli_port_taken`            | 机器上另一个程序占着这个实例的端口                          |
| `cloudcli_register_failed`       | 这个 CloudCLI 已有一个密码不同的管理员                      |
| `account_unknown`                | 机器上没有这个账户                                          |
| `account_invalid`                | 这个名字在那台机器上不能做账户名                            |
| `account_duplicate`              | 两个实例用了同一个账户                                      |
| `port_invalid`                   | 端口不在 1024～65535 之内                                   |
| `port_duplicate`                 | 两个实例用了同一个端口                                      |
| `token_missing`                  | 中枢没有给实例发密码和令牌密钥                              |
| `credential_missing`             | Windows 上的实例没选登录信息                                |
| `credential_invalid`             | Windows 已经不接受这个账户的登录信息                        |

中枢重置或重装后会生成新密码，而 CloudCLI 里还是旧中枢建的管理员，这就是 `cloudcli_register_failed`。这时被控端让这个实例换一个新的数据库文件，重新启动一次。旧文件原样留在机器上，实例从新文件开始，里面没有以前的记录。
