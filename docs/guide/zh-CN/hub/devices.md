---
title: 设备
---

# 设备

**设备**（Devices）页是接入和操作机器的地方。局域网里扫到的机器、有 SSH 凭据的机器和已经在汇报的机器分栏列出；点开一台就能重启、唤醒、开 shell 或进桌面。页面分 **已管理的设备**（Managed devices）和 **未管理的设备**（Unmanaged devices）两栏，上方有 **扫描局域网**（Scan LAN）、**用链接添加**（Add by link）和筛选。

## 三种状态

![设备页](/guide/zh/devices_overview.webp)

| 标记     | 含义                                                    | 下一步             |
| -------- | ------------------------------------------------------- | ------------------ |
| Agent    | 已管理：机器上跑着被控端，上报自身状态，从 hub 接受模块 | 打开抽屉           |
| SSH      | 未管理，但保存了它的 SSH 凭据                           | 一步安装被控端     |
| 仅扫描到 | 未管理，也没有凭据                                      | 给它发一个加入链接 |
| 离线     | 没有响应；保存的凭据依然有效                            | 机器上线后再操作   |

**扫描局域网** 列出连在局域网里的机器，扫到的进入未管理一栏。筛选按名称、IP 或 MAC。

## 接入

![加入链接](/guide/zh/devices_enroll_link.webp)

接入的每一步都在[安装被控端](../agent/install.md)里。

- **用链接添加** 生成一条 `neutrino://enroll/…` 链接，在那台机器上运行 `sudo nagent connect '<enroll-link>'`，其中 `<enroll-link>` 是复制的链接。链接五分钟内有效，再生成一条时上一条作废。
- 有 SSH 凭据的机器，在抽屉里点 **安装被控端**（Install agent），hub 登录上去装好并接入。

![SSH 安装](/guide/zh/devices_install_ssh.webp)

## 抽屉

![设备抽屉](/guide/zh/devices_drawer.webp)

点一台已管理的设备打开抽屉。**身份**（Identity）里改 **显示名称**（Display name）和 **图标**（Icon）；下面是 CPU、内存和上报时间。

| **操作**（Actions）里的按钮           | 做什么                                        |
| ------------------------------------- | --------------------------------------------- |
| **重启**（Reboot）                    | 机器立即重启                                  |
| **关机**（Shut down）                 | 机器立即关机                                  |
| **网络唤醒**（Wake-on-LAN）           | 向 hub 服务的每个网络发一个魔术包，UDP 端口 9 |
| **重新安装被控端**（Reinstall agent） | 经 SSH 再装一遍                               |
| **忘记设备**（Forget device）         | 这台设备和它保存的凭据都从 hub 删除           |

重启和关机的确认框写着机器会立即执行，未保存的内容丢失。机器离线时 hub 拒绝操作并返回 `agent_offline`，机器上线后需要重新点一次。忘记一台设备不动机器上的被控端，下一条加入链接能让它回来。

**终端**（Terminal）和 **文件**（Files）两个按钮分别打开[终端](./terminals.md)和[文件](./files.md)页，机器已经选好。

## 远程桌面

![抽屉里的远程桌面](/guide/zh/devices_drawer_rdp.webp)

远程桌面用 RustDesk，主机随被控端一起装。共享在那台机器上发起：

```bash
sudo nagent rdp start --user alex
```

不带 `--user` 时，共享的是运行这条 sudo 命令的账户的桌面；命令直接以 root 运行时，共享屏幕前唯一登录的账户的桌面。命令返回后，抽屉的 **远程桌面**（Remote desktop）一节出现 **ID**、**直连端口 21118**（Direct port）、**由 alex 共享。**（Shared by）和观看人数。坐席密码是这台桌面接受连接时核对的密码，由 hub 保管，从不显示。**重置坐席密码**（Reset seat password）让机器立即换一个，当前连着的观看者都要重新连。

![客户端上连接桌面](/guide/zh/client_desktop_connect.webp)

客户端 **远程桌面**（Remote desktops）面板里点 **连接**（Connect），RustDesk 查看器打开那台机器的桌面，密码在这一次点击的应答里由 hub 交给客户端。要停止共享，在那台机器上运行 `sudo nagent rdp stop`。屏幕前没人登录时抽屉写 `rdp_nobody_seated`；Wayland 桌面还没允许过屏幕共享时写 `rdp_screen_not_allowed`，在那台机器自己的屏幕上允许一次。

## 版本不一致时

抽屉顶部写着 **这个被控端与 hub 的版本不一致。**（This agent is a different version from the hub.）时，给这台机器换上与 hub 同版本的被控端。有 SSH 凭据的机器点 **重新安装被控端**；没有的在那台机器上装新包，再用一条新链接接入。升级顺序是先 hub，再每台被控端，最后客户端。
