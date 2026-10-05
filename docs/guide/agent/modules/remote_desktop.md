---
title: Remote desktop
---

# Remote desktop

The **Remote desktop** module shares a managed machine's desktop with the clients of this hub. Its one switch is off on a new machine. The agent's own package carries RustDesk, so there is nothing to install: the switch decides whether the agent's RustDesk runs.

## Share the desktop

1. On the **Remote desktop** tab of the [Modules](../modules.md) page, turn on **Share this machine's desktop**.
1. Select **Apply remote desktop**.
1. In a client, under **Remote desktops**, select **Connect**.

With the switch on, the agent stops every other RustDesk host on the machine and runs its own copy under RustDesk's own service names, so the share comes back after the machine restarts. A RustDesk viewer someone has open on the machine keeps running. The share uses the direct port 21118 and none of RustDesk's servers. RustDesk 1.4.9 asks three public STUN servers (`stun.l.google.com`, `stun.cloudflare.com`, `stun.nextcloud.com`) for the machine's IPv6 address each time its host starts; the request carries no id and registers nothing, and no RustDesk option turns it off. Whose desktop a viewer sees is whoever is signed in at the screen.

The hub generates the seat password the first time the switch goes on and keeps it. The device drawer's **Reset seat password** gives the machine a new one at once and disconnects every viewer.

## Stop sharing

Turn the switch off and select **Apply remote desktop**. The agent's RustDesk stops, and a RustDesk you had installed on the machine before comes back as it was. Uninstalling the agent stops its RustDesk the same way first.

## When it fails

A step that fails shows its code on the tab, and **Apply remote desktop** tries the step again.

| Code                  | Cause                                                             |
| --------------------- | ----------------------------------------------------------------- |
| `rdp_takeover_failed` | a step of starting the agent's RustDesk failed; the step is named |
| `rdp_restore_failed`  | a step of putting back the machine's own RustDesk failed          |

A client's **Connect** is refused while the share has nothing to show:

| Code                     | Cause                                                                          |
| ------------------------ | ------------------------------------------------------------------------------ |
| `rdp_nobody_seated`      | nobody is signed in at the machine's screen                                    |
| `rdp_screen_not_allowed` | a Wayland session has not allowed screen sharing; allow it once at that screen |

On a Mac, the person at the screen grants RustDesk Screen Recording and Accessibility once. The Mac shows a dialog naming both when the switch goes on.
