# File share

File share is the feature that mounts a folder on your system at a path or drive letter on the client, where you read and write its files directly.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.2.0" />

The client gets the share's password from the hub and fills it in automatically, so you create no SMB user and remember no password.

The kinds of share are:

- **Home shares:** a home folder is the account's own folder, such as `/home/lab` on Linux. A home share shares the whole home folder.
- **Folder shares:** a folder share shares only the one folder you choose.

## Supported systems

| System                           | Architecture         | First Neutrino Hub version | Service used                                                          |
| -------------------------------- | -------------------- | -------------------------- | --------------------------------------------------------------------- |
| Linux (Debian and RHEL families) | amd64, arm64         | 0.2.0                      | Samba, installed with the system's package manager during the install |
| Linux (Arch family)              | amd64                | 0.2.0                      | Samba, installed with the system's package manager during the install |
| Windows                          | amd64                | 0.5.0                      | The system's built-in sharing service, with nothing to download       |
| macOS                            | Apple silicon, Intel | 0.5.0                      | The system's built-in sharing service, with nothing to download       |

## Install

1. Open the panel in a browser, sign in, and select the system to share files from in the lower half of the sidebar. Check that **Available accounts** lists your account. If it does not, add it first with the steps in [Add an account](/en/deploy/on_a_machine#add-an-account).
1. In the **Module configuration** area, select **+ Add module**. In the dialog, scroll down and select the **File share** card, then select **Close** after the card is highlighted.

   ![The module list with the Add module button boxed in red](/guide/en/deploy_file_share_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the File share card boxed in red](/guide/en/deploy_file_share_02_catalog.webp "Select File share")
   ![The File share card highlighted, with the Close button boxed in red](/guide/en/deploy_file_share_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **File share** row in the list on the left, and its tab appears on the right. Select **Install**.

   ![The module list with the File share row boxed in red](/guide/en/deploy_file_share_04_tab.webp "Select File share")
   ![The File share tab showing not installed, with the Install button boxed in red](/guide/en/deploy_file_share_05_install.webp "Select Install")

1. The tab lists every step, and on Linux the first step installs the system package. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with every step listed](/guide/en/deploy_file_share_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button boxed in red](/guide/en/deploy_file_share_07_installed.webp "Select Start")

1. The tab shows **running, no accounts**. Select **Configure**, and the settings open under it. Under **Home shares**, select your account. The log box can show a few `No such file or directory` lines; if the tab then shows **running**, ignore them.

   ![The tab showing running, no accounts, with the Configure button boxed in red](/guide/en/deploy_file_share_17_started.webp "Select Configure")
   ![The Home shares field with the lab row boxed in red](/guide/en/deploy_file_share_08_tick_account.webp "Select lab")

1. Select **Apply file share**. The account shows **running**, and **Applied.** appears under it. The home share is now on.

   ![lab selected, with the Apply file share button boxed in red](/guide/en/deploy_file_share_09_apply.webp "Select Apply file share")
   ![lab showing running, with Applied. under it](/guide/en/deploy_file_share_10_applying.webp "Applied")

You can also share one more folder. A folder share's accounts must first be selected under **Home shares**, so do not skip the previous steps. To add a folder share:

1. Scroll down to **Folder shares**, and select **Add** on the right.

   ![The Folder shares field with the Add button boxed in red](/guide/en/deploy_file_share_11_folder_add.webp)

1. In **Name**, enter a name for the share, such as demo, and the client shows this name. Select **Browse…**, then open the folders level by level in the dialog.

   ![The form with a name entered, and the Browse button boxed in red](/guide/en/deploy_file_share_12_folder_form.webp "Enter a name, select Browse")
   ![The folder dialog with the lab row boxed in red](/guide/en/deploy_file_share_13_folder_browse.webp "Open a folder")

1. Inside the folder you want, select **Choose this folder**. Under **Accounts**, select the accounts that can use this share, then select **Save**. The share takes effect on save, with no apply button to select.

   ![Inside the demo folder, with the Choose this folder button boxed in red](/guide/en/deploy_file_share_14_folder_choose.webp "Select Choose this folder")
   ![The completed form with the Save button boxed in red](/guide/en/deploy_file_share_15_folder_save.webp "Select Save")

1. After you save, a new row in the list shows the name, the folder and the accounts.

   ![The Folder shares list with the new demo row](/guide/en/deploy_file_share_16_folder_saved.webp)

When you save, the agent checks the folder first. If the folder does not exist, is a link, or is reached through a link, the form shows an error and saves nothing; choose the folder itself instead. While this system is offline, you cannot add or change shares, and the same holds for changing an account's **Share path** and selecting accounts.

![A link entered in the folder field, with red text under the form](/guide/en/deploy_file_share_21_folder_link_error.webp)

Files written through a folder share belong to the account used to connect.

## Use

Before you start, add your phone or computer to the hub, as [Join the hub](/en/access/join) describes. The **Files** permission is on by default. Shared files appear on the client's **Files** page, separate from the **Apps** page.

Mounting connects a share to your computer, where you use it like a local drive or folder. On a computer, mount a share:

1. Open the client and go to the **Files** page. A home share is named after its account, and a folder share shows as `demo (lab)`, with one row for each of its accounts. Select **Mount** on the row you want, with no password to enter. When the mount finishes, the location of the files appears under the row, and the button becomes **Unmount**.

   ![The client's Files page with the Mount button boxed in red](/guide/en/deploy_file_share_40_client_mount.webp "Select Mount")
   ![A local path under the row, with the Unmount button boxed in red](/guide/en/deploy_file_share_42_client_mounted.webp "Mounted")

1. To use another location, select **Configure** on the row before you mount, fill in the form, then select **Mount**.

   ![The configure form open, with a mount path field](/guide/en/deploy_file_share_41_client_form.webp)

After mounting, the location of the files depends on the computer's system. In the table, `<system-name>` is the system's name and `<share-name>` is the share's name:

| System  | Location of the files                                                                              |
| ------- | -------------------------------------------------------------------------------------------------- |
| Windows | A new drive in File Explorer, such as `Z:`                                                         |
| Linux   | `remote/<system-name>-<share-name>` in your home folder                                            |
| macOS   | `remote/<system-name>-<share-name>` in your home folder, also listed under **Locations** in Finder |

On a phone, skip mounting and open the **Files** page of the app:

- **Android:** select **Open in Files**, and a new location appears in the system's Files app.
- **iPhone:** select the open button on the row to go to the files page in the app, where you can upload, rename and delete files.

![The Files page on a phone](/guide/en/access_android_20_files.webp)

If mounting fails, see [Troubleshooting](/en/reference/troubleshooting).

## Share

File share cannot generate a link with [App share](/en/share/web_share), because App share works only for apps with a web page.

To let someone else use a share, have them install the client and join the hub. Then turn on the **Files** permission for their device on the **Clients** page, as [Clients](/en/hub/clients) describes. To open only one share, turn on **Choose per app** in the permissions and turn on only that row.

If the other person has no client, you can run a file app with a web page in [Containers](/en/deploy/containers) and share it.

## Risks and limits

By default a home share shares the account's whole home folder. Any client with the permission for this share can read and write every file in it. To narrow the scope, change the account's **Share path**, or turn on only the shares a client needs in its permissions on [Clients](/en/hub/clients).

On Linux, a share accepts only connections from the system itself, and other computers access it through the client. On Windows and macOS, File share uses the system's own service, and the system firewall decides whether LAN devices can connect directly.

On Windows and macOS, the agent leaves the system's SMB service unchanged when the system joins the hub. If the SMB service is already running, the **File share** row shows **running, no accounts**; if it is stopped, the row shows **stopped**.

The panel does not manage or change shares and users you created yourself. If one of your own shares has the same name as a Neutrino Hub share, only that Neutrino Hub share stays offline; the other shares work as usual. In that case, give the Neutrino Hub share another name.

If a shared folder later disappears, for example because it moved or its disk is not mounted, the share stays, temporarily offline. A yellow notice at the top of the **File share** tab names the share whose folder is missing. When the folder returns, the share goes online again automatically. If you no longer need the share, select **Remove**, or deselect the account.

![The yellow notice at the top of the File share tab, saying the folder of photos is missing](/guide/en/deploy_file_share_22_folder_missing.webp)

When you select **Stop**, the panel opens a confirmation dialog first, because every share on this system stops.

On Windows, after **Stop** this computer no longer serves shares, but port 445 stays open until the next restart; Windows itself behaves this way. If stopping fails, the row shows the failure; select **Stop** again.

![The Stop File share dialog with the Stop button boxed in red](/guide/en/deploy_file_share_19_stop_dialog.webp)

On systems such as Rocky and RHEL, when SELinux is in enforcing mode, File share turns on the system switch `samba_export_all_rw`. On uninstall, File share turns this switch off only if File share turned it on. This does not apply to Ubuntu and Debian.

## Settings

Apart from selecting accounts, the following settings can stay at their defaults:

| Setting                    | Where                                                        | Purpose                                                                          |
| -------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| **Home shares**            | **Configure** on the tab                                     | Select accounts; takes effect after **Apply file share**                         |
| **Folder shares**          | **Configure** on the tab                                     | **Add**, **Edit**, **Remove**; takes effect on save, and the name cannot change  |
| **Share path**             | Account form in **Available accounts**                       | Location of the home share; when empty, the home folder                          |
| **Now serving**            | **Configure** on the tab                                     | Shows who is connected to which share, and the disk usage                        |
| **SMB password · account** | **Generated by the hub** section of the **Credentials** page | The client gets it automatically; you need it only to sign in to a share by hand |

**Now serving** is at the bottom of the settings, with a disk usage line under each share.

![The Now serving area, with the disk usage of two shares under it](/guide/en/deploy_file_share_17_status.webp)

To sign in by hand, find this account's **SMB password** on the **Credentials** page. The username is `neutrino_` followed by the account name.

![The Credentials page with the SMB password · lab row boxed in red](/guide/en/deploy_file_share_18_credentials.webp)

## Uninstall

On the **File share** tab, select **Uninstall**. The dialog states that the shared folders and their files stay as they are. Select **Uninstall** to confirm.

![The File share tab with the Uninstall button boxed in red](/guide/en/deploy_file_share_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with the Uninstall button boxed in red](/guide/en/deploy_file_share_51_uninstall_dialog.webp "Confirm")

Removing a folder share works the same way: the folder and its files stay.
