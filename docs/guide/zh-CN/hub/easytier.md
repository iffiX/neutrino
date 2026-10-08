---
title: EasyTier
---

# 把中枢放到 EasyTier 网络里

本页让中枢加入一张 EasyTier 网络，最后徽章显示 **已连接**（connected），客户端也能加入这张网。完整版和国内版都有 EasyTier。

一张 EasyTier 网由网络名和网络密码确定，两样都相同的机器在同一张网里。密码同时是这张网流量的加密密钥。网里的机器之间用 11010 端口，TCP 和 UDP 都用。

开始之前，在 **外部访问**（Access）页打开 **EasyTier** 卡片的开关，并选择 **应用外部访问**（Apply access）。

## 选网络从哪来

选中 **EasyTier** 卡片，在下方的 **设置**（Settings）里选模式：

- 有 EasyTier 控制台账号时，选 **EasyTier 控制台**（EasyTier console）。网络、地址和子网路由都由控制台下发。
- 没有控制台账号，而且每台机器都能连到中枢的 11010 端口时，选 **手动碰头点**（Manual bootstrap peers）。中枢保存网络名和密码，经你列出的碰头点组网。

两种模式共用一个应用栏 **应用 EasyTier 设置**（Apply EasyTier settings）。换模式时 EasyTier 重启，经它的连接短暂中断。

## 在控制台里挂上中枢

控制台模式下，中枢先登记到你的控制台账号，你再在控制台里给它建一张网。

### 复制控制台地址

控制台地址形如 `tcp://et-web.console.easytier.net:22020/<token>`，`<token>` 是你账号的令牌。在 EasyTier 控制台里找到设备加入用的地址，复制下来。

<!-- 待核: 控制台网址、地址在哪复制、给的是完整地址还是只有令牌（大纲待核第 2 条） -->

**控制台地址**（Console address）也接受单独一个令牌。只填令牌时，中枢连 `udp://config-server.easytier.cn:22020`。填的内容既不是带令牌的地址也不是令牌时，中枢拒绝并返回 `easytier_config_server_invalid`。

### 登记中枢

1. 在 **设置** 里选 **EasyTier 控制台**。
1. 把地址粘到 **控制台地址**。
1. 可选：控制台的网络用了 EasyTier 的安全模式时，打开 **安全模式**（Secure mode）。
1. 选择 **应用 EasyTier 设置**。

徽章显示 **等待控制台挂载**（Waiting for the console）。设置里提示本机已登记到控制台，要在控制台里把它挂到一个网络上。

![中枢已登记，等待控制台挂载](/guide/zh/overlay_easytier_console_waiting.webp)

### 给中枢建网络

1. 在控制台的设备列表里找到中枢这台设备。
1. 给它新建一张网络，填网络名和网络密码。
1. 运行这张网络。

<!-- 待核: 控制台设备列表、建网络表单的字段名和运行按钮（大纲待核第 2 条） -->

![EasyTier 控制台的设备列表](/guide/console/console_easytier_devices.webp)

![控制台里给中枢建网络的表单](/guide/console/console_easytier_network_create.webp)

控制台把网络下发给中枢之后，徽章显示 **已连接**。**控制台下发的网络**（Networks from the console）列出每张网的网络名、本机在网里的地址和本机名称，以及 **子网路由**（Subnet routes）。控制台没给出的项写着 **控制台未提供**（Not provided by the console）。

<!-- 待核: 网里只有中枢一台时，徽章读已连接还是还没有对端（no peers yet）（大纲待核第 4 条） -->

![控制台下发的网络](/guide/zh/overlay_easytier_console_networks.webp)

## 挂上每个客户端

控制台模式下，客户端拿到的是控制台地址。客户端连虚拟网时，先登记到你的控制台，你再在控制台里把它挂到网上。这期间，客户端的虚拟网一行显示 **连接中…**（Connecting…），下方写着同样的登记提示。

在控制台的设备列表里找到这个客户端，把它挂到中枢所在的那张网络。挂上之后，客户端那一行显示 **已连接**（Connected）。

![控制台里把手机挂到同一张网](/guide/console/console_easytier_device_attach.webp)

## 导出局域网

控制台模式下，在控制台里给中枢这台设备加子网代理。手动模式下，把网段填进 **导出的局域网**（Exported networks）。完整步骤在[经 EasyTier 访问局域网设备](../scenarios/easytier_lan_routes.md)。

## 手动碰头点

手动模式下，中枢自己保存网络名和密码，并主动连你列出的碰头点。

1. 在 **设置** 里选 **手动碰头点**。
1. 选择 **生成**（Generate）。**网络名**（Network name）、**网络密码**（Network secret）和 **本机地址**（This box's address）自动填好。
1. 在 **碰头点**（Bootstrap peers）里加一台已经在网里的机器，例如 `tcp://198.51.100.7:11010`。
1. 可选：在 **导出的局域网** 里加上网里机器经中枢访问的网段。
1. 选择 **应用 EasyTier 设置**。

![手动模式下的 EasyTier 设置](/guide/zh/overlay_easytier_settings.webp)

一个碰头点都没填时，应用栏不可用。网里还没有别的机器时，先用下面第二条命令在一台公网机器上自建碰头点，再把它填进来。直接调用接口时，中枢拒绝并返回 `easytier_invalid`。

客户端拿到的碰头点是中枢上行网口的地址加 11010 端口。客户端在外面时，要能连到这个地址和端口。

::: warning
换密码等于换一张网。别的机器在改成新密码之前，仍留在旧的那张网里。
:::

**给别的机器的命令**（Commands for another machine）显示两条命令，屏幕上的密码打了码。**复制（含密码）**（Copy with the secret）复制带真实密码的命令。命令里的 `<network-name>` 是网络名，`<secret>` 是网络密码，`<hub-address>` 是别的机器访问中枢用的地址；复制出来的命令里三项都已填好。

第一条让一台机器经中枢加入这张网：

```bash
easytier-core -d --network-name <network-name> --network-secret <secret> -p tcp://<hub-address>:11010
```

第二条在一台有公网地址的机器上自建碰头点。它只转发这张网的流量，只接受带这把密码的机器：

```bash
easytier-core --private-mode true --network-name <network-name> --network-secret <secret> \
  --relay-network-whitelist <network-name> -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010
```
