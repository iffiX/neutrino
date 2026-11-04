# nhub 命令

`nhub` 是微子·中枢自带的命令，随中枢的安装包一起安装。面板打不开时，你可以在中枢所在电脑的终端里用它修复中枢。

下面的命令都在中枢所在的电脑上运行。在 Linux 和 macOS 上，需要管理员权限的命令前面加 `sudo`；在 Windows 上，打开管理员终端再运行，不用写 `sudo`。权限不够时，命令打印要运行的那一行。

每一级命令后面加 `-h` 都能查看帮助，帮助是英文的。

## 常用命令

如果你要查看每个服务是否在运行，运行 `nhub status`。这条命令不需要管理员权限。在 Linux 上每个服务一行，`running, enabled` 表示正在运行并且开机启动，`not installed` 表示这个功能没有打开过。在 macOS 和 Windows 上只有一行。

```bash
nhub status
```

```text
  xray: running, enabled
  router: running, enabled
  transport: running, enabled
  dnsmasq: running, enabled
  web: running, enabled
  cliproxyapi: running, enabled
  netbird: stopped, disabled
  easytier: stopped, disabled
  relay: not installed
  sakurafrp: not installed
  openfrp: not installed
```

每一行对应的服务见[服务的名字](#服务的名字)。

如果你忘了面板地址，运行下面的命令。它只打印地址，不打开浏览器。加 `sudo` 时打印配置里的地址和设置令牌，不加时下面多一行提示。

```bash
nhub open --print
```

```text
http://192.168.1.20:8080/
for the panel's configured address and the setup token, run: sudo nhub open --print
```

如果你忘了面板密码，运行 `sudo nhub reset password`。命令先显示确认提示，你回答 `y` 后再输入新密码。这时所有人都会退出登录，其他设置不变。

如果多次输错密码后面板已锁定，运行 `sudo nhub unlock`。这条命令解除面板的登录锁定和 SSH 封禁。

## 全部命令

下面的顺序和 `nhub -h` 相同。

| 命令                | 作用                                                                 | 参数                                                               |
| ------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `nhub setup`        | 第一次设置这个系统，只运行一次。通常使用浏览器里的向导，不用这条命令 | `--stdin`、`--json <文件>`：读取一个 JSON 文件作为全部答案         |
| `nhub run`          | 在前台运行一个进程，由服务管理器调用，不需要手动运行                 | `--only-<名字>`                                                    |
| `nhub open`         | 用浏览器打开面板，还没有设置时打开向导                               | `--print`：只打印地址                                              |
| `nhub start`        | 启动已启用的全部服务                                                 | `--yes`、`--only-<名字>`、`--interface <网口>`                     |
| `nhub stop`         | 停止中枢运行的服务，下次开机时会重新启动                             | `--yes`、`--only-<名字>`、`--interface <网口>`                     |
| `nhub status`       | 显示每个服务是否在运行                                               | 没有                                                               |
| `nhub service run`  | Windows 服务管理器调用的入口，不需要手动运行                         | 没有                                                               |
| `nhub apply`        | 从 `config/` 重新生成每个配置，校验，再生效                          | `--dry-run`：只生成和校验，不生效。`--skip-apply`、`--only <部分>` |
| `nhub unlock`       | 解除面板登录锁定和 SSH 封禁                                          | 没有                                                               |
| `nhub reset <目标>` | 把一部分恢复到刚安装时的状态，目标见下面                             | `--yes`、`--stdin`                                                 |
| `nhub update`       | 安装最新发行版本，新版本没有应答时恢复旧版本                         | `--yes`、`--package <文件>`：安装这个文件                          |
| `nhub vault rekey`  | 更换保险库口令，旧备份仍然使用旧口令                                 | `--stdin`                                                          |
| `nhub scan-secrets` | 供开发者使用，提交代码前检查是否带有密钥                             | `--staged`、`--history`、`--no-entropy`、`--no-vendor`、`--quiet`  |

全局参数有两个：`--version` 和 `--dev`。

- `--version` 打印版本。
- `--dev` 写在子命令前面，用来在源码目录里运行。

## reset 的目标

`sudo nhub reset` 不写目标时，只列出可以重置的内容，不执行任何操作。下面是实际输出，返回值是 2。

```bash
sudo nhub reset
```

```text
nhub reset <target>, where target is one of:

  all       every module's config, the panel password, and the keys and tokens this box collected; stops the hub's services too
  network   hands the machine's network back (the firewall, the engines, the resolver) and changes no config; removing the package runs it
  password  the panel password, leaving every other setting alone

Nothing was reset.
```

| 目标       | 作用                                                              | 后续操作                                 |
| ---------- | ----------------------------------------------------------------- | ---------------------------------------- |
| `password` | 更换面板密码，所有人退出登录。加 `--stdin` 时从标准输入读取新密码 | 用新密码登录                             |
| `network`  | 把这个系统的网络交还给系统，不修改配置，面板会停止                | 网络恢复后运行 `sudo nhub start`         |
| `all`      | 把配置全部恢复为示例，清除密码和密钥，停止服务                    | 运行 `sudo nhub setup`，或者重新完成向导 |

运行 `nhub reset all` 之后，所有被控端和客户端都要用新链接重新加入，因为中枢密钥已更换。

## 服务的名字

启动和停止时加 `--only-<名字>`，只操作一个服务，比如 `sudo nhub stop --only-web`。这个参数只在 Linux 上提供。`nhub status` 里的名字也是这些。

| 名字                   | 含义                                    |
| ---------------------- | --------------------------------------- |
| `web`                  | 面板                                    |
| `transport`            | 连接端口，客户端和被控端都连接它        |
| `relay`                | SSH 中继                                |
| `sakurafrp`、`openfrp` | SakuraFrp 和 OpenFrp 的 frpc            |
| `cliproxyapi`          | AI 网关                                 |
| `dnsmasq`、`router`    | DNS 和路由                              |
| `xray`                 | 出口程序                                |
| `supplicant`、`dhcpcd` | 按网口运行，还要加 `--interface <网口>` |

`nhub apply --only` 后面可以写 `router`、`dnsmasq`、`cliproxyapi`、`overlay`、`transport`、`xray`。

## 权限、确认和返回值

除了 `nhub status`、`nhub run`、`nhub scan-secrets`，其他命令都需要管理员权限。`nhub open` 是例外：面板正在运行时不需要管理员权限，`nhub open --print` 也一样。

`nhub start`、`nhub stop`、`nhub reset <目标>`、`nhub update` 先显示 `[y/N]`，你回答 `y` 后才执行，加 `--yes` 就不显示。没有终端又没有加 `--yes` 时，命令不执行任何操作，所以写入脚本时要加 `--yes`。

| 返回值 | 含义                      |
| ------ | ------------------------- |
| 0      | 完成                      |
| 1      | 回答了 no，或者某一步失败 |
| 2      | 权限不够，或者没有写目标  |
| 130    | 按了 Ctrl-C               |
