---
title: "一键部署 AstrBot"
description: "微子中枢一键部署 AstrBot：Windows、macOS、Linux 都能装，用中枢的 AI 模型在 QQ、微信、飞书、Telegram 里自动回复。"
---

# AstrBot

AstrBot 是把大模型接进 QQ、微信、飞书这些聊天软件的机器人平台，自带网页管理台。机器人回复消息时，用的是中枢 AI 网关里的模型。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.2" />

AstrBot 运行在[容器](/deploy/containers)里，每个系统只运行一个实例。所有打开它的人看到的是同一套机器人、对话和插件。

## 支持的系统

| 系统    | 架构              | 开始支持的微子·中枢版本 |
| ------- | ----------------- | ----------------------- |
| Linux   | amd64、arm64      | 0.6.2                   |
| Windows | amd64             | 0.6.2                   |
| macOS   | Apple 芯片、Intel | 0.6.2                   |

## 安装

AstrBot 跟随默认账户的 **AI 工具使用中枢网关** 开关，开关打开时，机器人用的模型来自 AI 网关。开始之前，你要先到 [AI 网关](/hub/ai_gateway) 添加 API 密钥或者订阅账号，再在系统页面编辑默认账户，打开这个开关，步骤见[加入了中枢的系统](/hub/ai_gateway#加入了中枢的系统)。

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **AstrBot** 卡片，卡片上显示 **需要：容器**，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_astrbot_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，AstrBot 的卡片标红](/guide/zh/deploy_astrbot_02_catalog.webp "勾选 AstrBot")
   ![AstrBot 的卡片亮了，关闭按钮标红](/guide/zh/deploy_astrbot_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **AstrBot** 这一行，右边会显示它的标签。按 **安装**。如果容器还没有安装，会先弹出确认框，按 **是** 会一起安装两个模块。图中的容器已经安装，所以没有弹出确认框。

   ![模块列表，AstrBot 这一行标红](/guide/zh/deploy_astrbot_04_tab.webp "点 AstrBot")
   ![AstrBot 标签显示未安装，安装按钮标红](/guide/zh/deploy_astrbot_05_install.webp "按 安装")

1. 在 Windows 和 macOS 上第一次安装时，接着会弹出 **运行设置**。确认 **CPU 数**、**内存（GiB）** 和 **磁盘上限（GiB）**，再按 **安装**。在 Windows 上，如果要重启，标签上会出现 **立即重启**，电脑重启后会自动继续安装。详细步骤见[依赖容器的应用](/deploy/on_a_machine#依赖容器的应用)。Linux 上没有这个弹窗。

   ![运行设置的弹窗，安装按钮标红](/guide/zh/containers_run_settings.webp)

1. 标签会列出每一步。它要拉取一个约 723 MB 的镜像，需要几分钟。标签变成 **已安装** 后，按 **启动**。

   ![标签显示安装中，下面列出每一步](/guide/zh/deploy_astrbot_06_installing.webp "安装中")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_astrbot_07_installed.webp "按 启动")

1. 这一步会运行 **首次启动**，通常一分钟左右。标签变成 **运行中**，这时安装完成。

   ![标签正在运行首次启动这一步](/guide/zh/deploy_astrbot_08_first_start.webp "首次启动")
   ![标签显示运行中](/guide/zh/deploy_astrbot_09_running.webp "运行中")

## 使用

### 打开 AstrBot

开始之前，你要先把手机或电脑加入中枢，见[加入中枢](/access/join)。

1. 打开客户端，进入 **应用** 页，找到 **AstrBot** 这一行。按 **使用**。这一行会多出一个本机地址，按钮变成 **停止**、**配置** 和 **打开**。按 **打开**。

   ![客户端的应用页，使用按钮标红](/guide/zh/deploy_astrbot_40_client_use.webp "按 使用")
   ![这一行有了本机地址，打开按钮标红](/guide/zh/deploy_astrbot_41_client_open.webp "按 打开")

1. 浏览器直接进入已登录的 AstrBot 管理台，不用输入密码。第一次打开时会先弹出欢迎对话框，按底部的 **关闭**。机器人、插件和人格都在这个页面里添加。默认账户的 **AI 工具使用中枢网关** 打开时，AstrBot 已经接好 AI 网关，默认使用网关的[默认模型](/hub/ai_gateway#默认模型)。

   ![浏览器里的 AstrBot 管理台](/guide/zh/deploy_astrbot_24_main.webp)

使用完后回到客户端按 **停止**。手机上的操作相同：在 **应用** 页按 **使用**，再按 **打开**。机器人一直在系统上运行，不受客户端的 **停止** 影响。

### 能接的聊天平台

下面这些平台由 AstrBot 主动连接平台的服务器，消息从这条连接收发，所以可以接：

| 平台                  | 连接方式                  |
| --------------------- | ------------------------- |
| QQ 官方机器人         | WebSocket                 |
| 个人微信              | 腾讯官方的 iLink，扫码    |
| 企业微信智能机器人    | 长连接                    |
| 飞书、Lark            | 长连接                    |
| 钉钉                  | Stream                    |
| Telegram              | 长轮询                    |
| Discord               | Gateway                   |
| Slack                 | Socket Mode               |
| Misskey、KOOK、Satori | WebSocket                 |
| Mattermost            | WebSocket，消息按钮不能用 |

下面这些平台用 Webhook 方式收发消息：平台的服务器把每条消息发到你提供的一个公网 HTTPS 地址。中枢不给 AstrBot 提供公网地址，所以这些平台接不了。个人微信能接，微信公众号接不了：

| 平台                                            | 原因              |
| ----------------------------------------------- | ----------------- |
| 微信公众号                                      | 只有 Webhook 方式 |
| 企业微信应用、微信客服                          | 只有 Webhook 方式 |
| QQ 官方机器人的 Webhook 方式                    | 要公网回调地址    |
| LINE                                            | 只有 Webhook 方式 |
| 飞书、企业微信智能机器人、Slack 的 Webhook 方式 | 要公网回调地址    |

### 连接 NapCat

AstrBot 不带 NapCat。如果你在同一个系统上自己安装了 NapCat，打开 NapCat 的 OneBot v11 设置，填写 `127.0.0.1:6199`。这是 AstrBot 的默认端口。在 AstrBot 里添加 OneBot v11 机器人后，它马上开始等待 NapCat 连接，不用重启。

这个端口只在本机打开，别的电脑和客户端都连不到。

## 分享

AstrBot 能用[应用分享](/share/web_share)生成链接，对方用浏览器就能打开。

1. 在面板左侧栏点 **服务**，找到 **AstrBot** 这一行，按 **分享**。

   ![服务页，AstrBot 这一行的分享按钮标红](/guide/zh/deploy_astrbot_20_services_share.webp)

1. 弹窗打开后，在 **名称** 里填写便于你自己识别的名称，对方看不到这个名称。**有效期** 默认是 7 天，你可以选择其他选项。选好后按 **生成链接**。立即按 **复制**，把链接发给对方，再按 **完成** 关闭弹窗。弹窗关闭后，面板不再显示这条链接。

   ![分享弹窗，名称一栏标红](/guide/zh/deploy_astrbot_21_share_dialog.webp "填写名称")
   ![分享弹窗填好了，生成链接按钮标红](/guide/zh/deploy_astrbot_22_share_generate.webp "按 生成链接")
   ![分享弹窗显示链接和二维码，链接一行标红](/guide/zh/deploy_astrbot_23_share_link.webp "按 复制")

弹窗里的黄色提示说明，访客会以 astrbot 的身份使用这个应用，astrbot 是 AstrBot 管理台唯一的账户。对方打开链接后不用登录，直接进入管理台，能修改你的机器人、插件和对话，直到分享撤销或者到期。

## 注意

所有打开 AstrBot 的人共用同一套机器人、对话和插件，用的也是你的 AI 额度。

AstrBot 管理台里有几项设置由中枢负责，在页面里修改会失败：密码和用户名、两步验证、SSL、端口和监听地址。AstrBot 自己的更新按钮也不能用，换版本见下面的“设置”一节。

在 AstrBot 里退出登录，或者登录过了 7 天，页面会显示 AstrBot 的登录框，这个登录框无法登录。回到客户端重新按 **打开** 即可。

如果这个系统上已经有其他程序占用了 `127.0.0.1:6199`，AstrBot 无法启动。

它空闲时约占 300 到 400 MB 内存，镜像约占 2.0 GB 磁盘，插件越多，数据越大。在 Windows 和 macOS 上，所有容器应用共用一台虚拟机的内存，这个应用需要 1 GiB。

容器停止后，AstrBot 也显示 **已停止**。容器再次启动后，它也恢复运行。

## 设置

它没有 **配置** 按钮，标签里只有状态、日志和操作按钮。机器人、插件和模型都在 AstrBot 的管理台里设置。

AstrBot 的默认模型跟着 AI 网关的默认模型变。中枢还把这个模型的[上下文长度](/hub/ai_gateway#上下文长度)写进 AstrBot，对话超过这个长度时，AstrBot 会压缩对话。中枢添加的模型名称以 `neutrino_gateway/` 开头。如果你在 AstrBot 里把默认模型换成了别的模型，中枢不再改默认模型。要重新跟着 AI 网关变，把默认模型选回中枢添加的那一个。

关掉默认账户的 **AI 工具使用中枢网关** 时，中枢从 AstrBot 里删除它添加的提供方。如果默认模型是中枢添加的模型，默认模型也会清空。你自己添加的提供方和你选的默认模型都保留。再打开这个开关，中枢重新添加。

在 AstrBot 里给 AI 网关这个来源添加模型时，获取模型列表的按钮会报错，直接填写模型名称即可。名称就是 AI 网关里显示的模型名称。

| 设置                          | 位置           | 作用                                                  |
| ----------------------------- | -------------- | ----------------------------------------------------- |
| **更新**、**安装另一个版本…** | 标签的状态下面 | 更换版本，步骤见[换版本](/deploy/on_a_machine#换版本) |

AstrBot 只能升级，因为它第一次启动新版本时会迁移数据，旧版本读不了迁移过的数据。**安装另一个版本…** 的列表里，比当前版本旧的版本是灰色的，不能选。换版本时，机器人、插件和设置都保留。

## 卸载

在 **AstrBot** 标签上按 **卸载**。弹窗里的红字提示，机器人、对话、插件和设置都会删除，无法恢复。你要先在 AstrBot 管理台里备份需要保留的内容，确认后再按红色的 **卸载**。

![AstrBot 标签，卸载按钮标红](/guide/zh/deploy_astrbot_50_uninstall.webp "按 卸载")
![卸载的弹窗，红字提示数据会删除](/guide/zh/deploy_astrbot_51_uninstall_dialog.webp "确认")

AstrBot 的镜像在没有别的容器使用时一起删除。卸载 AstrBot 时，容器模块不会一起卸载。

如果 AstrBot 无法启动，查看[故障排查](/reference/troubleshooting)。
