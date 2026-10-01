---
layout: home
title: 微子
hero:
  name: 微子
  text: 用一台 hub 管理你自己的机器
  tagline: hub 装在一台常开的机器上，被控端装在它管理的每台机器上，客户端装在每个人的电脑或手机上。
  image:
    src: /neutrino_512.png
    alt: 微子
  actions:
    - theme: brand
      text: 快速上手
      link: /zh-CN/quick-start
    - theme: alt
      text: 安装 hub
      link: /zh-CN/hub/install
    - theme: alt
      text: 概述
      link: /zh-CN/overview
features:
  - title: 开始
    details: hub、被控端和客户端在你的网络里各在哪里；从零搭起一台 hub，管理一台机器，挂上一个共享。
    link: /zh-CN/overview
  - title: Hub
    details: 在一台 Linux 机器上装好 hub，再设置网络、虚拟网、代理、AI 网关、设备、客户端、服务、凭据和设置。
    link: /zh-CN/hub/install
  - title: 被控端
    details: 在 hub 管理的 Linux、Windows 或 Mac 机器上开终端、管文件、装模块，模块包括共享、Gitea、容器、ZFS 和 VS Code。
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

微子（Neutrino）用一台常开的 Linux 机器管理一个人或一个家庭的所有机器。这台机器上的 hub 决定网络形态，加入 NetBird 或 EasyTier，把选定的流量交给出口节点。hub 还提供一个 AI 网关和一个在浏览器里打开的面板。Linux、Windows 和 Mac 上的被控端提供共享、git、容器、存储和 VS Code；电脑和 Android 手机上的客户端用一个按钮打开其中每一项。
