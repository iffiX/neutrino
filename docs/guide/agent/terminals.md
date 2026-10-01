---
title: Terminals
---

# Terminals

From the **Terminals** page you get a root shell on any managed machine whose agent is online. A shell marked persistent keeps running there after you close the browser, and a shared one opens from every client allowed a terminal on that machine.

![The Terminals page with two shell tabs and the Persistent switch on](/guide/en/terminals_persist.webp)

## Open a shell

1. Under **Which machine**, select a machine.
1. Select **New terminal**.

A tab named after the machine opens with a root shell; on a Windows machine the shell is PowerShell. Keystrokes go to the machine, Escape included. Tabs stay open while you visit other panel pages. The **Terminal** button in a device's drawer on the [Devices](../hub/devices.md) page opens this page on that machine.

## Keep or share a session

Two switches under the shell belong to the tab on show, **Persistent** and **Shared**. Both are off for every new tab. They work only while the tab is connected, with the dot above the shell reading **open**, and only on a session this panel opened. On a session a client opened they are greyed, with **Opened by** and the client's name beside them.

- With **Persistent** on, the shell keeps running on the machine when you close the browser, reload the panel or sign out.
- With **Shared** on, every client allowed a terminal on that machine lists the session and can attach to it. A shared session also keeps running when its last tab closes.
- With both off, the shell ends when its tab closes.

The agent holds every session itself, so restarting or upgrading the agent ends them all.

## Return to a session

The tabs follow the sessions the online machines hold. When the panel loads, the page adds a tab for every session, in the order the sessions were opened. The first tab attaches at once, and the session's last 256 KB of output appears first; another tab attaches when you select it. A session opened later, here or in a client, appears as a new tab.

A tab shows **kept** for a persistent session, **shared** for a shared one, and **2 open** when two windows are attached to it.

A session a client opened and did not share is listed so that you can end it, but the panel does not attach to it. Its tab reads **Opened by** the client **and not shared**.

## Watch one session from several windows

Any number of windows attach to one session at once, from browsers and clients alike, as in tmux. Each shows the same output, keystrokes from any of them reach the shell, and the shell takes the smallest window's columns and rows.

## End a session

- On a tab of this panel's with both switches off, select the × to close the tab and end its shell.
- On any other tab, select the × once to arm it, then again to end the session on the machine. After the first press, the tooltip of the × says the next press ends the session.
- In any tab, run `exit` to end the shell.

## When a tab ends by itself

When a session ends on the machine, by `exit` or from another window, its tab reads **Ended** and keeps its last output. Select the × to close it.

When the line under the shell reads **This session closed. The machine may have stopped answering.**, the tab lost its connection to the machine.
