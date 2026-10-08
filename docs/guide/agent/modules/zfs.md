---
title: ZFS storage
---

# ZFS storage

On a managed Linux machine, the **ZFS storage** tab builds ZFS pools and datasets and shows the health of every disk. The tab shows what the machine reports about its own disks, and each button acts on the machine at the press. The hub keeps no list of wanted pools.

To prepare the tab, select **Install** and then **Configure** on the **ZFS storage** tab of the [Modules](../modules.md) page. The install also brings smartmontools for the disk health readings. The **Topology**, **Pools** and **Datasets** sections open under the tab.

![The ZFS storage tab with a pool and its disks](/guide/en/zfs.webp)

## Create a pool

1. Under **Pools**, select **Create pool**.
1. Fill **Pool name**.
1. Under **First vdev disks**, pick the disks.
1. Under **Vdev layout**, pick a layout. A layout unlocks when enough disks are picked.
1. If the picked disks hold data, type `wipe` to erase them.
1. Select **Create pool**.

A vdev is a group of disks inside the pool, and its layout sets how much of the group can fail:

| Layout      | What it gives           |
| ----------- | ----------------------- |
| **Single**  | no redundancy           |
| **Mirror**  | full copies             |
| **RAID-Z1** | survives 1 failed disk  |
| **RAID-Z2** | survives 2 failed disks |

**Expand** on a pool adds another vdev to it. The new vdev joins the pool permanently and cannot be removed later.

::: warning
A new vdev whose layout differs from the pool's other vdevs leaves the pool only as safe as its weakest vdev. Adding one takes a second press, on **Add anyway**.
:::

When attached disks hold a pool this machine has not imported, the tab shows the pool's name and an **Import** button. **Destroy pool** erases every dataset on the pool after you type the pool's name.

## Disk health

**Topology** draws each pool's vdevs and disks, and lists unused disks as **UNASSIGNED**. Each disk reads **SMART ok** or **SMART FAILING**, with its temperature when the drive reports one. Select a disk to see its model, serial number, size, SMART result and read, write and checksum error counts.

- **Scrub** on a pool checks every block of the pool against its checksums.
- **Offline** takes a selected disk out of its pool for the time being, and **Online** puts it back.
- **Replace** on a selected disk opens a list of spare disks. Pick one and select **Start resilver** to rebuild onto it.

With no spare disk attached, **Replace** is greyed and its tooltip reads **No spare disk to replace with**.

## Datasets

1. Under **Datasets**, select **Add dataset**.
1. Pick the **Pool** and fill the **Name**.
1. Optional: set a **Mountpoint**. Left blank, it is `/pool/name`.
1. Pick the **Compression** and the **Record size**. Small records suit databases and VM images; large ones suit media and archives.
1. Select **Create dataset**.

Each dataset row shows its compression, record size and usage. **Destroy** removes the dataset and every file on it, and only a snapshot taken earlier brings them back.

## Share a dataset

The [File share](shares.md) module must be running on the same machine. While it is missing or stopped, the button reads **Install and start Samba first**.

1. On a mounted dataset's row, select **Share**.
1. Pick the users the share accepts, or pick none to accept every user, future ones included.
1. Select **Share**.

The File share module exports the dataset's mountpoint over SMB, read and write for the chosen users. A shared row has an `smb` badge with the share's name, and **Unshare** withdraws it.
