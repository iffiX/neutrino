# Hermes WebUI

Hermes WebUI is the web interface of Hermes Agent, an AI assistant. Hermes Agent supports memory and skills, and you can open it on your phone at any time.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.0" />

Hermes WebUI runs in [Containers](/en/deploy/containers), with one instance per system. Everyone who uses it shares the same conversations.

## Supported systems

| System  | Architecture         | First Neutrino Hub version |
| ------- | -------------------- | -------------------------- |
| Linux   | amd64, arm64         | 0.6.0                      |
| Windows | amd64                | 0.6.0                      |
| macOS   | Apple silicon, Intel | 0.6.0                      |

## Install

Every model in Hermes WebUI comes from the AI gateway. Before you start, add an API key or a subscription account in the [AI gateway](/en/hub/ai_gateway).

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **Hermes WebUI** card, which shows **Needs: Containers**. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_hermes_webui_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the Hermes WebUI card marked in red](/guide/en/deploy_hermes_webui_02_catalog.webp "Select Hermes WebUI")
   ![The Hermes WebUI card highlighted, with the Close button marked in red](/guide/en/deploy_hermes_webui_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **Hermes WebUI** row in the list on the left, and its tab opens on the right. Select **Install**. If Containers is not installed yet, a confirmation appears first, and **Yes** installs both modules. In the pictures, Containers is already installed, so the confirmation does not appear.

   ![The module list with the Hermes WebUI row marked in red](/guide/en/deploy_hermes_webui_04_tab.webp "Select Hermes WebUI")
   ![The Hermes WebUI tab showing not installed, with the Install button marked in red](/guide/en/deploy_hermes_webui_05_install.webp "Select Install")

1. On Windows and macOS, the first installation then opens **Choose the account that runs the containers**. Choose an account and select **Install**; the details are in [Apps that need containers](/en/deploy/on_a_machine#apps-that-need-containers). Linux has no such dialog.

   ![The Choose the account that runs the containers dialog](/guide/zh/windows_account_dialog.webp)

1. On Windows, if a restart is needed, the tab shows a notice with **Restart now** beside it. Select **Restart now**. After the computer restarts, the installation continues automatically.

   ![The Hermes WebUI tab showing that Windows needs a restart, with the Restart now button marked in red](/guide/zh/deploy_hermes_webui_10_reboot.webp)

1. The tab lists each step. It pulls two images, which takes a few minutes. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with each step listed](/guide/en/deploy_hermes_webui_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button marked in red](/guide/en/deploy_hermes_webui_07_installed.webp "Select Start")

1. This step runs **First start**, which takes a few minutes the first time. When the tab shows **running**, the installation is complete.

   ![The tab running the First start step](/guide/en/deploy_hermes_webui_08_first_start.webp "First start")
   ![The tab showing running](/guide/en/deploy_hermes_webui_09_running.webp "Running")

## Use

Join your phone or computer to the hub first, as [Join the hub](/en/access/join) describes.

1. In the client, open the **Apps** page and find the **Hermes WebUI** row. Select **Use**, and the row shows a local address with the buttons **Stop**, **Configure** and **Open**. Select **Open**.

   ![The client's Apps page with the Use button marked in red](/guide/en/deploy_hermes_webui_40_client_use.webp "Select Use")
   ![The row with a local address, and the Open button marked in red](/guide/en/deploy_hermes_webui_41_client_open.webp "Select Open")

1. The browser opens a page that is already signed in. Enter your question in the input box at the bottom and send it. A new conversation uses the AI gateway's [default model](/en/hub/ai_gateway#default-model). To change the model, use the list beside the input box, which shows the models the AI gateway serves.

   ![Hermes WebUI in the browser](/guide/zh/deploy_hermes_webui_24_visitor.webp)

![A conversation in Hermes WebUI, with deepseek-flash as the model](/guide/zh/deploy_hermes_webui_30_chat.webp)

When you finish, return to the client and select **Stop**. On a phone, the steps are the same: on the **Apps** page, select **Use**, then **Open**.

## Share

Hermes WebUI can generate a link with [App share](/en/share/web_share), and the visitor opens it in a browser.

1. In the panel's left sidebar, select **Services**. Find the **Hermes WebUI** row and select **Share**.

   ![The Services page with the Share button of the Hermes WebUI row marked in red](/guide/en/deploy_hermes_webui_20_services_share.webp)

1. In the dialog, enter a **Name** that helps you recognize the link; the name is visible only to you. **Expires** defaults to 7 days, and you can choose another option. Select **Generate link**.

   ![The share dialog with the Name field marked in red](/guide/en/deploy_hermes_webui_21_share_dialog.webp "Enter a name")
   ![The share dialog filled in, with the Generate link button marked in red](/guide/en/deploy_hermes_webui_22_share_generate.webp "Select Generate link")

1. Select **Copy** right away and send the link to the visitor. Then select **Done** to close the dialog. After the dialog closes, the panel no longer shows the link.

   ![The share dialog showing the link and a QR code, with the link row marked in red](/guide/en/deploy_hermes_webui_23_share_link.webp "Select Copy")

The yellow notice in the dialog names the account hermeswebui, which is the account Hermes WebUI uses inside its container. The visitor opens the link without signing in and sees the page shown under Use.

## Risks and limits

Everyone who uses Hermes WebUI shares one set of conversations, memory and workspace. The visitor sees your conversations and uses your AI quota.

A share link that the Hermes page generates itself opens only in a browser that has signed in.

Hermes WebUI uses about 3.2 GB of disk for its images and about 2.4 GB for its cache. On Windows and macOS, every container app shares the memory of one virtual machine, and this app needs 1 GiB of it.

When Containers stops, Hermes WebUI also shows **stopped**. When Containers starts again, Hermes WebUI runs again.

## Settings

Hermes WebUI has no **Configure** button, and its tab holds only the status, the journal and the action buttons. To change the model, choose it on the Hermes page.

The Hermes page is dark by default. To switch to light, select the gear in the lower-left corner of the page, then choose **Light** under **Theme** in **Appearance**.

![The Appearance page with Light under Theme marked in red](/guide/zh/deploy_hermes_webui_25_theme.webp)

Its version is locked, so the **Install another version…** dialog lists a single version that cannot be selected. The two images are a tested pair, and each new Neutrino Hub release updates them.

## Uninstall

On the **Hermes WebUI** tab, select **Uninstall**. The red text in the dialog warns that the conversations, the settings and the files in the workspace are deleted for good. Copy out anything you want to keep first, then select the red **Uninstall** to confirm.

![The Hermes WebUI tab with the Uninstall button marked in red](/guide/en/deploy_hermes_webui_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with red text warning that the data is deleted](/guide/en/deploy_hermes_webui_51_uninstall_dialog.webp "Confirm")

Uninstalling Hermes WebUI leaves Containers installed.

If Hermes WebUI does not start, see [Troubleshooting](/en/reference/troubleshooting).
