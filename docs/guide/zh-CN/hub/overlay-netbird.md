---
title: 虚拟网：NetBird
---

# 虚拟网：NetBird

NetBird 是带管理面的虚拟网；管理面就是它的控制台服务，账号、节点和访问策略都在那里管。这一页把 hub 加进你的 NetBird 网络，再把家里的局域网路由导出去。之后外面的机器经 hub 进局域网。

## 开始之前

- 一个 NetBird 账号，浏览器里开着它的管理控制台。**虚拟网**（Overlay）页上有 **打开控制台**（Open console）按钮。
- hub 能访问 NetBird 的管理面。访问不到时，状态徽章写 **管理面不可达**（management unreachable），解法在下文。
- 一台机器同时只在一张虚拟网里。选 NetBird 会停掉 EasyTier，外面经 EasyTier 进来的路随之关闭。

## 在控制台建网络

1. 在控制台里打开 Networks，点 Add Network。
1. 在新建的网络里，于 Routing Peers 下点 Add，选 Install NetBird。
1. 复制它显示的 setup key。

这三步是面板 **加入网络**（Join a network）一节里写着的原话。

## 面板选 NetBird 并加入

1. 打开 **虚拟网** 页，在 **组网方式**（Engine）里选 NetBird。

   ![组网方式的三个选项](/guide/zh/overlay_chooser.webp)

1. 点 **应用组网方式**（Apply engine）。NetBird 没装时，这一步把它装上。
1. 在 **加入网络** 里粘贴 setup key；**管理面地址**（Management URL）留空则用 netbird.io。

   ![加入网络](/guide/zh/overlay_netbird_join.webp)

1. 点 **加入**（Join）。

按钮短暂显示 **加入中…**，然后徽章变成 **已连接**（connected）。**这台网关在虚拟网中的身份**（This gateway on the overlay）里出现 **虚拟网地址**（Overlay address）、**名称**（Name）和 **管理面**（Management）。

::: warning
徽章写 **管理面不可达** 时，hub 连不上 NetBird 的管理面，多半是出网受限。到[代理](./proxy.md)页打开 **让 微子·中枢 自己的流量走代理**，再回来点加入。
:::

## 导出 LAN 路由

![已连接，下面是局域网路由](/guide/zh/overlay_netbird_connected.webp)

**局域网路由**（LAN routes）一节列出每个 LAN 角色网口的子网，每行有 **复制**（Copy）。服务器形态没有 LAN 角色，这一节写着 **没有接口处于 LAN 角色**。

1. 在控制台的 Networks 下，把每个子网作为 Resource 添加到你的网络。
1. 给它配一条 Access Control Policy。

之后另一个节点用局域网地址就能访问那个子网里的机器。hub 是否在虚拟网上应答自己的面板和共享，由[网络](./network.md)页的 **开放范围** 决定。

## 看对端表

![节点表](/guide/zh/overlay_netbird_peers.webp)

**节点**（Peers）一行一个对端，列出名称、虚拟网地址、连接方式和上次握手的时间，有丢包时还列丢包率。连接方式是 **直连**（direct）或 **中继**（relayed）。表空着时写 **还没有节点。在另一台设备上用 NetBird 应用登录。**

## 从外面接入

另一台设备不装微子的任何包：装 NetBird 自己的应用，用同一个账号登录，这台设备就成了这张网的一个节点，能经 hub 进局域网。

要给 hub 换一个身份，在 **这台网关在虚拟网中的身份** 里点 **重新注册**（Re-enroll），粘贴一把新的 setup key。重新注册后 hub 在网络里是一个新节点，旧的节点条目留在控制台里，到那里删掉。
