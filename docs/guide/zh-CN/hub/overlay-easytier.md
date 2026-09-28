---
title: 虚拟网：EasyTier
---

# 虚拟网：EasyTier

读完这一页，hub 就在一张 EasyTier 网里：要么由 EasyTier 官方控制台管理，要么由 hub 自己生成、经碰头点把第二台机器接进来。

## 它是什么

EasyTier 是点对点的虚拟网：一张网就是一个名字加一把密码，两样都一致的机器就在同一张网里，密码同时是这张网流量的加密密钥。两台机器至少有一台能从公网直接访问时，它们直接连。两台都在 NAT 后面时，需要一个有公网地址的 rendezvous node（会合节点），双方都先连它。它可以是你自己在一台云主机上运行的 EasyTier。对端端口是 11010，TCP 和 UDP 都要通。

拓扑下面的 **模式**（Mode）面板决定网从哪里来。选 **EasyTier 控制台**（EasyTier console），网络名、密码、本机地址、碰头点和子网路由都由官方控制台下发。选 **手动碰头点**（Manual bootstrap peers），这些都留在 hub 上，下文生成网络的几节只对这个模式有效。

## 控制台模式

1. 在 EasyTier 控制台里复制设备加入用的地址，形如 `tcp://et-web.console.easytier.net:22020/<token>`。`<token>` 是账号的令牌，谁拿到它谁就能把设备加进你的账号。
1. 在 **虚拟网**（Overlay）页的 **模式** 里选 **EasyTier 控制台**，点 **应用模式**（Apply mode）。
1. 在 **EasyTier 控制台** 一节，点 **控制台地址**（Console address）旁的 **替换**（Replace），粘贴地址，点 **保存**（Save）。引擎按控制台的网络重启。
1. 控制台的网络用了安全模式时，打开 **安全模式**（Secure mode），点 **应用安全模式**（Apply secure mode）。

引擎停着时，标题旁的标记写 **未运行**（not running）；引擎在跑但控制台还没下发网络时写 **等待控制台挂载**（Waiting for the console）：本机已登记到控制台，在控制台里把它挂载到一个网络即可。

**控制台下发的网络**（Networks from the console）列出引擎在跑的每张网：网络名、本机地址和名称、子网路由。控制台没给这台机器的字段写 **控制台未提供**（Not provided by the console）。要让网里的机器访问本机的局域网，在控制台里给这台设备加一条子网路由。

地址旁的 **忘掉**（Forget）删除地址并停下引擎。允许加入虚拟网的客户端拿到的是控制台地址，加入的也是同一张控制台网络。

## 面板选 EasyTier 并生成

1. 打开 **虚拟网**（Overlay）页，在 **组网方式**（Engine）里选 EasyTier，点 **应用组网方式**（Apply engine）。引擎没装时这一步把它装上。

   ![组网方式的三个选项](/guide/zh/overlay_chooser.webp)

1. **模式** 保持 **手动碰头点**。
1. 在 **这台网关在网里**（This gateway on the network）里点 **生成**（Generate）。面板给 **网络名**（Network name）填入一个新名字，给 **网络密码**（Network secret）填入一把密码，密码打码显示。
1. 填 **本机地址**（This box's address），例如 `10.0.0.1/24`。
1. 点 **应用网络**（Apply network）。

引擎按这张网重启，徽章变成 **已连接**（connected）或 **还没有对端**（no peers yet）。

## Rendezvous node 与导出的网络

![运行中的 EasyTier 一节](/guide/zh/overlay_easytier_running.webp)

**碰头点**（Bootstrap peers）一栏填这台机器启动时先去连的 rendezvous node。这套网络没有服务器角色，任何一台已经在网里的机器都能当 rendezvous node。直连地址写 `tcp://`、`udp://`、`ws://`、`wss://` 或 `quic://`；返回地址列表的发现服务写 `http://`、`https://`、`txt://` 或 `srv://`。列表空着时这台机器不主动连任何对端，只接受进来的连接。加一条后点 **应用碰头点**（Apply peers）。

**导出的局域网**（Exported networks）是网里的机器能经这台机器访问的网段，例如 `10.20.0.0/24`。加完点 **应用网段**（Apply networks），引擎重启并向网里通告。

## 给另一台机器的命令

![给别的机器的命令](/guide/zh/overlay_easytier_commands.webp)

**给别的机器的命令**（Commands for another machine）一节由面板生成，屏幕上密码打码，**复制（含密码）**（Copy with the secret）放到剪贴板的是完整命令。

第一条给普通节点，在第二台机器上运行：

```bash
easytier-core -d --network-name PLACEHOLDER_NETWORK \
  --network-secret PLACEHOLDER_SECRET -p tcp://198.51.100.10:11010
```

几秒内这台机器出现在 hub 的节点表里。第二条在一台有公网地址的机器上自建 rendezvous node，它只转发这张网的流量，也只接受带这把密码的连接：

```bash
easytier-core --private-mode true --network-name PLACEHOLDER_NETWORK \
  --network-secret PLACEHOLDER_SECRET \
  --relay-network-whitelist PLACEHOLDER_NETWORK \
  -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010
```

两条命令里随你的网变的只有网络名和密码。

## 对端表

![节点表](/guide/zh/overlay_easytier_peers.webp)

**节点**（Peers）一行一台机器，每 5 秒刷新一次。没有机器时写 **还没有机器加入。** 一台机器迟迟不出现，先核对它的网络名和密码是否与这里完全一致。

## 密钥在哪

密码和控制台地址都封在保险库里，用保险库的数据密钥加密。面板从不把密码画在屏幕上，输入框里写 **保持不变**（kept as it is）表示已经有一把；只有 **复制（含密码）** 在点击那一刻读出它。控制台地址在页面上只显示 **已保存**（Saved）或 **未保存**（Not saved）。换密码等于换一张网，其它机器在改之前仍留在旧的那张上。

::: danger
密码就是这张网的加密密钥。拿到网络名和密码的任何机器都在网里。
:::
