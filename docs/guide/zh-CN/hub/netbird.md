---
title: NetBird
---

# 把中枢加入 NetBird

照这一页做完，中枢在 NetBird 上的徽章显示 **已连接**（connected），面板里存着一把可以重复使用的 setup key。每个客户端扫码加入时都拿到这把 key，和中枢进同一张 NetBird 网。你需要一个 netbird.io 账号，或者一套自建的 NetBird 管理面。

国内版没有 NetBird。国内版的外部访问见[把中枢放到 EasyTier 网络里](./easytier.md)。

开始之前，在 **外部访问**（Access）页打开 **NetBird** 卡片的开关，并选择 **应用外部访问**（Apply access）。NetBird 还没运行时，加入按钮不可用，旁边写着 **NetBird 还没有运行。**（NetBird is not running yet.）

## 建一把多台机器能用的 setup key

中枢自己用这把 key 加入，再把它交给每个客户端。所以 key 要能重复使用，次数不能先用完。下面的字段名照 NetBird 控制台的英文界面写。对话框里的 **Ephemeral Peers** 和 **Allow Extra DNS Labels** 保持关闭。

1. 在 NetBird 控制台里打开 **Settings** 下的 **Setup Keys**。
1. 选择 **Create Key**。
1. 在 **Name** 里给 key 起个名字，例如 `neutrino-hub`。
1. 打开 **Make this key reusable**。
1. **Usage limit** 留空就是不限次数，框里显示 **Unlimited**。要限次数时，填不少于中枢加全部客户端的台数。
1. **Expires in** 留空，key 就不会过期。
1. 在 **Auto-assigned groups** 里新建一个分组，例如 `neutrino`。
1. 选择 **Create Setup Key**。
1. 在 **Setup key created successfully!** 对话框里，用 key 旁边的复制按钮复制下来。控制台只显示这一次。

![NetBird 控制台的 Setup Keys 列表](/guide/console/console_netbird_keys_list.webp)

![填好的 Create Setup Key 对话框](/guide/console/console_netbird_key_create.webp)

![只显示一次 key 的那一屏](/guide/console/console_netbird_key_created.webp)

::: warning
控制台 **Networks** → **Routing Peers** → **Add** → **Install NetBird** 给出的 key 只能用一次。中枢存着这种 key 时，key 用掉之后，客户端加入返回 `overlay_join_failed`。
:::

## 让中枢加入

1. 在外部访问页选中 **NetBird** 卡片。
1. 在下方的 **设置**（Settings）里，照三步提示做：「在控制台里打开 Setup Keys，新建一把 key。」「把它设成可重复使用（reusable）、不限使用次数，这台中枢的每个客户端都用它加入。」「复制它只显示一次的 key，粘贴到下面。」
1. 把 key 粘到 setup key 输入框。
1. 用 netbird.io 时，管理面地址留空；用自建管理面时，填它的地址。
1. 选择 **加入**（Join）。

徽章先显示 **加入中**（joining），再显示 **已连接**。**设置** 里出现 **虚拟网地址**（Overlay address）、**名称**（Name）和 **管理面**（Management）。**Setup key** 一行显示 **已保存**（Saved），旁边有 **替换**（Replace）和 **忘掉**（Forget）。

![加入之后的 NetBird 设置](/guide/zh/overlay_netbird_settings.webp)

## 看懂徽章

| 徽章                                       | 含义                                    | 怎么办                                                |
| ------------------------------------------ | --------------------------------------- | ----------------------------------------------------- |
| **加入中**（joining）                      | 中枢正在用 key 加入                     | 等它变成已连接                                        |
| **已连接**（connected）                    | 中枢在这张网上                          | 不用处理                                              |
| **正在连接**（connecting）                 | NetBird 守护进程重启后正在重连          | 等它变成已连接                                        |
| **未加入**（not joined）                   | 中枢没有 NetBird 身份，或上次登录已失效 | 用一把新 key 再加入                                   |
| **管理面不可达**（management unreachable） | 中枢连不上 NetBird 的管理面             | 检查这台机器的上行线路和 DNS，确认管理面地址填对了    |
| **未运行**（not running）                  | NetBird 守护进程没有运行                | 在外部访问页关掉再打开 NetBird，选择 **应用外部访问** |

上次登录失效时，设置里写着 **上次的登录已失效，请用新的 setup key 重新加入。**（The last login has expired. Join again with a new setup key.）管理面不可达时，设置里写着 **管理面不可达。**（Management plane unreachable.）

## 换掉交给客户端的 key

中枢存的是一次性 key 时，key 用掉之后客户端都加入不了。换成可重复使用的 key：

1. 照本页第一节在控制台里建一把可重复使用的 key。
1. 在 **Setup key** 一行选择 **替换**。
1. 粘贴新 key。
1. 选择 **保存**（Save）。

中枢自己的 NetBird 身份不变。每个客户端在中枢下一次推送状态时拿到新 key。选择 **忘掉** 之后、存进新 key 之前，客户端都加入不了这张网。

## 发布局域网网段

**局域网路由**（LAN routes）列出中枢服务的每个网段。把这些网段在 NetBird 控制台里发布出去，客户端就能按局域网地址访问那些机器。具体步骤在[经 NetBird 访问局域网设备](../scenarios/netbird_lan_routes.md)。

![局域网路由列出中枢服务的网段](/guide/zh/overlay_netbird_routes.webp)

服务器形态的中枢不服务任何网段，这里写着 **没有接口处于 LAN 角色。**（No interface has the LAN role.）

## 重新加入或离开

面板上没有“重新加入”按钮。要给中枢换一个 NetBird 身份，先离开，再加入：

1. 在 **设置** 标题旁选择 **离开**（Leave）。
1. 在 **离开 NetBird 网络**（Leave the NetBird network）对话框里选择 **离开**。中枢从这张网里删除自己。
1. 照“让中枢加入”一节，用一把新 key 再加入。
1. 控制台的 **Peers** 里还留着中枢的旧对端时，删掉它。

只经 NetBird 连到中枢的人，在中枢离开期间连不上。手机上重装客户端 App 后，它作为新对端注册，旧的那个也在控制台的 **Peers** 里删掉。
