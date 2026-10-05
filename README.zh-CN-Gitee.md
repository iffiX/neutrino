# 微子中枢

微子中枢是放在你家里的一台远程访问中心。家里各台机器上的文件、网页、端口、远程桌面、终端和 AI 网关，都由它集中起来。你在手机或电脑上装好客户端，在任何地方都能用这些服务。

开源，MIT 许可证。

## 能做什么

- 在外面打开家里机器上的共享文件夹：电脑上挂成一个文件夹或盘符，手机上出现在系统的“文件”应用里。
- 打开家里机器上的网页服务，例如你自己装的 Gitea、VS Code、code-server。
- 把家里机器的一个端口转到本机，交给本机的程序使用。
- 打开家里机器的远程桌面和终端。
- 让本机的 Claude Code、Codex 和 Gemini CLI 用中枢上的 AI 网关。
- 从面板唤醒家里的机器：中枢在它自己的局域网里发唤醒包，机器要事先开启网络唤醒。

客户端只连中枢一个端口，由中枢再连到每台机器上的服务。

## 三个部分

| 部分   | 装在哪里                         | 国内版支持的系统                                                    |
| ------ | -------------------------------- | ------------------------------------------------------------------- |
| 中枢   | 家里一台常开的机器               | Debian 系 Linux（amd64、arm64）；Windows（x64）和 macOS（Apple 芯片）上以服务器形态运行 |
| 被控端 | 每台要用的家里机器               | Debian 系 Linux（amd64、arm64）、Windows（x64）、macOS（Apple 芯片） |
| 客户端 | 你随身的电脑或手机               | Debian 系 Linux（amd64、arm64）、Windows（x64）、macOS（Apple 芯片）、Android |

## 安装

在 Linux 或 macOS 上，用一条命令安装中枢：

```bash
curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh
```

在 Windows 上，以管理员身份打开 PowerShell，运行：

```powershell
irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1 | iex
```

脚本从本仓库的发行版页面下载安装包，核对校验和后安装。在 Linux 或 macOS 上，在 `sh` 后面加 `-s -- agent` 安装被控端，加 `-s -- client` 安装客户端。

也可以在发行版页面自己下载安装包。文件名里的 `<version>` 是页面上的版本号：

| 系统                | 中枢                                     | 被控端                                     | 客户端                                      |
| ------------------- | ---------------------------------------- | ------------------------------------------ | ------------------------------------------- |
| Linux amd64         | `neutrino-hub_<version>_amd64.deb`       | `neutrino-agent_<version>_amd64.deb`       | `neutrino-client_<version>_amd64.deb`       |
| Linux arm64         | `neutrino-hub_<version>_arm64.deb`       | `neutrino-agent_<version>_arm64.deb`       | `neutrino-client_<version>_arm64.deb`       |
| Windows x64         | `neutrino-hub-<version>-windows-amd64.msi` | `neutrino-agent-<version>-windows-amd64.msi` | `neutrino-client-<version>-windows-amd64.msi` |
| macOS（Apple 芯片） | `neutrino-hub-<version>-macos-arm64.pkg` | `neutrino-agent-<version>-macos-arm64.pkg` | `neutrino-client-<version>-macos-arm64.pkg` |
| Android             |                                          |                                            | `neutrino-client-<version>-android.apk`     |

## 装好之后

1. 用浏览器打开安装脚本最后打印的设置向导地址（Linux 上也可以运行 `sudo nhub setup`），按向导设好中枢，然后登录面板。
1. 在面板的 **设备** 页选 **用链接添加**，在要管理的机器上用这条链接运行 `nagent join '<enroll-link>'`：Linux 和 macOS 上加 `sudo`，Windows 上以管理员身份运行。
1. 在面板的 **客户端** 页选 **新建客户端链接**，电脑把链接粘进客户端窗口，手机扫页面上的二维码。

详细的步骤见[快速上手](docs/guide/zh-CN/quick-start.md)。

## 从外面连回来

在面板的 **外部访问** 页上选一种办法：

- EasyTier：家里的中枢和外面的设备加入同一个 EasyTier 网络，见[外部访问](docs/guide/zh-CN/hub/overlay.md)。
- 中继：用你自己的一台有公网地址的服务器，中枢经 SSH 把一个端口映射上去，见[中继](docs/guide/zh-CN/hub/relay.md)。

在外面管理中枢时，给你自己的客户端打开 **免密码进入中枢面板** 权限（默认关闭），再用客户端上的 **面板** 按钮打开面板。

## 文档

- 中文文档在 [docs/guide/zh-CN](docs/guide/zh-CN/overview.md)，从[概览](docs/guide/zh-CN/overview.md)读起。
- 客户端的用法：[桌面客户端](docs/guide/zh-CN/client/desktop.md)、[Android 应用](docs/guide/zh-CN/client/android.md)。

## 完整版和开发

这里发布的是国内版，包含完整版功能的一部分。完整版和全部开发都在 GitHub：<https://github.com/iffiX/neutrino>。

## 许可证

MIT；Android 应用带有 RustDesk 的核心，所以使用 AGPL-3.0。
