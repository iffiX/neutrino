---
title: Gitea
---

# Gitea

装好 **Gitea** 模块，受管机器上就跑着你自己的 git 服务，客户端在 **网页**（Web）页里打开它。一台机器一个 Gitea，Linux、macOS 和 Windows 都能跑。你在这台机器上安装 Gitea：模块的安装程序取来 Gitea 发布方构建的二进制文件，版本固定。

## 安装

1. 在[模块](../modules.md)页的 **Gitea** 标签下，选择 **安装**（Install）。
1. 选择 **配置**（Configure）。标签下面随即展开 **接入**（Access）和 **管理员**（Administrator）。

Linux 上，安装程序从机器自己的软件源一并装上 git。macOS 和 Windows 上，git 要你先装好：Mac 上装开发者工具或 Homebrew 的 git，Windows 上装 Git for Windows。机器上没有能用的 git 时，安装和应用都以 `gitea_git_missing` 失败。

## 设置接入

**接入** 里是要和中枢保持一致的设置。仓库、账号和其他设置都在 Gitea 里管理。

1. 设置 Gitea 监听的 **端口**（Port）。
1. 可选：设置 **Root URL**，克隆地址以它开头。留空时按机器的地址推导。
1. 可选：打开 **开放注册**（Open registration），访客就能自己注册账号。
1. 选择 **应用接入设置**（Apply access）。机器重写 `app.ini` 并重启 Gitea。

![server 的 Gitea 标签和它的接入设置](/guide/zh/gitea.webp)

服务运行时，标题旁的 **打开 Gitea**（Open Gitea）在浏览器新标签页里打开它。

## 创建管理员

新装的 Gitea 没有账号。标签的状态词读 **运行中**（running）时，服务已经启动，**创建管理员** 才能按。

1. 在 **管理员** 下填用户名和密码，需要时再填邮箱。
1. 选择 **创建管理员**（Create administrator）。

管理员建好后，这里显示它的名字和 **重置密码**（Reset password），用来给它设新密码。

## 在 macOS 和 Windows 上

- 克隆和推送只走 HTTP，这两种系统上的 Gitea 没有 SSH。
- Mac 上，Gitea 以隐藏账户 `neutrino_gitea` 运行。
- Windows 上，Gitea 以 LocalSystem 运行。
- **卸载**（Uninstall）删掉服务、二进制文件和 `app.ini`，数据目录和运行账户都留下，再装一次就接着用原来的仓库和账号。

## 手工装的 Gitea

中枢只配置它自己装的 Gitea。别人手工装的 Gitea 只上报端口，设置仍由它自己保管。

## 发布到哪里

Gitea 是[服务](../../hub/services.md)页 **网页**（Web）组里的一行，来源写着由那台机器上的 gitea 模块发布。在[桌面客户端](../../client/desktop.md)里，它是 **网页** 页上的一项，带 **打开**（Open）按钮；Android 应用的网页列表里也有它。
