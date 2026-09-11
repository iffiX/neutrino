---
title: AI gateway
---

# AI gateway

The AI gateway is one endpoint on the hub that every machine's AI tools point
at, and the panel decides which provider answers. It carries CLIProxyAPI, and
it answers on port `8317`.

What this page does not do:

- It routes; it does not choose models for you. There are no model
  recommendations here.
- Accounts and API keys serve as one pool. The gateway picks between them.
- A key is shown once and is not shown again.
- Save in the client's Config dialog only stages the change. Nothing on the
  machine moves until Apply.
- Running Ollama beside the gateway does not exist.

## Providers

Open **AI**.

Expect: the page headed "AI", subtitled "One endpoint for every machine's AI
tools; which provider answers is switched here.", with Activity at the top and
Providers below. With none added it reads "No providers yet" and "Add an API
endpoint and token once, instead of pasting it into every machine."

Press "Add provider", then fill Name, Kind, Base URL, API token and Model
aliases.

Expect: Kind offers four protocols, "Anthropic, /v1/messages", "OpenAI,
/v1/responses", "Gemini, generateContent" and "OpenAI-compatible,
/chat/completions". The token is picked from the vault, not typed twice: "The
stored token this endpoint is keyed with."

The Kind is the protocol the endpoint speaks, not whose models are behind it.
DeepSeek's `/anthropic` endpoint is Anthropic.

Press "Save provider", then "Apply providers".

Expect: "Saves the serving order and which providers are enabled, then reloads
the gateway.", under the warning "The gateway restarts, and requests in flight
fail." A gateway left behind reads "The gateway is serving an older
configuration; applying reloads it."

![The AI page's provider list, with two endpoints and their model aliases](/guide/en/ai_providers.webp)

The provider list is the serving order: the first enabled provider answers
first. Model aliases go one per line, real name first, with `= alias` where
tools should see a different name; devices are told to ask for the first one.

## Accounts by device code

In "Accounts", press "Sign in" and pick a subscription.

Expect: either a device code with "Open this address and enter the code
there.", or an address to sign in at whose final URL you paste back into
"Address bar or code": "Open this address and sign in. The browser lands on a
page that does not load; its address goes below."

Finish at the provider, then press "Finish sign-in".

Expect: the account appears and serves alongside the API providers, because
"Accounts and API keys serve the same models as one pool; the gateway picks
between them."

![The AI accounts section with one signed-in subscription](/guide/en/ai_accounts.webp)

A code that sat too long reads "Expired", and a gateway with no subscription
flow reads "This gateway offers no subscription sign-in."

## Client keys

In "Access", read the endpoint at the top.

Expect: `http://<hub>:8317`, unless the gateway port was changed.

Press "Generate key" and name it after the machine that will hold it.

Expect: the key is shown once, with "Paste it into the tool beside the endpoint
above."

![The Access section with the gateway endpoint and the key list](/guide/en/ai_keys.webp)

A client that joins is handed a key named after it, so this button is for a
machine no client runs on. A client that has not been handed one refuses with
"the hub has not granted you a key yet".

::: warning Revoking a key
Revoking a key stops whatever holds it from reaching the gateway at once, and
that tool needs a new key to get back in.

A revoked client key is replaced without you doing anything: "{client} stops
reaching the gateway at once and is handed a new key." A hand-made key is not;
generate another and paste it in.
:::

The gateway port is "The TCP port the gateway answers on." Changing it restarts
the gateway, and "Every machine pointed at the old port stops reaching the
gateway until its endpoint is changed too."

## Usage

Read the usage grid.

Expect: the last 30 days, by provider and by key, with requests today and
tokens today in Activity above it.

![The AI usage grid over the last 30 days, by provider and by key](/guide/en/ai_usage.webp)

Where the gateway reports nothing, the section reads "Usage unavailable" and
"The gateway is not reporting usage on this box yet."

## On the client: Config then Apply

In the client window, in the AI panel, press "Config".

Expect: the "AI tool configuration" dialog, with three headings in order,
Claude Code, Codex and Gemini. Every model field offers "(gateway default)" as
its empty value.

![The client's AI tool configuration dialog with the Claude Code slots](/guide/en/client_ai_config.webp)

Claude Code has four slots: Default model, Opus slot, Sonnet slot and Haiku
slot. Codex has Model and Reasoning effort, which is `minimal`, `low`, `medium`
or `high`. Gemini has Model.

Pick the models and press "Save".

Expect: the dialog closes and the AI panel is marked as changed. Nothing on the
machine has moved yet.

Switch "Enabled" on and press "Apply".

Expect: Apply reads "switching the tools…", then the line beside the toggle
reads "the tools point at the hub".

![The client's AI panel enabled, reading that the tools point at the hub](/guide/en/client_ai_panel.webp)

The same thing from a terminal:

```bash
nclient service ai apply hub --claude-default '' --codex-effort medium
```

Expect: the three tools' own configuration files now name the gateway.

## Putting a tool back

Switch "Enabled" off and press "Apply".

Expect: the line beside the toggle reads "the tools are as they were", and each
tool's own configuration is restored.

```bash
nclient service ai apply off
```

::: tip
`nclient service ai show` prints where this person's tools point right now,
without opening the window.
:::

That is the whole path: one endpoint, one key per machine, and a toggle that
puts every tool back.
