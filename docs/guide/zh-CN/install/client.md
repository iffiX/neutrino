---
title: 安装客户端
---

# 安装客户端

客户端装在你自己的电脑或 Android 手机上。装好并加入中枢之后，中枢那一行读 **已连接 ·**（Connected ·），后面是这次连上中枢的路径。一台电脑同一时间只运行一个账户的客户端；另一个账户这时运行 `nclient` 命令，返回 `client_held`。

## 开始之前

- 系统是下面之一：
  - 带桌面会话的 Linux：Debian 12、Ubuntu 22.04 或更新版本，RHEL 9、AlmaLinux 9、Fedora 41 或更新版本。
  - macOS 12.3 或更新版本，Apple 芯片或 Intel。
  - x86-64 上的 Windows 10 1809 或更新版本。
  - Android 8.0 或更新版本，64 位 ARM 处理器。
- 电脑上用你自己的普通账户运行客户端。以 root 运行时，客户端返回 `root_refused`。
- 能访问中枢的 8443 端口：在家里直接访问，在外面经一种外部访问办法访问。

外部访问有哪几种办法，见[外部访问](../hub/overlay.md)。

## 一条命令装桌面客户端

用你自己的账户运行下面的命令，命令前面不加 `sudo`。你还没加入过中枢时，脚本最后打印一行 `nclient join` 的用法。

### Linux 和 macOS

完整版：

```bash
curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- client
```

国内版：

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh -s -- client
```

装包那一步由脚本调用 `sudo`，下载开始之前你输入一次密码。

### Windows

打开 PowerShell。完整版：

```powershell
& ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) client
```

国内版：

```powershell
& ([scriptblock]::Create((irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1))) client
```

Windows 弹出一次授权框，安装在新开的管理员窗口里进行。加入中枢时，以你自己的账户新开一个 PowerShell。

## 用包文件装桌面客户端

从发布页下载对应系统的包，然后安装：

::: code-group

```bash [Debian、Ubuntu]
sudo apt install ./neutrino-client_0.5.0_amd64.deb
```

```bash [RHEL、AlmaLinux、Fedora]
sudo dnf install ./neutrino-client-0.5.0-1.x86_64.rpm
```

```powershell [Windows]
msiexec /i neutrino-client-0.5.0-windows-amd64.msi
```

```bash [macOS]
sudo installer -pkg neutrino-client-0.5.0-macos-arm64.pkg -target /
```

:::

64 位 ARM 的 Linux 上，`.deb` 文件名里写 `arm64`，`.rpm` 文件名里写 `aarch64`。Intel 的 Mac 用 `neutrino-client-0.5.0-macos-amd64.pkg`。`apt` 和 `dnf` 连同依赖一起装：WebKitGTK、托盘库、`cifs-utils` 和 polkit。

::: warning
`dpkg -i` 和 `rpm -i` 不装依赖。已经用了的话，Debian 系运行 `sudo apt -f install`，RHEL 系用 `sudo dnf install` 装上它列出的包。
:::

Windows 上双击 `.msi` 也是同一个安装程序。保持勾选 **Add the Neutrino Client to PATH**，任何终端里都能用 `nclient`。机器上没有 WebView2 运行时的话，安装程序运行微软的引导程序装上它。卸载时勾选 **Keep my configuration**，下次装好后直接回到原来的中枢。

![Windows 安装程序](/guide/os/win_msi_installer.webp)

macOS 上，安装程序把 **Neutrino Client** 放进 `/Applications`，把 `nclient` 链接到 `/usr/local/bin`。这个应用只有临时签名，第一次打开时，在 Gatekeeper 的提示里确认一次。

每个包都登记虚拟网用的系统服务：NetBird 守护进程和 EasyTier 守护进程。国内版的包只有 EasyTier 守护进程。Windows 上还多一个服务 `NeutrinoClientFiles`，**文件**（Files）页靠它把共享挂成盘符。客户端运行时升级，安装程序先让它退出，装完再在原来那个账户的会话里打开它。

## 装安卓 App

1. 在手机上从发布页下载 `neutrino-client-0.5.0-android.apk`。
1. 打开这个文件。Android 提示时，允许浏览器或文件管理器安装应用。
1. 选 **安装**，装好后打开 **微子**。

国内版的 apk 在 Gitee 的发布页上，里面没有 NetBird。

每个发布的 apk 都用项目自己的密钥签名。要核对下载的 apk，在装有 Android SDK 构建工具的电脑上运行：

```bash
apksigner verify --print-certs neutrino-client-0.5.0-android.apk
```

```text
Signer #1 certificate SHA-256 digest: 0e20b8b4542f329c4d3ed91632f3ea90730cb99472c46c31585780d046ee612d
```

37 及更新版本的构建工具把这一行打成 `V2 Signer: certificate SHA-256 digest: …`，摘要相同。

::: warning
摘要对不上，就删掉这个 apk，别安装它。
:::

## 生成客户端链接

1. 在中枢的面板里打开 **客户端**（Clients）。
1. 选择 **新建客户端链接**（New client link）。
1. 填这台电脑或手机的名字，选择 **创建链接**（Create link）。

![客户端链接、复制按钮和二维码](/guide/zh/clients_link_qr.webp)

通知里显示链接、**复制**（Copy）按钮和这条链接的二维码。链接 30 分钟内有效，只能加入一台设备，中枢中途重启也照样有效。每个客户端能用哪些服务，在[客户端](../hub/clients.md)页上设置。

## 从电脑加入

1. 打开客户端：Linux 上在应用菜单里，Windows 上在开始菜单里，macOS 上打开 **Neutrino Client**。**中枢**（Hubs）页读 **尚未加入任何中枢**（No hub joined yet）。
1. 把链接粘进 **加入中枢**（Join a hub）那一行的输入框。
1. 选择 **加入**（Join）。

![加入中枢之后的客户端窗口](/guide/zh/client_connected.webp)

新出现的一行先读 **已加入，尚未连上中枢**（Joined; the hub has not been reached yet）。连上以后读 **已连接 · 局域网**（Connected · LAN），或别的连接路径的名字。一直停在 **已加入，尚未连上中枢**，说明链接里的中枢地址都连不上，检查这台电脑能不能访问中枢的 8443 端口。

在终端里运行 `nclient join '<client-link>'` 效果相同，`<client-link>` 是复制的客户端链接。

加入失败时，输入框下面或这一行上写出错误码：

| 错误码                | 原因                                 | 怎么办                                       |
| --------------------- | ------------------------------------ | -------------------------------------------- |
| `link_not_for_client` | 粘的是 **设备** 页发的被控端链接     | 在 **客户端** 页生成链接                     |
| `link_unreadable`     | 链接没粘全                           | 从面板复制整条链接                           |
| `ticket_spent`        | 链接用过或已过期                     | 在这一行上选 **离开**（Leave），用新链接加入 |
| `admission_paused`    | 中枢上失败的加入太多，暂停了新的加入 | 客户端过了码里给的秒数自己再试               |

## 从手机加入

1. 在应用的 **中枢** 页选择 **加入中枢**。
1. 选择 **允许使用相机**（Allow the camera），在 Android 的权限框里允许。
1. 把相机对准面板上的二维码。

![加入中枢页上的二维码扫描框](/guide/zh/app_join_scan.webp)

也可以把链接粘进 **或**（or）下面的输入框，再选择 **加入**。手机横屏或在平板上时，相机按钮是页面顶部的 **扫码**（Scan）。在外面用移动数据时，新的一行先读 **已加入，尚未连上中枢**，连上中枢后读 **已连接 ·** 加路径。

## 加入另一台中枢

在另一台中枢的面板里生成一条客户端链接，照同样的步骤加入。每台中枢各记各的设备名字，各发布各的服务。
