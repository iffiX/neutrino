---
description: "Neutrino Hub installs apps on any system that joined it, from the panel: pick the system, add the module, select Install. Every system works the same."
---

# Install an app on a system

You can install an app from the panel on any system that has joined the hub. A system is a computer that has joined the hub, and the computer running the hub has joined already, so you start with one system.

The steps use code-server as the example: add the module, install, start, add more accounts, stop, change the version and uninstall. Other apps follow the same steps, and each app's own page covers its differences. The panel calls an app a **module**.

## Open the system's page

1. Open the panel in a browser and sign in.
1. In the lower half of the sidebar, which lists every system that has joined the hub, select the system to install the app on.

   ![The lower half of the sidebar, with the system's name boxed in red](/guide/en/deploy_on_a_machine_01_sidebar.webp)

The system's page opens on the right. Monitoring is at the top, and further down are the **Available accounts** and **Module configuration** areas. Every later step happens in these two areas.

## Accounts

An app runs as a system account, and the files it creates belong to that account. **Available accounts** lists the accounts the hub can use.

Every system has one default account, whose row carries the **Default** chip, and it cannot be changed later. Terminal, SSH server, File share and every app that runs as an account enable the default account automatically. So you choose no account when you install an app. The system that runs the hub got its default account in the [setup wizard](/en/hub/install). A system joined by a link or over SSH needs its first account first, as [Add the first account](#add-the-first-account) describes. On an upgrade from 0.6.1, the account added earliest on each system becomes its default account automatically. A system with no account yet shows **incomplete**.

### Add another account

If another account on this system also uses apps, add it to **Available accounts**. You add each account only one time.

1. In the **Available accounts** area, select **Add** in the top-right corner.

   ![The Available accounts area with the lab row carrying the Default chip and the Add button boxed in red](/guide/en/deploy_on_a_machine_02_accounts.webp)

1. In the form that opens, select the **System account** field. The list shows the accounts on this system that can sign in and are not added yet, with each one's home folder on the right. Select the account to add, here dev.

   ![The account form with the System account field boxed in red](/guide/en/deploy_on_a_machine_03_account_form2.webp "Select System account")
   ![The system account list with the dev row boxed in red](/guide/en/deploy_on_a_machine_04_account_pick_dev.webp "Select dev")

1. Leave the remaining fields empty and select **Save**.

   ![The completed form with the Save button boxed in red](/guide/en/deploy_on_a_machine_05_account_save_dev.webp)

1. The hub first tests that the account can sign in, then saves it. The account appears in the list when it is added.

   ![The list with the new dev row under lab, boxed in red](/guide/en/deploy_on_a_machine_06_account_saved_dev.webp)

If the test fails, the reason appears under the form and nothing is saved. On Linux and macOS, the test checks that the account has a login shell and that its home folder exists. On Windows, the test signs in one time with the password in the form.

The list holds only accounts that can sign in. On Linux and macOS, these are the accounts with a login shell and a home folder that exists. On Windows, these are the accounts that have signed in on this computer at least one time. If the account you want is missing, sign in as it on the computer one time first.

The other fields of the form usually stay empty, and the defaults work for every later step. The fields are:

| Setting                            | Purpose                                                                                                                         |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **Share path**                     | The folder that File share shares for this account; when empty, the account's home folder                                       |
| **Shell**                          | The program that runs when you open a terminal; when empty, the account's own shell                                             |
| **AI tools use the hub's gateway** | This account's AI tools use the [AI gateway](/en/hub/ai_gateway). You cannot turn this switch on while the gateway has no model |

On Windows, the form has an extra **Password** field. Enter the password this account uses to sign in to Windows. Neutrino Hub signs in as this account with it to run apps on this system. Enter the password even if you normally sign in with a PIN. With a wrong password, the form shows **Windows does not accept this password for dev. Type the right one and try again.** A later password change is tested the same way.

![The account form of a Windows system, with the Password field boxed in red](/guide/en/deploy_on_a_machine_44_windows_account.webp)

Later, select **Edit** on the account's row to change its settings, or **Remove** to delete it; the dialog lists the apps that stop running as it. The default account has no **Remove**.

![The dialog that removes dev, with the Remove button boxed in red](/guide/en/deploy_on_a_machine_91_remove_dev.webp)

### Add the first account

A system joined by a link or over SSH starts with no account. Its name in the sidebar then shows a yellow dot and **incomplete**, and the top of its page shows **incomplete** too. Every module and **+ Add module** are grey, and the modules show **Add this machine's default account under Available accounts first.**

![The page of an incomplete system, with Available accounts empty and the Add button boxed in red](/guide/en/deploy_on_a_machine_46_incomplete.webp)

1. Select **Add** in the top-right corner of **Available accounts**, choose the account you normally use as the previous section describes, and select **Save**.
1. A dialog shows **Make lab the default account** and says that it cannot be changed later. When this is the right account, select **Make default**.

   ![The Make lab the default account dialog with the Make default button boxed in red](/guide/en/deploy_on_a_machine_47_first_confirm.webp)

When the account carries the **Default** chip, **incomplete** disappears and the modules become available. Terminal and SSH server already have this account enabled.

### A wrong default account

The default account cannot be changed. If you chose the wrong account, or the system deleted it, join the system again:

- A system joined by a link or over SSH: on the **Agents** page, select [Forget](/en/hub/agents#forget) on its row. Then [uninstall the agent](/en/hub/uninstall) on that computer, install it again, join the hub, and add the first account.
- The system that runs the hub: [uninstall the hub](/en/hub/uninstall) together with its configuration, then install it again. The setup wizard asks for the account again.

## Add the module

The left side of the **Module configuration** area is the module list. At first it holds only **Terminal**, **SSH server** and **Remote desktop**, and these three are already installed. Add any other app to this list first, and it appears under these three in a fixed order, which [App sources and kinds](/en/deploy/app_kinds) lists.

1. Under the list, select **+ Add module**.

   ![The module list with the Add module button boxed in red](/guide/en/deploy_on_a_machine_07_add_module.webp)

1. In the dialog, each card is one app; the buttons along the top filter by purpose, and the box in the top-right corner searches. Select the checkbox in the top-right corner of the app's card, here code-server. The card is highlighted when the app is in the list. You can select more apps, then select **Close**.

   ![The Add module dialog with the code-server card boxed in red](/guide/en/deploy_on_a_machine_08_catalog.webp "Select code-server")
   ![The code-server card highlighted, with the Close button boxed in red](/guide/en/deploy_on_a_machine_09_catalog_ticked.webp "Select Close")

This step only adds a tab, and the software stays uninstalled until the next section. To remove a tab you no longer need, open the dialog and deselect the app. You cannot deselect an installed app; uninstall it first. A grey card without a checkbox cannot be added, because this system cannot run the app.

## Install

1. In the list on the left, select the code-server row, and its tab appears on the right. The **Upstream** and **Account service** chips after the title show its source and kind, which [App sources and kinds](/en/deploy/app_kinds) explains. Then select **Install**.

   ![The module list with the code-server row boxed in red](/guide/en/deploy_on_a_machine_10_tab.webp "Select code-server")
   ![The code-server tab showing not installed, with the Install button boxed in red](/guide/en/deploy_on_a_machine_11_install.webp "Select Install")

1. The tab lists every step. A green dot marks a finished step, a yellow dot a running step, and a grey dot a step not started yet. The row on the left also shows `1/2`, meaning step 1 of 2.

   ![The tab showing installing, with two steps listed and the Cancel button boxed in red](/guide/en/deploy_on_a_machine_12_installing.webp)

1. When the tab shows **installed**, the install is complete. The app is not running yet.

   ![The tab showing installed, with the Start button boxed in red](/guide/en/deploy_on_a_machine_14_installed.webp)

Each download uses a fast and stable source that is chosen automatically. An install that a program runs itself, such as npm or pip, uses one source from start to finish. If a step cannot start yet, the reason appears under that step. Several apps can install at the same time and queue only when they need the same resource; the tab then shows **queued**.

The **Log · last 200 lines** box further down shows only the app's own log, so it is usually empty during an install. The step list shows the install's progress.

During a first install, the **Install** button becomes **Cancel**. To abandon the install, select **Cancel**, then select **Cancel install** in the dialog. The running step finishes, the later steps are skipped, and everything installed so far is removed. To continue instead, select **Keep installing**.

![The cancel-install dialog with the Cancel install button boxed in red](/guide/en/deploy_on_a_machine_13_cancel_dialog.webp)

Ayakaleaf's first start takes longer, and the **Cancel** button also shows during that time. The button is absent while you change versions and for an app that is already installed.

## Start

An installed app is a service on this system. **Start** runs it and **Stop** stops it. Terminal, SSH server and Remote desktop are exceptions, with no **Start** or **Stop**.

1. Select **Start**, the button boxed in red in the previous picture.
1. The tab shows **running**. code-server already runs as the default account lab, with nothing more to set.

   ![The tab showing running, with the Configure button boxed in red](/guide/en/deploy_on_a_machine_19_running.webp)

The app now appears on the client's **Apps** page, with the account name after its name, for example `code-server (lab)`. Each app's own page explains how to use it.

## Add more accounts

Terminal, SSH server, File share, VS Code, code-server, CloudCLI, Codeg, SiYuan, Claude Code, Codex and OpenCode can add more accounts. The app runs one instance for each account you enable. The default account stays enabled and cannot be cleared. An account must be in **Available accounts** before you enable it; see [Add another account](#add-another-account).

1. Select **Configure**, and the settings open under the tab. Under **Enabled accounts**, the default account lab is already selected and grey. Select the account to add, here dev.

   ![The Enabled accounts field with lab selected and the dev row boxed in red](/guide/en/deploy_on_a_machine_15_tick_dev.webp)

1. The button further down becomes active; select **Apply code-server**.

   ![dev selected, with the Apply code-server button boxed in red](/guide/en/deploy_on_a_machine_16_apply_dev.webp)

1. A few seconds later, dev shows **running**, and the bar under the list returns to **Nothing changed here.** The client now also lists `code-server (dev)`.

   ![lab and dev both showing running](/guide/en/deploy_on_a_machine_17_applied_dev.webp)

Select **Hide configuration** to close the settings, and the log box then shows the app's own log.

![The tab showing running, with output in the log box](/guide/en/deploy_on_a_machine_18_running.webp)

Adding an account or changing a setting does not start the app. While the app is stopped, you can also configure first and select **Start** later, and the configuration then shows **The module is stopped; these settings take effect at the next Start.**

The other apps run one instance per system and have no **Enabled accounts** field. On Windows and macOS, Containers runs as the default account. Hermes WebUI, Ayakaleaf and AstrBot follow the default account's **AI tools use the hub's gateway** switch, and use the AI gateway while it is on. For Gitea, Containers and Ayakaleaf, **Configure** opens their own settings, which their pages describe. Hermes WebUI and AstrBot have no **Configure** button.

## Stop

You can stop an app you do not need for a while, which frees the memory and ports it uses.

1. Select **Stop**.

   ![The tab showing running, with the Stop button boxed in red](/guide/en/deploy_on_a_machine_30_stop.webp)

1. The tab shows **stopped**. When you need the app, select **Start**, and the tab returns to **running**.

   ![The tab showing stopped, with the Start button boxed in red](/guide/en/deploy_on_a_machine_31_stopped.webp "Select Start")
   ![The tab showing running again](/guide/en/deploy_on_a_machine_32_started.webp "Running again")

A stopped app stays stopped through a restart of the computer, until you select **Start**. Meanwhile its row disappears from the client and its share links do not open; the links stay the same and work again after the start. While the app is stopped, you can change accounts, add shared folders and select **Configure**, and none of these starts it. After a change, the settings show **The module is stopped; these settings take effect at the next Start.**

![An app's settings showing The module is stopped; these settings take effect at the next Start](/guide/en/deploy_on_a_machine_43_stopped_hint.webp)

## Change the version

The **Install** button installs the version Neutrino Hub has tested. The tab shows `Installed 4.140.0 · newest 4.145.2`: the first number is the installed version, and the second is the publisher's newest version.

1. Select **Install another version…**.

   ![The version row with the Install another version button boxed in red](/guide/en/deploy_on_a_machine_33_version_button.webp)

1. The dialog lists newer versions first. **tested** marks the tested version, **untested** marks the versions newer than it, and a check mark shows the installed one. Select the version you want, here 4.139.1. The dialog closes, the tab starts **Switch to version 4.139.1**, and the app then configures and starts.

   ![The version list with the 4.139.1 row boxed in red](/guide/en/deploy_on_a_machine_34_version_dialog.webp "Select 4.139.1")
   ![The tab showing installing, with Switch to version 4.139.1 as the first step](/guide/en/deploy_on_a_machine_35_version_switching.webp "Switch to this version")

1. The tab returns to **running**, and the version row shows the new version.

   ![The version row showing Installed 4.139.1, with the Update button boxed in red](/guide/en/deploy_on_a_machine_36_version_older.webp)

The **Update** button beside it switches straight to the newest version. The newest version can be **untested**, and if it causes problems, you can switch back to the previous version. The button is grey when the newest version is already installed.

![Already on the newest version 4.145.2, with the Update button grey](/guide/en/deploy_on_a_machine_38_updated.webp)

To return to the tested version, select **Follow the tested version** at the top of the dialog. The panel has no switch for automatic updates. Hermes WebUI, File share and Containers on Linux have no version choice, and their dialog shows one version you cannot select. Gitea, Ayakaleaf, AstrBot, Codeg and CloudCLI carry **Upgrade only** on their tab. In their dialog, the versions older than the installed one are grey and cannot be selected; see [App kinds](/en/deploy/app_kinds#upgrade-only).

## Uninstall

1. Select **Uninstall**.

   ![The Uninstall button boxed in red](/guide/en/deploy_on_a_machine_39_uninstall.webp)

1. The second sentence of the dialog says whether the app's data is kept or deleted; code-server's settings and extensions stay in the home folder. If the app deletes data, that sentence and the confirm button are red. Select **Uninstall** to confirm. To keep the app, select **Cancel** or select outside the dialog.

   ![The uninstall dialog with the Uninstall button boxed in red](/guide/en/deploy_on_a_machine_40_uninstall_dialog.webp)

1. The tab returns to **not installed**.

   ![The tab showing not installed, with the Install button available again](/guide/en/deploy_on_a_machine_42_uninstalled.webp)

Uninstalling ends every share of the app, and you must generate new links to use it again. The tab stays in the list; to hide it, deselect the app in **+ Add module**. When you install the same app again, the accounts enabled last time stay enabled, and the app runs after you select **Start**. While another app needs Containers, uninstall that app before you uninstall Containers.

## Apps that need containers

Hermes WebUI, Ayakaleaf and AstrBot run in containers, and their cards show **Needs: Containers**.

![The Hermes WebUI card showing that it needs Containers, boxed in red](/guide/en/deploy_on_a_machine_20_requires_card.webp)

If Containers is not installed yet, **Install** first opens a confirmation that shows **Installing this also installs:** and **Containers**. **Yes** installs both modules, and **No** installs neither.

![The confirmation listing Containers, with the No and Yes buttons](/guide/en/deploy_on_a_machine_21_requires_dialog.webp)

On Linux, this is the last step. On Windows and macOS, the containers run in a virtual machine of the default account, and the first install opens **Run settings** next.

1. Check the default values of **CPUs**, **Memory (GiB)** and **Disk limit (GiB)**. After the virtual machine's first start, a CPU or memory change needs a restart of the virtual machine, and the disk can only grow.
1. Select **Install**.

![The Run settings dialog with the Install button boxed in red](/guide/en/containers_run_settings.webp)

On Windows, installing Containers can need a restart of the computer. The Containers tab then shows **Windows needs a restart to finish turning on WSL; the install goes on after it.** with **Restart now** beside it. Save your work first, because every program open on this system closes; then select **Restart now**, and **Restart** in the dialog. The install continues automatically after the restart, and apps that wait for Containers show the same button on their tabs.

![The Containers tab showing that Windows needs a restart, with Restart now boxed in red](/guide/en/deploy_containers_18_reboot.webp)

## Errors and offline systems

When the tab shows **install failed** or **failed**, the reason appears under the failed step. Fix the problem, then select the same button again to retry. When the tab shows **install failed**, you can also select **Uninstall** to remove a half-finished install.

![The File share tab showing install failed, with the reason under the failed step](/guide/en/deploy_on_a_machine_23_failed.webp)

While this system is offline, every button is grey and the tab shows **The agent is offline**. The buttons become available again when the system reconnects to the hub. For the meaning of each error message and its fix, see [Troubleshooting](/en/reference/troubleshooting).
