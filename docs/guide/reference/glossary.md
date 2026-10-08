---
title: Glossary
---

# Glossary

Each row is one term the guide uses, with the name the Chinese panel and the Chinese pages give it and what it means. The rows run in the order a new user meets the terms.

| English                                             | 中文                           | Meaning                                                                                                 |
| --------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------- |
| Neutrino                                            | 微子                           | the product: a hub, agents and clients                                                                  |
| hub                                                 | 中枢                           | the main program, on one computer that stays on; agents and clients connect to it                       |
| agent                                               | 被控端                         | the program on each machine that provides services; it installs modules and opens terminals for the hub |
| client                                              | 客户端                         | the program or app on a person's computer or phone that opens what the hub publishes                    |
| panel                                               | 面板                           | the hub's management pages in a browser                                                                 |
| setup wizard                                        | 设置向导                       | the screens the panel shows the first time after the hub is installed                                   |
| vault                                               | 保险库                         | the hub's encrypted file of keys, passwords and tokens                                                  |
| **Vault passphrase**                                | 保险库口令                     | the passphrase that opens the vault, also needed to restore a backup                                    |
| **Credentials**                                     | 凭据                           | the SSH keys, logins and tokens stored in the vault                                                     |
| **Mode**                                            | 形态、模式                     | the role the hub's computer plays in its network                                                        |
| **Server**                                          | 服务器                         | the mode that forwards no traffic, on every system                                                      |
| **Side gateway**                                    | 旁路网关                       | the mode that forwards traffic for devices that name the hub as their gateway; Linux, full edition only |
| **Router**                                          | 路由器                         | the mode that takes over the network interfaces and serves a network of its own; Linux only             |
| **One-arm router**                                  | 单臂路由                       | the router mode on a single network cable                                                               |
| **Role**: **WAN**, **LAN**, **Split**, **Disabled** | 网口角色：WAN、LAN、拆分、停用 | what each network interface does in the router mode                                                     |
| **Exposure**                                        | 开放范围                       | the networks the panel and the services answer on                                                       |
| **Access**                                          | 外部访问                       | the ways to reach the hub from outside the home                                                         |
| **Direct**                                          | 直连                           | reaching the hub at a public address, through a port forward on the home router                         |
| **SSH Relay**                                       | SSH 中继                       | reaching the hub through a public port on a server of the user's own                                    |
| **Virtual network**                                 | 虚拟网                         | a private network laid over the internet: NetBird or EasyTier                                           |
| console                                             | 控制台                         | the web management page that NetBird or EasyTier runs                                                   |
| **Setup key**                                       | setup key                      | the key a NetBird console issues for joining its network                                                |
| **Bootstrap peers**                                 | 碰头点                         | in EasyTier's manual mode, the addresses of machines already on the network                             |
| **LAN routes**                                      | 子网路由、局域网路由           | routes that let a client reach LAN devices without an agent over a virtual network                      |
| **Proxy**                                           | 代理                           | sends traffic to exit nodes by rules; full edition only                                                 |
| **Exit nodes**                                      | 出口节点                       | the servers the proxy sends traffic out through                                                         |
| **AI gateway**                                      | AI 网关                        | one address on the hub in front of the user's API keys and subscriptions                                |
| **Providers**                                       | 提供方                         | the API endpoints the AI gateway sends requests to                                                      |
| **Accounts**                                        | 账号                           | the subscriptions signed in to the AI gateway                                                           |
| client link, enrollment link                        | 客户端链接、加入链接           | a link the panel creates for one device to join; it works once, within 30 minutes                       |
| **Modules**                                         | 模块                           | the features an agent installs on a machine                                                             |
| **Global configuration**                            | 全局配置                       | the settings on the **Modules** page that apply to the whole machine                                    |
| **Instances**                                       | 实例                           | one VS Code, code-server or CloudCLI for one account                                                    |
| **File share**                                      | 文件共享                       | the module that shares folders over SMB                                                                 |
| **Terminal** (module)                               | 终端（模块）                   | the module that sets the account and the shell of the machine's terminals                               |
| **Remote desktop**                                  | 远程桌面                       | the module that shares a machine's desktop, and the client page that shows it                           |
| **Containers**                                      | 容器                           | the module that runs containers with podman; Linux only                                                 |
| **ZFS storage**                                     | ZFS 存储                       | the module that manages ZFS pools; Linux only                                                           |
| **Services**                                        | 服务                           | what the hub publishes to clients: web pages, ports, the AI gateway, files and desktops                 |
| forward                                             | 转发                           | a port a client opens on its own device that leads to one published service                             |
| **Persistent**                                      | 持久                           | a terminal session that stays after its window closes                                                   |
| **Shared**                                          | 共享                           | a terminal session that other clients with terminal permission also see                                 |
| state line                                          | 状态行                         | the words on a client's hub row, for example **Connected · LAN**                                        |
| full edition, mainland edition                      | 完整版、国内版                 | two builds of one source; the mainland edition has no proxy, no NetBird and no side gateway             |
