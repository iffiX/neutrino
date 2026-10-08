---
title: 终端
---

# 终端（Terminal）

**Terminal** 模块设定受管机器上的终端以哪个账户运行、启动哪个 shell 程序。被控端的安装包里带着它，所以每台受管机器都有这个标签，不用安装，也不能卸载。

| 系统    | 能设置的内容                        |
| ------- | ----------------------------------- |
| Linux   | 账户和 shell 程序                   |
| macOS   | 账户和 shell 程序                   |
| Windows | 只有 shell 程序，终端以 SYSTEM 运行 |

## 设置账户和 shell

1. 在[模块](../modules.md)页的 **Terminal** 标签上，选一个 **账户**（Account）。
1. 可选：在 **Shell 程序**（Shell program）里填程序的完整路径，或者选择 **浏览…**（Browse…），在这台机器的文件里选中程序。
1. 选择 **应用终端设置**（Apply terminal）。

![server 的 Terminal 标签，选了一个账户](/guide/zh/modules_terminal_tab.webp)

**账户** 的第一项是 **被控端自己的账户（root；Windows 上是 SYSTEM）**（The agent's own (root; SYSTEM on Windows)），这也是默认值。Windows 机器上 **账户** 是灰的。**Shell 程序** 留空时，用该账户的登录 shell；Windows 上是 PowerShell。为某个账户开的终端，从这个账户的主目录启动，用它自己的环境变量。

之后打开的终端都按新设置运行，面板的[终端](../terminals.md)页和客户端开的都一样。已经打开的终端保持原样，容器里的 shell 也不受影响。

## 拒绝的原因

| 错误码                   | 原因                               |
| ------------------------ | ---------------------------------- |
| `account_unknown`        | 机器上没有这个账户                 |
| `path_invalid`           | shell 程序不是完整路径             |
| `shell_program_unusable` | 机器上没有这个程序，或者它不能运行 |

账户或程序后来从机器上消失时，再开的终端照样关闭，错误码是 `account_unknown` 或 `shell_program_unusable`。终端不改用 root 运行。
