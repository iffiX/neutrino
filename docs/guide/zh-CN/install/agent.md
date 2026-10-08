---
title: 安装被控端
---

# 安装被控端

被控端装好并加入中枢之后，那台 Linux、macOS 或 Windows 机器就出现在面板上。它列在 **设备**（Devices）页的 **已管理的设备**（Managed devices）里，状态是在线。被控端可以用一条命令装，也可以用安装包装；Linux 机器还能交给中枢经 SSH 代装。

中枢自己那台机器不用装：设置向导已经在上面装好了被控端。

## 开始之前

- 机器的系统在[支持的平台](../reference/platforms.md)的被控端一栏里。
- 你有这台机器的 root 权限，Windows 上是管理员权限。
- 这台机器能访问中枢的 8443 端口。

## 拿一条加入链接

1. 在面板里打开 **设备**。
1. 选择 **用链接添加**（Add by link）。通知里出现一条加入链接。
1. 选择 **复制**（Copy）。

![加入链接和复制按钮](/guide/zh/devices_enroll_link.webp)

**未管理的设备**（Unmanaged devices）里，每台机器的抽屉都有 **获取链接**（Get link），为那一行生成一条链接。两种按钮生成的加入链接规则相同：30 分钟内有效，中枢中途重启也照样有效。新生成一条加入链接时，上一条随即作废。

## 一条命令安装

下面的命令装好被控端后，用 `nagent join` 加入中枢。命令里的 `<enroll-link>` 换成刚复制的加入链接。

### Linux 和 macOS

完整版：

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
```

国内版：

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh -s -- agent
```

下载开始之前，你在 `sudo` 的提示下输入一次密码。

装好后加入中枢：

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

PowerShell 不是以管理员身份运行时，Windows 弹出一次授权框，脚本在新开的管理员窗口里接着运行。脚本为这个窗口更新了 `PATH`，装好后就在这个窗口里加入中枢：

```powershell
nagent join '<enroll-link>'
```

## 用包文件安装

从发布页下载这台机器对应的文件。每个系统装好包后，都用 `nagent join` 加入中枢。

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

ARM64 机器的文件名以 `_arm64.deb` 或 `.aarch64.rpm` 结尾。`apt` 和 `dnf` 连同依赖一起装，`dpkg -i` 和 `rpm -i` 不装依赖。

### macOS

Apple 芯片的 Mac 运行：

```bash
sudo installer -pkg neutrino-agent-0.5.0-macos-arm64.pkg -target /
sudo nagent join '<enroll-link>'
```

Intel 的 Mac 用 `neutrino-agent-0.5.0-macos-amd64.pkg`。

### Windows

1. 运行 `neutrino-agent-0.5.0-windows-amd64.msi`。
1. 以管理员身份新开一个 PowerShell，让它读到新的 `PATH`。
1. 运行 `nagent join '<enroll-link>'`。

静默安装时，在管理员 PowerShell 里运行 `msiexec /i neutrino-agent-0.5.0-windows-amd64.msi /qn`。

## 让中枢经 SSH 代装

这个办法只对 Linux 机器有效。开始之前，在[凭据](../hub/credentials.md)页存好那台机器的 SSH 密钥或登录信息。

1. 在 **未管理的设备** 里打开那台机器的抽屉。
1. 选择 **安装被控端**（Install agent）。
1. 填 **主机**（Host）、**端口**（Port）和 **用户名**（Username）。
1. 在 **凭据**（Credential）里选 **SSH 密钥**（SSH key）或 **密码**（Password），再选存好的那一条。
1. 可选：在 **Sudo 密码**（Sudo password）里选 `sudo` 要用的登录信息。账户免密 sudo 时留空。
1. 选择 **安装被控端**。

![SSH 安装对话框：主机、端口、用户名和凭据](/guide/zh/devices_install_ssh.webp)

**安装输出**（Install output）实时显示安装过程。中枢先读对方的系统，不是 Linux 时返回 `unsupported_remote_install`，改用加入链接即可。

## 核对机器

加入成功时，`nagent join` 打印中枢的地址和这台机器的 id：

```text
joined https://192.168.1.10:8443 as <device-id>
```

几秒之内，这台机器出现在 **已管理的设备** 里。在那台机器上运行 `sudo nagent status`，看被控端的服务和连接状态；Windows 上在管理员 PowerShell 里运行 `nagent status`。

- `nagent join` 不带链接时，提示你粘贴一条。
- 机器已经加入过别的中枢时，`nagent join` 先确认再替换；加 `--yes` 直接替换。
- 链接用过、无效或已过期时，中枢返回 `ticket_spent`。在面板里生成一条新链接再加入。

## 包在机器上装了什么

| 系统    | 程序目录                                          | 服务                                            | 日志                                          |
| ------- | ------------------------------------------------- | ----------------------------------------------- | --------------------------------------------- |
| Linux   | `/opt/neutrino/agent`                             | systemd 服务 `neutrino_agent`                   | systemd 日志，`journalctl -u neutrino_agent`  |
| Windows | `C:\Program Files\Neutrino\agent`                 | `neutrino_agent` 服务，以 LocalSystem 运行      | `C:\ProgramData\Neutrino\agent\log\agent.log` |
| macOS   | `/Library/Application Support/Neutrino/agent/app` | LaunchDaemon `com.neutrino.agent`，以 root 运行 | `/Library/Logs/Neutrino/agent/agent.log`      |

每个包都带一份 RustDesk，放在被控端自己的目录里。模块页上这台机器的 **Remote desktop** 开关打开时，被控端才把 RustDesk 注册成系统服务；关掉时，被控端恢复机器原来的样子。
