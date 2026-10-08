---
title: 第一步
---

# 第一步：装中枢，加入客户端，连上外网

这一页在你的电脑上装好中枢，让手机和笔记本加入它，再让它们离开家里的 Wi-Fi 也连得上，约 10 分钟。服务在这里都还没打开；终端、AI 会话、编辑器这些，在快速上手的其余几页里打开。

## 开始之前

- 一台电脑，系统是下面之一：
  - 带桌面的 Debian 12、Ubuntu 22.04 或更新版本，或 64 位树莓派 OS。
  - Apple 芯片的 Mac，macOS 12.3 或更新版本。
  - x86-64 上的 Windows 10 1809 或更新版本。
- 你有这台电脑的管理员权限，它能上网。
- 一部 Android 8.0 或更新版本的手机，64 位 ARM 处理器，开通了移动数据。或者另一台笔记本，系统同样是上面之一。
- 一个 EasyTier 控制台账号，在 `https://console.easytier.net` 注册。按 EasyTier 的规定，控制台的免费档每月有 1 GB 中转流量，最多接入 20 台设备。<!-- 待核: 免费档的 1 GB 和 20 台两个数字取自 iffi 的清单，仓库里没有出处。 -->
- 手机和笔记本先连上电脑所在的 Wi-Fi。

想用 NetBird、直连或自己的服务器时，先按 [NetBird](./hub/netbird.md) 页、[外部访问](./hub/overlay.md)页的直连一节或[用自己的 VPS 中继连回家](./scenarios/vps_relay.md)做好，再从“把手机和笔记本挂上”接着做。NetBird 只有完整版有；直连和 VPS 中继没有虚拟网，跳过那一节。

## 安装中枢

Linux 上打开终端，macOS 上打开“终端”应用，运行：

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh
```

Windows 上打开 PowerShell，运行：

```powershell
irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1 | iex
```

脚本要一次管理员权限：Linux 和 macOS 上输入登录密码，Windows 上在授权框里选 **是**。装好后，终端打印设置向导的地址，末尾带一次性令牌。

这是国内版的命令。完整版的命令见[安装中枢](./install/hub.md)。

## 回答向导

每一屏填好后，选择 **下一步**。最后一屏确认之前，向导不写入任何东西。

1. 在电脑的浏览器里打开终端打印的地址，连同末尾的令牌。
1. 选择 **开始配置这台机器**。
1. 在 **语言** 屏选择 **简体中文**。
1. 在 **面板密码** 和下面的 **再输一次** 里填同一个密码，至少 8 个字符。
1. 在 **保险库口令** 和它的 **再输一次** 里填同一个口令。口令至少 16 个字符，混用小写、大写、数字和符号。

   ![面板密码、保险库口令和 HTTPS 开关](/guide/zh/setup_secrets.webp)

1. 在 **这台机器做什么？** 屏选择 **服务器**。macOS 和 Windows 上只有这一项。
1. 在 **用哪些网口？** 屏，两个端口保持原值。
1. 在 **就绪** 屏选择 **开始配置这台机器**。

页面标题先读 **正在配置**，再读 **这个中枢已配置好**，中枢和本机的被控端就装好了。

![配置完成的页面](/guide/zh/setup_done.webp)

::: warning
保险库口令封存中枢保管的每一份凭据，恢复备份时还要输入它。把它记在这台电脑以外的地方。
:::

## 登录面板

1. 选择 **打开面板**。
1. 在 **面板密码** 里填你设的密码，选择 **登录**。

面板打开 **总览** 页。

## 让手机和笔记本加入

每台设备用一条自己的客户端链接，链接 30 分钟内有效。

### 在手机上加入

1. 在手机浏览器里打开 `https://gitee.com/iffiX/neutrino/releases`，下载 `neutrino-client-0.5.0-android.apk`。
1. 打开下载的文件。Android 提示时，允许浏览器安装应用。
1. 选 **安装**，装好后打开 **微子**。
1. 在电脑的面板侧栏打开 **客户端**，选择 **新建客户端链接**。
1. 填手机的名字，选择 **创建链接**。面板显示链接和它的二维码。

   ![客户端链接和它的二维码](/guide/zh/clients_link_qr.webp)

1. 在手机的 **中枢** 页选择 **加入中枢**。
1. 选择 **允许使用相机**，在 Android 的权限框里允许。
1. 把相机对准面板上的二维码。

   ![应用的加入页在扫描二维码](/guide/zh/app_join_scan.webp)

中枢那一行出现，先读 **连接中…**，再读 **已连接 · 局域网**。

### 在笔记本上加入

用你自己的账户运行下面的命令，前面不加 `sudo`。Linux 和 macOS 上：

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh -s -- client
```

Windows 上，在 PowerShell 里：

```powershell
& ([scriptblock]::Create((irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1))) client
```

1. 在面板的 **客户端** 页再建一条链接，名字填笔记本的名字。
1. 选择链接旁的 **复制**。
1. 打开客户端：Linux 上在应用菜单里，Windows 上在开始菜单里，macOS 上打开 **Neutrino Client**。
1. 把链接粘进 **加入中枢** 那一行的输入框，选择 **加入**。

中枢那一行同样读 **已连接 · 局域网**。加入失败时，见故障排查的[加入中枢失败](./reference/troubleshooting.md#加入中枢失败)。

## 打开 EasyTier

### 在面板里启用

控制台地址从 EasyTier 控制台里复制，形如 `tcp://et-web.console.easytier.net:22020/` 后接你账号的令牌。

1. 在面板侧栏打开 **外部访问**。
1. 在 **EasyTier** 卡片上打开 **启用**。
1. 选择 **应用外部访问**。
1. 选中 **EasyTier** 卡片，在它的 **设置** 里选择 **EasyTier 控制台**。
1. 在 EasyTier 控制台右上角选择 **设备接入方法**，切到 **开源版接入** 标签。
1. 在 **连接 EasyTier** 一节的 **接入秘钥** 里选一把密钥。
1. 页面给出一条命令，复制 `--config-server` 后面的整段地址。
1. 把地址粘进面板的 **控制台地址**。
1. 选择 **应用 EasyTier 设置**。

卡片标题旁的徽章读 **等待控制台挂载**。

![EasyTier 卡片选了控制台模式，徽章读等待控制台挂载](/guide/zh/overlay_easytier_console_waiting.webp)

### 在控制台里挂上电脑

1. 在 EasyTier 控制台的 **设备** 页找到你的电脑。

   ![EasyTier 控制台的设备列表，里面有你的电脑](/guide/console/console_easytier_devices.webp)

1. 在控制台侧栏打开 **网络**。
1. 选择 **创建网络**。
1. 在 **网络名称** 里填一个名字，其他项不动。

   ![EasyTier 控制台里新建网络的表单](/guide/console/console_easytier_network_create.webp)

1. 选择对话框底部的 **创建网络**。
1. 选择新网络的名字，打开它的页面。
1. 选择 **挂载设备**。
1. 在 **入网设备** 里选你的电脑。
1. 选择 **加入网络**。

电脑那一行先显示 **挂载中**，再显示 **运行中**。面板上的徽章换成 **还没有对端** 或 **已连接**，**控制台下发的网络** 列出你刚建的网络。

![控制台下发的网络列出电脑所在的网络](/guide/zh/overlay_easytier_console_networks.webp)

## 把手机和笔记本挂上

1. 在手机中枢那一行下面的 **虚拟网** 一行，选择 **连接**。
1. 在 Android 的 VPN 连接请求里选择 **确定**。

   ![Android 的 VPN 连接请求](/guide/zh/app_vpn_prompt.webp)

   虚拟网一行读 **连接中…**，下面一行提示去控制台挂载这部手机。

   ![虚拟网一行在连接中，下面是控制台提示](/guide/zh/app_hub_console_waiting.webp)

1. 在笔记本客户端的 **虚拟网** 一行，选择 **连接**。
1. 在 EasyTier 控制台里打开电脑所在的网络，选择 **挂载设备**。
1. 在 **入网设备** 里选你的手机。手机在列表里的名字是它的 Android 设备名。

   ![EasyTier 控制台里把手机挂到同一个网络](/guide/console/console_easytier_device_attach.webp)

1. 选择 **加入网络**。
1. 对笔记本重复上面三步。

手机和笔记本的虚拟网一行都读 **已连接 ·**，后面是它在虚拟网里的地址。一直停在 **连接中…** 时，见故障排查的[虚拟网连不上](./reference/troubleshooting.md#虚拟网连不上)。

## 离开 Wi-Fi

关掉手机的 Wi-Fi。中枢那一行读 **已连接 · EasyTier**，后面是往返时间，单位是 ms。

![中枢一行经 EasyTier 连着，虚拟网一行已连接](/guide/zh/app_hub.webp)
