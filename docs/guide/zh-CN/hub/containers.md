---
title: 容器
---

# 容器

容器模块按你写下的声明，在一台被控端机器上以 systemd 单元运行容器；声明包括镜像、端口和卷。它的 **声明的容器**（Declared containers）、**正在运行**（Running now）和 **镜像源**（Registry mirrors）三节，在[模块](./modules.md)页的 **Containers** 标签下点 **配置**（Configure）之后展开。第一次点 **配置**，hub 把机器上已有的容器和镜像源收下来。

podman 4.4 起，一条声明变成一个 Quadlet `.container` 文件，由 podman 转成 systemd 单元。podman 更老时（例如 Debian 12 自带的 4.3），被控端自己写出 `.service` 单元，声明的含义不变。

## 声明容器

1. 点 **添加容器**（Add container）。
1. 填 **名称**（Name）。
1. 填 **镜像标签**（Image tag），或者点 **选择标签**（Pick a tag）从仓库列表里选。
1. 在 **端口**（Ports）里写主机端口到容器端口的映射。
1. 在 **卷**（Volumes）里写要保留的目录。
1. 需要时填 **环境变量**（Environment）和 **命令（可选）**，勾选 **随机器启动**（Start with the box）。命令一栏在英文界面上是 Command (optional)。
1. 点 **应用容器**（Apply containers）。

第一次启动要拉镜像，可能要等一会儿。

::: warning
改过的容器在应用时重建，卷以外的文件丢失。要保留的数据都放进卷。
:::

## 正在运行

**正在运行** 一行一个容器，带 **启动**（Start）、**停止**（Stop）、**重启**（Restart）、**日志**（Journal）和 **Shell**。Shell 在页面里打开容器内的命令行；退出后，这个命令行打印过的内容保留到你关闭它为止。

## 镜像仓库镜像

**镜像源** 列出拉取时先于 docker.io 尝试的地址，按顺序试。点 **添加镜像源**（Add mirror），填地址，点 **应用镜像源**（Apply mirrors）；下一次拉取生效，不重启任何东西。

## 发布结果

容器发布的每个主机端口成为 **服务**（Services）页 **端口**（Ports）组里的一行，来源写着由容器某镜像发布。客户端的 **端口** 面板里，这一行有 **连接**（Connect），把它转到本机回环地址，步骤在客户端的[端口](../client/ports.md)页。
