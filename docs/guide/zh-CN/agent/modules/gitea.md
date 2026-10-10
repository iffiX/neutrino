---
title: Gitea
---

# Gitea

装上 **Gitea** 模块，一个被控端就成了私人 Git 服务器，仓库存在这台机器上。一台机器一个 Gitea，Linux、macOS 和 Windows 都能跑，版本固定。

## 安装

1. 在[模块](../modules.md)页的 **Gitea** 标签下，选择 **安装**。
1. 选择 **配置**，标签下面展开 **接入** 和 **管理员**。

Linux 上，安装程序一并装上 git。Mac 上先装开发者工具或 Homebrew 的 git，Windows 上先装 Git for Windows；没有 git 时安装失败，见[故障排查](../../reference/troubleshooting.md#模块页上的错误)。

## 设置接入

**接入** 里是要和中枢一致的设置，其余设置在 Gitea 里管理。

1. 设置 Gitea 监听的 **端口**。
1. 可选：设置 **Root URL**，克隆地址以它开头；留空时按机器的地址推导。
1. 可选：打开 **开放注册**，访客就能自己注册账号。
1. 选择 **应用接入设置**。机器重写 `app.ini` 并重启 Gitea。

![server 的 Gitea 标签和它的接入设置](/guide/zh/gitea.webp)

服务运行时，标题旁的 **打开 Gitea** 在新标签页里打开它。

## 创建管理员

新装的 Gitea 没有账号。标签读 **运行中** 时才能创建。

1. 在 **管理员** 下填用户名和密码，需要时再填邮箱。
1. 选择 **创建管理员**。

建好后，这里显示管理员的名字和 **重置密码**。

## 在 macOS 和 Windows 上

- 克隆和推送只走 HTTP，这两种系统上的 Gitea 没有 SSH。
- Mac 上，Gitea 以隐藏账户 `neutrino_gitea` 运行。
- Windows 上，Gitea 以 LocalSystem 运行。
- **卸载** 删掉服务、程序和 `app.ini`，数据和运行账户留下。

## 手工装的 Gitea

中枢只配置它自己装的 Gitea。手工装的 Gitea 只上报端口。

## 发布到哪里

Gitea 是[服务](../../hub/services.md)页 **网页** 组里的一行，客户端在 **网页** 页上选 **打开**。
