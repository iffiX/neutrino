---
title: The window
---

# The window

The window, titled **Neutrino client**, has a sidebar on the left and shows one page at a time on the right. This page names every page and what each row on it does.

## The sidebar and the head

The sidebar lists **Hubs**, **Web**, **Ports**, **AI**, **Files**, **Terminals** and **Remote desktops**, and its foot names this computer, its platform and the client's version. The head over the page holds the page's name, the **↻** button and **Settings**. The **↻** button sends every connected hub a report and starts a connection round on every hub whose channel is down. **Settings** opens the client's own settings.

## The Hubs page

Each row holds one hub: its name, its state, its address and the package the hub runs. The dot before the name is coloured by the hub's state.

| The dot        | Meaning                                                                                       |
| -------------- | --------------------------------------------------------------------------------------------- |
| green          | the channel is open                                                                           |
| amber, turning | the client is reconnecting to a hub it reached before                                         |
| amber          | the hub is out of reach and nothing is broken, such as `hub_unreachable` or `client_disabled` |
| red            | a person has to change something, such as `hub_untrusted` or `binding_unknown`                |
| grey           | the hub has not been reached yet                                                              |

A row whose hub publishes a virtual network has a **Virtual network** button with its state and this computer's address on it. Selecting it joins or leaves that network, as [Virtual networks](./overlay.md) describes. Each row also has **Leave**, and a row reading **Replaced by another client** has **Reconnect**. The **Join a hub** row under them takes a link from any hub's **Clients** page.

**Leave** removes that hub's row at once and undoes what it published on this computer: its mounts, forwards, viewers and a virtual network no other hub names.

## A service page

**Web**, **Ports**, **AI**, **Files** and **Remote desktops** each show one panel with every hub's entries of that kind, hub by hub in the order the hubs were joined. Under its address, each entry names the hub and the machine it comes from, such as **from Neutrino:Argon**. A hub older than 0.4.0 names no machine, and the entry shows the machine's address in its place.

An entry the hub cannot reach right now is greyed and reads **not reachable now**. A hub that is not connected takes one greyed row with its state. A panel with no entry at all reads a line such as **no port is published**.

## The AI page

Each hub's gateway is one entry with a **The AI tools use this gateway** switch, and one switch at most is on. Switching an entry on makes its hub the target and points the tools at its gateway; the other switch goes off. Switching the one in use off puts the tools back as they were. Only a connected hub takes the switch, and a hub whose channel is down is rejected with `no_exit_hub`. **Config** picks the models, as [AI](./ai.md) describes.

## The Terminals page

The strip on top lists every machine the connected hubs offer a terminal on, each with a dot that is green while the machine is online. **New terminal** opens a shell on the picked machine in a tab under the strip, as [Terminals](./terminals.md) describes.

## Settings

1. Select **Settings** in the head.
1. In the **Client settings** dialog, pick the **Language** and the **Theme**.
1. Select **Save**.

The language and theme are the client's own; the panel's are set on the hub.

## The tray

Closing the window hides it, and the client keeps running with every hub joined. **Open** in the tray icon's menu shows the window again, and **Quit** stops the client. `nclient gui --hidden` starts the client in the tray, and `nclient quit` stops it from a terminal.

## What a refusal does to the binding

A refusal keeps the binding: the row stays, shows the code, and the client opens the channel again a minute later. One code ends the binding, and the row goes with it.

| The row shows      | What the code means                                              | The binding                                    |
| ------------------ | ---------------------------------------------------------------- | ---------------------------------------------- |
| `protocol_too_old` | this client speaks an older protocol number than the hub accepts | stays; install a newer client                  |
| `protocol_too_new` | this client speaks a newer protocol number than the hub speaks   | stays; upgrade that hub first                  |
| `hub_untrusted`    | the certificate at that address is not the one the link pinned   | stays; a hub that was reset takes a fresh link |
| `binding_unknown`  | that hub's **Clients** page no longer holds this client          | goes; a fresh link joins again                 |
