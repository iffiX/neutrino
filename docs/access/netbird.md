# NetBird

NetBird 是把你的设备组成一张虚拟网的软件。中枢和设备加入同一张虚拟网，设备再连接中枢在虚拟网里的地址。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.1.0" />

| 免费账号的额度 | 数值                            |
| -------------- | ------------------------------- |
| 用户           | 最多 5 个                       |
| 设备           | 最多 100 台                     |
| 读取日期       | 2026-10-30，以 NetBird 官网为准 |

开始之前，你要把设备[加入中枢](/access/join)，并打开这台设备的 **虚拟网** 权限，见[客户端](/hub/clients)。下面的步骤还会用到一个 netbird.io 账号和一个 setup key。

只打开 NetBird 时，中枢不生成[应用分享](/share/web_share)的链接。如果你要分享应用，再开启 [SakuraFrp](/access/sakurafrp)。一台设备同一时间只使用 NetBird 和 EasyTier 中的一个。在 iPhone 上，你要安装 NetBird 自己的 App，见 [iOS 应用](/access/ios)。

## 创建 setup key

中枢和每个客户端共用一个 setup key，所以它必须可以重复使用，不限次数。不要使用控制台 **Install NetBird** 页面提供的 key，因为它只能使用一次。

1. 打开 netbird.io，注册并登录，进入控制台。

   ![NetBird 控制台的 Peers 页，列着两台设备](/guide/zh/access_netbird_19_console_home.webp)

1. 在左侧栏点 **Settings**，打开 **Setup Keys**，再按 **Create Key**。

   ![NetBird 控制台的 Setup Keys 页，Setup Keys 和 Create Key 标红](/guide/zh/access_netbird_20_console_keys.webp)

1. 填写 **Name**，打开 **Make this key reusable**。**Usage limit** 保持空白，再清空 **Expires in** 里默认的 7，然后按 **Create Setup Key**。

   ![新建 setup key 的表单，Expires in 默认填着 7](/guide/zh/access_netbird_21_console_key_form.webp)

1. 复制 key，因为它只显示这一次。

   ![setup key 已创建，只显示这一次，图里的 key 是示例](/guide/zh/access_netbird_22_console_key_once.webp)

## 把中枢加入虚拟网

1. 在面板左侧栏点 **外部访问**，打开 **NetBird** 卡片的开关，再按 **应用外部访问**。下面会出现 **设置**。标题旁的 **打开控制台** 也能打开 NetBird 的网站。

   ![NetBird 开关已打开，应用外部访问按钮标红](/guide/zh/access_netbird_01_switch.webp "按 应用外部访问")
   ![NetBird 的设置，打开控制台标红](/guide/zh/access_netbird_02_console.webp "这里也能打开 NetBird 的网站")

1. 把 key 粘贴到 **Setup key**。如果你使用 netbird.io，旁边的管理面地址（NetBird 管理服务器的地址）留空，只有自建的 NetBird 才填写它。再按 **加入**。

   ![Setup key 输入框标红](/guide/zh/access_netbird_03_steps.webp "粘贴 key")
   ![key 已填写，加入按钮标红](/guide/zh/access_netbird_04_join.webp "按 加入")

1. 等待面板显示 **已连接**。

   ![NetBird 显示已连接，拓扑里连着一台设备](/guide/zh/access_netbird_06_connected.webp)

各状态的含义如下。

| 状态             | 含义                                                      |
| ---------------- | --------------------------------------------------------- |
| **加入中**       | 中枢正在用 key 加入                                       |
| **已连接**       | 中枢已加入虚拟网                                          |
| **正在连接**     | NetBird 重启后正在重新连接                                |
| **未加入**       | 中枢还没有加入，或上次的登录已失效，你要用新 key 重新加入 |
| **管理面不可达** | 中枢无法连接 NetBird 的管理面                             |
| **未运行**       | NetBird 没有运行                                          |

## 连接客户端

你不需要在客户端上填写 key。

打开客户端的 **中枢** 页，在 NetBird 那一行按 **连接**。在 Android 上第一次连接时，系统会弹出授权框，选择“确定”。这一行显示 **已连接** 和地址，就说明连接成功。然后关闭 Wi-Fi，用移动网络再试一次，中枢那一行会显示 **已连接 · NetBird**。

![中枢那一行下面显示 NetBird 未连接，连接按钮标红](/guide/zh/access_netbird_08_client_connect.webp "按 连接")
![这一行显示 NetBird 已连接和地址](/guide/zh/access_netbird_09_client_connected.webp "显示 已连接")

如果客户端要换用其他虚拟网，要等这一行显示 **未连接** 时才能更换。

## 后续维护

**节点** 一栏列出虚拟网里的每台设备。

**网络** 页 **开放范围** 里这张虚拟网的开关默认打开。关闭后，虚拟网里的设备无法连接中枢。

**局域网路由** 用来访问没有安装被控端的设备，你要在 NetBird 控制台里添加这些子网，步骤见[访问没有安装被控端的设备](/deploy/without_agent)。

![局域网路由一栏](/guide/zh/access_netbird_05_routes.webp)

如果你要更换 key，在 **Setup key** 一行按 **替换**。如果你要删除已保存的 key，按 **忘掉**。按 **忘掉** 后、保存新 key 前，客户端无法加入虚拟网。

如果你要退出，按 **离开**，再在弹窗里按 **离开**。这时只通过 NetBird 连接的设备无法连接中枢。然后到控制台的 **Peers** 删除中枢的旧记录。
