---
title: 通道
---

# 通道

通道是 hub 和它管理的每台机器之间的那一条 WebSocket，微子 0.5.0 起的协议号是 3。用通道的有两种角色：`agent` 是受管机器上的被控端服务，`client` 是一个人的桌面客户端或手机应用。仓库之外写的程序要接入，用的就是这一页的全部词汇：链接、证书指纹、两个 HTTP 端点、帧、流、两种角色各自交换的文档，以及错误码。

## 端口与证书指纹

通道在被控端端口上，默认 8443，这个端口只通过 TLS 提供 `/api/channel`。面板端口是另一个；面板开不开 HTTPS，通道都不变。

被控端端口上的证书是自签名的，有效期十年，所以它的指纹就是 hub 的全部身份。

| 规则                     | 值                                                  |
| ------------------------ | --------------------------------------------------- |
| 固定的是什么             | 证书 DER 编码的 SHA-256 摘要，64 个小写十六进制字符 |
| 什么时候校验             | 每次 TLS 握手之后，任何请求字节发出之前             |
| 证书链和主机名校验       | 关闭                                                |
| TLS 最低版本             | 1.2                                                 |
| 链接里的某个地址指纹不符 | 关闭套接字，终止加入，不再试下一个地址              |
| `https` 地址没有配指纹   | 不连接                                              |

## 加入链接

客户端的链接在 hub 的**客户端**（Clients）页生成，被控端的链接在**设备**（Devices）页生成。客户端链接的生成步骤见[客户端](../hub/clients.md)。被控端链接的生成步骤见[设备](../hub/devices.md)。链接的形式是 `neutrino://enroll/<payload>`，其中 payload 是一个 JSON 对象的 base64url 编码：

```json
{
  "urls": ["https://192.168.100.1:8443", "https://100.92.14.7:8443"],
  "token": "sB1nYt9Qk2_pL0wV7xR4cZ8f",
  "fp": "<sha256-hex>",
  "role": "client",
  "overlays": [
    {
      "provider": "netbird",
      "setup_key": "...",
      "management_url": "",
      "fqdn": "hub.netbird.cloud"
    }
  ]
}
```

| 字段       | 内容                                                                                                                                     |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `urls`     | hub 在被控端端口上开放的每个地址；其中一个在加入方所在的网络里，程序按顺序逐个尝试                                                       |
| `token`    | 加入凭证，五分钟内有效，只能用一次                                                                                                       |
| `fp`       | 要固定的指纹                                                                                                                             |
| `role`     | `client` 或 `agent`                                                                                                                      |
| `overlays` | 只在客户端链接里有：和客户端状态里的 `overlays` 是同一个列表，按生成链接时的默认权限取；默认权限不含 `overlay`，或没有可用的虚拟网时为空 |

客户端拿到被控端链接时返回 `link_not_for_client`，被控端拿到客户端链接时返回 `link_not_for_agent`；两个错误码的 `params` 都写明链接的 `role`。base64url 的字母表里没有 shell 会拆开、URL 要转义的字符，所以链接不加引号也能直接粘贴。

## 加入与离开

| 端点                      | 请求体                                                           | 返回                                                                                   |
| ------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `POST /api/channel/join`  | `{ticket, role, protocol, machine_id, name, software, platform}` | `{id, token}`：绑定 id，以及之后每个 `hello` 都要带的密钥                              |
| `POST /api/channel/leave` | `{id, token}`                                                    | `{}`；设备那一行留在**设备**页上，只去掉令牌；客户端那一行连同它的 AI 网关密钥一起删除 |

`machine_id` 和 `platform` 描述机器本身，两种角色从不同的地方读取：

| 字段         | 被控端发送                                                                                                                                                                                                                      | 客户端发送                                     |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `machine_id` | `/etc/machine-id`，没有就用 `/var/lib/dbus/machine-id`，再没有就为空                                                                                                                                                            | 每次安装生成一次并保存的 uuid4 十六进制串      |
| `platform`   | `{os, family, arch, version}`：`linux`、`windows` 或 `darwin`；`debian`、`rhel` 或空；`amd64`、`arm64` 或 `armhf`；Linux 上是 glibc 版本（`2.36`），Windows 上是构建号（`26100`），macOS 上是产品版本（`15.3.1`），读不到时为空 | `{os, family, arch}`，Linux 以外 `family` 为空 |

hub 拿被控端的 `version` 和模块的最低版本比较，低于最低版本的机器上，这个模块显示为系统不支持。不带 `version` 的被控端不受这条限制。

客户端从 hub 已有记录的那次安装再次加入时，回到原来那一行，密钥、开关和最近一次汇报都保留。

| 状态码 | `detail`                                      | 什么时候                               |
| ------ | --------------------------------------------- | -------------------------------------- |
| 409    | `protocol_too_old`，params `{peer, hub, min}` | 协议号低于 hub 的 `PROTOCOL_MIN`       |
| 409    | `protocol_too_new`，params `{peer, hub, min}` | 协议号高于 hub 的 `PROTOCOL`           |
| 409    | `role_mismatch`，params `{role}`              | 凭证是为另一种角色生成的               |
| 401    | `ticket_spent`                                | 凭证不存在、已过期或已用过             |
| 401    | `binding_unknown`                             | `leave` 给出的 id 和令牌对不上任何绑定 |

hub 先检查协议号，再读凭证，所以协议号不合格时凭证不会用掉。HTTP 错误的响应体是 `{"detail": {"code": "...", "params": {}}}`。

## 套接字

套接字是 `wss://<hub-address>:8443/api/channel/socket`，`<hub-address>` 是加入成功时用的那个地址；每次都新建一条固定指纹的连接。文本帧是一个 JSON 对象，`type` 取帧名之一；二进制帧是大端序的 `u32` 流 id，后面跟这个流的字节。

### 握手

两个方向的第一帧都是身份卡，形状相同。套接字打开后十秒内发出 `hello`，hub 回 `welcome` 或 `refused`。

| 字段       | `hello`（上行）                                   | `welcome`（下行）                    |
| ---------- | ------------------------------------------------- | ------------------------------------ |
| `protocol` | 这个构建的协议号，`3`                             | hub 的协议号，`3`                    |
| `role`     | `agent` 或 `client`                               | `hub`                                |
| `id`       | 绑定 id                                           | hub 自己的 id，一个 uuid             |
| `name`     | 主机名，或绑定的名字                              | hub 在**设置**（Settings）页上的名字 |
| `software` | `neutrino_agent/0.5.0` 或 `neutrino_client/0.5.0` | `neutrino_hub/0.5.0`                 |
| `token`    | 绑定令牌                                          | 无                                   |

加入了多个 hub 的客户端，按 hub 的 `id` 分组，用它的 `name` 显示。`hello` 不合格时，hub 回 `refused {code, params}`，然后以 4000 关闭；第一帧超时、是二进制、类型不对或读不懂时，错误码是 `hello_invalid`。

### 帧

| 帧        | 方向 | 内容                                        |
| --------- | ---- | ------------------------------------------- |
| `hello`   | 上行 | 身份卡，带 `token`                          |
| `welcome` | 下行 | hub 的身份卡                                |
| `refused` | 下行 | `{code, params}`，随后以 4000 关闭          |
| `state`   | 下行 | `{hash, ...sections}`：应当成立的状态       |
| `report`  | 上行 | `{state_hash, ...sections}`：实际的状态     |
| `open`    | 双向 | `{stream, kind, ...args}`：一个流开始       |
| `close`   | 双向 | `{stream, code, params}`：流结束，带着结果  |
| `credit`  | 双向 | `{stream, bytes}`：发送方还能再发这么多字节 |
| 二进制    | 双向 | `<u32 stream id><bytes>`                    |

hub 每 20 秒发一次 ping，pong 迟到超过 20 秒就断开套接字。被控端和客户端 45 秒收不到任何东西就认为套接字已断，按 5～60 秒的退避间隔重连。

## 流层

每个操作都是一个流：`open` 是请求，`close` 是回复，`kind` 是方法名。

| 方面       | 规则                                                                                                      |
| ---------- | --------------------------------------------------------------------------------------------------------- |
| id         | hub 从 0 开始用偶数 id，对端从 1 开始用奇数 id，两边不会撞号                                              |
| 字节       | 一个二进制帧装一个流的字节；流的文本输出一行一帧                                                          |
| 额度       | `credit {stream, bytes}` 再给这么多字节的额度；窗口 1 MiB，单帧最大 64 KiB                                |
| 结果       | 任何一方都可以发 `close {stream, code, params}` 结束流；`code` 为空时 `params` 是结果，有 `code` 时是拒绝 |
| 只关一次   | 一方已关闭的流，另一方不再回 close                                                                        |
| 未知的种类 | 程序没有处理程序的 kind 以 `kind_unknown` 关闭；`command` 流上未知的动词以 `verb_unknown` 关闭            |

## 客户端的状态

客户端的汇报里 `state_hash` 和 hub 的不同时，或 hub 自己的状态变了时，hub 下发 `state`。

| 段            | 内容                                                                                         |
| ------------- | -------------------------------------------------------------------------------------------- |
| `hash`        | 一个不透明的字符串，客户端在每次汇报里原样带回                                               |
| `is_disabled` | 在**客户端**页选择**停用**（Disable）后为 `true`：列表为空，所有操作都返回 `client_disabled` |
| `services`    | 这个客户端有权使用的已发布条目，按它的套接字来源地址解析                                     |
| `urls`        | hub 提供通道的每个地址，客户端存下来供下次重连                                               |
| `overlays`    | 客户端加入 hub 每个虚拟网要用的材料，首选的排在前面                                          |
| `terminals`   | 客户端有权打开 shell 的受管机器，每台是 `{device_id, name, is_online, sessions}`             |

### 虚拟网

`overlays` 里每个有材料的运行中虚拟网占一个对象，NetBird 排在前面。下面几种情况列表为空：这台机器没运行虚拟网、客户端已停用、客户端的权限不含 `overlay`、hub 的保险库已锁。

```json
[
  {
    "provider": "netbird",
    "setup_key": "...",
    "management_url": "",
    "fqdn": "hub.netbird.cloud"
  },
  {
    "provider": "easytier",
    "mode": "manual",
    "network_name": "...",
    "network_secret": "...",
    "peer": "tcp://203.0.113.7:11010",
    "hub_address": "10.0.0.1"
  }
]
```

| 提供方与模式          | 字段                                                                                                                        |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `netbird`             | `setup_key`，可重复使用的密钥；`management_url`，用 NetBird 官方管理面时为空；`fqdn`，hub 在虚拟网上的名字                  |
| `easytier`，`manual`  | `network_name`、`network_secret`；`peer`，即 `tcp://<join-host>:11010`；`hub_address`，hub 在这个网络上的地址，不带前缀长度 |
| `easytier`，`console` | `config_server`，带账户令牌的控制台地址；`is_secure_mode`；`hub_address`                                                    |

### 终端与会话

客户端的权限包含 `terminal` 时，`terminals` 列出每台受管机器，hub 自己的也在内；权限指定了机器时，只列那几台。每一项的 `sessions` 是这台机器保留的终端会话，按 `started_at` 排序，机器离线时为空：

| 字段             | 内容                                                                         |
| ---------------- | ---------------------------------------------------------------------------- |
| `session_id`     | 打开方生成的 id，一个 uuid                                                   |
| `account`        | shell 运行所用的账户                                                         |
| `started_at`     | 打开时间，Unix 秒                                                            |
| `title`          | shell 最后设置的标题，或 shell 名                                            |
| `owner`          | 谁打开的，即 hub 在 `shell` 的 open 上盖的标记                               |
| `is_attached`    | 现在有没有流连着                                                             |
| `is_persistent`  | 最后一个流关闭后会话是否保留                                                 |
| `is_shared`      | 对这台机器有终端权限的客户端是否都能连上；共享的会话在最后一个流关闭后也保留 |
| `attached_count` | 现在连着几个流                                                               |

被控端的通道建立或断开时，或某台机器的会话列表变化时，hub 给每个客户端推送状态。

## 客户端的汇报

```json
{
  "type": "report",
  "state_hash": "<state-hash>",
  "machine": {
    "hostname": "laptop",
    "platform": { "os": "darwin", "family": "", "arch": "arm64" }
  }
}
```

收到 welcome 后发一次汇报，之后每 30 秒一次，每应用完一份状态再发一次。收到第一份状态之前，`state_hash` 为空。

## 服务条目

`services` 里每个条目是 `{id, type, title, payload, is_healthy, source, description, description_code, description_params, device_name}`。

| `type` | `payload`                                                            |
| ------ | -------------------------------------------------------------------- |
| `web`  | `{url, is_local_only}`；只有 VS Code 的条目带 `is_local_only` 且为真 |
| `port` | `{host, port}`                                                       |
| `ai`   | `{endpoint, protocol, models}`，`protocol` 是 `openai`               |
| `file` | `{protocol, host, share, users}`，`protocol` 是 `smb`                |
| `rdp`  | `{protocol, host, port, attention}`，`protocol` 是 `rustdesk`        |

带 `is_local_only` 的条目只能通过转发到客户端本机 `127.0.0.1` 的端口打开，所以手机上显示为仅桌面可用。`rdp` 条目的 `attention` 写明共享桌面的那台机器前要先做什么：`rdp_nobody_seated`、`rdp_screen_not_allowed`，或为空。`file` 条目的 `users` 列出能打开这个共享的账户，手机据此给出用户名，只让人输密码。手动声明的共享这一项为空，0.5.0 之前的 hub 不发这一项。

| 字段                 | 内容                                                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `is_healthy`         | 最近一次探测的结果，从没探测过时为 `null`                                                                                                        |
| `source`             | `module`、`declared` 或 `device`                                                                                                                 |
| `description_code`   | 来源说明的错误码形式，由程序自己翻成文字：`ai_gateway`、`container`、`declared`、`device_share`、`gitea_module`、`samba_module`、`vscode_module` |
| `description_params` | 那句话要用的值；`vscode_module` 用 `{host, account}`                                                                                             |
| `device_name`        | 提供这个条目的机器名；hub 记录里没有这台机器时为空                                                                                               |

## 客户端打开的流

### service 流

`open {kind: service, id}` 请求某个条目要从 hub 取的材料。hub 按下面的顺序检查，第一项不通过的检查决定 close 的错误码：

| `code`              | 什么时候                                             |
| ------------------- | ---------------------------------------------------- |
| `binding_unknown`   | 没有哪个客户端行的 id 是这条套接字绑定的 id          |
| `client_disabled`   | 这个客户端在**客户端**页上停用了                     |
| `service_unknown`   | 为这个客户端解析出的列表里没有这个 id                |
| `permission_denied` | 这个客户端的权限不含条目的类型，或不含提供条目的机器 |
| `rdp_not_shared`    | 条目所在的机器已停止共享桌面                         |
| `vault_locked`      | hub 的保险库已锁，打不开 AI 密钥或 VS Code 令牌      |

不带错误码的 close 带回材料：

| 条目                                           | close 的 `params`                                                                                |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `rdp`                                          | `{host, port, password}`：当前解析出的地址和座位密码                                             |
| `ai`                                           | `{base_url, api_key, model}`：网关地址、这个客户端自己的密钥、网关提供的第一个模型               |
| `description_code` 为 `vscode_module` 的 `web` | `{token}`；客户端把条目的端口转发到本机 `127.0.0.1`，打开 `http://127.0.0.1:<port>/?tkn=<token>` |
| 其他 `web`、`port`、`file`                     | 空；payload 已经是客户端需要的全部                                                               |

### shell 与 command 流

| `open`                                                                                | hub 做什么                                                                                                                                                                                                   |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `{kind: shell, device_id, cols, rows, session_id, is_resumed}`                        | 在那台机器上以 `session_id` 打开 shell，双向转发终端字节；机器保留着这个 id 的会话时，和已经连着的流一起连到那个会话，先发最近的输出；`is_resumed: true` 只连已有会话，机器上没有时以 `session_unknown` 关闭 |
| `{kind: command, module: agent, verb: resize, shell, cols, rows}`                     | 调整客户端自己那个 `shell` 流的大小；没有这个流时返回 `shell_unknown`                                                                                                                                        |
| `{kind: command, module: agent, verb: persist, session_id, is_persistent, is_shared}` | 设置最后一个流关闭后会话是否保留，以及会话是否共享；没带的那个值不变                                                                                                                                         |
| `{kind: command, module: agent, verb: stop_session, session_id}`                      | 在会话所在的机器上结束它                                                                                                                                                                                     |

一个会话可以同时连多个流：每个流都收到全部输出，任何一个流的输入都进 shell，shell 的大小取所有连着的窗口中最小的列数和行数。hub 在机器上打开任何东西之前，`shell` 流可能以 `binding_unknown`、`client_disabled`、`permission_denied {kind: terminal}` 或 `agent_offline {device}` 关闭。没有哪台机器保留这个会话时，`persist` 和 `stop_session` 以 `session_unknown` 关闭。被控端重启或升级时，那台机器上的会话全部结束。

## 被控端的段

被控端的两份文档包含下面这些段；`modules` 里的条目来自 hub 的模块清单，按被控端的 `platform` 解析。

| 段        | 发给被控端的 `state`                           | 被控端的 `report`                                                         |
| --------- | ---------------------------------------------- | ------------------------------------------------------------------------- |
| `machine` |                                                | `{hostname, platform, accounts, metrics, sessions}`                       |
| `network` |                                                | `{link: {interface, mac, address}, interfaces: [{name, mac, addresses}]}` |
| `modules` | `{<name>: {want, config, install, uninstall}}` | `{<name>: {state, is_active, code, params, details}}`                     |
| `desktop` | `{seat_password}`                              | `{is_shared, account, share_id, port, attention, connected_count}`        |
| `urls`    | hub 提供通道的每个地址                         |                                                                           |
| `error`   |                                                | `{code, params}`：被控端最近一次值得显示的失败                            |

被控端每 5 秒汇报一次。hub 向它打开 `shell`、`file` 和 `command` 流，它向 hub 打开 `log` 和 `package` 流。

## 拒绝与绑定

拒绝在任何地方都是 `{code, params}`：HTTP 错误里的 `detail`、`refused` 帧，或流的 close 上的错误码。拒绝不影响绑定；程序记下它，一分钟后再发 `hello`。

| 错误码                         | 出现在               | 对绑定的影响                                 |
| ------------------------------ | -------------------- | -------------------------------------------- |
| `protocol_too_old`             | `join`、`hello`      | 保留                                         |
| `protocol_too_new`             | `join`、`hello`      | 保留                                         |
| `role_mismatch`                | `join`、`hello`      | 保留                                         |
| `hello_invalid`                | `hello`              | 保留                                         |
| `ticket_spent`                 | `join`               | 还没有绑定；要生成一条新链接                 |
| `binding_unknown`              | `hello`、`leave`、流 | 解除：程序删掉自己的绑定，要用新链接重新加入 |
| `kind_unknown`、`verb_unknown` | 流                   | 保留                                         |

只有 `binding_unknown` 会解除绑定，因为它表示那一行已在面板上删除，而且只有持有固定证书的 hub 才发得出它。

| 关闭码 | 含义                                                         |
| ------ | ------------------------------------------------------------ |
| 4000   | `refused`；它前面的 `refused` 帧带着错误码                   |
| 4010   | `replaced`：同一个绑定又开了一条套接字；程序要等人操作才重连 |

## 协议号

每个构建声明一个整数 `PROTOCOL`，包的版本号不参与准入。hub 还有 `PROTOCOL_MIN`，协议号在 `PROTOCOL_MIN` 到 `PROTOCOL` 之间的对端才能接入。

| `PROTOCOL` | 首个次版本 |
| ---------- | ---------- |
| 1          | 0.3.0      |
| 2          | 0.4.0      |
| 3          | 0.5.0      |

0.5.0 起 `PROTOCOL_MIN` 是 3。协议 3 把链接和客户端状态里的 `overlay`（一个对象或 null）改名为 `overlays`（一个列表）。0.3 和 0.4 的被控端或客户端接入 0.5.0 的 hub 时返回 `protocol_too_old`，也不会从 hub 自动升级。hub 自己升级时会重装本机的被控端；其他机器要在**设备**页上或手动装 0.5.0 的包。

读取宽松，写出严格。不认识的字段忽略，不认识的 kind 以 `kind_unknown` 关闭，程序只发自己协议号定义过的内容。增加 kind、字段或错误码时协议号不变；删掉任何东西、改变含义，或改动链接、凭证、证书指纹，以及 `hello`、`state`、`report`、`open` 这四个词时，协议号加一。
