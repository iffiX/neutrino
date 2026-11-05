# 故障排查

你可以按屏幕上的提示或错误码，在下面的条目里查到原因和解决办法。

条目按界面分组，每条先写原因，再写解决办法。你可以按 Ctrl+F 搜索屏幕上的文字和错误码。最常见的条目如下。

- [**多次失败后已锁定。**](#面板访问和登录)：运行 `sudo nhub unlock`
- [忘记面板密码](#面板访问和登录)：运行 `sudo nhub reset password`
- [**中枢未响应**](#客户端-中枢一行)：先确认中枢正在运行，再打开一种外部访问，见[外部访问：选择一种方式](/access/ways_in)
- [**中枢密钥不符**](#客户端-中枢一行)：中枢重置过，按 **离开**，再用新链接加入
- [`agent_offline`](#通用错误)：到那个系统上运行 `sudo nagent status`
- [`download_failed`](#系统页-安装、启动、卸载)：检查那个系统和中枢的网络
- [**这个链接已失效。**](#分享链接)：分享已结束，重新生成一条分享链接

![客户端的中枢页，这一行显示中枢密钥不符](/guide/zh/reference_troubleshooting_01_untrusted.webp)

## 通用错误

### `agent_offline`

你要使用的系统现在没有连接中枢。

1. 到那个系统上运行 `sudo nagent status`，查看 `service` 和 `heartbeat` 两行。
1. 如果服务已停止，运行 `sudo nagent start`。
1. 回到面板，等这个系统变成在线，再重新操作。

### `hub_unreachable`

无法连接中枢的连接端口，这个端口默认是 8443。

1. 确认中枢所在的电脑已开机，再运行 `nhub status`，`transport` 这一行应该显示 `running`。
1. 如果你不在中枢所在的局域网，确认 **外部访问** 页打开了一种方式。
1. 到 **网络** 页查看 **开放范围**，你使用的网络要打开。

### `permission_denied`

这个客户端没有这类权限，或者权限不包括那个系统。

到面板 **客户端** 页，按这一行的 **权限**，打开对应的权限，再按 **应用权限**。

### `control_unavailable`

中枢正忙，没有及时响应。这不算失败，程序会自动重试，你不用操作。

### `vault_locked`

这个系统上没有保险库的工作密钥，所以中枢无法读取凭据。

到 **设置** 页恢复一份备份，并填写做这份备份时的保险库口令。

## 面板访问和登录

### 浏览器打不开面板地址

可能的原因是服务没有运行、端口已修改，或者你的设备不在开放范围内。

1. 在中枢所在的电脑上运行 `nhub status`，`web` 这一行应该显示 `running`。
1. 运行 `sudo nhub open --print`，查看面板当前的地址。
1. 进入面板后，到 **网络** 页查看 **端口** 和 **开放范围**。

### 修改面板端口或者切换 HTTPS 后退出了登录

切换会结束所有会话，这是正常现象。在跳转到的新地址重新登录。

### **浏览器里的旧会话挡住了这次登录。**

浏览器还保留着 HTTPS 端口的旧登录记录。按 **清掉旧会话**，再登录。

### **多次失败后已锁定。**

你连续输错了密码。在中枢所在的电脑上运行 `sudo nhub unlock`，SSH 封禁也会一起解除。

### 忘记面板密码

面板密码无法读取，只能更换。

1. 在中枢所在的电脑上运行 `sudo nhub reset password`。
1. 输入 `y`，再输入新密码。所有人都会退出登录，之后用新密码重新登录。

### 忘记保险库口令

用旧口令创建的备份无法打开，运行中的中枢不受影响。

1. 运行 `sudo nhub vault rekey`，设置新口令。
1. 到 **设置** 页下载一份新备份，以后使用这一份。

### `setup_in_progress`

这个中枢的向导已经在运行。等向导结束，或者回到向导页面继续操作。

## 面板的 HTTPS 证书

下面的条目只和面板的 HTTPS 端口有关，和设备连接中枢无关。

### 浏览器提示证书不可信

你还没有在这台设备上安装中枢的证书。到 **设置** 页按 **安装证书**，按步骤操作，再重启浏览器。

### **开启 HTTPS** 是灰色的，显示 **先安装证书并重启浏览器。**

这个浏览器不信任中枢的证书。

1. 到 **设置** 页按 **安装证书**，按步骤操作，再重启浏览器。
1. 用 `http://` 地址打开面板，再按 **开启 HTTPS**。

### 同一台电脑上 Firefox 报警，Chrome 不报警

Firefox 有自己的证书列表，所以你要按 **安装证书** 里 Firefox 的步骤再操作一次。

### 修改设置后每个浏览器都报警

有人按过 **重新生成证书**。这时每台设备都要重新安装证书，再重启浏览器。

### 浏览器提示证书属于其他名称

地址栏的地址不在证书上，证书不包含公网地址。改用证书上列出的名称或者地址打开。

### `https_authority_missing`

这个中枢还没有证书颁发机构，先到 **设置** 页生成。

### `https_reset_over_https`

只能从 HTTP 地址重新生成证书。用 `http://` 地址打开面板，再操作一次。

## 设置页和向导

恢复备份时，错误码可能以 `backup_` 或 `vault_passphrase_` 开头。这表示中枢没有恢复任何内容，你的设置保持不变。这一节最后三个错误码出现在更新中枢时。

### `backup_wrong_extension`

你选择的不是面板导出的备份文件。改选面板下载的备份文件。

### `backup_unrecognized`、`backup_corrupt`

中枢无法识别这个文件，或者文件已经损坏。换一份备份。

### `backup_mode_unavailable`

这个中枢没有备份里的网络模式。换一份备份，或者换对应版本的中枢。

### `vault_passphrase_needed`、`vault_passphrase_wrong`

你没有填写口令，或者口令错误。填写做这份备份时的保险库口令。

### 文件已恢复，弹窗提示应用未完成

文件已经恢复，但生效的某一步失败了。按弹窗显示的原因处理，再运行 `sudo nhub apply`。

### `health_gate_failed`

新版本没有在限定时间内响应，所以中枢已恢复旧版本。查看日志找到原因，再更新一次。

### `disk_space_short`

磁盘空间不足，无法保存新版本。释放空间后再更新。

### `release_major`

新的大版本不能在面板上直接升级。按升级说明手动操作，比如[从 0.5 升级](/hub/upgrade)。

## 凭据页

### `key_is_public`

你粘贴的是公钥。这里要粘贴配对的私钥，也就是不带 `.pub` 的文件。

### `key_passphrase_needed`

这个私钥有口令保护，你要同时填写口令。

## 被控端页

### `unsupported_remote_install`

**用 SSH 添加** 只能安装到 Linux。这时先在那个系统上安装被控端，再改用 **用链接添加**。

### `key_passphrase_not_stored`

**用 SSH 添加** 或 **重新安装** 的弹窗显示 **这个密钥有口令保护，中枢打不开它。请在凭据页带上口令添加这个密钥。** 中枢存着这个密钥，但没有它的口令。到 **凭据** 页按 **添加密钥**，粘贴私钥并填写 **密钥口令**，再在弹窗里选择这条新密钥。

### `install_credentials_invalid`

那个系统不接受这份登录信息。核对用户名、密钥或者密码。

### `agent_package_missing`

中枢没有这个平台的被控端安装包。到那个系统上用安装脚本安装。

### `transport_key_missing`

连接端口还没有就绪。稍后再生成链接。

### `wol_no_mac`

这个系统没有上报过 MAC 地址，所以无法唤醒。让它上线一次后，以后就能唤醒。

### `reinstall_failed`、`update_failed`

被控端重新安装或者更新失败。到那个系统上重新运行安装脚本。

## 外部访问页

### `overlay_subnet_overlap`

虚拟网的网段和另一个虚拟网重叠，或者和这个系统的网络重叠。修改 EasyTier 的地址，或者到 **网络** 页修改局域网地址。

### `overlay_route_overlap`

一条虚拟网路由和这个系统的网络重叠。到管理这个虚拟网的控制台修改这条路由。

### `overlay_default_route_refused`

控制台向中枢下发了一条默认路由，中枢已经删除它，始终从自己的上行网络访问互联网。你也要到控制台删除这条路由。

### `direct_host_invalid`

**公网地址** 既不是 IP 地址，也不是主机名。改正后按 **应用直连**。

### `easytier_config_server_invalid`

控制台地址错误。从 EasyTier 控制台重新复制。

### `easytier_invalid`

手动模式下没有填写引导节点，至少要填写一个。

### NetBird 显示 **未加入**

中枢没有 NetBird 身份，或者登录已经失效。用新的 setup key 重新加入。

### NetBird 显示 **管理面不可达。**

中枢无法连接 NetBird 的管理面。检查这个系统的上行网络和 DNS。

### NetBird 显示 **未运行**

NetBird 没有运行。关闭卡片再打开，然后按 **应用外部访问**。

### EasyTier 显示 **还没有系统加入。**

另一个系统的网络名或者密码不一致。重新复制命令，到那个系统上再运行一次。

### 无法通过虚拟网连接中枢

**开放范围** 里没有打开虚拟网。到 **网络** 页打开它，再按 **应用开放范围**。

### SSH 中继显示 **连接中**

第一次检查还没有完成，一分钟后再查看。

### SSH 中继显示 **未配置**

服务器、账户或者凭据没有填写。填写后按 **应用 SSH 中继**。

### **认证失败**

服务器不接受这个密钥或者这个密码。核对服务器上的 `authorized_keys`，或者核对密码。

### **服务器不让对外监听**

服务器拒绝监听，或者这个端口已有其他程序在使用。确认 `permitlisten` 的设置，再释放这个端口。

### **对外端口不通**

转发在运行，但公网地址没有响应。使用 SSH 中继时，检查 `GatewayPorts` 和防火墙。使用 frp 时，到服务商那里查询。

### **主机密钥已变**

服务器提供的密钥已更改。确认你重新安装过服务器后，再按 **忘记主机密钥**。如果你没有重新安装过，不要继续操作。

### **连不上服务器**

SSH 无法连接服务器。检查服务器是否正在运行，SSH 端口是否填写正确。

### **保险库已锁定**

这和上面的 `vault_locked` 相同，到 **设置** 页恢复一份备份。

### `frpc_missing`

中枢的安装包缺少 frpc。在原来的系统上重新安装中枢。

### `frp_credential_refused`

服务商不接受这个登录信息。重新复制访问密钥，或者重新登录。

### `frp_not_signed_in`、**未登录**

你还没有登录服务商，或者登录已过期。重新登录，见 [SakuraFrp](/access/sakurafrp) 和 [OpenFrp](/access/openfrp)。

### `frp_tunnel_unknown`

选中的隧道已经不在账户的列表里。刷新列表，选择一条列出的隧道。

### `frp_vendor_unreachable`

中枢没有从服务商获取到可用的回复。检查中枢的上行网络和 DNS，再试一次。

### `frp_config_unusable`

服务商返回的配置里没有这条隧道。到服务商的控制台查询，再刷新。

### **已启用，未连接**

你已经登录，但还没有选择隧道。选择一行，再按应用按钮。

### **本机端口已有程序在用**

其他程序占用了本机端口，SakuraFrp 使用 18443，OpenFrp 使用 18444。停止那个程序，关闭卡片再打开。

### 卡片上的其他红字

服务商的隧道或者服务器出现问题。查看 [SakuraFrp](/access/sakurafrp) 或者 [OpenFrp](/access/openfrp)。

## 网络页

### `network_invalid`

**开放范围** 里打开的网口，角色是 **停用**。修改它的角色，或者关闭它的开放。

### `port_out_of_range`

端口不在允许的范围内。改成提示显示的范围。

### `port_already_in_use`

页面显示 **已被占用**，其他程序正在使用这个端口。更换端口，或者停止那个程序。

### `lan_subnet_overlaps`

两个网络的网段重叠。修改其中一个。

### `dhcp_range_invalid`

DHCP 范围错误。改成这个网段里的范围。

### `interface_not_ap_capable`

这个无线网卡只能加入其他网络。更换网卡，或者用它加入其他网络。

### `wifi_join_failed`

这个系统无法接入无线网络。核对网络名和密码。

### `resolver_required`、`no_exit_node_enabled`、`xray_refused`

这三个错误码只在出口设置里出现。`resolver_required` 表示没有远程解析器，`no_exit_node_enabled` 表示没有启用任何出口，`xray_refused` 后面显示 xray 的原始输出。

## 系统页：安装、启动、卸载

处理原因后，再按一次原来的按钮就会重试。

### `download_failed`

所有下载源都无法提供这个文件，后面列出了每个下载源和失败的原因。

1. 检查这个系统和中枢能否访问互联网。
1. 网络恢复后，再按一次刚才的按钮。

### `no_platform_build`、`module_architecture_unsupported`

这个系统或者架构不能运行这个应用。查看[支持的平台](/reference/platforms)。

### `install_failed`

安装失败，后面显示原因。按原因处理后，再按 **安装**。

### `install_unconfirmed`

安装结束，但找不到这个软件。再按一次 **安装**。

### `uninstall_unconfirmed`

卸载结束，但软件仍然存在。再按一次 **卸载**。

### `module_digest_mismatch`

下载的文件和校验值不符。再按一次。如果仍然失败，更换网络后再试。

### `package_manager_busy`

其他程序占用系统的包管理器已有 5 分钟，比如系统在自动更新。等更新结束后再按。

### `module_needed`

它依赖的应用没有运行，提示会说明是哪一个。如果提示要按 **安装**，就按 **安装**。如果提示要按 **启动**，就按 **启动**。两个应用会一起重试。

### `containers_not_applied`

**容器** 无法运行这个应用的容器。先处理 **容器** 标签上的错误，再按 **启动**。

### `module_in_use`

还有应用依赖它，提示会说明是哪一个。先卸载那个应用，再卸载它。

### `state_not_settled`

这个应用正在应用配置。稍后再按。

### `version_switch_failed`

新版本启动失败，已经恢复原来的版本。查看后面显示的原因，或者继续使用原来的版本。

### `version_locked`

这个应用的版本不能选择，它跟随系统或者被控端。你不用处理。

### `apply_failed`

这个系统无法应用这份配置，后面显示原因。按原因处理后，再按一次。

### 灰色的卡片

这个系统不能运行这个应用。查看[支持的平台](/reference/platforms)。

### **在等系统的包管理器空出来** 这类等待提示

这不是错误，操作正在排队。等待操作完成。

## 系统页：账户

### `account_unknown`

系统上没有这个账户。更换账户，或者先在系统上创建它。

### `account_invalid`

这个名称在这个应用里不能使用。更换账户。

### `account_duplicate`

这个账户已经添加过，不用再添加。

### `account_no_profile`

这个 Windows 账户从未登录过，而这个应用要使用它的主目录。用这个账户在电脑上登录一次，再按一次原来的按钮。容器不受这条限制。

### `credential_missing`

这个 Windows 账户没有保存密码。在 **可用账户** 里按这一行的 **编辑**，填写 **密码**。

### `credential_invalid`

Windows 不接受这个密码，比如密码已修改。在弹窗或者账户表单里填写正确的密码。

### `account_logon_refused`

这个账户已锁定、已停用或者密码已过期，后面显示 Windows 的原始提示。到 Windows 里处理这个账户。

## 系统页：各个应用

### `page_silent`

容器都在运行，但应用的页面 5 分钟没有响应。检查这个端口上还有什么程序在监听。

### `gitea_git_missing`

Mac 或者 Windows 上没有 git。在 Mac 上安装开发者工具或者 Homebrew 的 git，在 Windows 上安装 Git for Windows，然后再按 **安装**。

### `terms_not_accepted`

你还没有在这个系统上接受微软的条款。到 **VS Code** 标签按 **打开并接受条款**。

### `cloudcli_npm_install_failed`

npm 安装失败，后面显示原因。按原因处理后，再按 **应用 CloudCLI**。

### `cloudcli_native_module_failed`

一个预编译文件下载失败。确认这个系统能访问 GitHub，再按 **应用 CloudCLI**。

### `cloudcli_install_out_of_memory`

npm 安装时内存耗尽。关闭其他程序释放内存，再按 **应用 CloudCLI**。

### `cloudcli_register_failed`

这个 CloudCLI 已经有一个密码不同的管理员。中枢重置或者重新安装后，CloudCLI 会自动使用新的数据库，旧文件会保留。

### `cloudcli_port_taken`、`code_server_port_taken`、`codeg_port_taken`、`siyuan_port_taken`

页面显示 **已被占用**，其他程序正在使用这个端口。停止那个程序，再按一次。

### `ayakaleaf_setup_failed`

第一次启动停在某一步，后面显示是哪一步。按原因处理后，再按 **安装**。

### `ayakaleaf_guest_failed`

访客账户创建失败，所以分享显示 **失败**。下次应用时会自动重试，你可以查看后面的原因。

### `copy_runs_first`、`copy_unreached`

这个账户的 shell 先运行了另一份同名程序，或者找不到模块安装的副本。按这一行的 **让本模块安装的副本优先**，见 [Claude Code](/deploy/claude_code#注意)。

### `copy_in_system_path`

在 Windows 上，同名程序在系统 PATH 里，模块安装的副本排不到它前面，所以这个账户不能勾选。先卸载那一份，或者把它的目录从系统 PATH 里删除，再勾选这个账户。

### `share_name_taken`

这个系统已经有同名的共享。添加时遇到它，给新共享换一个名称。如果同名的是你自己创建的共享，只有微子的这个共享不上线，其他共享照常。给微子的共享换一个名称，或者修改你自己的共享。

### `share_path_missing`

共享的文件夹不存在，或者被控端读不到它。添加或修改共享时遇到它，表单什么都不保存，改选一个存在的文件夹。如果共享添加以后文件夹才不见，共享会保留，暂时不上线。文件夹回来后，共享会自动上线。如果你不再需要这个共享，按 **移除**，或者取消勾选这个账户。

### `share_path_link`

共享的文件夹是一个链接，或者路径上有链接。改选链接指向的那个文件夹。

### `share_not_served`

在 Windows 和 macOS 上，系统的 SMB 服务拒绝了这个共享，后面是系统给出的原因。其他共享照常。按原因处理后，再按 **应用文件共享**。

### `user_name_taken`

这个系统已有同名账户，这个账户不是文件共享创建的。修改那个账户。

### `share_users_unknown`

一个文件夹共享没有勾选账户，所以中枢没有提供它。给它勾选账户，或者移除它。

### `samba_domain_member`

这个系统的 Samba 是域成员，这样的系统不能使用文件共享。

### `samba_hosts_allow_no_loopback`、`samba_interfaces_no_loopback`

Samba 配置排除了本机。在 Samba 配置里添加 `127.0.0.1` 和 `lo`。

### `reboot_required`

安装 WSL 要重启电脑。按 **立即重启**，重启后会自动继续安装。

### `windows_feature_failed`

Windows 无法打开 WSL 需要的功能。确认内部版本是 19041 及以上，再按 **安装**。

### `podman_install_failed`

WSL 或者 Podman 的安装包返回了错误。查询这个退出码，再按 **安装**。

### `machine_account_missing`

你还没有选择运行容器的账户。到 **运行设置** 选择 **账户**。

### `machine_image_missing`

虚拟机映像已丢失。按 **卸载**，再按 **安装**。

### `machine_init_failed`、`machine_set_failed`

Podman 无法创建或者修改虚拟机。确认电脑固件里已打开虚拟化，再查看后面的输出。

### `machine_unreachable`

虚拟机没有响应。刚开机时等待 30 秒。如果一直没有响应，按 **启动**。

### `machine_cpus_invalid`、`machine_memory_invalid`

填写的数字超过了电脑实际的数量。改成提示显示的上限以内。

### `machine_disk_shrink`、`machine_disk_invalid`

磁盘上限小于当前大小，或者在 Windows 上填写了 0。填写当前大小或者更大的值。

### `volume_not_shared`

虚拟机无法访问卷的文件夹。在 Windows 上使用固定磁盘，在 macOS 上使用 `/Users` 下的文件夹，或者改用命名卷。

### `udp_not_forwarded`

你在 Windows 上发布了 UDP 端口，Windows 上不支持。改用 TCP 发布。

### `container_name_invalid`、`container_name_duplicate`、`container_name_reserved`

**名称** 不合规、重名，或者以 `neutrino_` 开头。更换 **名称**。

### `container_hub_owned`

这个容器由应用运行，你要到那个应用的标签里修改。

### `image_invalid`

**镜像标签** 为空，或者含有空格。填写正确的标签，比如 `redis:7`。

### `port_mapping_invalid`

**端口** 格式错误。写成 `8080:80`，UDP 在后面加 `/udp`。

### `service_invalid`、`service_protocol_none`

**服务** 里的端口错误，或者 TCP、UDP 都没有勾选。每个端口保留一行，并勾选协议。

### `volume_invalid`、`environment_invalid`、`command_invalid`

**卷**、**环境变量** 或者 **命令（可选）** 格式错误。按提示修改。

### `mirror_invalid`

**镜像源** 不是主机名。只填写主机名，不带 `http://`。

### `rdp_takeover_failed`、`rdp_restore_failed`

启动或者恢复 RustDesk 的某一步失败。按后面的原因处理，再按 **应用远程桌面**。

### `terminal_account_missing`

这个系统的终端没有启用账户。到 **终端** 标签启用一个账户。

### `key_missing`

SSH 服务器没有中枢生成的密钥。再按一次 **应用 SSH 服务器**。

## AI

手机上没有 AI 页。

### `gateway_not_serving`、`gateway_no_models`

AI 网关还没有可用的模型。先到 **AI** 页添加提供方，或者登录订阅。

### `gateway_unreachable`

网关没有响应。查看 **AI** 页的日志，在 Linux 上也可以运行下面的命令。

```bash
systemctl status neutrino_hub_cliproxyapi
```

### `gateway_settings_refused`

网关不接受这些设置。按后面显示的原因修改。

### `login_expired`

这次登录超时。重新按 **登录**，尽快完成。

### `switch_failed`

cc-switch 无法把工具指向网关。按后面的原因处理，关闭开关再打开。

### `no_exit_hub`

打开开关时，那个中枢没有连接。等中枢那一行显示 **已连接**。

### `no_endpoint`

中枢还没有给这个客户端分配密钥。到 **AI** 页吊销它的密钥，中枢会重新分配。

### `ai_tools_managed`

这台电脑安装了被控端，由中枢设置。到它的系统页面，在账户表单里设置。

### 工具无法连接

工具连接的是客户端的转发。客户端关闭后转发也关闭，所以你要保持客户端运行。

## 分享链接

### **这个链接不完整。**

复制时链接缺了一部分。重新复制完整的链接。

### **这个链接已失效。**

页面打开期间分享已结束。重新生成一条分享链接。

### **中枢已离线。**

无法连接中枢所在的电脑，或者分享已经结束。页面会自动重试。如果一直显示这个提示，重新生成一条分享链接。

### **应用暂时打不开。**

应用所在的系统已离线，或者应用已停止。恢复后页面会自动打开应用。

### **线路较慢，仍在连接…**

线路较慢，页面仍在连接。如果 30 秒后仍未连接成功，页面显示 **中枢已离线。**

### 外部网络打不开，局域网能打开

只打开了 EasyTier 或者 NetBird，或者生成链接时还没有公网地址。

1. 打开直连、SakuraFrp、OpenFrp 或者 SSH 中继中的一种。
1. 重新生成一条分享链接，见[应用分享](/share/web_share)。

### `web_share_entry_invalid`

这个应用的页面不能分享。选择列表里的应用。

### `web_share_site_invalid`

站点不是 `https://` 地址。改成以 `https://` 开头的地址。

### `web_share_unknown`

这个分享已经不存在。刷新页面。

## 客户端：中枢一行

带倒计时的状态，倒计时到 0 时客户端会自动重新连接。

### 一直在 **连接中…** 和 **中枢未响应** 之间切换

链接里的地址都无法连接，比如手机不在中枢所在的局域网。回到中枢所在的网络，或者连接虚拟网。

### **中枢未响应 · 5 秒后重试**

这一轮尝试的地址都没有连接成功。确认中枢正在运行。如果你不在中枢所在的局域网，确认打开了一种外部访问，见[外部访问：选择一种方式](/access/ways_in)。

### **中枢未上虚拟网 · 5 秒后重试**

本机在虚拟网里，但无法通过虚拟网连接中枢。到面板查看这个虚拟网的状态和 **开放范围**。

### **无网络**

本机没有网络。连接网络后会恢复。

### **中枢密钥不符 · 60 秒后重试**（`hub_untrusted`）

中枢重置或者重新安装过，密钥已更改。

1. 在这一行按 **离开**。
1. 到面板 **客户端** 页生成新链接，重新加入。

### **中枢暂停接纳 · 60 秒后重试**（`admission_paused`）

失败的加入过多，中枢暂时不接受新的加入。倒计时到 0 时，客户端会自动重新加入。

### **中枢没有本机的记录**（`binding_unknown`）

中枢的 **客户端** 页上没有这个客户端。按 **离开**，再用新链接加入。

### **版本太旧 · 更新客户端**（`protocol_too_old`）

客户端比中枢旧。安装新版客户端，已加入的中枢都会保留。

### **版本太旧**（`protocol_too_new`）

客户端比中枢新，你要升级中枢。

### **加入被拒**（`ticket_spent`、`role_mismatch`、`hub_key_missing`）

链接已过期、已使用或者不是客户端链接，或者绑定来自 0.5。按 **离开**，再用新链接加入。

### **已被替换 · 重新连接**（`replaced`）

另一个客户端用同一个绑定连接了中枢。按 **重新连接**。

### **已停用**（`client_disabled`）

屏幕显示 **中枢已把本机停用。** 你在面板上停用了这台设备。到面板的 **客户端** 页按 **启用**。

### `channel_full`

中枢的连接数已达到上限。这不算失败，程序会自动重试。

## 客户端：加入框

### `link_not_for_client`

你粘贴的是被控端的链接。到面板 **客户端** 页生成一条客户端链接。

### `link_unreadable`、`link_incomplete`

链接没有粘贴完整。从面板复制完整的链接。

## 客户端：虚拟网一行

失败后客户端不会自动重试，你处理后再按 **连接**。

### `overlay_join_failed`

加入失败，常见原因是 setup key 只能使用一次。创建一个可以重复使用的 setup key，到 **NetBird** 卡片按 **替换**。

### `overlay_other_network`

本机已经在另一个虚拟网里。先断开那个虚拟网。

### `overlay_no_address`

90 秒内没有获取到地址。确认本机能访问互联网，再按 **连接**。

### `overlay_daemon_down`、`bundle_missing`

安装不完整。重新安装客户端。

### `overlay_console_invalid`

中枢提供的 EasyTier 控制台地址不可用。到 **EasyTier** 卡片上核对。

### `overlay_withdrawn`

中枢不再提供这个网络。到 **外部访问** 页重新打开它。

### `overlay_not_authorized`

你没有在手机上选择允许，或者在系统设置里撤销了授权。到系统设置里允许，再按 **连接**。

### 一直显示 **连接中…**，提示本机已登记到控制台

EasyTier 控制台还没有把它挂载到网络。到控制台把它挂载到中枢所在的网络。

## 客户端：程序本身

### `client_not_running`

客户端没有运行。运行 `nclient gui`。

### `client_held`

这台电脑上其他账户的客户端正在运行。让那个账户从托盘退出。

### `root_refused`

你用 `sudo` 启动了客户端。改用你自己的账户启动。

### `gui_webkitgtk_missing`、`gui_webview2_missing`

缺少窗口需要的组件。安装提示里列出的软件包。

### `transport_unavailable`

传输程序没有运行。退出客户端再打开。如果仍然失败，重新安装客户端。

## 客户端：应用页

### **当前无法访问**

提供它的系统或者服务现在无法连接。让它重新上线。

### `connect_failed`

那个服务没有响应。确认服务正在运行。如果是声明的应用，再核对地址。

### `port_not_published`

那个系统不再发布这个端口。到它的页面重新启动应用。

### `service_unknown`

中枢不再发布这一项。刷新客户端。

### `connect_limit`

这个客户端打开的连接过多。关闭不需要的转发或者程序。

### `port_taken`

页面显示 **已被占用**，其他程序正在使用这个本机端口。按 **配置** 更换端口。

### `app_in_use`

应用正在使用时不能修改本机端口。先按 **停止**。

### `app_not_in_use`

你还没有按 **使用**。先按 **使用**。

### `web_token_missing`

中枢没有提供这个网页的令牌。再按一次 **打开**。

## 客户端：文件页

### `mountpoint_invalid`

路径不在你的主目录下。填写主目录下的文件夹。

### `mountpoint_not_drive_letter`

你在 Windows 上选择的不是空闲盘符。选择一个空闲盘符。

### `mountpoint_not_empty`

这个文件夹里有文件。更换一个空文件夹。

### `mountpoint_in_use`

另一个共享已经设置为挂载到这里。更换位置。

### `mount_not_authorized`

登录框已关闭，或者客户端是从 ssh 这类非桌面会话启动的。再按一次 **挂载**，在 Linux 上要从桌面启动客户端。

### `mount_timed_out`

系统十分钟内没有完成挂载。再按一次 **挂载**。

### `mount_tooling_missing`

缺少挂载工具。重新安装客户端的软件包。

### `pkexec_missing`

Linux 上没有 `pkexec`。用包管理器安装它。

### `credentials_missing`

保存的登录信息已丢失。按 **配置** 重新填写。

### `share_login_rejected`

用户名或者密码错误。到 **配置** 里重新填写。

### `share_hub_login_rejected`

屏幕显示 **中枢给的登录被拒了，请在面板检查这个系统的文件共享。** 这时到面板打开这个系统的 **文件共享** 标签，按 **配置**，再按 **应用文件共享**。

### `share_access_denied`

屏幕显示 **登录被拒绝：密码不对，或者这个账号不能用这个共享。** 这时核对密码和这个共享勾选的账户。

### `share_not_found`

主机上没有这个共享。到面板确认共享是否存在。

### `share_unreachable`

无法连接主机，电脑和手机都可能出现。先查看中枢一行，再让那个系统上线。

### `share_session_conflict`

Windows 已经用另一个账号连接这台服务器。先断开那个连接。

### `files_adapter_unavailable`

Windows 的文件适配器服务缺失或者已停止。运行 `sc query NeutrinoClientFiles`。如果服务缺失，重新安装客户端。

### `files_adapter_in_use`

屏幕显示 **文件适配器正被这台电脑上的另一个账户使用**。让那个账户退出客户端。

## 客户端：终端页

### **这个系统的终端没有启用的账户。**

你还没有启用账户。到它的 **终端** 标签启用一个账户。

### `account_not_enabled`

这个账户没有启用。到 **终端** 标签勾选它。

### `session_not_owned`

这个会话是在其他位置打开的。让对方打开 **共享**，或者新开一个终端。

### `session_unknown`

会话已经结束，比如被控端重启过。新开一个终端。

### `unknown_terminal`

中枢没有提供那个系统的终端。选择列表里的系统。

### **中枢已把本机停用，这个终端已结束。**

你在面板上停用了这台设备，普通终端随之结束。到面板的 **客户端** 页按 **启用**，再新开一个终端。打开了 **持久** 或 **共享** 的终端会显示 **已断开，正在等待中枢**，启用后自动接回。

### **中枢没有本机的记录，这个终端已结束。**

中枢已经没有这台设备的记录，比如设备已删除。用新链接重新加入中枢，见[加入中枢](/access/join)。如果显示 **这个终端仍在它所在的系统上运行**，说明这是持久或共享的终端，重新加入后可以再次连接这个会话。

### **已断开，这个终端已结束。**

网络断开，普通终端随之结束。恢复连接后新开一个终端。如果要在断网时保留会话，打开终端下面的 **持久**。

### **已断开，正在等待中枢**

持久或共享的终端在等待重新连接，命令仍在系统上运行。连接恢复后，客户端会自动接回原来的 shell，你不需要操作。

### `shell_program_unusable`

这个程序不存在，或者不能运行。更换程序，或者把 **默认 shell** 留空。

## 客户端：远程桌面页

### `rdp_viewer_open`

这个桌面已经打开了一个查看器。关闭那个窗口，再按 **连接**。

### `rdp_not_shared`

那个系统停止了共享。到它的 **远程桌面** 标签打开共享。

### `rdp_nobody_seated`

屏幕前没有人登录。在那台电脑上登录桌面。

### `rdp_screen_not_allowed`

Wayland 还没有允许屏幕共享。到屏幕前允许一次。

### `rdp_permissions_needed`

你还没有在 Mac 上给 RustDesk 权限。打开“屏幕录制”和“辅助功能”。

### `rdp_no_desktop`

这个会话没有屏幕。在有桌面的会话里打开。

### `rdp_launch_failed`

查看器启动失败。按后面的原因处理。如果仍然失败，重新安装客户端。

### `rdp_no_address`

那个系统没有发布可连接的地址。到它的 **远程桌面** 标签再按一次 **应用远程桌面**。

## 被控端所在的系统

`nagent status` 显示的内容见 [nagent 命令](/reference/nagent)。

### `hub_key_missing`

这份绑定来自 0.5。用新链接运行 `sudo nagent join`，见[从 0.5 升级](/hub/upgrade)。

### `binding_unknown`、`hub_untrusted`

中枢没有这个系统的记录，或者中枢的密钥已更改。

1. 到面板 **被控端** 页按 **用链接添加**，生成新链接。
1. 在这个系统上运行 `sudo nagent join '<链接>'`。

### `replaced`

另一个会话占用了这份绑定。重启服务，或者用新链接加入。

## 日志位置

上面没有列出的问题，可以查看日志。

| 日志             | Linux                                                   | macOS                                       | Windows                                       |
| ---------------- | ------------------------------------------------------- | ------------------------------------------- | --------------------------------------------- |
| 中枢             | `journalctl -u neutrino_hub_web -n 200`，其他服务同样写 | `/Library/Logs/Neutrino/hub/`               | `C:\ProgramData\Neutrino\hub\log\`            |
| 被控端           | `journalctl -u neutrino_agent -n 200`                   | `/Library/Logs/Neutrino/agent/agent.log`    | `C:\ProgramData\Neutrino\agent\log\agent.log` |
| 客户端           | `~/.config/neutrino/client/client.log`                  | `~/Library/Logs/Neutrino/client/client.log` | `%LOCALAPPDATA%\Neutrino\client\client.log`   |
| 第一次设置的过程 | `/var/log/neutrino/hub/setup.log`                       |                                             |                                               |

AI 网关的日志也在面板 **AI** 页。
