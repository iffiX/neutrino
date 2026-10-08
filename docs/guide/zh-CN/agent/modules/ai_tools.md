---
title: 把一台机器的 AI 工具指向网关
---

# 把一台机器的 AI 工具指向网关

一台受管机器打开这个设置后，机器上运行 VS Code、code-server 或 CloudCLI 的账户，它们的 Claude Code、Codex 和 Gemini 都改用中枢的 AI 网关。每个账户那一行读 **使用中枢的 AI 网关**（Uses the hub's AI gateway）。

开始之前，中枢的 AI 网关要已有能用的模型，设置方法见 [AI](../../hub/ai.md) 页。这台机器上要有 VS Code、code-server 或 CloudCLI 的实例，被控端要在线。

![server 的全局配置，开关打开，两个账户都读使用中枢的 AI 网关](/guide/zh/modules_ai_tools.webp)

## 打开

1. 在 **模块**（Modules）页的 **选择机器**（Which machine）里选这台机器。
1. 在 **全局配置**（Global configuration）里打开 **这台机器的 AI 工具使用中枢的 AI 网关**（This machine's AI tools use the hub's AI gateway）。

开关按下就生效，这一块没有应用栏。被控端离线时，开关是灰的。网关还没有可用的模型时，开关打不开，下面显示 `gateway_not_serving` 的说明。

第一次用时，机器从中枢取一份 cc-switch。cc-switch 是改写这些工具设置文件的程序，机器用它逐个账户切换。

## 选模型

1. 在 **全局配置** 里选择 **配置**（Configure）。
1. 给 Claude Code 选 **默认模型**（Default model）、**Opus 档位**（Opus slot）、**Sonnet 档位**（Sonnet slot）和 **Haiku 档位**（Haiku slot）。
1. 给 Codex 选 **模型**（Model）和 **推理强度**（Reasoning effort）。
1. 给 Gemini 选 **模型**。
1. 选择 **保存**（Save）。

每一项都能留在 **网关默认**（gateway default），这时用网关的第一个模型。**取消**（Cancel）关掉这一块，不保存改动。

## 作用于哪些账户

开关下面一行写着 **作用于在这台机器上运行 VS Code、code-server 或 CloudCLI 的账户：**（Applies to the accounts that run VS Code, code-server or CloudCLI here:），后面跟账户名。下面每个账户一行：账户名、它有实例的模块、上一次的结果。

| 结果                                                         | 意思                                 |
| ------------------------------------------------------------ | ------------------------------------ |
| **使用中枢的 AI 网关**                                       | 这个账户的工具已经指向网关           |
| **使用自己原来的设置**（Uses its own settings）              | 这个账户的工具用它自己的设置         |
| **失败**（failed），后面跟错误码的说明                       | 见本页的“某个账户失败时”             |
| **正在等待被控端上报。**（Waiting for the agent to report.） | 开关开着，机器还没上报这个账户的结果 |

机器上还没有这样的账户时，这一行写着 **这台机器上还没有账户运行 VS Code、code-server 或 CloudCLI。**（No account runs VS Code, code-server or CloudCLI on this machine yet.），下面没有账户行。开关照样能打开。以后哪个账户加了实例，机器那时再切换它。

每一步都以这个账户的身份运行。cc-switch 用的是这个账户的 Neutrino 目录里一份单独的存放处，账户自己的 `~/.cc-switch` 和 CC Switch 应用保持原样。

## 关掉

再按一次开关。每个账户的工具切回原来的设置，原来的文件按原样写回。

还有账户指着网关时，开关仍读开着，切回失败的账户也算。这时再按一次，就再试一次切回。

下面这些时候，机器也把账户切回原来的设置：

- 账户的最后一个实例删掉时。
- 运行 `nagent service uninstall` 卸载被控端时。
- 机器离开中枢时。
- 网关不再有可用的模型时。网关又有模型后，机器自动把账户重新指向网关，不用再按开关。

## 某个账户失败时

| 结果                                                                                                    | 原因                                                                                       |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `switch_failed`                                                                                         | cc-switch 没能把工具指向网关，后面带细节                                                   |
| `cc_switch_download_failed`                                                                             | 机器没能从中枢取到 cc-switch                                                               |
| `account_unknown`                                                                                       | 机器上没有这个账户                                                                         |
| `credential_missing`                                                                                    | Windows 上，这个账户的实例没选登录信息；在它所在模块标签的实例上选一条，登录信息存在凭据页 |
| `credential_invalid`                                                                                    | Windows 已经不接受这个账户的登录信息                                                       |
| **cc-switch 没能把工具改回原来的设置：**（cc-switch did not put the tools back to their own settings:） | 切回失败；原来的文件留着，下次切回时写回                                                   |

修好原因后再按开关重试。开关读开着时，先关掉，再打开。

## 同时装了客户端的电脑

受管机器上也装着桌面客户端时，客户端 **AI** 页的开关和 **配置** 是灰的，下面的原因行是 `ai_tools_managed` 的说明，指向中枢面板的模块页。客户端以前把这台电脑的工具指向过网关的，第一次检测到被控端时先切回一次，之后开关保持关闭。客户端的用法见[桌面客户端](../../client/desktop.md)。
