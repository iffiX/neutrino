---
title: 远程桌面
---

# 远程桌面（Remote desktop）

**Remote desktop** 模块把受管机器的桌面共享给这台中枢的客户端。设置只有一个开关，新机器上默认关着。被控端的安装包里带着 RustDesk，所以这个模块不用安装。

## 共享桌面

1. 在[模块](../modules.md)页的 **Remote desktop** 标签上，打开 **共享这台机器的桌面**（Share this machine's desktop）。
1. 选择 **应用远程桌面**（Apply remote desktop）。
1. 在客户端的 **远程桌面**（Remote desktops）页上，选这台机器的 **连接**（Connect）。

![Remote desktop 标签，共享开关已打开并应用](/guide/zh/modules_remote_desktop_tab.webp)

开关打开后，被控端停掉机器上别的 RustDesk 主机，用 RustDesk 自己的服务名运行它带的那一份，所以机器重启后共享照样恢复。有人正在这台机器上用的 RustDesk 查看器保持原样。共享走直连端口 21118，不经过 RustDesk 的服务器。RustDesk 1.4.9 的主机启动时，会向三个公共 STUN 服务器（`stun.l.google.com`、`stun.cloudflare.com`、`stun.nextcloud.com`）查询本机的 IPv6 地址。这个请求不带标识，也不登记任何东西，RustDesk 没有关掉它的选项。

客户端看到的，是正坐在屏幕前登录的那个人的桌面。只要被控端的 RustDesk 服务在运行，标签就读 **运行中**（running），屏幕前有没有人都一样。屏幕前没人登录时，客户端的 **连接** 以 `rdp_nobody_seated` 失败。

在 Mac 上，开关打开时屏幕上弹出对话框，列出 RustDesk 要的“屏幕录制”和“辅助功能”权限。屏幕前的人授权一次之后，客户端才看得到画面。

Windows 上，这个模块只在 amd64 机器上运行。

## 停止共享

1. 关掉 **共享这台机器的桌面**。
1. 选择 **应用远程桌面**。

被控端的 RustDesk 停下，你原先装在这台机器上的 RustDesk 恢复原样。卸载被控端、机器离开中枢或在[设备](../../hub/devices.md)页上移除机器时，被控端也立刻停下它的 RustDesk，放回原来的那一份。

## 失败时

哪一步失败，标签上就显示错误码的说明，说明里写着是哪一步。再选择一次 **应用远程桌面**，就重试这一步。

| 错误码                | 原因                                 |
| --------------------- | ------------------------------------ |
| `rdp_takeover_failed` | 启动被控端 RustDesk 的某一步失败     |
| `rdp_restore_failed`  | 还原机器原来的 RustDesk 的某一步失败 |

共享没有可显示的画面时，客户端的 **连接** 以错误码失败：

| 错误码                   | 原因                                                     |
| ------------------------ | -------------------------------------------------------- |
| `rdp_nobody_seated`      | 机器屏幕前没人登录                                       |
| `rdp_screen_not_allowed` | Wayland 会话还没允许屏幕共享，在那台机器的屏幕上允许一次 |
