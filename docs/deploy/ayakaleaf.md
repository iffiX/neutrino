# Ayakaleaf

Ayakaleaf 是写 LaTeX 论文的网页编辑器。你可以和别人一起写，论文保存在你自己的电脑上。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.0" />

Ayakaleaf 运行在[容器](/deploy/containers)里，每个系统只运行一个实例。界面是英文的，和 Overleaf 相似。

## 支持的系统

| 系统    | 架构              | 开始支持的微子·中枢版本 |
| ------- | ----------------- | ----------------------- |
| Linux   | amd64、arm64      | 0.6.0                   |
| Windows | amd64             | 0.6.0                   |
| macOS   | Apple 芯片、Intel | 0.6.0                   |

## 安装

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **Ayakaleaf** 卡片，卡片上显示 **需要：容器**，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_ayakaleaf_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，Ayakaleaf 的卡片标红](/guide/zh/deploy_ayakaleaf_02_catalog.webp "勾选 Ayakaleaf")
   ![Ayakaleaf 的卡片亮了，关闭按钮标红](/guide/zh/deploy_ayakaleaf_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **Ayakaleaf** 这一行，右边会显示它的标签。按 **安装**。如果容器还没有安装，会先弹出确认框，按 **是** 会一起安装两个模块。图中的容器已经安装，所以没有弹出确认框。

   ![模块列表，Ayakaleaf 这一行标红](/guide/zh/deploy_ayakaleaf_04_tab.webp "点 Ayakaleaf")
   ![Ayakaleaf 标签显示未安装，安装按钮标红](/guide/zh/deploy_ayakaleaf_05_install.webp "按 安装")

1. 在 Windows 和 macOS 上第一次安装时，接着会弹出 **选择运行容器的账户**。选择账户，再按 **安装**，详细步骤见[依赖容器的应用](/deploy/on_a_machine#依赖容器的应用)。Linux 上没有这个弹窗。

   ![选择运行容器的账户的弹窗](/guide/zh/windows_account_dialog.webp)

1. 在 Windows 上，如果要重启，这个标签会显示提示，旁边有 **立即重启**。按 **立即重启**，电脑重启后会自动继续安装。

   ![Ayakaleaf 标签显示 Windows 需要重启，立即重启按钮标红](/guide/zh/deploy_ayakaleaf_10_reboot.webp)

1. 标签会列出每一步。它要拉取三个镜像，需要几分钟。如果你要放弃，可以按 **取消**。标签变成 **已安装** 后，按 **启动**。

   ![标签显示安装中，下面列出每一步](/guide/zh/deploy_ayakaleaf_06_installing.webp "安装中")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_ayakaleaf_07_installed.webp "按 启动")

1. 第一次启动时，它要初始化数据库、创建管理员、安装中文 TeX 宏包，需要几分钟到十几分钟。这段时间你可以关闭页面，启动会继续运行。如果你要放弃，可以按 **取消**。标签变成 **运行中**，这时安装完成。

   ![标签正在运行等待应用启动这一步，取消按钮标红](/guide/zh/deploy_ayakaleaf_08_first_start.webp "第一次启动")
   ![标签显示运行中](/guide/zh/deploy_ayakaleaf_09_running.webp "运行中")

## 使用

开始之前，你要先把手机或电脑加入中枢，见[加入中枢](/access/join)。

1. 打开客户端，进入 **应用** 页，找到 **Ayakaleaf** 这一行。按 **使用**。这一行会多出一个本机地址，按钮变成 **停止**、**配置** 和 **打开**。按 **打开**。

   ![客户端的应用页，使用按钮标红](/guide/zh/deploy_ayakaleaf_40_client_use.webp "按 使用")
   ![这一行有了本机地址，打开按钮标红](/guide/zh/deploy_ayakaleaf_41_client_open.webp "按 打开")

1. 浏览器会打开项目列表，你不用输入密码，直接以管理员身份进入。按 **Create a new project**，再选择 **Blank project**，创建一个空白项目。

   ![项目列表，Create a new project 标红](/guide/zh/deploy_ayakaleaf_30_projects.webp "按 Create a new project")
   ![菜单展开了，Blank project 标红](/guide/zh/deploy_ayakaleaf_31_new_menu.webp "选择 Blank project")

1. 填写项目名称，再按 **Create**。编辑器打开后，左边是源码，右边是 PDF。如果要写中文，你要更换编译器：按左下角的齿轮，在 **Compiler** 里把 **pdfLaTeX** 换成 **XeLaTeX**，再按 Esc 关闭。中文宏包在第一次启动时已经安装，文档开头写 `\documentclass{ctexart}`。

   ![新项目的弹窗，Create 按钮标红](/guide/zh/deploy_ayakaleaf_32_new_name.webp "按 Create")
   ![设置弹窗，Compiler 一栏标红，选了 XeLaTeX](/guide/zh/deploy_ayakaleaf_33_compiler.webp "选择 XeLaTeX")

1. 写好后，按右边上方的 **Recompile**。编译好的 PDF 显示在右边。

   ![编辑器，Recompile 按钮标红](/guide/zh/deploy_ayakaleaf_34_editor.webp "按 Recompile")
   ![左边是源码，右边是编译好的中文 PDF](/guide/zh/deploy_ayakaleaf_35_pdf.webp "编译好的 PDF")

使用完后回到客户端按 **停止**。手机上的操作相同：在 **应用** 页按 **使用**，再按 **打开**。

## 分享

Ayakaleaf 能用[应用分享](/share/web_share)生成链接。每条链接有一个专用的访客账户，对方不用注册，也不用输入密码。

1. 在面板左侧栏点 **服务**，找到 **Ayakaleaf** 这一行，按 **分享**。

   ![服务页，Ayakaleaf 这一行的分享按钮标红](/guide/zh/deploy_ayakaleaf_20_services_share.webp)

1. 弹窗打开后，在 **名称** 里填写便于你自己识别的名称，对方看不到这个名称。**有效期** 默认是 7 天，你可以选择其他选项。选好后按 **生成链接**。立即按 **复制**，把链接发给对方。弹窗关闭后，面板不再显示这条链接，所以先不要关闭。

   ![分享弹窗，名称一栏标红](/guide/zh/deploy_ayakaleaf_21_share_dialog.webp "填写名称")
   ![分享弹窗填好了，生成链接按钮标红](/guide/zh/deploy_ayakaleaf_22_share_generate.webp "按 生成链接")
   ![分享弹窗显示链接和二维码，链接一行标红](/guide/zh/deploy_ayakaleaf_23_share_link.webp "按 复制")

弹窗里除了链接，下面还显示一个访客地址，形如 `guest-a1b2@share.neutrino`，图里的地址已换成示例。复制这个地址，接下来邀请对方时要用到，然后按 **完成** 关闭弹窗。分享的 **状态** 显示 **准备中** 时，稍后再操作。

对方进入后，只能看到你邀请这个访客地址加入的项目，所以你还要邀请一次。

打开项目，按右上角的 **Share**。在 **Add email address** 里粘贴访客地址，按 **Invite**。下面会多出一行，显示这个地址和 **Editor**。旁边显示的 **Invite not yet accepted.** 不用处理，对方打开链接时会自动接受。

![Share Project 弹窗，Invite 按钮标红](/guide/zh/deploy_ayakaleaf_36_share_project.webp "按 Invite")
![弹窗里多了一行访客地址](/guide/zh/deploy_ayakaleaf_37_invited.webp "多了一行")

这样对方打开链接后，会直接进入项目列表。

![访客的浏览器里打开了项目列表](/guide/zh/deploy_ayakaleaf_24_visitor.webp)

分享撤销或者到期后，这个访客账户也会删除，它修改过的内容保留在项目里。

## 注意

编译都在同一个容器里运行，彼此没有隔离，所以链接只发给你信任的人。

它占用的资源较多：空闲时约 1.6 GB 内存，磁盘约 5.5 GB。在 Windows 和 macOS 上，虚拟机要预留 3 GiB 内存，内存不足时标签会显示建议的值。内存不足不会阻止运行，只是速度变慢。

换版本时，TeX 宏包要重新安装，需要再等几分钟。

Ayakaleaf 限制每分钟最多下载 10 次 zip。超过后页面会显示错误，刷新页面后恢复。

Ayakaleaf 的 Git 同步功能不可用。

## 设置

除了版本，下面的设置保持默认即可。如果要修改，按标签上的 **配置** 打开。

![Ayakaleaf 的配置，AI 模型一栏](/guide/zh/deploy_ayakaleaf_47_config.webp)

| 设置                          | 位置            | 作用                                                              |
| ----------------------------- | --------------- | ----------------------------------------------------------------- |
| **AI 模型**                   | 标签的 **配置** | 编辑器里的 AI 助手使用的模型，要先配置 [AI 网关](/hub/ai_gateway) |
| **应用 Ayakaleaf 设置**       | 标签的 **配置** | 保存设置，Ayakaleaf 会重启，打开的编辑器会重新连接                |
| **更新**、**安装另一个版本…** | 标签的状态下面  | 更换版本，步骤见[换版本](/deploy/on_a_machine#换版本)             |

Ayakaleaf 只能升级，因为旧版本可能无法读取新版本迁移过的数据。**安装另一个版本…** 的列表里，比当前版本旧的版本是灰色的，不能选。

![版本列表，比当前版本旧的版本是灰色的](/guide/zh/deploy_ayakaleaf_44_version_dialog.webp)

## 卸载

在 **Ayakaleaf** 标签上按 **卸载**。弹窗里的红字提示，论文和项目都会删除，无法恢复。你要先在 Ayakaleaf 里下载需要保留的项目，确认后再按红色的 **卸载**。

![Ayakaleaf 标签，卸载按钮标红](/guide/zh/deploy_ayakaleaf_50_uninstall.webp "按 卸载")
![卸载的弹窗，红字提示数据会删除](/guide/zh/deploy_ayakaleaf_51_uninstall_dialog.webp "确认")

卸载 Ayakaleaf 时，容器不会一起卸载。

如果安装或启动停在某一步，查看[故障排查](/reference/troubleshooting)。
