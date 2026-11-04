# 面板菜单对照表

面板菜单对照表是面板上每个菜单名和手册页的对应关系。

面板左边的侧栏分两栏，**中枢** 这一栏是固定的页面，**被控端** 这一栏是加入中枢的每个系统。

## 中枢一栏

下面的图用红框标出每个菜单在侧栏上的位置。

| 菜单         | 英文界面    | 内容                                                                 | 手册页                                               | 图                                                                                |
| ------------ | ----------- | -------------------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------- |
| **总览**     | Dashboard   | 实时吞吐和被控端计数                                                 | [总览](/hub/dashboard)                               | ![总览页，侧栏的总览标红](/guide/zh/reference_panel_menu_01_dashboard.webp)       |
| **网络**     | Network     | 模式、开放范围、面板端口和连接端口                                   | [网络形态：服务器、路由器、旁路网关](/hub/network)   | ![网络页，侧栏的网络标红](/guide/zh/reference_panel_menu_02_network.webp)         |
| **外部访问** | Access      | 六张卡片：NetBird、EasyTier、SSH 中继、直连、SakuraFrp、OpenFrp      | [外部访问：选择一种方式](/access/ways_in)            | ![外部访问页，侧栏的外部访问标红](/guide/zh/reference_panel_menu_03_overlay.webp) |
| **代理**     | Proxy       | 出口、分流和 DNS                                                     | [代理](/hub/proxy)                                   | ![代理页，侧栏的代理标红](/guide/zh/reference_panel_menu_04_proxy.webp)           |
| **AI**       | AI          | 所有 AI 工具共用的端点、提供方和用量                                 | [AI 网关](/hub/ai_gateway)                           | ![AI 页，侧栏的 AI 标红](/guide/zh/reference_panel_menu_05_ai.webp)               |
| **被控端**   | Agents      | 每行一个系统，右上角有 **用链接添加** 和 **用 SSH 添加**             | [被控端](/hub/agents)                                | ![被控端页，侧栏的被控端标红](/guide/zh/reference_panel_menu_06_agents.webp)      |
| **客户端**   | Clients     | 上面是 **客户端** 面板，下面是 **应用分享** 面板                     | [客户端](/hub/clients)、[应用分享](/share/web_share) | ![客户端页，侧栏的客户端标红](/guide/zh/reference_panel_menu_07_clients.webp)     |
| **服务**     | Services    | **应用**、**AI**、**文件**、**远程桌面** 四节，右上角有 **声明应用** | [加入已有的服务](/deploy/services)                   | ![服务页，侧栏的服务标红](/guide/zh/reference_panel_menu_08_services.webp)        |
| **凭据**     | Credentials | **SSH 密钥**、**登录信息**、**令牌** 和 **中枢生成的**               | [数据和外连](/hub/what_it_holds)                     | ![凭据页，侧栏的凭据标红](/guide/zh/reference_panel_menu_09_credentials.webp)     |
| **设置**     | Settings    | 密码、备份和版本                                                     | [设置：备份、更新、密码](/hub/settings)              | ![设置页，侧栏的设置标红](/guide/zh/reference_panel_menu_10_settings.webp)        |

## 被控端一栏

每个加入中枢的系统占一项，显示它的名字。点开就是这个系统的页面，你在这个页面上安装应用，步骤见[在一个系统上安装应用](/deploy/on_a_machine)。

![一个系统的页面，侧栏的 my-computer 标红](/guide/zh/reference_panel_menu_11_machine.webp)

这个页面从上到下分为三部分：**监控**、**模块** 和 **被控端本身**。

| 部分           | 内容                                               |
| -------------- | -------------------------------------------------- |
| **监控**       | 运行时间、负载、磁盘、温度、CPU 和内存曲线、进程表 |
| **模块**       | **可用账户**、**模块配置**                         |
| **被控端本身** | 版本、**更新被控端**、**重新安装**                 |

## 模块配置里的标签

**模块配置** 左边的每一行是一个应用，点开就是它的标签。标签标题后面的两个小标签是来源和种类，含义见[应用的分类](/deploy/app_kinds)。各标签按下表的顺序排列，对应的手册页如下。

| 标签             | 手册页                               |
| ---------------- | ------------------------------------ |
| **终端**         | [终端](/deploy/terminal)             |
| **SSH 服务器**   | [SSH](/deploy/ssh)                   |
| **远程桌面**     | [远程桌面](/deploy/remote_desktop)   |
| **文件共享**     | [文件共享](/deploy/file_share)       |
| **Gitea**        | [Gitea](/deploy/gitea)               |
| **VS Code**      | [VS Code](/deploy/vscode)            |
| **code-server**  | [code-server](/deploy/code_server)   |
| **CloudCLI**     | [CloudCLI](/deploy/cloudcli)         |
| **Codeg**        | [Codeg](/deploy/codeg)               |
| **思源笔记**     | [思源笔记](/deploy/siyuan)           |
| **容器**         | [容器](/deploy/containers)           |
| **Hermes WebUI** | [Hermes WebUI](/deploy/hermes_webui) |
| **Ayakaleaf**    | [Ayakaleaf](/deploy/ayakaleaf)       |

## 外部访问的卡片

**外部访问** 页的各张卡片对应的手册页如下。

| 卡片          | 手册页                         |
| ------------- | ------------------------------ |
| **NetBird**   | [NetBird](/access/netbird)     |
| **EasyTier**  | [EasyTier](/access/easytier)   |
| **SSH 中继**  | [SSH 中继](/access/vps)        |
| **直连**      | [直连](/access/direct)         |
| **SakuraFrp** | [SakuraFrp](/access/sakurafrp) |
| **OpenFrp**   | [OpenFrp](/access/openfrp)     |

## 窄屏和旧名字

在窄屏和竖屏上，比如手机的浏览器，侧栏会变成底部一排图标，只有 **中枢** 这一栏的页面。要进入一个系统的页面，先点 **被控端** 图标。

![手机宽度的面板，底部一排图标标红](/guide/zh/reference_panel_menu_12_phone.webp)

如果你用过 0.5，**设备** 页现在叫 **被控端**。**终端**、**文件**、**模块** 三页已删除，它们都在系统的页面上。

侧栏底部的 **退出登录** 是一个按钮，不是页面。
