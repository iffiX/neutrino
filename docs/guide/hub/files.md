---
title: Files
---

# Files

Browse a managed machine's filesystem as root from the **Files** page, and copy files in either direction.

![The Files page browsing a machine](/guide/en/files.webp)

1. Under **Which machine**, pick a machine that is online. The file browser opens on that machine's filesystem, as root.
1. Open a directory by selecting it; **.. up** returns to its parent.

**Upload** sends files from your computer into the open directory. **Download** fetches one file, and **Download as tar.gz** fetches a directory as one archive. A directory is created with **New folder**, and an entry is renamed with **Rename**. Deleting takes two presses of **Delete**: the first arms the button, the second removes the entry. The agent reads and writes as root on the machine, and a machine that is offline is rejected with `agent_offline`. The drawer of a device on [the Devices page](./devices.md) has a **Files** button that opens the same browser.
