---
title: 容器
---

# 容器

**容器**（Containers）页在一台被控端机器上按声明运行容器。声明是你在这一页填的一条容器描述，包括镜像、端口和卷；podman 把每个声明变成那台机器上的一个 systemd 单元。容器发布的端口出现在每个客户端里。

## 启用设备

![容器页](/guide/zh/containers.webp)

1. 打开 **容器**（Containers）页。
1. 在 **已启用的设备**（Enabled devices）里勾选一台机器，点 **应用设备**（Apply devices）。
1. 在确认框里再点一次。

被控端装上 podman，页面下方出现 **声明的容器**（Declared containers）、**正在运行**（Running now）和 **镜像源**（Registry mirrors）。

::: warning
容器模块需要 podman 4.4 或更新：声明靠 podman 的 Quadlet 机制变成 systemd 单元，4.4 才带这个机制。Debian 12 自带 4.3.1，勾选这样的机器时 hub 拒绝启用。
:::

## 声明容器

1. 点 **添加容器**（Add container）。
1. 填 **名称**（Name）。
1. 填 **镜像标签**（Image tag），或者点 **选择标签**（Pick a tag）从仓库列表里选。
1. 在 **端口**（Ports）里写主机端口到容器端口的映射。
1. 在 **卷**（Volumes）里写要保留的目录。
1. 需要时填 **环境变量**（Environment）和 **命令（可选）**，勾选 **随机器启动**（Start with the box）。命令一栏在英文界面上是 Command (optional)。
1. 点 **应用容器**（Apply containers）。

第一次启动要拉镜像，可能要等一会儿。改过的容器会重建，卷以外的文件丢失，所以要保留的数据都放进卷。

## 正在运行

**正在运行** 一行一个容器，带 **启动**（Start）、**停止**（Stop）、**重启**（Restart）、**日志**（Journal）和 **Shell**。Shell 在页面里打开容器内的命令行；退出后，这个命令行打印过的内容保留到你关闭它为止。

## 镜像仓库镜像

**镜像源** 列出拉取时先于 docker.io 尝试的地址，按顺序试。点 **添加镜像源**（Add mirror），填地址，点 **应用镜像源**（Apply mirrors）；下一次拉取生效，不重启任何东西。

## 发布结果

容器发布的每个主机端口成为 **服务**（Services）页 **端口**（Ports）组里的一行，来源写着由容器某镜像发布。客户端的 **端口** 面板里，这一行有 **连接**（Connect），把它转到本机回环地址，步骤在客户端的[端口](../client/ports.md)页。
