# OpenCode

OpenCode 是 Anomaly 发布的开源命令行 AI 编程工具。微子·中枢为你勾选的账户安装它，你在这个系统的终端里运行 `opencode` 就能使用。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.1" />

OpenCode 是普通程序，没有启动和停止，只在你运行它时运行。它的来源是外部源，由中枢从发布方下载，见[应用的分类](/deploy/app_kinds)。OpenCode 以 MIT 许可证发布。

## 支持的系统

| 系统                         | 架构              | 开始支持的微子·中枢版本 |
| ---------------------------- | ----------------- | ----------------------- |
| Linux                        | amd64、arm64      | 0.6.1                   |
| Windows 10 1809 或更新的版本 | amd64、arm64      | 0.6.1                   |
| macOS 13 或更新的版本        | Apple 芯片、Intel | 0.6.1                   |

## 安装

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。确认 **可用账户** 里有你的账户。如果没有，先按[添加账户](/deploy/on_a_machine#添加账户)的步骤添加它。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **OpenCode** 卡片，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_opencode_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，OpenCode 的卡片标红](/guide/zh/deploy_opencode_02_catalog.webp "勾选 OpenCode")
   ![OpenCode 的卡片亮了，关闭按钮标红](/guide/zh/deploy_opencode_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **OpenCode** 这一行，右边会显示它的标签。按 **安装**，标签会列出每一步。

   ![模块列表，OpenCode 这一行标红](/guide/zh/deploy_opencode_04_tab.webp "点 OpenCode")
   ![OpenCode 标签显示未安装，安装按钮标红](/guide/zh/deploy_opencode_05_install.webp "按 安装")
   ![标签显示安装中，下面列出每一步](/guide/zh/deploy_opencode_06_installing.webp "安装中")

1. 安装完成后，标签显示 **可用**。OpenCode 是普通程序，标签上只有 **安装**、**卸载** 和 **配置**，没有 **启动** 和 **停止**。按 **配置**，在 **启用的账户** 里勾选要使用 OpenCode 的账户。

   ![标签显示可用，配置按钮标红](/guide/zh/deploy_opencode_07_installed.webp "按 配置")
   ![启用的账户一栏，lab 这一行标红](/guide/zh/deploy_opencode_08_tick_account.webp "勾选 lab")

1. 如果这个账户的 shell 已经能运行另一份 OpenCode，比如你自己安装的那一份，勾选时面板会弹窗。弹窗写明那一份的位置和版本、模块安装的副本的版本，并说明那一份会原样保留。按 **替换**，这个账户改用模块安装的副本；按 **取消** 或者点弹窗外面，这个账户不会勾选。你自己安装的那一份没有任何改动，你仍然可以自己升级或卸载它。

   ![替换 lab 运行的副本的弹窗，替换按钮标红](/guide/zh/deploy_opencode_09_replace_dialog.webp)

1. 按 **应用 OpenCode**。被控端会让每个勾选账户的 PATH 先找到模块安装的副本。完成后，账户这一行显示模块安装的副本的版本。

   ![勾选了 lab，应用 OpenCode 按钮标红](/guide/zh/deploy_opencode_10_apply.webp "按 应用 OpenCode")
   ![lab 这一行显示模块安装的副本的版本](/guide/zh/deploy_opencode_11_applied.webp "已应用")

被控端查找另一份 OpenCode 时，先查这个账户的 PATH，再查下面这些常用的安装位置：

| 系统    | PATH 之外查找的位置                                                                                                 |
| ------- | ------------------------------------------------------------------------------------------------------------------- |
| Linux   | `~/.opencode/bin/opencode`、`/usr/local/bin/opencode`、`/usr/bin/opencode`                                          |
| macOS   | `~/.opencode/bin/opencode`、`/opt/homebrew/bin/opencode`、`/usr/local/bin/opencode`                                 |
| Windows | `%USERPROFILE%\scoop\shims\opencode.exe`、`%ProgramData%\chocolatey\bin\opencode.exe`、`%APPDATA%\npm\opencode.cmd` |

在 Windows 上，如果另一份 OpenCode 在系统 PATH 里，弹窗的标题会写“无法使用本模块安装的副本”，只有 **关闭** 按钮，这个账户不会勾选。Windows 先找系统 PATH，再找用户 PATH，所以模块安装的副本排不到那一份前面。如果你要让这个账户使用模块安装的副本，要先卸载那一份，或者把它的目录从系统 PATH 里删除。

## 使用

开始之前，你要能打开这个系统上这个账户的终端。你可以在这个系统上直接打开终端，也可以从客户端打开，见[终端](/deploy/terminal)。

1. 打开一个新的终端。勾选账户之前已经打开的终端还是原来的 PATH，找不到模块安装的副本，所以要新开一个。
1. 运行 `opencode`。OpenCode 在终端里打开它的界面，中间是输入框，输入框下面显示当前的模型。第一次运行时，模型是 OpenCode 提供的 Big Pickle。如果你要使用自己的服务商，在输入框里输入 `/connect`，按提示添加服务商。费用由你选择的服务商决定。

   ![终端里运行 opencode，显示第一次运行的画面](/guide/zh/deploy_opencode_12_terminal.webp)

用微子的 SSH 连接时也一样，比如 `nclient ssh` 和 VS Code 的 Remote-SSH。新开的 SSH 会话会把勾选的程序排在 PATH 的最前面。勾选或取消勾选账户不会断开已经打开的 SSH 会话，这些会话保持原来的 PATH。

如果你要让 OpenCode 使用中枢的 AI 网关，在系统页面的 **可用账户** 里编辑这个账户，打开 **AI 工具使用中枢网关**，再按 **保存**，步骤见 [AI 网关](/hub/ai_gateway#加入了中枢的系统)。OpenCode 标签的账户那一行会显示 **使用中枢的 AI 网关**；开关关闭时显示 **使用自己原来的设置**。这个开关不在 OpenCode 标签上，改完也不用再按 **应用 OpenCode**。

开关打开后，被控端在 OpenCode 的设置文件里加入服务商 `neutrino`，它在 OpenCode 里显示为 **Neutrino Hub**。设置文件是 `~/.config/opencode/opencode.json`，文件里原有的服务商和设置都保留。如果你从没设置过 OpenCode，它启动后直接使用中枢的模型。如果这个文件用 `model` 指定了模型，或者你用过其他服务商的模型，OpenCode 先用那个模型。这时在输入框里输入 `/models`，选择 **Neutrino Hub** 下的模型。

## 分享

这个模块只安装命令行程序，面板上没有 OpenCode 的网页，所以不能用[应用分享](/share/web_share)生成链接。

## 注意

在终端里运行的 OpenCode 能做这个账户能做的一切，包括读写这个账户的所有文件。

版本由中枢管理，换版本的步骤见[换版本](/deploy/on_a_machine#换版本)。OpenCode 每次启动时查看 npm 上的新版本，有新版本时显示提示，这个版本不一定在中枢的版本列表里。如果你要关闭这项检查，在 `opencode.json` 里写入 `"autoupdate": false`。`opencode upgrade` 和 `/update` 这两个升级命令，只用这个账户自己的包管理器安装 OpenCode，比如 npm 和 Homebrew。模块安装的副本属于 root，这两个命令不改动它。

勾选账户以后，如果出现下面的情况，这个账户那一行会显示提示，并提供 **让本模块安装的副本优先** 按钮：

- 这个账户的 shell 先运行另一份 OpenCode，比如你之后自己安装的那一份。提示里写明那一份的位置和版本。
- 这个账户的 shell 找不到模块安装的副本。

按下这个按钮后，被控端把启动文件里的那一行重新移到文件末尾。在 Windows 上，被控端把模块的程序目录重新放到用户 PATH 的最前面。你不按这个按钮，被控端就不会改回来。你改了启动文件以后，这一行的提示会自己更新。

![lab 这一行显示红字提示，让本模块安装的副本优先按钮标红](/guide/zh/deploy_opencode_13_conflict.webp)

OpenCode 允许 `opencode.json` 里有注释，被控端修改这个文件用的 cc-switch 无法读取带注释的文件。如果文件里有注释，打开 **AI 工具使用中枢网关** 会失败，这个账户那一行显示失败的原因。删除注释后，关闭开关再打开。

## 设置

除了勾选账户，下面的设置保持默认即可。

| 设置                    | 位置                     | 作用                                                                                     |
| ----------------------- | ------------------------ | ---------------------------------------------------------------------------------------- |
| **启用的账户**          | OpenCode 标签的 **配置** | 勾选的账户使用模块安装的 OpenCode                                                        |
| **AI 工具使用中枢网关** | **可用账户** 的账户表单  | 让这个账户的 OpenCode 使用 [AI 网关](/hub/ai_gateway)，OpenCode 标签的账户那一行显示结果 |

勾选账户后，被控端按系统做下面的设置，让这个账户的 shell 先找到模块安装的副本：

| 系统    | 被控端的设置                                                                                                                    |
| ------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Linux   | 写入 `~/.local/share/neutrino/agent/env.sh`，再在这个账户的启动文件末尾加一行载入它。这个文件把模块的程序目录排到 PATH 的最前面 |
| macOS   | 和 Linux 一样，文件是 `~/Library/Application Support/Neutrino/agent/env.sh`                                                     |
| Windows | 把模块的程序目录放到这个账户的用户 PATH 的最前面                                                                                |

加这一行的启动文件由这个账户的登录 shell 决定：

| 登录 shell | 启动文件                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------- |
| bash       | `~/.bashrc`，以及登录文件：`~/.bash_profile`；没有它时是 `~/.bash_login`；再没有时是 `~/.profile` |
| zsh        | `~/.zshrc`                                                                                        |
| fish       | `~/.config/fish/config.fish`，这一行载入 `env.sh` 旁边的 `env.fish`                               |
| 其他 shell | `~/.profile`                                                                                      |

取消勾选这个账户时，被控端从 `env.sh` 里去掉 OpenCode 的程序目录；在 Windows 上，从用户 PATH 里删除这个目录。Codex 和 Claude Code 模块也用同一个 `env.sh` 和同一行。这个账户的三个模块都不再勾选时，被控端删除这一行和 `env.sh`，账户的启动文件恢复原样。

## 卸载

在 **OpenCode** 标签上按 **卸载**，再在弹窗里确认。弹窗写明：每个账户在 `~/.config/opencode` 里的设置都保留，在本模块之外安装的 OpenCode 也保留。

![卸载 OpenCode 的弹窗，卸载按钮标红](/guide/zh/deploy_opencode_14_uninstall_dialog.webp)

OpenCode 运行时还会写入三个目录：`~/.local/share/opencode`、`~/.local/state/opencode`、`~/.cache/opencode`。会话记录和日志在第一个目录里，卸载后这三个目录都保留。被控端只删除名称一看就属于微子·中枢的目录。`~/.local/share`、`~/.local`、`~/.config/fish` 这类共用的目录会保留。
