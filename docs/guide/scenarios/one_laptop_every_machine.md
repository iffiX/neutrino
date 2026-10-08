---
title: One laptop, every machine
---

# One laptop, every machine at home

This tutorial ends with a Mac laptop working on every machine at home from one client window. The client on `laptop` has a shell open on the hub box, on the Linux machine `server` and on the Windows computer `desktop`. It shows `desktop`'s screen in a viewer, and it opens VS Code from the hub box in your browser.

Every step runs on your home LAN.

## Before you start

- The hub is installed on the hub box, and you are signed in to its panel, as [Install the hub](../install/hub.md) describes. The panel lists the hub box's own agent as `hub`.
- You have root through `sudo` on `server`, an administrator account on `desktop`, and an administrator account on `laptop`.
- The hub box, `server`, `desktop` and `laptop` are on the same LAN.

## Enroll server

1. On the panel's **Devices** page, select **Add by link**.
1. Select **Copy** to copy the enrollment link. Each link joins one machine.
1. On `server`, run the install script for the agent:

   ```bash
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
   ```

1. Join `server` to the hub, in a terminal on `server` or over SSH to it. Replace `<enroll-link>` with the link you copied:

   ```bash
   sudo nagent join '<enroll-link>'
   ```

`server` appears under **Managed devices** on the **Devices** page.

![The enrollment link with its Copy button on the Devices page](/guide/en/devices_enroll_link.webp)

## Enroll desktop

1. On the **Devices** page, select **Add by link**.
1. Select **Copy** to copy a new enrollment link.
1. On `desktop`, open PowerShell.
1. Run the install script for the agent:

   ```powershell
   & ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) agent
   ```

1. Accept the Windows prompt for administrator rights. The script goes on in a new administrator window.
1. In that administrator window, join `desktop` to the hub with the new link:

   ```powershell
   nagent join '<enroll-link>'
   ```

`desktop` appears under **Managed devices** beside `hub` and `server`.

## Join laptop as a client

1. On `laptop`, open Terminal.
1. Run the install script for the client. The script runs `sudo` one time, so type your password at its prompt:

   ```bash
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- client
   ```

1. On the panel's **Clients** page, select **New client link**.
1. Type `laptop` as the name.
1. Select **Create link**.
1. Select **Copy**.
1. On `laptop`, open **Neutrino Client** from Applications.
1. On the **Hubs** page, paste the link into the **Join a hub** row.
1. Select **Join**.

The hub's row reads **Connected · LAN**.

![The hub row in the client window reading Connected · LAN](/guide/en/client_connected.webp)

## Open a shell on each machine

1. In the client window, open the **Terminals** page.
1. Pick `hub` in the strip of machines at the top of the page.
1. Select **New terminal**.
1. Pick `server`.
1. Select **New terminal**.
1. Pick `desktop`.
1. Select **New terminal**.

Each terminal opens in a tab of its own. On `hub` and `server` the shell runs as root. On `desktop` it is PowerShell, running as SYSTEM.

![Three terminal tabs in the client, one for each machine](/guide/en/client_terminals_three.webp)

## Share desktop's screen

1. On the panel's **Modules** page, pick `desktop`.
1. On the **Remote desktop** tab, turn on **Share this machine's desktop**.
1. Select **Apply remote desktop**.
1. If nobody is signed in at `desktop`'s own screen, sign in to Windows there.
1. In the client window, open the **Remote desktops** page.
1. On the `desktop` row, select **Connect**.

The RustDesk viewer opens on `desktop`'s screen, and the row reads **Viewer open**.

![The Remote desktops page with the desktop row reading Viewer open](/guide/en/client_remote_desktops.webp)

## Open VS Code on the hub box

The VS Code instance runs on the hub box as one of its user accounts, such as the one you sign in with there. The account must already exist.

In the panel:

1. On the **Modules** page, pick `hub`.
1. If the tab strip shows no **VS Code** tab, select **+** and turn on **VS Code** in the list.
   <!-- 待核: whether a new machine's Modules page shows the VS Code tab before it is turned on under + (outline item 10) -->
1. On the **VS Code** tab, select **Open and accept the terms**. Microsoft's terms open in a new browser tab, and the hub records that you accept them for this machine.
1. Select **Install**.
1. When the install finishes, select **Configure**.
1. Under **Instances**, select **Add instance**.
1. Fill **Account** with that account's user name.
1. Select **Apply VS Code**. The instance's row reads **running**.

![The VS Code tab on hub with one running instance](/guide/en/vscode_panel.webp)

On `laptop`:

1. In the client window, open the **Web** page.
1. On the VS Code row, select **Open**.

VS Code opens in your browser, working on the hub box's files.

![The Web page in the client with the VS Code row open](/guide/en/client_web_vscode.webp)
