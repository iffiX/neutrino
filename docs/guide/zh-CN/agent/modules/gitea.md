---
title: Gitea
---

# Gitea

装上 **Gitea** 模块，一台被控端 Linux 机器就成了私有 git 服务器，每个客户端都能在网页列表里打开它。模块的安装程序取来固定版本的 Gitea，支持 amd64 和 arm64，把它装好，再从机器自己的软件源装上 git。

开始之前，在[模块](../modules.md)页的 **Gitea** 标签下依次选择 **安装**（Install）和 **配置**（Configure）。标签下面随即展开 **接入**（Access）和 **管理员**（Administrator）两个分区。

![Gitea 标签和它的接入分区](/guide/zh/gitea.webp)

## 设置接入

**接入** 里是必须和中枢保持一致的设置。仓库、账号和其他所有设置都在 Gitea 里管理。

1. 设置 Gitea 监听的 **端口**（Port）。
1. 可选：设置 **Root URL**，克隆地址以它开头。留空则按机器的地址推导。
1. 可选：打开 **开放注册**（Open registration），访客就能自己注册账号。
1. 选择 **应用接入设置**（Apply access）。机器重写 `app.ini` 并重启 Gitea。

服务运行时，分区标题旁的 **打开 Gitea**（Open Gitea）在浏览器新标签页里打开它。

## 创建管理员

新装的 Gitea 没有账号。创建第一个账号：

1. 在 **管理员** 下填用户名、密码，需要的话再填邮箱。
1. 选择 **创建管理员**（Create administrator）。

服务启动之后，这个按钮才可用。管理员建好后，分区里显示它的名字和 **重置密码**（Reset password），用来给它设新密码。

## 手工装的 Gitea

中枢只配置它自己装的 Gitea。别人手工装的 Gitea 只上报端口，设置仍由它自己保管。

## 发布到哪里

Gitea 是[服务](../../hub/services.md)页 **网页**（Web）组里的一行，来源写着由那台机器上的 gitea 模块发布。在[桌面客户端](../../client/desktop.md)里，它是 **网页** 面板中的一项，带 **打开**（Open）按钮；Android 应用的网页列表里也有它。
