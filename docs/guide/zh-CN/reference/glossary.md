---
title: 术语表
---

# 术语表

术语表收全站用到的产品词，一词一行：中文、英文界面上的叫法、一句意思。词按开始用微子时遇到的先后排列。

| 中文                 | 英文界面                     | 意思                                                       |
| -------------------- | ---------------------------- | ---------------------------------------------------------- |
| 微子                 | Neutrino                     | 产品名                                                     |
| 中枢                 | hub                          | 装在一台常开电脑上的主程序，客户端和被控端都连它           |
| 被控端               | agent                        | 装在提供服务的机器上，替中枢装模块、开终端                 |
| 客户端               | client                       | 装在你自己的电脑或手机上，打开中枢发布的服务               |
| 面板                 | panel                        | 中枢在浏览器里的管理页面                                   |
| 设置向导             | setup wizard                 | 装好中枢后第一次打开的那几屏                               |
| 保险库               | vault                        | 中枢存密钥、密码和令牌的加密文件；面板的提示里也写作保管库 |
| 保险库口令           | Vault passphrase             | 打开保险库的口令，恢复备份时也要                           |
| 凭据                 | Credentials                  | 存进保险库的 SSH 密钥、登录信息和令牌                      |
| 形态、模式           | Shape、Mode                  | 中枢所在电脑在网络里的角色；向导里叫形态，网络页上叫模式   |
| 服务器               | Server                       | 不转发流量的形态，三个系统都有                             |
| 旁路网关             | Side gateway                 | 给把它设成网关的设备转发流量，只在 Linux 完整版            |
| 路由器               | Router                       | 接管网口、自己提供一个网络，只在 Linux 上                  |
| 单臂路由             | One-arm router               | 只用一根网线的路由器形态                                   |
| 角色                 | Role                         | 路由器形态下每个网口做什么，可选 WAN、LAN、拆分、停用      |
| 拆分                 | Split                        | 网口角色之一，把网口切成多个 VLAN                          |
| 停用                 | Disabled                     | 网口角色之一，中枢不管这个网口，交给系统                   |
| 开放范围             | Exposure                     | 面板和服务在哪些网络上应答                                 |
| 外部访问             | Access                       | 从家外面连回中枢的办法                                     |
| 直连                 | Direct                       | 经公网地址和路由器的端口转发，直接连中枢                   |
| SSH 中继             | SSH Relay                    | 经你自己服务器上的一个公网端口连中枢                       |
| 虚拟网               | virtual network              | 架在互联网上的私有网络，NetBird 或 EasyTier                |
| 控制台               | console                      | NetBird 或 EasyTier 官方的网页管理台                       |
| setup key            | setup key                    | NetBird 控制台发的加入密钥                                 |
| 碰头点               | Bootstrap peers              | EasyTier 手动模式下已在网里的机器的地址                    |
| 子网路由、局域网路由 | Subnet routes、LAN routes    | 让客户端经虚拟网访问没装被控端的局域网设备                 |
| 代理                 | Proxy                        | 按规则把流量交给出口节点，只在完整版                       |
| 出口节点             | Exit nodes                   | 代理把流量交出去的那台服务器                               |
| AI 网关              | AI gateway                   | 中枢上的一个入口，背后是你的密钥和订阅                     |
| 提供方               | Providers                    | AI 网关转发请求的 API 端点                                 |
| 账号                 | Accounts                     | 登录到 AI 网关的订阅账号                                   |
| 加入链接             | client link、enrollment link | 面板生成的一次性链接，30 分钟内有效                        |
| 模块                 | Modules                      | 被控端在一台机器上装的一项功能                             |
| 全局配置             | Global configuration         | 模块页上对整台机器生效的设置                               |
| 实例                 | Instances                    | 一个账户的一个 VS Code、code-server 或 CloudCLI            |
| 文件共享             | File share                   | 经 SMB 共享文件夹的模块                                    |
| 终端（模块）         | Terminal                     | 设定终端用哪个账户和 shell 的模块                          |
| 远程桌面             | Remote desktop               | 共享桌面的模块，也是客户端的一页                           |
| 容器                 | Containers                   | 用 podman 运行容器的模块，只在 Linux 上                    |
| ZFS 存储             | ZFS storage                  | 管 ZFS 存储池的模块，只在 Linux 上                         |
| 服务                 | Services                     | 中枢发布给客户端的条目：网页、端口、AI、文件、桌面         |
| 转发                 | forward                      | 客户端在本机开一个端口，接到中枢发布的条目                 |
| 持久                 | Persistent                   | 终端会话在窗口关掉后还在                                   |
| 共享（终端）         | Shared                       | 其他有终端权限的客户端也看得到这个会话                     |
| 状态行               | state line                   | 客户端中枢一行上的状态字，例如 已连接 · 局域网             |
| 完整版、国内版       | intl、cn                     | 同一份源码的两个版本，国内版没有代理、NetBird 和旁路网关   |
