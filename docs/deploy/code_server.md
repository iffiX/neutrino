# code-server

code-server 是开源的网页版 VS Code。你不用接受微软的条款，在手机上也能写代码。

<Facts systems="Linux,macOS" editions="国际版,国内版" since="0.5.0" />

它的扩展来自 Open VSX，每个账户运行一个实例。Windows 上这张卡片是灰色的，因为 code-server 没有 Windows 版本。在 Windows 上，你可以使用 [VS Code](/deploy/vscode)。

## 支持的系统

| 系统  | 架构              | 开始支持的微子·中枢版本 |
| ----- | ----------------- | ----------------------- |
| Linux | amd64、arm64      | 0.5.0                   |
| macOS | Apple 芯片、Intel | 0.5.0                   |

## 安装

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。确认 **可用账户** 里有你的账户。如果没有，先按[添加账户](/deploy/on_a_machine#添加账户)的步骤添加它。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **code-server** 卡片，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_code_server_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，code-server 的卡片标红](/guide/zh/deploy_code_server_02_catalog.webp "勾选 code-server")
   ![code-server 的卡片亮了，关闭按钮标红](/guide/zh/deploy_code_server_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **code-server** 这一行，右边会显示它的标签。按 **安装**。

   ![模块列表，code-server 这一行标红](/guide/zh/deploy_code_server_04_tab.webp "点 code-server")
   ![code-server 标签显示未安装，安装按钮标红](/guide/zh/deploy_code_server_05_install.webp "按 安装")

1. 标签会列出每一步。它要下载一个压缩包再解压，通常一分钟内完成。标签变成 **已安装** 后，按 **启动**。

   ![标签显示安装中，下面列出每一步](/guide/zh/deploy_code_server_06_installing.webp "安装中")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_code_server_07_installed.webp "按 启动")

1. 标签变成 **运行中，没有账户**。按 **配置**，下面会展开设置。在 **启用的账户** 里勾选你的账户。

   ![标签显示运行中，没有账户，配置按钮标红](/guide/zh/deploy_code_server_17_started.webp "按 配置")
   ![启用的账户一栏，lab 这一行标红](/guide/zh/deploy_code_server_08_tick_account.webp "勾选 lab")

1. 按 **应用 code-server**。账户后面出现 **运行中**，下面也出现 **已应用。** 这时安装完成。

   ![勾选了 lab，应用 code-server 按钮标红](/guide/zh/deploy_code_server_09_apply.webp "按 应用 code-server")
   ![lab 后面显示运行中，下面显示已应用](/guide/zh/deploy_code_server_10_applying.webp "已应用")

## 使用

开始之前，你要先把手机或电脑加入中枢，见[加入中枢](/access/join)。

打开客户端，进入 **应用** 页，找到 **code-server (lab)** 这一行，括号里是账户名。按 **使用**。这一行会多出一个本机地址，按钮变成 **停止**、**配置** 和 **打开**。按 **打开**。

![客户端的应用页，使用按钮标红](/guide/zh/deploy_code_server_40_client_use.webp "按 使用")
![这一行有了本机地址，打开按钮标红](/guide/zh/deploy_code_server_41_client_open.webp "按 打开")

浏览器会打开编辑器，你不用输入密码。第一次打开时显示欢迎页，点里面的 **open a folder**，选择你的项目文件夹，就能开始写代码。左上角的菜单里有 **Terminal**，可以打开这个账户的终端。

![浏览器里的 code-server，显示欢迎页](/guide/zh/deploy_code_server_16_visitor.webp)

使用完后回到客户端按 **停止**，本机地址随即关闭。登录过期后，回到客户端再按一次 **打开**。

手机上的操作相同：在 **应用** 页按 **使用**，再按 **打开**。

## 分享

code-server 能用[应用分享](/share/web_share)生成链接，对方用浏览器就能打开，不用安装任何软件。

1. 在面板左侧栏点 **服务**，找到 **code-server (lab)** 这一行，按 **分享**。

   ![服务页，code-server (lab) 这一行的分享按钮标红](/guide/zh/deploy_code_server_12_services_share.webp)

1. 弹窗打开后，在 **名称** 里填写便于你自己识别的名称，对方看不到这个名称。下面的黄色提示说明，对方会以这个账户的身份使用这个应用。**有效期** 默认是 7 天，你可以选择其他选项。选好后按 **生成链接**。立即按 **复制**，把链接发给对方，再按 **完成** 关闭弹窗。弹窗关闭后，面板不再显示这条链接。

   ![分享弹窗，名称一栏标红](/guide/zh/deploy_code_server_13_share_dialog.webp "填写名称")
   ![分享弹窗填好了，生成链接按钮标红](/guide/zh/deploy_code_server_14_share_generate.webp "按 生成链接")
   ![分享弹窗显示链接和二维码，链接一行标红](/guide/zh/deploy_code_server_15_share_link.webp "按 复制")

对方打开链接后不用登录，直接进入上面的编辑器，和你使用同一个账户。

## 注意

对方打开里面的终端，就能读写这个账户的文件，也能运行命令，所以链接只发给你信任的人。

你在 code-server 里启动的开发服务器不会出现在客户端。如果要使用它，按[加入已有的服务](/deploy/services)声明。

## 设置

除了启用账户，下面的设置保持默认即可。

| 设置                          | 位置                        | 作用                                                  |
| ----------------------------- | --------------------------- | ----------------------------------------------------- |
| **启用的账户**                | 标签的 **配置**             | 每个勾选的账户运行一个实例                            |
| **更新**、**安装另一个版本…** | 标签的状态下面              | 更换版本，步骤见[换版本](/deploy/on_a_machine#换版本) |
| **AI 工具使用中枢网关**       | **可用账户** 的账户表单     | 让这个账户的工具使用 [AI 网关](/hub/ai_gateway)       |
| 扩展                          | 编辑器左边的 **Extensions** | 搜索后按 **Install**                                  |

## 卸载

在 **code-server** 标签上按 **卸载**。弹窗说明，每个账户的设置和扩展都保留在它的主目录里。确认后按 **卸载**。

![code-server 标签，卸载按钮标红](/guide/zh/deploy_code_server_50_uninstall.webp "按 卸载")
![卸载的弹窗，卸载按钮标红](/guide/zh/deploy_code_server_51_uninstall_dialog.webp "确认")

如果遇到报错，查看[故障排查](/reference/troubleshooting)。
