---
title: Virtual networks
---

# Virtual networks

Joining a hub's virtual network puts this computer on the hub's NetBird or EasyTier network as an ordinary peer. The hub is then reachable at its address on that network from anywhere this computer has internet.

## Before you join

- The client package is installed, which registers the NetBird and EasyTier daemons as system services.
- The hub runs NetBird or EasyTier, and for NetBird its **Overlay** page holds a saved setup key.
- The hub's **Clients** page lets this client use the virtual network.

When any of these is missing, the hub row shows no **Virtual network** button.

## Join and leave

1. Open the **Hubs** tab.
1. Select **Virtual network** on the hub's row.
1. Approve the system prompt, if one opens.

The prompt opens for EasyTier on Linux and macOS, where its configuration is written as root. NetBird and EasyTier on Windows open none. Select the button again to leave.

## What the button shows

The button reads **Virtual network**, the state, and this computer's address once the network assigns one.

| State                      | Meaning                                                   |
| -------------------------- | --------------------------------------------------------- |
| **off**                    | this computer is not on the network                       |
| **joining…**, **leaving…** | a step is running; the button is grey                     |
| **on**                     | this computer is on the network                           |
| **failed**                 | the last step failed; the code shows under the hub's name |

| Code                     | Meaning                                                              |
| ------------------------ | -------------------------------------------------------------------- |
| `overlay_other_network`  | NetBird on this computer is on another network; leave that one first |
| `overlay_not_authorized` | the system prompt was declined                                       |
| `overlay_daemon_down`    | the NetBird daemon is not running; reinstall the client              |
| `bundle_missing`         | this install has no NetBird or EasyTier; reinstall the client        |
| `overlay_join_failed`    | NetBird rejected the join, with its own words after the code         |

## Two hubs on one network

Two hubs that name the same NetBird management server, or the same EasyTier network, share one membership, and both rows show the same state. Leaving one of those hubs keeps the network; leaving the last one leaves it.

## After the client quits

The daemons keep this computer on the network after the client quits. After a restart, NetBird rejoins by itself, and so does EasyTier on Linux and macOS; on Windows EasyTier rejoins once the client runs. Select the button, or leave the hub, to take the computer off.
