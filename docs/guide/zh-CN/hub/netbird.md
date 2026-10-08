---
title: NetBird
---

# 把中枢加入 NetBird

这一页让中枢用一把可重复使用的 setup key 加入 NetBird，再把同一把 key 交给每个客户端。你需要一个 netbird.io 账号，或者一套自建的 NetBird 管理面。国内版没有 NetBird，国内版用[把中枢放到 EasyTier 网络里](./easytier.md)。

开始之前，在 **外部访问** 页打开 **NetBird** 卡片的开关，选择 **应用外部访问**。

## 建一把多台机器能用的 setup key

中枢和每个客户端都用这把 key，所以它要能重复使用、不限次数。字段名照 NetBird 控制台的英文界面写。对话框里的 **Ephemeral Peers** 和 **Allow Extra DNS Labels** 保持关闭。

1. 在 NetBird 控制台里打开 **Settings** 下的 **Setup Keys**。
1. 选择 **Create Key**。
1. 在 **Name** 里给 key 起个名字，例如 `neutrino-hub`。
1. 打开 **Make this key reusable**。
1. **Usage limit** 留空，框里显示 **Unlimited**。
1. **Expires in** 留空，key 不过期。
1. 在 **Auto-assigned groups** 里新建一个分组，例如 `neutrino`。
1. 选择 **Create Setup Key**。
1. 在 **Setup key created successfully!** 对话框里复制 key。控制台只显示这一次。

![NetBird 控制台的 Setup Keys 列表](/guide/console/console_netbird_keys_list.webp)

![填好的 Create Setup Key 对话框](/guide/console/console_netbird_key_create.webp)

![只显示一次 key 的那一屏](/guide/console/console_netbird_key_created.webp)

::: warning
控制台 **Networks** → **Routing Peers** → **Add** → **Install NetBird** 给出的 key 只能用一次。中枢存着这种 key 时，第一台设备用掉它之后，别的客户端都加入不了。
:::

## 让中枢加入

1. 在外部访问页选中 **NetBird** 卡片。
1. 把 key 粘到 **设置** 里的 setup key 输入框。
1. 用 netbird.io 时，管理面地址留空；用自建管理面时，填它的地址。
1. 选择 **加入**。

徽章先读 **加入中**，再读 **已连接**。**设置** 里出现 **虚拟网地址**、**名称** 和 **管理面**。**Setup key** 一行读 **已保存**，旁边有 **替换** 和 **忘掉**。

![加入之后的 NetBird 设置](/guide/zh/overlay_netbird_settings.webp)

## 看懂徽章

| 徽章             | 含义                                    |
| ---------------- | --------------------------------------- |
| **加入中**       | 中枢正在用 key 加入                     |
| **已连接**       | 中枢在这张网上                          |
| **正在连接**     | NetBird 守护进程重启后正在重连          |
| **未加入**       | 中枢没有 NetBird 身份，或上次登录已失效 |
| **管理面不可达** | 中枢连不上 NetBird 的管理面             |
| **未运行**       | NetBird 守护进程没有运行                |

徽章不是 **已连接** 时怎么处理，见[故障排查](../reference/troubleshooting.md#外部访问)。

## 换掉交给客户端的 key

中枢存的是一次性 key 时，换成可重复使用的：

1. 照“建一把多台机器能用的 setup key”一节建一把新 key。
1. 在 **Setup key** 一行选择 **替换**。
1. 粘贴新 key，选择 **保存**。

中枢自己的 NetBird 身份不变，客户端随下一次状态拿到新 key。选择 **忘掉** 之后、存进新 key 之前，客户端都加入不了。

## 发布局域网网段

**局域网路由** 列出中枢服务的每个网段。在 NetBird 控制台里发布这些网段，客户端就能按局域网地址访问那些机器，步骤见[经 NetBird 访问没装被控端的设备](../scenarios/netbird_lan_routes.md)。服务器形态的中枢不服务任何网段，这里写着 **没有接口处于 LAN 角色。**

![局域网路由列出中枢服务的网段](/guide/zh/overlay_netbird_routes.webp)

## 重新加入或离开

给中枢换一个 NetBird 身份，要先离开再加入：

1. 在 **设置** 标题旁选择 **离开**。
1. 在 **离开 NetBird 网络** 对话框里选择 **离开**。
1. 照“让中枢加入”一节，用一把新 key 再加入。
1. 控制台的 **Peers** 里还留着中枢的旧对端时，删掉它。

手机上重装客户端后，它作为新对端注册，旧的那个也在 **Peers** 里删掉。
