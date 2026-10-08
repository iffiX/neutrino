---
title: Remote desktop
---

# Remote desktop

One switch on the **Remote desktop** tab shares a managed machine's desktop with the clients of this hub. The switch is off on a new machine. The agent's own package includes RustDesk, so the module has nothing to install. When the switch is on and applied, the machine is listed on each client's **Remote desktops** page, and **Connect** shows its desktop.

## Share the desktop

1. On the **Remote desktop** tab of the [Modules](../modules.md) page, turn on **Share this machine's desktop**.
1. Select **Apply remote desktop**.
1. In a client, under **Remote desktops**, select **Connect**.

![The Remote desktop tab with Share this machine's desktop on and applied](/guide/en/modules_remote_desktop_tab.webp)

With the switch on, the agent stops every other RustDesk host on the machine. It then runs its own copy under RustDesk's own service names, so the share comes back after the machine restarts. A RustDesk viewer someone has open on the machine keeps running.

The share uses the direct port 21118 and none of RustDesk's servers. Each time its host starts, RustDesk 1.4.9 asks three public STUN servers (`stun.l.google.com`, `stun.cloudflare.com`, `stun.nextcloud.com`) for the machine's IPv6 address. The request holds no id and registers nothing, and no RustDesk option turns it off.

A viewer sees the desktop of whoever is signed in at the machine's screen. The tab reads **running** while the agent's RustDesk service runs, whether anybody is signed in or not. With nobody at the screen, a client's **Connect** is rejected with `rdp_nobody_seated`.

On a Mac, the person at the screen grants RustDesk **Screen Recording** and **Accessibility** one time. When the switch goes on, the Mac shows a dialog that names both.

## Stop sharing

Turn the switch off and select **Apply remote desktop**. The agent's RustDesk stops, and a RustDesk you had installed on the machine before comes back as it was.

The agent stops its RustDesk the same way, at once and whatever the switch says, in these cases:

- the agent is uninstalled;
- the machine leaves the hub;
- the machine is removed on the **Devices** page.

## When it fails

A step that fails shows its code on the tab, and **Apply remote desktop** tries the step again.

| Code                  | Cause                                                             |
| --------------------- | ----------------------------------------------------------------- |
| `rdp_takeover_failed` | a step of starting the agent's RustDesk failed; the step is named |
| `rdp_restore_failed`  | a step of putting back the machine's own RustDesk failed          |

A client's **Connect** is rejected while the share has nothing to show:

| Code                     | Cause                                                                          |
| ------------------------ | ------------------------------------------------------------------------------ |
| `rdp_nobody_seated`      | nobody is signed in at the machine's screen                                    |
| `rdp_screen_not_allowed` | a Wayland session has not allowed screen sharing; allow it once at that screen |
