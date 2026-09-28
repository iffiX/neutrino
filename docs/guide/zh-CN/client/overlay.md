---
title: 虚拟网
---

# 虚拟网

加入 hub 的虚拟网后，这台电脑成为 hub 的 NetBird 或 EasyTier 网络里的普通一员。只要能上网，就能用 hub 在这个网络里的地址找到它。

## 加入之前

- 装好客户端包。包会把 NetBird 和 EasyTier 的守护进程登记成系统服务。
- hub 运行 NetBird 或 EasyTier；用 NetBird 时，hub 的 **虚拟网**（Overlay）页上存有 setup key。
- hub 的客户端页允许这个客户端使用虚拟网。

缺了任何一条，hub 那一行就没有 **虚拟网**（Virtual network）按钮。

## 加入与离开

1. 打开 **Hub** 标签。
1. 点 hub 那一行的 **虚拟网** 按钮。
1. 如果弹出系统授权框，确认它。

Linux 和 macOS 上加入 EasyTier 会弹授权框，因为它的配置要以 root 写入；NetBird 和 Windows 上的 EasyTier 不弹。再点一次按钮就离开。

## 按钮上的字

按钮写着“虚拟网”、状态，分到地址后再写本机的地址。

| 状态                     | 含义                                |
| ------------------------ | ----------------------------------- |
| **未加入**               | 本机不在这个网络里                  |
| **加入中…**、**离开中…** | 正在进行，按钮变灰                  |
| **已加入**               | 本机在这个网络里                    |
| **失败**                 | 上一步失败，错误码写在 hub 名字下面 |

| 错误码                   | 含义                                           |
| ------------------------ | ---------------------------------------------- |
| `overlay_other_network`  | 本机的 NetBird 在另一个网络里，先离开那个      |
| `overlay_not_authorized` | 你取消了系统授权框                             |
| `overlay_daemon_down`    | NetBird 守护进程没有运行，重装客户端           |
| `bundle_missing`         | 这份安装里没有 NetBird 或 EasyTier，重装客户端 |
| `overlay_join_failed`    | NetBird 拒绝了这次加入，码后面是它自己的原话   |

## 两个 hub 同一个网络

两个 hub 用同一个 NetBird 管理服务器，或同一个 EasyTier 网络名时，共用一份成员关系，两行显示同一个状态。离开其中一个 hub，网络还在；离开最后一个，才退出网络。

## 客户端退出之后

客户端退出后，守护进程仍让本机留在网络里。重启后 NetBird 自动回到网络，Linux 和 macOS 上的 EasyTier 也一样；Windows 上的 EasyTier 要等客户端运行起来才回去。要退出网络，点按钮或离开那个 hub。
