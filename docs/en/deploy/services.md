# Add existing services

Existing services are services that already run, such as the admin page of a router or a NAS. After you declare them as apps, you can open them from the client.

Declaring a service needs only that the hub can connect to it. The client connects only to the hub, and the hub connects to the device, so you can open the service from an outside network too.

## Declare an app

The following steps use the admin page of a router as the example:

1. In the panel's left sidebar, select **Services**, then select **Declare app** in the top-right corner.

   ![The Services page with the Declare app button marked in red](/guide/en/deploy_services_01_page.webp)

1. In the dialog, enter the name to display in **Name**. In **Host**, enter the IP address or host name of the device, here `192.168.122.1`, which the hub must be able to connect to. `127.0.0.1` or `localhost` means the hub itself. **Description** is optional.

   ![The Declare app dialog with the Host field marked in red](/guide/en/deploy_services_02_name_host.webp "Enter the name and host")

1. Under **Entries**, open the first **Type** and choose the type of the entry: **Web**, **Port** or **File**. Here, choose **Web**.

   ![The Type list with the Web row marked in red](/guide/en/deploy_services_03_entry_type.webp "Choose Web")

1. In **Port**, enter the port the service uses, usually 80 or 443 for a web page. In **Scheme**, choose http or https. Leave **Path** at `/` unless the page of the service is under another path.

   ![The Port field showing 80, marked in red](/guide/en/deploy_services_04_entry_port.webp "Enter the port")

1. If the device has other ports to use, select **Add entry** to add another row. Here, add a second entry of type **Port** and choose TCP in **Protocol**. The same entry cannot be added twice.

   ![The second entry, of type Port, marked in red](/guide/en/deploy_services_05_entry_second.webp "Add another entry")

1. When everything is filled in, select **Declare**.

   ![The Declare button marked in red](/guide/en/deploy_services_06_save.webp)

1. The **Apps** area gains a row that shows the host, the description, each entry and the source **declared**.

   ![The Services page with the router row marked in red](/guide/en/deploy_services_07_declared_row.webp)

Each entry is followed by **reachable**, **unreachable**, **checking…** or **not checked**. If the row shows **unreachable**, it also shows **The host did not answer.** under it, which means the hub cannot connect to the service. In that case, check **Host** and **Port** for mistakes, then select **Test** in the row to make the hub check again right away.

![The router row with the Test button marked in red](/guide/en/deploy_services_08_tested.webp)

When the hub can connect, the entries show **reachable**:

![The printer row with its entries showing reachable, marked in red](/guide/en/deploy_services_10_reachable.webp)

## Open from the client

Open the **Apps** page in the client, where the declared app is listed.

![The client's Apps page with the printer row marked in red](/guide/en/deploy_services_11_client_row.webp)

Each type of entry works as follows:

| **Type** | Also fill in                            | Use in the client                                                                                      |
| -------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **Web**  | **Scheme**, http or https, and **Path** | On the **Apps** page, select **Use**, then **Open**                                                    |
| **Port** | **Protocol**, TCP or UDP                | On the **Apps** page, select **Use**, then enter the local address in your program                     |
| **File** | **Share name**; **Port** can stay empty | On the **Files** page, select **Configure** to enter the user name and password, then select **Mount** |

A web entry can also get a link through [App share](/en/share/web_share): select **Share** in its row. The visitor sees the app's own page and signs in to it when the app has a sign-in page. Port and file entries cannot be shared.

## Apps that appear automatically

Apps you install on a system appear automatically after they run. Each port that a container publishes also appears automatically, with its entry type, web or port, detected, and its source shows **declared** or **manual**. To run new software, you can use [Containers](/en/deploy/containers).

## Delete a declared app

If you no longer need an app, select **Delete** in its row, then **Delete** in the dialog. This also ends the shares of the app. Only declared apps have **Test** and **Delete**.

![The delete dialog with the Delete button marked in red](/guide/en/deploy_services_09_delete_dialog.webp)

## Risks and limits

A client needs the **Web pages**, **Ports** or **Files** permission to see declared apps, as [Clients](/en/hub/clients) describes.

If the address is on none of the joined systems, a client with a permission other than **All agents** cannot see the app. In that case, turn on **Choose per app** in the permission, then turn on this row.

The hub cannot check UDP ports, so they always show **not checked**, and clients can still use them. UDP shares one connection with the other traffic. It suits light traffic such as lookups and time sync, and is unsuited to voice, video and fast-paced games.

When an entry cannot be reached, its row in the client shows **Not reachable now**.

The hub keeps no password for a declared file share, so enter the password yourself in the client.

Declared entries have no one-time passphrase. After you select **Use**, every program on this client computer can connect to that local address.

On macOS and iOS, all web apps share one address. When two apps keep sign-in records with the same name, signing in to one signs you out of the other.
