# Quick start

In this tutorial, you install the hub and CloudCLI, then open an AI session on your computer from your phone.

The tutorial uses CloudCLI, a web interface for Claude Code. After you install it, you give Claude Code on your computer instructions from your phone, and it edits your code. Other apps install and work the same way.

## Before you start

You need a Windows, macOS or Linux computer with internet access, and administrator rights on it. The computer must stay on afterwards, or your phone cannot connect.

You also need an Android phone connected to the same Wi-Fi or router as this computer. On mobile data, the phone cannot connect to the hub yet. After you finish this tutorial, turn on an access method; see [Choose an access method](/en/access/ways_in). If you have an iPhone, first install the app as [iOS app](/en/access/ios) describes, then skip the steps that download and install the app.

## Step 1: Install the hub

The hub is the program you install on the computer. The panel is its web page, and you install every app from the panel.

### Run the install command

1. On the computer, open a terminal. On Linux, open the **Terminal** app. On macOS, open **Applications** > **Utilities** > **Terminal**. On Windows, search for PowerShell in the Start menu and open it.

1. Copy the command for your system, paste it into the terminal and press Enter. If you are in mainland China, choose the China edition for faster downloads.

   ::: code-group

   ```bash [Linux, macOS]
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
   ```

   ```powershell [Windows]
   irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
   ```

   ```bash [China edition Linux, macOS]
   curl -fsSL https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.sh | sh
   ```

   ```powershell [China edition Windows]
   irm https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.ps1 | iex
   ```

   :::

1. The script requests administrator rights one time. On Linux and macOS, type the password you sign in to this computer with, and press Enter. The screen shows no characters while you type. On Windows, select **Yes** in the system prompt, then switch to the newly opened window.

1. Wait for the script to finish. The terminal prints an address that starts with `http://` and contains `?token=`. If the line `Press Enter to begin:` appears after the address, do not press Enter.

   ```text
   Installed neutrino-hub_0.6.0_amd64.deb
     The hub's service asks the same questions in a browser at:

       http://192.168.1.20:8080/?token=<wizard-token>

   NEUTRINO ─────────────────────────────────────
   ...
     Press Enter to begin:
   ```

### Complete the setup wizard

1. Copy the whole address line, open it in a browser and select **Set this box up**. The wizard is dark on your screen and light in these pictures, with the same buttons and text. The next screen is **Language**: select **English**, then **Next**.

   ![The first wizard screen, with the set-up button marked in red](/guide/en/hub_install_02_wizard_start.webp "Select Set this box up")
   ![The Language screen, with Next marked in red](/guide/en/hub_install_04_language_next.webp "Select English, then Next")

1. Set the **Panel password** and the **Vault passphrase**, typing each one twice, then select **Next**.

   - The **Panel password** has at least 8 characters, and you sign in to the panel with it.
   - The **Vault passphrase** has at least 16 characters and must mix lowercase letters, uppercase letters, digits and symbols. You need it to restore a backup, so write it down.

   ![Both passwords filled in, with Next marked in red](/guide/en/hub_install_05_passwords.webp "Set both passwords, then select Next")

1. On the **What is this machine for?** screen, select **Server**, then **Next**. Choose it for laptops and desktops too, and your network stays as it is.

   ![The purpose screen, with Server marked in red](/guide/en/hub_install_06_mode_server.webp "Select Server, then Next")

1. Leave the **Which ports?** screen as it is and select **Next**. Leave the next screen as it is too, with **Set it up here** off, and select **Next**.

   ![The Which ports? screen, with Next marked in red](/guide/en/hub_install_07_network.webp "Leave it as it is, select Next")
   ![The switch left off, with Next marked in red](/guide/en/hub_install_08_exit.webp "Leave it off, select Next")

1. On the **Ready** screen, select **Set this box up**. When the page changes to **Setting up**, wait for the setup to finish. When **This hub is set up** appears, select **Open the panel**.

   ![The Ready screen, with the set-up button marked in red](/guide/en/hub_install_09_ready.webp "Select Set this box up")
   ![This hub is set up, with Open the panel marked in red](/guide/en/hub_install_11_done.webp "After setup, select Open the panel")

1. Sign in with the panel password you set earlier. The **Dashboard** page opens, and this stage is complete.

   ![The password filled in, with Sign in marked in red](/guide/en/hub_install_13_login_press.webp "Enter the password, select Sign in")
   ![The Dashboard after sign-in](/guide/en/hub_install_14_dashboard.webp "The Dashboard page opens")

If the wizard shows an error or does not open, see [Install the hub](/en/hub/install) and [Troubleshooting](/en/reference/troubleshooting).

## Step 2: Add a subscription or an API key in the AI gateway

CloudCLI uses models through the AI gateway of the hub, so you do not install Claude Code on the computer. You can sign in with a Claude subscription or add an API key from a provider, and one of the two is enough. The provider sets the cost.

### Sign in with a Claude subscription

1. In the left sidebar of the panel, select **AI**. In the **Accounts** section, select **Sign in**, then choose Claude in the dialog.

   ![AI page, with Sign in in the Accounts section marked in red](/guide/en/hub_ai_gateway_18_accounts.webp "Select Sign in")
   ![The subscription sign-in dialog, listing the providers](/guide/en/hub_ai_gateway_08_sign_in.webp "Choose Claude")

1. The dialog shows an address. Select **Copy**, open the address in a browser, then sign in with your Claude account and give your consent.

1. If the browser then shows that the page cannot be opened, that is expected. Copy the contents of the address bar, paste them into **Address bar or code** in the dialog, and select **Finish sign-in**. When a new row appears in **Accounts**, this stage is complete.

   ![The Claude sign-in dialog, with an address and an input field](/guide/en/hub_ai_gateway_17_sign_in_step.webp "Paste, then select Finish sign-in")

### Use an API key

These steps use DeepSeek. For other providers, see [AI gateway](/en/hub/ai_gateway#add-an-api-key).

1. In the left sidebar of the panel, select **Credentials**, then select **Add token** in the **Tokens** section. Enter `deepseek` in **Name**, paste your DeepSeek API key into **Value**, and select **Save token**. After you save, the key is no longer shown.

   ![Credentials page, with Add token marked in red](/guide/en/hub_ai_gateway_01_credentials.webp "Select Add token")
   ![The new token form, with Save token marked in red](/guide/en/hub_ai_gateway_02_token_form.webp "Fill it in, then select Save token")

1. In the left sidebar, select **AI**, then select **Add provider** in the **Providers** section.

   ![AI page, with Add provider marked in red](/guide/en/hub_ai_gateway_03_page.webp)

1. Fill in the form as follows, then select **Save provider**:

   - **Name**: `DeepSeek`
   - **Kind**: **OpenAI-compatible — /chat/completions**
   - **Base URL**: `https://api.deepseek.com`
   - **Model aliases**: two rows, `deepseek-flash` in the first and `deepseek-v4-pro` in the second
   - **API token**: `deepseek`, the token you saved earlier

   ![The API token list open, with the saved token marked in red](/guide/en/hub_ai_gateway_04_provider_token.webp "Choose the saved token")
   ![The completed provider form, with Save provider marked in red](/guide/en/hub_ai_gateway_05_provider_form.webp "Select Save provider")

1. A new row appears in the list. Select **Apply providers**, and only then does the change take effect. After a few seconds, refresh the page. When **Activity** at the top of the page shows **Serving 2 models**, this stage is complete.

   ![The provider list and a yellow notice, with Apply providers marked in red](/guide/en/hub_ai_gateway_06_provider_list.webp "Select Apply providers")
   ![Activity showing Serving 2 models](/guide/en/hub_ai_gateway_09_page_serving.webp "Shows Serving 2 models")

## Step 3: Install CloudCLI in the panel

1. The lower part of the left sidebar lists every system that joined the hub. Select the name of this computer to open its page. Then select **Add** in the **Available accounts** section.

   ![The lower part of the sidebar, with this computer's name marked in red](/guide/en/deploy_on_a_machine_01_sidebar.webp "Select this computer's name")
   ![The Available accounts section, with Add marked in red](/guide/en/deploy_on_a_machine_02_accounts_add.webp "Select Add")

1. In **System account**, choose the account you usually sign in to this computer with. On Windows, also enter the sign-in password of this account in **Password**. If you start the computer with a PIN, enter the account password here, because the PIN does not work.

   Turn on **AI tools use the hub's gateway**, then select **Save**. If this section already lists the account, select **Edit** on its row, turn on the switch and save.

   ![The account form, with System account marked in red](/guide/en/deploy_on_a_machine_03_account_form.webp "Choose the account")
   ![The account form, with the AI tools switch marked in red](/guide/en/hub_ai_gateway_13_account_switch.webp "Turn on the switch, then select Save")

1. In the **Module configuration** section, select **+ Add module**. In the dialog, select the **CloudCLI** card, which is highlighted when selected. Then select **Close** at the bottom right.

   ![The module list, with + Add module marked in red](/guide/en/deploy_cloudcli_01_add_module.webp "Select + Add module")
   ![The CloudCLI card highlighted, with Close marked in red](/guide/en/deploy_cloudcli_03_catalog_ticked.webp "Select CloudCLI, then Close")

1. **CloudCLI** now appears in the list. Select it, then select **Install**. This step downloads files, and the page shows a checklist of its steps. When the tab shows **installed**, select **Start**.

   ![The CloudCLI tab showing not installed, with Install marked in red](/guide/en/deploy_cloudcli_05_install.webp "Select Install")
   ![The tab showing installed, with Start marked in red](/guide/en/deploy_cloudcli_07_installed.webp "Select Start")

1. When the tab shows **running, no accounts**, select **Configure**. In **Enabled accounts**, select your account.

   ![The tab showing running, no accounts, with Configure marked in red](/guide/en/deploy_cloudcli_17_started.webp "Select Configure")
   ![The Enabled accounts section, with the account row marked in red](/guide/en/deploy_cloudcli_08_tick_account.webp "Select the account")

1. Select **Apply CloudCLI**. The tab shows **installing** while the npm step runs. The first time, this step takes from a few minutes to more than ten minutes.

   ![The account selected, with Apply CloudCLI marked in red](/guide/en/deploy_cloudcli_09_apply.webp "Select Apply CloudCLI")
   ![The npm step running](/guide/en/deploy_cloudcli_10_npm_running.webp "Wait for the npm step")

1. When the tab shows **running**, this stage is complete.

   ![The tab showing running](/guide/en/deploy_cloudcli_11_running.webp)

## Step 4: Add your phone to the hub

1. Scan the QR code with the phone camera or WeChat, then download and install the app.

   | China edition                                                      | International edition                                                          |
   | ------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
   | ![QR code of the China edition download page](/home/qr_app_cn.svg) | ![QR code of the International edition download page](/home/qr_app_global.svg) |

1. Back in the panel on the computer, select **Clients** in the left sidebar, then select **New client link**. Enter `My phone` in **Name**, then select **Generate link**.

   ![Clients page, with New client link marked in red](/guide/en/access_join_01_clients.webp "Select New client link")
   ![The dialog with a name filled in, Generate link marked in red](/guide/en/access_join_02_name.webp "Enter a name, then select Generate link")

1. The dialog shows a QR code; keep the dialog open. The app you installed is named **Neutrino**. Open it on the phone and select **Join a hub** on the **Hubs** page. Select **Allow the camera**, then point the camera at the QR code in the panel.

   ![The link and QR code in the dialog](/guide/en/access_join_03_link.webp "The panel shows a QR code")
   ![The phone's join page, with the camera pointed at the QR code](/guide/en/access_android_05_camera_on.webp "Point the phone's camera at the QR code")

1. When your hub appears on the **Hubs** page of the phone and shows **Connected · LAN**, this stage is complete. Back in the panel, select **Done** to close the dialog.

   ![The phone's Hubs page, connected](/guide/en/access_android_07_joined.webp)

## Step 5: Open CloudCLI on your phone

1. On the phone's bottom bar, select **Apps**, find the row with **CloudCLI** and your account name, and select **Use**. When Android requests notification permission, select Allow; the notification keeps the connection running in the background.

   The row then shows an **Open** button. Select it, and the phone's browser opens CloudCLI. You are already signed in, so you do not type a password.

   ![The phone's Apps page with the Use button](/guide/en/access_android_11_use.webp "Select Use")
   ![The system prompt for notification permission](/guide/en/access_android_12_notify_prompt.webp "Select Allow")
   ![The phone's Apps page with the Open button](/guide/en/access_android_13_open.webp "Select Open")

1. The first time, CloudCLI shows its setup page in English. Fill in **Git Name** and **Git Email**, then select **Next**. On the **Connect Your AI Agents** screen, select **Complete Setup**. These pictures come from a computer browser, and the phone shows the same content in a narrower layout.

   ![The Git Configuration screen, with the Git Name field marked in red](/guide/en/deploy_cloudcli_20_git_config.webp "Fill it in, then select Next")
   ![The Connect Your AI Agents screen, with Complete Setup marked in red](/guide/en/deploy_cloudcli_22_connect_agents.webp "Select Complete Setup")

1. When the CloudCLI main page opens, you are done if you can open the projects on your computer and chat with Claude Code. To change the language of CloudCLI, open **Quick Settings** on the right and choose a language in **Language**.

   ![The CloudCLI main page, with the small arrow on the right marked in red](/guide/en/deploy_cloudcli_23_home.webp "The main page in a computer browser")
   ![CloudCLI on the phone](/guide/en/access_android_14_browser.webp "The same page on the phone")

To use the hub from outside your network, see [Choose an access method](/en/access/ways_in). To share an app with other people, see [App share](/en/share/web_share).
