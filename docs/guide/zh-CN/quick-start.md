---
title: 快速上手
---

# 快速上手

大约半小时后，你手上会有一套能用的环境：一台 Linux 机器以服务器形态运行 hub，第二台 Linux 机器归 hub 管理，那台机器上的一个目录经桌面客户端挂到你的笔记本上。

## 你需要什么

- 一台装 hub 的 Linux 机器，本页叫它 `home-hub`。它是 x86-64，系统是 Debian 12 及以上或 Ubuntu 22.04 及以上，能访问互联网，你有它的 root 权限。
- 第二台同类的 Linux 机器装被控端，本页叫它 `studio`。
- 一台带桌面环境的 Linux 电脑装客户端，本页叫它 `laptop`。
- 0.5.0 版的三个安装包，从 [Releases](https://github.com/iffiX/neutrino/releases) 下载：`neutrino-hub_0.5.0_amd64.deb`、`neutrino-agent_0.5.0_amd64.deb` 和 `neutrino-client_0.5.0_amd64.deb`。

三台机器在同一个局域网里。服务器形态保留 `home-hub` 的所有地址，你网络里的其他部分保持原样。

## 安装 hub

1. 在 `home-hub` 上安装包：

   ```bash
   sudo apt install ./neutrino-hub_0.5.0_amd64.deb
   ```

1. 启动初始化向导：

   ```bash
   sudo nhub setup
   ```

   终端为这台机器的每个网口打印一个地址，地址末尾带一次性令牌。

1. 在 `laptop` 的浏览器里打开其中一个地址，连同令牌一起。

## 回答初始化向导

每个问题屏底部都有**下一步**（Next），选它进入下一屏。你在最后一屏确认之后，向导才写入这台机器。

1. 选择 **Set this box up**。这一屏还是英文。
1. 在**语言**（Language）屏，选择**简体中文**。
1. 在**面板密码，以及保险库口令**（A password for the panel, a passphrase for the vault）屏，在**面板密码**（Panel password）里填至少 8 个字符，在**再输一次**（Again）里再填一遍。
1. 在同一屏的**保险库主口令**（Vault master passphrase）里，填至少 16 个字符，包含小写、大写、数字和符号，在它的**再输一次**里再填一遍。
1. **面板使用 HTTPS**（HTTPS for the panel）保持关闭。
1. 在**这台机器做什么？**（What is this machine for?）屏，选择**服务器**（Server）。
1. 在**用哪些网口？**（Which ports?）屏，**面板监听端口**（Panel answers on port）保持 `8080`。
1. 在**通过代理出网**（Going out through a proxy）屏，**在这里设置**（Set it up here）保持关闭。
1. 在**就绪**（Ready）屏，确认 **HTTPS** 一行是**关闭**（off），然后选择**开始配置这台机器**（Set this box up）。

屏幕上逐项执行各个步骤，从检查软件包到安装本机被控端，完成后标题变成**这台机器已是网关**（This box is a gateway）。

::: warning
保险库主口令封存这台机器保管的每一份凭据，恢复备份时还要再输一次。把它记在这台机器以外的地方。
:::

## 登录面板

1. 在**这台机器已是网关**屏，选择**打开面板**（Open the panel）。
1. 在**面板密码**里填你设的密码，选择**登录**（Sign in）。

面板打开**总览**（Dashboard）页。侧栏分两组：**Hub** 和**被控端**（Agent）。

## 把 studio 加为受管机器

1. 在 `studio` 上安装被控端：

   ```bash
   sudo apt install ./neutrino-agent_0.5.0_amd64.deb
   ```

1. 在面板的 **Hub** 组里，打开**设备**（Devices）。
1. 选择**用链接添加**（Add by link）。通知里显示一条链接，三十分钟内有效。
1. 选择**复制**（Copy）。
1. 在 `studio` 上运行下面的命令，把 `<enroll-link>` 换成刚复制的链接：

   ```bash
   sudo nagent join '<enroll-link>'
   ```

`studio` 出现在**已管理的设备**（Managed devices）里，旁边是 `home-hub`。`home-hub` 的被控端由向导装好。

## 让客户端加入 hub

1. 在 `laptop` 上安装客户端：

   ```bash
   sudo apt install ./neutrino-client_0.5.0_amd64.deb
   ```

1. 在面板里打开**客户端**（Clients），选择**新建客户端链接**（New client link）。
1. 名称填 `laptop`，选择**创建链接**（Create link）。
1. 选择**复制**。链接三十分钟内有效。
1. 在 `laptop` 上以你自己的账户运行 `nclient gui`，不加 `sudo`。**微子·客户端**（Neutrino client）窗口打开，停在**中枢**（Hubs）页。
1. 在**加入 hub**（Join a hub）下，把链接粘进输入框，选择**加入**（Join）。

新出现的 hub 一行显示**已连接**（Connected），下面是 hub 的地址和“运行 neutrino_hub/0.5.0”。

## 在 studio 上安装共享模块

1. 在面板的**被控端**组里，打开**模块**（Modules）。
1. 在页面顶部的机器里选择 `studio`。
1. 选择 **File share** 标签页。没有这个标签页时，选择标签旁的 **+**，勾选 **File share**。
1. 选择**安装**（Install），等标签上不再显示**安装中**（installing）。
1. 选择**配置**（Configure）。按钮下方展开**共享**（Shares）和**用户**（Users）两节。

## 添加用户和共享

1. 在**用户**里，新用户名填 `alex`，旁边的输入框填一个密码。
1. 选择**添加用户**（Add user）。
1. 选择**应用用户**（Apply users）。`alex` 这一行显示**就绪**（ready）。
1. 在**共享**里，选择**添加共享**（Add share）。
1. **名称**（Name）填 `media`，**路径**（Path）填 `/srv/media`。
1. 选择**应用共享**（Apply shares）。

被控端在 `studio` 上创建 `/srv/media`，并以 `media` 的名字发布给每个客户端。

## 在笔记本上挂载共享

1. 在客户端窗口里打开**文件**（Files）。`media` 条目旁边是 `studio` 的地址。
1. 在 `media` 条目上选择**配置**（Config）。
1. **共享用户名**（Share username）填 `alex`，**共享密码**（Share password）填它的密码。
1. **挂载路径**（Mount path）保持默认，即家目录下的 `nas/media`。
1. 选择**挂载**（Mount）。

按钮变成**卸载**（Unmount），`laptop` 上的 `~/nas/media` 里就是 `studio` 上 `/srv/media` 的文件。
