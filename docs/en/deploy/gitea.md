# Gitea

Gitea is a self-hosted code hosting service similar to GitHub. Your code stays on your own computer, and you can manage repositories together with other people.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.2.0" />

Each system runs one instance. Gitea runs as an account of its own, so you skip choosing an account.

## Supported systems

| System  | Architecture         | First Neutrino Hub version | git                                                       |
| ------- | -------------------- | -------------------------- | --------------------------------------------------------- |
| Linux   | amd64, arm64         | 0.2.0                      | Installed together with Gitea                             |
| Windows | amd64                | 0.5.0                      | Included with Gitea                                       |
| macOS   | Apple silicon, Intel | 0.5.0                      | The install adds Apple's Command Line Tools automatically |

## Install

1. Open the panel in a browser, sign in, and select the system to install on in the lower half of the sidebar.
1. In the **Module configuration** area, select **+ Add module**. In the dialog, select the **Gitea** card, then select **Close** after the card is highlighted.

   ![The module list with the Add module button boxed in red](/guide/en/deploy_gitea_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the Gitea card boxed in red](/guide/en/deploy_gitea_02_catalog.webp "Select Gitea")
   ![The Gitea card highlighted, with the Close button boxed in red](/guide/en/deploy_gitea_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **Gitea** row in the list on the left, and its tab appears on the right. Select **Install**.

   ![The module list with the Gitea row boxed in red](/guide/en/deploy_gitea_04_tab.webp "Select Gitea")
   ![The Gitea tab showing not installed, with the Install button boxed in red](/guide/en/deploy_gitea_05_install.webp "Select Install")

1. The tab lists every step, and on Linux it also installs the git system package. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with every step listed](/guide/en/deploy_gitea_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button boxed in red](/guide/en/deploy_gitea_07_installed.webp "Select Start")

1. The tab shows **running**. Select **Configure**, and the settings open under it. In the **Administrator** area, fill in **username** and **password**, which you use later to sign in to Gitea. You can leave **email (optional)** empty.

   ![The tab showing running, with the Configure button boxed in red](/guide/en/deploy_gitea_17_started.webp "Select Configure")
   ![The Administrator area with the username field boxed in red](/guide/en/deploy_gitea_08_config.webp "Enter a username and password")

1. Select **Create administrator**. **Administrator** shows **exists** beside it, with this username listed under it. The install is complete.

   ![The username and password filled in, with the Create administrator button boxed in red](/guide/en/deploy_gitea_09_admin_create.webp "Select Create administrator")
   ![The Administrator area showing exists](/guide/en/deploy_gitea_10_admin_created.webp "Exists")

## Use

Before you start, add your phone or computer to the hub, as [Join the hub](/en/access/join) describes.

1. Open the client, go to the **Apps** page, and find the **Gitea** row. The row has two addresses under it: a web address, and an SSH address for git. Select **Use**, then **Open**.

   ![The client's Apps page with the Use button boxed in red](/guide/en/deploy_gitea_40_client_use.webp "Select Use")
   ![The Gitea row with the Open button boxed in red](/guide/en/deploy_gitea_41_client_open.webp "Select Open")

1. The browser opens Gitea's home page. Select **Sign In** in the top-right corner, enter the username and password you set, and select **Sign In**.

   ![Gitea's home page with the Sign In button boxed in red](/guide/en/deploy_gitea_42_home.webp "Select Sign In")
   ![The sign-in page with the Sign In button boxed in red](/guide/en/deploy_gitea_43_login.webp "Fill in, then select Sign In")

1. After you sign in, your dashboard opens. To create a repository, select **+** in the top-right corner. Enter a name in **Repository Name**, leave the other fields unchanged, then scroll down and select **Create Repository**.

   ![The dashboard after signing in](/guide/en/deploy_gitea_44_dashboard.webp "Select +")
   ![The new repository page with the Repository Name field boxed in red](/guide/en/deploy_gitea_45_new_repo.webp "Enter the repository name")

1. The repository is created, and its page shows the clone address and the commands to run.

   ![The new repository's page showing the clone address](/guide/en/deploy_gitea_46_repo.webp)

After you select **Use** in the client, git can use the clone address on the page. To clone with the SSH address, add your SSH key in Gitea's web page first.

![A repository home page with two files, and the README under them](/guide/en/deploy_gitea_47_repo_files.webp)

## Share

Gitea can generate a link with [App share](/en/share/web_share).

1. In the panel sidebar, select **Services**, find the **Gitea** row, and select **Share**.

   ![The Services page with the Share button of the Gitea row boxed in red](/guide/en/deploy_gitea_20_services_share.webp)

1. In the dialog, enter a **Name** that helps you identify the share; the other person does not see it. **Expires** defaults to 7 days, and you can choose another option before you select **Generate link**. Select **Copy** right away, send the link, then select **Done**. After the dialog closes, the panel no longer shows the link.

   ![The share dialog with the Name field boxed in red](/guide/en/deploy_gitea_21_share_dialog.webp "Enter a name")
   ![The completed share dialog with the Generate link button boxed in red](/guide/en/deploy_gitea_22_share_generate.webp "Select Generate link")
   ![The share dialog showing the link and a QR code, with the link row boxed in red](/guide/en/deploy_gitea_23_share_link.webp "Select Copy")

The link opens Gitea's own home page, where the other person signs in on their own. They can sign in after you create an account for them in Gitea.

![Gitea's home page open in a visitor's browser](/guide/en/deploy_gitea_24_visitor.webp)

## Risks and limits

With **Open registration** on, anyone who has the share link can create an account.

You manage accounts and repositories in Gitea's own web page, and the panel manages only the first administrator.

## Settings

Apart from the administrator, the following settings can stay at their defaults:

| Setting                                  | Where                 | Purpose                                                        |
| ---------------------------------------- | --------------------- | -------------------------------------------------------------- |
| **Open registration**                    | **Access**            | Whether visitors can create their own accounts; off by default |
| **Port**, **Root URL**                   | **Access**            | Usually left unchanged                                         |
| **Apply access**                         | **Access**            | Saves the settings in the previous rows, and Gitea restarts    |
| **Reset password**                       | **Administrator**     | Resets the administrator's password                            |
| **Update**, **Install another version…** | Under the tab's state | Change the version; the steps follow this table                |

To change the version, first read the version line on the tab, for example `Installed 28.3.0`. When the publisher has a newer version, the line also shows `· newest` and that version. Then follow these steps:

1. Select **Install another version…**. The dialog lists newer versions first, and **tested** marks the tested version. A new version migrates the data when it starts, so Gitea only upgrades: versions older than the installed one are grey and cannot be selected. Select the newer version you want.

   ![The version row with the Install another version button boxed in red](/guide/en/deploy_gitea_30_version_button.webp "Select Install another version")
   ![The version list, with the versions older than the installed one in grey](/guide/en/deploy_gitea_31_version_dialog.webp "Older versions cannot be selected")

1. When a newer version exists, the **Update** button beside it switches straight to the newest version. The tab lists the **Switch to version** steps and returns to **running** when they finish. On the newest version, **Update** is grey.

## Uninstall

On the **Gitea** tab, select **Uninstall**. The dialog states that the repositories, Gitea's accounts and the database stay in its data folder. Select **Uninstall** to confirm.

![The Gitea tab with the Uninstall button boxed in red](/guide/en/deploy_gitea_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with the Uninstall button boxed in red](/guide/en/deploy_gitea_51_uninstall_dialog.webp "Confirm")

After you install Gitea again, the original repositories and accounts work as before.

If the install fails, see [Troubleshooting](/en/reference/troubleshooting).
