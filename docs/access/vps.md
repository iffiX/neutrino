# SSH 中继

SSH 中继是设备经过你自己的 VPS 连接中枢的外部访问方式。中枢用 SSH 连接 VPS，VPS 把一个公网端口转发到中枢的连接端口。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.5.0" />

所有流量都经过这台 VPS。内容已加密，VPS 无法读取。外部网络的访客也能打开分享链接。

你要有一台有公网地址、运行 OpenSSH 的服务器，并且能以 root 登录。有的服务商限制端口转发，所以你要先阅读服务商的条款。中枢不在 VPS 上运行任何命令，下面的命令都要你自己运行。

## 设置 VPS

下面的命令以 root 运行，示例账户是 `relay`，对外端口是 `8443`。如果你要更换端口，每一步都要更换。

1. 创建一个账户。

   ```bash
   useradd --create-home --shell /usr/sbin/nologin relay
   ```

1. 如果你用密钥登录，在你自己的电脑上生成一对密钥。

   ```bash
   ssh-keygen -t ed25519 -N '' -f neutrino-relay
   ```

1. 回到 VPS，运行下面的命令，把公钥写入 `relay` 账户。`<public-key>` 代表公钥，要换成 `neutrino-relay.pub` 的内容。

   ```bash
   mkdir -p /home/relay/.ssh
   echo 'restrict,port-forwarding,permitlisten="8443" <public-key>' >> /home/relay/.ssh/authorized_keys
   chown -R relay:relay /home/relay/.ssh
   chmod 700 /home/relay/.ssh
   chmod 600 /home/relay/.ssh/authorized_keys
   ```

1. 如果你用密码登录，跳过上面两步，改为给账户设置密码，并打开密码登录。

   ```bash
   passwd relay
   printf 'Match User relay\n    PasswordAuthentication yes\n' > /etc/ssh/sshd_config.d/20-neutrino-relay-password.conf
   ```

1. 让这个端口监听公网地址，再重启 SSH。在 Fedora、RHEL、Arch 上，服务名是 `sshd`。

   ```bash
   echo 'GatewayPorts clientspecified' > /etc/ssh/sshd_config.d/10-neutrino-relay.conf
   systemctl restart ssh
   ```

1. 打开服务商的控制台，放行 TCP `8443`。如果服务器运行着防火墙，也要放行。

## 保存登录凭据

1. 在面板左侧栏点 **凭据**。如果你用密钥登录，按 **添加密钥**。填写 **名称**，在 **私钥** 粘贴 `neutrino-relay` 这个文件的全部内容，再按 **保存密钥**。

   ![凭据页，添加密钥按钮标红](/guide/zh/hub_add_machine_05_credentials.webp "按 添加密钥")
   ![新建密钥的表单，保存密钥按钮标红](/guide/zh/hub_add_machine_06_key_form.webp "填好后按 保存密钥")

1. 如果你用密码登录，改按 **添加登录信息**，保存这个账户的密码，再按 **保存登录信息**。

   ![新建登录信息的表单，保存按钮标红](/guide/zh/hub_add_machine_07_login_form.webp)

## 连接 VPS

1. 在左侧栏点 **外部访问**，打开 **SSH 中继** 卡片的开关，再按 **应用外部访问**。下面会出现 **状态** 和 **设置**，状态显示 **未配置**。

   ![状态一节显示未配置](/guide/zh/access_vps_05_status.webp)

1. 在 **设置** 填写 **服务器**（VPS 的地址）、**SSH 端口**、**账户**（`relay`）和 **对外端口**（`8443`）。在 **凭据** 里选择 **SSH 密钥** 或 **密码**，再选择刚才保存的凭据，然后按 **应用 SSH 中继**。

   ![SSH 中继的设置表单](/guide/zh/access_vps_06_settings.webp "填写这张表")
   ![填好的设置，应用 SSH 中继按钮标红](/guide/zh/access_vps_07_filled.webp "按 应用 SSH 中继")

1. 等待状态变成 **已连上**，一分钟内会有结果。

   <div class="pic-holder">图：状态显示已连上</div>

各状态的含义如下。

| 状态                   | 含义                                             |
| ---------------------- | ------------------------------------------------ |
| **连接中**             | 第一次检查还没有完成，一分钟内有结果             |
| **已连上**             | 从外部网络能连接到这台中枢                       |
| **未配置**             | 服务器、账户或凭据没有填写，或凭据已删除         |
| **保险库已锁定**       | 中枢无法读取密钥或密码                           |
| **认证失败**           | 服务器不接受这个密钥或密码                       |
| **服务器不让对外监听** | 服务器不允许打开这个端口，或端口已有其他程序在用 |
| **对外端口不通**       | 通常是 GatewayPorts 没有打开，或防火墙没有放行   |
| **主机密钥已变**       | 服务器的密钥和中枢记录的不同                     |
| **连不上服务器**       | SSH 无法连接服务器，或连接已断开                 |

## 验证连接

已加入的设备会自动获取这个地址，你不用重新加入。在手机上断开虚拟网，关闭 Wi-Fi。如果中枢这一行显示 **已连接 · SSH 中继**，就说明配置成功。

![中枢那一行显示已连接和 SSH 中继](/guide/zh/access_vps_09_client_connected.webp)

## 后续维护

- **应用设置：** 每次按 **应用 SSH 中继**，通过它连接的客户端都会断开再重新连接。
- **更换服务器：** 填写新的 **服务器** 再应用。
- **同一个地址重装了系统：** 先按上面的步骤重新设置 VPS，再按 **忘记主机密钥**，并在弹窗里选择 **忘记**。
- **不再使用：** 关闭卡片的 **启用**，按 **应用外部访问**。然后删除 VPS 上的 `relay` 账户。再到 `/etc/ssh/sshd_config.d/` 删除两个文件：`10-neutrino-relay.conf`、`20-neutrino-relay-password.conf`。
