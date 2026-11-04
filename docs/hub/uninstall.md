# 卸载

你可以卸载一个应用，也可以卸载整套微子·中枢：

- **卸载一个应用：** 在面板上操作。
- **卸载整套微子·中枢：** 依次卸载客户端、被控端和中枢。

## 卸载一个应用

打开这个系统的页面，在 **模块配置** 选中这个应用的标签，再按 **卸载**。弹窗说明数据保留还是删除，读完再按 **卸载**。

![卸载按钮标红](/guide/zh/deploy_on_a_machine_39_uninstall.webp "按 卸载")
![卸载的弹窗，卸载按钮标红](/guide/zh/deploy_on_a_machine_40_uninstall_dialog.webp "读完再按 卸载")

大多数应用的数据都会保留。Ayakaleaf 和 Hermes WebUI 不同，弹窗里的红字说明数据会删除，无法恢复。你要先把需要保留的数据复制出来。

![Ayakaleaf 卸载弹窗的红字](/guide/zh/deploy_ayakaleaf_51_uninstall_dialog.webp)

## 卸载整套微子·中枢

你要按客户端、被控端、中枢的顺序操作。

### 第一步：客户端

在每台设备上打开客户端的 **中枢** 页，按 **离开**。按钮会变成 **再按一次离开**，再按一次才生效。然后卸载程序，方法见下一节。在 Android 和 iOS 上，直接删除 App。

![中枢页，离开按钮标红](/guide/zh/hub_uninstall_01_leave.webp "按 离开")
![按钮变成再按一次离开](/guide/zh/hub_uninstall_01b_leave_armed.webp "再按一次")

如果客户端无法连接中枢，到面板的 **客户端** 页，按那一行的 **删除**。如果你要用命令行离开，运行 `nclient hub leave <中枢>`。

### 第二步：被控端

在面板的 **被控端** 页，按每个系统那一行的 **忘记**，再在弹窗里按 **忘记**。然后到那台电脑上卸载程序。如果你要用命令行离开，运行 `sudo nagent leave`。

![这一行的忘记按钮标红](/guide/zh/hub_uninstall_02_forget.webp)

### 第三步：中枢

如果你要保留备份，先到 **设置** 页按 **下载备份**，记好保险库口令。然后卸载程序。这台电脑上的被控端要另外卸载。

![配置存档一节，下载备份按钮标红](/guide/zh/hub_uninstall_03_backup.webp)

你的文件、Gitea 仓库和容器的数据都保留在电脑上。

## 卸载程序

安装包的名字是 `neutrino-hub`、`neutrino-agent` 和 `neutrino-client`。

| 系统      | 卸载方法                                                                                 |
| --------- | ---------------------------------------------------------------------------------------- |
| Debian 系 | `sudo apt remove <包名>`，保留配置和状态                                                 |
| RHEL 系   | `sudo dnf remove <包名>`，保留配置和状态                                                 |
| Arch 系   | `sudo pacman -R <包名>`，保留配置和状态                                                  |
| Windows   | 在系统设置的 **应用** 里卸载 **Neutrino Hub**、**Neutrino Agent** 或 **Neutrino Client** |
| macOS     | 没有卸载程序，运行下面对应的命令                                                         |

在 Debian 系上运行 `sudo apt purge <包名>` 时，配置和状态也会一起删除。中枢的保险库也会删除，只有备份能恢复它。

在 Windows 上卸载客户端时，勾选 **Keep my configuration**，就能保留加入过的中枢。

<div class="pic-holder">图：Windows 系统设置里的卸载</div>

## 在 macOS 上卸载

卸载中枢时，先运行 `sudo nhub reset all`，再运行下面的命令。

```bash
sudo launchctl bootout system/com.neutrino.hub
sudo rm -rf "/Library/Application Support/Neutrino/hub/app" "/Applications/Neutrino Hub.app"
sudo rm -f /Library/LaunchDaemons/com.neutrino.hub.plist /usr/local/bin/nhub
```

卸载被控端时，运行下面的命令。

```bash
sudo nagent service uninstall
sudo rm -rf "/Library/Application Support/Neutrino/agent" /Library/Logs/Neutrino/agent
```

卸载客户端时，运行下面的命令。

```bash
sudo launchctl bootout system/com.neutrino.client.easytier
sudo launchctl bootout system/com.neutrino.client.netbird
sudo rm -f /Library/LaunchDaemons/com.neutrino.client.*.plist /usr/local/bin/nclient
sudo rm -rf "/Applications/Neutrino Client.app"
```

## 每个部分卸载的内容

卸载中枢时，安装包的卸载脚本先把网络交还给系统，再删除程序。

卸载被控端时，应用添加的服务和计划任务都会删除，AI 工具恢复原来的设置，桌面共享关闭。共享和账户（系统的 SMB 服务继续提供）、仓库、账户里的数据、容器的数据都会保留。

你账户里的 Claude Code、它的会话和你的文件都不受影响。

在开启了 SELinux 的系统上，文件共享打开过系统开关 `samba_export_all_rw`。运行 `sudo nagent service uninstall` 之后，这个开关仍然打开。如果你要关闭它，运行下面的命令。

```bash
sudo setsebool -P samba_export_all_rw off
```

## 恢复到刚安装时的状态

如果你不卸载程序，只要恢复到刚安装时的状态，可以运行下面的命令。每条命令都先显示 `[y/N]`，加上 `--yes` 就不显示。在 Windows 上要用管理员 PowerShell，并去掉 `sudo`。

- `sudo nhub reset network` 把网络交还给这台电脑，并停止面板，配置不变。
- `sudo nhub reset all` 把配置恢复为示例，删除保险库密钥、中枢密钥和面板的证书，并停止服务。之后运行 `sudo nhub setup` 重新设置，设备都要用新链接重新加入。

## 卸载后保留的内容

如果你不再需要这些内容，手动删除它们。下面的 `<包名>` 是 `hub`、`agent` 或 `client`。

| 内容                            | Linux                           | macOS                                                 | Windows                                 |
| ------------------------------- | ------------------------------- | ----------------------------------------------------- | --------------------------------------- |
| 配置                            | `/etc/neutrino/<包名>`          | `/Library/Application Support/Neutrino/<包名>/config` | `C:\ProgramData\Neutrino\<包名>\config` |
| 状态                            | `/var/lib/neutrino/<包名>`      | `/Library/Application Support/Neutrino/<包名>/state`  | `C:\ProgramData\Neutrino\<包名>\state`  |
| 日志                            | `/var/log/neutrino/<包名>`      | `/Library/Logs/Neutrino/<包名>`                       | `C:\ProgramData\Neutrino\<包名>\log`    |
| 每个账户的客户端配置            | `~/.config/neutrino/client`     | `~/Library/Application Support/Neutrino/client`       | `%APPDATA%\Neutrino\client`             |
| CloudCLI、Codeg、思源笔记的数据 | `~/.local/share/neutrino/agent` | `~/Library/Application Support/Neutrino/agent`        | `%LOCALAPPDATA%\Neutrino\agent`         |
