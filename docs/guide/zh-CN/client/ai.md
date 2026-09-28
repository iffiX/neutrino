---
title: AI
---

# AI

这台电脑上的 Claude Code、Codex 和 Gemini CLI 指向一个 hub 的 AI 网关，也就是目标 hub 的网关。客户端的 **AI** 页负责切过去，也负责切回来。

## 条目从哪来

每个跑着网关的 hub 发布一条 AI 条目，**AI** 页把它们列在同一块面板里。每条有 **配置**（Config）和 **AI 工具使用此网关**（The AI tools use this gateway）开关，同一时间最多开一个。

密钥是 hub 的 AI 页给每个客户端单独发的一把，工具切过去时取到这台电脑。hub 还没给这个客户端发密钥时，打开开关返回 `no_endpoint`。

## 打开一个网关

点要用的那个网关的开关。它的 hub 成为目标，工具指向这个网关，原来开着的开关随之关上。切换期间条目写 **正在切换工具…**，切完写 **工具已指向 hub**（the tools point at the hub）。只有写着 **已连接**（Connected）的 hub 能打开；通道断着的返回 `no_exit_hub`。

客户端用自带的 cc-switch 改写三个工具各自的配置文件，全部成功或全部不改。改写前的配置保存在客户端的配置目录下。从一个网关换到另一个，也是一次改写，工具从旧网关直接转到新网关。

## 配置

![AI 工具配置](/guide/zh/client_ai_config.webp)

点条目上的 **配置**，打开 **AI 工具配置**（AI tool configuration），三个工具各一节：

| 工具        | 可选项                                                                                                                  |
| ----------- | ----------------------------------------------------------------------------------------------------------------------- |
| Claude Code | **默认模型**（Default model）、**Opus 档位**（Opus slot）、**Sonnet 档位**（Sonnet slot）、**Haiku 档位**（Haiku slot） |
| Codex       | **模型**（Model）、**推理强度**（Reasoning effort）：minimal、low、medium、high                                         |
| Gemini      | **模型**（Model）                                                                                                       |

每一项都可以留在 **网关默认**（gateway default），也就是网关模型别名里的第一行。模型表是那个 hub 自己的，换一个网关就换一份表。正在用的网关上，点 **保存**（Save）立刻按新选择改写工具；别的网关上，选择先存着，等打开它的开关时一起生效。

## 关闭

![客户端的 AI 面板](/guide/zh/client_ai_panel.webp)

点开着的那个开关，每个工具恢复第一次改写前的配置。

## 命令行

```bash
nclient service ai show
nclient service ai apply hub --claude-default '' --codex-effort medium
nclient service ai apply off
```

`show` 打印每个工具现在指向哪里，不带 `--hub` 时看的是目标 hub。`apply hub` 指向目标 hub 的网关，带 `--hub <name>` 时先把目标换成那个 hub。每个模型参数省略则保持现值，传 `''` 则回到网关默认；`apply off` 还原。
