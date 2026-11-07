# AI gateway

The AI gateway is one endpoint that all your AI tools share. You add API keys and AI subscriptions to the hub one time, the AI tools on every computer can use them, and you see the usage in one place.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.1.0" />

The AI gateway installs with the hub and is already running. After you add a key or a subscription and connect your tools to the gateway, the tools keep no keys of their own. The gateway replaces only the model source and installs no tools, so you install tools such as Claude Code yourself. Hermes WebUI, Ayakaleaf and SiYuan use the AI gateway automatically, with nothing to set up.

## Add an API key

Save the key on the **Credentials** page, then create a provider on the **AI** page that uses the key:

1. In the panel's sidebar, select **Credentials**, then select **Add token** under **Tokens**. Enter a name in **Name**, paste the key from your provider in **Value**, then select **Save token**. After you save it, the key stays hidden.

   ![The Credentials page with Add token marked](/guide/en/hub_ai_gateway_01_credentials.webp "Select Add token")
   ![The new token form with Save token marked](/guide/en/hub_ai_gateway_02_token_form.webp "Fill it in, then select Save token")

1. In the sidebar, select **AI**, then select **Add provider** under **Providers**.

   ![The AI page with Add provider marked](/guide/en/hub_ai_gateway_03_page.webp)

1. Fill in the following fields, then select **Save provider**.

   - **Name**: any name you choose.
   - **Kind**: the API the provider offers, one of **Anthropic**, **OpenAI**, **Gemini** or **OpenAI-compatible**. For DeepSeek, for example, select **OpenAI-compatible — /chat/completions**.
   - **Base URL**: the provider's address, when it differs from the official one. For DeepSeek, enter `https://api.deepseek.com`.
   - **Model aliases**: one model name per line, at least one, because the gateway serves no models while the field is empty. For DeepSeek, enter two lines, first `deepseek-flash`, then `deepseek-v4-pro`.
   - **API token**: the token you saved in the first step.

   ![The API token list open with the saved token marked](/guide/en/hub_ai_gateway_04_provider_token.webp "Select the saved token")
   ![The filled provider form with Save provider marked](/guide/en/hub_ai_gateway_05_provider_form.webp "Select Save provider")

1. A new row appears in the list, and a yellow notice states that the gateway restarts and requests in progress fail. Select **Apply providers** to put the change into effect. Refresh the page after a few seconds. The key is added when **Activity** at the top of the page shows **running**, **answering** and **Serving 2 models**.

   ![The provider list and the yellow notice, with Apply providers marked](/guide/en/hub_ai_gateway_06_provider_list.webp "Select Apply providers")
   ![The Activity area showing Serving 2 models](/guide/en/hub_ai_gateway_09_page_serving.webp "It shows Serving 2 models")

The providers are ordered from top to bottom, and the first enabled one serves requests first. Drag a row by its start to change the order, or turn a provider off for a while with its row's switch. After any of these changes, select **Apply providers**.

## Add a subscription

If you have an AI subscription, sign in with the account one time to use it, without a key. Accounts and API keys form one pool. When a tool requests a model, the gateway picks an account or key that offers that model.

1. On the **AI** page, select **Sign in** under **Accounts**, then choose a provider in the dialog.

   ![The AI page with Sign in marked under Accounts](/guide/en/hub_ai_gateway_18_accounts.webp "Select Sign in")
   ![The subscription sign-in dialog listing the providers](/guide/en/hub_ai_gateway_08_sign_in.webp "Choose a provider")

1. The dialog shows an address. Select **Copy**, open the address in a browser, then sign in and approve. If the dialog shows a code, enter the code at that address.

1. After you sign in, the browser can report that the page cannot open, which is expected. Copy the contents of the address bar, paste them into **Address bar or code**, then select **Finish sign-in**. The subscription is added when a new row appears under **Accounts**.

   ![The Sign in with Claude dialog with an address and an input box](/guide/en/hub_ai_gateway_17_sign_in_step.webp)

## Connect tools to the AI gateway

The setup depends on the programs installed on the computer.

### Computers with only the client

On a computer with only the client installed, turn on a switch in the client window:

1. Open the client, go to its **AI** page, and select **The AI tools use this gateway**. The switch turns green, and the row shows **The tools point at the hub**. From then on, Claude Code, Codex and Gemini go through the gateway.

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

The switch also covers CloudCLI and Codeg, and tools started in a VS Code or code-server terminal use the gateway too. While the gateway has no models available, the switch cannot be turned on. When you remove the account, or the system leaves the hub, the tools return to their own settings.

If a computer with the client has also joined the hub, the client's switch is grey. Use the switch in the panel instead.

## Default model

The default model is the model that the AI tools, Ayakaleaf, Hermes WebUI and SiYuan use when nobody chose one. On the **AI** page, in the **Access** panel, choose a model in **Default model**, then select **Apply access settings**. Without a choice, the hub uses the first model by name among the models the gateway serves.

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

## View usage

**Activity**, at the top of the **AI** page, shows **requests today**, **tokens today** and the usage of the **last 30 days**. Select **Journal** to read the gateway's log.

![The Activity area](/guide/en/hub_ai_gateway_07_activity.webp)

**AI usage** on the [Dashboard](/en/hub/dashboard) page also shows requests and tokens, and it can show one key alone.
