---
title: 文件
---

# 文件

**文件**（Files）面板把 hub 发布的一个共享挂到家目录下的文件夹，Windows 上挂到一个盘符；卸载在同一个条目上。

## 条目从哪来

条目来自某台机器上启用的 Samba 模块发布的每个共享，来源行写着由某台机器上的 Samba 模块发布；也来自 hub 服务页里手动声明的 SMB 共享，来源行写着手动声明。面板空着时写 **没有发布共享**。

## 配置

![挂载配置](/guide/zh/client_files_config.webp)

1. 在条目上点 **配置**（Config）。
1. 填 **共享用户名**（Share username）和 **共享密码**（Share password），也就是 Samba 页上建的用户。
1. Linux 和 macOS 上填 **挂载路径**（Mount path），默认是家目录下的 `nas/<share>`；Windows 上选 **盘符**（Drive），默认 `N:`。

![Windows 上选盘符](/guide/zh/win_files_drive_letter.webp)

客户端拒绝下列位置，并返回对应的错误码。

| 错误码                        | 原因                       |
| ----------------------------- | -------------------------- |
| `mountpoint_invalid`          | 路径不在家目录下           |
| `mountpoint_not_empty`        | 文件夹非空                 |
| `mountpoint_not_drive_letter` | Windows 上填的不是空闲盘符 |

## 挂载与卸载

![已挂载](/guide/zh/client_files_mounted.webp)

点 **挂载**（Mount）。按钮依次显示 **正在等待客户端…**、**正在挂载…**，然后变成 **卸载**（Unmount）。Windows 上共享以选中的盘符出现在文件资源管理器里。

![Windows 资源管理器里的盘符](/guide/os/win_explorer_mapped.webp)

客户端把用户名和密码保存在你的配置目录下，文件名是 `mount_credentials`，下次点 **挂载** 直接用。保存的登录信息丢了时，客户端返回 `credentials_missing`，重新点 **配置** 填一次。点 **卸载** 摘掉共享，登录信息保留。终端里同一件事：

```bash
nclient service file config <ref> --path ~/nas/media --username alex
nclient service file mount <ref>
nclient service file unmount <ref>
```

## Linux 上的 polkit 助手

Linux 上挂载 CIFS 需要 root，客户端通过 `pkexec` 调用包里自带的挂载助手，polkit 弹一次授权。拒绝授权时客户端返回 `mount_not_authorized`；机器上缺 cifs-utils 时返回 `mount_tooling_missing`。这是客户端唯一的提权点，其余时候它都以你的普通账户运行。
