---
title: 设置
---

# 设置

**设置**（Settings）页管面板密码、语言、配置存档和版本信息，各节是 **面板密码**（Panel password）、**语言**（Language）、**配置存档**（Configuration archive）和 **关于**（About）。升级和重置的命令也在这一页。

## 面板密码与语言

改密码时，填 **当前密码**（Current password）、**新密码**（New password）和 **确认新密码**（Confirm new password），点 **修改密码**（Change password）。其他会话保持登录。忘了密码时在 hub 这台机器上运行 `sudo nhub reset password`，它设一个新密码并登出所有会话。

**语言** 是面板显示所用的语言，两个选项：English 和简体中文。选好点 **应用语言**（Apply language），所有页面改用所选语言。

## 配置归档

![配置存档](/guide/zh/settings_backup.webp)

在 **配置存档** 一节点 **下载备份**（Download backup），浏览器下载一个 `.tar.gz` 存档。存档包含整个 `config/` 目录，凭据以保险库主口令封存在里面。有了这份存档，就能在另一台机器上复原这台 hub。

| 不在存档里的     | 在哪里                 |
| ---------------- | ---------------------- |
| Samba 共享的内容 | 提供共享那台机器的磁盘 |
| Gitea 的仓库     | 跑 Gitea 的那台机器    |
| 容器的卷         | 跑 podman 的那台机器   |
| ZFS 数据集       | 存储池                 |

::: tip
存档本身是普通压缩包，`config/` 里除保险库以外的内容都能直接读到。拿到存档和主口令的人就拿到了全部凭据。
:::

## 恢复

![恢复](/guide/zh/settings_restore.webp)

1. 点 **从文件恢复**（Restore from file），选一个存档。
1. 在 **保险库主口令**（Vault master password）里填这份备份取自的那个保险库的主口令。
1. 点 **恢复**（Restore）。

存档覆盖 `config/` 下的每个文件，配置随即应用。面板重启并刷新本页，用恢复后的密码登录。恢复之后 AI 的订阅账号要重新登录一次，被控端自己重新连上。

| hub 返回的错误码         | 原因                       |
| ------------------------ | -------------------------- |
| `backup_wrong_extension` | 文件不是 `.tar.gz`         |
| `backup_corrupt`         | 校验和对不上，什么都不恢复 |
| `vault_passphrase_wrong` | 口令不对                   |

应用没完成时，页面写出原因，文件已经恢复，在终端里运行 `sudo nhub apply` 再来一次。

## 关于

![关于](/guide/zh/settings_about.webp)

**关于** 列出 **面板**（Panel）和 **地理数据**（Geodata）的版本，以及 **这台机器**（This machine）、**内核**（Kernel）和 **运行时长**（Uptime）。**随附软件**（Carried software）是 hub 下载并分发给受管机器的开源软件，每项带源码链接。被控端的版本在设备抽屉里，客户端的版本在客户端页的列表里。

## 升级

三个包共用一个版本号。升级顺序是 hub、每台被控端、每个客户端：

1. 在 hub 这台机器上安装新的 hub 包，面板在新版本上重启。
1. 对每台被控端，在设备抽屉里点 **重新安装被控端**（Reinstall agent）；没有 SSH 凭据的机器装新包后用新链接重新接入。
1. 在每台电脑上安装新的客户端包，窗口自己重新连上。

客户端比 hub 新时它自己解绑，窗口里写着先升级 hub；升级 hub 后粘一条新链接。`config/` 没有迁移脚本，两个版本的 `config/` 结构不保证一样。

## 重置

| 命令                       | 效果                                                                                            |
| -------------------------- | ----------------------------------------------------------------------------------------------- |
| `sudo nhub reset password` | 设一个新的面板密码，登出所有会话                                                                |
| `sudo nhub unlock`         | 解除多次登录失败后的锁定，同时清掉 fail2ban 的 SSH 封禁                                         |
| `sudo nhub reset all`      | 先交还网络，再把 `config/` 换回示例，删掉每一把密钥和令牌，停下服务；`/etc/neutrino/agent` 保留 |

卸载 hub 包会停下它的单元并删掉它的文件；先在客户端页删掉每个客户端，在抽屉里忘记每台设备，再运行 `nhub reset all`。卸载被控端包停下它的服务。卸载客户端时 `remove` 留下这个人的配置，`purge` 才带走；Windows 的卸载程序显示一个保留配置的选项。
