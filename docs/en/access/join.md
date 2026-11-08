# Join a hub

You join a device to the hub before you use apps on it, and you decide which features each device can use.

To join a device, generate a link in the panel, then scan or paste it on the device. Before you start, install the client on the device, as [Install the client](/en/access/install_client) describes.

## Generate a join link

1. Open the panel, select **Clients** in the left sidebar, then select **New client link** in the upper-right corner.

   ![Clients page with the New client link button marked in red](/guide/en/access_join_01_clients.webp)

1. In **Name**, enter a name for the device, such as "My phone"; only the panel shows this name. If the device is yours, leave the permissions as they are and select **Generate link**. If the device belongs to someone else, change the permissions first, as [Clients](/en/hub/clients) describes.

   The dialog shows a link and a QR code. Keep the dialog open for joining the device: scan the QR code with a phone, or copy the link on a computer.

   ![Dialog with the name filled in and the Generate link button marked in red](/guide/en/access_join_02_name.webp "Enter a name and select Generate link")
   ![Link and QR code in the dialog](/guide/en/access_join_03_link.webp "The link and the QR code")

The link has these limits:

- Send it only to the device that joins. Anyone holding the link can join your hub with it.
- It is valid for 30 minutes and works one time.
- One link joins one device. A new link invalidates the previous unused one. Join two devices one after the other, and generate the second link after the first device joins.
- When the **Virtual network** permission is on, the link contains the credentials for joining the virtual network: the NetBird setup key, or the EasyTier network secret or console address.

Select **Done** after the device joins. If you close the dialog first, the panel stops showing the link. A link you copied still works until it expires; otherwise, generate a new one.

After the dialog closes, the **Clients** section gains a row showing **Waiting to join (N min left)**. If the link expires unused, the row disappears automatically.

![Waiting row in the Clients section](/guide/en/access_join_04_waiting.webp)

## Join on a phone

1. Open the client app **Neutrino** on the phone and select **Join a hub** on the **Hubs** page. The first time, grant camera access: select **Allow the camera**, then allow it in the system dialog.

   ![Phone Hubs page with the Join a hub button](/guide/en/access_android_01_home_empty.webp "Select Join a hub")
   ![Join page with the Allow the camera button](/guide/en/access_android_03_allow_camera.webp "Select Allow the camera")
   ![System camera permission dialog](/guide/en/access_android_04_camera_prompt.webp "Allow the camera")

1. Point the camera at the QR code in the panel. After a successful scan, the phone returns to the **Hubs** page automatically. If the camera is unavailable, paste the link into the input box under the camera view and select **Join**.

   ![QR code in the panel dialog](/guide/en/access_join_03_link.webp "The panel shows the QR code")
   ![Phone join page with the camera view](/guide/en/access_android_05_camera_on.webp "Point the phone at the QR code")

1. The new row first shows **Connecting…**. The phone has joined when the row shows **Connected · LAN** or another connection method.

   ![Phone Hubs page, connected](/guide/en/access_android_07_joined.webp)

## Join on a computer

1. In the panel dialog, select **Copy** to copy the link. Open the client window, paste the link into the **Join a hub** row on the **Hubs** page, then select **Join**.

   ![Client window with the link pasted and the Join button marked in red](/guide/en/access_install_client_03_join.webp)

1. The new row first shows **Connecting…**. The computer has joined when the row shows **Connected · LAN** followed by the round-trip time.

   ![The new row shows Connecting](/guide/en/access_install_client_04_connecting.webp "Connecting")
   ![The row shows Connected and LAN](/guide/en/access_install_client_05_connected.webp "Connected")

On the command line, you can instead run `nclient hub join '<link>'` with the copied link in place of `<link>`. The terminal shows `joined` and the hub address.

Back in the panel, select **Done** in the dialog. The device's row shows its host name, system and version, with the status **online**.

![Online row in the Clients section](/guide/en/access_join_05_joined.webp)

Away from the hub's LAN, you can still join when the hub has an [access method](/en/access/ways_in) turned on. A new row appears on the device immediately, and the link counts as used at the first connection to the hub. If no connection succeeds within 30 minutes, the row shows **Join refused**; select **Leave**, then join again with a new link.

## Set permissions

A new device follows the **Default permissions**. On the panel's **Clients** page, you change a device's permissions or limit them to some systems or apps. You also rename, disable and delete devices there, as [Clients](/en/hub/clients) describes.

## Join a second hub

A device can join several hubs at the same time:

1. Open the second hub's panel and change **Hub name** on the **Settings** page; otherwise, two hubs with the same name look identical.
1. Generate a new link on the second hub's **Clients** page, and join with the earlier steps.

After joining, the **Hubs** page has one more row, and the **Apps**, **Files**, **Terminals** and **Remote desktops** pages list the content of both hubs. Each hub's own **Clients** page sets what the device can use there.

A device joins the virtual network of one hub at a time. To switch, select **Disconnect** on the current hub first, then **Connect** on the other. The computer's **AI** page also opens the gateway of one hub at a time. Selecting **Leave** on one hub leaves the other hub unchanged.
