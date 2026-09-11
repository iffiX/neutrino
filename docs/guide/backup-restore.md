---
title: Backup and restore
---

# Backup and restore

The backup is the whole of `config/`, as one plain `.tar.gz`. Restoring it on a
fresh machine and running the installer reproduces the appliance.

Five things to settle first:

- The backup holds `config/` and nothing else. No share, no repository, no
  container volume, no dataset. If your data is what you want kept, this page
  is not the one.
- The archive is not encrypted. The credentials inside are sealed under the
  vault passphrase; the rest of `config/` is readable by whoever holds the
  file.
- A restore overwrites every file under `config/` and restarts the panel.
- A rekey does not reach an archive already taken. Old archives keep the
  passphrase they were taken under.
- There are no migrations. An archive from a different version may not apply.

## What the backup holds

- Every file under `config/`, in one `.tar.gz`.
- A first member, `neutrino_backup.json`, naming what the archive is, and a
  second, `SHA256SUMS`, carrying a digest for every member after it.
- The vault, at `credentials/vault.json`, whose data key rides wrapped under
  the master passphrase.

The archive travels plainly because `config/` holds no unsealed secret.

| Not in the backup     | Where it lives                            |
| --------------------- | ----------------------------------------- |
| Samba share contents  | the disk on the machine serving them      |
| Gitea repositories    | Gitea's own data directory on its machine |
| Container volumes     | the machine running podman                |
| ZFS datasets          | the pool                                  |
| `/etc/neutrino/agent` | the agent package on each machine         |

## Download

Open **Settings** and find "Configuration archive".

Expect: the hint "Holds all of config/. The credentials inside travel sealed
under the vault master password, which restoring asks for."

Press "Download backup".

Expect: a `.tar.gz` lands in the browser's downloads, and the page reads
"Backup downloaded."

![The Settings page's configuration archive section with the Download backup button](/guide/en/settings_backup.webp)

::: tip
The archive is plain, so its contents can be listed with `tar tzf` like any
other. Whoever holds the archive and the passphrase holds the credentials.
:::

## Keep the passphrase

The vault's data key is wrapped under the master passphrase. A rekey changes
what opens the vault, and nothing sealed is re-encrypted.

```bash
sudo nhub vault rekey
```

Expect: a prompt for the new passphrase, then "rekeyed: the vault now opens
with the new passphrase".

Without a terminal to type into, feed it instead:

```bash
printf '%s' "$NEW_PASSPHRASE" | sudo nhub vault rekey --stdin
```

::: danger Old archives keep the old passphrase
An archive taken **before** a rekey still opens only with the **old**
passphrase. Keep both until the old archives are gone.
:::

## Restore

Open **Settings**, press "Restore from file", and pick the archive.

Expect: the dialog "Restore {name}", reading "Every file under config/ is
overwritten by the archive's, the configuration is applied, and the panel
restarts on its own.", with a "Vault master password" field below it.

![The restore dialog with the archive named and the vault master password field](/guide/en/settings_restore.webp)

Type the passphrase of the box the archive came from, then press "Restore".

Expect: "Applying the restored configuration; this can take minutes when heavy
services re-render.", then "The panel is restarting; this page reloads by
itself. Sign in with the restored password."

::: warning
The files are restored before the apply runs, so an apply that fails leaves the
box holding the restored `config/` and serving the old configuration.

The panel says which line failed and names the way out: fix the cause, then run
`sudo nhub apply` from a terminal. Where the panel never comes back, the same
command from a terminal finishes the job.
:::

| Refusal                                             | What it means                                         |
| --------------------------------------------------- | ----------------------------------------------------- |
| "Backups are .tar.gz files; that file is not one."  | the wrong extension                                   |
| "This is not a Neutrino backup."                    | no manifest member in the archive                     |
| `backup_corrupt`                                    | a digest in `SHA256SUMS` does not match               |
| `vault_passphrase_needed`, `vault_passphrase_wrong` | the archive's vault will not open with what was typed |
| `backup_too_large`                                  | over 32 MiB                                           |

## After a restore

```bash
# 1. Did every module render? Expect no error and no diff.
sudo nhub apply --dry-run

# 2. Is the panel up? Expect neutrino_hub_web active.
systemctl status neutrino_hub_web
```

- The panel password is the restored one, not the one this box had before.
- The vault passphrase is the one the archive was taken under, until a rekey.
- Agents reconnect by themselves. A device whose hub identity changed is asked
  to rejoin, reading "the hub's identity changed (it was reset or
  reinstalled)".

Changing the panel password is a different job, on the Settings page under
"Change password", and "Other sessions stay signed in."

That is the whole path: an archive on your own disk, and a box that comes back
from it.
