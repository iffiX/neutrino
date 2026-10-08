---
title: AI
---

# AI

The **AI** page sets up the hub's AI gateway, CLIProxyAPI, which serves your API keys and subscription accounts behind one endpoint on port 8317. Every client and managed machine reaches it with a key of its own.

## Add a provider

A provider is an API endpoint. Before you start, store the provider's API key as a token on the [Credentials](./credentials.md) page. To add the provider:

1. Under **Providers**, select **Add provider**.
1. Type a **Name** and pick the **Kind**.
1. Optional: set the **Base URL** of a relay service.
1. Pick the **API token**.
1. Under **Model aliases**, type one model per line. Add `= alias` after a name to show it to tools under that alias.
1. Select **Save provider**.
1. Select **Apply providers**. The gateway restarts, and requests in flight fail.

![The providers list](/guide/en/ai_providers.webp)

| Kind                  | Protocol            |
| --------------------- | ------------------- |
| **Anthropic**         | `/v1/messages`      |
| **OpenAI**            | `/v1/responses`     |
| **Gemini**            | `generateContent`   |
| **OpenAI-compatible** | `/chat/completions` |

The kind is the protocol the endpoint speaks, so DeepSeek's `/anthropic` endpoint is **Anthropic**. Drag a row to change the serving order.

## Sign in to a subscription

To add a subscription account:

1. Under **Accounts**, select **Sign in** and pick the subscription.
1. Open the address the dialog shows. For a code sign-in, enter the code there. For a redirect sign-in, sign in, then copy the address of the page that fails to load into **Address bar or code**.
1. Select **Finish sign-in**.

The dialog counts down how long the code stays valid. When the sign-in does not finish, select **Try again**; the codes are on [Troubleshooting](../reference/troubleshooting.md#an-ai-tool-ignores-the-gateway). **Delete** on an account row stops the account serving at once.

## Share the endpoint and keys

![The Access section with the endpoint and the keys](/guide/en/ai_keys.webp)

**Access** shows the **Endpoint**. Each client that joins gets a key named `client/` followed by its name. For a machine that runs no client:

1. Under **Access**, select **Generate key**.
1. Name the key after what uses it, and select **Generate**.
1. Copy the key. The panel shows it one time.

**Revoke** cuts off whatever holds a key at once. A revoked client key is replaced, and the hub sends the new key to that client.

## Point machines at the gateway

On a person's computer, the client's AI page points the local tools at the endpoint, as described in [Desktop client](../client/desktop.md). On a managed machine, the **AI tools** section of the **Modules** page does it for each account, as described in [AI tools](../agent/modules/ai_tools.md).

## Read usage

**Activity** shows the models the gateway serves and today's requests and tokens. Under it, a grid shows the last 30 days by **Providers** or by **Keys**.

## Change the gateway port

1. Under **Gateway port**, type the new **Port**.
1. Select **Apply gateway port**. The gateway restarts on the new port.

Clients and managed machines follow the new port by themselves. Type the new endpoint into every tool set up by hand with a generated key.
