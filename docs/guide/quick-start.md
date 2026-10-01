---
title: Quick start
---

# Quick start

In about half an hour you build a hub in server mode on one Linux box and a second Linux machine that it manages. At the end, a folder on that machine is mounted on your laptop through the desktop client.

## What you need

- A Linux box for the hub, called `home-hub` on this page. It is x86-64, runs Debian 12 or newer or Ubuntu 22.04 or newer, and reaches the internet. You have root on it.
- A second Linux machine of the same kind for the agent, called `studio`.
- A Linux computer with a desktop session for the client, called `laptop`.
- The three package files of release 0.5.0 from the [releases page](https://github.com/iffiX/neutrino/releases): `neutrino-hub_0.5.0_amd64.deb`, `neutrino-agent_0.5.0_amd64.deb` and `neutrino-client_0.5.0_amd64.deb`.

The three machines are on one local network. Server mode keeps every address `home-hub` has, and the rest of your network stays as it is.

## Install the hub

1. On `home-hub`, install the package:

   ```bash
   sudo apt install ./neutrino-hub_0.5.0_amd64.deb
   ```

1. Start the setup wizard:

   ```bash
   sudo nhub setup
   ```

   The terminal prints an address for each of the box's interfaces, each ending in a one-time token.

1. On `laptop`, open one of the printed addresses in a browser, token included.

## Answer the setup wizard

Each question screen ends with **Next**, which moves to the following screen. The wizard writes to the box only after you confirm the last screen.

1. Select **Set this box up**.
1. On **Language**, keep **English**.
1. On **A password for the panel, a passphrase for the vault**, type a **Panel password** of at least 8 characters, and repeat it in **Again**.
1. On the same screen, type a **Vault master passphrase** of at least 16 characters with lowercase, uppercase, digits and symbols, and repeat it in **Again**.
1. Leave **HTTPS for the panel** off.
1. On **What is this machine for?**, select **Server**.
1. On **Which ports?**, keep **Panel answers on port** at `8080`.
1. On **Going out through a proxy**, leave **Set it up here** off.
1. On **Ready**, check that **HTTPS** reads **off**, and select **Set this box up**.

The steps run on the screen, from checking packages to installing this machine's agent, and the title changes to **This box is a gateway**.

::: warning
The vault passphrase seals every credential the box holds, and a restore from backup requires it again. Write it down somewhere other than the box.
:::

## Sign in to the panel

1. On **This box is a gateway**, select **Open the panel**.
1. Type the panel password in **Panel password** and select **Sign in**.

The **Dashboard** opens. The sidebar has two groups, **Hub** and **Agent**.

## Add studio as a managed machine

1. On `studio`, install the agent:

   ```bash
   sudo apt install ./neutrino-agent_0.5.0_amd64.deb
   ```

1. In the panel, under **Hub**, open **Devices**.
1. Select **Add by link**. A notice shows a link that works for five minutes.
1. Select **Copy**.
1. On `studio`, run the following command, with `<enroll-link>` replaced by the copied link:

   ```bash
   sudo nagent join '<enroll-link>'
   ```

`studio` appears under **Managed devices**, beside `home-hub`, whose agent the wizard installed.

## Join the client to the hub

1. On `laptop`, install the client:

   ```bash
   sudo apt install ./neutrino-client_0.5.0_amd64.deb
   ```

1. In the panel, open **Clients** and select **New client link**.
1. Type `laptop` as the name and select **Create link**.
1. Select **Copy**. The link works for five minutes.
1. On `laptop`, run `nclient gui` as yourself, without `sudo`. The **Neutrino client** window opens on **Hubs**.
1. Under **Join a hub**, paste the link into the field and select **Join**.

The new hub row reads **Connected**, with the hub's address and `runs neutrino_hub/0.5.0`.

## Install the file share on studio

1. In the panel, under **Agent**, open **Modules**.
1. Select `studio` among the machines at the top of the page.
1. Select the **File share** tab. If the tab is missing, select **+** beside the tabs and tick **File share**.
1. Select **Install**, and wait until the tab no longer reads **installing**.
1. Select **Configure**. The **Shares** and **Users** sections open under the buttons.

## Add a user and a share

1. Under **Users**, type `alex` as the new user name and a password in the field beside it.
1. Select **Add user**.
1. Select **Apply users**. The row for `alex` reads **ready**.
1. Under **Shares**, select **Add share**.
1. Type `media` in **Name** and `/srv/media` in **Path**.
1. Select **Apply shares**.

The agent creates `/srv/media` on `studio` and publishes it as `media` to every client.

## Mount the share on your laptop

1. In the client window, open **Files**. The `media` entry is listed with the address of `studio`.
1. On the `media` entry, select **Config**.
1. Type `alex` in **Share username** and its password in **Share password**.
1. Leave **Mount path** at its default, `nas/media` under your home folder.
1. Select **Mount**.

The button changes to **Unmount**, and `~/nas/media` on `laptop` shows the files of `/srv/media` on `studio`.
