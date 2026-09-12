---
title: 安装被控端
---

# 安装被控端

被控端装在要管的每台 Linux 机器上。装好并接入后，这台机器出现在 **设备**（Devices）页的 **已管理的设备**（Managed devices）里，向 hub 汇报状态并接受模块。被控端只有 Linux 版本，以 root 运行，没有窗口。

## 开始之前

- 一台 Linux 机器，x86-64 或 ARM64，带 systemd。支持的发行版在[支持的平台](../reference/platforms.md)里。
- 这台机器上的 root 权限。`nagent` 的每个子命令都要 root。
- 这台机器能访问 hub 的 8443 端口。被控端通道走这个端口的 TLS，证书指纹写在加入链接里。

## 方式一：链接注册

1. 在面板的 **设备** 页点 **用链接添加**（Add by link）。

   ![加入链接](/guide/zh/devices_enroll_link.webp)

1. 点 **复制**（Copy）。链接形如 `neutrino://enroll/…`，五分钟内有效；再生成一条时，上一条作废。
1. 在那台机器上装好包，步骤在[直接装包](#直接装包)一节。
1. 在那台机器的终端里接入。

   ```bash
   sudo nagent connect 'neutrino://enroll/PLACEHOLDER_LINK'
   ```

命令返回后几秒内，这台机器出现在 **已管理的设备** 里。不带链接运行 `sudo nagent connect`，它改为提示粘贴；机器已经绑定过别的 hub 时，加 `--yes` 直接替换。

![已管理的设备](/guide/zh/devices_managed.webp)

::: tip
链接的载荷是 base64url，不含任何 shell 会拆开的字符，不加引号粘贴也行。
:::

## 方式二：从面板经 SSH 安装

这个方式适合 hub 能用 SSH 登录的机器。凭据先在[凭据](../hub/credentials.md)页保存好：一把 SSH 密钥，或一组用户名和密码。

1. 在 **设备** 页的 **未管理的设备**（Unmanaged devices）里点开那台机器。
1. 点 **安装被控端**（Install agent）。

   ![SSH 安装对话框](/guide/zh/devices_install_ssh.webp)

1. 填 **主机**（Host）、**端口**（Port）和 **用户名**（Username）。
1. 在 **凭据**（Credential）里选一把 SSH 密钥或一条登录信息。
1. 账户执行 sudo 要密码时，填 **Sudo 密码**（Sudo password）；免密 sudo 留空。
1. 点 **安装被控端**。

**安装输出**（Install output）面板实时打印安装过程，最后一行是退出码。安装过程生成一条加入链接并用它接入，不用你复制。hub 只在安装和重新安装时通过 SSH 登录设备，之后不再主动连它。机器报告的系统不是 Linux 时，面板拒绝并提示改用链接。

## 直接装包

从 [Releases](https://github.com/iffiX/neutrino/releases) 下载对应的包。

::: code-group

```bash [Debian 系]
sudo apt install ./neutrino-agent_0.2.0_amd64.deb
```

```bash [RHEL 系]
sudo dnf install ./neutrino-agent-0.2.0-1.x86_64.rpm
```

:::

ARM64 机器换成 `_arm64.deb` 或 `.aarch64.rpm`。包自带解释器和 RustDesk 主机，它的 GTK 和 X 依赖是给 RustDesk 主机用的。装完之后用 `sudo nagent connect` 接入，命令见上文。

## hub 自己的被控端

hub 初始化的最后一步在它自己这台机器上装了被控端，所以设备页里从一开始就有一台已管理的设备。这台被控端和其他被控端一样接受模块：在 Samba 页勾选 hub 这台机器，共享就由这台机器提供。这台被控端的配置在 `/etc/neutrino/agent`，`nhub reset all` 不动这个目录。

## 分配能力

一台机器进了 **已管理的设备** 之后，你就能在侧栏 **被控端**（Agent）组的每一页里勾选这台机器。

| 页面                         | 这台机器得到什么                     |
| ---------------------------- | ------------------------------------ |
| [终端](../hub/terminals.md)  | 面板里的 root shell                  |
| [文件](../hub/files.md)      | 面板里的文件浏览器                   |
| [Samba](../hub/samba.md)     | SMB 共享，客户端能挂载               |
| [Gitea](../hub/gitea.md)     | 私有 git 服务器，客户端能打开        |
| [容器](../hub/containers.md) | 按声明运行的容器，发布的端口进客户端 |
| [ZFS](../hub/zfs.md)         | 存储池、数据集和磁盘健康             |
