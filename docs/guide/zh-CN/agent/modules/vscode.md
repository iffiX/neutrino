---
title: VS Code
---

# VS Code

**VS Code** 模块在受管机器上运行浏览器里的 VS Code，每个账户一个实例。你按微软的许可条款在这台机器上安装 VS Code Server：模块的安装程序取来微软独立版 VS Code CLI 的一个固定构建，由被控端运行。

| 系统    | 能运行它的机器                    |
| ------- | --------------------------------- |
| Linux   | amd64 和 arm64，glibc 2.28 及以上 |
| Windows | amd64                             |
| macOS   | Apple 芯片和 Intel                |

## 启用

1. 在[模块](../modules.md)页的 **VS Code** 标签下，选择 **打开并接受条款**（Open and accept the terms）。
1. 选择 **安装**（Install）。
1. 选择 **配置**（Configure）。标签下面随即展开 **实例**（Instances）。

第一步在浏览器新标签页里打开微软的条款，这一按就记下你在这台机器上接受了条款。按钮随后变成 **已接受条款**（Terms accepted），标签的其余部分出现在它下面。每台机器只接受一次。接受之前，中枢拒绝在这台机器上安装、启动或配置 VS Code，返回 `terms_not_accepted`。

## 添加实例

1. 在 **实例** 下选择 **添加实例**（Add instance）。
1. 在 **账户**（Account）里填机器上一个账户的名字。
1. 可选：改 **端口**（Port）。新实例默认用已占用的最大端口加一，从 8000 起。
1. 如果是 Windows 机器，选这个账户的登录信息。那一栏的标题是账户名后接 **的 Windows 登录**（Windows login for）。
1. 选择 **应用 VS Code**（Apply VS Code）。机器保存实例并重启它们。

![中枢所在机器上的 VS Code 标签，一个实例在运行](/guide/zh/vscode_panel.webp)

每个实例以它的账户身份运行，它建的文件归这个账户所有。实例那一行写着 **运行中**（running）或 **未运行**（not running）；机器上报了原因时，原因写在这一行下面。

## Windows 登录

Windows 要有账户的密码，才能以这个账户启动实例。先在[凭据](../../hub/credentials.md)页的 **登录信息**（Logins）里存好这个账户的用户名和密码，再在实例上选这条登录信息。

账户在 Windows 上改了密码之后，被控端为这个实例上报 `credential_invalid`。到 **凭据** 页更新这条登录信息，或者换一条，再选择一次 **应用 VS Code**。

## 应用时的拒绝

| 错误码               | 原因                         |
| -------------------- | ---------------------------- |
| `account_unknown`    | 机器上没有这个名字的账户     |
| `account_duplicate`  | 两个实例用了同一个账户       |
| `port_duplicate`     | 两个实例用了同一个端口       |
| `port_invalid`       | 端口不在 1024～65535 之内    |
| `credential_missing` | Windows 上的实例没选登录信息 |
| `token_missing`      | 中枢没有给实例发连接令牌     |

## 让它的 AI 工具走网关

实例所属账户的 Claude Code、Codex 和 Gemini 能改用中枢的 AI 网关，在模块页的全局配置里打开，见[把一台机器的 AI 工具指向网关](./ai_tools.md)。

## 从客户端打开

每个运行中的实例，都是[服务](../../hub/services.md)页 **网页**（Web）组里的一行，标题是 **VS Code** 加括号里的账户名。实例只在所在机器的回环地址上监听，浏览器直接打开这一行的地址是打不开的。在客户端的 **网页** 页上选择 **打开**（Open），客户端经中枢建一个转发，带上新取的令牌在浏览器里打开实例。桌面客户端和 Android 应用都能打开它。
