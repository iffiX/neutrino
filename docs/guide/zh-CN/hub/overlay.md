---
title: 虚拟网
---

# 虚拟网

虚拟网是架在公网上的一张私网，外面的机器经它访问 hub 和 hub 后面的局域网。**虚拟网**（Overlay）页可以运行 NetBird、EasyTier，或两个同时运行；每个引擎有自己的开关和自己的设置。

## 打开引擎

![两张引擎卡片，开关都已打开](/guide/zh/overlay_switches.webp)

**组网方式**（Engine）一节每个引擎一张卡片。卡片上的开关 **运行 NetBird**（Run NetBird）或 **运行 EasyTier**（Run EasyTier）决定引擎是否运行。点卡片本身，只切换卡片下方显示哪个引擎的设置。

1. 打开引擎的开关。
1. 选择 **应用虚拟网**（Apply overlays）。引擎没装时 hub 先装上；然后先启动开着的引擎，再停掉关掉的引擎。

带 **使用中**（active）标记的卡片，引擎正在运行。写着 **这台机器没有对应的版本**（No build for this machine）的卡片打不开。一个引擎都没开时，页面写着 **没有虚拟网在运行，外面进不来这台机器。**

打开一个引擎时，如果它的网段和另一张虚拟网重叠，或和这台机器有地址的任何网络重叠，hub 拒绝并返回 `overlay_subnet_overlap`。NetBird 的网段是 `100.64.0.0/10`；EasyTier 的网段由本机在这张网里的地址决定。

## 加入 NetBird

开始之前，你需要一个 NetBird 账号，并打开它的管理控制台；NetBird 一节的 **打开控制台**（Open console）打开 app.netbird.io。NetBird 必须已经打开并在运行，否则应用栏写着 **NetBird 还没有运行。**

先在控制台里准备网络和 setup key：

1. 打开 Networks，点 Add Network。
1. 在新建的网络里，于 Routing Peers 下点 Add，选 Install NetBird。
1. 复制控制台显示的 setup key。

![NetBird 的设置，带 setup key 输入框](/guide/zh/overlay_netbird_settings.webp)

再在面板里用这把 key 加入：

1. 选择 **NetBird** 卡片。
1. 在 **设置**（Settings）里粘贴 setup key。管理面地址留空，则用 netbird.io。
1. 选择 **加入**（Join）。

**NetBird** 旁的徽章先写 **加入中**（joining），再变成 **已连接**（connected）。**设置** 里出现 **虚拟网地址**（Overlay address）、**名称**（Name）和 **管理面**（Management）。key 用保险库加密保存，**Setup key** 一行写着 **已保存**（Saved）。允许加入虚拟网的客户端拿到这把 key，加入同一张网；**替换**（Replace）和 **忘掉**（Forget）用来换掉或删掉它。哪些客户端能用虚拟网，在[客户端](./clients.md)页设置。

| 徽章                                       | 含义                                                         |
| ------------------------------------------ | ------------------------------------------------------------ |
| **正在连接**（connecting）                 | 守护进程重启后正在重连                                       |
| **未加入**（not joined）                   | 这台机器没有 NetBird 身份，或上次登录已失效；用新 key 再加入 |
| **管理面不可达**（management unreachable） | 这台机器连不上 NetBird 的管理面                              |

网络限制挡住管理面时，到[代理](./proxy.md)页打开 **让 微子·中枢 自己的流量走代理**（Send Neutrino Hub's own traffic through the proxy），再加入一次。

加入之后，应用栏的按钮变成 **重新注册**（Re-enroll）：用一把新 key 给这台机器换一个身份，再到控制台删掉旧节点。**离开**（Leave）在你确认后把这台机器从网络里删掉。

**局域网路由**（LAN routes）列出这台机器服务的每个子网。在控制台的 Networks 下，把每个子网加成网络的 Resource，并给它配一条 Access Control Policy；之后对端用局域网地址就能访问那个子网里的机器。服务器形态写着 **没有接口处于 LAN 角色。**

## 设置 EasyTier

一张 EasyTier 网就是一个名字加一把密码。两样都一致的机器就在网里，密码同时是这张网流量的加密密钥。对端之间用 11010 端口，TCP 和 UDP 都用。

![手动模式下的 EasyTier 设置](/guide/zh/overlay_easytier_settings.webp)

选择 **EasyTier** 卡片。它的 **设置** 决定网从哪里来，整块设置共用一个应用栏 **应用 EasyTier 设置**（Apply EasyTier settings）。

### EasyTier 控制台

这个模式下，网络、本机地址、碰头点和子网路由都由 EasyTier 官方控制台下发。

1. 在 EasyTier 控制台里复制设备加入用的地址，形如 `tcp://et-web.console.easytier.net:22020/` 后接账号令牌。
1. 在面板的 **设置** 里选 **EasyTier 控制台**（EasyTier console）。
1. 把地址粘到 **控制台地址**（Console address）。
1. 可选：控制台的网络用了 EasyTier 安全模式时，打开 **安全模式**（Secure mode）。
1. 选择 **应用 EasyTier 设置**。

在控制台里把这台机器挂到一个网络之前，徽章写着 **等待控制台挂载**（Waiting for the console）。挂上之后，**控制台下发的网络**（Networks from the console）列出每张网的名字、本机的地址和名称，以及 **子网路由**（Subnet routes）。要导出本机的局域网，在控制台里给这台设备加子网路由。

### 手动碰头点

这个模式下，本机保存网络名和密码，并主动连你列出的碰头点。

1. 在 **设置** 里选 **手动碰头点**（Manual bootstrap peers）。
1. 选择 **生成**（Generate）。**网络名**（Network name）、**网络密码**（Network secret）和 **本机地址**（This box's address）自动填好。
1. 在 **碰头点**（Bootstrap peers）里加一台已经在网里的机器，例如 `tcp://198.51.100.7:11010`。
1. 可选：在 **导出的局域网**（Exported networks）里加上网里机器经本机访问的网段。
1. 选择 **应用 EasyTier 设置**。

碰头点为空时，本机只接受别人主动连进来。徽章写 **已连接**（connected）；网里还没有别的机器时，写 **还没有对端**（no peers yet）。

::: warning
换密码等于换一张网。其他机器在改密码之前，仍留在旧的那张网里。
:::

**给别的机器的命令**（Commands for another machine）显示两条命令，屏幕上密码打码；**复制（含密码）**（Copy with the secret）复制的是带真实密码的命令。命令里的 `<network-name>` 和 `<secret>` 是这张网的名字和密码，`<hub-address>` 是另一台机器访问本机用的地址；复制出来的命令三项都已填好。第一条让一台机器经本机加入这张网：

```bash
easytier-core -d --network-name <network-name> --network-secret <secret> -p tcp://<hub-address>:11010
```

第二条在一台有公网地址的机器上自建碰头点。它只转发这张网的流量，只接受带这把密码的机器：

```bash
easytier-core --private-mode true --network-name <network-name> --network-secret <secret> \
  --relay-network-whitelist <network-name> -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010
```

## 同时运行两个

打开两个开关，选择 **应用虚拟网**。两个引擎各有自己的设置、对端和客户端，hub 把它们隔开：

- 网段重叠时，hub 拒绝并返回 `overlay_subnet_overlap`，和打开单个引擎时一样。EasyTier 运行时保存它的地址，也做同样的检查。
- 从一张虚拟网进来、要从另一张出去的数据包，hub 一律丢弃。
- 某张虚拟网装了和其他网络重叠的路由时，页面顶部用红字列出。NetBird 的路由由 hub 取消选中；EasyTier 的路由只报告，页面提示到管理这张虚拟网的地方改掉。
- 经虚拟网的默认路由显示为 `overlay_default_route_refused`：hub 删掉它，仍以自己的上行为出口。

## 关掉引擎

1. 关掉引擎的开关。
1. 读应用栏里的警告。
1. 选择 **应用虚拟网**。

![应用栏里关于在线客户端的警告](/guide/zh/overlay_off_warning.webp)

警告写着有几台在线客户端正经这个引擎连着，以及经它进入这台机器的通路将关闭。hub 把新状态发给每个客户端和被控端之后，才停掉引擎。

::: info
关掉引擎会停掉它的服务，设置保留。再打开时，它按原来的设置启动。
:::

## 看节点表

每个引擎一节的末尾是 **节点**（Peers），每 5 秒刷新一次。每行有对端的名称、虚拟网地址，以及连接方式 **直连**（direct）或 **中继**（relayed）。NetBird 还显示上次握手距今多久；EasyTier 还显示协议和丢包率；两者都显示时延和收发字节数。NetBird 的空表写着 **还没有节点。在另一台设备上用 NetBird 应用登录。** EasyTier 的空表写着 **还没有机器加入。**

机器加入网络后，设置上方的 **拓扑**（Topology）画出本机、它的局域网和对端。本机是否在虚拟网上应答自身的服务，由[网络](./network.md)页的 **开放范围** 决定。
