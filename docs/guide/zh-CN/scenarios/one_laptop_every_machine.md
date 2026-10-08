---
title: 一台笔记本，管家里所有机器
---

# 一台笔记本，管家里所有机器

做完这一页，你的 Mac 笔记本 `laptop` 上的客户端里会开着三个终端，分别在中枢所在的机器 `hub`、Linux 机器 `server` 和 Windows 电脑 `desktop` 上。客户端还打开了 `desktop` 的远程桌面，浏览器里开着 `hub` 上的 VS Code。四台机器在同一个局域网里，全程用不到外部访问。

## 开始之前

- 中枢已经装好，你登录了面板。装中枢的步骤见[安装中枢](../install/hub.md)。
- 中枢装好时，`nhub setup` 已经把它所在的机器加成被控端，设备列表里这一行叫 `hub`。
- 你在 `server` 上有 root 权限，在 `desktop` 上有管理员权限。
- `hub`、`server`、`desktop` 和 `laptop` 连在同一个局域网里。

从家外面用这些机器另有一套准备，见[选哪种外部访问](./choose_a_way_in.md)。

## 加入 `server`

下面的 `<enroll-link>` 代表面板生成的加入链接。运行时连同尖括号换成复制的链接，单引号保留。

1. 在面板的 **设备**（Devices）页，选择 **用链接添加**（Add by link）。
1. 选择 **复制**（Copy）。
1. 在 `server` 上安装被控端：

   ```bash
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
   ```

1. 在 `server` 上用复制的链接加入中枢：

   ```bash
   sudo nagent join '<enroll-link>'
   ```

1. 回到面板的 **设备** 页，在 **已管理的设备**（Managed devices）里找到 `server`。

![设备页上显示的加入链接和它的复制按钮](/guide/zh/devices_enroll_link.webp)

链接只在一段时间内有效，面板上写着还剩几分钟。过期之后，再选一次 **用链接添加**。

## 加入 `desktop`

1. 回到面板的 **设备** 页，再选一次 **用链接添加**。
1. 选择 **复制**。
1. 在 `desktop` 上，以管理员身份打开 PowerShell。
1. 在这个窗口里安装被控端：

   ```powershell
   & ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) agent
   ```

1. 在同一个窗口里加入中枢：

   ```powershell
   nagent join '<enroll-link>'
   ```

1. 在面板的 **已管理的设备** 里找到 `desktop`。

## 让 `laptop` 当客户端加入

1. 在 `laptop` 的终端里安装客户端：

   ```bash
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- client
   ```

1. 打开面板的 **客户端**（Clients）页。
1. 选择 **新建客户端链接**（New client link）。
1. 在名称输入框里填 `laptop`。
1. 选择 **创建链接**（Create link）。
1. 选择 **复制**。
1. 在 `laptop` 的应用程序文件夹里打开 **Neutrino Client**。
1. 把链接粘贴到窗口里的链接输入框。
1. 选择 **加入**（Join）。

窗口里多出中枢那一行，连上之后显示 **已连接 · 局域网**（Connected · LAN）。

![客户端窗口里，中枢那一行显示已经经局域网连上](/guide/zh/client_connected.webp)

## 在每台机器上开 shell

1. 在客户端窗口里打开 **终端**（Terminals）页。
1. 在机器列表里选 `hub`。
1. 选择 **新终端**（New terminal）。
1. 选 `server`，再选择 **新终端**。
1. 选 `desktop`，再选择 **新终端**。

三个终端各占一个标签，切换标签不丢输出。`hub` 和 `server` 上开的是 root 的登录 shell。`desktop` 上开的是 PowerShell，以 SYSTEM 身份运行。

![客户端的终端页，hub、server、desktop 各开着一个终端](/guide/zh/client_terminals_three.webp)

## 共享 `desktop` 的屏幕

1. 打开面板的 **模块**（Modules）页，在机器条里选 `desktop`。
1. 打开 **Remote desktop** 标签。
1. 打开 **共享这台机器的桌面**（Share this machine's desktop）。
1. 选择 **应用远程桌面**（Apply remote desktop）。
1. 在 `desktop` 的屏幕前登录 Windows。
1. 在客户端的 **远程桌面**（Remote desktops）页，`desktop` 那一行选择 **连接**（Connect）。

查看器在新窗口里打开，显示 `desktop` 上登录的那个人的桌面。客户端里这一行显示 **查看器已打开**（Viewer open）。屏幕前没人登录时，连接返回 `rdp_nobody_seated`；在 `desktop` 前登录 Windows，再选一次 **连接**。

![客户端的远程桌面页，desktop 那一行显示查看器已打开](/guide/zh/client_remote_desktops.webp)

## 在中枢机器上打开 VS Code

VS Code 实例以一个账户的身份运行，这个账户要在 `hub` 上存在。下面用你自己在 `hub` 上的账户。先装上 VS Code：

1. 回到 **模块** 页，改选 `hub`。
1. 如果没有 **VS Code** 标签，选择 **+**，勾上 VS Code。
1. 打开 **VS Code** 标签。
1. 选择 **打开并接受条款**（Open and accept the terms）。
1. 选择 **安装**（Install）。

再加一个实例：

1. 选择 **配置**（Configure）。
1. 选择 **添加实例**（Add instance）。
1. 在 **账户**（Account）里填你在 `hub` 上的系统账户名。
1. 选择 **应用 VS Code**（Apply VS Code）。

实例开始运行后，它那一行显示 **运行中**（running）。

![VS Code 标签上，hub 的一个实例正在运行](/guide/zh/vscode_panel.webp)

这时客户端的 **网页**（Web）页多出一行，标题是 VS Code 加你的账户名。选择这一行的 **打开**（Open）。系统浏览器打开 VS Code，地址是 `laptop` 本机回环地址上的一个端口。

![客户端的网页页，VS Code 那一行已转发到本机端口](/guide/zh/client_web_vscode.webp)
