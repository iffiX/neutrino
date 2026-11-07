# Clients

A client is the program you use to connect to the hub, either the desktop client or the phone app. The panel's **Clients** page is where you generate join links, set each device's permissions, and rename, disable or delete devices.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.2.0" />

To install the client on a device, see [Install the client](/en/access/install_client). To join a device to the hub, see [Join a hub](/en/access/join).

## Page contents

In the panel's sidebar, select **Clients**. The page has these sections:

- **Clients**: one row for each device that joined the hub.
- **App shares**: one row for each share, as [App share](/en/share/web_share) describes.

![The Clients page with the Clients section on top and the App shares section under it](/guide/en/hub_clients_01_page.webp)

After a device joins, its row shows the following columns:

![An online row in the Clients section](/guide/en/access_join_05_joined.webp)

| Column        | Content                                                                                                             |
| ------------- | ------------------------------------------------------------------------------------------------------------------- |
| **Name**      | The name you gave the device                                                                                        |
| **Hostname**  | The device's host name                                                                                              |
| **Platform**  | The device's operating system                                                                                       |
| **Version**   | The client's version                                                                                                |
| **Status**    | The device's connection status, such as **online**, **disabled** or **never connected**                             |
| **Last seen** | When the device last connected to the hub, **online** while it is connected, or **never** if it has never connected |

After you generate a link, the row shows **Waiting to join (N min left)** until the device joins. Such a row has only **Permissions** and delete. When the link expires, the row disappears automatically.

![A waiting row in the Clients section](/guide/en/access_join_04_waiting.webp)

## Permission kinds

If the device belongs to someone else, change its permissions before you send the link, and turn on only the features that person needs.

Each permission is either on or off. When a permission is on, the device uses that feature directly, with no further password. New devices follow **Default permissions**, in which only **Hub panel without the password** is off.

| Permission                         | What the device can do when it is on                                                                                                                 |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Virtual network**                | Join the NetBird or EasyTier network that the hub publishes                                                                                          |
| **Hub panel without the password** | The hub's row gets a **Panel** button that signs in directly. The device can change everything in the panel, so turn it on only for your own devices |
| **Web pages**                      | Open the web pages of apps                                                                                                                           |
| **Ports**                          | Forward app ports to the device's local address, for programs on the device to connect to                                                            |
| **AI gateway**                     | Use the hub's AI gateway. The phone apps lack this feature                                                                                           |
| **Files**                          | Open the shares on each system                                                                                                                       |
| **Terminals**                      | Open terminals and run commands as the accounts turned on for each system                                                                            |
| **SSH**                            | Let ssh, scp and git on a computer connect to each system. The phone apps lack this feature                                                          |
| **Remote desktops**                | Connect to the desktops that each system shares                                                                                                      |

A permission change takes effect immediately. When you take a permission away, the hub immediately closes the connections that the permission covers.

## Change one device's permissions

1. In the **Clients** section, find the device and select **Permissions** on its row. A table opens under the row. While **Follow the default** is on, every other switch is grey, so turn it off first.

   ![The row's Permissions button marked](/guide/en/access_join_06_permission_button.webp "Select Permissions")
   ![The permissions table with the Follow the default switch marked](/guide/en/access_join_07_follow.webp "Turn off Follow the default")

1. Turn on or off the permissions you want to change, for example **Hub panel without the password**, then select **Apply permissions**. What the device shows updates to the new permissions immediately, and the row shows **own permissions**.

   ![The table with Follow the default off and the Hub panel without the password switch marked](/guide/en/access_join_08_custom.webp "Change the permissions")
   ![The Apply permissions button marked](/guide/en/access_join_11_apply.webp "Select Apply permissions")

To return to the defaults, open the table, turn **Follow the default** back on, then select **Apply permissions**.

## Limit to some systems or apps

By default, a permission covers every system. You can narrow it by system or by app.

### Limit by system

Select **All agents** on the right of the permission, then select the systems to allow. With no system selected, every system is allowed.

![The permissions table with the picker next to Web pages marked](/guide/en/access_join_16_filter_button.webp "Select All agents")
![The system list for Web pages, open](/guide/en/access_join_09_filter.webp "Select the systems")

### Limit by app

Turn on **Choose per app** at the bottom. Each permission then lists every app, share, desktop and system under it, each with its own switch. These switches take priority over the switch of the permission they belong to. An app that belongs to two permissions appears under both, and the two switches are one and the same.

![Each app with its own switch after Choose per app is on](/guide/en/access_join_10_fine.webp)

To allow only one app, turn off **Follow the default** and every permission, turn on **Choose per app**, then turn on only that app's switch. To clear an app's own setting, select **Follow the kind** beside it. Select **Apply permissions** after every change.

## Change the default permissions

Select **Default permissions** at the top right of the **Clients** section. The dialog has the same switches as a device's permissions table. After you select **Apply permissions**, every device that follows the default uses the new permissions.

![The Clients section with Default permissions marked](/guide/en/access_join_17_default_button.webp "Select Default permissions")
![The Default permissions dialog](/guide/en/access_join_12_default.webp "Change it, then select Apply permissions")

## Row buttons

Each row has **Rename**, **Permissions**, **Disable** and **Delete** on the right. For **Permissions**, see [Change one device's permissions](#change-one-device-s-permissions).

### Rename

Select **Rename**, edit the name in the input box, then select **Save**. The change affects only the name the panel shows.

![The name as an input box](/guide/en/access_join_15_rename.webp)

### Disable

Select **Disable**. In the device's client, the hub's row then shows **Disabled by the hub** and the message **The hub has switched this client off.** The device cannot use any feature until you enable it again, and its open connections close immediately. Select **Enable** to restore it. If a device is lost, disable it first, and delete it after you are sure you cannot recover it.

![The row's Disable button marked](/guide/en/access_join_13_disable.webp)

### Delete

Select **Delete** on the row, then **Delete** in the dialog. The device leaves the hub, and the hub revokes its gateway key. The device needs a new link to join again. Deleting a device that is still waiting to join invalidates its link immediately.

![The delete confirmation dialog](/guide/en/access_join_14_delete.webp)
