# 安装中枢

中枢是安装在电脑上的程序，面板是它的网页。

你要运行一条命令，再完成设置向导，这台电脑上就有了面板。以后安装应用、把手机加入中枢，都在面板上操作。

你要选择一台能一直开机的电脑，因为这台电脑关机后，手机和其他设备都无法使用上面的应用。你要确保这台电脑能访问互联网，并且你有它的管理员权限。安装过程不需要注册账号。

## 支持的系统

| 系统                                                  | 架构              | 开始支持的微子·中枢版本 |
| ----------------------------------------------------- | ----------------- | ----------------------- |
| Debian 12、Ubuntu 22.04、64 位树莓派 OS，或更新的版本 | amd64、arm64      | 0.1.0                   |
| Fedora、RHEL 9、AlmaLinux 9、Rocky 9，或更新的版本    | amd64、arm64      | 0.1.0                   |
| Arch、EndeavourOS、Manjaro                            | amd64             | 0.1.0                   |
| Windows 10 1809 或更新的版本                          | amd64             | 0.5.0                   |
| macOS 13 或更新的版本                                 | Apple 芯片、Intel | 0.5.0                   |

## 运行安装命令

1. 在这台电脑上打开终端。在 Linux 上打开“终端”程序，在 macOS 上打开“应用程序”里“实用工具”下的“终端”，在 Windows 上从开始菜单搜索并打开 PowerShell，不用选择“以管理员身份运行”。

1. 复制下面的命令，粘贴到终端里，再按回车。如果你在中国大陆，选择国内版，下载速度更快。国内版不具备代理和旁路网关。

   ::: code-group

   ```bash [Linux、macOS]
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
   ```

   ```powershell [Windows]
   irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
   ```

   ```bash [国内版 Linux、macOS]
   curl -fsSL https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.sh | sh
   ```

   ```powershell [国内版 Windows]
   irm https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.ps1 | iex
   ```

   :::

1. 脚本请求管理员权限时，授权一次。在 Linux 和 macOS 上，终端提示你输入登录这台电脑的密码，输入时屏幕上不显示字符，输完按回车。在 Windows 上，系统弹出授权框。选“是”后，脚本在新打开的窗口里继续运行，后面的操作都看这个新窗口。

   <div class="pic-holder">图：Windows 的授权框</div>

1. 等待脚本运行完成。脚本会自动选择这台电脑对应的安装包，下载后核对校验值，再安装。这一步不需要你操作。如果终端显示 `Waiting up to 300 seconds`，说明另一个程序正在使用系统的包管理器，脚本会等它结束。

1. 终端打印出一个以 `http://` 开头、带 `?token=` 的地址时，就安装好了。电脑有几个网口，终端就打印几个地址。

   ```text
   Installed neutrino-hub_0.6.0_amd64.deb
     The hub's service asks the same questions in a browser at:

       http://192.168.1.20:8080/?token=<向导令牌>

   NEUTRINO ─────────────────────────────────────
   ...
     Press Enter to begin:
   ```

最后一行是 `Press Enter to begin:`。这时不要按回车，因为按回车后会改成在终端里回答问题。让终端保持打开，然后到浏览器里操作。

## 完成设置向导

按 **开始配置这台机器** 之后，向导一共 6 屏。每屏按 **下一步** 前进，按 **返回** 回到上一屏。在最后一屏确认之前，向导不写入系统。

向导和面板在你的屏幕上默认是深色的，下面的图换成了浅色，便于查看，按钮和文字都相同。

1. 在浏览器里打开终端打印的地址。你要复制整行，包括 `?token=` 后面的部分。你可以在这台电脑上打开，也可以在同一个网络里的另一台电脑上打开。打开后，在第一屏按 **开始配置这台机器**。如果浏览器语言不是中文，这个按钮显示 **Set this box up**，下一屏可以更换语言。

   如果页面显示 **这台机器正等待配置**，说明地址缺少后面的令牌。回到终端，复制整行再打开一次。

   下一屏是 **语言**。点选择框，选择 **简体中文**，再按 **下一步**。

   ![向导的第一屏，开始配置的按钮标红](/guide/zh/hub_install_02_wizard_start.webp "按 开始配置这台机器")
   ![语言选择框展开，简体中文标红](/guide/zh/hub_install_03_language.webp "选择 简体中文，再按 下一步")

1. 在 **面板密码，以及保险库口令** 这一屏设置面板密码和保险库口令，再按 **下一步**。

   - **面板密码** 用来登录面板，至少 8 个字符。下面的 **再输一次** 填写相同的内容。
   - **保险库口令** 至少 16 个字符，要混用小写字母、大写字母、数字和符号，同样输入两次。你要记下来，因为恢复备份时要输入它。如果你忘了口令，就无法恢复备份里的密钥。
   - 让 **面板使用 HTTPS** 保持关闭，以后可以在[设置：备份、更新、密码](/hub/settings)页打开。

   下一屏是 **这台机器做什么？**。选择 **服务器**，再按 **下一步**。服务器模式不改变这台电脑的网络，笔记本和台式机都选择它。列表里的其他选项只在 Linux 上提供，这里用不到。这些选项的说明见[网络形态：服务器、路由器、旁路网关](/hub/network)。

   ![两个密码都填好，下一步按钮标红](/guide/zh/hub_install_05_passwords.webp "设置两个密码，按 下一步")
   ![选择用途这一屏，服务器标红](/guide/zh/hub_install_06_mode_server.webp "选择 服务器，按 下一步")

1. **用哪些网口？** 这一屏不用修改，直接按 **下一步**。这里列出了这台电脑的网口，**本机经此上网** 标出它访问互联网使用的网口。只有 **面板端口** 的 8080 或 **HTTPS 端口** 的 443 已有程序占用时，你才要更换数字，两个端口不能相同。

   下一屏是 **通过代理出网**。让 **在这里设置** 保持关闭，再按 **下一步**。以后需要时，可以在[代理](/hub/proxy)页设置。

   ![用哪些网口这一屏，下一步按钮标红](/guide/zh/hub_install_07_network.webp "不用修改，按 下一步")
   ![通过代理出网这一屏，下一步按钮标红](/guide/zh/hub_install_08_exit.webp "保持关闭，按 下一步")

1. 在 **就绪** 这一屏核对你的选择，再按一次 **开始配置这台机器**。按下后，中枢才开始写入。页面变成 **正在配置**，逐步列出正在执行的操作，绿点表示这一步已完成。你不用操作，等待配置完成。

   ![就绪这一屏列出全部选择，开始配置按钮标红](/guide/zh/hub_install_09_ready.webp "核对后按 开始配置这台机器")
   ![正在配置，逐步显示进度](/guide/zh/hub_install_10_configuring.webp "等待配置完成")

   如果页面显示 **有一步失败了，输出在终端里**，回到刚才的终端查看输出，再查看[故障排查](/reference/troubleshooting)。

1. 看到 **这个中枢已配置好**，中枢就安装好了。页面几秒后自动转到面板，你也可以直接按 **打开面板**。

   ![这个中枢已配置好，打开面板按钮标红](/guide/zh/hub_install_11_done.webp)

## 登录面板

1. 在 **面板密码** 里填写你刚才设置的密码，再按 **登录**。

   ![登录页，面板密码输入框标红](/guide/zh/hub_install_12_login.webp "填写面板密码")
   ![密码已填好，登录按钮标红](/guide/zh/hub_install_13_login_press.webp "按 登录")

1. 进入 **总览** 页，就登录成功了。左侧栏下半部分的 **被控端** 一栏里有这台电脑的名字，前面的绿点表示它在线。向导已经把这台电脑加入中枢，你不用另外安装。

   ![登录后的总览页](/guide/zh/hub_install_14_dashboard.webp)

以后要打开面板，在浏览器里输入终端打印的地址，去掉 `?token=` 和后面的部分，比如 `http://192.168.1.20:8080`。

如果你忘了地址，在这台电脑上运行 `sudo nhub open --print`。如果登录页显示 **多次失败后已锁定。**，运行 `sudo nhub unlock`。在 Windows 上，这两条命令都在管理员 PowerShell 里运行，并去掉 `sudo`。

## 手动安装

如果你不想运行脚本，可以自行下载安装包。

1. 打开发布页，可以选择[国际版](https://github.com/iffiX/neutrino/releases/latest)或[国内版](https://cnb.cool/iffi-X/neutrino/-/releases)，下载这台电脑对应的 `.deb`、`.rpm`、`.pkg.tar.zst`、`.pkg` 或 `.msi`。文件名以 `neutrino-hub` 开头。
1. 安装这个文件。在 Debian 系上运行 `sudo apt install ./<文件>`，在 RHEL 系上运行 `sudo dnf install ./<文件>`，在 Arch 系上运行 `sudo pacman -U <文件>`，在 macOS 和 Windows 上双击文件。
1. 在 Linux 上运行 `sudo nhub setup`，在 macOS 和 Windows 上打开 **Neutrino Hub**。然后按上面的步骤完成设置向导。

不要用 `dpkg -i` 和 `rpm -i`，因为它们不安装依赖。在 RHEL 系上，你要先启用 EPEL 软件源。安装脚本会自动启用；如果你手动安装，要自己启用。
