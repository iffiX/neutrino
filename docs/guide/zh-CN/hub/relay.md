---
title: SSH 中继
---

# 经自己的服务器连到中枢

打开 SSH 中继后，网络外面的客户端和被控端连到你租用或自有服务器上的一个公网端口，服务器把每个连接转给中枢。转发由中枢自己经 SSH 建立，服务器上只需要一个 SSH 账户，中枢用 SSH 密钥或密码登录它。

从客户端到中枢的连接全程加密，客户端照常核对中枢的证书，和在局域网里一样。服务器只转发它读不懂的字节。

开始之前，你需要：

- 一台有公网地址、运行 OpenSSH 的服务器，你能以 root 身份修改它的 SSH 配置。
- 给中枢用的一对 SSH 密钥，比如用 `ssh-keygen -t ed25519 -N '' -f relay_key` 生成的那一对。私钥 `relay_key` 放到 **凭据**（Credentials）页，公钥 `relay_key.pub` 放到服务器上。也可以改用这个账户的密码，作为登录信息放到 **凭据** 页。密钥更稳妥，因为服务器可以把它限定在一个监听端口上。
- 服务商关于流量转发的条款。开端口之前先读一遍，有的服务商限制或禁止转发。

## 设置服务器

以下步骤在服务器上以 root 运行。示例账户是 `relay`，示例公网端口是 `8443`。换成别的端口时，每一步都用同一个端口。

1. 建立中枢登录用的账户：

   ```bash
   useradd --create-home --shell /usr/sbin/nologin relay
   ```

1. 用密钥时，把中枢的公钥写进这个账户的 `authorized_keys`，前面加上只允许一个监听端口的选项。`<public-key>` 换成公钥文件里的那一行：

   ```bash
   mkdir -p /home/relay/.ssh
   echo 'restrict,port-forwarding,permitlisten="8443" <public-key>' >> /home/relay/.ssh/authorized_keys
   chown -R relay:relay /home/relay/.ssh
   chmod 700 /home/relay/.ssh
   chmod 600 /home/relay/.ssh/authorized_keys
   ```

1. 改用密码时，给这个账户设一个密码，并只允许这个账户用密码登录：

   ```bash
   passwd relay
   printf 'Match User relay\n    PasswordAuthentication yes\n' > /etc/ssh/sshd_config.d/20-neutrino-relay-password.conf
   ```

1. 允许转发出来的端口监听在公网地址上，然后重启 SSH 服务。这个设置对整台服务器生效：

   ```bash
   echo 'GatewayPorts clientspecified' > /etc/ssh/sshd_config.d/10-neutrino-relay.conf
   systemctl restart ssh
   ```

1. 在服务商的控制台里放行 TCP 端口 `8443`，服务器上自己跑着防火墙的话也一并放行。中枢还要能连到服务器的 SSH 端口，默认是 22。

Fedora、RHEL 和 Arch 上 SSH 服务名是 `sshd`，重启命令是 `systemctl restart sshd`。

## 让中枢连上去

1. 在 **凭据** 页的 **SSH 密钥**（SSH keys）下，选择 **添加密钥**（Add key），粘贴私钥。用密码时，改在 **登录信息**（Logins）下添加。
1. 在 **外部访问**（Access）页，打开 **SSH 中继**（SSH Relay）卡片上的开关，再选择 **应用虚拟网**（Apply overlays）。卡片下方出现它的设置，状态是 **未配置**。
1. 在 **设置**（Settings）里填 **服务器**（Server）、**SSH 端口**（SSH port）、**账户**（Account）和 **对外端口**（Public port）。在 **凭据**（Credential）里选 **SSH 密钥** 并选刚才的密钥，或选 **密码**（Password）并选那条登录信息。
1. 选择 **应用 SSH 中继**（Apply SSH Relay），保存设置，中继开始运行。

**状态**（Status）先显示 **连接中**（Connecting），一分钟内变成 **已连上**（Connected）。**客户端连接地址**（Address for clients）显示 `https://<server>:<public-port>`，由你填的服务器和对外端口组成。此后每条客户端链接、每台被控端的地址列表都把它列在最后一个。**主机密钥**（Host key）显示 SSH 第一次连接时记下的服务器密钥。

## 看懂状态

转发启动 5 秒后，中枢自己去连这个公网地址，之后每分钟连一次。只有在那里碰到中枢自己的证书，才算 **已连上**。状态下面显示 SSH 写出的最后一行，或者检查没通过的原因。

| 状态                                      | 原因                                                                 | 处理                                                                                               |
| ----------------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **连接中**（Connecting）                  | 转发已启动，第一次检查还没做。                                       | 等一分钟。                                                                                         |
| **未配置**（Not configured）              | 服务器、账户、密钥或登录信息没填，或者已从凭据里删掉。               | 填好设置，选择 **应用 SSH 中继**。                                                                 |
| **保险库已锁定**（Vault locked）          | 这台机器上没有保险库数据密钥的工作副本，中枢打不开存着的密钥或密码。 | 按 [保险库](./credentials.md#保险库) 一节恢复工作副本。                                            |
| **认证失败**（Authentication failed）     | 服务器不接受这把密钥或这个密码。                                     | 检查账户 `authorized_keys` 里的公钥那一行，或者密码和服务器上这个账户的 `PasswordAuthentication`。 |
| **服务器不让对外监听**（Forward refused） | 服务器拒绝了监听，或者别的程序已占着这个端口。                       | 确认 `permitlisten` 里的端口就是对外端口，并在服务器上腾出这个端口。                               |
| **对外端口不通**（Public port closed）    | 转发在运行，但公网地址没有回应，或者回应的是别的证书。               | 检查 `GatewayPorts clientspecified` 和服务商的防火墙。                                             |
| **主机密钥已变**（Host key changed）      | 服务器出示的密钥和记下的不一样。                                     | 如果你换过或重装过服务器，选择 **忘记主机密钥**（Forget host key）。                               |
| **连不上服务器**（Server unreachable）    | SSH 连不到服务器，或者连接断了。                                     | 检查服务器和 SSH 端口，确认服务器在运行。                                                          |

## 换一台服务器

应用不同的服务器或 SSH 端口时，中枢删掉记下的主机密钥，下次连接记下新服务器的密钥。同一地址上重装了系统时，先重新做一遍服务器设置，再在 **主机密钥** 旁选择 **忘记主机密钥**，选 **忘记**（Forget）确认。中枢随即重新连接。

应用新设置时，经 SSH 中继连着的客户端会断开，随后自己重新连上。
