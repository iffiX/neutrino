# Containers

A container is packaged software that runs with Podman. You can also run and open an app missing from the module list by entering its image name.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.2.0" />

An image is a packaged software bundle, such as `docker.io/library/redis:7`. After you enter the image name and ports in the panel, the container runs and appears automatically on the client's **Apps** page.

## Supported systems

| System                           | Architecture         | First Neutrino Hub version | How it runs                                                                                |
| -------------------------------- | -------------------- | -------------------------- | ------------------------------------------------------------------------------------------ |
| Linux (Debian and RHEL families) | amd64, arm64         | 0.2.0                      | The system's Podman 3.4 or later, directly on the system                                   |
| Linux (Arch family)              | amd64                | 0.2.0                      | The system's Podman 3.4 or later, directly on the system                                   |
| Windows (build 19041 or later)   | amd64                | 0.6.0                      | A Podman virtual machine in WSL 2, installed during the install; virtualization must be on |
| macOS 13 or later                | Apple silicon, Intel | 0.6.0                      | A Podman virtual machine, installed during the install                                     |

## Install

1. Open the panel in a browser, sign in, and select the system to install on in the lower half of the sidebar.
1. In the **Module configuration** area, select **+ Add module**. In the dialog, scroll down and select the **Containers** card, then select **Close** after the card is highlighted.

   ![The module list with the Add module button boxed in red](/guide/en/deploy_containers_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the Containers card boxed in red](/guide/en/deploy_containers_02_catalog.webp "Select Containers")
   ![The Containers card highlighted, with the Close button boxed in red](/guide/en/deploy_containers_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **Containers** row in the list on the left, and its tab appears on the right. Select **Install**.

   ![The module list with the Containers row boxed in red](/guide/en/deploy_containers_04_tab.webp "Select Containers")
   ![The Containers tab showing not installed, with the Install button boxed in red](/guide/en/deploy_containers_05_install.webp "Select Install")

1. On Linux, the tab starts listing the steps right away. On Windows and macOS, **Choose the account that runs the containers** opens first; for its steps, see [Apps that need containers](/en/deploy/on_a_machine#apps-that-need-containers).

   ![The tab showing installing, with every step listed](/guide/en/deploy_containers_06_installing.webp "Linux: steps listed")
   ![The Choose the account that runs the containers dialog](/guide/zh/windows_account_dialog.webp "Windows and macOS: choose an account first")

1. On Windows, if the tab shows that a restart is needed, select **Restart now**. Every program open on this system closes, and the install continues after the restart.

   ![The Containers tab showing that Windows needs a restart, with Restart now boxed in red](/guide/zh/deploy_containers_18_reboot.webp)

1. When the tab shows **installed**, select **Start**. When the tab shows **running**, select **Configure**.

   ![The tab showing installed, with the Start button boxed in red](/guide/en/deploy_containers_07_installed.webp "Select Start")
   ![The tab showing running, with the Configure button boxed in red](/guide/en/deploy_containers_17_started.webp "Select Configure")

The **Running now**, **Hub containers**, **Registry mirrors** and **Declared containers** areas open under the tab, and the install is complete.

![The Containers tab with its settings open](/guide/en/deploy_containers_08_config.webp)

## Use

The following steps run a container, with the small web program whoami as the example:

1. In the **Declared containers** area, select **Add container**.

   ![The Declared containers area with the Add container button boxed in red](/guide/en/deploy_containers_09_add_container.webp)

1. In **Name**, enter a name of lowercase letters, digits, hyphens and underscores. In **Image tag**, enter the image name and tag, here `docker.io/traefik/whoami:latest`; for an image on Docker Hub, you can pick one with **Pick a tag**. In the **Ports** box, enter `8088:80`, the system's port and then the container's port, and select **Add** beside it. Anything typed in the box without **Add** is added automatically when you select **Apply containers**.

   ![The name and image tag filled in, with the Image tag field boxed in red](/guide/en/deploy_containers_10_editor_name.webp "Enter the name and image")
   ![The Ports field showing 8088:80, boxed in red](/guide/en/deploy_containers_11_editor_port.webp "Enter the port")

1. The **Services** list under it shows this port. Keep **Auto** to detect after the container runs whether this entry is a web page or a port, or choose **Web** or **Port** directly. Select **Apply containers**; the first time, downloading the image takes a while. The yellow text beside the button says that edited containers are recreated, and files outside volumes are lost.

   ![The Services field with Auto selected for 8088, boxed in red](/guide/en/deploy_containers_12_editor_services.webp "Keep Auto")
   ![The Apply containers button boxed in red, with yellow text beside it](/guide/en/deploy_containers_13_apply.webp "Select Apply containers")

1. When **Applied.** appears under it, the container is running. The **Running now** area gains a row with the container's name, image and running time. The buttons beside it show the **Journal**, open a **Shell**, **Restart** and **Stop**.

   If a container fails to start, only that container shows the failure and its reason, and the other containers keep running.

   ![Applied. shown under the button](/guide/en/deploy_containers_14_applying.webp "Applied")
   ![The Running now area with the whoami row boxed in red](/guide/en/deploy_containers_15_live_row.webp "A new row")

Every port a container publishes becomes an entry on the client's **Apps** page automatically. These entries are in one row, titled with the container's name.

Open the client, go to the **Apps** page, find this row and select **Use**. The row gains a local address. For a web entry, select **Open**, and the browser opens it. A port entry has no **Open**, so enter this local address in your program.

![The client's Apps page with the Use button boxed in red](/guide/en/deploy_containers_40_client_use.webp "Select Use")
![The row with a local address, and the Open button boxed in red](/guide/en/deploy_containers_41_client_open.webp "Select Open")

**Configure** on this row changes the local port. A client needs the **Web pages** or **Ports** permission to see this row, as [Clients](/en/hub/clients) describes. Containers you start yourself with commands also appear here, with **manual** as their source.

## Share

The **Containers** tab has no web page of its own and cannot be shared. The web entries of the containers you run can generate links with [App share](/en/share/web_share).

1. In the panel sidebar, select **Services**, find the **whoami** row, and select **Share**.

   ![The Services page with the Share button of the whoami row boxed in red](/guide/en/deploy_containers_20_services_share.webp)

1. In the dialog, enter a **Name** that helps you identify the share; the other person does not see it. **Expires** defaults to 7 days, and you can choose another option before you select **Generate link**. Select **Copy** right away, send the link, then select **Done**. After the dialog closes, the panel no longer shows the link.

   ![The share dialog with the Name field boxed in red](/guide/en/deploy_containers_21_share_dialog.webp "Enter a name")
   ![The completed share dialog with the Generate link button boxed in red](/guide/en/deploy_containers_22_share_generate.webp "Select Generate link")
   ![The share dialog showing the link and a QR code, with the link row boxed in red](/guide/en/deploy_containers_23_share_link.webp "Select Copy")

The other person sees the web page inside the container. If the web page has a sign-in page, they sign in on their own. Port entries cannot be shared.

![whoami's web page open in a visitor's browser](/guide/zh/deploy_containers_24_visitor.webp)

## Risks and limits

When you select **Apply containers**, the panel shows **Edited containers will be recreated, and files outside volumes will be lost.** Keep the files you need in **Volumes**.

Every program in a container can read and write the folders that volumes map, and containers run as root.

On Linux, published ports bind to every address of the system, and the system firewall decides whether other computers can connect directly. On Windows and macOS, other computers connect through the client. Windows cannot publish UDP ports.

On Windows, changing the CPUs, memory or disk restarts every WSL system of this account. On Windows and macOS, changing the account stops the old account's virtual machine, and its images and named volumes stay where they are.

**Stop** also stops the virtual machine, which then stays stopped after a restart of the computer. Settings changed while it is stopped take effect at the next **Start**.

If you installed Podman yourself before installing Containers, Containers uses your Podman and installs no other copy. The tab shows your Podman's own version, which you cannot choose. Uninstalling Containers keeps your Podman.

On Windows and macOS, **Containers** on such a system shows **stopped** after the system joins the hub. At your first **Start**, the agent downloads the virtual machine image and creates the virtual machine, which takes a while.

## Settings

Each container's settings are in **Declared containers**, and you select **Apply containers** after a change.

| Setting                | Purpose                                                                                                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Name**               | Lowercase letters, digits, hyphens and underscores only                                                                                                   |
| **Image tag**          | Written as `<image>:<tag>`. For an image on Docker Hub, you can pick one with **Pick a tag**                                                              |
| **Ports**              | One `<host-port>:<container-port>` per line; add `/udp` for UDP                                                                                           |
| **Services**           | For each port, choose **Auto**, **Web** or **Port**; with Auto, the type is detected after the container runs                                             |
| **Volumes**            | One `<source>:<container-path>` per line. Windows accepts only the computer's fixed disks, and macOS only folders under /Users, /private and /var/folders |
| **Environment**        | One `<name>=<value>` per line                                                                                                                             |
| **Command (optional)** | When empty, the image's own command runs. A base image needs a long-running command                                                                       |
| **Start with the box** | Whether this container starts with the system                                                                                                             |

**Run settings** exist only on Windows and macOS:

| Setting              | Purpose                                                                                                                           |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Account**          | Runs the containers in this account's Podman virtual machine, which starts at boot without the account signing in                 |
| **CPUs**             | Defaults to half the CPU count; 0 here means the default                                                                          |
| **Memory (GiB)**     | Defaults to half the computer's memory, up to 4 GiB. When a container app lacks memory, a suggested value appears under the field |
| **Disk limit (GiB)** | Defaults to 100 and can only grow                                                                                                 |

The tab also has these two areas:

| Setting              | Purpose                                                                                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Running now**      | Lists each container and its source: **hub**, **declared** or **manual**. Change a **hub** container in the tab of its app                              |
| **Registry mirrors** | Add a mirror with **Add mirror**. Downloads try the mirrors in order and use docker.io only when none responds. Select **Apply mirrors** after a change |

![The Registry mirrors area with the Add mirror button boxed in red](/guide/en/deploy_containers_16_mirrors.webp)

## Uninstall

On the **Containers** tab, select **Uninstall**. The dialog states that the volumes of declared containers stay, and so does the Podman virtual machine on Windows and macOS. Select **Uninstall** to confirm.

![The Containers tab with the Uninstall button boxed in red](/guide/en/deploy_containers_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with the Uninstall button boxed in red](/guide/en/deploy_containers_51_uninstall_dialog.webp "Confirm")

After you install Containers again, the containers and volumes return.

While Ayakaleaf or Hermes WebUI is installed, uninstall it before you uninstall Containers. If you select **Uninstall** in that case, the tab lists the apps to uninstall first.

![The Containers tab showing that Hermes WebUI and Ayakaleaf must be uninstalled first](/guide/en/deploy_containers_47_uninstall_refused.webp)

If a container cannot run, see [Troubleshooting](/en/reference/troubleshooting).
