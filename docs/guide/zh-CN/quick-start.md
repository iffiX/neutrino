---
title: 快速上手
---

# 快速上手

走完这一页，你的手机在用移动数据时，也能看到家里电脑的桌面，打开电脑上共享的文件夹，在电脑上开终端。全程大约 10 分钟。


外部访问用的是 EasyTier 控制台的 **免费版**，全程不花钱。免费版最多接入 20 台设备。

## 开始之前

- 你的电脑：带桌面的 Linux（Debian 12、Ubuntu 22.04 或更新版本等），macOS 12.3 或更新版本，或 x86-64 上的 Windows 10 1809 或更新版本。
- 你有这台电脑的管理员权限，它能上网，屏幕前有人登录着。
- 一部 Android 8.0 或更新版本的手机，64 位 ARM 处理器，开通了移动数据。
- 一个 EasyTier 控制台账号，在 `https://console.easytier.net` 注册，登录也用这个网址。
- 手机和电脑连在同一个 Wi-Fi 上。

本页只讲 EasyTier 这一种外部访问，其他办法见[选哪种外部访问](./scenarios/choose_a_way_in.md)。要管理多台机器，见[一台笔记本管所有机器](./scenarios/one_laptop_every_machine.md)。

## 安装中枢

Linux 上打开终端，macOS 上打开“终端”应用，运行：

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
```

Windows 上打开一个普通的 PowerShell 窗口，运行：

```powershell
irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
```

脚本只要一次管理员权限：Linux 和 macOS 上输入你的登录密码，Windows 上在弹出的授权框里选 **是**。Windows 上，脚本随后换到一个新开的 PowerShell 窗口里运行。脚本用发布页的 `SHA256SUMS` 核对安装包，然后安装。装好后，终端打印设置向导的地址，地址末尾带一次性令牌。终端保持开着，向导在浏览器里填写。

国内版的安装命令见[安装中枢](./install/hub.md)。

## 打开设置向导

1. 在你的电脑上用浏览器打开终端打印的地址，连同末尾的令牌一起。
1. 选择 **开始配置这台机器**（Set this box up）。

## 回答向导

每一屏填好后，选择 **下一步**（Next）。最后一屏确认之前，向导不写入任何东西。

1. 在 **语言**（Language）屏选择 **简体中文**。
1. 在 **面板密码**（Panel password）和它下面的 **再输一次**（Again）里，填同一个密码，至少 8 个字符。
1. 在 **保险库口令**（Vault passphrase）和它的 **再输一次** 里，填同一个口令。它至少 16 个字符，要混用小写、大写、数字和符号。
1. **面板使用 HTTPS**（HTTPS for the panel）保持关闭。
1. 在形态屏 **这台机器做什么？**（What is this machine for?）里选择 **服务器**（Server）。macOS 和 Windows 上只有这一项。
1. 在 **用哪些网口？**（Which ports?）屏，两个端口保持原值。
1. 在 **通过代理出网**（Going out through a proxy）屏，**在这里设置**（Set it up here）保持关闭。
1. 在 **就绪**（Ready）屏选择 **开始配置这台机器**。

页面标题变成 **正在配置**（Setting up），下面逐条列出正在跑的步骤，最后一步是 **安装本机被控端**（Installing this machine's agent）。标题变成 **这个中枢已配置好**（This hub is set up），中枢就装好了。

::: warning
保险库口令封存中枢保管的每一份凭据，恢复备份时还要输入它。把它记在这台电脑以外的地方。
:::

## 登录面板

1. 选择 **打开面板**（Open the panel）。
1. 在 **面板密码** 里填你设的密码，选择 **登录**（Sign in）。

面板打开 **总览**（Dashboard）。在侧栏打开 **设备**（Devices），**已管理的设备**（Managed devices）里已经有你的电脑。向导在这台电脑上装好了被控端，并让它加入了中枢。

## 打开 EasyTier

控制台地址从 EasyTier 控制台里取。在控制台右上角选择 **设备接入方法**，切到 **开源版接入** 标签。在 **连接 EasyTier** 一节的 **接入秘钥** 里选一把密钥，页面给出一条命令。命令里 `--config-server` 后面的整段就是控制台地址。

1. 在侧栏打开 **外部访问**（Access）。
1. 在 **EasyTier** 卡片上打开 **启用**（Enable）。
1. 选择 **应用外部访问**（Apply access）。
1. 选中 **EasyTier** 卡片，在它的 **设置**（Settings）里选择 **EasyTier 控制台**（EasyTier console）。
1. 在 EasyTier 控制台里复制这个控制台地址。
1. 把地址粘进 **控制台地址**（Console address）。
1. 选择 **应用 EasyTier 设置**（Apply EasyTier settings）。

这个地址形如 `tcp://et-web.console.easytier.net:22020/`，后面接你账号的令牌。应用之后，卡片标题旁的徽章读 **等待控制台挂载**（Waiting for the console）。

![EasyTier 卡片选了控制台模式，徽章读等待控制台挂载](/guide/zh/overlay_easytier_console_waiting.webp)

## 在控制台里挂上你的电脑

1. 在 EasyTier 控制台的 **设备** 页找到你的电脑。

   ![EasyTier 控制台的设备列表，里面有你的电脑](/guide/console/console_easytier_devices.webp)

1. 在控制台侧栏打开 **网络**。
1. 选择 **创建网络**。
1. 在 **网络名称** 里填一个名字，其他项不动。

   ![EasyTier 控制台里为电脑新建网络的表单](/guide/console/console_easytier_network_create.webp)

1. 选择对话框底部的 **创建网络**。
1. 选择新网络的名字，打开它的页面。
1. 选择 **挂载设备**。
1. 在 **入网设备** 里选你的电脑。
1. 选择 **加入网络**。

网络页面上，电脑那一行先显示 **挂载中**，再显示 **运行中**。

面板上的徽章换成 **已连接**（connected）或 **还没有对端**（no peers yet）。**控制台下发的网络**（Networks from the console）列出你刚建的网络。

![控制台下发的网络列出电脑所在的网络](/guide/zh/overlay_easytier_console_networks.webp)

## 共享电脑的桌面

1. 在侧栏的 **被控端**（Agent）组里打开 **模块**（Modules）。
1. 在页面上方的机器里选择你的电脑。
1. 选择 **Remote desktop** 标签。
1. 打开 **共享这台机器的桌面**（Share this machine's desktop）。
1. 选择 **应用远程桌面**（Apply remote desktop）。

![Remote desktop 标签上的共享开关已打开](/guide/zh/modules_remote_desktop_tab.webp)

macOS 上，电脑屏幕弹出一个对话框，并打开系统设置的“屏幕录制”面板。在“隐私与安全性”里，为 RustDesk 打开“屏幕录制”和“辅助功能”。Linux 的 Wayland 会话上，在电脑屏幕前允许一次屏幕共享。

## 装上文件共享

1. 选择 **File share** 标签。没有这个标签时，用标签旁的 **+** 加上它。
1. 选择 **安装**（Install），等标签上的 **安装中**（installing）消失。
1. 选择 **配置**（Configure）。下面展开 **共享**（Shares）和 **用户**（Users）两节。

Linux 上这一步装的是 Samba。macOS 和 Windows 用系统自带的 SMB 服务，不下载东西。

## 添加用户和共享

1. 在 **用户** 下的两个输入框里，填一个用户名和它的密码。
1. 选择 **添加用户**（Add user）。
1. 选择 **应用用户**（Apply users），等这一行读 **就绪**（ready）。
1. 在 **共享** 下选择 **添加共享**（Add share）。
1. 在 **名称**（Name）里填共享名，在 **路径**（Path）里填电脑上一个已有的文件夹。
1. 选择 **应用共享**（Apply shares）。

记下这个用户名和密码，手机打开共享时要用。

## 装 App 并加入

1. 在手机浏览器里打开 `https://github.com/iffiX/neutrino/releases`，下载 `neutrino-client-0.5.0-android.apk`。
1. 打开下载的文件。Android 提示时，允许浏览器安装应用。
1. 在安装界面选 **安装**，装好后打开 **微子**。
1. 在电脑的面板里打开 **客户端**（Clients），选择 **新建客户端链接**（New client link）。
1. 填手机的名字，选择 **创建链接**（Create link）。面板显示链接和它的二维码，30 分钟内有效。

   ![客户端链接和它的二维码](/guide/zh/clients_link_qr.webp)

1. 在手机的 **中枢**（Hubs）页选择 **加入中枢**（Join a hub）。
1. 选择 **允许使用相机**（Allow the camera），在 Android 的权限框里允许。
1. 把相机对准电脑屏幕上的二维码。

   ![应用的加入页在扫描二维码](/guide/zh/app_join_scan.webp)

中枢那一行出现，读 **已连接 · 局域网**（Connected · LAN）。

## 连上手机的虚拟网

1. 在中枢那一行下面的 **虚拟网**（Virtual network）一行，选择 **连接**（Connect）。
1. 在 Android 的 VPN 连接请求里选择 **确定**。

   ![Android 的 VPN 连接请求](/guide/zh/app_vpn_prompt.webp)

   虚拟网一行读 **连接中…**（Connecting…），下面一行提示你去控制台挂载这部手机。

   ![虚拟网一行在连接中，下面是控制台提示](/guide/zh/app_hub_console_waiting.webp)

1. 在 EasyTier 控制台里打开电脑所在的网络。
1. 选择 **挂载设备**。
1. 在 **入网设备** 里选你的手机。列表里的手机名是它的 Android 设备名。

   ![EasyTier 控制台里把手机挂到同一个网络](/guide/console/console_easytier_device_attach.webp)

1. 选择 **加入网络**。

虚拟网一行读 **已连接 ·**，后面是手机在虚拟网里的地址。

## 用移动数据使用你的电脑

下面每一节都在手机上做，手机不连 Wi-Fi。

### 离开 Wi-Fi

关掉手机的 Wi-Fi。中枢那一行读 **已连接 · EasyTier**（Connected · EasyTier），后面是往返时间，单位是 ms。

![中枢一行经 EasyTier 连着，虚拟网一行已连接](/guide/zh/app_hub.webp)

### 看桌面

1. 打开 **远程桌面**（Remote desktops）。
1. 在你的电脑那一行选择 **连接**。

查看器占满屏幕，显示电脑的桌面。右上角三个圆按钮依次弹出键盘、显示特殊键、结束会话。

![手机查看器里的电脑桌面，右上角三个圆按钮](/guide/zh/app_rdp_viewer.webp)

### 打开共享文件夹

1. 打开 **文件**（Files）。
1. 在共享那一行选择 **在“文件”中打开**（Open in Files）。
1. 在 **共享用户名**（Share username）和 **共享密码**（Share password）里，填添加用户时设的用户名和密码。
1. 保持勾选 **记住**（Remember），选择 **连接**。

Android 的“文件”应用打开这个共享，里面是电脑上那个文件夹的内容。

![“文件”应用里作为一个位置的共享](/guide/zh/app_files_provider.webp)

### 开终端

1. 打开 **终端**（Terminals）。
1. 在上方的机器标签里选择你的电脑。
1. 选择 **新终端**（New terminal）。
1. 输入 `hostname` 并回车。

终端里显示电脑的主机名。Linux 上的 shell 是登录 shell，macOS 上是 zsh，Windows 上是 PowerShell。

![带按键行的手机终端](/guide/zh/app_terminal.webp)
