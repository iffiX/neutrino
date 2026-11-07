# Android app

The Android app is the phone client of Neutrino Hub. With only your phone, you use the apps, files, terminals and desktops on your computers.

<Facts editions="国际版,国内版" since="0.5.0" />

Before you start, install the client on the phone and join the phone to a hub, as [Install the client](/en/access/install_client) and [Join a hub](/en/access/join) describe. The bar at the bottom of the screen holds the pages: **Hubs**, **Apps**, **Files**, **Terminals**, **Desktops** and **Settings**. Compared with a computer, the app lacks the **AI** page and the SSH for other programs.

Connections stay open when you switch to another app. The notification **Connected to N hubs** keeps the connections running in the background.

## Hubs

The **Hubs** page has one row per hub and shows its status as a computer does, such as **Connected · SakuraFrp**. When the phone moves between mobile data and Wi-Fi, the app reconnects immediately. The row also has these buttons:

- **Panel** opens the panel in the phone's browser. It appears only when the phone has the **Hub panel without the password** permission.
- **Leave** takes effect on the second press.
- **Connect** appears only when the hub publishes NetBird or EasyTier. At the first connection, the system shows a permission dialog; select OK.

![Phone bottom bar and Hubs page, connected](/guide/zh/access_android_07_joined.webp "The row shows the status")
![A row on the phone Hubs page with the Leave button marked in red](/guide/zh/access_android_08_hub_row.webp "Leave takes two presses")

## Apps

1. In the bottom bar, select **Apps**, find the row you want, and select **Use**. On Android 13 and later, the system requests notification permission at the first press; allow it.

   The row gains **Open**. Select **Open** to open the app in the phone's browser. Only apps with a web page have this button.

   ![Phone Apps page with the Use button](/guide/zh/access_android_11_use.webp "Select Use")
   ![System notification permission dialog](/guide/zh/access_android_12_notify_prompt.webp "Allow it the first time")
   ![Phone Apps page with the Open button](/guide/zh/access_android_13_open.webp "Select Open")
   ![App open in the phone browser](/guide/zh/access_android_14_browser.webp "Use it in the browser")

1. When you finish, return to the **Apps** page and select **Stop**.

Select **Configure** to change the local port on the phone; you rarely need to change it. While the app is in use, the button is grey.

## Files

In the bottom bar, select **Files**, then select **Open in Files** on the share's row. The phone's Files app opens with the share as one of its locations. There you can open, write, create and delete files.

![Phone Files page with the Open in Files button marked in red](/guide/zh/access_android_20_files.webp "Select Open in Files")
![The share in the system Files app](/guide/zh/access_android_24_system_files.webp "The share is one location")

Shares on your systems open without a password. For a share declared by hand, such as a NAS, enter **Share username** and **Share password** the first time, keep **Remember** selected, and select **Connect**. **Forget password** takes effect on the second press.

## Terminals

In the bottom bar, select **Terminals** and choose a system. If the system has two or more accounts enabled, also choose an **Account**. Then select **New terminal**.

When the terminal opens, a row of keys appears on top of the keyboard: Esc, Tab, Ctrl, Shift, Alt and the arrow keys. Touch and hold the screen to show **Copy** and **Paste**.

![Phone Terminals page, choosing a system](/guide/zh/access_android_20_terminal.webp "Choose a system")
![Phone Terminals page with the New terminal button marked in red](/guide/zh/access_android_21_terminal_new.webp "Select New terminal")
![Terminal open on the phone](/guide/zh/access_android_22_terminal_open.webp "The terminal is open")
![Terminal and extra keys on the phone](/guide/zh/access_android_23_terminal_keys.webp "A row of keys on top of the keyboard")

The **Persistent** and **Shared** switches work as in the [Desktop client](/en/access/desktop).

## Desktops

Turn on sharing on that system first, as [Remote desktop](/en/deploy/remote_desktop) describes.

1. In the bottom bar, select **Desktops**. To adjust the picture, first select **Configure** on the row and choose **Codec** and **Quality**. Select **Connect**; the desktop fills the screen, and you can zoom with two fingers.

1. The round buttons in the upper-right corner are **Keyboard**, **Keys** and **Disconnect**, from left to right. **Keys** holds the keys a phone keyboard lacks, such as Esc, Ctrl and the arrow keys. Chinese input methods work as usual.

   ![Phone Desktops page with the Connect button marked in red](/guide/zh/access_android_30_desktop_row.webp "Select Connect")
   ![Configure dialog with Codec and Quality](/guide/zh/access_android_31_desktop_config.webp "Configure: Codec and Quality")
   ![Computer desktop full screen on the phone](/guide/zh/access_android_32_viewer.webp "The desktop fills the screen")
   ![Keys bar open](/guide/zh/access_android_33_viewer_keys.webp "Select Keys")

## Settings

In the bottom bar, select **Settings**. Change **Language** and **Theme**, then select **Save**. **About** shows the phone's name, the app version and the bundled programs.

![Phone Settings page](/guide/zh/access_android_20_settings.webp)
