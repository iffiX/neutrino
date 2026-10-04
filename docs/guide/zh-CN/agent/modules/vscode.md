---
title: VS Code
---

# VS Code

**VS Code** 模块在被控端机器上运行浏览器版 VS Code，每个账户一个实例。桌面客户端把实例的端口转发到自己的 `127.0.0.1`，再打开它。你按微软的许可条款在这台机器上安装 VS Code Server：模块的安装程序取来微软独立版 VS Code CLI 的一个固定构建，由被控端运行。

| 系统    | 能运行它的机器                    |
| ------- | --------------------------------- |
| Linux   | amd64 和 arm64，glibc 2.28 及以上 |
| Windows | amd64                             |
| macOS   | Apple 芯片                        |

## 启用

1. 在[模块](../modules.md)页的 **VS Code** 标签下，选择 **打开并接受条款**（Open and accept the terms）。微软的条款在浏览器新标签页里打开，这一按即记下你在这台机器上接受了条款。按钮随后变为 **已接受条款**（Terms accepted），标签的其余内容出现在它下面。
1. 选择 **安装**（Install）。
1. 选择 **配置**（Configure）。标签下面随即展开 **实例**（Instances）分区。

每台机器只问一次。条款接受之前，中枢拒绝在这台机器上安装、启动或配置 VS Code，返回 `terms_not_accepted`。

![VS Code 标签，一个实例和它的账户](/guide/zh/vscode_panel.webp)

## 添加实例

1. 在 **实例** 下选择 **添加实例**（Add instance）。
1. 在 **账户**（Account）里填机器上一个账户的名字。
1. 可选：改 **端口**（Port）。新实例默认用已占用的最高端口的下一个，从 8000 起。
1. 如果是 Windows 机器，在“这个账户的 **Windows 登录**”（Windows login for）里选它的登录信息。
1. 选择 **应用 VS Code**（Apply VS Code）。机器保存实例并重启它们。

每个实例以它的账户身份运行，它建的文件归这个账户所有。实例那一行写着 **运行中**（running）或 **未运行**（not running）；机器上报原因时，原因写在这一行下面。

## Windows 登录

Windows 要有账户的密码，才能以这个账户启动实例。先在[凭据](../../hub/credentials.md)页的 **登录信息**（Logins）里存好这个账户的用户名和密码，再在实例上选这条登录信息。

账户在 Windows 上改了密码之后，被控端为这个实例上报 `credential_invalid`，实例那一行说 Windows 已经不接受这条登录。到 **凭据** 页更新这条登录信息，或者换一条，再选择一次 **应用 VS Code**。

## 应用时的拒绝

| 错误码               | 原因                         |
| -------------------- | ---------------------------- |
| `account_unknown`    | 机器上没有这个名字的账户     |
| `account_duplicate`  | 两个实例用了同一个账户       |
| `port_duplicate`     | 两个实例用了同一个端口       |
| `port_invalid`       | 端口不在 1024 到 65535 之间  |
| `credential_missing` | Windows 上的实例没选登录信息 |
| `token_missing`      | 保管库锁着，读不出实例的令牌 |

## 从客户端打开

每个运行中的实例，都是[服务](../../hub/services.md)页 **网页**（Web）组里的一行，标题是 VS Code 加账户名。这一行只供查看，能打开实例的只有桌面客户端。在客户端的 **网页** 面板里，这一项的按钮是 **本机打开**（Open locally）。按下后，客户端先把实例端口转发到 `127.0.0.1`，再带上实例令牌在浏览器里打开。Android 应用里这一项是灰色的，带“仅桌面”标记。
