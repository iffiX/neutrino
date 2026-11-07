# code-server

code-server is the open source VS Code that runs in a browser. You use it without accepting Microsoft's terms, and you can write code with it on a phone too.

<Facts systems="Linux,macOS" editions="国际版,国内版" since="0.5.0" />

Its extensions come from Open VSX, and each account runs one instance. On Windows its card is grey, because code-server has no Windows version. On Windows, you can use [VS Code](/en/deploy/vscode).

## Supported systems

| System | Architecture         | First Neutrino Hub version |
| ------ | -------------------- | -------------------------- |
| Linux  | amd64, arm64         | 0.5.0                      |
| macOS  | Apple silicon, Intel | 0.5.0                      |

## Install

1. Open the panel in a browser, sign in, and select the system to install on in the lower half of the sidebar. Check that **Available accounts** lists your account. If it does not, add it first with the steps in [Add an account](/en/deploy/on_a_machine#add-an-account).
1. In the **Module configuration** area, select **+ Add module**. In the dialog, select the **code-server** card, then select **Close** after the card is highlighted.

   ![The module list with the Add module button boxed in red](/guide/en/deploy_code_server_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the code-server card boxed in red](/guide/en/deploy_code_server_02_catalog.webp "Select code-server")
   ![The code-server card highlighted, with the Close button boxed in red](/guide/en/deploy_code_server_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **code-server** row in the list on the left, and its tab appears on the right. Select **Install**.

   ![The module list with the code-server row boxed in red](/guide/en/deploy_code_server_04_tab.webp "Select code-server")
   ![The code-server tab showing not installed, with the Install button boxed in red](/guide/en/deploy_code_server_05_install.webp "Select Install")

1. The tab lists every step while it downloads an archive and unpacks it, which usually takes less than a minute. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with every step listed](/guide/en/deploy_code_server_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button boxed in red](/guide/en/deploy_code_server_07_installed.webp "Select Start")

1. The tab shows **running, no accounts**. Select **Configure**, and the settings open under it. Under **Enabled accounts**, select your account.

   ![The tab showing running, no accounts, with the Configure button boxed in red](/guide/en/deploy_code_server_17_started.webp "Select Configure")
   ![The Enabled accounts field with the lab row boxed in red](/guide/en/deploy_code_server_08_tick_account.webp "Select lab")

1. Select **Apply code-server**. The account shows **running**, and **Applied.** appears under it. The install is complete.

   ![lab selected, with the Apply code-server button boxed in red](/guide/en/deploy_code_server_09_apply.webp "Select Apply code-server")
   ![lab showing running, with Applied. under it](/guide/en/deploy_code_server_10_applying.webp "Applied")

## Use

Before you start, add your phone or computer to the hub, as [Join the hub](/en/access/join) describes.

Open the client, go to the **Apps** page, and find the **code-server (lab)** row, with the account name in parentheses. Select **Use**. The row gains a local address, and its buttons become **Stop**, **Configure** and **Open**. Select **Open**.

![The client's Apps page with the Use button boxed in red](/guide/en/deploy_code_server_40_client_use.webp "Select Use")
![The row with a local address, and the Open button boxed in red](/guide/en/deploy_code_server_41_client_open.webp "Select Open")

The browser opens the editor, with no password to enter. The first open shows a welcome page; select **open a folder** in it and choose your project folder to start writing code. The menu in the top-left corner has **Terminal**, which opens this account's terminal.

![code-server in a browser, showing the welcome page](/guide/zh/deploy_code_server_16_visitor.webp)

When you finish, return to the client and select **Stop**, and the local address closes with it. When the sign-in expires, return to the client and select **Open** again.

On a phone, the steps are the same: on the **Apps** page, select **Use**, then **Open**.

## Share

code-server can generate a link with [App share](/en/share/web_share), and the other person opens it in a browser without installing any software.

1. In the panel sidebar, select **Services**, find the **code-server (lab)** row, and select **Share**.

   ![The Services page with the Share button of the code-server (lab) row boxed in red](/guide/en/deploy_code_server_12_services_share.webp)

1. In the dialog, enter a **Name** that helps you identify the share; the other person does not see it. The yellow notice under it says that the other person uses this app as this account. **Expires** defaults to 7 days, and you can choose another option before you select **Generate link**. Select **Copy** right away, send the link, then select **Done**; after the dialog closes, the panel no longer shows the link.

   ![The share dialog with the Name field boxed in red](/guide/en/deploy_code_server_13_share_dialog.webp "Enter a name")
   ![The completed share dialog with the Generate link button boxed in red](/guide/en/deploy_code_server_14_share_generate.webp "Select Generate link")
   ![The share dialog showing the link and a QR code, with the link row boxed in red](/guide/en/deploy_code_server_15_share_link.webp "Select Copy")

The other person opens the link without signing in, goes straight to the editor described earlier, and uses the same account as you.

## Risks and limits

If the other person opens the terminal inside, they can read and write this account's files and run commands. Send the link only to people you trust.

A development server you start in code-server does not appear in the client. To use one, declare it as [Add an existing service](/en/deploy/services) describes.

## Settings

Apart from enabling accounts, the following settings can stay at their defaults:

| Setting                                  | Where                                    | Purpose                                                                                                 |
| ---------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| **Enabled accounts**                     | **Configure** on the tab                 | Each selected account runs one instance                                                                 |
| **Update**, **Install another version…** | Under the tab's state                    | Change the version; for the steps, see [Change the version](/en/deploy/on_a_machine#change-the-version) |
| **AI tools use the hub's gateway**       | Account form in **Available accounts**   | This account's tools use the [AI gateway](/en/hub/ai_gateway)                                           |
| Extensions                               | **Extensions** on the left of the editor | Search, then select **Install**                                                                         |

## Uninstall

On the **code-server** tab, select **Uninstall**. The dialog states that each account's settings and extensions stay in its home folder. Select **Uninstall** to confirm.

![The code-server tab with the Uninstall button boxed in red](/guide/en/deploy_code_server_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with the Uninstall button boxed in red](/guide/en/deploy_code_server_51_uninstall_dialog.webp "Confirm")

If an error appears, see [Troubleshooting](/en/reference/troubleshooting).
