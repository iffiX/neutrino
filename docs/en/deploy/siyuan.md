# SiYuan

SiYuan is note-taking and knowledge base software. You open the same notes on your phone and your laptop, and the notes are stored on your own computer.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.0" />

SiYuan runs one instance per account, and the notes of each account are kept apart from the others.

## Supported systems

| System  | Architecture         | First Neutrino Hub version |
| ------- | -------------------- | -------------------------- |
| Linux   | amd64, arm64         | 0.6.0                      |
| Windows | amd64                | 0.6.0                      |
| macOS   | Apple silicon, Intel | 0.6.0                      |

## Install

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on. Check that **Available accounts** lists your account. If it does not, add it as [Add an account](/en/deploy/on_a_machine#add-an-account) describes.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **SiYuan** card. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_siyuan_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the SiYuan card marked in red](/guide/en/deploy_siyuan_02_catalog.webp "Select SiYuan")
   ![The SiYuan card highlighted, with the Close button marked in red](/guide/en/deploy_siyuan_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **SiYuan** row in the list on the left, and its tab opens on the right. Select **Install**.

   ![The module list with the SiYuan row marked in red](/guide/en/deploy_siyuan_04_tab.webp "Select SiYuan")
   ![The SiYuan tab showing not installed, with the Install button marked in red](/guide/en/deploy_siyuan_05_install.webp "Select Install")

1. The tab lists each step. It downloads the full desktop edition, which is 700 to 800 MB unpacked, so this step takes a while. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with each step listed](/guide/en/deploy_siyuan_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button marked in red](/guide/en/deploy_siyuan_07_installed.webp "Select Start")

1. The tab shows **running, no accounts**. Select **Configure** to expand the settings. Under **Enabled accounts**, select your account.

   ![The tab showing running, no accounts, with the Configure button marked in red](/guide/en/deploy_siyuan_17_started.webp "Select Configure")
   ![The Enabled accounts field with the lab row marked in red](/guide/en/deploy_siyuan_08_tick_account.webp "Select lab")

1. Select **Apply SiYuan**. The button changes to **Applying…** for a few seconds. When the step list on the tab gains **Set up account lab** and the tab shows **running**, the installation is complete.

   ![lab selected, with the Apply SiYuan button marked in red](/guide/en/deploy_siyuan_09_apply.webp "Select Apply SiYuan")
   ![The tab showing running, with a green dot on every step](/guide/en/deploy_siyuan_11_running.webp "Running")

## Use

Before you start, join your phone or computer to the hub, as [Join the hub](/en/access/join) describes.

In the client, open the **Apps** page and find the **SiYuan (lab)** row, where the name in parentheses is the account. Select **Use**, and the row shows a local address with the buttons **Stop**, **Configure** and **Open**. Select **Open**.

![The client's Apps page with the Use button marked in red](/guide/en/deploy_siyuan_40_client_use.webp "Select Use")
![The row with a local address, and the Open button marked in red](/guide/en/deploy_siyuan_41_client_open.webp "Select Open")

SiYuan opens in the browser without an access password. On the first visit, it already holds a notebook and a document named **A Fresh Start**, and you can type in the body right away.

![SiYuan in the browser](/guide/en/deploy_siyuan_16_visitor.webp)

To change the interface language, use the settings of SiYuan itself. When you finish, return to the client and select **Stop**. On a phone, the steps are the same: on the **Apps** page, select **Use**, then **Open**.

## Share

SiYuan can generate a link with [App share](/en/share/web_share), and the visitor opens it in a browser.

1. In the panel's left sidebar, select **Services**. Find the **SiYuan (lab)** row and select **Share**.

   ![The Services page with the Share button of the SiYuan (lab) row marked in red](/guide/en/deploy_siyuan_12_services_share.webp)

1. In the dialog, enter a **Name** that helps you recognize the link; the name is visible only to you. The yellow notice under it states that the visitor uses this app as this account. **Expires** defaults to 7 days, and you can choose another option. Select **Generate link**.

   ![The share dialog with the Name field marked in red](/guide/en/deploy_siyuan_13_share_dialog.webp "Enter a name")
   ![The share dialog filled in, with the Generate link button marked in red](/guide/en/deploy_siyuan_14_share_generate.webp "Select Generate link")

1. Select **Copy** right away and send the link to the visitor. Then select **Done** to close the dialog. After the dialog closes, the panel no longer shows the link.

   ![The share dialog showing the link and a QR code, with the link row marked in red](/guide/en/deploy_siyuan_15_share_link.webp "Select Copy")

The visitor opens the link without signing in and uses the same account as you. The visitor can view, edit and delete every note of this account.

To share only some notes, add another account on this system and keep only the notes to share in it. Then share the row of that account.

## Risks and limits

The SiYuan here and the desktop edition on your computer keep separate notes, so import your existing notes by hand.

The AI settings gain a provider automatically, which uses models from the [AI gateway](/en/hub/ai_gateway), and the visitor can use it too. When the accounts or providers of the gateway change, SiYuan restarts one time for every account.

## Settings

Apart from the enabled accounts, the following settings can stay at their defaults:

| Setting                                  | Where                       | What it does                                                                                                                                       |
| ---------------------------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Enabled accounts**                     | **Configure** on the tab    | Each selected account has its own notes                                                                                                            |
| **Update**, **Install another version…** | Under the status on the tab | Changes the version; the steps are in [Change version](/en/deploy/on_a_machine#change-the-version). SiYuan downloads no new packages automatically |

## Uninstall

On the **SiYuan** tab, select **Uninstall**. The dialog shows the folder where the notes of each account stay. Select **Uninstall** to confirm.

![The SiYuan tab with the Uninstall button marked in red](/guide/en/deploy_siyuan_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with the Uninstall button marked in red](/guide/en/deploy_siyuan_51_uninstall_dialog.webp "Confirm")

When you clear only one account, its notes also stay.

If SiYuan does not start, see [Troubleshooting](/en/reference/troubleshooting).
