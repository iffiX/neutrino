---
title: EasyTier
---

# 把中枢放到 EasyTier 网络里

EasyTier 是外部访问的一种，完整版和国内版都有。网络名和网络密码都相同的机器在同一张网里，网里的机器之间用 11010 端口，TCP 和 UDP 都用。

开始之前，在 **外部访问** 页打开 **EasyTier** 卡片的开关，选择 **应用外部访问**。

## 选网络从哪来

选中 **EasyTier** 卡片，在下方的 **设置** 里选模式：

- 有 EasyTier 控制台账号时，选 **EasyTier 控制台**。网络、地址和子网路由都由控制台下发。
- 每台机器都能连到中枢的 11010 端口时，也可以选 **手动碰头点**。

两种模式共用 **应用 EasyTier 设置**。换模式时 EasyTier 重启，经它的连接短暂中断。

## 在控制台里挂上中枢

### 复制控制台地址

控制台地址形如 `tcp://et-web.console.easytier.net:22020/<token>`，`<token>` 是你账号的令牌。在 `https://console.easytier.net` 里复制它：

1. 在右上角选择 **设备接入方法**。
1. 选择 **开源版接入** 标签。
1. 在 **连接 EasyTier** 一节，从 **接入秘钥** 里选一把密钥。
1. 复制页面给出的命令里 `--config-server` 后面的整段地址。

### 登记中枢

1. 在 **设置** 里选 **EasyTier 控制台**。
1. 把地址粘到 **控制台地址**。
1. **安全模式** 保持关着，和第一步一样；控制台自己的接入命令带 `--secure-mode=true`，开不开中枢都能登记上。
1. 选择 **应用 EasyTier 设置**。

徽章读 **等待控制台挂载**。

![中枢已登记，等待控制台挂载](/guide/zh/overlay_easytier_console_waiting.webp)

### 给中枢建网络

中枢登记之后，出现在控制台的 **设备** 页。

![EasyTier 控制台的设备列表](/guide/console/console_easytier_devices.webp)

1. 在控制台侧栏打开 **网络**。
1. 选择 **创建网络**。
1. 在 **创建租户网络** 对话框里填 **网络名称**。**网络地址范围** 留空时用 `10.144.0.0/16`。
1. 选择对话框底部的 **创建网络**。
1. 选择网络名，打开这张网络的页面。
1. 选择 **挂载设备**。
1. 在 **入网设备** 里选中枢。
1. 选择 **加入网络**。

![控制台里给中枢建网络的表单](/guide/console/console_easytier_network_create.webp)

在 **网络设备** 标签里，中枢那一行先读 **挂载中**，再读 **运行中**。

网里只有中枢一台时，面板上的徽章读 **还没有对端**；另一台设备连通后读 **已连接**。**控制台下发的网络** 列出每张网的网络名、本机地址和 **子网路由**。

![控制台下发的网络](/guide/zh/overlay_easytier_console_networks.webp)

## 挂上每个客户端

控制台模式下，客户端连虚拟网时先登记到你的控制台，这期间它的虚拟网一行读 **连接中…**。在控制台里打开中枢所在的网络，照上面的办法挂载这个客户端，那一行随即读 **已连接**。

![控制台里把手机挂到同一张网](/guide/console/console_easytier_device_attach.webp)

## 导出局域网

控制台模式下，在控制台里网络的 **子网路由** 标签把网段加成经中枢访问的路由。手动模式下，把网段填进 **导出的局域网**。完整步骤见[经 EasyTier 访问没装被控端的设备](../scenarios/easytier_lan_routes.md)。

## 手动碰头点

手动模式下，中枢自己保存网络名和密码，并连你列出的碰头点。

1. 在 **设置** 里选 **手动碰头点**。
1. 选择 **生成**，**网络名**、**网络密码** 和 **本机地址** 自动填好。
1. 在 **碰头点** 里加一台已经在网里的机器，例如 `tcp://198.51.100.7:11010`。
1. 可选：在 **导出的局域网** 里加上网段。
1. 选择 **应用 EasyTier 设置**。

![手动模式下的 EasyTier 设置](/guide/zh/overlay_easytier_settings.webp)

一个碰头点都没填时，应用栏不可用。网里还没有别的机器时，先用下面第二条命令在一台公网机器上自建碰头点。客户端在外面时，要能连到中枢上行网口的 11010 端口。

::: warning
换密码等于换一张网。别的机器改成新密码之前，仍留在旧的那张网里。
:::

**给别的机器的命令** 显示两条命令，**复制（含密码）** 复制带真实密码的命令。`<network-name>` 是网络名，`<secret>` 是网络密码，`<hub-address>` 是中枢的地址，复制出来时都已填好。

第一条让一台机器经中枢加入这张网：

```bash
easytier-core -d --network-name <network-name> --network-secret <secret> -p tcp://<hub-address>:11010
```

第二条在一台公网机器上自建碰头点：

```bash
easytier-core --private-mode true --network-name <network-name> --network-secret <secret> \
  --relay-network-whitelist <network-name> -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010
```

设置失败时，见[故障排查](../reference/troubleshooting.md#外部访问)。
