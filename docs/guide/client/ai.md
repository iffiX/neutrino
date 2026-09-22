---
title: AI
---

# AI

Claude Code, Codex and Gemini CLI on this computer point at one hub's gateway, the target hub's. The client's **AI** panel is what points them there and back.

## Where the entry comes from

Every hub running a gateway publishes one entry in its own group, with an **Enabled** switch, **Config** and **Apply**. Only the target hub's panel acts. On every other hub the same entry reads **the AI tools point at** the target hub's name, with its buttons inert.

The hub's **AI** page issues each client a key of its own, and the key reaches this computer during an apply. An apply on a client the hub has issued no key to is rejected with `no_endpoint`.

## Choose the target hub

The **Target** radio on a row of the **Hubs** section moves the target. The AI panels follow at once, and the buttons pass to the new target hub's panel. Only a hub reading **Connected** takes the target. From a terminal, `nclient service ai apply hub --hub <name>` moves the target to the hub of that name and applies in one step. [The window](./window.md) describes the rest of the row.

## Config

1. Select **Config**. The **AI tool configuration** dialog opens.
1. Under **Claude Code**, pick a **Default model**, and a model for the **Opus slot**, **Sonnet slot** and **Haiku slot**.
1. Under **Codex**, pick the **Model** and the **Reasoning effort**: `minimal`, `low`, `medium` or `high`.
1. Under **Gemini**, pick the **Model**.
1. Select **Save**.

![The AI tool configuration dialog](/guide/en/client_ai_config.webp)

Every picker offers **gateway default**, the first model the gateway lists. The models are the target hub's own, so a move to another hub brings another list. **Save** stages the choice, and the machine is unchanged until **Apply**.

## Apply

1. Switch **Enabled** on.
1. Select **Apply**. The button reads **switching the tools…**, then the line beside the switch reads **the tools point at the hub**.

The client includes cc-switch, a tool that rewrites each AI tool's own configuration. The apply runs it, and the configuration then names the gateway's endpoint, the key and the chosen models. The apply is all or nothing across the tools: when one tool's configuration cannot be written, none is changed.

Moving the target while the tools are on is one apply as well, straight from the old gateway to the new one.

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

`show` prints where the tools point, for the target hub unless `--hub` names another. `apply hub` points them at the target hub's gateway. The flags `--claude-default`, `--claude-opus`, `--claude-sonnet`, `--claude-haiku`, `--codex-model`, `--codex-effort` and `--gemini-model` set the slots. An omitted flag keeps the saved choice, and `''` means the gateway default. `apply off` puts the tools back.
