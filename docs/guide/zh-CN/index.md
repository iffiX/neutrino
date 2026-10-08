---
layout: home
title: 微子
hero:
  name: 微子
  text: 用一台中枢管理你自己的机器
  tagline: 中枢装在一台常开的机器上，被控端装在它管理的每台机器上，客户端装在每个人的电脑或手机上。
  image:
    src: /neutrino_512.png
    alt: 微子
  actions:
    - theme: brand
      text: 快速上手
      link: /zh-CN/quick-start
    - theme: alt
      text: 安装中枢
      link: /zh-CN/install/hub
    - theme: alt
      text: 概述
      link: /zh-CN/overview
features:
  - title: 开始
    details: 中枢、被控端和客户端各在你网络里的什么位置；用一台电脑和一部手机走一遍快速上手；安装中枢、被控端和客户端。
    link: /zh-CN/overview
  - title: 场景
    details: 选哪种外部访问；一台笔记本管所有机器；经虚拟网访问没装被控端的局域网设备。
    link: /zh-CN/scenarios/choose_a_way_in
  - title: 中枢
    details: 设置网络、外部访问、代理、AI 网关、设备、客户端、服务、凭据和设置。
    link: /zh-CN/hub/dashboard
  - title: 被控端
    details: 在受管机器上开终端、管文件、装模块，模块包括 AI 工具、文件共享、终端、远程桌面、Gitea、VS Code、code-server、CloudCLI、容器和 ZFS 存储。
    link: /zh-CN/agent/terminals
  - title: 客户端
    details: Linux、Windows 和 macOS 上的桌面客户端，以及 Android 应用。
    link: /zh-CN/client/desktop
  - title: 命令
    details: nhub、nagent 和 nclient 的每个子命令。
    link: /zh-CN/commands/nhub
  - title: 参考
    details: 每个包支持的系统，按现象排查的故障，以及协议 3 下的通道。
    link: /zh-CN/reference/platforms
---

微子（Neutrino）用一台常开的机器管理一个人或一个家庭的所有机器。中枢装在这台机器上：Linux 上可以是任意网络形态，macOS 和 Windows 上是服务器形态。中枢设定网络形态，提供从外面连回中枢的办法，把选定的流量交给出口节点，还提供一个 AI 网关和一个在浏览器里打开的面板。Linux、Windows 和 Mac 上的被控端提供 AI 工具、文件共享、终端、远程桌面、Gitea、VS Code、code-server、CloudCLI、容器和 ZFS 存储；电脑和 Android 手机上的客户端，用一个按钮打开其中每一项。
