---
title: Files
---

# Files

On the **Files** page you browse a managed machine's whole filesystem as root. You also copy files between that machine and your own computer.

![The Files page at phone width, with two-line rows and a row's menu open](/guide/en/files_row_menu.webp)

## Browse a machine

1. Under **Which machine**, select a machine whose agent is online.
1. Select a folder's name to open it.

The path at the top of the list is a row of buttons; select any part of it to go back to that folder. The browser opens at `/`, the machine's root.

On a Windows machine, the browser opens at **Drives**, with one row per drive, such as `C:`. Select a drive to open its root. The path uses `\` between folders, as Windows writes it. At **Drives**, **New folder** and **Upload** are greyed, and the rows have no buttons.

The page keeps the machine and the folder you had open until you reload the panel. The **Files** button in a device's drawer on the [Devices](../hub/devices.md) page opens this page on that machine.

## Copy files

- To upload, open the target folder and select **Upload**, then pick one or more files. A line above the list counts them as they go.
- To download a file, select the download button on its row.
- To download a folder, select **Download as tar.gz** on its row. A file whose name starts with a dot also arrives as a tar.gz, because browsers drop that dot from a plain download.

A symbolic link has no download button; selecting it opens the folder it points to.

## Rename, delete and make folders

- **New folder** adds a row with a name field. Type the name and press Enter or select **Create**.
- **Rename** turns the row's name into a field. Type the new name and press Enter; Escape keeps the old one.
- **Delete** takes two presses. The first turns the button into a check and the line under the list says that deleting cannot be undone. The second press removes the entry.

## On a phone

At a width under 720 pixels, each row takes two lines: the name on the first, the size and the time on the second.

On a touch screen, or in a window narrower than 880 pixels or taller than wide, a row's buttons move behind **⋯** (**More actions**). Its menu lists **Download** (**Download as tar.gz** for a folder), **Rename** and **Delete**. After the first press, **Delete** reads **Click again to delete** and the menu stays open for the second press.

## When the machine is offline

If the machine's agent is offline, the hub rejects every request with `agent_offline`. The page then reads **The machine is not answering, so nothing was read or written.**
