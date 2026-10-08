---
layout: home
title: 微子
markdownStyles: false
hero:
  name: 微子
  text: 一台电脑上的服务，手机和笔记本在哪都能用
  tagline: 家里的电脑，扫一次码，从任何地方接着用
  image:
    src: /guide/zh/app_terminal.webp
    alt: 手机上开着家里电脑的终端
  actions:
    - theme: brand
      text: 第一步
      link: /zh-CN/quick-start
    - theme: alt
      text: 概述
      link: /zh-CN/overview
groups:
  - title: 第一次用
    items:
      - title: 第一步
        details: 装中枢，加入手机和笔记本，在外面也连得上
        link: /zh-CN/quick-start
      - title: AI 会话
        details: 手机上接着电脑上的 Claude Code 会话
        link: /zh-CN/quick-start/cloudcli
      - title: 编辑器
        details: 在浏览器里打开电脑上的 VS Code
        link: /zh-CN/quick-start/vscode
      - title: 终端
        details: 笔记本上开的终端，换到手机上接着用
        link: /zh-CN/quick-start/terminal
      - title: 远程桌面
        details: 在手机或笔记本上操作电脑的桌面
        link: /zh-CN/quick-start/remote_desktop
      - title: 文件
        details: 共享电脑上的文件夹，在别处打开
        link: /zh-CN/quick-start/files
  - title: 进阶用法
    items:
      - title: 选哪种外部访问
        details: 直连、SSH 中继、NetBird、EasyTier 对照
        link: /zh-CN/scenarios/choose_a_way_in
      - title: 一台笔记本管所有机器
        details: 给家里别的机器也装上被控端
        link: /zh-CN/scenarios/one_laptop_every_machine
      - title: VPS 中继
        details: 经你自己的 VPS 连回家
        link: /zh-CN/scenarios/vps_relay
      - title: 路由器或旁路网关
        details: 让中枢给家里的设备转发流量
        link: /zh-CN/scenarios/router_or_gateway
      - title: 没装被控端的设备
        details: 经虚拟网打开打印机、NAS 的管理页
        link: /zh-CN/scenarios/easytier_lan_routes
  - title: 文档参考
    items:
      - title: 中枢
        details: 面板上每一页的设置
        link: /zh-CN/hub/dashboard
      - title: 被控端
        details: 终端、文件和每个模块
        link: /zh-CN/agent/terminals
      - title: 客户端
        details: 桌面客户端和 Android 应用
        link: /zh-CN/client/desktop
      - title: 命令
        details: nhub、nagent、nclient 的子命令
        link: /zh-CN/commands/nhub
      - title: 参考
        details: 支持的平台、故障排查和术语表
        link: /zh-CN/reference/platforms
---

微子的中枢装在家里那台常开的电脑上。手机和笔记本装上客户端，扫码或贴链接加入；在外面经 EasyTier 这类外部访问连回来，家里没有公网地址也行。电脑上的终端、Claude Code 会话、编辑器、桌面和文件，在手机和笔记本上都能打开。

<HomeGroups
  v-for="group in $frontmatter.groups"
  :key="group.title"
  :title="group.title"
  :items="group.items"
/>
