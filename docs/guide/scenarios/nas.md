---
title: Make a machine a NAS
---

# Make a machine a NAS

At the end of this page, a managed Linux machine with a spare disk is the home's file server, open from your laptop and phone at home and away. On that machine, **ZFS storage** keeps the files on a pool of disks, and **File share** serves a folder of the pool over SMB. The hub lists each share on its **Services** page and relays every client's connection from its port 8443 to the machine's agent. The agent then connects to the share on its own machine.

## Before you start

- You have done the [Step zero](../quick-start.md), so the laptop and the phone are clients of the hub.
- A Linux machine runs the agent and is listed under **Managed devices**; [Install an agent](../install/agent.md) covers enrolling one. The hub box's own agent counts too.
- The machine has at least one spare disk. A disk that holds data is erased when it joins the pool.

## Install the modules

1. On the panel's **Modules** page, select the machine under **Which machine**.
1. If the **ZFS storage** or the **File share** tab is missing, select **+** at the end of the tabs and tick the missing one.
1. On the **ZFS storage** tab, select **Install**, and wait until the tab no longer reads **installing**.
1. Select **Configure**.
1. On the **File share** tab, select **Install**, and wait until the tab no longer reads **installing**.
1. Select **Configure**.

Outside Ubuntu, the ZFS install adds the package repository that holds ZFS, and builds the kernel module when the distribution provides none. The install also brings smartmontools for the disk health readings.

## Create the pool

1. On the **ZFS storage** tab, under **Pools**, select **Create pool**.
1. Fill **Pool name**, such as `tank`.
1. Under **First vdev disks**, tick the spare disks.
1. Under **Vdev layout**, pick **Single** for one disk or **Mirror** for two. More disks unlock **RAID-Z1** and **RAID-Z2**.
1. If a ticked disk holds data, type `wipe` in the field that appears.
1. Select **Create pool**.

The pool appears under **Pools**, and **Topology** draws it with its disks. [ZFS storage](../agent/modules/zfs.md) says how much each layout survives.

![The ZFS storage tab with a pool and its disks](/guide/en/zfs.webp)

## Create a dataset

A dataset is a folder of the pool with its own settings, and it is the folder you share.

1. Under **Datasets**, select **Add dataset**.
1. Pick the **Pool**, and fill **Name**, such as `media`.
1. Optional: fill **Mountpoint**. Left blank, the dataset is at `/tank/media`.
1. Pick the **Compression** and the **Record size**. For photos and videos, keep `lz4` and pick `1M`.
1. Select **Create dataset**.

The dataset's row shows its compression, record size and usage.

## Add a share user

A share user is the name and password a client signs in to the share with.

1. On the **File share** tab, under **Users**, type a new user name and a password, then select **Add user**.
1. Select **Apply users**. The user's row reads **ready**.

To change the password later, remove the user and add it again.

## Share the dataset

1. On the **ZFS storage** tab, on the dataset's row, select **Share**. A dialog titled **Share** and the dataset's name opens.
1. Tick the users who can open the share. With none ticked, every user under **Users** can, including users added later.
1. Select **Share**.

The machine serves the share at once, and the row gets the **smb · media** badge. The share takes the last part of the dataset's name and serves the dataset's mountpoint for reading and writing. It appears under **Shares** on the **File share** tab. **Unshare** on the row removes the share and keeps the files.

**Share** stays greyed with **Install and start Samba first** until the **File share** tab reads **running**. You can also add the share by hand on the **File share** tab, with the dataset's mountpoint as its **Path**, then select **Apply shares**. That form also has **Read only**.

![The File share tab with its shares and users](/guide/en/shares_windows.webp)

## What the Services page shows

The share is a row under **Files** on the hub's [Services](../hub/services.md) page, titled with the share's name and marked with the **module** chip. It reads **serving** while the **File share** module runs, and **not serving** while it is stopped.

Every client whose permission on the **Clients** page includes **Files** lists the share, and that kind is on by default. A client connects to the hub's port 8443 alone, and the hub passes the share's connection to the machine's agent.

## Mount it on the laptop

1. In the laptop's client window, open **Files**.
1. On the share's row, select **Configure**.
1. Type the share user's name in **Share username** and its password in **Share password**.
1. On Linux, keep the **Mount path** or type another folder under your home. On Windows, pick a **Drive**.
1. Select **Save**.
1. Select **Mount**. The button reads **Mounting…**, then **Unmount**.

The share is a folder under your home on Linux, a volume in the Finder on macOS, and a drive in File Explorer on Windows. [Share and mount files](../quick-start/files.md) shows the same steps with the prompts each system adds.

![The Files page with a share mounted](/guide/en/client_files_mounted.webp)

![The share as a drive in File Explorer](/guide/os/win_explorer_mapped.webp)

## Open it on the phone

1. In the app, open **Files**.
1. On the share's row, select **Open in Files**.
1. Type the share user's name in **Share username** and its password in **Share password**.
1. Select **Connect**.

Android's Files app opens the share under its name. Away from home, the laptop and the phone open the share with the same buttons. The hub's row in the client only has to read **Connected**, through any of the hub's ways in.

![The share in Android's Files app](/guide/en/app_files_provider.webp)

## Keep the pool healthy

- **Scrub** on the pool's card reads every block of the pool and checks it against its checksum. The card shows the progress and the time left, and **Stop scrub** ends it early.
- Each disk in **Topology** reads **SMART ok** or **SMART FAILING**. Select a disk to see its details, and **Replace** it with a spare disk.

When a mount fails, [Troubleshooting](../reference/troubleshooting.md#a-share-does-not-mount-on-a-computer) lists each code with its fix.
