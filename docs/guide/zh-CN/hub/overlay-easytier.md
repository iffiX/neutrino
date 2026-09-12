---
title: 虚拟网：EasyTier
---

# 虚拟网：EasyTier

EasyTier 是没有管理面的虚拟网：一张网就是一个名字加一把密码，两样都一致的机器就在同一张网里。这一页在 hub 上生成一张网，再把第二台机器接进来。

## 它是什么

EasyTier 是点对点的虚拟网。没有账号，没有控制台，密码同时是这张网流量的加密密钥。两台机器至少有一台能从公网直接访问时，它们直接连。两台都在 NAT 后面时，需要一个有公网地址的 rendezvous node（会合节点），双方都先连它。它可以是你自己在一台云主机上运行的 EasyTier。对端端口是 11010，TCP 和 UDP 都要通。

## 面板选 EasyTier 并生成

1. 打开 **虚拟网**（Overlay）页，在 **组网方式**（Engine）里选 EasyTier，点 **应用组网方式**（Apply engine）。引擎没装时这一步把它装上。

   ![组网方式的三个选项](/guide/zh/overlay_chooser.webp)

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

密码封在保险库里，用保险库的数据密钥加密。面板从不把它画在屏幕上，输入框里写 **保持不变**（kept as it is）表示已经有一把；只有 **复制（含密码）** 在点击那一刻读出它。换密码等于换一张网，其它机器在改之前仍留在旧的那张上。

::: danger
密码就是这张网的加密密钥。拿到网络名和密码的任何机器都在网里。
:::
