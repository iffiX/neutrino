---
title: nclient 命令
---

# nclient 命令

`nclient` 在终端里操作 Linux、Windows 或 macOS 上的桌面客户端，以使用者自己的账户运行。下表的子命令顺序与 `nclient --help` 的输出一致。

## 权限

以 root 运行时，每个子命令都打印 `root_refused`，返回 2。所有子命令都不问 `[y/N]`。

## 选择 hub

作用于某一个 hub 的子命令都接受 `--hub`，值是那个 hub 的名字或 id。只加入了一个 hub 时可以省略。加入了多个却没有指定时，命令打印 `ambiguous_hub` 并列出名字；指定的名字没有对应的绑定时，打印 `unknown_hub`。

## 子命令

`service` 各行里的 `<ref>` 是条目在 `nclient service list` 里所属 hub 下的编号，或条目的 id。

| 子命令                                  | 参数                                                                                                                                                                                                                                                 | 作用                                                                                                  |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `nclient join <link>`                   | `<link>` 是 hub **客户端**（Clients）页给出的 `neutrino://enroll/` 链接；省略时在提示符下读入                                                                                                                                                        | 加入链接指向的 hub，已加入的 hub 都保留。                                                             |
| `nclient leave`                         | `--hub <name>`                                                                                                                                                                                                                                       | 离开一个 hub，撤掉它在这台电脑上发布的东西。                                                          |
| `nclient status`                        |                                                                                                                                                                                                                                                      | 打印版本、每个已加入的 hub 一行，以及客户端是否在运行。                                               |
| `nclient gui`                           | `--hidden` 启动时不显示窗口                                                                                                                                                                                                                          | 运行客户端和它的窗口。                                                                                |
| `nclient quit`                          |                                                                                                                                                                                                                                                      | 停下正在运行的客户端。没有在运行的客户端时，打印 `resident_not_running`。                             |
| `nclient terminal <machine>`            | `<machine>` 是机器的名字或 id；`--session <id>` 连回机器保留的一个终端会话；`--hub <name>`                                                                                                                                                           | 在当前终端里打开那台机器的 shell。shell 关闭后返回 0，遇到拒绝返回 1，没有 hub 提供这台机器时返回 2。 |
| `nclient service list`                  | `--hub <name>` 只列那个 hub                                                                                                                                                                                                                          | 按 hub、再按类别打印每个已发布的条目。                                                                |
| `nclient service web open <ref>`        | `--hub <name>`                                                                                                                                                                                                                                       | 在浏览器里打开一个链接。                                                                              |
| `nclient service port forward <ref>`    | `--local-port <port>` 是优先使用的本机回环端口；`--hub <name>`                                                                                                                                                                                       | 把一个端口转发到这台电脑的回环地址。                                                                  |
| `nclient service port unforward <ref>`  | `--hub <name>`                                                                                                                                                                                                                                       | 关闭这个转发。                                                                                        |
| `nclient service file config <ref>`     | `--path <path>`（必填）、`--username <name>`、`--hub <name>`；密码在提示符下输入                                                                                                                                                                     | 保存共享的登录信息和挂载路径，然后挂载。                                                              |
| `nclient service file mount <ref>`      | `--hub <name>`                                                                                                                                                                                                                                       | 用保存的登录信息重新挂载共享。                                                                        |
| `nclient service file unmount <ref>`    | `--hub <name>`                                                                                                                                                                                                                                       | 卸载共享，保存的登录信息留着。                                                                        |
| `nclient service ai show`               | `--hub <name>` 显示那个 hub 的网关                                                                                                                                                                                                                   | 打印这个人的 AI 工具当前指向哪里。                                                                    |
| `nclient service ai apply hub`          | `--claude-default`、`--claude-opus`、`--claude-sonnet`、`--claude-haiku`、`--codex-model`、`--codex-effort`（`minimal`、`low`、`medium`、`high`）、`--gemini-model`；省略的参数保持原选择，`''` 表示网关默认值；`--hub <name>` 让那个 hub 先成为出口 | 让 AI 工具指向出口 hub 的网关。                                                                       |
| `nclient service ai apply off`          |                                                                                                                                                                                                                                                      | 让 AI 工具回到它们自己的配置。                                                                        |
| `nclient service desktop connect <ref>` | `--hub <name>`                                                                                                                                                                                                                                       | 打开查看器，连到一个共享的桌面。                                                                      |

`nclient easytier-daemon` 不出现在 `--help` 里。它是客户端 EasyTier 服务的入口：systemd 和 launchd 以 root 运行它，Windows 服务控制管理器以 SYSTEM 运行它。

## 全局参数

| 参数        | 位置      | 作用                     |
| ----------- | --------- | ------------------------ |
| `--version` | `nclient` | 打印包版本后退出。       |
| `-h`        | 每一级    | 打印这一级的帮助后退出。 |

`nclient` 不带子命令、`nclient service` 不带类别、某个类别不带动作时，打印帮助，返回 2。在 macOS 上，从访达打开应用包等同于运行 `nclient gui`。

## status 打印什么

```text
neutrino-client 0.5.0
hub        home    https://192.168.100.1:8443  connected  exit
hub        office  https://10.8.0.1:8443       reconnecting: the hub cannot be reached
resident   running
```

每个 hub 一行，依次是 hub 的名字、通道上次连上的地址、通道的状态，以及这条通道最后返回的错误码。`exit` 标出这个人的 AI 工具指向的 hub。最后一行是客户端自己，`running` 或 `not running`。所有 hub 都是 `connected` 且客户端在运行时返回 0，否则返回 1。
