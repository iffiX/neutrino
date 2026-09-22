---
title: nclient 命令
---

# nclient 命令

`nclient` 是客户端的命令行入口，以普通账户运行；以 root 运行时它返回 `root_refused` 并以 2 退出。没有子命令时打印帮助并返回 2。

作用在一个 hub 上的子命令都带 `--hub`，取值是那个 hub 的名字或者 id。只加入了一个 hub 时可以省略；加入了多个又没有指明时，命令返回 `ambiguous_hub` 并列出名字，指了没加入过的名字则返回 `unknown_hub`。`service` 的每个动作里，`ref` 是 `service list` 输出里条目在所属 hub 下的编号，或者条目的 id。

## 子命令

| 子命令                    | 参数                                                                                                                                                                                                                                                                                       | 作用                                                          |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- |
| `join [link]`             | `link` 是 hub 客户端页发的 `neutrino://enroll` 链接，省略则提示粘贴                                                                                                                                                                                                                        | 加入链接指向的 hub，已加入的 hub 都保留                       |
| `leave`                   | `--hub <name>`                                                                                                                                                                                                                                                                             | 离开一个 hub，并撤销它在这台电脑上的一切                      |
| `status`                  | 无                                                                                                                                                                                                                                                                                         | 打印版本、每个已加入 hub 一行、客户端在不在运行               |
| `gui`                     | `--hidden` 只进托盘不显示窗口                                                                                                                                                                                                                                                              | 运行客户端和它的窗口                                          |
| `quit`                    | 无                                                                                                                                                                                                                                                                                         | 停止正在运行的客户端；没有在运行时返回 `resident_not_running` |
| `service list`            | `--hub <name>` 只列这一个 hub                                                                                                                                                                                                                                                              | 先按 hub、再按类型列出发布的每一条                            |
| `service web open`        | `ref`；`--hub <name>`                                                                                                                                                                                                                                                                      | 在浏览器里打开一条网页服务                                    |
| `service port forward`    | `ref`；`--local-port LOCAL_PORT` 指定本机端口；`--hub <name>`                                                                                                                                                                                                                              | 把一个端口转到本机回环地址                                    |
| `service port unforward`  | `ref`；`--hub <name>`                                                                                                                                                                                                                                                                      | 关闭那条转发                                                  |
| `service file config`     | `ref`；`--path PATH` 必填；`--username USERNAME`；`--hub <name>`                                                                                                                                                                                                                           | 保存一个共享的登录信息和路径，并挂载                          |
| `service file mount`      | `ref`；`--hub <name>`                                                                                                                                                                                                                                                                      | 用保存的登录信息再次挂载                                      |
| `service file unmount`    | `ref`；`--hub <name>`                                                                                                                                                                                                                                                                      | 卸载；保存的登录信息不动                                      |
| `service ai show`         | `--hub <name>` 看这一个 hub 的网关，省略则看出口 hub 的                                                                                                                                                                                                                                    | 这个账户的工具现在指向哪里                                    |
| `service ai apply`        | `hub` 或 `off`。模型参数有 `--claude-default`、`--claude-opus`、`--claude-sonnet`、`--claude-haiku`、`--codex-model` 和 `--gemini-model`；省略则保持现值，传 `''` 回到网关默认。`--codex-effort` 取 `minimal`、`low`、`medium`、`high` 或 `''`。`--hub <name>` 在应用前把这个 hub 设为出口 | `hub` 把工具指向出口 hub 的网关，`off` 还原                   |
| `service desktop connect` | `ref`；`--hub <name>`                                                                                                                                                                                                                                                                      | 在一个共享桌面上打开查看器                                    |

顶层参数：`--version` 打印包版本并退出；`-h` 在每一级打印帮助。`service` 不带类型，或类型不带动作时，打印那一级的帮助并返回 2。

## status 打印什么

```text
neutrino-client 0.3.0
hub        home    https://192.168.100.1:8443  connected  exit
hub        office  https://10.8.0.1:8443       reconnecting: the hub cannot be reached
resident   running
```

加入的每个 hub 一行，顺序就是加入的顺序：名字、地址、通道的状态，以及这条通道最后返回的码。地址是通道最近一次连上的那一个，hub 的其他地址客户端也记着。`exit` 标出 AI 工具指向的那个 hub。最后一行是客户端自己，`running` 或 `not running`。每个 hub 都是 `connected` 且客户端在运行时退出码是 0，否则是 1。
