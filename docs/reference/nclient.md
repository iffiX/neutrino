# nclient 命令

`nclient` 是客户端的命令行程序。你在窗口里能做的操作，都能在终端和脚本里用它完成。

`nclient` 随客户端一起安装，手机上没有。你要用自己的账户运行它，不要加 `sudo`，否则它返回 `root_refused`。

除了 `nclient gui`，每条命令都要求客户端正在运行。客户端没有运行时，命令返回 1 和 `client_not_running`，这时先运行 `nclient gui` 打开客户端。帮助和提示的语言跟随客户端的语言。下面的输出都来自真实运行，系统名称是 `my-computer`。

每一级命令后面加 `-h` 都能查看帮助，比如下面这条。

```bash
nclient hub -h
```

```text
用法：nclient hub <命令> [参数]

你绑定的中枢。

  list         每个中枢的连接状态和连接方式
  join         用链接加入一个中枢
  leave        离开一个中枢
  open         经转发在浏览器打开中枢面板

例子：nclient hub join "neutrino://…"
```

## 全局选项

这些选项写在子命令前面。

| 选项           | 作用                                                           |
| -------------- | -------------------------------------------------------------- |
| `-h`、`--help` | 查看这一级的帮助                                               |
| `--version`    | 打印客户端的版本                                               |
| `--hub <中枢>` | 加入了多个中枢时，指定这条命令作用于哪一个。只加入一个时不用写 |

## 客户端本身

| 命令           | 作用                                               |
| -------------- | -------------------------------------------------- |
| `nclient gui`  | 运行客户端并打开窗口，已经在运行时把窗口显示到前面 |
| `nclient quit` | 关闭窗口，关闭所有转发并卸载所有共享               |

## hub：中枢

`nclient hub list` 为每个中枢列出一行，显示序号、名称、连接状态、连接方式和往返时间。

```bash
nclient hub list
```

```text
1  my-computer  已连接 · 局域网 · 0 ms
```

连接方式有局域网、NetBird、EasyTier、SSH 中继、直连、SakuraFrp、OpenFrp。

| 命令                               | 作用                                                                      |
| ---------------------------------- | ------------------------------------------------------------------------- |
| `nclient hub list`                 | 列出每个中枢和它的状态                                                    |
| `nclient hub join '<链接>'`        | 用面板 **新建客户端链接** 生成的链接加入。链接只能使用一次，30 分钟内有效 |
| `nclient hub leave <中枢> [--yes]` | 关闭转发并卸载共享，退出虚拟网，删除绑定。运行前先提示 `[y/N]`            |
| `nclient hub open <中枢>`          | 在浏览器打开面板，这个客户端要有面板权限                                  |

`<中枢>` 可以写名称，也可以写 `nclient hub list` 里的序号。写错时，命令会列出可用的中枢。

```bash
nclient hub leave 9
```

```text
没有叫 9 的中枢，有这些：my-computer
```

## app：应用

先用 `nclient app list` 查看有哪些应用。每个系统下面每个应用一行，显示来源和是否正在使用，再下面是每个入口和本机地址。

```bash
nclient app list
```

```text
my-computer
  whoami  声明  未用
    8088  网页  http://whoami.my-computer.localhost:24110/
```

如果要使用一个应用，运行 `use`。它会为这个应用的每个入口打开转发，并打印本机地址，你把这个地址填写到浏览器或者你的程序里。

```bash
nclient app use whoami
```

```text
已转发 http://whoami.my-computer.localhost:24110/
```

使用完后运行 `stop`。

```bash
nclient app stop whoami
```

```text
已停止 whoami
```

应用没有在使用时，`open` 无法打开，命令返回 1。

```bash
nclient app open whoami
```

```text
先使用这个应用：nclient app use
```

| 命令                                          | 作用                                                   |
| --------------------------------------------- | ------------------------------------------------------ |
| `nclient app list`                            | 按系统列出应用、来源、入口、本机地址、是否正在使用     |
| `nclient app use <应用>`                      | 为每个入口打开转发，打印本机地址                       |
| `nclient app open <应用>`                     | 在浏览器打开第一个网页入口                             |
| `nclient app stop <应用>`                     | 关闭这个应用的转发                                     |
| `nclient app set <应用> --port <入口>=<端口>` | 固定一个入口的本机端口，可以写多次。端口留空时恢复默认 |

两个系统有同名应用时，写成 `<系统>/<应用>`。

网页入口的地址是 `<应用>.<系统>.localhost:<端口>`，macOS 上是 `127.0.0.1:<端口>`。端口入口的地址是 `127.0.0.1:<端口>`。端口在 24000 到 31999 之间，第一次分配后不再改变。

## ssh

`nclient ssh list` 列出打开了 SSH 的系统和启用的账户。第一个账户是默认账户，账户后面是本机地址。

```bash
nclient ssh list
```

```text
my-computer  lab 127.0.0.1:26261
```

| 命令                                           | 作用                                                                                       |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `nclient ssh list`                             | 列出系统、账户和本机地址                                                                   |
| `nclient ssh open [<账户>@]<系统> [-- <命令>]` | 登录一个系统。写了 `--` 时只运行那条命令，保留退出码                                       |
| `nclient ssh config show`                      | 打印 `~/.ssh/neutrino_config` 的路径和内容                                                 |
| `nclient ssh config install`                   | 在 `~/.ssh/config` 开头添加一行 `Include`，之后 ssh、scp、VS Code 可以直接使用 `<系统>.nt` |
| `nclient ssh config uninstall`                 | 移除那行 `Include`，不删除微子·中枢自己的配置文件                                          |
| `nclient ssh proxy`                            | 供 `ProxyCommand` 调用，不用手动运行                                                       |

这些软件的连接方法见 [SSH 连接](/access/ssh)。

## terminal：终端

如果要运行一条命令后立即返回，可以用 `exec`。输入、输出和退出码都原样返回，所以它适合写进脚本。

```bash
nclient terminal exec my-computer -- uname -sr
```

```text
Linux 5.15.0-198-generic
```

| 命令                                     | 作用                                             |
| ---------------------------------------- | ------------------------------------------------ |
| `nclient terminal list <系统>`           | 列出系统上的会话                                 |
| `nclient terminal open <系统>`           | 打开一个新 shell，退出 shell 后结束              |
| `nclient terminal attach <系统> <会话>`  | 连接仍在运行的会话，按 Ctrl+] 断开，会话继续运行 |
| `nclient terminal exec <系统> -- <命令>` | 运行一条命令                                     |
| `nclient terminal set <系统> <会话>`     | 修改会话：`--persist on\|off`、`--share on\|off` |
| `nclient terminal stop <系统> <会话>`    | 结束会话和里面的程序                             |

`--account` 用来选择启用的账户，默认是第一个，`open` 和 `exec` 都可以使用。`exec` 加 `--tty` 会给命令分配一个终端，运行 htop、vim 时需要它。

`exec` 返回远端命令的退出码。125 表示拒绝，126 表示没有中枢提供这个系统。写错系统名称时，它显示 **没有叫 lab-gpu 的机器，有这些：my-computer**，并返回 126。

## file：文件

| 命令                                   | 作用                                                                                |
| -------------------------------------- | ----------------------------------------------------------------------------------- |
| `nclient file list`                    | 按系统列出共享：共享名、本机挂载位置、挂载状态                                      |
| `nclient file mount <系统>[/<共享>]`   | 挂载，不用输入密码。默认位置是 `~/remote/<系统>-<共享>`，Windows 上是第一个空闲盘符 |
| `nclient file unmount <系统>[/<共享>]` | 卸载。文件夹共享挂载了多个账户时，用 `--account` 指定                               |

`nclient file mount` 还有下面的参数：`--account` 选择账户，`--path` 选择目录（Linux、macOS），`--drive` 选择盘符（Windows）。

## ai

| 命令              | 作用                                                |
| ----------------- | --------------------------------------------------- |
| `nclient ai show` | 显示这台电脑上的 claude、codex、gemini 指向哪个网关 |
| `nclient ai set`  | 把中枢的 AI 网关写入它们的配置，再次运行会刷新      |

```bash
nclient ai show
```

```text
claude  -  它自己的
codex   -  它自己的
gemini  -  它自己的
```

安装了被控端的电脑不使用这两条命令，要到面板上这个系统的页面设置，见 [AI 网关](/hub/ai_gateway)。这时 `nclient ai show` 的输出下面多一句 **这是已管理的设备，请到中枢面板它的机器页上设置它的 AI 工具。**

## rdp：远程桌面

| 命令                         | 作用                                         |
| ---------------------------- | -------------------------------------------- |
| `nclient rdp list`           | 列出共享桌面的系统：屏幕前的用户、查看的人数 |
| `nclient rdp connect <系统>` | 打开查看器，客户端自动获取密码               |

## settings：设置

`nclient settings show` 每项一行，显示项名、当前值和可选值。

```bash
nclient settings show
```

```text
language     zh-CN  en, zh-CN
theme        system  system, dark, light
ssh_include  off  on, off
```

如果要修改一项，运行 `nclient settings set <项> <值>`，比如 `nclient settings set theme dark`。`ssh_include` 对应设置页的 **让 SSH 程序直接连被控端**。

## 权限和确认

一台电脑同一时间只运行一个账户的客户端，所以这台电脑上其他账户的客户端正在运行时，命令返回 `client_held`。

只有 `nclient hub leave` 会先提示 `[y/N]`，其他命令都直接运行。
