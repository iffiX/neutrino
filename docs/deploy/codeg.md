# Codeg

Codeg 是 AI 编程工作台。你可以在同一个网页里使用 Claude Code、Codex 和 Gemini，并在另一台设备上继续对话。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.5.1" />

每个账户运行一个实例。如果你只使用 Claude Code，需要更简单的页面，可以改用 [CloudCLI](/deploy/cloudcli)。

## 支持的系统

| 系统    | 架构              | 开始支持的微子·中枢版本 |
| ------- | ----------------- | ----------------------- |
| Linux   | amd64、arm64      | 0.5.1                   |
| Windows | amd64             | 0.5.1                   |
| macOS   | Apple 芯片、Intel | 0.5.1                   |

## 安装

Codeg 不包含 AI 工具。开始之前，你要先用你的账户在这个系统上安装要使用的工具，并登录一次。其中两个工具有现成的模块，见 [Claude Code](/deploy/claude_code) 和 [Codex](/deploy/codex)。Claude Code 的安装方法见 [Claude Code 的安装页](https://code.claude.com/docs/en/setup)。

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。确认 **可用账户** 里有你的账户。如果没有，先按[添加账户](/deploy/on_a_machine#添加账户)的步骤添加它。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **Codeg** 卡片，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_codeg_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，Codeg 的卡片标红](/guide/zh/deploy_codeg_02_catalog.webp "勾选 Codeg")
   ![Codeg 的卡片亮了，关闭按钮标红](/guide/zh/deploy_codeg_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **Codeg** 这一行，右边会显示它的标签。按 **安装**。

   ![模块列表，Codeg 这一行标红](/guide/zh/deploy_codeg_04_tab.webp "点 Codeg")
   ![Codeg 标签显示未安装，安装按钮标红](/guide/zh/deploy_codeg_05_install.webp "按 安装")

1. 标签会列出每一步。它先安装 Codeg 服务端，再安装自带的 Node.js。标签变成 **已安装** 后，按 **启动**。

   ![标签显示安装中，下面列出每一步](/guide/zh/deploy_codeg_06_installing.webp "安装中")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_codeg_07_installed.webp "按 启动")

1. 标签变成 **运行中，没有账户**。按 **配置**，下面会展开设置。在 **启用的账户** 里勾选你的账户。

   ![标签显示运行中，没有账户，配置按钮标红](/guide/zh/deploy_codeg_17_started.webp "按 配置")
   ![启用的账户一栏，lab 这一行标红](/guide/zh/deploy_codeg_08_tick_account.webp "勾选 lab")

1. 按 **应用 Codeg**。账户后面出现 **运行中**，下面也出现 **已应用。** 这时安装完成。

   ![勾选了 lab，应用 Codeg 按钮标红](/guide/zh/deploy_codeg_09_apply.webp "按 应用 Codeg")
   ![lab 后面显示运行中，下面显示已应用](/guide/zh/deploy_codeg_10_applying.webp "已应用")

## 使用

开始之前，你要先把手机或电脑加入中枢，见[加入中枢](/access/join)。

打开客户端，进入 **应用** 页，找到 **Codeg (lab)** 这一行，括号里是账户名。按 **使用**。这一行会多出一个本机地址，按钮变成 **停止**、**配置** 和 **打开**。按 **打开**。

![客户端的应用页，使用按钮标红](/guide/zh/deploy_codeg_40_client_use.webp "按 使用")
![这一行有了本机地址，打开按钮标红](/guide/zh/deploy_codeg_41_client_open.webp "按 打开")

浏览器会直接进入工作区，你不用输入密码。如果看到 Codeg 的登录页，回到客户端再按一次 **打开**。

第一次使用某个工具之前，你要先给它安装适配器。Codeg 通过适配器和工具通信。适配器和你在账户里安装的工具是两个不同的程序。

1. 工作区中间有一行红字，提示这个工具的适配器还没有安装。点这行字，新的标签页会打开 **设置** 的 **智能体** 页面，左边列出每个工具。

   ![工作区，红字提示适配器尚未安装，标红](/guide/zh/deploy_codeg_20_workspace.webp "点红字")
   ![设置页的智能体列表](/guide/zh/deploy_codeg_21_agents_settings.webp "智能体页面")

1. 按 **版本状态** 下面的 **安装**。适配器从 npm 官方源下载，需要一两分钟。

   ![智能体的详情，安装按钮标红](/guide/zh/deploy_codeg_22_agent_install.webp)

回到工作区，在输入框上面选择工具，填写你要它做的事，按发送按钮。左边的 **打开文件夹** 可以选择你的项目。

使用完后回到客户端按 **停止**。手机上的操作相同：在 **应用** 页按 **使用**，再按 **打开**。

![手机上的 Codeg 工作区](/guide/zh/deploy_codeg_60_phone.webp)

## 分享

Codeg 能用[应用分享](/share/web_share)生成链接，对方用浏览器就能打开。

1. 在面板左侧栏点 **服务**，找到 **Codeg (lab)** 这一行，按 **分享**。

   ![服务页，Codeg (lab) 这一行的分享按钮标红](/guide/zh/deploy_codeg_12_services_share.webp)

1. 弹窗打开后，在 **名称** 里填写便于你自己识别的名称，对方看不到这个名称。下面的黄色提示说明，对方会以这个账户的身份使用这个应用。**有效期** 默认是 7 天，你可以选择其他选项。选好后按 **生成链接**。立即按 **复制**，把链接发给对方，再按 **完成** 关闭弹窗。弹窗关闭后，面板不再显示这条链接。

   ![分享弹窗，名称一栏标红](/guide/zh/deploy_codeg_13_share_dialog.webp "填写名称")
   ![分享弹窗填好了，生成链接按钮标红](/guide/zh/deploy_codeg_14_share_generate.webp "按 生成链接")
   ![分享弹窗显示链接和二维码，链接一行标红](/guide/zh/deploy_codeg_15_share_link.webp "按 复制")

对方打开链接后不用登录，直接进入工作区，和你使用同一个账户和 AI 额度。

![访客的浏览器里打开了 Codeg 工作区](/guide/zh/deploy_codeg_16_visitor.webp)

## 注意

会话里的工具以这个账户运行，能读写它的文件，也能运行命令，对方同样能做这些操作，所以链接只发给你信任的人。

每个打开的会话占用约 300 MB 内存，关闭页面几分钟后释放。

工具要连接 AI 服务才能使用。你可以在这个账户里自己登录，也可以打开 **AI 工具使用中枢网关**。Codeg 自己的 **模型供应商** 设置也写入同样的文件，开关打开时以开关为准。

工作区右下角可能提示有新版本。版本由面板管理。如果要更换版本，到面板上按 **更新**，Codeg 内部不能更换版本。

## 设置

除了启用账户，下面的设置保持默认即可。

| 设置                          | 位置                    | 作用                                                          |
| ----------------------------- | ----------------------- | ------------------------------------------------------------- |
| **启用的账户**                | 标签的 **配置**         | 每个勾选的账户运行一个实例                                    |
| **更新**、**安装另一个版本…** | 标签的状态下面          | 更换版本，步骤见表格下方                                      |
| **AI 工具使用中枢网关**       | **可用账户** 的账户表单 | 让 Claude Code 和 Codex 的会话使用 [AI 网关](/hub/ai_gateway) |

如果要更换版本，先查看标签上的版本这一行，它显示当前版本和发布者的最新版本。

1. 按 **安装另一个版本…**。弹窗里新版本排在上面，标 **已测试** 的是测试过的版本，比它新的版本标 **未测试**，打勾的是当前安装的版本。点你要的版本。

   ![版本这一行，安装另一个版本按钮标红](/guide/zh/deploy_codeg_30_version_button.webp "按 安装另一个版本")
   ![版本列表，一个版本标红](/guide/zh/deploy_codeg_31_version_dialog.webp "点版本")

1. 弹窗关闭后，标签开始切换版本。标签恢复为 **运行中**，版本这一行显示新的版本。

   ![标签显示安装中，第一步是切换到版本](/guide/zh/deploy_codeg_32_version_switching.webp "切换中")
   ![版本这一行显示新的版本，更新按钮标红](/guide/zh/deploy_codeg_33_version_older.webp "切换完成")

如果你要回到测试过的版本，在弹窗里点最上面的 **跟随已测试的版本**。

## 卸载

在 **Codeg** 标签上按 **卸载**。弹窗说明每个账户的数据保留在哪个文件夹，数据库、上传的文件和它安装的工具都在那里。确认后按 **卸载**。

![Codeg 标签，卸载按钮标红](/guide/zh/deploy_codeg_50_uninstall.webp "按 卸载")
![卸载的弹窗，卸载按钮标红](/guide/zh/deploy_codeg_51_uninstall_dialog.webp "确认")

如果你无法使用 Codeg，查看[故障排查](/reference/troubleshooting)。
