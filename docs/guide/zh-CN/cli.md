---
title: 命令行
---

# 命令行

三个程序各管一台机器：`nhub` 是中枢，`nagent` 是被控端，`nclient` 是客户端。这一页只列子命令和参数，怎么做某件事在各自的指南页里。

`nhub` 除了 `run` 和 `scan-secrets`，每个子命令都要 root；没加时它打印带 `sudo` 的那一行并返回 2。`nagent` 每个子命令都要 root，各有各的理由。`nclient` 拒绝以 root 运行，那句话是「客户端以个人身份运行，绝不以 root 运行」，返回 2。三个程序都一样：不给子命令就打印帮助并返回 2；`nhub` 被 Ctrl-C 打断时打印它被停止并返回 130。没有 `nagent gui`，没有 `nagent module`，也没有 `nagent service`，面板里还提到第一个，它不存在。`nhub setup` 没有 `--yes`，非交互的写法是 `--stdin` 和 `--json PATH`。`--dev` 只有 `nhub` 有，不在工作副本里跑会被拒绝。

## nhub

顶层参数：`--version`、`--dev`（在工作副本的 `hub_dev_root/` 下运行）、`-h`。

| 子命令         | 参数                                                                                                                                                                                                                                                                             | root | 做什么                                                                                                    |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- | --------------------------------------------------------------------------------------------------------- |
| `setup`        | `--stdin`（从标准输入读一个 JSON 对象，作为全部答案）、`--json PATH`（从这个 JSON 文件读全部答案），二选一                                                                                                                                                                       | 要   | 把这台网关配置一次，见[《快速上手》](./quick-start.md)                                                    |
| `run`          | `--host`（绑定地址）、`--port`（绑定端口，默认取自配置）、`--reload`（源码变动就重启面板）、`--interface`（按接口的引擎用哪个接口）、`--only-web`、`--only-xray`、`--only-cliproxyapi`、`--only-dnsmasq`、`--only-supplicant`、`--only-dhcpcd`（只跑这一个进程，和它的单元一样） | 不要 | 在前台运行控制面板                                                                                        |
| `stop`         | `--interface`，以及 `--only-web`、`--only-cliproxyapi`、`--only-dnsmasq`、`--only-xray`、`--only-router`、`--only-supplicant`、`--only-dhcpcd` 之一（只停这一个服务）                                                                                                            | 要   | 停掉中枢在这台机器上跑的东西                                                                              |
| `apply`        | `--only {router,xray,dnsmasq,cliproxyapi,easytier}`（可重复，默认全部）、`--dry-run`（只渲染并打印，不写不应用）、`--skip-apply`（写文件但不重启任何服务）                                                                                                                       | 要   | 从 `config/` 渲染每一份配置，校验，然后应用，见[《代理》](./proxy.md)和[《网络模式》](./network-modes.md) |
| `unlock`       | 无                                                                                                                                                                                                                                                                               | 要   | 清掉登录锁定和 SSH 封禁，见[《升级与重置》](./upgrade-reset.md)                                           |
| `reset`        | 位置参数 `{all,password}`、`--stdin`（从标准输入读新密码，不再提示）                                                                                                                                                                                                             | 要   | 把这台机器的一部分退回初始状态，见[《升级与重置》](./upgrade-reset.md)                                    |
| `vault rekey`  | `--stdin`（从标准输入读新口令，不再提示）                                                                                                                                                                                                                                        | 要   | 用新的主口令重新包住数据密钥，见[《备份与恢复》](./backup-restore.md)                                     |
| `scan-secrets` | `--staged`（只看下一次提交要带的文件）、`--history`（每个可达提交里的每个 blob，而不是工作树）、`--no-entropy`（跳过噪音最大的高熵规则）、`--no-vendor`（即使装了也跳过 detect-secrets 和 gitleaks）、`--quiet`（只打印命中，不打印汇总）                                        | 不要 | 检查一次提交会带走什么                                                                                    |

`run` 不受 root 检查约束，因为它是每个单元的 `ExecStart`，systemd 是有意让代理核心以非特权身份启动的。单元文件随包发布，不由渲染生成，升级带来的单元变动落在 `apply` 这一步，已经是最新的单元不动它。`vault` 目前只有 `rekey` 一个动作，已封存的东西不会重新加密，变的只是打开它的那把口令。`scan-secrets` 是开发用的命令，和运行这台设备无关。

## nagent

顶层参数：`--version`、`-h`。没有 `--dev`。

| 子命令           | 参数                                                                                                     | 要 root 的理由                               | 做什么                                                                      |
| ---------------- | -------------------------------------------------------------------------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------- |
| `connect [link]` | `link`（hub 给的 `neutrino://enroll` 链接，不写则在提示符下粘贴）、`--yes`（直接顶掉已有绑定，不再询问） | 它写下绑定关系并把服务拉起来                 | 加入链接指向的那个 hub，见[《设备与远程桌面》](./devices-remote-desktop.md) |
| `disconnect`     | 无                                                                                                       | 它移除绑定关系                               | 离开这个 hub                                                                |
| `status`         | 无                                                                                                       | 它要经被控端那个仅 root 可用的控制套接字去问 | 这台机器绑在谁上                                                            |
| `sync`           | 无                                                                                                       | 同上                                         | 立刻向 hub 要一次这台机器的状态                                             |
| `run`            | 无                                                                                                       | 被控端管着这台机器                           | 在前台运行被控端                                                            |
| `rdp start`      | `--user USER`（共享谁的桌面，不写则是执行 sudo 的那个账号，或者屏幕前唯一那个账号）                      | 它要配置这台机器的桌面共享                   | 用 hub 设好的坐席密码共享这个桌面                                           |
| `rdp stop`       | 无                                                                                                       | 同上                                         | 停止共享这个桌面                                                            |

`nagent rdp` 不给动作时打印 rdp 那一层的帮助并返回 2。机器本来就没在共享时，`nagent rdp stop` 打印这台机器的桌面没有共享，返回 0。

## nclient

顶层参数：`--version`、`-h`。

| 子命令                    | 参数                                                                                                                                       | 做什么                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| `connect [link]`          | `link`（hub 给的 `neutrino://enroll` 链接，不写则在提示符下粘贴）、`--yes`（直接顶掉已有绑定）                                             | 加入链接指向的那个 hub，见[《客户端》](./clients.md)                       |
| `disconnect`              | 无                                                                                                                                         | 离开这个 hub                                                               |
| `status`                  | 无                                                                                                                                         | 这个人绑在谁上                                                             |
| `gui`                     | `--hidden`（起来时不显示窗口）                                                                                                             | 运行客户端和它的窗口                                                       |
| `quit`                    | 无                                                                                                                                         | 停掉正在运行的客户端                                                       |
| `service list`            | 无                                                                                                                                         | 列出发布给这个人的每一个条目，按类别分层                                   |
| `service web open`        | `ref`                                                                                                                                      | 在浏览器里打开一条链接                                                     |
| `service port forward`    | `ref`、`--local-port LOCAL_PORT`                                                                                                           | 把一个端口中继到这台机器的回环地址上                                       |
| `service port unforward`  | `ref`                                                                                                                                      | 关掉那条中继                                                               |
| `service file config`     | `ref`、`--path PATH`（必填）、`--username USERNAME`                                                                                        | 保存一个共享的登录信息和路径，并挂上它，见[《客户端》](./clients.md)       |
| `service file mount`      | `ref`                                                                                                                                      | 用存好的登录信息再挂一次                                                   |
| `service file unmount`    | `ref`                                                                                                                                      | 卸载一个共享，存好的登录信息保留                                           |
| `service ai show`         | 无                                                                                                                                         | 这个人的工具当前指向哪里                                                   |
| `service ai apply`        | `{hub,off}`、`--claude-default`、`--claude-opus`、`--claude-sonnet`、`--claude-haiku`、`--codex-model`、`--gemini-model`、`--codex-effort` | `hub` 把工具指向网关，`off` 把它们放回去，见[《AI 网关》](./ai-gateway.md) |
| `service desktop connect` | `ref`                                                                                                                                      | 打开查看器连上一个共享的桌面                                               |

到处出现的 `ref` 是这个条目在 `service list` 里的编号，或者它的 id。五个类别的说明分别是：`web` 发布的链接、`port` 发布的端口、`file` 发布的共享、`ai` AI 网关服务、`desktop` 机群共享的桌面。每个模型参数后面都跟着同一句：不写就保持原样，传 `''` 表示用网关默认值；`--codex-effort` 取 `minimal`、`low`、`medium`、`high` 或者 `''`。

`nclient service` 不给类别时打印 service 那一层的帮助并返回 2，给了类别不给动作时打印那个类别的帮助并返回 2。

## 通用参数

| 参数           | 在哪                                           | 做什么                              |
| -------------- | ---------------------------------------------- | ----------------------------------- |
| `--version`    | 三个都有                                       | 打印包的版本号并退出                |
| `-h`、`--help` | 每个程序的每一层                               | 打印帮助并退出                      |
| `--dev`        | 只有 `nhub`                                    | 在工作副本的 `hub_dev_root/` 下运行 |
| `--stdin`      | `nhub setup`、`nhub reset`、`nhub vault rekey` | 从标准输入读那份秘密，不再提示      |
| `--yes`        | `nagent connect`、`nclient connect`            | 直接顶掉已有绑定，不再询问          |
