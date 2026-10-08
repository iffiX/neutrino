---
title: Share and mount files
---

# Share and mount files

A folder on the computer becomes a file share. The laptop mounts it as a folder or a drive letter, and the phone opens it in Android's Files app.

Before you start, finish the [first step](../quick-start.md), and pick a folder on the computer to share.

## Share a folder

1. On the panel's **Modules** page, select your computer under **Which machine**.
1. Select the **File share** tab. If the tab is missing, select **+** at the end of the tabs and tick **File share**.
1. Select **Install**, and wait until the tab no longer reads **installing**.
1. Select **Configure**.
1. Under **Users**, type a new user name and a password for the share, then select **Add user**.
1. Select **Apply users**. The user's row reads **ready**.
1. Under **Shares**, select **Add share**, type a **Name**, and type the folder's full path in **Path**, such as `/home/lin/Documents` or `C:\Users\Public\Documents`.
1. Select **Apply shares**.

On Linux the install fetches Samba, and on macOS and Windows the module uses the SMB server that comes with the system.

![The File share tab with a user and a share](/guide/en/shares_windows.webp)

## Mount it on the laptop

1. In the laptop's client window, open **Files**.
1. On the share's row, select **Configure**.
1. Type the user name in **Share username** and its password in **Share password**.
1. On Linux, keep the **Mount path** or type another folder under your home. On Windows, pick a **Drive**.
1. Select **Save**.
1. Select **Mount**.

The button reads **Mounting…**, then **Unmount**. On Linux the share is a folder under your home, and polkit shows a password prompt the first time. On macOS it is a volume in the Finder, and on Windows a drive letter in File Explorer.

![The Files page with a share mounted](/guide/en/client_files_mounted.webp)

![The share as a drive in File Explorer](/guide/os/win_explorer_mapped.webp)

When the row shows a code, [Troubleshooting](../reference/troubleshooting.md#a-share-does-not-mount-on-a-computer) lists its cause and fix.

## Open it on the phone

1. In the app, open **Files**.
1. On the share's row, select **Open in Files**.
1. Type the user name in **Share username** and its password in **Share password**.
1. Select **Connect**.

Android's Files app opens the share, under the share's name, and its files open from there. Away from home, the share opens the same way over NetBird. When **Connect** fails, [Troubleshooting](../reference/troubleshooting.md#a-share-is-unreachable-on-a-phone) has the fix.

![The share in Android's Files app](/guide/en/app_files_provider.webp)
