# VS Code

VS Code is Microsoft's code editor. Neutrino Hub runs Microsoft's VS Code Server, and you use it in the browser of a computer, phone or tablet.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.5.0" />

Each account runs one instance. If you prefer not to accept Microsoft's terms, use [code-server](/en/deploy/code_server) instead; you need only one of the two.

## Supported systems

| System  | Architecture         | First Neutrino Hub version |
| ------- | -------------------- | -------------------------- |
| Linux   | amd64, arm64         | 0.5.0                      |
| Windows | amd64                | 0.5.0                      |
| macOS   | Apple silicon, Intel | 0.5.0                      |

## Install

1. Open the panel in a browser, sign in, and select the system to install on in the lower half of the sidebar. Check that **Available accounts** lists your account. If it does not, add it first with the steps in [Add an account](/en/deploy/on_a_machine#add-an-account).
1. In the **Module configuration** area, select **+ Add module**. In the dialog, select the **VS Code** card, then select **Close** after the card is highlighted.

   ![The module list with the Add module button boxed in red](/guide/en/deploy_vscode_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the VS Code card boxed in red](/guide/en/deploy_vscode_02_catalog.webp "Select VS Code")
   ![The VS Code card highlighted, with the Close button boxed in red](/guide/en/deploy_vscode_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **VS Code** row in the list on the left, and the top of its tab shows Microsoft's license terms. Select **Open and accept the terms**, and the browser opens the terms page. Selecting this button accepts the terms, and each system needs it only one time.

   ![The module list with the VS Code row boxed in red](/guide/en/deploy_vscode_04_tab.webp "Select VS Code")
   ![The VS Code tab with the Open and accept the terms button boxed in red](/guide/en/deploy_vscode_21_terms.webp "Select Open and accept the terms")

1. The install button appears only after the button changes to **Terms accepted**. Select **Install**.

   ![The VS Code tab showing not installed, with the Install button boxed in red](/guide/en/deploy_vscode_05_install.webp)

1. The tab lists every step while it downloads Microsoft's command-line program, which usually takes less than a minute. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with every step listed](/guide/en/deploy_vscode_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button boxed in red](/guide/en/deploy_vscode_07_installed.webp "Select Start")

1. The tab shows **running, no accounts**. Select **Configure**, and the settings open under it. Under **Enabled accounts**, select your account.

   ![The tab showing running, no accounts, with the Configure button boxed in red](/guide/en/deploy_vscode_17_started.webp "Select Configure")
   ![The Enabled accounts field with the lab row boxed in red](/guide/en/deploy_vscode_08_tick_account.webp "Select lab")

1. Select **Apply VS Code**. The account shows **running**, and **Applied.** appears under it. The install is complete.

   ![lab selected, with the Apply VS Code button boxed in red](/guide/en/deploy_vscode_09_apply.webp "Select Apply VS Code")
   ![lab showing running, with Applied. under it](/guide/en/deploy_vscode_10_applying.webp "Applied")

## Use

Before you start, add your phone or computer to the hub, as [Join the hub](/en/access/join) describes.

Open the client, go to the **Apps** page, and find the **VS Code (lab)** row, with the account name in parentheses. Select **Use**. The row gains a local address, and its buttons become **Stop**, **Configure** and **Open**. Select **Open**.

![The client's Apps page with the Use button boxed in red](/guide/en/deploy_vscode_40_client_use.webp "Select Use")
![The row with a local address, and the Open button boxed in red](/guide/en/deploy_vscode_41_client_open.webp "Select Open")

The browser opens the editor, with no password to enter. On the first open, this system downloads the VS Code server, and the page shows a single line of English text. The editor opens automatically when the download finishes.

![VS Code in a browser](/guide/en/deploy_vscode_16_visitor.webp)

Open your project folder in the editor to start writing code. The menu in the top-left corner also opens this account's terminal. When you finish, return to the client and select **Stop**.

On a phone, the steps are the same: on the **Apps** page, select **Use**, then **Open**.

## Share

VS Code can generate a link with [App share](/en/share/web_share), and the other person opens it in a browser.

On the first open, this system downloads the server. If the other person opens the link during the download, the page shows a loading screen, then the editor when the download finishes. To spare them the wait, open VS Code from the client first and wait for the editor to load before you send the link.

1. In the panel sidebar, select **Services**, find the **VS Code (lab)** row, and select **Share**.

   ![The Services page with the Share button of the VS Code (lab) row boxed in red](/guide/en/deploy_vscode_12_services_share.webp)

1. In the dialog, enter a **Name** that helps you identify the share; the other person does not see it. The yellow notice under it says that the other person uses this app as this account. **Expires** defaults to 7 days, and you can choose another option before you select **Generate link**. Select **Copy** right away, send the link, then select **Done**; after the dialog closes, the panel no longer shows the link.

   ![The share dialog with the Name field boxed in red](/guide/en/deploy_vscode_13_share_dialog.webp "Enter a name")
   ![The completed share dialog with the Generate link button boxed in red](/guide/en/deploy_vscode_14_share_generate.webp "Select Generate link")
   ![The share dialog showing the link and a QR code, with the link row boxed in red](/guide/en/deploy_vscode_15_share_link.webp "Select Copy")

The other person opens the link without signing in and uses the same account as you.

## Risks and limits

The terminal in VS Code is this account's shell: it reads and writes the account's files and runs commands, and the other person can do the same. Send the link only to people you trust.

A development server you start in VS Code does not appear in the client. To use one, declare it as [Add an existing service](/en/deploy/services) describes.

## Settings

Apart from enabling accounts, the following settings can stay at their defaults:

| Setting                                  | Where                                  | Purpose                                                                                                 |
| ---------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| **Enabled accounts**                     | **Configure** on the tab               | Each selected account runs one instance                                                                 |
| **Update**, **Install another version…** | Under the tab's state                  | Change the version; for the steps, see [Change the version](/en/deploy/on_a_machine#change-the-version) |
| **AI tools use the hub's gateway**       | Account form in **Available accounts** | This account's tools use the [AI gateway](/en/hub/ai_gateway)                                           |

## Uninstall

On the **VS Code** tab, select **Uninstall**. The dialog states that each account's settings and extensions stay in its home folder. Select **Uninstall** to confirm.

![The VS Code tab with the Uninstall button boxed in red](/guide/en/deploy_vscode_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with the Uninstall button boxed in red](/guide/en/deploy_vscode_51_uninstall_dialog.webp "Confirm")

If an error appears, see [Troubleshooting](/en/reference/troubleshooting).
