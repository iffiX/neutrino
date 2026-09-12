---
title: Quick start
---

# Quick start

This walk takes about half an hour. At the end, a hub in server mode runs on one Linux box and a second Linux machine reports to it as a managed device. A share from the hub box is mounted on your laptop.

## What you need

- A Linux box for the hub, `home-hub` in the screenshots. It is x86-64, runs Debian 12 or newer or Ubuntu 24.04 or newer, and has root and a route to the internet.
- A second Linux machine of the same family to manage, `studio` in the screenshots.
- A computer with a desktop session for the client, `laptop` in the screenshots.
- The three package files of one release from the [releases page](https://github.com/iffiX/neutrino/releases): `neutrino-hub_0.2.0_amd64.deb`, `neutrino-agent_0.2.0_amd64.deb` and `neutrino-client_0.2.0_amd64.deb`.

The three machines are on one network. Server mode keeps every address the hub box has, and the rest of the network stays as it is.

## Install the hub and set it up

On `home-hub`, install the package:

```bash
sudo apt install ./neutrino-hub_0.2.0_amd64.deb
```

Then run the setup wizard:

1. Run `sudo nhub setup`. The terminal prints an address with a one-time token. On a box that has a browser, the wizard opens in it.
1. Open the printed address in a browser on the same network.
   ![The setup wizard's welcome screen](/guide/en/setup_welcome.webp)
1. Select **Set this box up**.
1. On **Language**, pick **English**.
1. On **A password for the panel, a passphrase for the vault**, type a **Panel password** and a **Vault master passphrase**.
1. On **What is this machine for?**, pick **Server**, the shape that keeps every address the box has.
   ![The shape screen with Server picked](/guide/en/setup_shape.webp)
1. On **Which ports?**, keep **Panel answers on port** at `8080`.
1. On **Going out through a proxy**, leave **Set it up here** off.
1. On **Ready**, read the summary and confirm it.
   ![The review screen before confirming](/guide/en/setup_review.webp)

**Next** moves to the following screen. Nothing is written until **Ready** is confirmed. The steps then run on the screen, from checking packages to installing this machine's own agent, and end with **This box is a gateway**.

![The done screen with the Open the panel button](/guide/en/setup_done.webp)

::: warning
The vault passphrase seals every credential the box holds, and a restore from backup requires it again. Keep it somewhere off the box.
:::

## Sign in

1. Open `http://<hub>:8080`, where `<hub>` is the address of the box.
   ![The sign-in page](/guide/en/login.webp)
1. Type the panel password and select **Sign in**.

The **Dashboard** opens, with a sidebar in two groups, **Hub** and **Agent**.

![The Dashboard after the first sign-in](/guide/en/dashboard.webp)

## Add a second machine

1. Open **Devices** in the panel.
1. Select **Add by link**. A notice shows a `neutrino://enroll/` link, valid for five minutes, with a **Copy** button.
   ![The enrollment link notice](/guide/en/devices_enroll_link.webp)
1. On `studio`, run `sudo apt install ./neutrino-agent_0.2.0_amd64.deb`.
1. On `studio`, run `sudo nagent connect '<link>'`, where `<link>` is the copied link.

`studio` appears under **Managed devices** within seconds, next to `home-hub`, which the setup wizard enrolled.

![Managed devices with both machines](/guide/en/devices_managed.webp)

## Install the client

1. In the panel, open **Clients**.
1. Select **New client link**.
   ![The new client link form](/guide/en/clients_create_link.webp)
1. Type `laptop` as the name and select **Create link**. The notice shows the link and a **Copy** button; the link is valid for five minutes.
1. On `laptop`, run `sudo apt install ./neutrino-client_0.2.0_amd64.deb`.
1. On `laptop`, run `nclient gui` as yourself, without `sudo`. The window opens with **Not connected** and a field for the link.
   ![The client window before joining](/guide/en/client_disconnected.webp)
1. Paste the link into the field and select **Connect**.

The status card reads **Connected** with the hub's version, and the **Services** section draws five panels: **Web**, **Ports**, **AI**, **Files** and **Remote desktops**.

![The client window connected](/guide/en/client_connected.webp)

## Publish a share and mount it

1. Under **Agent** in the panel's sidebar, open **Samba**.
1. Under **Enabled devices**, tick `home-hub` and select **Apply devices**. A consent dialog names what is installed on the box; confirm it.
1. Under **Users**, select **Add user**, type `alex` as the name and a password, and select **Apply users**.
1. Under **Shares**, select **Add share**, name it `media` with a **Path** on the box, and select **Apply shares**.
   ![The Samba page with the media share](/guide/en/samba_share.webp)
1. Open **Services**. `media` is listed under **Files**, published by the samba module on `home-hub`.
   ![The Services page listing the share](/guide/en/services_list.webp)
1. On `laptop`, in the client's **Files** panel, select **Config**.
1. Type `alex` as **Share username** and its password as **Share password**, and keep the **Mount path** at `~/nas/media`.
   ![The Files panel's config form](/guide/en/client_files_config.webp)
1. Select **Mount**.

The button reads **Unmount**, and the share is at `~/nas/media` on `laptop`.

![The Files panel with the share mounted](/guide/en/client_files_mounted.webp)
