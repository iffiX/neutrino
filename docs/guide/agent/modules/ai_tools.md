---
title: Point a machine's AI tools at the gateway
---

# Point a machine's AI tools at the gateway

Claude Code, Codex and Gemini on a managed machine can send their requests to the hub's AI gateway. One setting per machine switches them for every account that runs VS Code, code-server or CloudCLI there. Each such account's row then reads **Uses the hub's AI gateway**.

Before you begin, the hub's [AI](../../hub/ai.md) page must serve at least one model. Each account you want switched needs an instance of VS Code, code-server or CloudCLI on the machine.

![The Global configuration panel of server, with two accounts reading Uses the hub's AI gateway](/guide/en/modules_ai_tools.webp)

## Turn it on

1. Open the **Modules** page.
1. Under **Which machine**, select the machine.
1. Under **Global configuration**, select **This machine's AI tools use the hub's AI gateway**.

The press takes effect at once, and the panel has no apply bar. The control is greyed while the machine's agent is offline. While the gateway serves no model, the control is greyed too. The line under it then reads **The hub's AI gateway serves no model yet; set it up on the AI page first.**

The first time a machine uses the setting, its agent fetches cc-switch from the hub. cc-switch is the program that rewrites each tool's settings for an account.

## Choose the models

1. Under **Global configuration**, select **Configure**.
1. Under **Claude Code**, pick a model for **Default model**, **Opus slot**, **Sonnet slot** and **Haiku slot**.
1. Under **Codex**, pick the **Model** and the **Reasoning effort**.
1. Under **Gemini**, pick the **Model**.
1. Select **Save**.

Every picker offers **gateway default**, which leaves that choice to the gateway. **Cancel** closes the form without saving.

## Which accounts it acts on

The line under the control reads **Applies to the accounts that run VS Code, code-server or CloudCLI here:** and names them. These are the accounts with an instance in the machine's VS Code, code-server or CloudCLI configuration. Each has a row with its name, the modules it has an instance in, and its result:

| Result                               | The account's tools                                                                 |
| ------------------------------------ | ----------------------------------------------------------------------------------- |
| **Uses the hub's AI gateway**        | send their requests to the gateway                                                  |
| **Uses its own settings**            | use the settings they had before the switch                                         |
| a red dot and the failure's words    | were not switched; [When an account fails](#when-an-account-fails) lists the causes |
| **Waiting for the agent to report.** | have not been reported on by the machine yet                                        |

With no such account, the line reads **No account runs VS Code, code-server or CloudCLI on this machine yet.**

You can turn the setting on all the same, and an account that gets an instance later is switched at that point.

The agent runs cc-switch with a store of its own in each account's Neutrino folder. The account's own `~/.cc-switch`, and the CC Switch app that keeps its data there, stay as they were.

## Turn it off

Select **This machine's AI tools use the hub's AI gateway** again. The agent switches every account back, and cc-switch removes the gateway from its settings. Each file the switch changed, such as `~/.claude/settings.json` or `~/.codex/config.toml`, is written back byte for byte as it was before.

The control reads on while any account still points at the gateway, including an account whose switch back failed. A press in that state tries the switch back again. The control reads off when every account uses its own settings.

The agent also switches an account back when its last instance is removed, when the machine leaves the hub, and when the agent is uninstalled.

## When an account fails

| Code                        | Cause                                                                    |
| --------------------------- | ------------------------------------------------------------------------ |
| `switch_failed`             | cc-switch could not point the account's tools at the gateway             |
| `cc_switch_download_failed` | the machine could not get cc-switch from the hub                         |
| `account_unknown`           | the machine has no account by that name                                  |
| `credential_missing`        | on Windows, the account's instance has no Windows login picked           |
| `credential_invalid`        | on Windows, the account's password changed and the stored login is stale |

A switch back that fails reads **cc-switch did not put the tools back to their own settings:** followed by what cc-switch printed. The control then stays on.

To try a failed switch again, turn the setting on again. When the control still reads on because other accounts were switched, select it twice, off and then on.

## A computer that also runs the client

On a computer with both the agent and the desktop client, the client's **AI** page is greyed. Its reason line shows `ai_tools_managed`: **This is a managed device: set its AI tools on the hub's panel, under Modules, Global configuration.** When the client had pointed the tools at the gateway earlier, it switches them back one time.

The [Desktop client](../../client/desktop.md) page covers the **AI** page on a computer without the agent.
