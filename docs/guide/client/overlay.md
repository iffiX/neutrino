---
title: Virtual networks
---

# Virtual networks

Joining a hub's virtual network puts this computer on the hub's NetBird or EasyTier network as an ordinary peer. The hub is then reachable at its address on that network from anywhere this computer has internet.

## Before you join

- The client package is installed, which registers two system services: the NetBird daemon and the client's own EasyTier daemon.
- A NetBird client already installed on this computer is left alone: on Windows the two daemons run side by side on their own pipes, on macOS the client uses the installed daemon and its own stays off, and on Linux the package does not install next to it.
- The hub runs NetBird or EasyTier. For NetBird its **Overlay** page holds a saved setup key; EasyTier runs either as a manual network or from an EasyTier console account.
- The hub's **Clients** page lets this client use the virtual network.

When any of these is missing, the hub row shows no **Virtual network** button.

## Join and leave

1. Open the **Hubs** tab.
1. Select **Virtual network** on the hub's row.

The same two steps join on Linux, Windows and macOS alike. The EasyTier daemon runs as root, or as SYSTEM on Windows, and writes the network's configuration itself. Select the button again to leave.

## Networks from an EasyTier console

A hub whose EasyTier runs from an EasyTier console hands the client the console's address. Joining starts EasyTier on this computer against that console, and the console assigns the network, the address and the computer's name. This computer holds one console at a time, alongside any number of manual EasyTier networks.

## What the button shows

The button reads **Virtual network**, the state, and this computer's address once the network assigns one.

| State                      | Meaning                                                   |
| -------------------------- | --------------------------------------------------------- |
| **off**                    | this computer is not on the network                       |
| **joining…**, **leaving…** | a step is running; the button is grey                     |
| **on**                     | this computer is on the network                           |
| **failed**                 | the last step failed; the code shows under the hub's name |

| Code                      | Meaning                                                                                      |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| `overlay_other_network`   | NetBird is on another network, or EasyTier holds another hub's console; leave that one first |
| `overlay_daemon_down`     | the NetBird or EasyTier daemon is not running; reinstall the client                          |
| `bundle_missing`          | this install has no NetBird or EasyTier; reinstall the client                                |
| `overlay_join_failed`     | NetBird rejected the join, with its own words after the code                                 |
| `overlay_console_invalid` | the hub's EasyTier console address is not one EasyTier accepts                               |

## Two hubs on one network

Two hubs that name the same NetBird management server, the same EasyTier network, or the same EasyTier console share one membership, and both rows show the same state. Leaving one of those hubs keeps the network; leaving the last one leaves it.

## After the client quits

The daemons keep this computer on the network after the client quits. After a restart, NetBird and EasyTier rejoin by themselves on every platform, with no client running. Select the button, or leave the hub, to take the computer off.
