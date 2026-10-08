---
title: Terminal
---

# Terminal

A terminal opened from the laptop runs on the computer, and the phone picks up the same session with its output still scrolling.

Before you start, finish the [first step](../quick-start.md) with both the phone and the laptop. Each keeps the **Terminals** permission that every client has by default on the panel's **Clients** page.

## Open a terminal on the laptop

1. In the laptop's client window, open **Terminals**.
1. Select your computer in the strip on top.
1. Select **New terminal**.
1. Under the shell, turn on **Persistent** and **Shared**.
1. Run a command that keeps printing, such as `ping localhost` on Linux and macOS, or `ping -t localhost` on Windows.

The tab shows the **kept** and **shared** badges. The shell runs as root, or as SYSTEM on Windows, and the **Terminal** tab on the panel's **Modules** page sets another account.

![A terminal tab with Persistent and Shared on](/guide/en/client_terminal_switches.webp)

## Switch to the phone

1. Close the laptop's client window. The client keeps running in the tray.
1. In the app, open **Terminals**.
1. Select the session's tab.

The phone shows the same session, and the command's output keeps scrolling there.

![The same session in the app](/guide/en/app_terminal.webp)

## Use it from both devices

- On the laptop, select **Open** in the client's tray menu.

The laptop's tab and the phone's tab show the same screen, and keys typed on either reach the shell. When a session closes on its own, [Troubleshooting](../reference/troubleshooting.md) names the cause.

![The session on the laptop again](/guide/en/client_terminal.webp)
