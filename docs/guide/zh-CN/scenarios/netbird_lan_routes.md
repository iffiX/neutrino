---
title: 经 NetBird 访问没装被控端的设备
---

# 经 NetBird 访问没装被控端的设备

家里的打印机、路由器管理页这类设备装不了被控端。这一页在 NetBird 控制台里给它们的网段加一条路由，让连着 NetBird 的客户端在家外面用局域网地址打开它们。

国内版没有 NetBird，也没有旁路网关。用国内版时，读[经 EasyTier 访问没装被控端的设备](./easytier_lan_routes.md)。

开始之前：

- 中枢已经加入 NetBird，客户端能经 NetBird 连上中枢，见[把中枢加入 NetBird](../hub/netbird.md)。
- 中枢是 **路由器** 或 **旁路网关** 模式。
- 你在这个 NetBird 账号的控制台里有管理员权限。

## 读出中枢服务的网段

1. 在面板的 **外部访问** 页，选择 **NetBird** 卡片。
1. 在 **局域网路由** 里，选择设备所在的那个网段。

面板把这个网段复制到剪贴板。

![NetBird 卡片上的局域网路由，列出一个网段](/guide/zh/overlay_netbird_routes.webp)

## 把网段加成资源

控制台的 **Add Network** 向导依次建网络、资源、策略和路由节点，本节和后面两节照这个顺序走。

1. 打开 NetBird 控制台 **Network Routing** 下的 **Networks**。
1. 选择 **Add Network**。
1. 在 **Name** 里给网络起个名字，进入下一步 **Add Resource**。
1. 在 **Name** 里给资源起个名字。
1. 在 **Address** 里粘贴刚才复制的网段。
1. 进入下一步，也就是访问控制这一步。

## 给客户端的分组放行

客户端用中枢那把 setup key 加入 NetBird，所以都在这把 key 的自动分组里。**Setup Keys** 列表里，这把 key 的 **Groups** 一栏写着这个分组。

1. 在访问控制这一步选择 **Add Policy**。
1. 来源选 setup key 的自动分组。
1. 目标选上一节的资源。
1. 协议选 **All**。
1. 选择 **Continue**。
1. 选择 **Submit**。

建好的策略列在控制台 **Access Control** 下的 **Policies** 里。

![NetBird 控制台里的策略，来源是自动分组，目标是局域网资源](/guide/console/console_netbird_policy.webp)

## 把中枢设成路由节点

1. 在 **Add Routing Peer** 里选中中枢那个节点。
1. 选择 **Continue**。
1. 选择 **Submit**。

**Install NetBird** 是给还没装 NetBird 的机器用的，这里不选它。

![NetBird 控制台里的网络，路由节点是中枢，资源是局域网网段](/guide/console/console_netbird_network.webp)

## 在客户端上验证

1. 在家外面打开客户端，确认中枢那一行显示 **已连接 · NetBird**。
1. 在浏览器里打开设备的局域网地址。

人在家里时测不出这条路由，浏览器直接连到设备。安卓 App 的虚拟网连着时，控制台里新加的路由自动生效，不用断开再连。

## 设备还是打不开时

浏览器连不上设备、面板上也没有红字时，检查控制台里有没有给客户端分组放行的策略。没有就照「给客户端的分组放行」补上。**外部访问** 页顶部出现红字时，见[故障排查](../reference/troubleshooting.md#外部访问)。
