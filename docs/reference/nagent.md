# nagent 命令

`nagent` 是被控端自带的命令，三个系统同名。系统无法连接中枢时，你可以在这个系统上用它查明原因，再重新加入。

下面的命令都在被控端所在的系统上运行。在 Linux 和 macOS 上，前面加 `sudo`；在 Windows 上，打开管理员终端再运行，不用写 `sudo`。权限不够时，命令打印原因和要运行的那一行，并返回 2。

```bash
nagent status
```

```text
nagent status needs root (it asks the agent over its root-only control socket):
    sudo nagent status
```

## 查看状态

如果系统无法连接中枢，先运行 `sudo nagent status`。正常时的输出如下，返回值是 0。

```bash
sudo nagent status
```

```text
neutrino-agent 0.6.0
hub        tcp://192.168.1.20:8443
binding    486e750d56454a11b1e71d7179789450
service    running
heartbeat  ok. The service holds its session to the hub
```

各行的含义如下。

| 行          | 含义                              |
| ----------- | --------------------------------- |
| 第一行      | 被控端的版本                      |
| `hub`       | 这个系统加入的中枢的地址          |
| `binding`   | 这个系统在中枢上的编号            |
| `service`   | 被控端的服务是否在运行            |
| `heartbeat` | 和中枢的连接情况，`ok` 表示已连接 |

不正常时返回 1，输出分别显示三种情况：没有加入中枢、服务没有运行、无法连接中枢。无法连接中枢时，`heartbeat` 这一行显示一个代码，含义和处理方法如下。详细步骤见[故障排查](/reference/troubleshooting)。

| 代码                    | 含义                                                    | 处理方法                                                       |
| ----------------------- | ------------------------------------------------------- | -------------------------------------------------------------- |
| `hub_untrusted`         | 中枢的密钥对不上，通常是中枢重置或者重新安装过          | 在面板生成新链接，运行 `sudo nagent join`                      |
| `hub_key_missing`       | 这份绑定来自 0.5                                        | 用新链接运行 `sudo nagent join`，见[从 0.5 升级](/hub/upgrade) |
| `binding_unknown`       | 中枢已没有这个系统的记录，通常是你在面板上按过 **忘记** | 用新链接运行 `sudo nagent join`                                |
| `replaced`              | 另一个会话占用了这份绑定                                | 重启服务，或者用新链接加入                                     |
| `hub_unreachable`       | 无法连接中枢                                            | 检查这个系统到中枢的网络，防火墙要放行连接端口                 |
| `protocol_too_old`      | 被控端版本太旧                                          | 到它的页面按 **更新被控端**                                    |
| `protocol_too_new`      | 中枢版本太旧                                            | 先更新中枢                                                     |
| `control_unavailable`   | 中枢正忙，没有应答                                      | 等待，被控端会自动重新连接                                     |
| `transport_unavailable` | 被控端的传输程序缺失或者损坏                            | 重新安装被控端                                                 |

## 加入和离开

要把这个系统加入中枢，先到面板 **被控端** 页按 **用链接添加**，生成一个链接。把链接写在单引号里，运行下面的命令。

```bash
sudo nagent join '<链接>'
```

也可以不写链接，命令会提示你粘贴。加入后，系统恢复到面板上原来那一行，名字和设置都保留。

如果这个系统已经加入过其他中枢，命令显示 `this machine is bound to ...; replace it? [y/N]`。回答 `y` 就替换成新的中枢，加 `--yes` 就不显示。

要离开中枢，运行 `sudo nagent leave`。这条命令删除绑定，保留被控端和服务。没有绑定时，这条命令返回 1。

## 全部命令

下面的顺序和 `nagent -h` 相同。

| 命令                       | 作用                                                                 | 参数                    |
| -------------------------- | -------------------------------------------------------------------- | ----------------------- |
| `nagent join [<链接>]`     | 加入链接指定的中枢                                                   | `--yes`：替换已有的绑定 |
| `nagent leave`             | 离开中枢，删除绑定，保留被控端和服务                                 | `--yes`                 |
| `nagent status`            | 打印版本、绑定的中枢、服务和连接情况                                 | 没有                    |
| `nagent sync`              | 立即向中枢发送上报。服务没有运行或者没有绑定时返回 1                 | 没有                    |
| `nagent start`             | 启动被控端的服务                                                     | `--yes`                 |
| `nagent stop`              | 停止服务，保留绑定，下次开机时会重新启动                             | `--yes`                 |
| `nagent run`               | 在前台运行，由 systemd 和 macOS 的 LaunchDaemon 调用，不需要手动运行 | 没有                    |
| `nagent service run`       | Windows 服务管理器调用的入口，不需要手动运行                         | 没有                    |
| `nagent service uninstall` | 删除被控端和应用添加的服务、计划任务和防火墙规则                     | `--yes`                 |
| `nagent answer`            | 由被控端调用，不需要手动运行                                         | `--prompt`、`--answer`  |
| `nagent step-down`         | 由被控端调用，不需要手动运行                                         | `--uid`、`--gid`        |

`nagent service uninstall` 会保留共享、账户和应用数据。安装包卸载时会自动运行它，升级时不运行。macOS 没有卸载程序，所以这条命令也会删除被控端，见[卸载](/hub/uninstall)。

## 权限、确认和返回值

除了 `--version`、`nagent answer`、`nagent step-down`，其他命令都需要管理员权限。

`nagent leave`、`nagent start`、`nagent stop`、`nagent service uninstall` 先显示 `[y/N]`，加 `--yes` 就不显示。`nagent join` 只在已经绑定中枢时才显示。没有终端又没有加 `--yes` 时，命令只打印一行说明，不执行任何操作。

不带子命令，或者 `nagent service` 不带动作时，命令打印帮助，并返回 2。
