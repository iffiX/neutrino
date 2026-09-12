---
title: 快速上手
---

# 快速上手

快速上手只走一条最短的路。hub 选服务器形态；第二台 Linux 机器用链接接入，做被控端；一台 Linux 电脑装客户端；最后发布一个共享并挂上。走完之后，一个共享出现在客户端的家目录下。服务器形态不改机器上的任何地址，也不让任何设备经它上网。

## 你需要什么

- hub 装在一台常开的 64 位 Linux 机器上，这台机器带 systemd，能出网。树莓派、刷过系统的电视盒子或旧笔记本都行。本页叫它 `home-hub`。
- 第二台 Linux 机器做被控端，本页叫它 `studio`。
- 一台装桌面环境的 Linux 电脑跑客户端，本页叫它 `laptop`。
- 三台机器在同一个网里，三个包同一个版本，都从 [Releases](https://github.com/iffiX/neutrino/releases) 下载。

## 装 hub 并初始化

### 安装包并启动向导

1. 在 `home-hub` 上安装包。

   ```bash
   sudo apt install ./neutrino-hub_0.2.0_amd64.deb
   ```

1. 启动向导。

   ```bash
   sudo nhub setup
   ```

   终端打印一个带一次性令牌的地址；这台机器有浏览器时，向导在浏览器里打开。

1. 在浏览器里点 **开始配置这台机器**（Set this box up）。

![向导的欢迎页](/guide/zh/setup_welcome.webp)

### 回答六屏问题

1. **语言**（Language）：选简体中文，点 **下一步**（Next）。
1. **面板密码，以及保险库口令**（A password for the panel, a passphrase for the vault）：填一个面板密码和一个保险库主口令。
1. **这台机器做什么？**（What is this machine for?）：选 **服务器**（Server）。

   ![形态屏，服务器已选中](/guide/zh/setup_shape.webp)

1. **用哪些网口？**（Which ports?）：面板端口保持 8080。
1. **通过代理出网**（Going out through a proxy）：不勾选，直接下一步。
1. **就绪**（Ready）：核对一遍，确认。

   ![就绪屏](/guide/zh/setup_review.webp)

1. 等步骤列表跑完，点 **打开面板**（Open the panel）。

![初始化完成](/guide/zh/setup_done.webp)

::: warning
保险库主口令封存这台机器保管的每一份凭据，恢复备份时还要再输一次。这个口令在机器上没有备份，记在面板之外的地方。
:::

## 登录看一眼

1. 在浏览器里打开 `http://<hub-address>:8080`，其中 `<hub-address>` 是 `home-hub` 的地址。

   ![登录页](/guide/zh/login.webp)

1. 在 **面板密码**（Panel password）里填第二屏设的密码，点 **登录**（Sign in）。

登录后是 **总览**（Dashboard）页。侧栏分两组：**Hub** 组十页，**被控端**（Agent）组六页。

![总览页](/guide/zh/dashboard.webp)

## 接入第二台机器

1. 打开 **设备**（Devices）页。`home-hub` 自己已经在 **已管理的设备**（Managed devices）里，因为初始化时装了它自己的被控端。
1. 点 **用链接添加**（Add by link）。

   ![加入链接](/guide/zh/devices_enroll_link.webp)

1. 点通知里的 **复制**（Copy）。链接五分钟内有效。
1. 在 `studio` 上安装被控端。

   ```bash
   sudo apt install ./neutrino-agent_0.2.0_amd64.deb
   ```

1. 在 `studio` 上用刚复制的链接接入。

   ```bash
   sudo nagent connect 'neutrino://enroll/PLACEHOLDER_LINK'
   ```

   命令返回后几秒内，`studio` 出现在 **已管理的设备** 里。

![两台已管理的设备](/guide/zh/devices_managed.webp)

## 装客户端

1. 在面板里打开 **客户端**（Clients）页，点 **新建客户端链接**（New client link）。

   ![新建客户端链接](/guide/zh/clients_create_link.webp)

1. 名称填 `laptop`，点 **创建链接**（Create link），然后点 **复制**。
1. 在 `laptop` 上安装客户端。

   ```bash
   sudo apt install ./neutrino-client_0.2.0_amd64.deb
   ```

1. 以你自己的账户打开窗口。

   ```bash
   nclient gui
   ```

   窗口标题是 **微子·客户端**（Neutrino client），状态卡写着 **未连接**（Not connected）。

   ![未连接的窗口](/guide/zh/client_disconnected.webp)

1. 把链接粘进输入框，点 **连接**（Connect）。

状态卡变成 **已连接**（Connected），带 hub 的版本号；下面是五个面板：网页、端口、AI、文件、远程桌面。

![已连接的窗口](/guide/zh/client_connected.webp)

::: tip
`nclient` 以你的账户运行，前面不加 sudo。以 root 运行时它返回 `root_refused`。
:::

## 发布一个共享并挂载

1. 在面板里打开 **Samba** 页，在 **已启用的设备**（Enabled devices）里勾选 `home-hub`，点 **应用设备**（Apply devices）。
1. 在确认框里点 **应用设备**。安装完成后，页面下方出现这台机器的 Samba 面板。
1. 在 **用户**（Users）里点 **添加用户**（Add user），用户名填 `alex`，密码任填一个，点 **应用用户**（Apply users）。
1. 在 **共享**（Shares）里点 **添加共享**（Add share），名称填 `media`，路径填一个目录，点 **应用共享**（Apply shares）。

   ![一个共享](/guide/zh/samba_share.webp)

1. 打开 **服务**（Services）页。`media` 在 **文件**（Files）组里，来源写着由 `home-hub` 上的 samba 模块发布。

   ![服务页](/guide/zh/services_list.webp)

1. 在 `laptop` 的客户端窗口里，在 **文件** 面板的 `media` 条目上点 **配置**（Config）。

   ![挂载配置](/guide/zh/client_files_config.webp)

1. **共享用户名**（Share username）填 `alex`，**共享密码**（Share password）填它的密码，**挂载路径**（Mount path）保持默认，点 **挂载**（Mount）。

按钮变成 **卸载**（Unmount），共享在 `~/nas/media`。

![已挂载的共享](/guide/zh/client_files_mounted.webp)
