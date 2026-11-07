# Hermes WebUI

Hermes WebUI 是 AI 助手 Hermes Agent 的网页界面。Hermes Agent 支持记忆和技能，你可以在手机上随时打开它。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.0" />

Hermes WebUI 运行在[容器](/deploy/containers)里，每个系统只运行一个实例，所有使用它的人共用同一份对话。

## 支持的系统

| 系统    | 架构              | 开始支持的微子·中枢版本 |
| ------- | ----------------- | ----------------------- |
| Linux   | amd64、arm64      | 0.6.0                   |
| Windows | amd64             | 0.6.0                   |
| macOS   | Apple 芯片、Intel | 0.6.0                   |

## 安装

开始之前，你要先到 [AI 网关](/hub/ai_gateway) 添加 API 密钥或者订阅账号，Hermes WebUI 的模型都来自 AI 网关。

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **Hermes WebUI** 卡片，卡片上显示 **需要：容器**，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_hermes_webui_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，Hermes WebUI 的卡片标红](/guide/zh/deploy_hermes_webui_02_catalog.webp "勾选 Hermes WebUI")
   ![Hermes WebUI 的卡片亮了，关闭按钮标红](/guide/zh/deploy_hermes_webui_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **Hermes WebUI** 这一行，右边会显示它的标签。按 **安装**。如果容器还没有安装，会先弹出确认框，按 **是** 会一起安装两个模块。图中的容器已经安装，所以没有弹出确认框。

   ![模块列表，Hermes WebUI 这一行标红](/guide/zh/deploy_hermes_webui_04_tab.webp "点 Hermes WebUI")
   ![Hermes WebUI 标签显示未安装，安装按钮标红](/guide/zh/deploy_hermes_webui_05_install.webp "按 安装")

1. 在 Windows 和 macOS 上第一次安装时，接着会弹出 **选择运行容器的账户**。选择账户，再按 **安装**，详细步骤见[依赖容器的应用](/deploy/on_a_machine#依赖容器的应用)。Linux 上没有这个弹窗。

   ![选择运行容器的账户的弹窗](/guide/zh/windows_account_dialog.webp)

1. 在 Windows 上，如果要重启，这个标签会显示提示，旁边有 **立即重启**。按 **立即重启**，电脑重启后会自动继续安装。

   ![Hermes WebUI 标签显示 Windows 需要重启，立即重启按钮标红](/guide/zh/deploy_hermes_webui_10_reboot.webp)

1. 标签会列出每一步。它要拉取两个镜像，需要几分钟。标签变成 **已安装** 后，按 **启动**。

   ![标签显示安装中，下面列出每一步](/guide/zh/deploy_hermes_webui_06_installing.webp "安装中")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_hermes_webui_07_installed.webp "按 启动")

1. 这一步会运行 **首次启动**，第一次需要几分钟。标签变成 **运行中**，这时安装完成。

   ![标签正在运行首次启动这一步](/guide/zh/deploy_hermes_webui_08_first_start.webp "首次启动")
   ![标签显示运行中](/guide/zh/deploy_hermes_webui_09_running.webp "运行中")

## 使用

开始之前，你要先把手机或电脑加入中枢，见[加入中枢](/access/join)。

1. 打开客户端，进入 **应用** 页，找到 **Hermes WebUI** 这一行。按 **使用**。这一行会多出一个本机地址，按钮变成 **停止**、**配置** 和 **打开**。按 **打开**。

   ![客户端的应用页，使用按钮标红](/guide/zh/deploy_hermes_webui_40_client_use.webp "按 使用")
   ![这一行有了本机地址，打开按钮标红](/guide/zh/deploy_hermes_webui_41_client_open.webp "按 打开")

1. 浏览器直接进入已登录的页面。在下面的输入框里填写你要问的内容，然后发送。新对话使用 AI 网关的[默认模型](/hub/ai_gateway#默认模型)。输入框旁边可以换模型，列表里是 AI 网关正在提供的模型。

   ![浏览器里的 Hermes WebUI](/guide/zh/deploy_hermes_webui_24_visitor.webp)

![Hermes WebUI 里的一次对话，下面的模型是 deepseek-flash](/guide/zh/deploy_hermes_webui_30_chat.webp)

使用完后回到客户端按 **停止**。手机上的操作相同：在 **应用** 页按 **使用**，再按 **打开**。

## 分享

Hermes WebUI 能用[应用分享](/share/web_share)生成链接，对方用浏览器就能打开。

1. 在面板左侧栏点 **服务**，找到 **Hermes WebUI** 这一行，按 **分享**。

   ![服务页，Hermes WebUI 这一行的分享按钮标红](/guide/zh/deploy_hermes_webui_20_services_share.webp)

1. 弹窗打开后，在 **名称** 里填写便于你自己识别的名称，对方看不到这个名称。**有效期** 默认是 7 天，你可以选择其他选项。选好后按 **生成链接**。立即按 **复制**，把链接发给对方，再按 **完成** 关闭弹窗。弹窗关闭后，面板不再显示这条链接。

   ![分享弹窗，名称一栏标红](/guide/zh/deploy_hermes_webui_21_share_dialog.webp "填写名称")
   ![分享弹窗填好了，生成链接按钮标红](/guide/zh/deploy_hermes_webui_22_share_generate.webp "按 生成链接")
   ![分享弹窗显示链接和二维码，链接一行标红](/guide/zh/deploy_hermes_webui_23_share_link.webp "按 复制")

弹窗里的黄色提示显示的账户是 hermeswebui，这是 Hermes WebUI 在容器里使用的账户。对方打开链接后不用登录，看到的就是上面的页面。

## 注意

所有使用它的人共用一份对话、记忆和工作区。对方能看到你的对话，使用的也是你的 AI 额度。

Hermes 页面里自己生成的分享链接，只有登录过的浏览器才能打开。

它占用的磁盘空间如下：镜像约 3.2 GB，缓存约 2.4 GB。在 Windows 和 macOS 上，所有容器应用共用一台虚拟机的内存，这个应用需要 1 GiB。

容器停止后，Hermes WebUI 也显示 **已停止**。容器再次启动后，它也恢复运行。

## 设置

它没有 **配置** 按钮，标签里只有状态、日志和操作按钮。要换模型，在 Hermes 的页面里选择。

Hermes 的页面默认是深色的。如果你要换成浅色，按页面左下角的齿轮，在 **外观** 的 **主题** 里选择 **Light**。

![外观页面，主题里的 Light 标红](/guide/zh/deploy_hermes_webui_25_theme.webp)

它的版本是锁定的，**安装另一个版本…** 的弹窗里只有一个无法点击的版本。两个镜像是测试过的一对，会随微子·中枢的新版本更新。

## 卸载

在 **Hermes WebUI** 标签上按 **卸载**。弹窗里的红字提示，对话、设置和工作区里的文件都会删除，无法恢复。你要先把需要保留的内容复制出来，确认后再按红色的 **卸载**。

![Hermes WebUI 标签，卸载按钮标红](/guide/zh/deploy_hermes_webui_50_uninstall.webp "按 卸载")
![卸载的弹窗，红字提示数据会删除](/guide/zh/deploy_hermes_webui_51_uninstall_dialog.webp "确认")

卸载 Hermes WebUI 时，容器不会一起卸载。

如果 Hermes WebUI 无法启动，查看[故障排查](/reference/troubleshooting)。
