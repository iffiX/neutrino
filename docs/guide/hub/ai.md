---
title: AI
---

# AI

Your subscriptions and API keys sit behind one gateway address on the hub: CLIProxyAPI on port 8317. On the **AI** page you add them, and the hub issues each client a key of its own.

## Providers

A provider is an endpoint the gateway forwards to, keyed with a stored token. The list is the serving order: the first enabled provider answers first.

1. In the panel, open **AI**.
1. Under **Providers**, select **Add provider**.
1. Fill **Name**, pick the **Kind**, and set the **Base URL** for a relay or leave it empty for the service's default.
1. Pick the **API token** from the tokens stored on [the Credentials page](./credentials.md).
1. Under **Model aliases**, type one model per line, real name first. Add `= alias` after a name where the tools are to see it under another name.
1. Select **Save provider**, then **Apply providers**.

![The providers list](/guide/en/ai_providers.webp)

| Kind                  | Protocol            |
| --------------------- | ------------------- |
| **Anthropic**         | `/v1/messages`      |
| **OpenAI**            | `/v1/responses`     |
| **Gemini**            | `generateContent`   |
| **OpenAI-compatible** | `/chat/completions` |

The kind is the protocol the endpoint speaks, whatever models are behind it. A relay's `/anthropic` endpoint is **Anthropic**. Applying restarts the gateway, and requests in flight fail.

## Subscription accounts

You sign in to a subscription once, and the gateway serves that account and the API providers as one pool.

1. Under **Accounts**, select **Sign in** and pick the subscription.
1. Open the address the panel shows in a browser and enter the code there; for a redirect sign-in, the browser ends on a page that does not load, and its address goes into **Address bar or code**.
1. Select **Finish sign-in**.

![The accounts list with a signed-in subscription](/guide/en/ai_accounts.webp)

The code's remaining lifetime is shown as **Expires in** followed by the time left. A gateway with no subscription sign-in reads **This gateway offers no subscription sign-in.**

## Access: the endpoint and the keys

**Access** shows the **Endpoint**, `http://<hub>:8317` unless the port was changed, where `<hub>` is the box's address. The keys under it are named after the clients they were handed to: a client that joins gets a key of its own, listed as the client's name.

1. Select **Generate key** for a machine that runs no client.
1. Name it after what uses it. The key is shown once, with **Paste it into the tool beside the endpoint above.**

![The Access section with the endpoint and the keys](/guide/en/ai_keys.webp)

**Revoke** cuts off whatever holds the key at once. When the key belongs to a client, the hub generates a new key and sends it to that client.

## Usage and journal

**Activity** shows today's requests and tokens. The usage grid shows the last 30 days by provider and by key. **Usage unavailable** means the gateway is not reporting usage yet. **Journal** shows the gateway's last log lines.

![The usage grid](/guide/en/ai_usage.webp)

## Gateway port

**Gateway port** is the TCP port the gateway listens on. **Apply gateway port** restarts the gateway on the new port. Every machine pointed at the old port stops reaching the gateway until its endpoint is changed too.

## On the client

The client's **AI** panel has one entry, with an **Enabled** switch, **Config** and **Apply**.

![The AI panel in the client window](/guide/en/client_ai_panel.webp)

1. Select **Config**. The **AI tool configuration** dialog lists **Claude Code**, **Codex** and **Gemini**, with a model picker per slot that offers **gateway default**.
   ![The AI tool configuration dialog](/guide/en/client_ai_config.webp)
1. Pick the models and select **Save**. The choice is staged; the machine is unchanged.
1. Switch **Enabled** on and select **Apply**.

The line beside the switch reads **the tools point at the hub**. Switching **Enabled** off and applying again restores each tool's previous configuration, and the line reads **the tools are as they were**. [The client's AI page](../client/ai.md) has the terminal form.
