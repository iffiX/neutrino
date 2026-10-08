---
title: 卸载
---

# 卸载

卸载按包分开：中枢、被控端、客户端各占一节，最后一节列出卸完还留在机器上的东西。

## 中枢

只想让中枢回到刚装好的状态，不必卸载。在中枢所在的电脑上运行下面的命令，Windows 上在管理员 PowerShell 里去掉 `sudo` 运行。

| 命令                      | 效果                                                                                   |
| ------------------------- | -------------------------------------------------------------------------------------- |
| `sudo nhub reset network` | 交还这台电脑的网络（防火墙、引擎、解析器），停下面板，配置不变                         |
| `sudo nhub reset all`     | 交还网络，把配置换回示例，删掉保险库密钥、被控端连接用的证书和面板的颁发机构，停下服务 |

每条命令先问 `[y/N]`，加 `--yes` 不问。`nhub reset all` 之后，再运行 `sudo nhub setup` 就能重新配置；在那之前，只能经 SSH 登录这台电脑。

要把中枢整个卸掉，按系统做。

- Debian 系：运行 `sudo apt remove neutrino-hub` 或 `sudo apt purge neutrino-hub`，两者的差别见下表。
- RHEL 系：运行 `sudo dnf remove neutrino-hub`。Arch 上运行 `sudo pacman -R neutrino-hub`。这两种卸法删掉程序，留下 `/etc/neutrino/hub` 和 `/var/lib/neutrino/hub`，不要了就手动删掉。
- Windows：先运行 `nhub reset all`，再在系统的 **应用** 设置里卸载 **Neutrino Hub**。<!-- 待核: msi 卸载时会不会删掉 C:\ProgramData\Neutrino\hub 和系统防火墙里 neutrino_hub_ 开头的规则；标准里没写。 -->
- macOS：先运行 `sudo nhub reset all`。macOS 的安装包没有卸载程序，它放下的是 `/Library/Application Support/Neutrino/hub`、`/Library/LaunchDaemons/com.neutrino.hub.plist`、`/usr/local/bin/nhub` 和 `/Applications/Neutrino Hub.app`。<!-- 待核: 中枢在 macOS 上的卸载做法标准里没写；上面只列出安装包放下的东西，删除步骤待定。 -->

Linux 上卸包时，卸载脚本先运行 `nhub reset network`，把网络交还给这台电脑。

| 卸法         | `/opt/neutrino/hub` 程序 | `/etc/neutrino/hub` 配置 | `/var/lib`、`/var/log` 下的状态和日志 |
| ------------ | ------------------------ | ------------------------ | ------------------------------------- |
| `apt remove` | 删掉                     | 留下                     | 留下                                  |
| `apt purge`  | 删掉                     | 删掉                     | 删掉                                  |

`apt purge` 连保险库一起删掉。先在 **设置** 页下载一份备份，才有办法回来。

中枢所在的电脑上还装着被控端，按下一节卸。

## 被控端

先让这台机器离开中枢。在面板 **设备** 页打开这台机器，选 **忘记设备**；或者在这台机器上运行 `sudo nagent leave`。然后按系统卸载。

- Debian 系：运行 `sudo apt remove neutrino-agent`。卸载脚本自己运行 `nagent leave` 和 `nagent service uninstall`。`apt purge` 还删掉 `/etc/neutrino/agent` 和 `/var/lib/neutrino/agent`。
- RHEL 系：运行 `sudo dnf remove neutrino-agent`。它运行 `nagent service uninstall`，留下 `/etc/neutrino/agent`。
- Windows：在系统的 **应用** 设置里卸载 **Neutrino Agent**。卸载程序运行 `nagent service uninstall --yes`，删掉模块加的计划任务和防火墙规则。
- macOS：安装包没有卸载程序。运行下面的命令。

```bash
sudo nagent service uninstall
sudo rm -rf "/Library/Application Support/Neutrino/agent" /Library/Logs/Neutrino/agent
```

第一条删掉被控端的程序、它的 launchd 任务和它带的 RustDesk，留下配置、状态和日志；第二条删掉这三样。

`nagent service uninstall` 删掉模块为了运行加上的服务、计划任务和防火墙规则。文件共享的共享和账户、存储池、仓库、容器卷都留下，系统的 SMB 服务照常提供这些共享。

## 客户端

先离开每个中枢。在桌面客户端或 Android 应用的 **中枢** 页，每个中枢一行选 **离开** 并确认；在终端里运行 `nclient leave` 也一样。中枢连得上时，面板 **客户端** 页上这一项随之删掉；连不上时，到那一页手动 **删除**。

然后按系统卸载。

- Debian 系：运行 `sudo apt remove neutrino-client`，每个账户自己的配置留下；`sudo apt purge neutrino-client` 把它们也删掉。
- RHEL 系：运行 `sudo dnf remove neutrino-client`，每个账户自己的配置留下。
- Windows：在系统的 **应用** 设置里卸载 **Neutrino Client**。卸载程序问 **Keep my configuration**，勾上时留下加入的中枢，下次装好直接连回去；没人回答时也留下。
- macOS：安装包放下的是 `/Applications/Neutrino Client.app` 和 `/usr/local/bin/nclient`，另有虚拟网用的 LaunchDaemon。<!-- 待核: 客户端在 macOS 上的卸载做法和它的 LaunchDaemon 名字标准里没写。 -->
- Android：在系统设置里卸载这个应用。

## 留在机器上的东西

下表里的 `<package>` 是 `hub`、`agent` 或 `client`。卸包后还在的目录，不要了就手动删掉。

| 是什么                          | Linux                           | macOS                                                    | Windows                                    |
| ------------------------------- | ------------------------------- | -------------------------------------------------------- | ------------------------------------------ |
| 配置                            | `/etc/neutrino/<package>`       | `/Library/Application Support/Neutrino/<package>/config` | `C:\ProgramData\Neutrino\<package>\config` |
| 状态                            | `/var/lib/neutrino/<package>`   | `/Library/Application Support/Neutrino/<package>/state`  | `C:\ProgramData\Neutrino\<package>\state`  |
| 日志                            | `/var/log/neutrino/<package>`   | `/Library/Logs/Neutrino/<package>`                       | `C:\ProgramData\Neutrino\<package>\log`    |
| 每个账户的客户端配置            | `~/.config/neutrino/client`     | `~/Library/Application Support/Neutrino/client`          | `%APPDATA%\Neutrino\client`                |
| 被控端在每个账户里装的 CloudCLI | `~/.local/share/neutrino/agent` | `~/Library/Application Support/Neutrino/agent`           | `%LOCALAPPDATA%\Neutrino\agent`            |
