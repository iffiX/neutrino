---
title: ZFS storage
---

# ZFS storage

ZFS pools and datasets on a managed Linux machine are built on the **ZFS storage** tab, which also shows the health of every disk. It shows what the machine reports, and each button acts at the press; the hub keeps no list of wanted pools.

To prepare the tab, select **Install** and then **Configure** on the **ZFS storage** tab of the [Modules](../modules.md) page. The install also brings smartmontools.

![The ZFS storage tab with a pool and its disks](/guide/en/zfs.webp)

## Create a pool

1. Under **Pools**, select **Create pool**.
1. Fill **Pool name**.
1. Under **First vdev disks**, pick the disks.
1. Under **Vdev layout**, pick **Single**, **Mirror**, **RAID-Z1** or **RAID-Z2**. A layout unlocks when enough disks are picked.
1. If the picked disks hold data, type `wipe` to erase them.
1. Select **Create pool**.

A vdev is a group of disks in the pool. **Single** has no redundancy, **Mirror** keeps full copies, and **RAID-Z1** and **RAID-Z2** survive one and two failed disks. **Expand** adds another vdev to a pool for good.

::: warning
A new vdev whose layout differs from the pool's other vdevs leaves the pool only as safe as its weakest vdev. Adding one takes a second press, on **Add anyway**.
:::

A pool on attached disks that this machine has not imported shows an **Import** button. **Destroy pool** erases every dataset after you type the pool's name.

## Disk health

**Topology** draws each pool's vdevs and disks, and lists unused disks as **UNASSIGNED**. Each disk reads **SMART ok** or **SMART FAILING**; select one to see its details.

- **Scrub** checks every block of a pool against its checksums.
- **Offline** takes a selected disk out of its pool for a while, and **Online** puts it back.
- **Replace** lists the spare disks; pick one and select **Start resilver** to rebuild onto it.

## Datasets

1. Under **Datasets**, select **Add dataset**.
1. Pick the **Pool** and fill the **Name**.
1. Optional: set a **Mountpoint**. Left blank, it is `/pool/name`.
1. Pick the **Compression** and the **Record size**. Small records suit databases and VM images, large ones media.
1. Select **Create dataset**.

**Destroy** on a row removes the dataset and every file on it.

To share a mounted dataset, the [File share](shares.md) module must run on the same machine. Select **Share** on the row, pick the users, or none for every user, and select **Share** again. The row then has an `smb` badge, and **Unshare** withdraws it.
