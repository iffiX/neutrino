# CloudCLI

CloudCLI is a web interface for AI coding tools such as Claude Code. On your phone, you can use it to have an AI tool change the code on your computer.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.5.0" />

CloudCLI runs one instance per account, so enable it for each account you use it in. To use several AI tools in one web page, you can use [Codeg](/en/deploy/codeg) instead.

## Supported systems

| System  | Architecture         | First Neutrino Hub version |
| ------- | -------------------- | -------------------------- |
| Linux   | amd64, arm64         | 0.5.0                      |
| Windows | amd64                | 0.5.0                      |
| macOS   | Apple silicon, Intel | 0.5.0                      |

## Install

CloudCLI includes its own copy of Claude Code. Give it access to a model before you install it. For the recommended setup, add a subscription or API key on the hub's **AI** page. Then turn on **AI tools use the hub's gateway** in this account's form, as [AI gateway](/en/hub/ai_gateway) describes.

If you do not use the AI gateway, sign in to Claude Code with your Claude account first. For example, install the [Claude Code](/en/deploy/claude_code) module and run `claude` in a terminal. The sign-in is saved in this account's `~/.claude`, and CloudCLI shares it.

CloudCLI looks for `claude` only in the following folders, which include the folder the official install command uses:

| System  | Folders                                                        |
| ------- | -------------------------------------------------------------- |
| Linux   | `~/.local/bin`, `~/bin`, `/usr/local/bin`, `/usr/bin`          |
| macOS   | `~/.local/bin`, `~/bin`, `/opt/homebrew/bin`, `/usr/local/bin` |
| Windows | `%APPDATA%\npm`, or a folder on this account's `PATH`          |

Install CloudCLI in the panel:

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on. Check that **Available accounts** lists your account. If it does not, add it as [Add an account](/en/deploy/on_a_machine#add-an-account) describes.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **CloudCLI** card. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_cloudcli_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the CloudCLI card marked in red](/guide/en/deploy_cloudcli_02_catalog.webp "Select CloudCLI")
   ![The CloudCLI card highlighted, with the Close button marked in red](/guide/en/deploy_cloudcli_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **CloudCLI** row in the list on the left, and its tab opens on the right. Select **Install**.

   ![The module list with the CloudCLI row marked in red](/guide/en/deploy_cloudcli_04_tab.webp "Select CloudCLI")
   ![The CloudCLI tab showing not installed, with the Install button marked in red](/guide/en/deploy_cloudcli_05_install.webp "Select Install")

1. The tab lists each step. The first step installs the bundled Node.js and finishes quickly. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with Node.js as the first step](/guide/en/deploy_cloudcli_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button marked in red](/guide/en/deploy_cloudcli_07_installed.webp "Select Start")

1. The tab shows **running, no accounts**. Select **Configure** to expand the settings. Under **Enabled accounts**, select your account.

   ![The tab showing running, no accounts, with the Configure button marked in red](/guide/en/deploy_cloudcli_17_started.webp "Select Configure")
   ![The Enabled accounts field with the lab row marked in red](/guide/en/deploy_cloudcli_08_tick_account.webp "Select lab")

1. Select **Apply CloudCLI**. The tab shows **installing** and runs the step **Run npm for lab**. This step takes from a few minutes to over ten minutes, depending on the network and the system's speed. You can keep the page open or close it, and the step keeps running on the system.

   ![lab selected, with the Apply CloudCLI button marked in red](/guide/en/deploy_cloudcli_09_apply.webp "Select Apply CloudCLI")
   ![The npm step running](/guide/en/deploy_cloudcli_10_npm_running.webp "Wait for the npm step")

1. When the tab shows **running**, the installation is complete.

   ![The tab showing running, with a green dot on every step listed](/guide/en/deploy_cloudcli_11_running.webp)

If the npm step fails, the tab shows the reason, such as an address that cannot be reached. After the network recovers, select **Apply CloudCLI** again to retry. For other failures, see [Troubleshooting](/en/reference/troubleshooting).

## Use

Before you start, join your phone or computer to the hub, as [Join the hub](/en/access/join) describes.

In the client, open the **Apps** page and find the **CloudCLI (lab)** row, where the name in parentheses is the account. Select **Use**, and the row shows a local address with the buttons **Stop**, **Configure** and **Open**. Select **Open**.

![The client's Apps page with the Use button marked in red](/guide/en/deploy_cloudcli_40_client_use.webp "Select Use")
![The row with a local address, and the Open button marked in red](/guide/en/deploy_cloudcli_41_client_open.webp "Select Open")

CloudCLI opens in the browser without a password prompt. The first visit shows two setup screens in English. Complete both to start:

1. The first screen is **Git Configuration**. Enter your name and email in **Git Name** and **Git Email**, and CloudCLI writes them to this account's git settings. Select **Next**.

   ![The Git Configuration screen with the Git Name field marked in red](/guide/en/deploy_cloudcli_20_git_config.webp "Enter your name and email")
   ![Both fields filled in, with the Next button marked in red](/guide/en/deploy_cloudcli_21_git_next.webp "Select Next")

1. The second screen is **Connect Your AI Agents**, which shows whether each tool is signed in. Each sign-in can wait until later. Select **Complete Setup**.

   ![The Connect Your AI Agents screen with the Complete Setup button marked in red](/guide/en/deploy_cloudcli_22_connect_agents.webp)

On the main page, you can change the interface language, for example to Chinese:

1. Select the small arrow on the right edge of the window to open **Quick Settings**. In **Language**, choose the language, such as **简体中文**.

   ![The main page with the small arrow on the right marked in red](/guide/en/deploy_cloudcli_23_home.webp "Select the small arrow")
   ![Quick Settings open, with the Language field marked in red](/guide/en/deploy_cloudcli_24_language.webp "Choose a language")

1. The interface switches to that language and keeps it on later visits.

   ![The main page shown in Chinese](/guide/en/deploy_cloudcli_25_home_zh.webp)

A project in CloudCLI is a folder on the system. Create a project before the first use:

1. Select **+** in the top-left corner. In **Workspace Path**, enter the folder's full path, here `/home/lab/demo`. Select **Next**.

   ![The plus button in the top-left corner marked in red](/guide/en/deploy_cloudcli_26_new_project.webp "Select +")
   ![The new project dialog with the Workspace Path field marked in red](/guide/en/deploy_cloudcli_27_new_project_path.webp "Enter the path")

1. Check that the path is correct, then select **Create Project**. The project appears in the list on the left. Select the project.

   ![The confirmation screen with the Create Project button marked in red](/guide/en/deploy_cloudcli_28_new_project_confirm.webp "Select Create Project")
   ![demo added to the list on the left, marked in red](/guide/en/deploy_cloudcli_29_project_listed.webp "Select demo")

1. A new session opens on the right. In the input box at the bottom, enter what you want Claude Code to do, and press Enter to send it. The tabs in the top-right corner switch to **Shell**, **Files** and **Source Control**.

   ![The project open, with the input box at the bottom](/guide/en/deploy_cloudcli_30_project_open.webp)

![A conversation in CloudCLI, with Claude answering through the AI gateway](/guide/zh/deploy_cloudcli_30_chat.webp)

CloudCLI 1.37.3 displays each message you send twice, and sends it one time.

When you finish, return to the client and select **Stop**, and the local address closes. If the browser shows a sign-in prompt, return to the client and select **Open** again.

On a phone, the steps are the same: on the **Apps** page, select **Use**, then **Open**, and the app opens in the phone's browser.

![CloudCLI on a phone](/guide/en/access_android_14_browser.webp)

## Share

CloudCLI can generate a link with [App share](/en/share/web_share), and the visitor needs only a browser to open it.

1. In the panel's left sidebar, select **Services**. Find the **CloudCLI (lab)** row and select **Share**.

   ![The Services page with the Share button of the CloudCLI row marked in red](/guide/en/deploy_cloudcli_12_services_share.webp)

1. In the dialog, enter a **Name** that helps you recognize the link; the name is visible only to you. The yellow notice under it states that the visitor uses this app as lab. **Expires** defaults to 7 days, and you can choose another option. Select **Generate link**.

   ![The share dialog with the Name field marked in red and a yellow notice under it](/guide/en/deploy_cloudcli_13_share_dialog.webp "Enter a name")
   ![The share dialog filled in, with the Generate link button marked in red](/guide/en/deploy_cloudcli_14_share_generate.webp "Select Generate link")

1. Select **Copy** right away and send the link to the visitor. Then select **Done** to close the dialog. After the dialog closes, the panel no longer shows the link.

   ![The share dialog showing the link and a QR code, with the link row marked in red](/guide/en/deploy_cloudcli_15_share_link.webp "Select Copy")

The visitor opens the link and enters CloudCLI without signing in, using the same account as you.

![CloudCLI open in the visitor's browser](/guide/en/deploy_cloudcli_16_visitor.webp)

## Risks and limits

The visitor sees your projects and sessions and uses your AI quota. The AI tools can read and write this account's files and run commands, and so can the visitor. Send the link only to people you trust.

CloudCLI can show an update notice in its lower-left corner. The panel manages the version, so to update, select **Update** in the panel.

After you reset or reinstall Neutrino Hub, CloudCLI uses a new account database. Your files stay on the computer, and the new database holds none of the earlier records.

## Settings

Apart from the enabled accounts, the following settings can stay at their defaults:

| Setting                                  | Where                                         | What it does                                                                                       |
| ---------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **Enabled accounts**                     | **Configure** on the tab                      | Each selected account runs one instance, separate from the others                                  |
| **Update**, **Install another version…** | Under the status on the tab                   | Changes the version; the steps are in [Change version](/en/deploy/on_a_machine#change-the-version) |
| **AI tools use the hub's gateway**       | The account form under **Available accounts** | Makes this account's tools use the [AI gateway](/en/hub/ai_gateway)                                |

## Uninstall

1. On the **CloudCLI** tab, select **Uninstall**.

   ![The CloudCLI tab with the Uninstall button marked in red](/guide/en/deploy_cloudcli_50_uninstall.webp)

1. The dialog shows the folder where each account's data stays, and uninstalling keeps this data. Select **Uninstall** to confirm.

   ![The uninstall dialog showing where the data stays, with the Uninstall button marked in red](/guide/en/deploy_cloudcli_51_uninstall_dialog.webp)

Uninstalling ends every share of this app. When you install it again, the accounts you selected last time stay selected, and selecting **Start** runs them.
