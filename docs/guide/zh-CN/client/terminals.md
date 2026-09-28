---
title: 终端
---

# 终端

客户端的终端是 hub 管理的某台机器上的 shell，在本机自己的终端程序里打开。客户端的权限里有终端时，hub 为每台受管机器提供一个。

## 从窗口打开

1. 打开 **终端**（Terminals）标签。
1. 在所属 hub 下面找到那台机器。
1. 点 **打开终端**（Open terminal）。

Linux 上打开找到的第一个终端程序，先找 `x-terminal-emulator`；Windows 上是 Windows Terminal，没装时用控制台窗口；macOS 上是“终端”应用。

## 从命令行打开

```sh
nclient terminal lepton --hub home
```

机器用名字或 id 指定。两个 hub 下有同名机器时，用 `--hub` 选 hub。调整终端大小，shell 跟着变。shell 结束时退出码是 0，hub 拒绝时是 1，没有 hub 提供这台机器时是 2。

## hub 拒绝时

| 错误码                 | 含义                                   |
| ---------------------- | -------------------------------------- |
| `permission_denied`    | hub 的客户端页不允许这个客户端打开终端 |
| `agent_offline`        | 那台机器现在没有连到 hub               |
| `unknown_terminal`     | hub 没有提供那台机器的终端             |
| `terminal_app_missing` | 本机找不到终端程序                     |
| `kind_unknown`         | hub 的版本早于 0.4.0，先升级 hub       |
