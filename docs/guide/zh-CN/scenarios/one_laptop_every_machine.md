---
title: 一台笔记本管所有机器
---

# 一台笔记本管所有机器

家里除了中枢那台电脑，还有 Linux 机器 `server` 和 Windows 电脑 `desktop`。下面给它们装上被控端，再从 Mac 笔记本 `laptop` 的客户端里用它们：开终端，看桌面，打开 VS Code。

## 开始之前

- 做完了[第零步](../quick-start.md)。
- 中枢所在的机器已经是被控端，下文叫它 `hub`。
- 你在 `server` 上有 root 权限，在 `desktop` 上有管理员权限。
- 四台机器连在同一个局域网里。

## 加入 `server`

命令里的 `<enroll-link>` 是面板生成的加入链接，连同尖括号换成复制的链接，单引号保留。

1. 在面板的 **设备** 页，选择 **用链接添加**。
1. 选择 **复制**。链接 30 分钟内有效。
1. 在 `server` 上安装被控端：

   ```bash
   curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh -s -- agent
   ```

1. 用复制的链接加入中枢：

   ```bash
   sudo nagent join '<enroll-link>'
   ```

1. 在面板 **设备** 页的 **已管理的设备** 里找到 `server`。

![设备页上的加入链接和复制按钮](/guide/zh/devices_enroll_link.webp)

中枢是完整版时，安装命令见[安装被控端](../install/agent.md)。

## 加入 `desktop`

1. 在 **设备** 页再选一次 **用链接添加**。
1. 选择 **复制**。
1. 在 `desktop` 上，以管理员身份打开 PowerShell。
1. 安装被控端：

   ```powershell
   & ([scriptblock]::Create((irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1))) agent
   ```

1. 在同一个窗口里加入中枢：

   ```powershell
   nagent join '<enroll-link>'
   ```

1. 在 **已管理的设备** 里找到 `desktop`。

## 让 `laptop` 当客户端加入

第零步里加入的笔记本就是 `laptop` 时，跳过这一节。否则照[第零步](../quick-start.md#让手机和笔记本加入)里笔记本的做法加入，链接名称填 `laptop`。窗口里中枢那一行显示 **已连接 · 局域网**。

![客户端窗口，中枢一行经局域网连上](/guide/zh/client_connected.webp)

## 在每台机器上开 shell

1. 在客户端窗口里打开 **终端** 页。
1. 在机器列表里选 `hub`。
1. 选择 **新终端**。
1. 选 `server`，再选择 **新终端**。
1. 选 `desktop`，再选择 **新终端**。

三个终端各占一个标签。`hub` 和 `server` 上是 root 的登录 shell，`desktop` 上是以 SYSTEM 身份运行的 PowerShell。

![终端页上三台机器各开着一个终端](/guide/zh/client_terminals_three.webp)

## 共享 `desktop` 的屏幕

1. 打开面板的 **模块** 页，在机器条里选 `desktop`。
1. 打开 **远程桌面** 标签。
1. 打开 **共享这台机器的桌面**。
1. 选择 **应用远程桌面**。
1. 在 `desktop` 的屏幕前登录 Windows。
1. 在客户端的 **远程桌面** 页，`desktop` 那一行选择 **连接**。

查看器在新窗口里打开，显示 `desktop` 的桌面，这一行显示 **查看器已打开**。连接失败时，见[故障排查](../reference/troubleshooting.md#远程桌面打不开)。

![远程桌面页上 desktop 一行的查看器已打开](/guide/zh/client_remote_desktops.webp)

## 在中枢机器上打开 VS Code

VS Code 实例以 `hub` 上一个账户的身份运行，下面用你自己的账户。先装上 VS Code：

1. 回到 **模块** 页，改选 `hub`。
1. 没有 **VS Code** 标签时，用 **+** 加上它。
1. 打开 **VS Code** 标签。
1. 选择 **打开并接受条款**。
1. 选择 **安装**。

再加一个实例：

1. 选择 **配置**。
1. 选择 **添加实例**。
1. 在 **账户** 里填你的系统账户名。
1. 选择 **应用 VS Code**。

实例那一行显示 **运行中**。

![VS Code 标签上一个实例正在运行](/guide/zh/vscode_panel.webp)

客户端的 **网页** 页多出 VS Code 加你账户名的一行。选择这一行的 **打开**，系统浏览器打开 VS Code。

![网页页上的 VS Code 一行](/guide/zh/client_web_vscode.webp)
