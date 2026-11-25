---
title: "One-click deploy AstrBot"
description: "Neutrino Hub deploys AstrBot in one click on Windows, macOS or Linux: chat bots for QQ, WeChat, Telegram and Slack that answer with the hub's AI models."
---

# AstrBot

AstrBot is a chat bot platform that brings large language models into chat apps such as QQ, WeChat, Telegram and Slack, with its own web console. Its bots answer with the models of the hub's AI gateway.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.2" />

AstrBot runs in [Containers](/en/deploy/containers), with one instance per system. Everyone who opens it sees the same bots, conversations and plugins.

## Supported systems

| System  | Architecture         | First Neutrino Hub version |
| ------- | -------------------- | -------------------------- |
| Linux   | amd64, arm64         | 0.6.2                      |
| Windows | amd64                | 0.6.2                      |
| macOS   | Apple silicon, Intel | 0.6.2                      |

## Install

AstrBot follows the default account's **AI tools use the hub's gateway** switch. While the switch is on, the bots' models come from the AI gateway. Before you start, add an API key or a subscription account in the [AI gateway](/en/hub/ai_gateway). Then edit the default account on the system's page and turn the switch on, as [Systems joined to the hub](/en/hub/ai_gateway#systems-joined-to-the-hub) describes.

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **AstrBot** card, which shows **Needs: Containers**. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_astrbot_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the AstrBot card marked in red](/guide/en/deploy_astrbot_02_catalog.webp "Select AstrBot")
   ![The AstrBot card highlighted, with the Close button marked in red](/guide/en/deploy_astrbot_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **AstrBot** row in the list on the left, and its tab opens on the right. Select **Install**. If Containers is not installed yet, a confirmation appears first, and **Yes** installs both modules. In the pictures, Containers is already installed, so no confirmation appears.

   ![The module list with the AstrBot row marked in red](/guide/en/deploy_astrbot_04_tab.webp "Select AstrBot")
   ![The AstrBot tab showing not installed, with the Install button marked in red](/guide/en/deploy_astrbot_05_install.webp "Select Install")

1. On Windows and macOS, the first installation then opens **Run settings**. Check **CPUs**, **Memory (GiB)** and **Disk limit (GiB)**, then select **Install**. On Windows, if a restart is needed, the tab shows **Restart now**, and the installation continues after the restart. [Apps that need containers](/en/deploy/on_a_machine#apps-that-need-containers) has the details. Linux has no such dialog.

   ![The Run settings dialog with the Install button boxed in red](/guide/en/containers_run_settings.webp)

1. The tab lists each step. It pulls one image of about 723 MB, which takes a few minutes. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with each step listed](/guide/en/deploy_astrbot_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button marked in red](/guide/en/deploy_astrbot_07_installed.webp "Select Start")

1. This step runs **First start**, which usually takes about a minute. When the tab shows **running**, the installation is complete.

   ![The tab running the First start step](/guide/en/deploy_astrbot_08_first_start.webp "First start")
   ![The tab showing running](/guide/en/deploy_astrbot_09_running.webp "Running")

## Use

### Open AstrBot

Join your phone or computer to the hub first, as [Join the hub](/en/access/join) describes.

1. In the client, open the **Apps** page and find the **AstrBot** row. Select **Use**, and the row shows a local address with the buttons **Stop**, **Configure** and **Open**. Select **Open**.

   ![The client's Apps page with the Use button marked in red](/guide/en/deploy_astrbot_40_client_use.webp "Select Use")
   ![The row with a local address, and the Open button marked in red](/guide/en/deploy_astrbot_41_client_open.webp "Select Open")

1. The browser opens the AstrBot console already signed in, with no password to type. The first time, a welcome dialog opens first; select **关闭** at its bottom. You add bots, plugins and personas in the console. While the default account's **AI tools use the hub's gateway** is on, AstrBot is connected to the AI gateway and uses the gateway's [default model](/en/hub/ai_gateway#default-model). The console starts in Chinese whatever the browser's language. To switch it to English, select **选项** at the top right, then **English** under **语言**.

   ![The AstrBot console in the browser](/guide/en/deploy_astrbot_24_main.webp)

When you finish, return to the client and select **Stop**. On a phone, the steps are the same: on the **Apps** page, select **Use**, then **Open**. The bots keep running on the system whatever the client does.

### Chat platforms

On these platforms, AstrBot connects out to the platform's servers and sends and receives messages over that connection, so they work:

| Platform              | How the bot connects                   |
| --------------------- | -------------------------------------- |
| QQ official bot       | WebSocket                              |
| Personal WeChat       | Tencent's official iLink, by QR code   |
| WeCom AI bot          | Long connection                        |
| Feishu, Lark          | Long connection                        |
| DingTalk              | Stream                                 |
| Telegram              | Long polling                           |
| Discord               | Gateway                                |
| Slack                 | Socket Mode                            |
| Misskey, KOOK, Satori | WebSocket                              |
| Mattermost            | WebSocket; message buttons do not work |

These platforms use webhooks: the platform's servers send each message to a public HTTPS address you provide. The hub gives AstrBot no public address, so they do not work. Personal WeChat works, while WeChat Official Accounts do not:

| Platform                                       | Why                         |
| ---------------------------------------------- | --------------------------- |
| WeChat Official Accounts                       | Webhook only                |
| WeCom app, WeChat customer service             | Webhook only                |
| QQ official bot in webhook mode                | Needs a public callback URL |
| LINE                                           | Webhook only                |
| Feishu, WeCom AI bot and Slack in webhook mode | Needs a public callback URL |

### Connect NapCat

AstrBot does not include NapCat. If you installed NapCat yourself on the same system, point its OneBot v11 settings at `127.0.0.1:6199`, AstrBot's default port. After you add a OneBot v11 bot in AstrBot, it accepts NapCat's connection right away, with no restart.

The port opens on the system itself only. Other computers and the clients cannot reach it.

## Share

AstrBot can generate a link with [App share](/en/share/web_share), and the visitor opens it in a browser.

1. In the panel's left sidebar, select **Services**. Find the **AstrBot** row and select **Share**.

   ![The Services page with the Share button of the AstrBot row marked in red](/guide/en/deploy_astrbot_20_services_share.webp)

1. In the dialog, enter a **Name** that helps you recognize the link; the name is visible only to you. **Expires** defaults to 7 days, and you can choose another option. Select **Generate link**.

   ![The share dialog with the Name field marked in red](/guide/en/deploy_astrbot_21_share_dialog.webp "Enter a name")
   ![The share dialog filled in, with the Generate link button marked in red](/guide/en/deploy_astrbot_22_share_generate.webp "Select Generate link")

1. Select **Copy** right away and send the link to the visitor. Then select **Done** to close the dialog. After the dialog closes, the panel no longer shows the link.

   ![The share dialog showing the link and a QR code, with the link row marked in red](/guide/en/deploy_astrbot_23_share_link.webp "Select Copy")

The yellow notice in the dialog says that visitors use the app as astrbot, the one account of the AstrBot console. The visitor opens the link without signing in and lands in the console. Until the share is revoked or expires, the visitor can change your bots, plugins and conversations.

## Risks and limits

Everyone who opens AstrBot shares one set of bots, conversations and plugins, and uses your AI quota.

The hub manages a few settings of the AstrBot console, and changing them on the page fails: the password and the user name, two-factor sign-in, SSL, the port and the listen address. AstrBot's own update button does not work either. To change the version, use the tab, as the Settings section describes.

After you sign out in AstrBot, or 7 days after the sign-in, the page shows AstrBot's sign-in form, which cannot sign you in. Select **Open** in the client again.

If another program already holds `127.0.0.1:6199` on the system, AstrBot does not start.

AstrBot uses about 300 to 400 MB of memory when idle. Its image takes about 2.0 GB of disk, and its data grows with the plugins. On Windows and macOS, every container app shares the memory of one virtual machine, and this app needs 1 GiB of it.

When Containers stops, AstrBot also shows **stopped**. When Containers starts again, AstrBot runs again.

## Settings

AstrBot has no **Configure** button, and its tab holds only the status, the journal and the action buttons. Bots, plugins and models are all set in the AstrBot console.

AstrBot's default model follows the AI gateway's default model. The hub also writes that model's [context length](/en/hub/ai_gateway#context-length) into AstrBot, which compresses a conversation that grows past it. The models the hub adds have names starting with `neutrino_gateway/`. If you switch the default model in AstrBot to another one, the hub stops changing it. To follow the AI gateway again, choose the model the hub added as the default.

When you turn off the default account's **AI tools use the hub's gateway**, the hub deletes the provider it added from AstrBot. If the default model is one the hub added, the default model is cleared too. The providers you added and a default model you chose stay. Turn the switch on again, and the hub adds its provider again.

When you add a model to the AI gateway's source in AstrBot, the button that fetches the model list fails. Type the model's name instead, exactly as the AI gateway shows it.

| Setting                                  | Where                 | What it does                                                                                       |
| ---------------------------------------- | --------------------- | -------------------------------------------------------------------------------------------------- |
| **Update**, **Install another version…** | Under the tab's state | Changes the version, as [Change the version](/en/deploy/on_a_machine#change-the-version) describes |

AstrBot is upgrade only: its first start on a new version migrates the data, and an older version cannot read the migrated data. In the **Install another version…** list, versions older than the current one are grey and cannot be selected. Changing the version keeps the bots, plugins and settings.

## Uninstall

On the **AstrBot** tab, select **Uninstall**. The red text in the dialog warns that the bots, conversations, plugins and settings are deleted for good. Back up anything you want to keep in the AstrBot console first, then select the red **Uninstall**.

![The AstrBot tab with the Uninstall button marked in red](/guide/en/deploy_astrbot_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with red text warning that the data is deleted](/guide/en/deploy_astrbot_51_uninstall_dialog.webp "Confirm")

The uninstall also removes AstrBot's image when no other container uses it. The Containers module stays installed.

If AstrBot does not start, see [Troubleshooting](/en/reference/troubleshooting).
