---
title: Terminal
---

# Terminal

**Terminal**（终端）模块决定受管机器上的终端以哪个账户运行、启动哪个 shell 程序。被控端自己的安装包里就带着它，所以每台受管机器都有这个标签，不用安装，也不能卸载。

| 系统    | 能设置的内容                        |
| ------- | ----------------------------------- |
| Linux   | 账户和 shell 程序                   |
| macOS   | 账户和 shell 程序                   |
| Windows | 只有 shell 程序，终端以 SYSTEM 运行 |

## 设置账户和 shell

1. 在[模块](../modules.md)页的 **Terminal** 标签上，选一个**账户**（Account）。默认是**被控端自己的账户（root；Windows 上是 SYSTEM）**。
1. 可选：在 **Shell 程序**（Shell program）里填程序的完整路径，或者点**浏览…**（Browse…），在这台机器的文件里点选程序。
1. 点**应用终端设置**（Apply terminal）。

**Shell 程序**留空时，用的是该账户的登录 shell：macOS 上是 `zsh`，Windows 上是 PowerShell。为某个账户开的终端，从这个账户的主目录启动，用它自己的环境变量。

之后打开的终端都按这些设置来，不管是面板的[终端](../terminals.md)页还是客户端开的。已经打开的终端保持原样，容器里的 shell 也不受影响。

## 拒绝的原因

| 代码                     | 原因                               |
| ------------------------ | ---------------------------------- |
| `account_unknown`        | 机器上没有这个账户                 |
| `path_invalid`           | shell 程序不是完整路径             |
| `shell_program_unusable` | 机器上没有这个程序，或者它不能运行 |

如果账户或程序后来从机器上没了，再开终端时同样会以 `account_unknown` 或 `shell_program_unusable` 关闭，不会改用 root。
