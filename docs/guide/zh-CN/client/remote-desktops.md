---
title: 远程桌面
---

# 远程桌面

**远程桌面**（Remote desktops）面板列出别的机器共享出来的桌面，点一下 **连接**（Connect），RustDesk 查看器就打开那台机器的屏幕。

## 条目从哪来

**远程桌面**（Remote desktops）面板里的条目是机器自己共享出来的桌面。在那台机器上运行 `sudo nagent rdp start`，那台机器的被控端向 hub 声明桌面在共享，条目随即出现。运行 `sudo nagent rdp stop` 或那台机器停止上报，条目消失。hub 的服务页上没有这一组，只有设备抽屉和这里能看到它。

## 连接

![连接桌面](/guide/zh/client_desktop_connect.webp)

1. 在条目上点 **连接**（Connect）。

按钮显示 **正在连接…**，客户端启动自带的 RustDesk 查看器，直连那台机器的 21118 端口，密码在这一次点击的应答里由 hub 交给客户端，你不用输。查看器打开后行里写 **查看器已打开**。终端里同一件事是 `nclient service desktop connect <ref>`，其中 `<ref>` 是 `nclient service list` 里的编号或条目 id。

## 看不到条目时

| 情况                                | 客户端或面板写着                                     |
| ----------------------------------- | ---------------------------------------------------- |
| 那台机器没人登录                    | `rdp_nobody_seated`：屏幕前没有人登录                |
| 你还没在 Wayland 桌面上授权屏幕共享 | `rdp_screen_not_allowed`：在那台机器的屏幕上允许一次 |
| 桌面已经停止共享                    | `rdp_not_shared`                                     |
| 那台机器没有发布可连接的地址        | `rdp_no_address`                                     |
| 这台电脑的会话没有屏幕给查看器用    | `rdp_no_desktop`                                     |
