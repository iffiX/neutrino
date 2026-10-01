---
title: AI
---

# AI

The hub runs an AI gateway, CLIProxyAPI, that puts your API keys and subscription accounts behind one endpoint on port 8317. On the **AI** page you add providers and accounts once, and every client gets a key of its own to reach them.

## Add a provider

A provider is an API endpoint the gateway forwards to, keyed with a token stored on the [Credentials](./credentials.md) page. Store the token there first.

1. Under **Providers**, select **Add provider**.
1. Type a **Name** and pick the **Kind**.
1. Optional: set the **Base URL** for a relay; empty uses the service's default.
1. Pick the **API token**.
1. Under **Model aliases**, type one model per line, real name first. Add `= alias` after a name for tools to see it under the alias.
1. Select **Save provider**.
1. Select **Apply providers**. The gateway restarts, and requests in flight fail.

![The providers list](/guide/en/ai_providers.webp)

| Kind                  | Protocol            |
| --------------------- | ------------------- |
| **Anthropic**         | `/v1/messages`      |
| **OpenAI**            | `/v1/responses`     |
| **Gemini**            | `generateContent`   |
| **OpenAI-compatible** | `/chat/completions` |

The kind is the protocol the endpoint speaks, whoever's models are behind it; a relay's `/anthropic` endpoint is **Anthropic**. Devices are told to ask for the first model of a provider. The model names across all providers are the list every machine's tools pick from.

The list is the serving order among providers: drag a row to move it, and the first enabled provider answers first. A row that reads **Needs a token before it can serve** has no token. **Edit** and **Delete** act on one provider; deleting keeps its token stored.

## Sign in to a subscription

A subscription account serves the same models as the providers, and the gateway rotates between them as one pool.

1. Under **Accounts**, select **Sign in** and pick the subscription.
1. Open the address the panel shows. For a code sign-in, enter the code there. For a redirect sign-in, sign in, then copy the address of the page that does not load into **Address bar or code**.
1. Select **Finish sign-in**.

The panel shows how long the code stays valid, and **Expired** after that. An account row shows its successful and failed requests; **Delete** stops it serving at once.

## Share the endpoint and keys

![The Access section with the endpoint and the keys](/guide/en/ai_keys.webp)

**Access** shows the **Endpoint**, the box's address on the gateway port. Each client that joins gets a key named `client/` followed by the client's name. For a machine that runs no client:

1. Select **Generate key**.
1. Name the key after what uses it, such as `laptop`, and select **Generate**.
1. Copy the key. The panel shows it once, with **Paste it into the tool beside the endpoint above.**

Each row shows when the key was last used. **Revoke** cuts off whatever holds the key at once. A revoked client key is replaced, and the hub sends the new key to that client.

The client's own AI panel points its tools at the endpoint; [Desktop client](../client/desktop.md) covers it.

## Read usage

**Activity** shows the models the gateway serves, today's requests and tokens, and **Journal**, the gateway's last log lines. Select a model name to copy it.

Under it, the grid shows the last 30 days by **Providers** or by **Keys**. **Usage unavailable** means the gateway is not reporting usage yet.

## Change the gateway port

**Gateway port** is the TCP port the gateway listens on, 8317 by default.

1. Type the new **Port**.
1. Select **Apply gateway port**. The gateway restarts on the new port.

::: warning
Every machine pointed at the old port loses the gateway until its endpoint changes too. Apply each client's AI panel again, and type the new endpoint into every tool set up by hand.
:::
