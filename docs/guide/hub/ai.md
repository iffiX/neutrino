---
title: AI
---

# AI

The hub runs an AI gateway, CLIProxyAPI, that serves your API keys and subscription accounts behind one endpoint on port 8317. On the **AI** page you add each provider and account one time. Every client and managed machine then reaches them with a key of its own.

## Add a provider

A provider is an API endpoint the gateway forwards to, keyed with a token stored on the [Credentials](./credentials.md) page. Before you start, store the provider's API key there as a token.

1. Under **Providers**, select **Add provider**.
1. Type a **Name** and pick the **Kind**.
1. Optional: set the **Base URL** of a relay service. Empty uses the service's default.
1. Pick the **API token**.
1. Under **Model aliases**, type one model per line, real name first. Add `= alias` after a name for tools to see it under that alias.
1. Select **Save provider**.
1. Select **Apply providers**. The gateway restarts, and requests in flight fail.

![The providers list](/guide/en/ai_providers.webp)

| Kind                  | Protocol            |
| --------------------- | ------------------- |
| **Anthropic**         | `/v1/messages`      |
| **OpenAI**            | `/v1/responses`     |
| **Gemini**            | `generateContent`   |
| **OpenAI-compatible** | `/chat/completions` |

The kind is the protocol the endpoint speaks, whoever's models are behind it, so DeepSeek's `/anthropic` endpoint is **Anthropic**. A provider's first model is the default the machines ask for. The model names across all providers form the list every machine's tools pick from.

The list is the serving order: drag a row to move it, and the first enabled provider answers first. A row that reads **Needs a token before it can serve** has no token. **Edit** and **Delete** act on one provider, and deleting it keeps its token stored.

## Sign in to a subscription

A subscription account serves models beside the providers, and the gateway picks from accounts and API keys as one pool.

1. Under **Accounts**, select **Sign in** and pick the subscription.
1. Open the address the dialog shows. For a code sign-in, enter the code there. For a redirect sign-in, sign in, then copy the address of the page that fails to load into **Address bar or code**.
1. Select **Finish sign-in**.

The dialog shows how long the sign-in stays open, then **Expired**. When the hub's sign-in session times out, the dialog keeps its current screen and shows `login_expired`, a sign-in that took too long. Select **Try again** to start a new one. Any other failure reads **The sign-in did not finish.**, with the gateway's own reason under it.

An account row shows its successful and failed requests. **Delete** stops the account serving at once.

## Share the endpoint and keys

![The Access section with the endpoint and the keys](/guide/en/ai_keys.webp)

**Access** shows the **Endpoint**, the box's address on the gateway port. Each client that joins gets a key named `client/` followed by the client's name, and the hub sends it to the client. For a machine that runs no client:

1. Under **Access**, select **Generate key**.
1. Name the key after what uses it, such as `laptop`, and select **Generate**.
1. Copy the key. The panel shows it one time, with **Paste it into the tool beside the endpoint above.**

Each row shows when its key was last used. **Revoke** cuts off whatever holds the key at once. A revoked client key is replaced, and the hub sends the new key to that client.

## Point machines at the gateway

On a person's computer, the client's own AI page sets the local tools to use the endpoint, as described in [Desktop client](../client/desktop.md).

On a managed machine, the **AI tools** section of the **Modules** page points each account's tools at the gateway, as described in [AI tools](../agent/modules/ai_tools.md).

## Read usage

**Activity** shows the models the gateway serves, today's requests and tokens, and **Journal**, the gateway's last log lines. Select a model name to copy it.

Under it, a grid shows the last 30 days by **Providers** or by **Keys**. **Usage unavailable** means the gateway is not reporting usage.

## Change the gateway port

**Gateway port** is the TCP port the gateway listens on, 8317 by default.

1. Type the new **Port**.
1. Select **Apply gateway port**. The gateway restarts on the new port.

::: warning
Every machine pointed at the old port loses the gateway until its endpoint changes too. Apply each client's AI page again, and type the new endpoint into every tool set up by hand.
:::
