# Ayakaleaf

Ayakaleaf is a web editor for writing LaTeX papers. You can write together with other people, and the papers are stored on your own computer.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.0" />

Ayakaleaf runs in [Containers](/en/deploy/containers), with one instance per system. Its interface is in English and resembles Overleaf.

## Supported systems

| System  | Architecture         | First Neutrino Hub version |
| ------- | -------------------- | -------------------------- |
| Linux   | amd64, arm64         | 0.6.0                      |
| Windows | amd64                | 0.6.0                      |
| macOS   | Apple silicon, Intel | 0.6.0                      |

## Install

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **Ayakaleaf** card, which shows **Needs: Containers**. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_ayakaleaf_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the Ayakaleaf card marked in red](/guide/en/deploy_ayakaleaf_02_catalog.webp "Select Ayakaleaf")
   ![The Ayakaleaf card highlighted, with the Close button marked in red](/guide/en/deploy_ayakaleaf_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **Ayakaleaf** row in the list on the left, and its tab opens on the right. Select **Install**. If Containers is not installed yet, a confirmation appears first, and **Yes** installs both modules. In the pictures, Containers is already installed, so the confirmation does not appear.

   ![The module list with the Ayakaleaf row marked in red](/guide/en/deploy_ayakaleaf_04_tab.webp "Select Ayakaleaf")
   ![The Ayakaleaf tab showing not installed, with the Install button marked in red](/guide/en/deploy_ayakaleaf_05_install.webp "Select Install")

1. On Windows and macOS, the first installation then opens **Choose the account that runs the containers**. Choose an account and select **Install**; the details are in [Apps that need containers](/en/deploy/on_a_machine#apps-that-need-containers). Linux has no such dialog.

   ![The Choose the account that runs the containers dialog](/guide/zh/windows_account_dialog.webp)

1. On Windows, if a restart is needed, the tab shows a notice with **Restart now** beside it. Select **Restart now**. After the computer restarts, the installation continues automatically.

   ![The Ayakaleaf tab showing that Windows needs a restart, with the Restart now button marked in red](/guide/zh/deploy_ayakaleaf_10_reboot.webp)

1. The tab lists each step. It pulls three images, which takes a few minutes. To give up, you can select **Cancel**. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with each step listed](/guide/en/deploy_ayakaleaf_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button marked in red](/guide/en/deploy_ayakaleaf_07_installed.webp "Select Start")

1. On the first start, Ayakaleaf initializes its database, creates an administrator and installs the Chinese TeX packages. This takes from a few minutes to over ten minutes, and the start keeps running if you close the page. To give up, you can select **Cancel**. When the tab shows **running**, the installation is complete.

   ![The tab on the step that waits for the app to start, with the Cancel button marked in red](/guide/en/deploy_ayakaleaf_08_first_start.webp "First start")
   ![The tab showing running](/guide/en/deploy_ayakaleaf_09_running.webp "Running")

## Use

Join your phone or computer to the hub first, as [Join the hub](/en/access/join) describes.

1. In the client, open the **Apps** page and find the **Ayakaleaf** row. Select **Use**, and the row shows a local address with the buttons **Stop**, **Configure** and **Open**. Select **Open**.

   ![The client's Apps page with the Use button marked in red](/guide/en/deploy_ayakaleaf_40_client_use.webp "Select Use")
   ![The row with a local address, and the Open button marked in red](/guide/en/deploy_ayakaleaf_41_client_open.webp "Select Open")

1. The browser opens the project list, and you are signed in as the administrator without a password. Select **Create a new project**, then choose **Blank project** to create an empty project.

   ![The project list with Create a new project marked in red](/guide/zh/deploy_ayakaleaf_30_projects.webp "Select Create a new project")
   ![The open menu with Blank project marked in red](/guide/zh/deploy_ayakaleaf_31_new_menu.webp "Choose Blank project")

1. Enter a project name and select **Create**. The editor opens with the source on the left and the PDF on the right. To write in Chinese, select the gear in the lower-left corner, change **Compiler** from **pdfLaTeX** to **XeLaTeX**, and press Esc to close. The first start installs the Chinese packages, so begin the document with `\documentclass{ctexart}`.

   ![The new project dialog with the Create button marked in red](/guide/zh/deploy_ayakaleaf_32_new_name.webp "Select Create")
   ![The settings dialog with the Compiler field marked in red and XeLaTeX chosen](/guide/zh/deploy_ayakaleaf_33_compiler.webp "Choose XeLaTeX")

1. When you finish writing, select **Recompile** at the top of the right side. The compiled PDF appears on the right.

   ![The editor with the Recompile button marked in red](/guide/zh/deploy_ayakaleaf_34_editor.webp "Select Recompile")
   ![The source on the left and the compiled Chinese PDF on the right](/guide/zh/deploy_ayakaleaf_35_pdf.webp "Compiled PDF")

When you finish, return to the client and select **Stop**. On a phone, the steps are the same: on the **Apps** page, select **Use**, then **Open**.

## Share

Ayakaleaf can generate a link with [App share](/en/share/web_share). Each link has a guest account of its own, so the visitor signs in without registering or entering a password.

1. In the panel's left sidebar, select **Services**. Find the **Ayakaleaf** row and select **Share**.

   ![The Services page with the Share button of the Ayakaleaf row marked in red](/guide/en/deploy_ayakaleaf_20_services_share.webp)

1. In the dialog, enter a **Name** that helps you recognize the link; the name is visible only to you. **Expires** defaults to 7 days, and you can choose another option. Select **Generate link**.

   ![The share dialog with the Name field marked in red](/guide/en/deploy_ayakaleaf_21_share_dialog.webp "Enter a name")
   ![The share dialog filled in, with the Generate link button marked in red](/guide/en/deploy_ayakaleaf_22_share_generate.webp "Select Generate link")

1. Select **Copy** right away and send the link to the visitor. Keep the dialog open, because after it closes, the panel no longer shows the link.

   ![The share dialog showing the link and a QR code, with the link row marked in red](/guide/en/deploy_ayakaleaf_23_share_link.webp "Select Copy")

Under the link, the dialog also shows a guest address such as `guest-a1b2@share.neutrino`, and the picture shows an example address. Copy this address for the invitation that follows, then select **Done** to close the dialog. While the share's **Status** shows **preparing**, wait a moment before you continue.

The visitor sees only the projects that you invite this guest address to, so you must also send an invitation.

Open the project and select **Share** in the top-right corner. Paste the guest address into **Add email address** and select **Invite**. A new row appears with the address and **Editor**. You can ignore the **Invite not yet accepted.** beside it, because the invitation is accepted automatically when the visitor opens the link.

![The Share Project dialog with the Invite button marked in red](/guide/zh/deploy_ayakaleaf_36_share_project.webp "Select Invite")
![A row with the guest address added to the dialog](/guide/zh/deploy_ayakaleaf_37_invited.webp "New row")

When the visitor opens the link, the project list opens directly.

![The project list open in the visitor's browser](/guide/zh/deploy_ayakaleaf_24_visitor.webp)

When the share is revoked or expires, the guest account is deleted, and its changes stay in the project.

## Risks and limits

All compilations run in the same container with no isolation between them, so send the link only to people you trust.

Ayakaleaf uses about 1.6 GB of memory when idle and about 5.5 GB of disk. On Windows and macOS, the virtual machine must reserve 3 GiB of memory, and when memory is short, the tab shows the suggested value. With too little memory, Ayakaleaf still runs, only slower.

When you change the version, the TeX packages install again, which takes a few more minutes.

Ayakaleaf limits zip downloads to 10 per minute. Past that limit, the page shows an error, and refreshing the page restores it.

The Git sync feature of Ayakaleaf is unavailable.

## Settings

Apart from the version, the following settings can stay at their defaults. To change them, select **Configure** on the tab.

![The Ayakaleaf configuration with the AI model field](/guide/en/deploy_ayakaleaf_47_config.webp)

| Setting                                  | Where                       | What it does                                                                                       |
| ---------------------------------------- | --------------------------- | -------------------------------------------------------------------------------------------------- |
| **AI model**                             | **Configure** on the tab    | The model the AI assistant in the editor uses; set up the [AI gateway](/en/hub/ai_gateway) first   |
| **Apply Ayakaleaf**                      | **Configure** on the tab    | Saves the settings; Ayakaleaf restarts, and open editors connect again                             |
| **Update**, **Install another version…** | Under the status on the tab | Changes the version; the steps are in [Change version](/en/deploy/on_a_machine#change-the-version) |

Ayakaleaf only upgrades, because an older version can fail to read data that a newer version migrated. In the **Install another version…** list, versions older than the installed one are grey and cannot be selected.

![The version list, with the versions older than the installed one in grey](/guide/en/deploy_ayakaleaf_44_version_dialog.webp)

## Uninstall

On the **Ayakaleaf** tab, select **Uninstall**. The red text in the dialog warns that the papers and projects are deleted for good. Download the projects you want to keep from Ayakaleaf first, then select the red **Uninstall** to confirm.

![The Ayakaleaf tab with the Uninstall button marked in red](/guide/en/deploy_ayakaleaf_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with red text warning that the data is deleted](/guide/en/deploy_ayakaleaf_51_uninstall_dialog.webp "Confirm")

Uninstalling Ayakaleaf leaves Containers installed.

If the installation or the start stays on one step, see [Troubleshooting](/en/reference/troubleshooting).
