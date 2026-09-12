---
title: Settings
---

# Settings

The **Settings** page holds the password, the language, backup and restore, the versions, the upgrade order and the reset commands. This page takes them in that order.

## Password and language

Under **Panel password**, fill **Current password**, **New password** and **Confirm new password**, and select **Change password**; other sessions stay signed in. Under **Language**, pick the language and select **Apply language**, and every page is drawn in it. The client window has a language of its own.

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

## Upgrade

The three packages share one version number. Install the new packages in this order:

1. On the hub box, install the new hub package with the same command as the first install.
1. For each managed machine, select **Reinstall agent** in its drawer, or send it a fresh link.
1. On each computer, install the new client package.

A client newer than the hub is rejected with `client_newer_than_hub` until the hub is upgraded; an agent newer than the hub with `agent_newer_than_hub`.

## Reset

| Command                    | What it does                                                                                                                                                     |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sudo nhub reset password` | sets a new panel password and signs every session out                                                                                                            |
| `sudo nhub unlock`         | removes the login lockout after repeated failures, and every fail2ban SSH ban with it                                                                            |
| `sudo nhub reset all`      | hands the network back, replaces `config/` with the examples, removes every key and token the box collected, stops the services, and keeps `/etc/neutrino/agent` |

Removing the hub package after `nhub reset all` stops its units and takes its files. On a client, `apt remove` or `dnf remove` stops the program and keeps the person's configuration; `purge` removes the configuration too. The Windows installer offers the same choice as the **Keep my configuration** checkbox.
