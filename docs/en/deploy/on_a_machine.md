# Install an app on a system

You can install an app from the panel on any system that has joined the hub. A system is a computer that has joined the hub, and the computer running the hub has joined already, so you start with one system.

The steps use code-server as the example: add an account, add the module, install, start, configure, stop, change the version and uninstall. Other apps follow the same steps, and each app's own page covers its differences. The panel calls an app a **module**.

## Open the system's page

1. Open the panel in a browser and sign in.
1. In the lower half of the sidebar, which lists every system that has joined the hub, select the system to install the app on.

   ![The lower half of the sidebar, with the system's name boxed in red](/guide/en/deploy_on_a_machine_01_sidebar.webp)

The system's page opens on the right. Monitoring is at the top, and further down are the **Available accounts** and **Module configuration** areas. Every later step happens in these two areas.

## Add an account

An app runs as a system account, and the files it creates belong to that account. Before anything else, set which accounts the hub can use. You add each account only one time.

1. In the **Available accounts** area, select **Add** in the top-right corner.

   ![The Available accounts area with the Add button boxed in red](/guide/en/deploy_on_a_machine_02_accounts_add.webp)

1. In the form that opens, select the **System account** field. The list shows the accounts on this system, with each one's home folder on the right. Select the account you normally use, here lab.

   ![The account form with the System account field boxed in red](/guide/en/deploy_on_a_machine_03_account_form.webp "Select System account")
   ![The system account list with the lab row boxed in red](/guide/en/deploy_on_a_machine_04_account_pick.webp "Select lab")

1. Leave the remaining fields empty and select **Save**.

   ![The completed form with the Save button boxed in red](/guide/en/deploy_on_a_machine_05_account_save.webp)

The account appears in the list when it is added.

![The list with the new lab row boxed in red](/guide/en/deploy_on_a_machine_06_account_saved.webp)

The other fields of the form usually stay empty, and the defaults work for every later step. The fields are:

| Setting                            | Purpose                                                                                                                         |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **Share path**                     | The folder that File share shares for this account; when empty, the account's home folder                                       |
| **Shell**                          | The program that runs when you open a terminal; when empty, the account's own shell                                             |
| **AI tools use the hub's gateway** | This account's AI tools use the [AI gateway](/en/hub/ai_gateway). You cannot turn this switch on while the gateway has no model |

On Windows, the form has an extra **Password** field. Enter the password this account uses to sign in to Windows. Neutrino Hub signs in as this account with it to run apps on this system. Enter the password even if you normally sign in with a PIN.

![The account form of a Windows system, with the Password field boxed in red](/guide/en/deploy_on_a_machine_44_windows_account.webp)

If the Windows account has never signed in, you cannot enable SSH, VS Code, CloudCLI, Codeg or SiYuan; the limit does not apply to Containers. The tab shows **lab has never signed in on this machine. Sign in as lab once, then try again.** Sign in as this account on the computer one time, then return to the panel and select the same button again. Later, select **Edit** on the account's row to change its settings, or **Remove** to delete it; the dialog lists the apps that stop running as it.

![The remove-account dialog with the Remove button boxed in red](/guide/en/deploy_on_a_machine_90_account_remove.webp)

## Add the module

The left side of the **Module configuration** area is the module list. At first it holds only **Terminal**, **SSH server** and **Remote desktop**, and these three are already installed. Add any other app to this list first, and it appears under these three in a fixed order, which [App sources and kinds](/en/deploy/app_kinds) lists.

1. Under the list, select **+ Add module**.

   ![The module list with the Add module button boxed in red](/guide/en/deploy_on_a_machine_07_add_module.webp)

1. In the dialog, each card is one app; the buttons along the top filter by purpose, and the box in the top-right corner searches. Select the checkbox in the top-right corner of the app's card, here code-server. The card is highlighted when the app is in the list. You can select more apps, then select **Close**.

   ![The Add module dialog with the code-server card boxed in red](/guide/en/deploy_on_a_machine_08_catalog.webp "Select code-server")
   ![The code-server card highlighted, with the Close button boxed in red](/guide/en/deploy_on_a_machine_09_catalog_ticked.webp "Select Close")

This step only adds a tab, and the software stays uninstalled until the next section. To remove a tab you no longer need, open the dialog and deselect the app. You cannot deselect an installed app; uninstall it first. A grey card without a checkbox cannot be added, because this system cannot run the app.

## Install

1. In the list on the left, select the code-server row, and its tab appears on the right. The **Upstream** and **Service** chips after the title show its source and kind, which [App sources and kinds](/en/deploy/app_kinds) explains. Then select **Install**.

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

An installed app is a service on this system. **Start** runs it and **Stop** stops it, however many accounts are enabled. Terminal, SSH server and Remote desktop are exceptions: they have no **Start** or **Stop**, and they run after you select the apply button in their settings.

1. Select **Start**, the button boxed in red in the previous picture.
1. The tab shows **running, no accounts**: the app has started, but no account is enabled yet. The client does not list the app yet.

   ![The tab showing running, no accounts, with the Configure button boxed in red](/guide/en/deploy_on_a_machine_19_started_no_account.webp)

## Configure

Configuring chooses the accounts the app runs as. The app runs one instance for each account you select.

1. Select **Configure**, and the settings open under the tab. Under **Enabled accounts**, select your account. The button further down becomes active; select **Apply code-server**.

   ![The Enabled accounts field with the lab row boxed in red](/guide/en/deploy_on_a_machine_15_tick_account.webp "Select lab")
   ![lab selected, with the Apply code-server button boxed in red](/guide/en/deploy_on_a_machine_16_apply.webp "Select Apply code-server")

1. The account shows **running**, and **Applied.** appears under it. The configuration is complete, and the tab also shows **running**.

   ![lab showing running, with Applied. under it](/guide/en/deploy_on_a_machine_17_applying.webp)

Select **Hide configuration** to close the settings, and the log box then shows the app's own log.

![The tab showing running, with output in the log box](/guide/en/deploy_on_a_machine_18_running.webp)

The app now appears on the client's **Apps** page, with the account name after its name, for example `code-server (lab)`. Each app's own page explains how to use it. Adding an account or changing a setting does not start the app. You can also configure first and select **Start** later, and the configuration then shows **The module is stopped; these settings take effect at the next Start.**

Gitea, Containers, Hermes WebUI and Ayakaleaf have no **Enabled accounts** field, and each runs one instance per system. For Gitea, Containers and Ayakaleaf, **Configure** opens their own settings, which their pages describe. Hermes WebUI has no **Configure** button.

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

To return to the tested version, select **Follow the tested version** at the top of the dialog. The panel has no switch for automatic updates. Hermes WebUI, File share and Containers on Linux have no version choice, and their dialog shows one version you cannot select. Gitea, Ayakaleaf, Codeg and CloudCLI carry **Upgrade only** on their tab. In their dialog, the versions older than the installed one are grey and cannot be selected; see [App kinds](/en/deploy/app_kinds#upgrade-only).

## Uninstall

1. Select **Uninstall**.

   ![The Uninstall button boxed in red](/guide/en/deploy_on_a_machine_39_uninstall.webp)

1. The second sentence of the dialog says whether the app's data is kept or deleted; code-server's settings and extensions stay in the home folder. If the app deletes data, that sentence and the confirm button are red. Select **Uninstall** to confirm. To keep the app, select **Cancel** or select outside the dialog.

   ![The uninstall dialog with the Uninstall button boxed in red](/guide/en/deploy_on_a_machine_40_uninstall_dialog.webp)

1. The tab returns to **not installed**.

   ![The tab showing not installed, with the Install button available again](/guide/en/deploy_on_a_machine_42_uninstalled.webp)

Uninstalling ends every share of the app, and you must generate new links to use it again. The tab stays in the list; to hide it, deselect the app in **+ Add module**. When you install the same app again, the accounts selected last time stay selected, and the app runs after you select **Start**. While another app needs Containers, uninstall that app before you uninstall Containers.

## Apps that need containers

Hermes WebUI and Ayakaleaf run in containers, and their cards show **Needs: Containers**.

![The Hermes WebUI card showing that it needs Containers, boxed in red](/guide/en/deploy_on_a_machine_20_requires_card.webp)

If Containers is not installed yet, **Install** first opens a confirmation that shows **Installing this also installs:** and **Containers**. **Yes** installs both modules, and **No** installs neither.

![The confirmation listing Containers, with the No and Yes buttons](/guide/en/deploy_on_a_machine_21_requires_dialog.webp)

On Linux, this is the last step. On Windows and macOS, if you have not chosen an account before, **Choose the account that runs the containers** opens next. The containers run in a virtual machine that belongs to an account. Fill in the dialog:

1. Under **Account**, select an account.
1. On Windows, if this account has no saved password, enter its **Password**. The hub verifies the password on the spot, and with a wrong password nothing is installed.
1. Check the default values of **CPUs**, **Memory (GiB)** and **Disk limit (GiB)**. After the virtual machine's first start, a CPU or memory change needs a restart of the virtual machine, and the disk can only grow.
1. Select **Install**.

![The Choose the account that runs the containers dialog](/guide/en/windows_account_dialog.webp)

On Windows, installing Containers can need a restart of the computer. The Containers tab then shows **Windows needs a restart to finish turning on WSL; the install goes on after it.** with **Restart now** beside it. Save your work first, because every program open on this system closes; then select **Restart now**, and **Restart** in the dialog. The install continues automatically after the restart, and apps that wait for Containers show the same button on their tabs.

![The Containers tab showing that Windows needs a restart, with Restart now boxed in red](/guide/en/deploy_containers_18_reboot.webp)

## Errors and offline systems

When the tab shows **install failed** or **failed**, the reason appears under the failed step. Fix the problem, then select the same button again to retry. When the tab shows **install failed**, you can also select **Uninstall** to remove a half-finished install.

![The File share tab showing install failed, with the reason under the failed step](/guide/en/deploy_on_a_machine_23_failed.webp)

While this system is offline, every button is grey and the tab shows **The agent is offline**. The buttons become available again when the system reconnects to the hub. For the meaning of each error message and its fix, see [Troubleshooting](/en/reference/troubleshooting).
