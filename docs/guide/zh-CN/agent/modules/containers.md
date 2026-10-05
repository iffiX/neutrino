---
title: Containers
---

# Containers

**Containers** 模块管理你声明的容器：被控端 Linux 机器上的 podman 运行它们，每个容器是一个 systemd 单元。容器发布的每个主机端口，都成为客户端里的一项。podman 4.4 起，一条声明变成一个 Quadlet `.container` 文件。podman 更老时，比如 Debian 12 自带的 4.3，被控端自己写出 `.service` 单元，声明的含义不变。

开始之前，在[模块](../modules.md)页的 **Containers** 标签下依次选择 **安装**（Install）和 **配置**（Configure）。标签下面随即展开 **正在运行**（Running now）、**镜像源**（Registry mirrors）和 **声明的容器**（Declared containers）三个分区。

![Containers 标签和声明的容器](/guide/zh/containers.webp)

## 声明容器

1. 在 **声明的容器** 下选择 **添加容器**（Add container）。
1. 填 **名称**（Name）。
1. 填 **镜像标签**（Image tag），或者选择 **选择标签**（Pick a tag），从仓库列出的标签里挑。
1. 在 **端口**（Ports）里把主机端口映射到容器端口，例如 `8080:80`。
1. 在 **卷**（Volumes）里把存数据的主机文件夹映射到容器里的路径，例如 `/srv/share:/data`。
1. 可选：在 **环境变量**（Environment）里逐行写 `KEY=value`；想换掉镜像自带的命令时，填 **命令（可选）**（Command (optional)）。
1. 可选：关掉 **随机器启动**（Start with the box），容器保持声明状态，你手动启动它才运行。
1. 选择 **应用容器**（Apply containers）。容器第一次启动要拉镜像，可能要等一会儿。

每个容器都是 podman 默认网络上的一个 systemd 单元。基础镜像需要一个长期运行的命令。

::: warning
应用时，改过的容器都要重建，卷以外的文件随之丢失。
:::

## 正在运行

**正在运行** 列出机器上的每个容器和它的状态。每一行有 **启动**（Start）、**停止**（Stop）、**重启**（Restart）、**日志**（Journal）和 **Shell**。**日志** 显示容器的日志，**Shell** 在页面上的窗口里打开容器内的 shell。

## 镜像源

拉镜像时，先按顺序试镜像源，最后才走 `docker.io`。选择 **添加镜像源**（Add mirror），填地址，再选择 **应用镜像源**（Apply mirrors）。下一次拉取时生效，不重启任何东西。

## 机器上已有的容器

第一次 **配置** 把机器上已有的容器收为声明，连同镜像、端口、卷和环境变量，镜像源也一并收下。从此，这个标签里的声明是这台机器唯一的依据。

## 发布到哪里

容器发布的每个主机端口，都是[服务](../../hub/services.md)页 **端口**（Ports）组里的一行，来源写着由那个容器的镜像发布。在[桌面客户端](../../client/desktop.md)里，它是 **端口** 面板中的一项，带 **连接**（Connect）按钮。带 `/udp` 发布的端口，例如 `5353:5353/udp`，单独成为一项，地址写成 `host:port/udp`。
