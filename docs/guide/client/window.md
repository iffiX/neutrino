---
title: The window
---

# The window

The window, titled **Neutrino client**, has a bar of tabs along its top and shows one tab at a time. This page names every tab and what each row in it does.

## The top bar

The bar names this computer, its platform and the client's version. Its tabs are **Hubs**, **Web**, **Files**, **Ports**, **Remote desktops**, **AI** and **Terminals**. The **↻** button sends every connected hub a report and starts a connection round on every hub whose channel is down. **Settings** opens the client's own settings.

## The Hubs tab

Each row holds one hub: its name, its state, its address and the package the hub runs. The dot before the name is coloured by the hub's state.

| The dot        | Meaning                                                                                       |
| -------------- | --------------------------------------------------------------------------------------------- |
| green          | the channel is open                                                                           |
| amber, turning | the client is reconnecting to a hub it reached before                                         |
| amber          | the hub is out of reach and nothing is broken, such as `hub_unreachable` or `client_disabled` |
| red            | a person has to change something, such as `hub_untrusted` or `binding_unknown`                |
| grey           | the hub has not been reached yet                                                              |

A row whose hub publishes a virtual network has a **Virtual network** button with its state and this computer's address on it. Selecting it joins or leaves that network, as [Virtual networks](./overlay.md) describes. Each row also has the **Target** radio and **Leave**, and a row reading **Replaced by another client** has **Reconnect**. The **Join a hub** row under them takes a link from any hub's **Clients** page.

**Leave** removes that hub's row at once and undoes what it published on this computer: its mounts, forwards, viewers and a virtual network no other hub names.

## The target hub

One hub of those joined is the target, and your AI tools point at its gateway. The **Target** radio makes that hub the target. Only a connected hub takes the radio; one whose channel is down is rejected with `no_exit_hub`. The [AI page](./ai.md) covers what the tools are pointed at.

## A service tab

**Web**, **Files**, **Ports**, **Remote desktops** and **AI** each show one column per hub, two side by side where the window is wide enough. A column lists that hub's entries of the kind, or a line such as **no port is published**. An entry the hub cannot reach right now is greyed and reads **not reachable now**. A hub that is not connected shows its state in place of its entries.

## The Terminals tab

Each hub's column lists the machines it offers a terminal on. **Open terminal** opens this computer's own terminal program with a shell on that machine, as [Terminals](./terminals.md) describes. The button is grey while the machine is offline.

## Settings

1. Select **Settings** in the top bar.
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
