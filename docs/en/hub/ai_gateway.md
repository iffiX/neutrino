---
description: "Neutrino Hub takes your API keys and subscriptions once, and Claude Code, Codex and OpenCode on every computer use them, with usage and cost in one place."
---

# AI gateway

The AI gateway is one endpoint that all your AI tools share. You add API keys and AI subscriptions to the hub one time, the AI tools on every computer can use them, and you see the usage and cost in one place.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.1.0" />

The AI gateway installs with the hub and is already running. After you add a key or a subscription and connect your tools to the gateway, the tools keep no keys of their own. The gateway replaces only the model source and installs no tools, so you install tools such as Claude Code yourself. Hermes WebUI, Ayakaleaf, AstrBot and SiYuan also connect to the AI gateway through an account's switch; see [Systems joined to the hub](#systems-joined-to-the-hub).

## Add an API key

Save the key on the **Credentials** page, then create a provider on the **AI** page that uses the key:

1. In the panel's sidebar, select **Credentials**, then select **Add token** under **Tokens**. Enter a name in **Name**, paste the key from your provider in **Value**, then select **Save token**. After you save it, the key stays hidden.

   ![The Credentials page with Add token marked](/guide/en/hub_ai_gateway_01_credentials.webp "Select Add token")
   ![The new token form with Save token marked](/guide/en/hub_ai_gateway_02_token_form.webp "Fill it in, then select Save token")

1. In the sidebar, select **AI**, then select **Add provider** under **Providers**.

   ![The AI page with Add provider marked](/guide/en/hub_ai_gateway_03_page.webp)

1. The form starts with **Vendor**. Choose your vendor from its list, for example **DeepSeek**, and the form fills in **Name**, **Base URL** and **Model aliases**.

   ![The Vendor list open with the DeepSeek row marked in red](/guide/en/hub_ai_gateway_20_provider_vendor.webp "Choose the vendor")

1. In **API token**, choose the token you saved in the first step, then select **Save provider**.

   ![The API token list open with the saved token marked](/guide/en/hub_ai_gateway_04_provider_token.webp "Select the saved token")
   ![The filled provider form with Save provider marked](/guide/en/hub_ai_gateway_05_provider_form.webp "Select Save provider")

1. A new row appears in the list, and a yellow notice states that the gateway restarts and requests in progress fail. Select **Apply providers** to put the change into effect. Refresh the page after a few seconds. The key is added when **Activity** at the top of the page shows **running**, **answering** and **Serving 2 models**.

   ![The provider list and the yellow notice, with Apply providers marked](/guide/en/hub_ai_gateway_06_provider_list.webp "Select Apply providers")
   ![The Activity area showing Serving 2 models](/guide/en/hub_ai_gateway_09_page_serving.webp "It shows Serving 2 models")

**Vendor** lists DeepSeek, Kimi, Zhipu GLM, Qwen, Doubao, MiniMax, OpenRouter, SiliconFlow, Mistral and xAI. Some vendors have a mainland China address and an international one, or a Coding Plan of their own. For those the form adds **Plan and region**; choose the one you pay for, and the address and model names change with it.

![The Plan and region list open with API (mainland China) marked in red](/guide/en/hub_ai_gateway_21_provider_endpoint.webp)

A vendor's model names are updated with each hub release. When a vendor adds a new model, add a line for it in **Model aliases** yourself. For a vendor missing from the list, choose **Custom** and fill in these fields:

- **Kind**: the API the provider offers, one of **Anthropic**, **OpenAI**, **Gemini** or **OpenAI-compatible**.
- **Base URL**: the provider's address; leave it empty for the official one.
- **Model aliases**: one model name per line, at least one, because the gateway serves no models while the field is empty.

## Add a subscription

If you have an AI subscription, sign in with the account one time to use it, without a key.

1. On the **AI** page, select **Sign in** under **Accounts**, then choose a provider in the dialog.

   ![The AI page with Sign in marked under Accounts](/guide/en/hub_ai_gateway_18_accounts.webp "Select Sign in")
   ![The subscription sign-in dialog listing the providers](/guide/en/hub_ai_gateway_08_sign_in.webp "Choose a provider")

1. The dialog shows an address. Select **Copy**, open the address in a browser, then sign in and approve. If the dialog shows a code, enter the code at that address.

1. After you sign in, the browser can report that the page cannot open, which is expected. Copy the contents of the address bar, paste them into **Address bar or code**, then select **Finish sign-in**. The subscription is added when a new row appears under **Accounts**.

   ![The Sign in with Claude dialog with an address and an input box](/guide/en/hub_ai_gateway_17_sign_in_step.webp)

## Account quota

Under **Accounts**, each account is a row while the window is wide enough, and a card in a narrower window. Every limit window is a ring with the used percent inside, and the window and its reset time under it. Claude and ChatGPT accounts have **5 h** and **7 days**, and Kimi also has **Month**. A ring turns yellow at 80 percent and red when the window is used up. A ChatGPT account also shows its plan and the date it runs until.

![The Accounts panel with an account's two quota rings, and the Refresh button marked in red](/guide/en/hub_ai_gateway_23_account_quota.webp)

The rings of a Claude or ChatGPT account follow the account's own requests, and **updated** on the right tells how old the numbers are. Select **Refresh** to have the hub read the quota from the vendor right away. A Kimi or Antigravity account shows rings only after its first **Refresh**. An xAI account has neither **Refresh** nor rings.

While an account's quota is used up, its status shows **limited until** and a time. During that time the gateway serves with the other accounts and the providers, as [Serving order](#serving-order) describes.

To stop using an account for a while, select **Pause**. The gateway stops using it right away, and its status shows **paused**. Select **Resume** to use it again with no new sign-in. After **Delete**, the account needs a new sign-in before it serves again.

![A paused account with the Resume button marked in red](/guide/en/hub_ai_gateway_24_account_paused.webp)

## Serving order

When a tool asks for a model, the gateway first uses the accounts and the systems' Ollama that serve the model, taking turns among them. When they are all limited or lack the model, it uses the API keys under **Providers** from the top down. A provider can answer with too many requests, a timeout, a refusal or a server error. The gateway then passes the same request to the next one, up to 3 more times.

![The provider list with the hint that accounts serve first, and the drag handle of a row marked in red](/guide/en/hub_ai_gateway_22_providers_order.webp)

Drag a row by its start to change the order, or turn a provider off for a while with its row's switch. After any of these changes, select **Apply providers**.

An account or provider that failed sits out for a while before the gateway uses it again:

| The vendor's answer                            | How long it sits out                                                                                               |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Too many requests (429)                        | the wait the answer names, at least 10 seconds; with none, 1 second, doubling each time in a row, up to 30 minutes |
| A Claude or ChatGPT account's quota is used up | until that window resets                                                                                           |
| A server error (5xx) or a timeout              | 1 minute                                                                                                           |
| A bad key, no credit, or access refused        | 30 minutes                                                                                                         |
| No such model (404)                            | 12 hours                                                                                                           |

## Ollama on your systems

When a system with [Ollama](/en/deploy/ollama) is online and its Ollama runs with at least one model, the hub adds it to the AI gateway. You add no key. The provider list on the **AI** page then shows a read-only row **from my-computer's Ollama**. Select **Manage** on that row to open the model list of Ollama on that system.

![The provider list on the AI page, with the row from my-computer's Ollama boxed in red](/guide/en/hub_ai_gateway_30_ollama_row.webp)

In the gateway these models keep the names they have in Ollama, with no system name in front. When two systems hold a model of the same name, the gateway takes turns between them. Embedding models, which make vectors and cannot chat, stay out of the gateway. The row goes away while the system is offline, while Ollama is stopped or uninstalled, and while Ollama holds no model; the gateway then stops serving those models.

## Connect tools to the AI gateway

The setup depends on the programs installed on the computer.

### Computers with only the client

On a computer with only the client installed, turn on a switch in the client window:

1. Open the client, go to its **AI** page, and select **The AI tools use this gateway**. The switch turns green, and the row shows **The tools point at the hub**. From then on, Claude Code, Codex, Gemini and OpenCode go through the gateway.

   The client must keep running for the tools to connect to the gateway. When you turn the switch off, the tools return to their own settings.

   ![The client's AI page with The AI tools use this gateway marked](/guide/en/access_desktop_05_ai.webp "Select The AI tools use this gateway")
   ![The switch turned on, with Configure marked](/guide/en/access_desktop_06_ai_on.webp "The switch turns green")

1. Optional: to choose the models, select **Configure**, pick a model for each tool, then select **Save**.

   ![The AI tools configuration dialog](/guide/en/access_desktop_07_ai_config.webp)

The phone apps have no **AI** page.

### Systems joined to the hub

On a system that joined the hub, the switch is on the system's page in the panel, and you set it per account:

1. In the lower part of the panel's sidebar, select the system's name. Under **Available accounts**, select **Edit** on the account's row.

   ![The system page with Edit marked on an account row](/guide/en/hub_ai_gateway_19_account_edit.webp)

1. Turn on **AI tools use the hub's gateway**, choose a model for each tool if you need to, then select **Save**. The setting is in effect when the account's row shows **Uses the hub's AI gateway**.

   ![The account form with the AI tools use the hub's gateway switch marked](/guide/en/hub_ai_gateway_13_account_switch.webp "Turn the switch on")
   ![The model list open with one model marked](/guide/en/hub_ai_gateway_14_account_model.webp "Choose a model")

The switch also covers CloudCLI, Codeg and this account's SiYuan, and tools started in a VS Code or code-server terminal use the gateway too. Hermes WebUI, Ayakaleaf and AstrBot have one copy per system, and they follow the default account's switch. While the gateway has no models available, the switch cannot be turned on. When you remove the account, or the system leaves the hub, the tools return to their own settings.

If a computer with the client has also joined the hub, the client's switch is grey. Use the switch in the panel instead.

## Default model

The default model is the model that the AI tools, Ayakaleaf, Hermes WebUI, AstrBot and SiYuan use when nobody chose one. On the **AI** page, in the **Access** panel, choose a model in **Default model**, then select **Apply access settings**. Without a choice, the hub uses the first model by name among the models the gateway serves.

## Models

The **Models** panel of the **AI** page lists every model the gateway serves, the cloud models first and then the Ollama models. Each row shows the model's name, **From** and **Context**, where **From** names the accounts and providers that serve it. On the right are **Configure** and **Details**; an Ollama model has **Details** alone.

![The Models panel of the AI page, with the Configure button of a cloud model marked in red](/guide/en/hub_ai_gateway_40_models.webp)

### Context length

A model's context length is the most tokens one request to it can hold: the prompt, the conversation and the answer. The hub works out a length for every model the gateway serves. It writes the length into OpenCode, Codex and Claude Code, and into Hermes WebUI, SiYuan and AstrBot. These tools compact a conversation before it grows past that length. Claude Code gets a length only while it uses a model whose name does not start with `claude-`, and Ayakaleaf uses no length.

By default, a cloud model's length comes from the hub's own table of models, then from the gateway's model catalog. When neither names the model, it is 200000. Where the length depends on the plan, the table holds the smallest plan's length.

An Ollama model's length is the smaller of the **setting** and the **model max**. When several systems hold the same model, the smallest counts, offline systems included. You change it on that system's Ollama tab, as [Ollama](/en/deploy/ollama#settings) describes.

Hermes WebUI does not take a model whose context length is under 64000. When you choose such a model, Hermes says the message was not sent.

### Prices

A price is what a million tokens cost, one for input and one for output. The hub takes its prices from models.dev, reads them every day and keeps a copy; the install package carries a copy too, so prices exist with no network. A price is matched to the vendor by the provider's Base URL. A **Custom** provider therefore has no price and shows **no price**, and you can enter one under **Configure**. An Ollama model costs nothing and has no price.

models.dev keeps every price in USD, and it converts the CNY prices of mainland China vendors at its own rate. If you pay in CNY, switch **Currency** to **CNY** under **Configure** and enter the price from the vendor's page.

### Change one model

1. On the model's row, select **Configure**.
1. In the dialog, change **Context length (tokens)**, from 4096 to 10000000. Under it are **Input price**, **Output price** and **Currency**, each price per 1M tokens. A changed length gets **Reset to** and the default length beside it. Changed prices get one line under them, **Reset to** with the two default prices. Selecting **Reset to** puts the default back.
1. Select **Save**. A new price counts from the next request, and the cost already counted stays. The AI tools on every system use a new length the next time they start, and a tool that is running keeps its old length.

   ![The Configure dialog with the context length and the two prices, and the Save button marked in red](/guide/en/hub_ai_gateway_41_model_configure.webp)

### One model's details

Select **Details** on a row. The top of the dialog shows, in large type, the model's requests, tokens and cost over the range picked under **Activity**. Under them each source has a box with its own requests, tokens and cost, and a cloud source also shows its input and output price.

In an Ollama model's details each system has a box with its **setting** and **model max**, the one equal to the model's length bright. A system's name opens that system's Ollama tab.

![The details dialog of a model, with the totals above and a box per source below](/guide/en/hub_ai_gateway_43_model_details.webp)

## Generate a key for other tools

Some tools require you to enter an address and a key by hand, and for those you can generate a separate key. The key is for tools on the hub's computer, or for tools that connect to that computer through SSH port forwarding. The gateway is closed to the LAN, so the address is `http://127.0.0.1:<port>`, with the number from the **Gateway port** section as `<port>`.

1. On the **AI** page, select **Generate key** under **Access**. **Endpoint** is the address you enter in the tool.

   ![The Access area with Generate key marked](/guide/en/hub_ai_gateway_10_access.webp)

1. Enter a name, then select **Generate**. Select **Copy key**, then enter the key and the **Endpoint** in the tool. The full key is visible only until this screen closes.

   ![A name filled in with Generate marked](/guide/en/hub_ai_gateway_11_key_name.webp "Enter a name, then select Generate")
   ![The newly generated key](/guide/en/hub_ai_gateway_12_key_once.webp "Select Copy key")

If you no longer need the key, select the trash icon on its row, then select **Revoke** in the dialog. Tools that use the key lose their connection to the gateway immediately.

![The key's row with the revoke icon marked](/guide/en/hub_ai_gateway_15_key_row.webp "Select the trash icon")
![The revoke confirmation dialog](/guide/en/hub_ai_gateway_16_revoke.webp "Select Revoke")

To stop one client from using the gateway, turn off its **AI gateway** permission on the **Clients** page. The steps are in [Clients](/en/hub/clients).

## View usage and cost

**Activity**, at the top of the **AI** page, shows **requests today**, **tokens today** and **cost today**. It adds **API value today** while a subscription account served requests. Select **Journal** to read the gateway's log.

![The Activity area with today's cost and the usage table under it](/guide/en/hub_ai_gateway_07_activity.webp)

The usage table under it switches its range with **Day**, **Week**, **Month** and **Year**, and its view with **Providers**, **Keys** and **Models**. The last column of each view is **Cost**.

![The usage table switched to Models, with the Cost column marked in red](/guide/en/hub_ai_gateway_45_usage_models.webp)

Each request's cost is the tokens it used at the price of that moment, with cache reads and cache writes at their own prices. Cost reads as follows:

- USD and CNY show apart and are never converted, for example **$3.10 + ¥12.40**.
- A subscription account or a Coding Plan is paid already, so its requests add nothing to the cost. They show as **API value**, what the same tokens would cost with an API key.
- A request with no price found shows **no price**, never 0.
- Ollama on your systems costs nothing and has no cost.

**AI usage** on the [Dashboard](/en/hub/dashboard) page also shows requests and tokens, and it can show one key alone.
