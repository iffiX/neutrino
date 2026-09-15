---
title: 通道
---

# 通道

通道是 hub 与它管理的每个程序之间的那条 WebSocket 连接：Linux 机器上的被控端，或者一个人的客户端。用别的语言另写一个客户端，说的话和 `neutrino_client` 一样。这一页写全这套话：加入链接、证书指纹、两个 HTTP 端点、八种帧、流层、客户端收发的两份文档、它使用的五类服务，以及 hub 拒绝它时给出的错误码。

## 端口与证书指纹

hub 开两个端口。面板端口默认 8080，是明文 HTTP，按会话 cookie 认人，只服务浏览器。通道在被控端端口上，默认 8443，只服务 `/api/channel`，全程 TLS。

这个端口上的证书是自签的，有效期十年，指纹就是 hub 的全部身份。

| 规则                    | 取值                                                |
| ----------------------- | --------------------------------------------------- |
| 固定的是什么            | 证书 DER 编码的 SHA-256 摘要，64 位小写十六进制字符 |
| 什么时候核对            | 每次 TLS 握手之后，发出任何请求字节之前             |
| 证书链与主机名校验      | 关闭                                                |
| TLS 最低版本            | 1.2                                                 |
| 对不上时                | 关闭连接，整个加入过程中止，不再试下一个地址        |
| 没有指纹的 `https` 地址 | 不连                                                |

链接里的地址上出现另一张证书，就是有人在冒充这台 hub，所以对不上时中止，而不是悄悄换下一个地址。

## 加入链接

链接由人在 hub 的 **客户端**（Clients）页上生成，做法在[客户端](../hub/clients.md)页，生成后粘进程序里。它的形状是 `neutrino://enroll/<payload>`，`<payload>` 是一个 JSON 对象的 base64url 编码：

```json
{
  "urls": ["https://192.168.100.1:8443", "https://10.8.0.1:8443"],
  "token": "sB1nYt9Qk2_pL0wV7xR4cZ8f",
  "fp": "<sha256-hex>",
  "role": "client"
}
```

| 字段    | 内容                                                                   |
| ------- | ---------------------------------------------------------------------- |
| `urls`  | hub 在被控端端口上开放的每个地址，其中一个在加入方的网里，程序逐个去试 |
| `token` | 加入票据，五分钟有效，只能用一次                                       |
| `fp`    | 要固定的证书指纹                                                       |
| `role`  | 客户端页发的链接是 `client`，设备页发的是 `agent`                      |

客户端拿到 `role` 为 `agent` 的链接，以 `link_not_for_client` 拒绝。base64url 的字符集里没有 shell 会切开、URL 要转义的字符，所以链接不加引号也能粘；末尾的 `=` 可有可无，解码前补齐即可。

再生成一条链接，上一条就作废，所以同一时刻只有一条邀请；hub 重启后票据全部失效。

## 加入与退出

一次绑定从 `POST /api/channel/join` 开始，到 `POST /api/channel/leave` 结束，两个端点都在这条固定了指纹的连接上收发 JSON。

加入请求体的字段：

| 字段         | 内容                                                                           |
| ------------ | ------------------------------------------------------------------------------ |
| `ticket`     | 链接里的 `token`                                                               |
| `role`       | `client`                                                                       |
| `protocol`   | 这份构建说的协议号，0.3.0 的三个包都是 `1`                                     |
| `machine_id` | 这次安装自己生成并保存的 uuid4 十六进制串                                      |
| `name`       | 这台电脑的主机名，客户端页显示它                                               |
| `software`   | 程序名加版本，例如 `neutrino_client/0.3.0`                                     |
| `platform`   | `{os, family, arch}`：`linux`、`windows` 或 `darwin`，Linux 发行版系，以及架构 |

hub 回 `{id, token}`。`id` 是生成链接时就定下的绑定 id，`token` 是 192 位的密钥，之后每个 `hello` 都带它。程序把两项存进只有本人能读的文件。

协议号的准入排在最前，所以 hub 拒绝一个协议号时不消耗票据。hub 取出票据和判断票据是同一步，所以两个程序抢同一条链接，只有一个能进来。

| 状态码 | `detail`                                      | 什么时候                                     |
| ------ | --------------------------------------------- | -------------------------------------------- |
| 409    | `protocol_too_old`，params `{peer, hub, min}` | 协议号低于 hub 的 `PROTOCOL_MIN`             |
| 409    | `protocol_too_new`，params `{peer, hub, min}` | 协议号高于 hub 的 `PROTOCOL`                 |
| 409    | `role_mismatch`，params `{role}`              | 票据是发给另一个角色的                       |
| 401    | `ticket_spent`                                | 票据不存在、过期、已用过，或者它指的那行没了 |

HTTP 错误的响应体是 `{"detail": {"code": "...", "params": {}}}`，和通道上其他拒绝同一个形状。

`POST /api/channel/leave` 收 `{id, token}`，返回 `{}`。hub 删掉绑定并吊销这个客户端的网关密钥，程序删掉自己那份。这一对对不上任何绑定时，返回 401 `binding_unknown`。

## 套接字

套接字的地址是 `wss://<hub-address>:8443/api/channel/socket`，其中的地址就是加入时成功的那一个。这条连接另开，指纹照样核对一次。文本帧是一个 JSON 对象，`type` 是八个词之一；二进制帧是大端 `u32` 流 id，后面跟这条流的字节。

hub 每 20 秒 ping 一次，pong 迟到超过 20 秒就断开。`neutrino_client` 把 45 秒的静默当作连接已死，按 5 到 60 秒的退避重连。

### 握手

两个方向的第一帧都是身份卡，形状相同。套接字打开后十秒内 `hello` 上行，`welcome` 或 `refused` 下行。

| 字段       | `hello`（上行）         | `welcome`（下行）    |
| ---------- | ----------------------- | -------------------- |
| `protocol` | 这份构建说的协议号      | hub 的协议号         |
| `role`     | `client`                | `hub`                |
| `id`       | 绑定 id                 | hub 自己的 id        |
| `name`     | 绑定的名字，或者主机名  | hub 的名字           |
| `software` | `neutrino_client/0.3.0` | `neutrino_hub/0.3.0` |
| `token`    | 绑定令牌                | 没有这一项           |

hub 的 `id` 是它安装时生成的 uuid，`name` 是有人在它设置页上填的字。加入了多台 hub 的程序按 `id` 归组，按 `name` 显示，因为名字会改，id 不会。

hub 拒绝 `hello` 时下行 `refused {code, params}`，随后以 4000 关闭。握手里没有状态哈希，第一份 report 才有。

### 帧

| 帧        | 方向 | 内容                                        |
| --------- | ---- | ------------------------------------------- |
| `hello`   | 上行 | 身份卡，带 `token`                          |
| `welcome` | 下行 | hub 的身份卡                                |
| `refused` | 下行 | `{code, params}`，随后以 4000 关闭          |
| `state`   | 下行 | `{hash, ...节}`：应该是什么样               |
| `report`  | 上行 | `{state_hash, ...节}`：现在是什么样         |
| `open`    | 双向 | `{stream, kind, ...参数}`：一条流开始       |
| `close`   | 双向 | `{stream, code, params}`：流结束，带结果    |
| `credit`  | 双向 | `{stream, bytes}`：发送方可以再发这么多字节 |
| 二进制帧  | 双向 | `<u32 流 id><字节>`                         |

## 流层

两份文档之外的每一个动作都是一条流：`open` 是请求，`close` 是回答，`kind` 就是全部方法名。

| 事项       | 规则                                                                                                     |
| ---------- | -------------------------------------------------------------------------------------------------------- |
| 流 id      | hub 开的流用偶数，对端开的用奇数，从 1 起各自递增，两边不会撞号                                          |
| 字节       | 二进制帧是流 id 加字节；一条流的文本输出按行编码，一行一帧                                               |
| 信用       | `credit {stream, bytes}` 允许发送方再发这么多字节，接收方边消费边给；hub 的窗口是 1 MiB，单帧最大 64 KiB |
| 结果       | `close {stream, code, params}` 从任一侧结束一条流；`code` 为空时 `params` 就是结果，带 code 就是拒绝     |
| 只关一次   | 一侧关掉的流，另一侧不再回一个 close                                                                     |
| 不认识的流 | `kind` 没有对应处理的流，以 `kind_unknown` 关掉                                                          |

客户端只开一种流 `service`，hub 不向客户端开流。其余几种（`shell`、`file`、`command`、`package`、`log`、`desktop`）用在 hub 与被控端之间。

## 两份文档

客户端这一侧的通道就是两份文档，共用一个哈希：`state` 下行，`report` 上行。

### 状态

```json
{
  "type": "state",
  "hash": "<state-hash>",
  "is_disabled": false,
  "services": [
    {
      "id": "samba_4b1c8f0d_media",
      "type": "file",
      "title": "media",
      "payload": {
        "protocol": "smb",
        "host": "192.168.100.24",
        "share": "media"
      },
      "is_healthy": true,
      "source": "module",
      "description": "published by the samba module on 192.168.100.24",
      "description_code": "samba_module",
      "description_params": { "host": "192.168.100.24" }
    }
  ]
}
```

| 字段          | 内容                                                                                         |
| ------------- | -------------------------------------------------------------------------------------------- |
| `hash`        | 一个不透明的字符串，程序存下来，之后每份 report 都带回去                                     |
| `is_disabled` | 客户端页点了 **停用**（Disable）之后为 `true`：列表为空，每个动作都以 `client_disabled` 拒绝 |
| `services`    | 发布的服务列表，按这条连接进来的地址解析过                                                   |

每条服务是 `{id, type, title, payload, is_healthy, source, description, description_code, description_params}`：

| 字段                 | 内容                                                                                                                            |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `id`                 | `service` 流点名用的就是它                                                                                                      |
| `type`               | `web`、`port`、`ai`、`file` 或 `rdp`                                                                                            |
| `title`              | 给人读的名字                                                                                                                    |
| `payload`            | 这个类别自己的字段，见下一节                                                                                                    |
| `is_healthy`         | 最近一次探测的结果，没人探测过时是 `null`                                                                                       |
| `source`             | `module` 是设备上的模块，`declared` 是人手填的，`device` 是机器自报的桌面                                                       |
| `description`        | 英文的来源说明                                                                                                                  |
| `description_code`   | 同一条来源的错误码写法，程序自己组织语言：`ai_gateway`、`container`、`declared`、`device_share`、`gitea_module`、`samba_module` |
| `description_params` | 那句话要用的值                                                                                                                  |

一条连接上，第一份 `state_hash` 和 hub 不一致的 report 触发一次下发，之后只有 hub 自己的列表变了才下发。程序换一个网络重连，payload 里的地址也换一批，因为 hub 按连接进来的地址重新解析每一条服务。

### 汇报

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

收到 welcome 之后立刻上行一份，之后每 30 秒一份，每应用完一份 state 再补一份。`state_hash` 是手上这份 state 的哈希，第一份到手之前为空。

## 服务的类别

`type` 决定 payload 的形状，也决定人在窗口上看到哪个按钮。

| `type` | `payload`                           | 客户端拿它做什么                                                              |
| ------ | ----------------------------------- | ----------------------------------------------------------------------------- |
| `web`  | `{url}`                             | 在浏览器里打开这个地址                                                        |
| `port` | `{host, port}`                      | 把这个地址转发到本机回环上的一个端口                                          |
| `ai`   | `{endpoint, protocol, models}`      | 把这个人的 AI 工具指到网关：`protocol` 是 `openai`，`models` 是网关提供的模型 |
| `file` | `{protocol, host, share}`           | 挂载这个共享，`protocol` 是 `smb`                                             |
| `rdp`  | `{protocol, host, port, attention}` | 打开 RustDesk 查看器连这台机器：`protocol` 是 `rustdesk`，`port` 是 21118     |

`rdp` 条目里的 `attention` 是共享方那台机器上还需要人做的事：`rdp_nobody_seated` 表示屏幕前没有登录的账户，`rdp_screen_not_allowed` 表示 Wayland 会话还没授予屏幕捕获权限，空字符串表示连过去就能看到桌面。

## service 流

`rdp` 和 `ai` 这两个类别要的材料不在发布列表里。程序开一条 `service` 流点名这条服务，close 带回来的就是材料：

```json
{ "type": "open", "stream": 1, "kind": "service", "id": "rdp_4f21c0" }
```

| 条目的 `type`         | close 的 `params`                                                      |
| --------------------- | ---------------------------------------------------------------------- |
| `rdp`                 | `{host, port, password}`：此刻解析出的地址，以及为这一次解封的座位密码 |
| `ai`                  | `{base_url, api_key, model}`：网关地址、这个客户端自己的密钥、默认模型 |
| `web`、`port`、`file` | 空：条目的 payload 就是全部材料                                        |

close 带 code 就是拒绝，这条流到此结束：

| 错误码            | `params`       | 含义                                  |
| ----------------- | -------------- | ------------------------------------- |
| `service_unknown` | `{service_id}` | 为这个客户端解析出的列表里没有这个 id |
| `rdp_not_shared`  | `{service_id}` | 那台机器已经不共享桌面了              |
| `client_disabled` |                | 客户端页上停用了它                    |
| `vault_locked`    |                | hub 的保险库是锁的，解封不出任何密钥  |
| `binding_unknown` |                | hub 这边没有这个客户端                |

## 拒绝与绑定

拒绝在哪里都是 `{code, params}`：HTTP 错误里是 `detail`，握手时是 `refused` 帧，流上是 close 的 code。

| 错误码             | 出现在                 | 对绑定的影响                                   |
| ------------------ | ---------------------- | ---------------------------------------------- |
| `protocol_too_old` | `join`、`hello`        | 保留绑定：记下这个码，一分钟后再发一次 `hello` |
| `protocol_too_new` | `join`、`hello`        | 保留绑定，同上                                 |
| `ticket_spent`     | `join`                 | 还没有绑定，找人要一条新链接                   |
| `role_mismatch`    | `join`、`hello`        | 保留绑定                                       |
| `binding_unknown`  | `hello`、`leave`、流上 | 解除绑定：删掉本地的绑定，用新链接重新加入     |
| `kind_unknown`     | 流上                   | 保留绑定                                       |

只有 `binding_unknown` 会解除绑定，因为它说的是面板上删掉了这一行，而这句话只有手握固定证书的那台 hub 说得出来。

| 关闭码 | 含义                                                                             |
| ------ | -------------------------------------------------------------------------------- |
| 4000   | `refused`，前一帧 `refused` 写了原因                                             |
| 4010   | `replaced`：同一个绑定又开了一条连接，这一条关掉。重连由人触发，例如窗口上的重连 |

## 协议号

hub 与程序之间的兼容性只看一个整数 `PROTOCOL`，每份构建声明一个，包版本不参与判断。hub 另有 `PROTOCOL_MIN`，即它还接受的最老协议号：对端的协议号在 `PROTOCOL_MIN` 到 `PROTOCOL` 之间，hub 才接受它。

读宽容，写严格：不认识的字段忽略，不认识的 kind 以 `kind_unknown` 关掉，程序只发本协议号定义的东西。

| 规则                                                               | 协议号                                           |
| ------------------------------------------------------------------ | ------------------------------------------------ |
| 加一种 kind、一个字段、一个错误码                                  | 不变，patch 版本也可以加                         |
| 删掉什么，或者改掉含义                                             | 加一                                             |
| 改链接、票据、指纹，或者 `hello`、`state`、`report`、`open` 四个词 | 加一                                             |
| 协议号加一之后                                                     | 1.0 之前开新 minor，1.0 之后开新 major           |
| `PROTOCOL_MIN`                                                     | 只在开新 minor 时上移，最多到上一个 minor 说的号 |

| `PROTOCOL` | 首次出现的 minor |
| ---------- | ---------------- |
| 1          | 0.3.0            |
