---
title: nclient 命令
---

# nclient 命令

`nclient` 是桌面客户端的命令行，在 Linux、Windows 和 macOS 上以使用者自己的账户运行。下表的子命令按 `nclient --help` 列出的顺序排列。

## 权限

以 root 运行时，除了下文的两个服务入口，每个子命令都打印 `root_refused` 的说明，返回 2。`nclient leave` 离开前问一次 `[y/N]`，带 `--yes` 不问。没有终端时它不提问，打印一行说明加 `--yes` 才离开，返回 1。

这台电脑上另一个账户的客户端在运行时，`nclient gui` 直接退出，不开窗口。除 `gui` 和 `quit` 以外的子命令打印 `client_held` 的说明，写出那个账户，返回 1。

## 选择中枢

作用于一台中枢的子命令都接受 `--hub`，值是那台中枢的名字或 id。只加入了一台中枢时可以省略。`nclient service list` 不带 `--hub` 时列出全部中枢。加入了多台却没指定时，命令打印 `ambiguous_hub` 并列出名字；指定的名字没有对应的绑定时，打印 `unknown_hub`。

## 子命令

`service` 各行里的 `<ref>` 是条目在 `nclient service list` 里所属中枢下的编号，或条目的 id。

| 子命令                                  | 参数                                                                                                                                                                                                                                        | 作用                                                                                                 |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `nclient join <link>`                   | `<link>` 是中枢 **客户端**（Clients）页给出的 `neutrino://enroll/` 链接，省略时在提示符下粘贴                                                                                                                                               | 加入链接指向的中枢，已加入的中枢都保留。                                                             |
| `nclient leave`                         | `--hub <name>`；`--yes` 不问就离开                                                                                                                                                                                                          | 离开一台中枢，撤掉它在这台电脑上的转发、挂载和查看器。                                               |
| `nclient status`                        | `--json` 打印一个 JSON 对象                                                                                                                                                                                                                 | 打印版本、每台已加入的中枢一行，以及客户端是否在运行。                                               |
| `nclient gui`                           | `--hidden` 启动时不显示窗口                                                                                                                                                                                                                 | 运行客户端和它的窗口。                                                                               |
| `nclient quit`                          |                                                                                                                                                                                                                                             | 停下正在运行的客户端；没有客户端在运行时，打印 `resident_not_running` 的说明。                       |
| `nclient terminal <machine>`            | `<machine>` 是机器的名字或 id；`--session <id>` 连回机器保留的一个会话；`--hub <name>`                                                                                                                                                      | 在当前终端里打开那台机器的 shell。shell 关闭后返回 0，遇到拒绝返回 1，没有中枢提供这台机器时返回 2。 |
| `nclient service list`                  | `--hub <name>` 只列那台中枢                                                                                                                                                                                                                 | 按中枢、再按类别打印每个已发布的条目。                                                               |
| `nclient service web open <ref>`        | `--hub <name>`                                                                                                                                                                                                                              | 在浏览器里打开一个网页条目。                                                                         |
| `nclient service port forward <ref>`    | `--local-port <port>` 是优先用的本机回环端口；`--hub <name>`                                                                                                                                                                                | 把一个端口转发到这台电脑的回环地址。                                                                 |
| `nclient service port unforward <ref>`  | `--hub <name>`                                                                                                                                                                                                                              | 关掉这个转发。                                                                                       |
| `nclient service file config <ref>`     | `--path <path>`（必填）、`--username <name>`、`--hub <name>`；密码在提示符下输入                                                                                                                                                            | 保存共享的登录信息和挂载位置，然后挂载。                                                             |
| `nclient service file mount <ref>`      | `--hub <name>`                                                                                                                                                                                                                              | 用保存的登录信息再挂一次共享。                                                                       |
| `nclient service file unmount <ref>`    | `--hub <name>`                                                                                                                                                                                                                              | 卸载共享，保存的登录信息留着。                                                                       |
| `nclient service ai show`               | `--hub <name>` 显示那台中枢的网关                                                                                                                                                                                                           | 打印 AI 工具现在指向哪里。                                                                           |
| `nclient service ai apply hub`          | `--claude-default`、`--claude-opus`、`--claude-sonnet`、`--claude-haiku`、`--codex-model`、`--codex-effort`（`minimal`、`low`、`medium`、`high`）、`--gemini-model`；省略的保持原样，`''` 表示网关默认；`--hub <name>` 先让那台中枢成为出口 | 让 AI 工具指向出口中枢的网关。                                                                       |
| `nclient service ai apply off`          |                                                                                                                                                                                                                                             | 让 AI 工具回到原来的配置。                                                                           |
| `nclient service desktop connect <ref>` | `--hub <name>`                                                                                                                                                                                                                              | 打开查看器，连到一个共享的桌面；这个桌面已开着查看器时打印 `rdp_viewer_open` 的说明。                |

这台电脑装了被控端时，`nclient service ai apply hub` 和 `nclient service ai apply off` 都打印 `ai_tools_managed` 的说明，返回 1，AI 工具改由中枢面板设置。`nclient service ai show` 照常打印，末尾多一行同样的说明。

`nclient easytier-daemon` 和 `nclient files-daemon` 不出现在 `--help` 里。前者是客户端 EasyTier 服务的入口，Linux 和 macOS 上以 root 运行，Windows 上以 SYSTEM 运行；后者是 Windows 上 `NeutrinoClientFiles` 服务的入口。

## 全局参数

| 参数        | 位置      | 作用                     |
| ----------- | --------- | ------------------------ |
| `--version` | `nclient` | 打印包版本后退出。       |
| `-h`        | 每一级    | 打印这一级的帮助后退出。 |

`nclient` 不带子命令、`nclient service` 不带类别、类别不带动作时，打印帮助，返回 2。在 macOS 上，从访达打开应用等同于运行 `nclient gui`。

## status 打印什么

```bash
nclient status
```

```text
neutrino-client 0.5.0
hub        hub  https://192.168.100.1:8443  connected · LAN · 12 ms  exit
resident   running
```

每台中枢一行，以 `hub` 开头，后面依次是中枢的名字（这个例子里中枢就叫 `hub`）、通道上次连上的地址、通道的状态。已连接的中枢在状态后面带两个标签，通道走的路和往返时间；还没量到往返时间时只有第一个。其他状态后面跟一个冒号和原因，例如 `down: the hub cannot be reached`。`exit` 标出 AI 工具指向的中枢。最后一行是客户端自己，`running` 或 `not running`。客户端在运行、而且每台中枢都是 `connected` 时返回 0，否则返回 1。

带 `--json` 时打印一个对象，返回值相同：

```json
{
  "hubs": [
    {
      "connection": "connected",
      "gateway_url": "https://192.168.100.1:8443",
      "hub_id": "f3c1",
      "hub_name": "hub",
      "is_exit": true,
      "last_error": null,
      "reached_through": "lan",
      "rtt_ms": 12
    }
  ],
  "is_running": true,
  "version": "0.5.0"
}
```

| 字段              | 内容                                                                                         |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `connection`      | `connected`、`connecting`、`down`、`pending`（已加入，还没连上过）、`replaced` 或 `disabled` |
| `reached_through` | 通道走的路：`lan`、`direct`、`netbird`、`easytier` 或 `relay`                                |
| `rtt_ms`          | 最近一次往返的毫秒数，取整；中枢没连着或还没收到第一个 `pong` 时为 `null`                    |
| `is_exit`         | AI 工具是否指向这台中枢                                                                      |
| `last_error`      | 通道最后一次的错误，`{code, params}`，没有时为 `null`                                        |

客户端没在运行时，`connection` 和 `reached_through` 为空，`rtt_ms` 和 `last_error` 为 `null`，`is_running` 为 `false`。
