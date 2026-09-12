---
title: Files
---

# Files

The client's **Files** panel mounts a share the hub publishes under your home directory, or on a drive letter on Windows. The same panel unmounts it.

## Where the entries come from

An entry in the **Files** panel is an SMB share the hub published, from one of these sources:

- the Samba module on a managed machine
- a dataset shared from the ZFS page
- a share on another server, declared by hand on the hub's **Services** page

The line under the entry says which.

## Config

1. In the **Files** panel, select **Config** on the entry.
1. Type the **Share username** and **Share password**: the account that the Samba module, or the other server, accepts.
1. On Linux and macOS, keep or change the **Mount path**, a folder under your home such as `~/nas/media`; on Windows, pick a **Drive** letter, `N:` by default.

![The Files panel's config form on Linux](/guide/en/client_files_config.webp)

![The drive letter picker on Windows](/guide/en/win_files_drive_letter.webp)

The client rejects a path outside your home with `mountpoint_invalid`, and a folder that is not empty with `mountpoint_not_empty`. On Windows, only an unused drive letter is accepted; anything else is `mountpoint_not_drive_letter`.

## Mount and unmount

1. Select **Mount**. The button reads **waiting to mount…**, then **mounting…**, then **Unmount**.

![The Files panel with the share mounted](/guide/en/client_files_mounted.webp)

![The mapped drive in File Explorer](/guide/os/win_explorer_mapped.webp)

The share is at the path or the drive letter until **Unmount**, and the login stays saved for the next **Mount**. The password is kept in a credentials file on your computer that only your account can read. When that file is gone, a mount is rejected with `credentials_missing`, and **Config** takes the password again. From a terminal, `nclient service file config <ref> --path <path> --username <name>` saves the login and mounts, and `mount` and `unmount` with the same `<ref>` attach and detach it.

## The polkit helper on Linux

On Linux a CIFS mount is the client's one privileged step. A root helper runs it under `pkexec`, polkit grants that only to a session at the console, and the helper mounts under your home only. Dismissing the polkit prompt gives `mount_not_authorized`. A machine without the helper or without `mount.cifs` gives `mount_tooling_missing`. On macOS the share is mounted with `mount_smbfs` as yourself, and on Windows as a mapped drive.
