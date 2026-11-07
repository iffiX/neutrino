# Settings: backup, updates and password

The **Settings** page is where you back up the configuration, update the hub and change the panel password.

To open it, select **Settings** in the panel's sidebar.

![The Settings page with Settings marked in the sidebar](/guide/en/hub_settings_01_page.webp)

## Download a backup

A backup is a `.tar.gz` file that holds the whole configuration. The keys in it are encrypted, and only the vault passphrase decrypts them. Everything else is plain text, so keep the file safe.

A backup leaves out your files, Gitea repositories, container volumes and AI subscription sign-ins.

1. In the **Configuration archive** section, select **Download backup**. The browser saves the file to its download folder.

   ![The Configuration archive section with Download backup marked](/guide/en/hub_settings_02_backup.webp)

1. Record the vault passphrase, because a restore requires the passphrase that this backup was encrypted with.

## Restore a backup

A restore replaces the whole configuration and ends every app share, and then the panel restarts.

1. In the **Configuration archive** section, select **Restore from file** and choose the backup file. Nothing is restored yet. In the dialog that opens, enter the **Vault passphrase** this backup was encrypted with, then select **Restore**. To back out, select **Cancel**.

   ![The Configuration archive section with Restore from file marked](/guide/en/hub_settings_03_restore_button.webp "Select Restore from file")
   ![The restore confirmation dialog](/guide/en/hub_settings_04_restore_dialog.webp "Enter the passphrase, then select Restore")

1. After the panel restarts, sign in with the password of the restored configuration.

Agents and clients reconnect automatically, even after a restore onto a different computer. On a different computer, sign in to your AI subscription accounts again.

If the configuration fails to apply, the dialog shows the reason. Fix the cause, then run `sudo nhub apply` on this computer.

## Update the hub

1. In the **Update** section, select **Check for updates**. The section lists the new version's notes and the disk space it uses.

   ![The Update section with Check for updates marked](/guide/en/hub_settings_05_update.webp)

1. Select **Install** followed by the version number, read the confirmation dialog, then confirm.

   ![The Update section listing version 0.6.1, with Install 0.6.1 marked](/guide/en/hub_settings_16_update_found.webp)

1. The panel restarts. Sign in again on the sign-in page, and the section then shows which version the hub updated from and to.

   ![The Update section showing the update from 0.6.0 to 0.6.1](/guide/en/hub_settings_17_updated.webp)

If the new version does not respond within three minutes, the hub restores the old version automatically.

The agent on this computer updates with the hub, and agents on other systems update automatically. If a system did not update, select **Update agent** on its page. If the confirmation dialog mentions agents on an older protocol, select **Reinstall** on that system's page. You install new client versions yourself.

A new major version cannot be installed from this section. Upgrade to it by hand with [Upgrade from 0.5](/en/hub/upgrade).

You can also update from the command line with `sudo nhub update`. The command shows a `[y/N]` prompt first, and `--yes` skips it. To install a package you downloaded yourself, run `sudo nhub update --package <file>`, with the package's path as `<file>`.

## Change the panel password

In the **Panel password** section, fill in **Current password**, **New password** and **Confirm new password**, then select **Change password**.

![The Panel password section with Change password marked](/guide/en/hub_settings_12_password.webp)

If you forget the password, run `sudo nhub reset password` on this computer, which sets a new password and signs out every session. If the sign-in page shows **Locked after repeated failures.**, run `sudo nhub unlock`. On Windows, run both commands in an administrator PowerShell, without `sudo`.

## Enable HTTPS

The panel uses HTTP by default. With HTTPS enabled, every HTTP address redirects to HTTPS. Install the certificate first on every device that opens the panel, or the browser shows a warning.

1. Open the panel at its http address and find the **HTTPS** section. Select **Install certificate**, which downloads the certificate. Select the tab for your system, for example **Windows**, then follow the steps it lists to install the certificate. Restart the browser.

   ![The HTTPS section with Install certificate marked](/guide/en/hub_settings_08_https.webp "Select Install certificate")
   ![The steps on the Windows tab](/guide/en/hub_settings_09_https_windows.webp "Follow the steps")

1. Return to the section. **Enable HTTPS** becomes available after **This browser trusts the certificate.** appears. The button has no confirmation dialog and takes effect immediately.

   ![Enable HTTPS marked; the button stays grey until the certificate is installed](/guide/en/hub_settings_10_https_enable.webp)

The certificate is valid only for private addresses, virtual network addresses and local names. A browser that opens the panel at a public address still shows a warning. Opening the panel with the client's **Panel** button is unaffected.

To **Regenerate certificate**, first select **Disable HTTPS**. After you confirm in the dialog, every browser that installed the old certificate must install the new one.

![The confirmation dialog for regenerating the certificate](/guide/en/hub_settings_11_regen_dialog.webp)

## Other settings

**Hub name** is the name that joined clients show. A change to it takes effect after you select **Apply name**.

![The Hub name section with Apply name marked](/guide/en/hub_settings_07_name.webp)

After you change **Language** or **Appearance**, select the apply button of that section, and every page updates.

![The Language section](/guide/en/hub_settings_14_language.webp "Language")
![The Appearance section](/guide/en/hub_settings_15_theme.webp "Appearance")

**About** shows the version and the open source software in the package.

![The About section](/guide/en/hub_settings_13_about.webp)
