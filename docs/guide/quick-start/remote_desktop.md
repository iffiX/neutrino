---
title: Remote desktop
---

# Remote desktop

One switch in the panel shares the computer's desktop, and the phone or the laptop then shows that desktop in a viewer and controls it.

Before you start, finish the [Step zero](../quick-start.md), and keep somebody signed in at the computer's screen. The viewer shows that person's desktop.

## Share the computer's desktop

1. On the panel's **Modules** page, select your computer under **Which machine**.
1. Select the **Remote desktop** tab.
1. Turn on **Share this machine's desktop**.
1. Select **Apply remote desktop**.

![The Remote desktop tab with the desktop shared](/guide/en/modules_remote_desktop_tab.webp)

The agent on the computer includes RustDesk, so nothing downloads. On macOS, the computer's screen then shows a dialog that names RustDesk's two permissions. In **System Settings** > **Privacy & Security**, turn on RustDesk under **Screen Recording** and under **Accessibility**. If the tab shows a code after that, select **Apply remote desktop** again. On Linux with a Wayland session, allow the screen sharing once at the computer's screen.

## Connect

1. In the app or the laptop's client window, open **Remote desktops**.
1. On your computer's row, select **Connect**.

![Your computer's row on the laptop's Remote desktops page](/guide/en/client_remote_desktops.webp)

The viewer shows the computer's desktop, at home or, over NetBird, from outside. On the phone, three round buttons at its top right raise the keyboard, show a bar of special keys, and end the session.

![The computer's desktop in the app's viewer](/guide/en/app_rdp_viewer.webp)

When **Connect** shows a code in place of the viewer, [Troubleshooting](../reference/troubleshooting.md#a-remote-desktop-does-not-open) lists its cause.
