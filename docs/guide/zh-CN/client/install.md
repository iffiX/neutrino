---
title: 安装客户端
---

# 安装客户端

客户端装在一个人的电脑上，以这个人的普通账户运行，Linux、Windows 和 macOS 都有包。粘一条链接就加入一个 hub；加入几个，窗口里就有几行，每行下面是那个 hub 发布的服务。

## 开始之前

- 一台有桌面会话的电脑。支持的系统在[支持的平台](../reference/platforms.md)里。
- 一个普通账户。`nclient` 拒绝以 root 运行。
- 这台电脑能访问每一个要加入的 hub 的 8443 端口。

## 在客户端页新建链接

1. 在面板的 **客户端**（Clients）页点 **新建客户端链接**（New client link）。

   ![新建客户端链接](/guide/zh/clients_create_link.webp)

1. 在名称里填这台电脑的名字，例如 `laptop`，点 **创建链接**（Create link）。
1. 点 **复制**（Copy）。链接五分钟内有效。

![链接通知](/guide/zh/clients_link_notice.webp)

设备页发的链接给被控端；把那种链接粘进客户端时，客户端返回 `link_not_for_client`。

## 安装包

从 [Releases](https://github.com/iffiX/neutrino/releases) 下载对应的包。

::: code-group

```bash [Debian 系]
sudo apt install ./neutrino-client_0.3.0_amd64.deb
nclient gui
```

```bash [RHEL 系]
sudo dnf install ./neutrino-client-0.3.0-1.x86_64.rpm
nclient gui
```

```powershell [Windows]
msiexec /i neutrino-client-0.3.0-windows-amd64.msi
```

```bash [macOS]
sudo installer -pkg neutrino-client-0.3.0-macos-arm64.pkg -target /
```

:::

Linux 上的包声明了对 WebKitGTK、托盘指示器、cifs-utils 和 polkitd 的依赖，包管理器一并装上。窗口从应用菜单的 Neutrino Client 打开，或者运行 `nclient gui`。

Windows 上也能双击 msi。安装程序显示一个把 `nclient` 命令加进 PATH 的选项；不加也能从开始菜单打开窗口。机器上没有 WebView2 运行时的话，安装程序顺带装上。卸载程序显示一个保留这个人配置的选项。

![Windows 安装程序](/guide/os/win_msi_installer.webp)

macOS 上的包只有 Apple 芯片版本，应用装在 `/Applications`，`nclient` 链到 `/usr/local/bin`。Gatekeeper 第一次会拦：右键 pkg 选“打开”。点应用图标即打开窗口。

三个系统上，关闭窗口只是隐藏它，客户端仍在运行。托盘菜单里有 **打开**（Open）和 **退出**（Quit）。托盘图标的位置：Windows 在任务栏角落，Linux 在顶栏的指示器区，macOS 在菜单栏。

![Windows 托盘菜单](/guide/os/win_tray_flyout.webp)

## 加入第一个 hub

1. 打开窗口。**Hub** 区写着 **尚未加入任何 hub**（No hub joined yet），下面是 **加入 hub**（Join a hub）那一行。

   ![尚未加入](/guide/zh/client_disconnected.webp)

1. 把链接粘进那一行的输入框，点 **加入**（Join）。

这个 hub 多出一行，写着 **已连接**（Connected）、它的地址和它运行的软件包。**服务**（Services）区在这个 hub 的名字下面画出五个面板。

![已加入一个 hub](/guide/zh/client_connected.webp)

![Windows 上已加入](/guide/zh/win_client_connected.webp)

终端里同一件事：

```bash
nclient join 'neutrino://enroll/PLACEHOLDER_LINK'
```

链接过期时客户端返回 `enroll_refused`。

## 再加入一个 hub

有几条链接就能加入几个 hub。每个 hub 各发各的链接，各记各的电脑名字，各发布各的服务，几个 hub 之间没有共享。

1. 在另一个 hub 的面板里，同样新建一条客户端链接。
1. 把链接粘进 **加入 hub** 那一行，点 **加入**。

**Hub** 区多一行，**服务** 区多一组。终端里 `nclient join` 加入一个 hub，`nclient leave --hub` 离开指定的那个。

## 五类服务的用法

| 面板                             | 条目从哪来                          | 按钮       |
| -------------------------------- | ----------------------------------- | ---------- |
| [网页](./web.md)                 | Gitea 模块，手动声明的网址          | 打开       |
| [端口](./ports.md)               | 容器发布的端口，手动声明的 TCP 端口 | 连接、断开 |
| [AI](./ai.md)                    | hub 的 AI 网关                      | 配置、应用 |
| [文件](./files.md)               | Samba 模块，手动声明的共享          | 配置、挂载 |
| [远程桌面](./remote-desktops.md) | 机器自己共享的桌面                  | 连接       |
