---
title: nclient 命令
---

# nclient 命令

在终端里操作桌面客户端用 `nclient`，它在 Linux、Windows 和 macOS 上以使用者自己的账户运行。子命令按 `nclient --help` 的顺序排列。

## 权限

以 root 运行时，除了两个服务入口，每个子命令都打印 `root_refused` 的说明，返回 2。`nclient leave` 离开前问一次 `[y/N]`，`--yes` 跳过；没有终端时打印一行说明，返回 1。

这台电脑上另一个账户的客户端在运行时，`nclient gui` 直接退出。除 `gui` 和 `quit` 以外的子命令打印 `client_held` 的说明，写出那个账户，返回 1。

## 选择中枢

`leave`、每个 `terminal` 子命令和每个 `service` 子命令都接受 `--hub <name>`，值是中枢的名字或 id，只加入了一台时可以省略；下表不再列它。`service list` 不带它时列出全部中枢。加入了多台却没指定时，打印 `ambiguous_hub` 并列出名字；名字对不上绑定时，打印 `unknown_hub`。

## 子命令

`terminal` 各行里的 `<machine>` 是机器的名字或 id，`<session-id>` 是会话 id 或它开头的几位。`service` 各行里的 `<ref>` 是条目在 `nclient service list` 里的编号，或条目的 id。

| 子命令                                            | 参数                                                                                   | 作用                                                                                                                                                                                                                                       |
| ------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `nclient join <link>`                             | `<link>` 是中枢 **客户端** 页给出的 `neutrino://enroll/` 链接，省略时在提示符下粘贴    | 加入链接指向的中枢，已加入的中枢都保留。                                                                                                                                                                                                   |
| `nclient leave`                                   | `--yes`                                                                                | 离开一台中枢，撤掉它在本机的转发、挂载和查看器。                                                                                                                                                                                           |
| `nclient status`                                  | `--json` 打印一个 JSON 对象                                                            | 打印版本、每台中枢一行，以及客户端是否在运行。                                                                                                                                                                                             |
| `nclient gui`                                     | `--hidden` 启动时不显示窗口                                                            | 运行客户端和它的窗口。                                                                                                                                                                                                                     |
| `nclient quit`                                    |                                                                                        | 停下正在运行的客户端；没在运行时打印 `resident_not_running` 的说明。                                                                                                                                                                       |
| `nclient terminal list`                           | `--json` 打印一个 JSON 对象                                                            | 列出每台在线的机器和它保留的会话：机器、会话 id 的前 8 位、标题、账户、谁打开的、是不是本机打开的、是否持久、是否共享、连着几个窗口。返回 0；正在运行的客户端没有回应时返回 1。                                                            |
| `nclient terminal open <machine>`                 | `--persistent` 让新会话一开就持久，`--shared` 让它一开就共享                           | 在当前终端里新开那台机器的 shell。shell 关闭后返回 0，拒绝返回 1，没有中枢提供这台机器返回 2。                                                                                                                                             |
| `nclient terminal attach <machine> <session-id>`  |                                                                                        | 连回那台机器保留的一个会话，先显示最近的输出；只能连本机开的或共享的会话。返回值同 `open`，机器上没有这个会话时也返回 2。                                                                                                                  |
| `nclient terminal exec <machine> -- <command>`    | `<command>` 是要运行的程序和它的参数；`--tty` 开一个伪终端，给 `top`、`vim` 这类程序用 | 在那台机器上运行一条命令。本机的 stdin 原样送过去，远程的 stdout 和 stderr 分别写到本机的 stdout 和 stderr；stdin 和 stdout 可以是文件或管道。返回远程命令的退出码；中枢、被控端或客户端自己拒绝时返回 125，没有中枢提供这台机器返回 126。 |
| `nclient terminal persist <machine> <session-id>` | `--on` 或 `--off`，二选一                                                              | 让会话在最后一个窗口关掉后仍然保留，或取消保留。成功返回 0，拒绝返回 1，机器上没有这个会话返回 2。                                                                                                                                         |
| `nclient terminal share <machine> <session-id>`   | `--on` 或 `--off`，二选一                                                              | 让对这台机器有终端权限的其他客户端能连进这个会话，或收回；收回时中枢立刻断开它们。返回值同 `persist`。                                                                                                                                     |
| `nclient terminal stop <machine> <session-id>`    |                                                                                        | 结束一个保留的会话，和在面板上结束它相同。返回值同 `persist`。                                                                                                                                                                             |
| `nclient service list`                            |                                                                                        | 按中枢、再按类别打印每个已发布的条目。                                                                                                                                                                                                     |
| `nclient service web open <ref>`                  |                                                                                        | 在浏览器里打开一个网页条目。                                                                                                                                                                                                               |
| `nclient service port forward <ref>`              | `--local-port <port>` 是优先用的本机端口                                               | 把一个端口转发到本机回环地址。                                                                                                                                                                                                             |
| `nclient service port unforward <ref>`            |                                                                                        | 关掉这个转发。                                                                                                                                                                                                                             |
| `nclient service file config <ref>`               | `--path <path>`（必填）、`--username <name>`；密码在提示符下输入                       | 保存共享的登录信息和挂载位置，然后挂载。                                                                                                                                                                                                   |
| `nclient service file mount <ref>`                |                                                                                        | 用保存的登录信息再挂一次共享。                                                                                                                                                                                                             |
| `nclient service file unmount <ref>`              |                                                                                        | 卸载共享，登录信息留着。                                                                                                                                                                                                                   |
| `nclient service ai show`                         |                                                                                        | 打印 AI 工具现在指向哪里。                                                                                                                                                                                                                 |
| `nclient service ai apply hub`                    | 每个工具的模型，见表下                                                                 | 让 AI 工具指向出口中枢的网关。                                                                                                                                                                                                             |
| `nclient service ai apply off`                    |                                                                                        | 让 AI 工具回到原来的配置。                                                                                                                                                                                                                 |
| `nclient service desktop connect <ref>`           |                                                                                        | 打开查看器，连到一个共享的桌面。                                                                                                                                                                                                           |

`nclient terminal <machine>` 不带动作时等于 `open`；机器的名字恰好是动作名时，写在 `open` 后面。会话 id 按前缀匹配，和 git 匹配提交号一样：只匹配到一个就是它；一个都没有时打印 `session_unknown` 的说明，返回 2；匹配到多个时打印全部候选，返回 2。`persist` 和 `share` 只对打开会话的客户端有效，其他客户端打印 `session_not_owned` 的说明，返回 1。

`exec` 不接会话 id，也不开持久或共享的会话。它要中枢在 **客户端** 页给这个客户端打开 **远程命令** 权限，新中枢默认关着。`exec` 把 125 和 126 留给客户端这边的结果，远程命令自己返回的 1 和 2 原样传回，脚本能分清结果来自客户端还是远程命令。

`nclient service ai apply hub` 的参数：`--claude-default`、`--claude-opus`、`--claude-sonnet`、`--claude-haiku`、`--codex-model`、`--codex-effort`（`minimal`、`low`、`medium`、`high`）、`--gemini-model`。省略的不变，`''` 是网关默认；带 `--hub` 时先让那台中枢成为出口。

这台电脑装了被控端时，两条 `nclient service ai apply` 都打印 `ai_tools_managed` 的说明，返回 1；`nclient service ai show` 末尾多一行同样的说明。

`nclient easytier-daemon` 和 `nclient files-daemon` 不在 `--help` 里。前者是客户端 EasyTier 服务的入口，Linux 和 macOS 上以 root 运行，Windows 上以 SYSTEM 运行；后者是 Windows 上 `NeutrinoClientFiles` 服务的入口。

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
hub        hub  https://192.168.100.1:8443  Connected · LAN · 12 ms  exit
resident   running
```

每台中枢一行，以 `hub` 开头，后面是中枢的名字、通道上次连上的地址和状态行。状态行和窗口里那一行相同，用英文写：已连接时带通道走的路和往返时间；等待时写原因和剩下的秒数，例如 `The hub did not answer · retrying in 5 s`。`exit` 标出 AI 工具指向的中枢。最后一行是客户端自己，`running` 或 `not running; open it: nclient gui`。客户端在运行、而且每台中枢都已连接时返回 0，否则返回 1。

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
      "next_round_at": null,
      "reached_through": "lan",
      "rtt_ms": 12,
      "wait_code": null,
      "wait_reason": ""
    }
  ],
  "is_running": true,
  "version": "0.5.0"
}
```

| 字段              | 内容                                                                                                                                              |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `connection`      | `connected`、`connecting`、`waiting`、`replaced` 或 `disabled`                                                                                    |
| `wait_reason`     | `waiting` 时的原因：`hub_silent`、`hub_off_overlay`、`no_network`、`untrusted`、`admission_paused`、`unknown_device`、`too_old` 或 `join_refused` |
| `wait_code`       | 原因背后的拒绝，`{code, params}`，没有时为 `null`                                                                                                 |
| `next_round_at`   | 下一轮拨号的时刻，Unix 秒；没有倒计时时为 `null`                                                                                                  |
| `reached_through` | `lan`、`direct`、`netbird`、`easytier` 或 `relay`                                                                                                 |
| `rtt_ms`          | 最近一次往返的毫秒数，取整；没连着或还没量到时为 `null`                                                                                           |
| `is_exit`         | AI 工具是否指向这台中枢                                                                                                                           |
| `last_error`      | 通道最后一次的错误，`{code, params}`，没有时为 `null`                                                                                             |

客户端没在运行时，`connection`、`wait_reason` 和 `reached_through` 为空，`wait_code`、`next_round_at`、`rtt_ms` 和 `last_error` 为 `null`，`is_running` 为 `false`。

## 终端示例

下面几行依次是：在 `server` 上运行 `uptime`；把本机的 `dump.sql` 交给远程的 `psql`，结果存进本机文件；开一个持久的 shell；列出会话；共享 id 以 `3f2a` 开头的会话，连回去，再收回共享；最后结束这个会话。

```bash
nclient terminal exec server -- uptime
cat dump.sql | nclient terminal exec server -- psql app | tee result.txt
nclient terminal open server --persistent
nclient terminal list
nclient terminal share server 3f2a --on
nclient terminal attach server 3f2a
nclient terminal share server 3f2a --off
nclient terminal stop server 3f2a
```
