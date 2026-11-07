# 安装客户端

你要在手机或电脑上安装客户端，才能使用系统上的应用和文件。

手机上的客户端是一个 App，名称是 **微子**。电脑上的客户端是一个窗口程序，名称是 **Neutrino Client**。你要在每台需要使用的设备上分别安装。安装后，你还要把设备加入中枢，见[加入中枢](/access/join)。

## 支持的系统

| 设备         | 系统要求                                                                                      | 开始支持的微子·中枢版本 |
| ------------ | --------------------------------------------------------------------------------------------- | ----------------------- |
| Linux 电脑   | 带桌面的 Debian 12、Ubuntu 22.04、Fedora、RHEL 9、AlmaLinux 9，或更新的版本；Arch 系（amd64） | 0.2.0                   |
| Windows 电脑 | Windows 10 1809 或更新的版本，amd64                                                           | 0.2.0                   |
| Mac          | macOS 13 或更新的版本，Apple 芯片或 Intel                                                     | 0.2.0                   |
| Android      | Android 8.0 或更新的版本，64 位 ARM                                                           | 0.5.0                   |
| iPhone       | iOS 16 或更新的版本                                                                           | 0.6.0                   |

## 在 Android 手机上安装

用手机的相机或微信扫码，下载安装。

| 国内版                                       | 国际版                                           |
| -------------------------------------------- | ------------------------------------------------ |
| ![国内版下载页的二维码](/home/qr_app_cn.svg) | ![国际版下载页的二维码](/home/qr_app_global.svg) |

## 在 iPhone 上安装

App 不在 App Store，也不在 TestFlight。你要下载 `.ipa` 文件，用自己的 Apple ID 签名后安装。步骤见 [iOS 应用](/access/ios)。

## 在电脑上安装

1. 打开终端。在 Linux 上打开“终端”程序，在 macOS 上打开“应用程序”里“实用工具”下的“终端”，在 Windows 上从开始菜单搜索 PowerShell 并打开。下面的命令要用你平时的账户运行，不要用 root，前面也不要加 `sudo`。

1. 复制下面的命令，粘贴到终端里，再按回车。如果你在中国大陆，选择国内版，下载更快。

   ::: code-group

   ```bash [Linux、macOS]
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- client
   ```

   ```powershell [Windows]
   & ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) client
   ```

   ```bash [国内版 Linux、macOS]
   curl -fsSL https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.sh | sh -s -- client
   ```

   ```powershell [国内版 Windows]
   & ([scriptblock]::Create((irm https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.ps1))) client
   ```

   :::

1. 脚本请求管理员权限时，授权一次。在 Linux 和 macOS 上，终端会提示你输入这台电脑的登录密码，输入时屏幕上不显示字符，输入后按回车。在 Windows 上会弹出授权框，选择“是”。

1. 等待脚本运行结束。终端最后显示 `Installed`，下一行提示加入中枢，这时安装完成。

   ```text
   neutrino-client_0.6.0_amd64.deb matches its SHA256SUMS line
   Installing neutrino-client_0.6.0_amd64.deb
   ...
   Installed neutrino-client_0.6.0_amd64.deb
   Next, join this computer to a hub: nclient hub join '<client link from the hub's Clients page>'
   ```

1. 打开客户端。在系统的应用菜单或开始菜单里找到 **Neutrino Client**，也可以运行 `nclient gui`。窗口打开后显示 **中枢** 页，上面显示 **尚未加入任何中枢**，下面是粘贴链接的输入框。

   ![客户端窗口，尚未加入任何中枢，输入框标红](/guide/zh/access_install_client_02_empty.webp)

客户端在托盘里有一个图标。关闭窗口后客户端继续运行。如果要完全退出，在托盘菜单里按 **退出**。

## 不用脚本安装

如果你不想运行脚本，可以从发布页下载。文件名以 `neutrino-client` 开头，扩展名是 `.deb`、`.rpm`、`.pkg.tar.zst`、`.pkg` 或 `.msi`，按你的系统选择。

下载后，按你的系统安装。

- **Debian 系：** 运行 `sudo apt install ./<文件>`。
- **RHEL 系：** 运行 `sudo dnf install ./<文件>`。
- **Arch 系：** 运行 `sudo pacman -U <文件>`。
- **macOS 和 Windows：** 双击文件。

## 升级

客户端不会自动升级。中枢升级后，客户端这一行可能显示 **版本太旧 · 更新客户端**。这时重新运行上面的命令，或者下载新的安装包，直接安装在旧版本上。在 Android 上，下载新的 apk 并打开安装。在 iPhone 上，把新的 `.ipa` 签名后安装。已加入的中枢都会保留，你不用重新加入。

从 0.5 升级时步骤不同，见[从 0.5 升级](/hub/upgrade)。
