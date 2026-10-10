---
title: 安装被控端
---

# 安装被控端

被控端装在提供服务的机器上，用一条命令或安装包装；Linux 机器还能让中枢经 SSH 代装。

中枢自己那台机器不用装，设置向导已经在上面装好了被控端。

## 开始之前

- 这台机器的系统列在[支持的平台](../reference/platforms.md)里被控端那一栏。
- 你有这台机器的 root 权限，Windows 上是管理员权限。
- 这台机器能访问中枢的 8443 端口。

## 拿一条加入链接

1. 在面板里打开 **设备**。
1. 选择 **用链接添加**，通知里出现一条加入链接。
1. 选择 **复制**。

![加入链接和复制按钮](/guide/zh/devices_enroll_link.webp)

未管理机器的抽屉里，**获取链接** 也生成一条。链接 30 分钟内有效，新生成一条时上一条作废。

## 一条命令安装

下面的 `<enroll-link>` 是刚复制的加入链接。

### Linux 和 macOS

完整版：

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
```

国内版：

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh -s -- agent
```

在 `sudo` 的提示下输入一次密码。装好后加入中枢：

```bash
sudo nagent join '<enroll-link>'
```

### Windows

打开 PowerShell。完整版：

```powershell
& ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) agent
```

国内版：

```powershell
& ([scriptblock]::Create((irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1))) agent
```

Windows 弹出一次授权框，脚本在新开的管理员窗口里运行。装好后在这个窗口里加入中枢：

```powershell
nagent join '<enroll-link>'
```

## 用包文件安装

从发布页下载这台机器对应的文件。

### Linux

::: code-group

```bash [Debian、Ubuntu、树莓派 OS]
sudo apt install ./neutrino-agent_0.5.0_amd64.deb
sudo nagent join '<enroll-link>'
```

```bash [Fedora、RHEL 系]
sudo dnf install ./neutrino-agent-0.5.0-1.x86_64.rpm
sudo nagent join '<enroll-link>'
```

:::

ARM64 机器的文件名以 `_arm64.deb` 或 `.aarch64.rpm` 结尾。

### macOS

Apple 芯片的 Mac 运行下面的命令，Intel 的 Mac 用 `neutrino-agent-0.5.0-macos-amd64.pkg`：

```bash
sudo installer -pkg neutrino-agent-0.5.0-macos-arm64.pkg -target /
sudo nagent join '<enroll-link>'
```

### Windows

1. 运行 `neutrino-agent-0.5.0-windows-amd64.msi`。
1. 以管理员身份新开一个 PowerShell，让它读到新的 `PATH`。
1. 运行 `nagent join '<enroll-link>'`。

静默安装时，在管理员 PowerShell 里运行 `msiexec /i neutrino-agent-0.5.0-windows-amd64.msi /qn`。

## 让中枢经 SSH 代装

只对 Linux 机器有效。先在[凭据](../hub/credentials.md)页存好那台机器的 SSH 密钥或登录信息。

1. 在 **未管理的设备** 里打开那台机器的抽屉。
1. 选择 **安装被控端**。
1. 填 **主机**、**端口** 和 **用户名**。
1. 在 **凭据** 里选 **SSH 密钥** 或 **密码**，再选存好的那一条。
1. 可选：账户要密码才能 sudo 时，在 **Sudo 密码** 里选一份登录信息。
1. 选择 **安装被控端**。

![SSH 安装对话框：主机、端口、用户名和凭据](/guide/zh/devices_install_ssh.webp)

**安装输出** 实时显示安装过程。对方不是 Linux 时，改用加入链接。

## 核对机器

加入成功时，`nagent join` 打印两行，第二行是中枢的地址和这台机器的 id，`<device-id>` 代表这个 id：

```text
joined the hub
joined https://192.168.1.10:8443 as <device-id>
```

几秒之内，这台机器出现在 **设备** 页的 **已管理的设备** 里。在那台机器上运行 `sudo nagent status` 看连接状态，Windows 上在管理员 PowerShell 里运行 `nagent status`。

机器已经加入过别的中枢时，`nagent join` 替换之前先确认，加 `--yes` 直接替换。加入失败时，见[故障排查](../reference/troubleshooting.md#加入中枢失败)。

## 包在机器上装了什么

Linux 上，被控端是 systemd 服务 `neutrino_agent`；Windows 上是以 LocalSystem 运行的服务；macOS 上是以 root 运行的 LaunchDaemon。日志的位置见[故障排查](../reference/troubleshooting.md#日志在哪)。

每个包都带一份 RustDesk。在模块页这台机器的 **远程桌面** 标签里打开 **共享这台机器的桌面** 时，被控端才把 RustDesk 注册成系统服务。从机器上拿掉被控端，见[卸载](../uninstall.md)。
