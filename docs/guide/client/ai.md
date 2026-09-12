---
title: AI
---

# AI

The client's **AI** panel points Claude Code, Codex and Gemini CLI on your computer at the hub's AI gateway. One switch puts them back.

## Where the entry comes from

The **AI** panel has one entry, published by the hub's AI gateway, with an **Enabled** switch, **Config** and **Apply**. The hub's **AI** page issues each client a key of its own, and the key arrives with the entry. An apply on a client the hub has issued no key to is rejected with `no_endpoint`.

## Config

1. Select **Config**. The **AI tool configuration** dialog opens.
1. Under **Claude Code**, pick a **Default model**, and a model for the **Opus slot**, **Sonnet slot** and **Haiku slot**.
1. Under **Codex**, pick the **Model** and the **Reasoning effort**: `minimal`, `low`, `medium` or `high`.
1. Under **Gemini**, pick the **Model**.
1. Select **Save**.

![The AI tool configuration dialog](/guide/en/client_ai_config.webp)

Every picker offers **gateway default**, the first model the gateway lists. **Save** stages the choice, and the machine is unchanged until **Apply**.

## Apply

1. Switch **Enabled** on.
1. Select **Apply**. The button reads **switching the tools…**, then the line beside the switch reads **the tools point at the hub**.

The client includes cc-switch, a tool that rewrites each AI tool's own configuration. The apply runs it, and the configuration then names the gateway's endpoint, the key and the chosen models. The apply is all or nothing across the tools: when one tool's configuration cannot be written, none is changed.

## Off

1. Switch **Enabled** off.
1. Select **Apply**. The line reads **the tools are as they were**.

![The AI panel with the tools pointed at the hub](/guide/en/client_ai_panel.webp)

Each tool's previous configuration is restored as it was before the first apply.

## The command line

```bash
nclient service ai show
nclient service ai apply hub --claude-default '' --codex-effort medium
nclient service ai apply off
```

`show` prints where the tools point. `apply hub` points them at the gateway. The flags `--claude-default`, `--claude-opus`, `--claude-sonnet`, `--claude-haiku`, `--codex-model`, `--codex-effort` and `--gemini-model` set the slots. An omitted flag keeps the saved choice, and `''` means the gateway default. `apply off` puts the tools back.
