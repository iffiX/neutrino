# 快速上手

你将安装中枢和 CloudCLI，然后用手机打开电脑上的 AI 会话。

下面以 CloudCLI 为例。CloudCLI 是 Claude Code 的网页界面。安装后，你可以在手机上让电脑上的 Claude Code 修改代码。其他应用的安装和使用方式相同。

## 开始之前

你要准备一台能访问互联网的电脑，系统是 Windows、macOS 或 Linux，并且你有它的管理员权限。这台电脑以后要一直开机，手机才能连接。

你还要准备一部 Android 手机，并让它和这台电脑连接同一个 Wi-Fi 或路由器。手机使用移动网络时暂时无法连接中枢。完成下面的步骤后，再开启一种外部访问，见[外部访问：选择一种方式](/access/ways_in)。如果你的手机是 iPhone，先按 [iOS 应用](/access/ios)安装 App，然后跳过下面下载和安装 App 的步骤。

## 第一步：安装中枢

中枢是安装在电脑上的程序，面板是它的网页，应用都从面板安装。

### 运行安装命令

1. 在电脑上打开终端。在 Linux 上打开“终端”程序，在 macOS 上打开“应用程序”里“实用工具”下的“终端”，在 Windows 上从开始菜单搜索并打开 PowerShell。

1. 复制下面的命令，粘贴到终端里，再按回车。如果你在中国大陆，选择国内版，下载速度更快。

   ::: code-group

   ```bash [Linux、macOS]
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
   ```

   ```powershell [Windows]
   irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
   ```

   ```bash [国内版 Linux、macOS]
   curl -fsSL https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.sh | sh
   ```

   ```powershell [国内版 Windows]
   irm https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.ps1 | iex
   ```

   :::

1. 脚本请求一次管理员权限。在 Linux 和 macOS 上，输入登录这台电脑的密码，输入时屏幕上不显示字符，输完按回车。在 Windows 上，系统弹出授权框，选“是”，之后查看新打开的窗口。

1. 等待脚本运行完成，终端会打印一个以 `http://` 开头、带 `?token=` 的地址。如果地址下面还有一行 `Press Enter to begin:`，不要按回车。

   ```text
   Installed neutrino-hub_0.6.0_amd64.deb
     The hub's service asks the same questions in a browser at:

       http://192.168.1.20:8080/?token=<向导令牌>

   NEUTRINO ─────────────────────────────────────
   ...
     Press Enter to begin:
   ```

### 完成设置向导

1. 复制这一整行地址，在浏览器里打开，然后按 **开始配置这台机器**。向导在你的屏幕上是深色的，下面的图是浅色的，按钮和文字都相同。下一屏是 **语言**，选择 **简体中文**，再按 **下一步**。

   ![向导的第一屏，开始配置的按钮标红](/guide/zh/hub_install_02_wizard_start.webp "按 开始配置这台机器")
   ![语言这一屏，下一步按钮标红](/guide/zh/hub_install_04_language_next.webp "选择 简体中文，按 下一步")

1. 设置 **面板密码** 和 **保险库口令**，每个都输入两次，再按 **下一步**。

   - **面板密码** 至少 8 个字符，你以后用它登录面板。
   - **保险库口令** 至少 16 个字符，要混用小写字母、大写字母、数字和符号。恢复备份时要用到它，所以你要记下来。

   ![两个密码都填好，下一步按钮标红](/guide/zh/hub_install_05_passwords.webp "设置两个密码，按 下一步")

1. 在 **这台机器做什么？** 这一屏选择 **服务器**，再按 **下一步**。笔记本和台式机都选择它，你的网络不会发生变化。

   ![选择用途这一屏，服务器标红](/guide/zh/hub_install_06_mode_server.webp "选择 服务器，按 下一步")

1. **用哪些网口？** 这一屏不用修改，直接按 **下一步**。下一屏也不用修改，让 **在这里设置** 保持关闭，再按 **下一步**。

   ![用哪些网口这一屏，下一步按钮标红](/guide/zh/hub_install_07_network.webp "不用修改，按 下一步")
   ![开关保持关闭，下一步按钮标红](/guide/zh/hub_install_08_exit.webp "保持关闭，按 下一步")

1. 在 **就绪** 这一屏按 **开始配置这台机器**。页面变成 **正在配置** 后，等待配置完成。看到 **这个中枢已配置好** 时，按 **打开面板**。

   ![就绪这一屏，开始配置的按钮标红](/guide/zh/hub_install_09_ready.webp "按 开始配置这台机器")
   ![这个中枢已配置好，打开面板按钮标红](/guide/zh/hub_install_11_done.webp "配置完成后，按 打开面板")

1. 用刚才设置的面板密码登录。登录后会进入 **总览** 页，这一步就完成了。

   ![密码已填好，登录按钮标红](/guide/zh/hub_install_13_login_press.webp "填写密码，按 登录")
   ![登录后的总览页](/guide/zh/hub_install_14_dashboard.webp "进入 总览 页")

如果向导报错或者你打不开向导，查看[安装中枢](/hub/install)和[故障排查](/reference/troubleshooting)。

## 第二步：在 AI 网关里登录 Claude 订阅

CloudCLI 通过中枢的 AI 网关使用 Claude，所以你不用在电脑上安装 Claude Code。下面用你的 Claude 订阅登录一次，费用由 Anthropic 决定。如果你使用 API 密钥，按 [AI 网关](/hub/ai_gateway) 的“添加 API 密钥”一节添加，再继续第三步。

1. 在面板左侧栏点 **AI**，在 **账号** 一栏按 **登录**，再在弹窗里选择 Claude。

   ![AI 页，账号一栏的登录按钮标红](/guide/zh/hub_ai_gateway_18_accounts.webp "按 登录")
   ![登录订阅的弹窗，列出可选的服务商](/guide/zh/hub_ai_gateway_08_sign_in.webp "选择 Claude")

1. 弹窗会显示一个地址。按 **复制**，在浏览器里打开这个地址，用你的 Claude 账号登录并同意。

1. 登录后，浏览器可能显示页面无法打开，这是正常现象。复制地址栏的内容，粘贴到弹窗的 **地址栏或验证码**，再按 **完成登录**。**账号** 一栏多出一行时，这一步就完成了。

   ![使用 Claude 登录的弹窗，有地址和输入框](/guide/zh/hub_ai_gateway_17_sign_in_step.webp "粘贴后按 完成登录")

## 第三步：在面板上安装 CloudCLI

1. 面板左侧栏的下半部分列出了每个加入中枢的系统。按这台电脑的名字，打开它的页面。再在 **可用账户** 一栏按 **添加**。

   ![左侧栏下半部分，这台电脑的名字标红](/guide/zh/deploy_on_a_machine_01_sidebar.webp "按这台电脑的名字")
   ![可用账户一栏，添加按钮标红](/guide/zh/deploy_on_a_machine_02_accounts_add.webp "按 添加")

1. 在 **系统账户** 里选择你平时登录这台电脑的账户。在 Windows 上，你还要在 **密码** 里填写这个账户的登录密码。如果你平时用 PIN 开机，这里也要填写密码，不是 PIN。再打开 **AI 工具使用中枢网关**，然后按 **保存**。如果这一栏已经列出这个账户，按这一行的 **编辑**，打开这个开关后保存。

   ![账户表单，系统账户选择框标红](/guide/zh/deploy_on_a_machine_03_account_form.webp "选择账户")
   ![账户表单，AI 工具使用中枢网关开关标红](/guide/zh/hub_ai_gateway_13_account_switch.webp "打开开关，按 保存")

1. 在 **模块配置** 一栏按 **+ 添加模块**。在弹窗里点 **CloudCLI** 的卡片，卡片亮起表示已选中，再按右下角的 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_cloudcli_01_add_module.webp "按 + 添加模块")
   ![CloudCLI 的卡片亮起，关闭按钮标红](/guide/zh/deploy_cloudcli_03_catalog_ticked.webp "点 CloudCLI，按 关闭")

1. 列表里会多出 **CloudCLI**，选中它，再按 **安装**。这一步要下载文件，页面上会显示步骤清单。标签显示 **已安装** 后，按 **启动**。

   ![CloudCLI 标签显示未安装，安装按钮标红](/guide/zh/deploy_cloudcli_05_install.webp "按 安装")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_cloudcli_07_installed.webp "按 启动")

1. 标签显示 **运行中，没有账户** 后，按 **配置**。在 **启用的账户** 里勾选你的账户。

   ![标签显示运行中，没有账户，配置按钮标红](/guide/zh/deploy_cloudcli_17_started.webp "按 配置")
   ![启用的账户一栏，账户这一行标红](/guide/zh/deploy_cloudcli_08_tick_account.webp "勾选账户")

1. 按 **应用 CloudCLI**。这时标签显示 **安装中**，正在运行 npm 这一步，第一次要几分钟到十几分钟。

   ![勾选了账户，应用 CloudCLI 按钮标红](/guide/zh/deploy_cloudcli_09_apply.webp "按 应用 CloudCLI")
   ![正在运行 npm 这一步](/guide/zh/deploy_cloudcli_10_npm_running.webp "等待 npm 这一步")

1. 标签显示 **运行中**，这一步就完成了。

   ![标签显示运行中](/guide/zh/deploy_cloudcli_11_running.webp)

## 第四步：把手机加入中枢

1. 在手机浏览器里打开发布页，可以选择[国际版](https://github.com/iffiX/neutrino/releases/latest)或[国内版](https://cnb.cool/iffi-X/neutrino/-/releases)。下载名字以 `android.apk` 结尾的文件，国内版的文件以 `android-cn.apk` 结尾。然后打开下载好的文件。

   ![手机浏览器里的发布页](/guide/zh/access_install_client_01_release_page.webp "下载 apk 文件")
   ![下载文件夹里的安装包](/guide/zh/access_install_client_02_downloaded.webp "打开安装包")

1. 第一次安装时，系统提示不允许安装来自此来源的未知应用。按 **设置**，打开 **允许来自此来源的应用** 开关，再按手机的返回键。系统显示 **要安装此应用吗？** 时，按 **安装**。

   ![系统的提示，设置按钮标红](/guide/zh/access_install_client_03_blocked.webp "按 设置")
   ![允许来自此来源的应用这个开关标红](/guide/zh/access_install_client_04_allow_source.webp "打开开关，按返回")
   ![要安装此应用吗的弹窗，安装按钮标红](/guide/zh/access_install_client_05_install.webp "按 安装")

1. 回到电脑上的面板，在左侧栏点 **客户端**，再按 **新建客户端链接**。在 **名称** 里填写“我的手机”，再按 **生成链接**。

   ![客户端页，新建客户端链接按钮标红](/guide/zh/access_join_01_clients.webp "按 新建客户端链接")
   ![填好名称的弹窗，生成链接按钮标红](/guide/zh/access_join_02_name.webp "填写名称，按 生成链接")

1. 弹窗会显示一个二维码，让弹窗保持打开。刚才安装的 App 名字叫 **微子**。在手机上打开这个 App，在 **中枢** 页按 **加入中枢**，再按 **允许使用相机**，然后把相机对准面板上的二维码。

   ![弹窗里的链接和二维码](/guide/zh/access_join_03_link.webp "面板上显示二维码")
   ![手机加入页，相机对准二维码](/guide/zh/access_android_05_camera_on.webp "用手机相机对准二维码")

1. 手机的 **中枢** 页上出现你的中枢这一行，并显示 **已连接 · 局域网**，这一步就完成了。回到面板，按 **完成** 关闭弹窗。

   ![手机中枢页，已连接](/guide/zh/access_android_07_joined.webp)

## 第五步：在手机上打开 CloudCLI

1. 在手机底栏按 **应用**，找到 **CloudCLI** 加你账户名的那一行，按 **使用**。系统请求通知权限时选“允许”，这个通知用来保持后台连接。这一行会多出一个 **打开** 按钮。按下这个按钮，手机浏览器就会打开 CloudCLI。这时已经登录，你不用输入密码。

   ![手机应用页，使用按钮](/guide/zh/access_android_11_use.webp "按 使用")
   ![通知权限的系统弹窗](/guide/zh/access_android_12_notify_prompt.webp "选择 允许")
   ![手机应用页，打开按钮](/guide/zh/access_android_13_open.webp "按 打开")

1. 第一次打开时显示英文设置页。填写 **Git Name** 和 **Git Email**，再按 **Next**。在 **Connect Your AI Agents** 这一屏，按 **Complete Setup**。下面的图拍自电脑浏览器，手机上内容相同，排版更窄。

   ![Git Configuration 这一屏，Git Name 一栏标红](/guide/zh/deploy_cloudcli_20_git_config.webp "填写后按 Next")
   ![Connect Your AI Agents 这一屏，Complete Setup 按钮标红](/guide/zh/deploy_cloudcli_22_connect_agents.webp "按 Complete Setup")

1. 进入 CloudCLI 的主页面后，如果你能打开电脑上的项目，并能和 Claude Code 对话，就全部完成了。如果你要换成中文，打开右边的 **Quick Settings**，在 **Language** 里选择 **简体中文**。

   ![CloudCLI 的主页面，右边的小箭头标红](/guide/zh/deploy_cloudcli_23_home.webp "电脑浏览器里的主页面")
   ![手机上的 CloudCLI](/guide/zh/access_android_14_browser.webp "手机上的同一页")

如果你要在外部网络使用，见[外部访问：选择一种方式](/access/ways_in)。如果你要把应用分享给别人，见[应用分享](/share/web_share)。
