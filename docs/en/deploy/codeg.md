# Codeg

Codeg is an AI coding workbench. You can use Claude Code, Codex and Gemini in one web page, and continue a conversation on another device.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.5.1" />

Codeg runs one instance per account. If you use only Claude Code and want a simpler page, you can use [CloudCLI](/en/deploy/cloudcli) instead.

## Supported systems

| System  | Architecture         | First Neutrino Hub version |
| ------- | -------------------- | -------------------------- |
| Linux   | amd64, arm64         | 0.5.1                      |
| Windows | amd64                | 0.5.1                      |
| macOS   | Apple silicon, Intel | 0.5.1                      |

## Install

Codeg uses the AI tools installed in your account, which are separate programs. Before you start, install the tools you want on this system as your account, and sign in to each of them. Two of the tools have modules of their own, [Claude Code](/en/deploy/claude_code) and [Codex](/en/deploy/codex). For installing Claude Code, see the [Claude Code setup page](https://code.claude.com/docs/en/setup).

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on. Check that **Available accounts** lists your account. If it does not, add it as [Add an account](/en/deploy/on_a_machine#add-an-account) describes.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **Codeg** card. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_codeg_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the Codeg card marked in red](/guide/en/deploy_codeg_02_catalog.webp "Select Codeg")
   ![The Codeg card highlighted, with the Close button marked in red](/guide/en/deploy_codeg_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **Codeg** row in the list on the left, and its tab opens on the right. Select **Install**.

   ![The module list with the Codeg row marked in red](/guide/en/deploy_codeg_04_tab.webp "Select Codeg")
   ![The Codeg tab showing not installed, with the Install button marked in red](/guide/en/deploy_codeg_05_install.webp "Select Install")

1. The tab lists each step. It installs the Codeg server first, then the bundled Node.js. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with each step listed](/guide/en/deploy_codeg_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button marked in red](/guide/en/deploy_codeg_07_installed.webp "Select Start")

1. The tab shows **running, no accounts**. Select **Configure** to expand the settings. Under **Enabled accounts**, select your account.

   ![The tab showing running, no accounts, with the Configure button marked in red](/guide/en/deploy_codeg_17_started.webp "Select Configure")
   ![The Enabled accounts field with the lab row marked in red](/guide/en/deploy_codeg_08_tick_account.webp "Select lab")

1. Select **Apply Codeg**. When **running** appears after the account and **Applied.** appears under the list, the installation is complete.

   ![lab selected, with the Apply Codeg button marked in red](/guide/en/deploy_codeg_09_apply.webp "Select Apply Codeg")
   ![lab followed by running, and Applied under the list](/guide/en/deploy_codeg_10_applying.webp "Applied")

## Use

Before you start, join your phone or computer to the hub, as [Join the hub](/en/access/join) describes.

In the client, open the **Apps** page and find the **Codeg (lab)** row, where the name in parentheses is the account. Select **Use**, and the row shows a local address with the buttons **Stop**, **Configure** and **Open**. Select **Open**.

![The client's Apps page with the Use button marked in red](/guide/en/deploy_codeg_40_client_use.webp "Select Use")
![The row with a local address, and the Open button marked in red](/guide/en/deploy_codeg_41_client_open.webp "Select Open")

The browser opens the workspace directly, without a password prompt. If the Codeg sign-in page appears, return to the client and select **Open** again.

Codeg communicates with each tool through an adapter, which is a separate program from the tool in your account. Install a tool's adapter before you use the tool the first time:

1. In the middle of the workspace, a line of red text states that this tool's adapter is not installed. Select that text, and a new browser tab opens the **Agents** page of **Settings**, with each tool listed on the left.

   ![The workspace with the red adapter notice marked in red](/guide/en/deploy_codeg_20_workspace.webp "Select the red text")
   ![The agent list on the settings page](/guide/en/deploy_codeg_21_agents_settings.webp "Agents page")

1. Under **Version Status**, select **Install**. The adapter downloads from the official npm registry in a minute or two.

   ![The agent details with the Install button marked in red](/guide/en/deploy_codeg_22_agent_install.webp)

Back in the workspace, choose a tool over the input box, enter what you want it to do, and select the send button. To choose your project, select **Open Folder** on the left.

When you finish, return to the client and select **Stop**. On a phone, the steps are the same: on the **Apps** page, select **Use**, then **Open**.

![The Codeg workspace on a phone](/guide/en/deploy_codeg_60_phone.webp)

## Share

Codeg can generate a link with [App share](/en/share/web_share), and the visitor opens it in a browser.

1. In the panel's left sidebar, select **Services**. Find the **Codeg (lab)** row and select **Share**.

   ![The Services page with the Share button of the Codeg (lab) row marked in red](/guide/en/deploy_codeg_12_services_share.webp)

1. In the dialog, enter a **Name** that helps you recognize the link; the name is visible only to you. The yellow notice under it states that the visitor uses this app as this account. **Expires** defaults to 7 days, and you can choose another option. Select **Generate link**.

   ![The share dialog with the Name field marked in red](/guide/en/deploy_codeg_13_share_dialog.webp "Enter a name")
   ![The share dialog filled in, with the Generate link button marked in red](/guide/en/deploy_codeg_14_share_generate.webp "Select Generate link")

1. Select **Copy** right away and send the link to the visitor. Then select **Done** to close the dialog. After the dialog closes, the panel no longer shows the link.

   ![The share dialog showing the link and a QR code, with the link row marked in red](/guide/en/deploy_codeg_15_share_link.webp "Select Copy")

The visitor opens the link and enters the workspace without signing in, using the same account and AI quota as you.

![The Codeg workspace open in the visitor's browser](/guide/en/deploy_codeg_16_visitor.webp)

## Risks and limits

The tools in a session run as this account, so they can read and write its files and run commands. The visitor can do the same, so send the link only to people you trust.

Each open session uses about 300 MB of memory, and Codeg frees it a few minutes after you close the page.

The tools must connect to an AI service to work. You can sign in within this account, or turn on **AI tools use the hub's gateway**. The **Model Providers** setting in Codeg writes to the same files, and while the switch is on, the switch takes precedence.

The lower-right corner of the workspace can show a notice about a new version. The panel manages the version, and only the panel changes it: select **Update** there.

## Settings

Apart from the enabled accounts, the following settings can stay at their defaults:

| Setting                                  | Where                                         | What it does                                                                      |
| ---------------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------- |
| **Enabled accounts**                     | **Configure** on the tab                      | Each selected account runs one instance                                           |
| **Update**, **Install another version…** | Under the status on the tab                   | Changes the version; the steps follow this table                                  |
| **AI tools use the hub's gateway**       | The account form under **Available accounts** | Makes the Claude Code and Codex sessions use the [AI gateway](/en/hub/ai_gateway) |

The version row on the tab shows the current version and the publisher's latest version. To change the version:

1. Select **Install another version…**. The dialog lists newer versions first: **tested** marks a tested version, **untested** marks a newer one, and a check mark marks the installed one. Select the version you want.

   ![The version row with the Install another version button marked in red](/guide/en/deploy_codeg_30_version_button.webp "Select Install another version")
   ![The version list with one version marked in red](/guide/en/deploy_codeg_31_version_dialog.webp "Select a version")

1. After the dialog closes, the tab switches the version. When the tab shows **running** again, the version row shows the new version.

   ![The tab showing installing, with switching to the version as the first step](/guide/en/deploy_codeg_32_version_switching.webp "Switching")
   ![The version row showing the new version, with the Update button marked in red](/guide/en/deploy_codeg_33_version_older.webp "Switch complete")

To return to the tested version, select **Follow the tested version** at the top of the dialog.

## Uninstall

On the **Codeg** tab, select **Uninstall**. The dialog shows the folder where each account's data stays, including the database, the uploaded files and the tools Codeg installed. Select **Uninstall** to confirm.

![The Codeg tab with the Uninstall button marked in red](/guide/en/deploy_codeg_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with the Uninstall button marked in red](/guide/en/deploy_codeg_51_uninstall_dialog.webp "Confirm")

If Codeg does not work, see [Troubleshooting](/en/reference/troubleshooting).
