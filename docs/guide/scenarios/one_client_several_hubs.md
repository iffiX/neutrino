---
title: One client, several hubs
---

# One client, several hubs

Your laptop or phone joins a second hub here, such as a hub at the office beside the one at home, and then lists the services of both side by side. Each hub keeps its own name, its own way in, its own permissions for this client and its own panel.

## Before you start

- Each hub has done the [Step zero](../quick-start.md) on its own box.
- The client is installed and joined to the first hub, as [Install a client](../install/client.md) describes.

## Name each hub

The client titles each hub's row with the hub's name, which starts as the box's hostname. On each hub whose name is unclear:

1. In the hub's panel, open **Settings**.
1. Under **Hub name**, type a name in **Name**, such as `office`.
1. Select **Apply name**.

## Make a link on the second hub

1. In the second hub's panel, open **Clients**.
1. Select **New client link**.
1. Type a name for the device.
1. Select **Create link**.

The link is valid for 30 minutes. After the join, this hub's **Clients** page alone sets what the client can use here.

## Join the second hub

### On a computer

1. In the client window, open **Hubs**.
1. Paste the link into the field of the **Join a hub** row.
1. Select **Join**.

### On a phone

1. In the app, on **Hubs**, select **Join a hub**.
1. Point the camera at the QR code on the second hub's **Clients** page.

## Read the Hubs page

**Hubs** has one row per hub, titled with its name. Each row reads **Connected ·** with the way the client reached that hub, **LAN**, **Direct**, **NetBird**, **EasyTier** or **SSH Relay**, and the round trip in milliseconds.

The client picks the way for each hub separately, so `hub` can read **Connected · LAN** while `office` reads **Connected · NetBird**. A hub reached over the LAN, through Direct or through the SSH Relay works while its virtual network is off.

![The Hubs page with two hub rows, one reached over the LAN and one through NetBird](/guide/en/client_hubs_two.webp)

## Find each hub's services

**Web**, **Ports**, **AI**, **Files**, **Terminals** and **Remote desktops** list the entries of every connected hub, in the order of the rows on **Hubs**. Each entry has a line that names its hub and machine, such as **from hub:server:Gitea**.

A hub that is not connected takes one row there, with its name and state line, until it connects.

On **Terminals**, the strip at the top holds the machines of every connected hub, and the line under it names the picked machine's hub.

On Windows, a drive letter on **Files** keeps naming the same machine of the same hub.

## Switch virtual networks

On a computer, each hub's **Virtual network** line connects separately, and the lines of several hubs can be on at once. The computer is on one NetBird network at a time, and on one EasyTier console at a time. **Connect** on a second one fails, with a line under it saying the computer is on another virtual network.

A phone is on one hub's virtual network at a time. While one is on, **Connect** on every other hub's line is greyed. To move the phone to the other hub's network:

1. On the first hub's row, select **Disconnect** on the **Virtual network** line.
1. On the second hub's row, select **Connect**.

The first hub stays connected through any other way in it has, such as Direct or the SSH Relay.

## Choose the AI gateway

On a computer, **AI** has one entry for each hub with an AI gateway. Select **The AI tools use this gateway** on the hub you want; the switch on the other entry turns off.

That hub's row on **Hubs** then reads **The AI tools point at this hub**. On a phone, each gateway has its own **Connect**, as [Android app](../client/android.md) describes.

## Open each hub's panel

**Panel** on a row opens that hub's panel in the browser, signed in. The button appears only when that hub's **Clients** page gives this client **Hub panel without the password**.

On Linux and Windows, each hub's panel opens at its own `.localhost` name, so the two sign-ins stay apart. On macOS both panels open on `127.0.0.1`, and signing in to one can sign out the other; **Panel** signs in again.<!-- 待核 -->

## Leave one hub

1. On the row of the hub to leave, select **Leave**.
1. Select **Press again to leave**.

The row goes, and the client stops that hub's forwards, mounts and viewers. Its virtual network goes off unless another hub uses the same network.

In a terminal, `leave`, `terminal` and the `service` subcommands take `--hub` with the hub's name while several hubs are joined, as [nclient commands](../commands/nclient.md) lists.

When a row reads anything but **Connected**, [The state line of a hub row](../reference/troubleshooting.md#the-state-line-of-a-hub-row) lists each line with its fix.
