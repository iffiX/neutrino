---
title: nhub 命令
---

# nhub 命令

`nhub` 是 hub 的命令行入口，装在 hub 这台机器上。除 `run` 和 `scan-secrets` 外，每个子命令都要 root；不以 root 运行时它打印带 `sudo` 的命令并返回 2。没有子命令时打印帮助并返回 2；Ctrl-C 中断时返回 130。

| 子命令         | 参数                                                                                                                                                                              | root | 作用                                                                                        |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------- |
| `setup`        | `--stdin` 从标准输入读一个 JSON 对象作为全部回答；`--json PATH` 从文件读；两者互斥                                                                                                | 是   | 初始化这台机器，只做一次                                                                    |
| `run`          | `--host HOST`、`--port PORT`、`--reload`、`--interface INTERFACE`；`--only-web`、`--only-xray`、`--only-cliproxyapi`、`--only-dnsmasq`、`--only-supplicant`、`--only-dhcpcd` 之一 | 否   | 在前台运行面板，或只运行一个进程；每个 systemd 单元的 `ExecStart` 就是它                    |
| `stop`         | `--interface INTERFACE`；`--only-web`、`--only-cliproxyapi`、`--only-dnsmasq`、`--only-xray`、`--only-router`、`--only-supplicant`、`--only-dhcpcd` 之一                          | 是   | 停下 hub 在这台机器上运行的服务，或只停一个                                                 |
| `apply`        | `--only {router,xray,dnsmasq,cliproxyapi,easytier}` 可重复；`--dry-run` 只渲染并打印；`--skip-apply` 写文件但不重启服务                                                           | 是   | 从 `config/` 渲染每份生成的配置，校验，应用                                                 |
| `unlock`       | 无                                                                                                                                                                                | 是   | 解除面板登录锁定和 fail2ban 的 SSH 封禁                                                     |
| `reset`        | `all` 或 `password`；`--stdin` 从标准输入读新密码                                                                                                                                 | 是   | `password` 设新的面板密码并登出所有会话；`all` 交还网络，`config/` 回到示例，密钥和令牌删除 |
| `vault rekey`  | `--stdin` 从标准输入读新口令                                                                                                                                                      | 是   | 把数据密钥重新封存在新的主口令下，已加密的内容不变                                          |
| `scan-secrets` | `--staged` 只查暂存区；`--history` 查每个提交的每个对象；`--no-entropy` 跳过高熵规则；`--no-vendor` 跳过 detect-secrets 和 gitleaks；`--quiet` 只打印发现                         | 否   | 开发命令：检查一次提交会带出什么                                                            |

顶层参数有三个。`--version` 打印包版本并退出。`--dev` 把所有根目录放在工作副本的 `hub_dev_root/` 下，并免去 root 检查；它只在源码工作副本里有效，对包安装的 hub 返回错误。`-h` 在每一级打印帮助。
