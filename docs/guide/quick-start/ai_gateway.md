---
title: AI tools share the hub's gateway
---

# AI tools share the hub's gateway

Your API key or subscription goes into the hub one time. Claude Code and Codex on the computer, and on a laptop with the client, then send their requests through the hub's AI gateway.

Before you start, finish the [Step zero](../quick-start.md), and have an API key or a subscription account at hand.

## Put your key or subscription into the hub

With an API key, store it and add its provider:

1. In the panel's sidebar, open **Credentials**.
1. Under **Tokens**, select **Add token**, fill **Name** and paste the key into **Value**.
1. Select **Save token**.
1. Open **AI**, and under **Providers**, select **Add provider**.
1. Type a **Name**, pick the **Kind** of the key's service, such as **Anthropic** for an Anthropic key, and pick the token under **API token**.
1. Under **Model aliases**, type one model name per line, spelled as the provider spells it.
1. Select **Save provider**.
1. Select **Apply providers**.

With a subscription, sign in to it instead:

1. On the **AI** page, under **Accounts**, select **Sign in** and pick the subscription.
1. Open the address the dialog shows, and sign in there.
1. For a code sign-in, enter the code on that page. For a redirect sign-in, copy the address of the page that fails to load into **Address bar or code**.
1. Select **Finish sign-in**.

**Activity**, at the top of the **AI** page, reads **Serving** and the number of models.

![The providers list on the AI page](/guide/en/ai_providers.webp)

## Point the computer's tools at the gateway

1. Open **Modules**.
1. Under **Which machine**, select your computer.
1. Under **Global configuration**, select **This machine's AI tools use the hub's AI gateway**.

The line under the switch names the accounts that run VS Code, code-server or CloudCLI on the computer. Each one's row reads **Uses the hub's AI gateway**. Claude Code in that account now sends its requests through the gateway, in a terminal and in the CloudCLI sessions you open on the phone.

![Global configuration with two accounts using the hub's AI gateway](/guide/en/modules_ai_tools.webp)

When a row shows a red dot, [Troubleshooting](../reference/troubleshooting.md#ai-tools) lists its cause.

## Point the laptop's tools at the gateway

If you have no laptop, skip this section.

1. In the laptop's client window, open **AI**.
1. On the hub's entry, select **The AI tools use this gateway**.

The entry reads **Switching tools…**, then **The tools point at the hub**. Claude Code, Codex and Gemini CLI on the laptop reach the gateway while the client runs in the tray.

![The laptop's AI page with the tools pointing at the hub](/guide/en/client_ai_on.webp)

## Read the usage per key

- On the **AI** page, under **Activity**, select **Keys**.

A table lists each key's requests and tokens over the last 30 days. The laptop's key is named `client/` followed by the laptop's name. **Access**, lower on the page, lists the same keys with when each was last used.

![The Access section with the endpoint and the keys](/guide/en/ai_keys.webp)
