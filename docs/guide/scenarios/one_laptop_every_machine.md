---
title: One laptop, every machine
---

# One laptop, every machine at home

You install an agent on two more machines at home, the Linux machine `server` and the Windows computer `desktop`. From one client window, a Mac laptop named `laptop` then opens a shell on each machine, shows `desktop`'s screen and opens VS Code on the hub box.

## Before you start

- You have done the [First step](../quick-start.md), so the hub runs on the hub box and the panel lists its own agent as `hub`.
- You have root through `sudo` on `server`, and an administrator account on `desktop` and on `laptop`.
- All four machines are on the same LAN, where every step runs.

## Enroll server

1. On the panel's **Devices** page, select **Add by link**.
1. Select **Copy**. Each enrollment link joins one machine.
1. On `server`, run the install script for the agent:

   ```bash
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
   ```

1. Join `server` to the hub, replacing `<enroll-link>` with the link you copied:

   ```bash
   sudo nagent join '<enroll-link>'
   ```

`server` appears under **Managed devices** on the **Devices** page.

![The enrollment link with its Copy button on the Devices page](/guide/en/devices_enroll_link.webp)

## Enroll desktop

1. On the **Devices** page, select **Add by link**.
1. Select **Copy**.
1. On `desktop`, open PowerShell.
1. Run the install script for the agent:

   ```powershell
   & ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) agent
   ```

1. Accept the prompt for administrator rights. The script goes on in a new administrator window.
1. In that window, join `desktop` with the new link:

   ```powershell
   nagent join '<enroll-link>'
   ```

`desktop` appears under **Managed devices** beside `hub` and `server`.

## Join laptop as a client

If `laptop` has not joined the hub yet, install the client and join it as the [First step](../quick-start.md) does for a laptop. Its hub row reads **Connected · LAN**.

![The hub row in the client window reading Connected · LAN](/guide/en/client_connected.webp)

## Open a shell on each machine

1. In the client window, open the **Terminals** page.
1. Pick `hub` in the strip of machines at the top of the page.
1. Select **New terminal**.
1. Pick `server`.
1. Select **New terminal**.
1. Pick `desktop`.
1. Select **New terminal**.

Each terminal opens in its own tab: a root shell on `hub` and `server`, and PowerShell as SYSTEM on `desktop`.

![Three terminal tabs in the client, one for each machine](/guide/en/client_terminals_three.webp)

## Share desktop's screen

1. On the panel's **Modules** page, pick `desktop`.
1. On the **Remote desktop** tab, turn on **Share this machine's desktop**.
1. Select **Apply remote desktop**.
1. If nobody is signed in at `desktop`'s own screen, sign in to Windows there.
1. In the client window, open the **Remote desktops** page.
1. On the `desktop` row, select **Connect**.

The viewer shows `desktop`'s screen, and the row reads **Viewer open**.

![The Remote desktops page with the desktop row reading Viewer open](/guide/en/client_remote_desktops.webp)

## Open VS Code on the hub box

The instance runs as an existing user account on the hub box, such as your own. In the panel:

1. On the **Modules** page, pick `hub`.
1. If the tab strip shows no **VS Code** tab, select **+** and turn on **VS Code** in the list.
1. On the **VS Code** tab, select **Open and accept the terms**. Microsoft's terms open in a new tab.
1. Select **Install**.
1. When the install finishes, select **Configure**.
1. Under **Instances**, select **Add instance**.
1. Fill **Account** with the account's user name.
1. Select **Apply VS Code**. The instance's row reads **running**.

![The VS Code tab on hub with one running instance](/guide/en/vscode_panel.webp)

On `laptop`:

1. In the client window, open the **Web** page.
1. On the VS Code row, select **Open**.

VS Code opens in your browser, on the hub box's files.

![The Web page in the client with the VS Code row open](/guide/en/client_web_vscode.webp)
