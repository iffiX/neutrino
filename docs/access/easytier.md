# EasyTier

EasyTier 是把你的设备组成一张虚拟网的软件。中枢和设备加入同一张虚拟网，设备再连接中枢在虚拟网里的地址。没有公网地址时也能使用。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.2.0" />

| 免费账号的额度 | 数值                             |
| -------------- | -------------------------------- |
| 功能           | 全部功能                         |
| 官方控制台     | P2P 直连无限，中转每月 1 GB 流量 |
| 设备           | 最多 20 台                       |
| 读取日期       | 2026-10-30，以 EasyTier 官网为准 |

EasyTier 有两种用法：**EasyTier 控制台** 和 **手动引导节点**。

- **EasyTier 控制台：** 使用官方控制台，你要注册一个账号。
- **手动引导节点：** 不需要账号，你填写引导节点的地址，也就是一台已经在这张虚拟网里的电脑的地址。

开始之前，你要把设备[加入中枢](/access/join)，并打开这台设备的 **虚拟网** 权限，见[客户端](/hub/clients)。

只打开 EasyTier 时，中枢不生成[应用分享](/share/web_share)的链接。如果你要分享应用，再开启 [SakuraFrp](/access/sakurafrp)。一台设备同一时间只使用 EasyTier 和 NetBird 中的一个。在 iPhone 上，你要安装 EasyTier 自己的 App。

## 打开 EasyTier

在面板左侧栏点 **外部访问**，打开 **EasyTier** 卡片的开关，再按 **应用外部访问**。下面会出现 **设置**，里面有 **EasyTier 控制台** 和 **手动引导节点** 两张卡片。选择一张，再按下面对应的一节操作。

![EasyTier 开关已打开，应用外部访问按钮标红](/guide/zh/access_easytier_01_switch.webp "按 应用外部访问")
![EasyTier 的设置，EasyTier 控制台卡片标红](/guide/zh/access_easytier_02_settings.webp "选择一张卡片")

## 使用控制台

1. 在浏览器里打开 console.easytier.net，注册并登录。

1. 在右上角选择 **设备接入方法**，再在 **接入密钥** 里选择一个。

   ![EasyTier 控制台的“设备”列表，右上角有设备接入方法](/guide/zh/access_easytier_30_console_devices.webp)

1. 复制命令里 `--config-server` 后面的整段地址。

1. 回到面板，按 **EasyTier 控制台** 卡片，把地址粘贴到 **控制台地址**。打开 **安全模式**，因为 EasyTier 控制台默认使用安全模式。再按 **应用 EasyTier 设置**。这时面板显示 **等待控制台挂载**。

   ![控制台地址输入框标红](/guide/zh/access_easytier_03_console.webp "粘贴地址")
   ![地址已填写，安全模式已打开并标红](/guide/zh/access_easytier_04_console_filled.webp "打开 安全模式，再按 应用 EasyTier 设置")

1. 回到控制台，在 **网络** 里创建一个网络，把中枢挂载到这个网络。

   ![控制台创建网络的弹窗](/guide/zh/access_easytier_31_console_network.webp "创建网络")
   ![控制台挂载设备的弹窗，列出可以挂载的设备](/guide/zh/access_easytier_32_console_attach.webp "把中枢挂载到这个网络")

1. 面板先显示 **还没有对端**，另一台设备连通后显示 **已连接**。**控制台下发的网络** 列出每个网络。

   ![EasyTier 显示已连接，拓扑里连着一台设备](/guide/zh/access_easytier_08_connected.webp)

你在每个客户端上第一次按 **连接** 后，这一行显示 **连接中…**，下面显示本机已登记到控制台。这时到控制台把这个客户端也挂载到同一个网络，这一行就会显示 **已连接** 和地址。

## 使用手动引导节点

1. 按 **手动引导节点** 卡片，再按 **设置** 旁边的 **生成**。**网络名**、**网络密码**、**本机地址** 会自动填写。在 **引导节点** 填写一台已经在虚拟网里的电脑的地址，以 `tcp://`、`udp://`、`ws://`、`wss://` 或 `quic://` 开头，再按 **添加**。一个都没有填写时，应用按钮显示为灰色。

   ![手动引导节点的设置，生成按钮标红](/guide/zh/access_easytier_05_generate.webp "按 生成")
   ![引导节点已填写，添加按钮标红](/guide/zh/access_easytier_06_manual.webp "填写引导节点，按 添加")

1. 按 **应用 EasyTier 设置**。

如果虚拟网里还没有其他电脑，在一台有公网地址的电脑上运行 **给别的系统的命令** 里的第二条命令，这台电脑就成为引导节点。其他电脑用第一条命令加入，按 **复制（含密码）** 能复制带真实密码的命令。

更换密码相当于建立一张新的虚拟网。其他电脑更换密码之前，仍在旧的虚拟网里。

## 连接客户端

你不需要在客户端上填写任何内容。

打开客户端的 **中枢** 页，在 EasyTier 那一行按 **连接**。在 Android 上第一次连接时，系统会弹出授权框，选择“确定”。这一行显示 **已连接** 和地址，就说明连接成功。

![中枢那一行下面显示 EasyTier 未连接，连接按钮标红](/guide/zh/access_easytier_08_client_connect.webp "按 连接")
![这一行显示 EasyTier 已连接和地址](/guide/zh/access_easytier_09_client_connected.webp "显示 已连接")

如果客户端要换用其他虚拟网，要等这一行显示 **未连接** 时才能更换。一台设备同一时间只加入一个中枢的虚拟网。

## 后续维护

**节点** 一栏列出虚拟网里的每台设备，**拓扑** 显示它们的关系。

![节点一栏，还没有设备加入](/guide/zh/access_easytier_07_nodes.webp)

更换模式时，EasyTier 会重启，经过它的连接会短暂中断。如果中转经过 EasyTier 的服务器，流量按控制台的额度计算。

**网络** 页 **开放范围** 里这张虚拟网的开关默认打开。关闭后，虚拟网里的设备无法连接中枢。

如果你要访问局域网里没有安装被控端的设备，见[访问没有安装被控端的设备](/deploy/without_agent)。
