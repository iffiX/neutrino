---
title: 客户端
---

# 客户端

客户端是一个常驻程序、一个托盘图标和一个窗口，跑在你自己的登录会话里。它消费中枢发布的东西：打开网页、转发端口、切 AI 工具、挂共享、连远程桌面。

客户端绝不以 root 运行，用 sudo 跑它会被当场拒绝。macOS 上它会按名字拒绝启动。Windows 上只有客户端，没有中枢，也没有被控端。客户端不发布任何东西，也不接收模块，想从中枢管住那台机器的同学，那要的是被控端，见[《设备与远程桌面》](./devices-remote-desktop.md)。客户端链接和设备链接不是一回事，各自在各自的页面上生成，拿错了对方会拒绝。Debian 上 `remove` 保留你的配置，只有 `purge` 才会把它拿走。EasyTier 不会出现在 Windows 客户端里，它的 Windows 构建静态引用了不允许再分发的 `packet.dll`。

## Windows 上装 msi

**下载 `neutrino-client-0.2.0-windows-amd64.msi` 并运行它。**

预期：安装程序走完，开始菜单里多一个条目。msi 分 x64 和 arm64 两种，里面带着钉死版本的嵌入式 Python。

![Windows 上的 msi 安装程序](/guide/os/win_msi_installer.webp)

::: warning
Windows 上的窗口要用 WebView2。没有它时客户端会拒绝，说这个窗口需要某个运行时，装上再试一次。

微软的 Evergreen 运行时装上之后，重新启动客户端就有窗口了。

:::

## 托盘与窗口

**从开始菜单打开客户端，或者运行 `nclient gui`。**

预期：窗口打开，标题是「微子·客户端」，里面是「状态」和「服务」两栏。还没加入 hub 时，服务那一栏写「加入 hub 后这里会出现服务。」

![Windows 上的托盘菜单](/guide/os/win_tray_flyout.webp)

- 关掉窗口只是把它藏起来，客户端还在跑，点托盘图标能叫回来。
- 托盘菜单里是「打开」和「退出」，真正停掉它的是「退出」。
- `nclient gui --hidden` 直接起在托盘里，不开窗口。

## Linux 上装 deb

**1. 装包。**

```bash
sudo apt install ./neutrino-client_0.2.0_amd64.deb
```

预期：安装脚本打印一行提示，让你打开它并加入一个 hub，后面跟着 `nclient gui`。

**2. 打开窗口。**

```bash
nclient gui
```

预期：窗口打开。前面不要加 `sudo`，客户端以个人身份运行，绝不以 root 运行。

::: warning
Linux 上的窗口要用 WebKitGTK。没有它时客户端会直接说出来，并把要装的包名列出来。

按它给的那条 `sudo apt install` 装上，再跑一次 `nclient gui`。

:::

## 粘贴链接

**1. 在面板的「客户端」页点「新建客户端链接」，名字填 `laptop`，点「创建链接」。**

预期：提示是把这条链接粘到 `laptop` 的客户端程序里，五分钟内有效，旁边有「复制」。

![新建客户端链接](/guide/zh/clients_create_link.webp)

![客户端链接的提示条](/guide/zh/clients_link_notice.webp)

**2. 在客户端窗口的输入框里粘上链接，点「连接」。**

预期：状态从「未连接」变成「已连接」，后面跟着 hub 的版本号，旁边是「断开」，下面画出五个服务面板。

![未连接状态的客户端窗口](/guide/zh/client_disconnected.webp)

![已连接状态的客户端窗口](/guide/zh/client_connected.webp)

![Windows 上已连接的客户端窗口](/guide/zh/win_client_connected.webp)

终端里是同一件事，已经绑过一次的加 `--yes` 顶掉旧绑定：

```bash
nclient connect 'neutrino://enroll/PLACEHOLDER_LINK'
```

把设备链接粘进客户端会被拒绝，说此链接是给设备 agent 的，不是给客户端的。客户端链接在客户端页生成，设备链接在设备页生成。

在面板的客户端页上，一台客户端一行，列是名称、主机名、平台、状态、版本和最后出现时间，每一行可以启用、停用或者删除。删除的提示是「它的网关密钥会被吊销，它的程序会失去这个 hub，需要一条新链接才能回来。」被停用的客户端窗口里写「已被 hub 关闭」，按钮全灰。

## 挂到盘符或者文件夹

**1. 在文件面板上点「配置」。**

预期：Linux 上是共享用户名、共享密码和挂载路径，路径已经填好 `<home>/nas/<共享名>`；Windows 上是一个「盘符」框，已经挑好一个空闲盘符，下面写「在文件资源管理器中显示为该盘符」。

![客户端的文件配置](/guide/zh/client_files_config.webp)

**2. 点「挂载」。**

预期：按钮依次走过「等待客户端…」「正在挂载…」，然后变成「卸载」。

![挂载完成的文件面板](/guide/zh/client_files_mounted.webp)

![Windows 上挂成盘符](/guide/zh/win_files_drive_letter.webp)

![文件资源管理器里的网络驱动器](/guide/os/win_explorer_mapped.webp)

| 拒绝               | 界面上的话                                 |
| ------------------ | ------------------------------------------ |
| Linux 路径不合规   | 请给一个家目录下的文件夹，例如 ~/nas/share |
| Windows 盘符不合规 | 请给一个没被占用的盘符，例如 N:            |
| 文件夹非空         | 那个文件夹不是空的                         |
| polkit 没放行      | 这台机器上没有授权挂载                     |
| 缺挂载工具         | 这台机器上缺少挂载工具                     |

终端里是同一件事：

```bash
nclient service file config 1 --path ~/nas/media --username alex
```

端口面板转发到本机的 `127.0.0.1:{port}`，转着的时候那一行上直接写出这个地址。

## 设置与语言

**点窗口顶上的「设置」。**

预期：弹出「客户端设置」，里面是语言选择、「保存」和「取消」。两个选项各用自己的语言写：English 和简体中文。

![客户端设置里的语言](/guide/zh/client_settings_language.webp)

语言是客户端自己的，不跟着面板走，同一台机器上两个人可以各用各的。

## 断开与卸载

**1. 在状态一栏点「断开」，或者在终端里跑。**

```bash
nclient disconnect
```

预期：窗口回到「未连接」，服务那一栏写「加入 hub 后这里会出现服务。」`nclient status` 能看到这个人当前绑在哪个 hub 上，`nclient quit` 停掉常驻进程，没在跑时它会说客户端没有运行。

**2. Debian 上卸载。**

```bash
sudo apt remove neutrino-client
```

预期：常驻进程停掉，安装目录删掉，机器上每个人自己留下的配置还在。卸载脚本是按整条命令行匹配常驻进程的，所以正在执行安装的那个 shell 不会被误杀。

**3. 连配置一起清掉。**

```bash
sudo apt purge neutrino-client
```

预期：个人配置也一并删除，下次装回来是全新的。

::: tip
`remove` 保留你的配置，只有 `purge` 才会把它拿走。
:::

客户端比中枢新时，它会停在错误状态上，说此客户端比 hub 新，请先升级 hub。被解绑时它会说明原因：客户端比 hub 新、hub 不再认识这个客户端，或者 hub 的身份变了（被重置或者重装过），然后让你粘一条新链接重新加入。
