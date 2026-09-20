---
title: Settings
---

# Settings

The **Settings** page holds the password, the language, the theme, backup and restore, the versions, updating the hub itself, the upgrade order and the reset commands. This page takes them in that order.

## Password, language and theme

Under **Panel password**, fill **Current password**, **New password** and **Confirm new password**, and select **Change password**; other sessions stay signed in. Under **Language**, pick the language and select **Apply language**, and every page is drawn in it. Under **Appearance**, pick **System**, **Dark** or **Light** and select **Apply theme**; **System** takes the colour scheme from the browser. The client window has a language and a theme of its own.

## Configuration archive

The archive is the whole of `config/` as one `.tar.gz`, with a manifest and a checksum list in front. The credentials inside are sealed under the vault master passphrase, and everything else in it is readable by whoever holds the file.

1. Under **Configuration archive**, select **Download backup**.

![The configuration archive section](/guide/en/settings_backup.webp)

| In the archive                                   | Elsewhere                                             |
| ------------------------------------------------ | ----------------------------------------------------- |
| every file under `config/`, the vault included   | the contents of Samba shares, on the machine's disk   |
| the network, proxy, overlay and AI configuration | Gitea's repositories, in Gitea's data directory       |
| declared services, devices and clients           | container volumes and ZFS datasets, on their machines |

## Restore

1. Under **Configuration archive**, select **Restore from file** and pick the archive.
1. In the **Restore** dialog, type the **Vault master password** of the vault the archive was taken from.
1. Select **Restore**.

![The restore dialog](/guide/en/settings_restore.webp)

The archive's files overwrite every file under `config/`, the configuration is applied, and the panel restarts and reloads the page. Sign in with the restored password. A damaged archive is rejected with `backup_corrupt`, and a wrong passphrase with `vault_passphrase_wrong`. When the apply stops short, the files stay restored and the page names the command that finishes it: `sudo nhub apply` in a terminal.

After a restore, each AI subscription account signs in again, and the agents reconnect on their own; an agent enrolled against another hub identity is rejected with `hub_untrusted` and joins with a fresh link.

## About

**About** shows the **Panel** version, **This machine** with its **Kernel** and **Uptime**, and the **Geodata** version. **Carried software** lists the open-source components the hub includes and installs on machines, each with a **source** link.

![The About section](/guide/en/settings_about.webp)

## Update

**Update** installs a newer release of the hub on the box it runs on. Press **Check for updates**; the panel reads the newest release from GitHub and shows its version, date, size, notes, and how much disk room the install needs. When the release is newer, **Install** opens a confirmation. The package is downloaded and checked against the release's checksums, then systemd installs it outside the panel. The panel restarts, the page returns to the sign-in, and after you sign in the **Update** section says which version is running.

For three minutes after the install, a health gate watches the panel and the router services. When they do not come up, the previous version's package is installed again and the section says so, with the reason and the install log. That package is fetched from the previous version's release the first time; a box installed from a build that has no release has none to fall back on, and the confirmation says so before you install.

A new major version is not installed from here, because a major can change the shape of `config/`; the section says the upgrade guide applies. `sudo nhub update` does the same from a terminal and asks before it installs; `--yes` skips the question, and `--package` installs a package file you brought yourself.

## Upgrade

The three packages share one version number. Install the new packages in this order:

1. On the hub box, press **Install** in the **Update** section, or install the new hub package with the same command as the first install.
1. For each managed machine, select **Reinstall agent** in its drawer, or send it a fresh link.
1. On each computer, install the new client package.

A hub rejects an agent or a client whose protocol number is outside what it accepts, with `protocol_too_old` or `protocol_too_new`. The machine keeps its binding and connects again once both ends are on versions that speak the same number.

## Reset

| Command                    | What it does                                                                                                                                                     |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sudo nhub reset password` | sets a new panel password and signs every session out                                                                                                            |
| `sudo nhub unlock`         | removes the login lockout after repeated failures, and every fail2ban SSH ban with it                                                                            |
| `sudo nhub reset all`      | hands the network back, replaces `config/` with the examples, removes every key and token the box collected, stops the services, and keeps `/etc/neutrino/agent` |

Removing the hub package after `nhub reset all` stops its units and takes its files. On a client, `apt remove` or `dnf remove` stops the program and keeps the person's configuration; `purge` removes the configuration too. The Windows installer offers the same choice as the **Keep my configuration** checkbox.
