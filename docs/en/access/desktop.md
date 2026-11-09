# Desktop client

The desktop client is a window program on your computer. In its window, you use the apps, files, terminals and desktops on each system.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.2.0" />

Before you start, install the client on this computer and join it to a hub, as [Install the client](/en/access/install_client) and [Join a hub](/en/access/join) describe. The pages are on the left side of the window: **Hubs**, **Apps**, **AI**, **Files**, **Terminals**, **Remote desktops** and **Settings**.

## Open and quit

The client starts only when you open it, never at login. Open **Neutrino Client** from the application menu or Start menu, or run `nclient gui`.

Closing the window only hides it, and connections and entries stay open. Select **Open** in the tray menu to show the window again. Select **Quit** in the tray menu to quit the client.

A computer runs the client for one account at a time. Another account can run it after this client quits.

## Hubs

The **Hubs** page has one row per hub, with its connection status and connection method.

![Hubs page with the Panel button marked in red](/guide/en/access_desktop_01_hubs.webp)

When connected, the row shows **Connected**, followed by the connection method and the round-trip time. The method is one of **LAN**, **Direct**, **NetBird**, **EasyTier**, **SSH relay**, **SakuraFrp** or **OpenFrp**. When not connected, the row shows the reason, such as **The hub did not answer**, **Hub key mismatch** or **Version too old**. [Troubleshooting](/en/reference/troubleshooting) lists the fixes.

The right side of the row has these buttons:

- **Panel** opens the hub's panel without a password. It appears only when this computer has the **Hub panel without the password** permission.
- **Leave** leaves this hub. The first press changes it to **Press again to leave**, and the second press takes effect.
- **Reconnect** appears only when the row shows **Replaced by another client**. That status means another client connected to the hub with the same binding.
- **Connect** joins the virtual network and appears only when the hub publishes NetBird or EasyTier. When the hub publishes both, a selector beside it picks one, and one is in use at a time. A computer joins the virtual network of one hub at a time.

## Apps

The **Apps** page has one row per app, with the app's address on this computer under it. The address stays the same, so you can bookmark it.

1. Select **Use** on the row to open the local entry; no browser opens at this point. The row gains **Stop** and **Open**.

   Select **Open**, and the system browser opens the app. Apps such as code-server and CloudCLI open already signed in, with no password prompt.

   ![Apps page with the Use button marked in red](/guide/en/access_desktop_02_apps.webp "Select Use")
   ![CloudCLI row with the Open button marked in red](/guide/en/access_desktop_03_apps_open.webp "Select Open")

1. When you finish, select **Stop** to close the entry.

Select **Configure** to change the local port the app uses; you rarely need to change it. While the app is in use, the button is grey, and you select **Stop** first.

![Dialog for setting the local port](/guide/en/access_desktop_04_app_port.webp)

## AI

On the **AI** page, set Claude Code, Codex and Gemini on this computer to use the hub's gateway:

1. Select **The AI tools use this gateway**. The switch turns green, and the row shows **The tools point at the hub**. The tools reach the gateway only while the client keeps running. One hub's gateway is on at a time.

   ![AI page with The AI tools use this gateway marked in red](/guide/en/access_desktop_05_ai.webp)

1. Optional: To pick the models, select **Configure**, choose them, then select **Save**.

   ![Switch turned on, Configure button marked in red](/guide/en/access_desktop_06_ai_on.webp "Select Configure")
   ![AI tool configuration dialog](/guide/en/access_desktop_07_ai_config.webp "Choose, then select Save")

If this computer also has the agent installed, the switch is grey. Use **AI tools use the hub's gateway** in the panel instead, as [AI gateway](/en/hub/ai_gateway) describes.

## Files

On the **Files** page, you mount the shares of your systems on this computer.

While a share is not mounted, its row has **Mount** and **Configure**. Select **Mount**; it mounts without a password. After mounting, the row shows the share's location, and the buttons become **Unmount**, **Configure** and **Open**. On Linux and macOS, shares mount under `~/remote/` by default, and on Windows a share mounts as a drive letter.

![Files page with the Mount button marked in red](/guide/en/access_desktop_08_files.webp "Select Mount")
![Mounted location shown, Open button marked in red](/guide/en/access_desktop_09_files_mounted.webp "Select Open")

Select **Open** to open the mounted folder in the system's file manager. Only the desktop client has this button. Select **Unmount** to unmount the share.

Select **Configure** to change the mount location. A location saved for a mounted share applies at the next mount; the buttons and the current mount stay as they are. For a share declared by hand, such as a NAS, first enter **Share username** and **Share password** in **Configure**. On macOS, the system shows a confirmation dialog at the first connection.

## Terminals

On the **Terminals** page, you open a terminal on a system without a password:

1. Select the system name at the top. If the system has two or more accounts enabled, choose one in **Account** beside it. Then select **New terminal**.

   ![Terminals page with the system name marked in red](/guide/en/access_desktop_10_terminal_pick.webp "Select the system name")
   ![Account selector and New terminal button](/guide/en/access_desktop_11_terminal_new.webp "Select New terminal")

1. The terminal appears under the system names, ready for commands.

   ![Open terminal with the Persistent and Shared switches under it](/guide/en/access_desktop_12_terminal_open.webp)

You can open several tabs, and each keeps its output when you switch between them. The context menu has **Copy**, **Paste**, **Select all** and **Clear**. The lower-right corner of the terminal has the **Persistent** and **Shared** switches:

- With **Persistent** on, the session stays on that system after you close the window.
- With **Shared** on, every client with the **Terminals** permission for that system can connect to the same session.

You can also open a terminal on the command line, as [Terminal commands](/en/access/terminal) describes.

## Remote desktops

On the **Remote desktops** page, you connect to a desktop that a system shares. Turn on sharing on that system first, as [Remote desktop](/en/deploy/remote_desktop) describes.

Select **Connect** on the row; it connects without a password. The desktop opens in a separate viewer window, and the row shows **Viewer open**.

![Remote desktops page with the Connect button marked in red](/guide/en/access_desktop_13_desktops.webp "Select Connect")
![The row shows Viewer open](/guide/en/access_desktop_14_viewer_open.webp "Viewer open appears")

The computer and the system share one clipboard, and the viewer's file transfer window copies files in both directions. Closing the viewer ends the connection.

If a Mac shows a black screen or the mouse has no effect, that Mac lacks permissions. On that Mac, turn on Screen Recording and Accessibility for RustDesk.

## Settings

In the lower part of the **Settings** page, change **Language** and **Theme** (**System**, **Dark** or **Light**), then select **Save**. [SSH connections](/en/access/ssh) covers **SSH programs reach the machines**. In the upper part, **About** shows this computer's name, the client version and the bundled programs.

![Settings page with the Save button marked in red](/guide/en/access_desktop_15_settings.webp)
