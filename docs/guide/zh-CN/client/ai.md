---
title: AI
---

# AI

客户端的 **AI** 面板把这台电脑上的 Claude Code、Codex 和 Gemini CLI 切到 hub 的网关，关掉开关又切回原来的配置。

## 条目从哪来

**AI** 面板只有一条，来源行写着由 AI 网关发布。这条服务的端点是 hub 的 AI 网关地址；密钥是这个客户端接入时 hub 按客户端名字发的一把，在 hub 的 AI 页里写作 `client/<name>`。hub 还没发密钥时按钮返回 `no_endpoint`。

## 配置

![AI 工具配置](/guide/zh/client_ai_config.webp)

点 **配置**（Config）打开 **AI 工具配置**（AI tool configuration），三个工具各一节：

| 工具        | 可选项                                                                                                                  |
| ----------- | ----------------------------------------------------------------------------------------------------------------------- |
| Claude Code | **默认模型**（Default model）、**Opus 档位**（Opus slot）、**Sonnet 档位**（Sonnet slot）、**Haiku 档位**（Haiku slot） |
| Codex       | **模型**（Model）、**推理强度**（Reasoning effort）：minimal、low、medium、high                                         |
| Gemini      | **模型**（Model）                                                                                                       |

每一项都可以留在 **网关默认**（gateway default），也就是网关模型别名里的第一行。点 **保存**（Save）只是暂存，机器上还没有任何改动；条目卡片随即高亮，表示有未应用的改动。

## 应用

![客户端的 AI 面板](/guide/zh/client_ai_panel.webp)

1. 打开 **启用**（Enabled）开关。
1. 点 **应用**（Apply）。

按钮短暂显示 **正在切换工具…**，然后开关旁写 **工具已指向 hub**（the tools point at the hub）。客户端用自带的 cc-switch 改写三个工具各自的配置文件，全部成功或全部不改。改写前的配置保存在客户端的配置目录下。

## 关闭

关掉 **启用** 再点 **应用**，每个工具恢复改写前的配置，开关旁写 **工具保持原样**（the tools are as they were）。

## 命令行

```bash
nclient service ai show
nclient service ai apply hub --claude-default '' --codex-effort medium
nclient service ai apply off
```

`show` 打印每个工具现在指向哪里。`apply hub` 指向网关，每个模型参数省略则保持现值，传 `''` 则回到网关默认；`apply off` 还原。
