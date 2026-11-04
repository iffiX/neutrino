# CloudCLI

CloudCLI 是 Claude Code 等 AI 编程工具的网页界面。你可以在手机上通过它让 AI 工具修改电脑上的代码。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.5.0" />

每个账户运行一个实例。你用哪个账户登录 Claude Code，就为哪个账户启用 CloudCLI。如果你要在一个网页里使用多种 AI 工具，可以改用 [Codeg](/deploy/codeg)。

## 支持的系统

| 系统    | 架构              | 开始支持的微子·中枢版本 |
| ------- | ----------------- | ----------------------- |
| Linux   | amd64、arm64      | 0.5.0                   |
| Windows | amd64             | 0.5.0                   |
| macOS   | Apple 芯片、Intel | 0.5.0                   |

## 安装

CloudCLI 不包含 Claude Code。开始之前，你要先用你的账户在这个系统上安装 Claude Code，并运行一次 `claude` 登录。安装方法见 [Claude Code 的安装页](https://code.claude.com/docs/en/setup)。

CloudCLI 只在下面这些目录里查找 `claude`，官方安装命令的安装目录也在其中。

| 系统    | 目录                                                           |
| ------- | -------------------------------------------------------------- |
| Linux   | `~/.local/bin`、`~/bin`、`/usr/local/bin`、`/usr/bin`          |
| macOS   | `~/.local/bin`、`~/bin`、`/opt/homebrew/bin`、`/usr/local/bin` |
| Windows | `%APPDATA%\npm`，或这个账户 `PATH` 里的目录                    |

接下来的步骤都在面板上操作。

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。确认 **可用账户** 里有你的账户。如果没有，先按[添加账户](/deploy/on_a_machine#添加账户)的步骤添加它。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **CloudCLI** 卡片，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_cloudcli_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，CloudCLI 的卡片标红](/guide/zh/deploy_cloudcli_02_catalog.webp "勾选 CloudCLI")
   ![CloudCLI 的卡片亮了，关闭按钮标红](/guide/zh/deploy_cloudcli_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **CloudCLI** 这一行，右边会显示它的标签。按 **安装**。

   ![模块列表，CloudCLI 这一行标红](/guide/zh/deploy_cloudcli_04_tab.webp "点 CloudCLI")
   ![CloudCLI 标签显示未安装，安装按钮标红](/guide/zh/deploy_cloudcli_05_install.webp "按 安装")

1. 标签会列出每一步。它先安装自带的 Node.js，这一步很快。标签变成 **已安装** 后，按 **启动**。

   ![标签显示安装中，第一步是安装 Node.js](/guide/zh/deploy_cloudcli_06_installing.webp "安装中")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_cloudcli_07_installed.webp "按 启动")

1. 标签变成 **运行中，没有账户**。按 **配置**，下面会展开设置。在 **启用的账户** 里勾选你安装 Claude Code 的账户。

   ![标签显示运行中，没有账户，配置按钮标红](/guide/zh/deploy_cloudcli_17_started.webp "按 配置")
   ![启用的账户一栏，lab 这一行标红](/guide/zh/deploy_cloudcli_08_tick_account.webp "勾选 lab")

1. 按 **应用 CloudCLI**。这时标签显示 **安装中**，正在运行 **为 lab 运行 npm** 这一步。这一步需要几分钟到十几分钟，取决于网速和这个系统的性能。你可以保持页面打开，也可以关闭页面，这一步会继续在系统上运行。

   ![勾选了 lab，应用 CloudCLI 按钮标红](/guide/zh/deploy_cloudcli_09_apply.webp "按 应用 CloudCLI")
   ![正在运行 npm 这一步](/guide/zh/deploy_cloudcli_10_npm_running.webp "等待 npm 这一步")

1. 标签变成 **运行中**，这时安装完成。

   ![标签显示运行中，下面列出的步骤都是绿点](/guide/zh/deploy_cloudcli_11_running.webp)

如果 npm 这一步失败，标签会显示原因，比如某个地址无法连接。网络恢复后，再按一次 **应用 CloudCLI** 就会重试。其他情况查看[故障排查](/reference/troubleshooting)。

## 使用

开始之前，你要先把手机或电脑加入中枢，见[加入中枢](/access/join)。

打开客户端，进入 **应用** 页，找到 **CloudCLI (lab)** 这一行，括号里是账户名。按 **使用**。这一行会多出一个本机地址，按钮变成 **停止**、**配置** 和 **打开**。按 **打开**。

![客户端的应用页，使用按钮标红](/guide/zh/deploy_cloudcli_40_client_use.webp "按 使用")
![这一行有了本机地址，打开按钮标红](/guide/zh/deploy_cloudcli_41_client_open.webp "按 打开")

浏览器会打开 CloudCLI，你不用输入密码。第一次打开时显示英文的设置页，完成这两屏后就能使用。

1. 第一屏是 **Git Configuration**。在 **Git Name** 和 **Git Email** 里填写你的名字和邮箱，它们会写入这个账户的 git 设置。再按 **Next**。

   ![Git Configuration 这一屏，Git Name 一栏标红](/guide/zh/deploy_cloudcli_20_git_config.webp "填写名字和邮箱")
   ![两栏都填好了，Next 按钮标红](/guide/zh/deploy_cloudcli_21_git_next.webp "按 Next")

1. 第二屏是 **Connect Your AI Agents**，列出每个工具是否已登录。这些登录都可以以后再做，直接按 **Complete Setup**。

   ![Connect Your AI Agents 这一屏，Complete Setup 按钮标红](/guide/zh/deploy_cloudcli_22_connect_agents.webp)

进入主页面后，按下面的步骤把界面换成中文。

1. 按窗口右边缘的小箭头，打开 **Quick Settings**。在 **Language** 里选择 **简体中文**。

   ![主页面，右边的小箭头标红](/guide/zh/deploy_cloudcli_23_home.webp "按小箭头")
   ![Quick Settings 打开了，Language 一栏标红](/guide/zh/deploy_cloudcli_24_language.webp "选择 简体中文")

1. 界面变成中文，以后打开也是中文。

   ![主页面变成了中文](/guide/zh/deploy_cloudcli_25_home_zh.webp)

CloudCLI 里的项目是系统上的一个文件夹。第一次使用时，你要先创建一个项目。

1. 按左上角的 **+**。在 **工作区路径** 里填写文件夹的完整路径，这里填写 `/home/lab/demo`。按 **下一步**。

   ![左上角的加号按钮标红](/guide/zh/deploy_cloudcli_26_new_project.webp "按 +")
   ![创建新项目的弹窗，工作区路径一栏标红](/guide/zh/deploy_cloudcli_27_new_project_path.webp "填写路径")

1. 确认路径没有写错，再按 **创建项目**。项目出现在左边的列表里，点这个项目。

   ![确认这一屏，创建项目按钮标红](/guide/zh/deploy_cloudcli_28_new_project_confirm.webp "按 创建项目")
   ![左边的列表里多了 demo，标红](/guide/zh/deploy_cloudcli_29_project_listed.webp "点 demo")

1. 右边会打开一个新会话。在下面的输入框里填写你要 Claude Code 做的事，按 Enter 发送。右上角还能切换到 **终端**、**文件** 和 **源代码管理**。

   ![项目打开了，下面是输入框](/guide/zh/deploy_cloudcli_30_project_open.webp)

<div class="pic-holder">图：CloudCLI 里的一次对话</div>

使用完后回到客户端按 **停止**，本机地址随即关闭。如果浏览器提示要登录，回到客户端再按一次 **打开**。

手机上的操作相同：在 **应用** 页按 **使用**，再按 **打开**，应用会在手机的浏览器里打开。

![手机上的 CloudCLI](/guide/zh/access_android_14_browser.webp)

## 分享

CloudCLI 能用[应用分享](/share/web_share)生成链接，对方用浏览器就能打开，不用安装任何软件。

1. 在面板左侧栏点 **服务**，找到 **CloudCLI (lab)** 这一行，按 **分享**。

   ![服务页，CloudCLI 这一行的分享按钮标红](/guide/zh/deploy_cloudcli_12_services_share.webp)

1. 弹窗打开后，在 **名称** 里填写便于你自己识别的名称，对方看不到这个名称。下面的黄色提示说明，对方会以 lab 的身份使用这个应用。**有效期** 默认是 7 天，你可以选择其他选项。选好后按 **生成链接**。立即按 **复制**，把链接发给对方，再按 **完成** 关闭弹窗。弹窗关闭后，面板不再显示这条链接。

   ![分享弹窗，名称一栏标红，下面有黄色提示](/guide/zh/deploy_cloudcli_13_share_dialog.webp "填写名称")
   ![分享弹窗填好了，生成链接按钮标红](/guide/zh/deploy_cloudcli_14_share_generate.webp "按 生成链接")
   ![分享弹窗显示链接和二维码，链接一行标红](/guide/zh/deploy_cloudcli_15_share_link.webp "按 复制")

对方打开链接后不用登录，直接进入 CloudCLI，和你使用同一个账户。

![访客的浏览器里打开了 CloudCLI](/guide/zh/deploy_cloudcli_16_visitor.webp)

## 注意

对方能看到你的项目和会话，使用的也是你的 AI 额度。AI 工具能读写这个账户的文件，也能运行命令，对方同样能做这些操作，所以链接只发给你信任的人。

CloudCLI 左下角可能提示有更新。版本由面板管理，如果要更新，到面板上按 **更新**。

重置或重新安装微子·中枢后，CloudCLI 会使用新的账户数据库。你的文件还在电脑上，但新数据库里没有以前的记录。

## 设置

除了启用账户，下面的设置保持默认即可。

| 设置                          | 位置                    | 作用                                                  |
| ----------------------------- | ----------------------- | ----------------------------------------------------- |
| **启用的账户**                | 标签的 **配置**         | 每个勾选的账户运行一个实例，实例之间相互独立          |
| **更新**、**安装另一个版本…** | 标签的状态下面          | 更换版本，步骤见[换版本](/deploy/on_a_machine#换版本) |
| **AI 工具使用中枢网关**       | **可用账户** 的账户表单 | 让这个账户的工具使用 [AI 网关](/hub/ai_gateway)       |

## 卸载

1. 在 **CloudCLI** 标签上按 **卸载**。

   ![CloudCLI 标签，卸载按钮标红](/guide/zh/deploy_cloudcli_50_uninstall.webp)

1. 弹窗说明每个账户的数据保留在哪个文件夹，卸载不会删除这些数据。确认后按 **卸载**。

   ![卸载的弹窗，说明数据的保留位置，卸载按钮标红](/guide/zh/deploy_cloudcli_51_uninstall_dialog.webp)

卸载后，这个应用的分享都会结束。再次安装时，上次勾选的账户仍然保留，按 **启动** 就会运行。
