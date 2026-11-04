# Gitea

Gitea 是可以自行部署的代码托管服务，类似 GitHub。代码保存在你自己的电脑上，你也可以和别人一起管理仓库。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.2.0" />

每个系统只运行一个实例。Gitea 有自己的运行账户，所以你不用选择账户。

## 支持的系统

| 系统    | 架构              | 开始支持的微子·中枢版本 | git                                    |
| ------- | ----------------- | ----------------------- | -------------------------------------- |
| Linux   | amd64、arm64      | 0.2.0                   | 安装时一起安装                         |
| Windows | amd64             | 0.5.0                   | 你要先安装 Git for Windows             |
| macOS   | Apple 芯片、Intel | 0.5.0                   | 你要先安装开发者工具或 Homebrew 的 git |

## 安装

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **Gitea** 卡片，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_gitea_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，Gitea 的卡片标红](/guide/zh/deploy_gitea_02_catalog.webp "勾选 Gitea")
   ![Gitea 的卡片亮了，关闭按钮标红](/guide/zh/deploy_gitea_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **Gitea** 这一行，右边会显示它的标签。按 **安装**。

   ![模块列表，Gitea 这一行标红](/guide/zh/deploy_gitea_04_tab.webp "点 Gitea")
   ![Gitea 标签显示未安装，安装按钮标红](/guide/zh/deploy_gitea_05_install.webp "按 安装")

1. 标签会列出每一步。在 Linux 上，它还会安装系统软件包 git。标签变成 **已安装** 后，按 **启动**。

   ![标签显示安装中，下面列出每一步](/guide/zh/deploy_gitea_06_installing.webp "安装中")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_gitea_07_installed.webp "按 启动")

1. 标签变成 **运行中**。按 **配置**，下面会展开设置。在 **管理员** 区域填写 **用户名** 和 **密码**，你以后用它们登录 Gitea。**邮箱（可选）** 可以不填。

   ![标签显示运行中，配置按钮标红](/guide/zh/deploy_gitea_17_started.webp "按 配置")
   ![管理员区域，用户名一栏标红](/guide/zh/deploy_gitea_08_config.webp "填写用户名和密码")

1. 按 **创建管理员**。**管理员** 旁边显示 **已存在**，下面列出这个用户名，这时安装完成。

   ![填好了用户名和密码，创建管理员按钮标红](/guide/zh/deploy_gitea_09_admin_create.webp "按 创建管理员")
   ![管理员区域显示已存在](/guide/zh/deploy_gitea_10_admin_created.webp "已存在")

## 使用

开始之前，你要先把手机或电脑加入中枢，见[加入中枢](/access/join)。

1. 打开客户端，进入 **应用** 页，找到 **Gitea** 这一行。这一行下面有两个地址，一个是网页地址，一个是 git 使用的 SSH 地址。按 **使用**，再按 **打开**。

   ![客户端的应用页，使用按钮标红](/guide/zh/deploy_gitea_40_client_use.webp "按 使用")
   ![Gitea 这一行，打开按钮标红](/guide/zh/deploy_gitea_41_client_open.webp "按 打开")

1. 浏览器会打开 Gitea 的首页，按右上角的 **登录**。填写你刚才设置的用户名和密码，再按 **登录**。

   ![Gitea 首页，登录按钮标红](/guide/zh/deploy_gitea_42_home.webp "按 登录")
   ![登录页，登录按钮标红](/guide/zh/deploy_gitea_43_login.webp "填写后按 登录")

1. 登录后进入你的主页。如果要新建仓库，点右上角的 **+**。在 **仓库名称** 里填写名称，其他项都可以不改，往下翻按 **创建仓库**。

   ![登录后的主页](/guide/zh/deploy_gitea_44_dashboard.webp "点 +")
   ![创建仓库页，仓库名称一栏标红](/guide/zh/deploy_gitea_45_new_repo.webp "填写仓库名称")

1. 仓库创建完成，页面上显示克隆地址和要运行的命令。

   ![新仓库的页面，显示克隆地址](/guide/zh/deploy_gitea_46_repo.webp)

你在客户端按 **使用** 后，git 就能使用页面上的克隆地址。如果用 SSH 地址克隆，先在 Gitea 的网页里添加你的 SSH 密钥。

![有两个文件的仓库首页，下面显示 README](/guide/zh/deploy_gitea_47_repo_files.webp)

## 分享

Gitea 能用[应用分享](/share/web_share)生成链接。

1. 在面板左侧栏点 **服务**，找到 **Gitea** 这一行，按 **分享**。

   ![服务页，Gitea 这一行的分享按钮标红](/guide/zh/deploy_gitea_20_services_share.webp)

1. 弹窗打开后，在 **名称** 里填写便于你自己识别的名称，对方看不到这个名称。**有效期** 默认是 7 天，你可以选择其他选项。选好后按 **生成链接**。立即按 **复制**，把链接发给对方，再按 **完成** 关闭弹窗。弹窗关闭后，面板不再显示这条链接。

   ![分享弹窗，名称一栏标红](/guide/zh/deploy_gitea_21_share_dialog.webp "填写名称")
   ![分享弹窗填好了，生成链接按钮标红](/guide/zh/deploy_gitea_22_share_generate.webp "按 生成链接")
   ![分享弹窗显示链接和二维码，链接一行标红](/guide/zh/deploy_gitea_23_share_link.webp "按 复制")

对方打开链接后，看到的是 Gitea 自己的首页，对方要自己登录。你在 Gitea 里给对方创建账号后，对方就能登录。

![访客的浏览器里打开了 Gitea 首页](/guide/zh/deploy_gitea_24_visitor.webp)

## 注意

打开 **开放注册** 后，持有分享链接的人都能自己创建账号。

账号和仓库都在 Gitea 自己的网页里管理，面板只管理第一个管理员。

## 设置

除了管理员，下面的设置保持默认即可。

| 设置                          | 位置           | 作用                           |
| ----------------------------- | -------------- | ------------------------------ |
| **开放注册**                  | **接入**       | 访客能否自己创建账号，默认关闭 |
| **端口**、**Root URL**        | **接入**       | 通常不用修改                   |
| **应用接入设置**              | **接入**       | 保存上面几项，Gitea 会重启     |
| **重置密码**                  | **管理员**     | 重置管理员的密码               |
| **更新**、**安装另一个版本…** | 标签的状态下面 | 更换版本，步骤见表格下方       |

如果要更换版本，先查看标签上的这一行：`已安装 1.27.3 · 最新 28.3.0`。前面是当前版本，后面是发布者的最新版本。

1. 按 **安装另一个版本…**。弹窗里新版本排在上面，标 **已测试** 的是测试过的版本。点你要的版本。

   ![版本这一行，安装另一个版本按钮标红](/guide/zh/deploy_gitea_30_version_button.webp "按 安装另一个版本")
   ![版本列表，一个旧版本标红](/guide/zh/deploy_gitea_31_version_dialog.webp "点版本")

1. 新版本启动时会迁移数据，旧版本可能无法读取迁移过的数据。所以你选择更旧的版本时，面板先弹窗提醒。如果你要放弃，按 **取消**。

   ![换到旧版本时的提醒弹窗，取消按钮标红](/guide/zh/deploy_gitea_32_downgrade_dialog.webp)

1. 旁边的 **更新** 直接切换到最新版本，标签列出 **切换到版本** 这几步，完成后恢复为 **运行中**。

   ![版本这一行，更新按钮标红](/guide/zh/deploy_gitea_33_update_button.webp "按 更新")
   ![标签恢复为运行中，版本这一行显示新版本](/guide/zh/deploy_gitea_35_updated.webp "切换完成")

## 卸载

在 **Gitea** 标签上按 **卸载**。弹窗说明，仓库、Gitea 的账户和数据库都保留在它的数据目录里。确认后按 **卸载**。

![Gitea 标签，卸载按钮标红](/guide/zh/deploy_gitea_50_uninstall.webp "按 卸载")
![卸载的弹窗，卸载按钮标红](/guide/zh/deploy_gitea_51_uninstall_dialog.webp "确认")

再次安装后，原来的仓库和账户仍然可以使用。

如果安装失败，查看[故障排查](/reference/troubleshooting)。
