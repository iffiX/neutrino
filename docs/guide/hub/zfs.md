---
title: ZFS
---

# ZFS

The **ZFS storage** tab of [the Modules page](./modules.md) builds pools and datasets on a managed machine and reads its disk health. A dataset shared from the tab becomes an SMB share. Its **Pools**, **Topology** and **Datasets** sections open after **Configure**.

The hub keeps no wanted pool list, so these sections show what the machine reports about its own disks, and each press runs on the machine at the moment you make it.

## Pools and topology

1. Under **Pools**, select **Create pool**.
1. Fill the **Pool name** and pick the **First vdev disks**.
1. Pick the **Vdev layout**.
1. Confirm. Disks that hold data need the word `wipe` typed before they are erased.

A vdev is a group of disks the pool stripes across, and the layout is how a vdev holds its data:

| Layout      | What it gives             |
| ----------- | ------------------------- |
| **Single**  | no redundancy             |
| **Mirror**  | full copies               |
| **RAID-Z1** | survives one failed disk  |
| **RAID-Z2** | survives two failed disks |

**Topology** draws each pool's vdevs and disks. **Expand** adds a vdev to a pool, and a pool found on attached disks is offered for **Import**.

::: danger
A layout that does not match the pool's existing vdevs leaves the pool only as safe as its weakest vdev.
:::

## Datasets

1. Under **Datasets**, select **Create dataset**.
1. Fill the **Name**, pick the **Pool**, and set a **Mountpoint** or leave it blank for `/pool/name`.
1. Confirm.

Each dataset row shows its compression, record size and usage. **Destroy** removes the dataset and every file on it, and there is no snapshot to return to unless one was taken.

## Disk health and replacement

Each disk in **Topology** shows its **SMART** result, **passed** or **FAILING**, and its **Model**. The temperature is shown when the drive reports one. **Scrub** starts a scrub of the pool. **Replace** on a disk takes a spare disk from the picker and resilvers onto it; with no spare attached the button reads **No spare disk to replace with**.

## Share a dataset

1. On a mounted dataset, select **Share**.
1. Pick the users the share accepts, or pick none to accept every user, and confirm.

The Samba module on the same machine exports the dataset's mountpoint over SMB, read-write for the chosen users. With Samba missing or stopped there, the button reads **Install and start Samba first**, which is the **File share** tab on the same page. A shared row has an `smb` badge, it is a share on [the Samba page](./samba.md) and an entry in the clients' **Files** panel, and **Unshare** withdraws it.
