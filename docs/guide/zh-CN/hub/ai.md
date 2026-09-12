---
title: AI
---

# AI

hub 的 **AI** 页把订阅账号和 API 密钥放到同一个网关地址后面，给每个客户端发一把自己的密钥。网关是 hub 自带的 CLIProxyAPI，默认端口 8317。这一页的节有 **活动**（Activity）、**提供方**（Providers）、**账号**（Accounts）、**接入**（Access）和 **网关端口**（Gateway port）。

## 提供方

![提供方](/guide/zh/ai_providers.webp)

提供方是网关转发到的端点，每个配一把保存过的令牌。列表顺序就是服务顺序，第一个启用的提供方先应答。

1. 点 **添加提供方**（Add provider）。
1. 填 **名称**（Name），选 **类型**（Kind）。
1. 填 **Base URL**；留空用这家服务的默认地址。
1. 在 **API 令牌**（API token）里选一把令牌。令牌在[凭据](./credentials.md)页保存，这里只选不贴。
1. 在 **模型别名**（Model aliases）里一行一个模型，真名在前。别名是 AI 工具里显示的名字；要用别名时，这一行写成 `真名 = 别名`。客户端默认请求第一行。
1. 点 **保存提供方**（Save provider），再点 **应用提供方**（Apply providers）。

| 类型                             | 端点的协议          |
| -------------------------------- | ------------------- |
| Anthropic                        | `/v1/messages`      |
| OpenAI                           | `/v1/responses`     |
| Gemini                           | `generateContent`   |
| OpenAI 兼容（OpenAI-compatible） | `/chat/completions` |

类型按端点的协议选，与模型出自哪家无关，例如 DeepSeek 的 `/anthropic` 端点选 Anthropic。应用提供方会重启网关，进行中的请求失败。

## 订阅账号

![账号](/guide/zh/ai_accounts.webp)

订阅账号和 API 密钥提供同一批模型，网关在两者之间挑选。账号的登录方式是设备码。

1. 在 **账号** 里点 **登录**（Sign in），选一家订阅。
1. 打开页面给出的地址，输入显示的验证码。有的提供方的登录页最后跳转到一个打不开的地址，这时把浏览器地址栏整行粘进 **地址栏或验证码**（Address bar or code）。
1. 点 **完成登录**（Finish sign-in）。

验证码有有效期，页面上写着剩余时间。**账号** 一节写着 **这个网关不提供订阅登录** 时，当前版本的网关没有可登录的订阅类型。

## 访问

![接入](/guide/zh/ai_keys.webp)

**接入** 顶部是 **端点**（Endpoint），形如 `http://<hub-address>:8317`，其中 `<hub-address>` 是这台机器的地址。每个客户端接入时自动拿到一把以它命名的密钥，列表里写作 `client/<name>`。没有客户端的机器手动生成一把：

1. 点 **生成密钥**（Generate key）。
1. 填这把密钥给谁用，例如 `laptop`。

密钥只显示这一次，贴进工具时和上面的端点配对。**吊销**（Revoke）一把密钥后，用这把密钥的每个工具立刻连不上网关；吊销的是客户端的密钥时，hub 直接发给那个客户端一把新的。

## 用量与日志

![用量](/guide/zh/ai_usage.webp)

**活动** 里有 **今日请求**（requests today）和 **今日 tokens**（tokens today），token 是模型计量文本的单位。下面是最近 30 天的用量，按 **提供方** 或 **密钥**（Keys）切换。**日志**（Journal）显示网关最近的若干行输出；网关还没上报时写 **暂无用量**。

## 网关端口

**网关端口** 默认 8317。改端口后点 **应用网关端口**（Apply gateway port），网关在新端口重启。

::: warning
指向旧端口的每台机器都连不上网关，直到它的端点也改过来。改完端口，在每个客户端上重新应用一次。
:::

## 在客户端上

![客户端的 AI 面板](/guide/zh/client_ai_panel.webp)

客户端 **AI** 面板只有一条，来源写着由 AI 网关发布，带一个 **启用**（Enabled）开关、**配置**（Config）和 **应用**（Apply）。

1. 点 **配置**，打开 **AI 工具配置**（AI tool configuration）。
1. 逐个工具选模型。Claude Code 有 **默认模型**（Default model）和 Opus、Sonnet、Haiku 三个档位；Codex 有 **模型**（Model）和 **推理强度**（Reasoning effort）；Gemini 只有 **模型**。每一项都可以留在 **网关默认**（gateway default）。
1. 点 **保存**（Save）。保存只是暂存，机器上还没有任何改动。
1. 打开 **启用**，点 **应用**。

![AI 工具配置](/guide/zh/client_ai_config.webp)

应用时客户端用 cc-switch 改写三个工具各自的配置文件，全部成功或全部不改；之后开关旁写 **工具已指向 hub**。关掉 **启用** 再点 **应用**，每个工具恢复原来的配置，旁边写 **工具保持原样**。终端里同一件事：

```bash
nclient service ai show
nclient service ai apply hub --codex-effort medium
nclient service ai apply off
```
