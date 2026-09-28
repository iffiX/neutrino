---
title: AI
---

# AI

Claude Code, Codex and Gemini CLI on this computer point at one hub's gateway, the target hub's. The client's **AI** page is what points them there and back.

## Where the entries come from

Every hub running a gateway publishes one entry, and the **AI** page lists them all in one panel. Each entry has **Config** and a **The AI tools use this gateway** switch, and one switch at most is on.

The hub's **AI** page issues each client a key of its own, and the key reaches this computer when the tools are pointed. A switch on a hub that has issued this client no key is rejected with `no_endpoint`.

## Switch a gateway on

Select the switch on the gateway you want. Its hub becomes the target, the tools point at its gateway, and the switch that was on goes off. The entry reads **switching the tools…** while the tools change, then **the tools point at the hub**. Only a hub reading **Connected** takes the switch; one whose channel is down is rejected with `no_exit_hub`.

The client includes cc-switch, a tool that rewrites each AI tool's own configuration. Switching runs it, and the configuration then names the gateway's endpoint, the key and the chosen models. The change is all or nothing across the tools: when one tool's configuration cannot be written, none is changed. Moving from one gateway to another is one change, straight from the old gateway to the new.

## Config

1. Select **Config** on the entry. The **AI tool configuration** dialog opens.
1. Under **Claude Code**, pick a **Default model**, and a model for the **Opus slot**, **Sonnet slot** and **Haiku slot**.
1. Under **Codex**, pick the **Model** and the **Reasoning effort**: `minimal`, `low`, `medium` or `high`.
1. Under **Gemini**, pick the **Model**.
1. Select **Save**.

![The AI tool configuration dialog](/guide/en/client_ai_config.webp)

Every picker offers **gateway default**, the first model the gateway lists. The models are that hub's own, so another gateway brings another list. On the gateway in use, **Save** points the tools with the new choice at once; on any other, the choice waits for its switch.

## Off

Select the switch that is on. Each tool's previous configuration is restored as it was before the tools were first pointed.

![The AI panel with the tools pointed at the hub](/guide/en/client_ai_panel.webp)

## The command line

```bash
nclient service ai show
nclient service ai apply hub --claude-default '' --codex-effort medium
nclient service ai apply off
```

`show` prints where the tools point, for the target hub unless `--hub` names another. `apply hub` points them at the target hub's gateway, and `--hub <name>` moves the target to that hub first. The flags `--claude-default`, `--claude-opus`, `--claude-sonnet`, `--claude-haiku`, `--codex-model`, `--codex-effort` and `--gemini-model` set the slots. An omitted flag keeps the saved choice, and `''` means the gateway default. `apply off` puts the tools back.
