---
title: Terminals
---

# Terminals

From the **Terminals** page you get a root shell on any managed machine whose agent is online. A shell marked persistent keeps running there after you close the browser.

![The Terminals page with two shell tabs and the Persistent switch on](/guide/en/terminals_persist.webp)

## Open a shell

1. Under **Which machine**, select a machine.
1. Select **New terminal**.

A tab named after the machine opens with a root shell; on a Windows machine the shell is PowerShell. Keystrokes go to the machine, Escape included. Tabs stay open while you visit other panel pages. The **Terminal** button in a device's drawer on the [Devices](../hub/devices.md) page opens this page on that machine.

## Keep a session after you leave

The **Persistent** switch under the shell belongs to the tab on show. It is off for every new tab. It works only while the tab is connected, with the dot above the shell reading **open**.

- With **Persistent** on, the shell keeps running on the machine when you close the browser, reload the panel or sign out.
- With **Persistent** off, the shell ends when its tab closes.

The agent holds every session itself, so restarting or upgrading the agent ends them all.

## Return to a kept session

When the panel loads, the **Terminals** page adds a tab for each persistent session on every online machine, in the order the sessions were opened. Sessions kept from a desktop or Android client appear in the same list.

A returned tab reads **This session is kept on the machine** until you select it. Selecting it attaches the tab, and the session's last 256 KB of output appears first.

## End a session

- On a tab with **Persistent** off, select the × to close the tab and end its shell.
- On a tab with **Persistent** on, select the × once to arm it, then again to end the session on the machine. After the first press, the tooltip of the × says the next press ends the session.
- In any tab, run `exit` to end the shell and close the tab.

## When a tab closes by itself

A session has one viewer at a time. When the same session opens in another browser or in a client, this tab closes with `session_taken`. The line under the shell then reads **This terminal was opened somewhere else, so it closed here.** To take a persistent session back, reload the page and select its tab.

When the line under the shell reads **This session closed. The machine may have stopped answering.**, the tab lost its connection to the machine.
