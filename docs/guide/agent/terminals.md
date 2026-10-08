---
title: Terminals
---

# Terminals

On the **Terminals** page you open a shell on any managed machine whose agent is online. A session you keep goes on running after you close the browser, and you can return to any session the machines hold.

![The Terminals page with two shell tabs and the Persistent switch on](/guide/en/terminals_persist.webp)

## Open a shell

1. Under **Which machine**, select a machine.
1. Select **New terminal**.

A tab named after the machine opens a shell there. The shell runs as the account the machine's [Terminal](./modules/terminal.md) module names. With no account named, the shell runs as root on Linux and macOS. On Windows the shell is always PowerShell running as SYSTEM.

Keystrokes go to the machine, Escape included. Tabs stay open while you visit other panel pages. On the [Devices](../hub/devices.md) page, the **Terminal** button in a device's drawer opens this page on that machine.

## Keep or share a session

Two switches under the shell, **Persistent** and **Shared**, belong to the tab on show. Both are off on every new tab. They work only while the tab is connected, and only the side that opened the session can change them. On a session somebody else opened, the switches are greyed, with **Opened by** and the opener's name beside them.

| Switches          | What happens to the session                                                                                                     |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **Persistent** on | the shell keeps running on the machine after you close the browser, reload the panel or sign out                                |
| **Shared** on     | every client with terminal rights on that machine lists the session and can attach to it; the session outlasts its last tab too |
| both off          | the shell ends when its tab closes                                                                                              |

The agent holds every session itself, so a restart or an upgrade of the agent ends them all.

## Return to a session

When the panel loads, the page adds a tab for every session the online machines hold, in the order the sessions were opened. The first tab attaches at once and shows the session's last 256 KB of output first. Any other tab attaches when you select it. A session opened later, here or in a client, appears as a new tab.

A tab shows **kept** for a persistent session, **shared** for a shared one, and **2 open** while two windows are attached to it.

The panel attaches to any session, including one a client opened and did not share. A client attaches only to its own sessions and to shared ones. When the opener turns **Shared** off, every other client attached to the session is disconnected at once with `session_not_owned`.

## Watch one session from several windows

Any number of windows attach to one session at once, from browsers and clients alike, as in tmux. Each window shows the same output, and keystrokes from any of them reach the shell. The shell takes the columns and rows of the smallest window.

## End a session

- On a tab this panel opened, with both switches off, select the × to close the tab and end its shell.
- On any other tab, select the × to arm it, then select it again to end the session on the machine. Between the two presses, the tooltip of the × says the next press ends the session.
- In the shell, run `exit`.

## When a tab ends by itself

When a session ends on the machine, by `exit` or from another window, its tab reads **Ended** and keeps its last output. Select the × to close it.

When the line under the shell reads **This session closed.**, the tab lost its connection to the machine.
