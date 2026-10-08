---
title: 用自己的 VPS 中继连回家
---

# 用自己的 VPS 中继连回家

有一台公网 VPS 时，中枢能用 SSH 登录它，建一条反向转发，把 VPS 上的一个公网端口接到家里中枢的 8443。客户端在外面连这个公网端口，就到了中枢。

开始之前，准备好这几样：

- 中枢已经装好，手机或笔记本已经加入，见[第零步](../quick-start.md)。
- 一台有公网地址、运行 OpenSSH 的服务器，你能以 root 改它的 SSH 配置。
- 服务商允许端口转发。有的服务商限制或禁止转发，开端口之前先读它的条款。

## 准备一对 SSH 密钥

1. 在你自己的电脑上生成一对密钥：

   ```bash
   ssh-keygen -t ed25519 -N '' -f neutrino-relay
   ```

   `neutrino-relay` 是私钥，`neutrino-relay.pub` 是公钥。

1. 在面板的 **凭据** 页，**SSH 密钥** 下选择 **添加密钥**。
1. 在 **私钥** 里粘贴 `neutrino-relay` 的内容，选择 **保存密钥**。

想用服务器账户的密码登录时，跳过上面三步。改在 **登录信息** 下选择 **添加登录信息**，存下一节给账户设的密码。

## 设置服务器

下面的命令在服务器上以 root 运行。示例账户是 `relay`，示例公网端口是 `8443`。换成别的端口时，每一步都用同一个端口。

1. 建一个中枢登录用的账户：

   ```bash
   useradd --create-home --shell /usr/sbin/nologin relay
   ```

1. 用密钥时，把公钥写进这个账户的 `authorized_keys`，前面加上只允许一个监听端口的选项。`<public-key>` 是 `neutrino-relay.pub` 里的那一行，在生成密钥的电脑上用 `cat neutrino-relay.pub` 打印出来复制：

   ```bash
   mkdir -p /home/relay/.ssh
   echo 'restrict,port-forwarding,permitlisten="8443" <public-key>' >> /home/relay/.ssh/authorized_keys
   chown -R relay:relay /home/relay/.ssh
   chmod 700 /home/relay/.ssh
   chmod 600 /home/relay/.ssh/authorized_keys
   ```

1. 用密码时，给这个账户设一个密码，并为它打开密码登录：

   ```bash
   passwd relay
   printf 'Match User relay\n    PasswordAuthentication yes\n' > /etc/ssh/sshd_config.d/20-neutrino-relay-password.conf
   ```

1. 让转发出来的端口监听在公网地址上，再重启 SSH 服务。这项设置对整台服务器生效：

   ```bash
   echo 'GatewayPorts clientspecified' > /etc/ssh/sshd_config.d/10-neutrino-relay.conf
   systemctl restart ssh
   ```

1. 在服务商的控制台里放行 TCP 端口 `8443`。服务器上自己跑着防火墙时，也一并放行。中枢还要能连到服务器的 SSH 端口，默认是 22。

第 4 步按 Debian 和 Ubuntu 写，SSH 服务名是 `ssh`。Fedora、RHEL 和 Arch 上服务名是 `sshd`，重启命令写成 `systemctl restart sshd`。

## 让中枢连上去

1. 在面板的 **外部访问** 页，打开 **SSH 中继** 卡片上的 **启用** 开关。
1. 选择 **应用外部访问**。
1. 在卡片下方的 **设置** 里，填 **服务器**、**SSH 端口**、**账户** 和 **对外端口**。
1. 在 **凭据** 里选 **SSH 密钥** 和刚存的密钥；用密码时，选 **密码** 和那条登录信息。
1. 选择 **应用 SSH 中继**。

**状态** 先显示 **连接中**，一分钟内变成 **已连上**。**客户端连接地址** 显示 `https://<server>:<public-port>`，其中 `<server>` 是你填的服务器，`<public-port>` 是对外端口。

![SSH 中继的设置，状态已连上，下面是客户端连接地址](/guide/zh/overlay_relay_settings.webp)

状态停在别的字上时，见[故障排查](../reference/troubleshooting.md#外部访问)。

## 让客户端用上这个地址

已加入的客户端和被控端随状态拿到这个地址，不用重新加入。之后新建的客户端链接也带上它。

在手机上验证：

1. 开着 EasyTier 或 NetBird 时，在手机中枢那一行下面的 **虚拟网** 一行选择 **断开**。
1. 关掉手机的 Wi-Fi，改用移动网络。
1. 打开客户端，看中枢那一行。

这一行显示 **已连接 · SSH 中继**。虚拟网连着时，客户端优先用它，这一行显示的是 NetBird 或 EasyTier。

不再用中继时，在 **外部访问** 页关掉 **SSH 中继** 的 **启用**，选择 **应用外部访问**。服务器上删掉 `relay` 账户和 `/etc/ssh/sshd_config.d/` 下这一页加的文件，再重启 SSH 服务。
