---
title: AI
---

# AI

这台电脑上的 Claude Code、Codex 和 Gemini CLI 指向一个 hub 的 AI 网关，也就是出口 hub 的网关。客户端的 **AI** 面板负责切过去，也负责切回来。

## 条目从哪来

每个跑着网关的 hub 都在自己那一组里发布一条 AI 条目，带 **启用**（Enabled）开关、**配置**（Config）和 **应用**（Apply）。只有出口 hub 那一条能动：其余 hub 的同一条写着 **AI 工具指向** 加上出口 hub 的名字，按钮都不可用。

密钥是 hub 的 AI 页给每个客户端单独发的一把，每次应用时取到这台电脑。hub 还没发密钥时，应用返回 `no_endpoint`。

## 选出口 hub

点 **Hub** 区某一行上的 **出口**（Exit）单选，出口就换成这个 hub。几个 AI 面板随即跟着变，按钮交给新出口 hub 的那一条。只有写着 **已连接**（Connected）的 hub 能当出口。终端里 `nclient service ai apply hub --hub <name>` 先换出口再应用，一条命令做完。[窗口页](./window.md)写了这一行上还有什么。

## 配置

![AI 工具配置](/guide/zh/client_ai_config.webp)

点 **配置** 打开 **AI 工具配置**（AI tool configuration），三个工具各一节：

| 工具        | 可选项                                                                                                                  |
| ----------- | ----------------------------------------------------------------------------------------------------------------------- |
| Claude Code | **默认模型**（Default model）、**Opus 档位**（Opus slot）、**Sonnet 档位**（Sonnet slot）、**Haiku 档位**（Haiku slot） |
| Codex       | **模型**（Model）、**推理强度**（Reasoning effort）：minimal、low、medium、high                                         |
| Gemini      | **模型**（Model）                                                                                                       |

每一项都可以留在 **网关默认**（gateway default），也就是网关模型别名里的第一行。模型表是出口 hub 自己的，换一个出口就换一份表。点 **保存**（Save）只是暂存，机器上还没有任何改动；条目卡片随即高亮，表示有未应用的改动。

## 应用

![客户端的 AI 面板](/guide/zh/client_ai_panel.webp)

1. 打开 **启用** 开关。
1. 点 **应用**。

按钮短暂显示 **正在切换工具…**，然后开关旁写 **工具已指向 hub**（the tools point at the hub）。客户端用自带的 cc-switch 改写三个工具各自的配置文件，全部成功或全部不改。改写前的配置保存在客户端的配置目录下。

工具开着的时候换出口，同样是一次应用，工具从旧网关直接转到新网关。

## 关闭

关掉 **启用** 再点 **应用**，每个工具恢复改写前的配置，开关旁写 **工具保持原样**（the tools are as they were）。

## 命令行

```bash
nclient service ai show
nclient service ai apply hub --claude-default '' --codex-effort medium
nclient service ai apply off
```

`show` 打印每个工具现在指向哪里，不带 `--hub` 时看的是出口 hub。`apply hub` 指向出口 hub 的网关，每个模型参数省略则保持现值，传 `''` 则回到网关默认；`apply off` 还原。
