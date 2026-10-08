---
title: nhub 命令
---

# nhub 命令

`nhub` 是中枢的命令行，随中枢的安装包装上，Linux、macOS 和 Windows 上同名。子命令按 `nhub --help` 的顺序排列。

## 子命令

**root** 一列是要以 root 运行的子命令，Windows 上对应管理员终端。**先确认** 一列是动手前问一次 `[y/N]` 的子命令，`--yes` 跳过提示；标准输入不是终端又没加 `--yes` 时，打印一行说明，不动手。返回值见[退出状态](#退出状态)。

| 子命令              | 参数                                                                                        | root | 先确认 | 作用                                                                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------- | ---- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `nhub setup`        | `--stdin` 或 `--json <path>`，从标准输入或文件读一个 JSON 对象作为全部回答                  | 是   | 否     | 初始化这台机器，只做一次，用浏览器向导或终端问答。                                                                                         |
| `nhub run`          | `--host`、`--port`、`--reload`、`--interface`、`--only-<unit>`                              | 否   | 否     | 在前台运行一个中枢进程，每个 `neutrino_hub_*` 单元运行的就是它。                                                                           |
| `nhub open`         | `--print` 只打印地址；`--start-service`、`--output <path>` 是它自己用的提权步骤             | 否   | 否     | 以当前账户在浏览器里打开面板，没初始化时打开向导。面板没有应答时，先提权启动中枢的服务。                                                   |
| `nhub start`        | `--interface`、`--yes`、`--only-<unit>`                                                     | 是   | 是     | 启动已启用的全部单元，路由在前，面板在后；或只启动一个。                                                                                   |
| `nhub stop`         | `--interface`、`--yes`、`--only-<unit>`                                                     | 是   | 是     | 停下中枢的服务，面板在前，路由在后；或只停一个。模块和虚拟网引擎照常运行，下次开机全部重新启动。                                           |
| `nhub status`       |                                                                                             | 否   | 否     | Linux 上每个单元一行：装没装、在不在运行、启用没有；macOS 和 Windows 上一行。面板在运行时返回 0。                                          |
| `nhub service run`  |                                                                                             | 是   | 否     | Windows 服务管理器启动中枢的入口，从终端运行返回 1。                                                                                       |
| `nhub apply`        | `--only <component>`，可重复；`--dry-run` 只打印渲染结果；`--skip-apply` 写文件但不重启服务 | 是   | 否     | 从 `config/` 渲染每份配置，校验后应用。`<component>` 取 `router`、`xray`、`dnsmasq`、`cliproxyapi` 或 `overlay`。                          |
| `nhub unlock`       |                                                                                             | 是   | 否     | 解除面板的登录锁定和 fail2ban 的全部 SSH 封禁。                                                                                            |
| `nhub reset`        | `all`、`network` 或 `password`；`--stdin` 从标准输入读新密码；`--yes`                       | 是   | 是     | `password` 换面板密码，登出所有会话。`network` 交还网络，不改 `config/`。`all` 交还网络，把 `config/` 换回示例，清掉密码和密钥，停下服务。 |
| `nhub update`       | `--yes`；`--package <file>` 装指定的包文件                                                  | 是   | 是     | 装最新发行版本并做健康检查，新版本不应答时装回原版本；通过后重装本机的被控端。                                                             |
| `nhub vault rekey`  | `--stdin` 从标准输入读新口令                                                                | 是   | 否     | 用新口令重新封存保险库的数据密钥，内容不重新加密。                                                                                         |
| `nhub scan-secrets` | `--staged`、`--history`、`--no-entropy`、`--no-vendor`、`--quiet`                           | 否   | 否     | 检查工作区、暂存区或提交历史里有没有凭据，开发用。                                                                                         |

`--only-<unit>` 只作用于一个单元，取 `router`、`xray`、`dnsmasq`、`cliproxyapi`、`relay`、`web`、`supplicant` 或 `dhcpcd`；`relay` 是 SSH 中继，`nhub run` 没有它。`supplicant` 和 `dhcpcd` 要配 `--interface`。`xray` 只在完整版里有。macOS 和 Windows 上只有一个服务，`start` 和 `stop` 带 `--only-<unit>` 时返回 2。`nhub reset all` 和 `nhub reset network` 在卸载时怎么用，见[卸载](../uninstall.md)。

## 全局参数

| 参数        | 位置                 | 作用                                                               |
| ----------- | -------------------- | ------------------------------------------------------------------ |
| `--version` | `nhub`               | 打印包版本后退出。                                                 |
| `--dev`     | `nhub`，写在子命令前 | 在工作副本的 `hub_dev_root/` 下运行，不查 root；装好的中枢上报错。 |
| `-h`        | 每一级               | 打印这一级的帮助后退出。                                           |

## 退出状态

| 退出状态 | 含义                                                                        |
| -------- | --------------------------------------------------------------------------- |
| 0        | 完成，或无事可做。                                                          |
| 1        | `[y/N]` 回答了 no，或某一步失败。                                           |
| 2        | 权限不够；`nhub` 或 `nhub reset` 没带目标；这台机器或这种安装方式下做不了。 |
| 130      | 运行中按了 Ctrl-C。                                                         |
