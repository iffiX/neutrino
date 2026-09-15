---
title: Remote desktops
---

# Remote desktops

One button in a **Remote desktops** panel opens another machine's desktop in a viewer, with the password supplied by the hub that published it.

## Where the entries come from

An entry is a desktop a managed machine shares with `sudo nagent rdp start`, described as **shared from** that device. The entry stays while the machine is sharing and online; `sudo nagent rdp stop` on the machine removes it. It appears in the group of the hub that manages the machine. The hub's **Devices** page describes the sharing side.

## Connect

1. In the **Remote desktops** panel, select **Connect**. The button reads **connecting…**, the RustDesk viewer opens on that desktop, and the row reads **viewer open**.

![The Remote desktops panel with a viewer open](/guide/en/client_desktop_connect.webp)

The hub sets the seat password and sends it in the reply to that one press. The viewer signs in with it. The client includes the viewer; the connection is direct, on port 21118 of that machine. From a terminal, `nclient service desktop connect <ref>` opens the same viewer. `<ref>` is the entry's number under its hub in `nclient service list`, or its id, and `--hub` takes the hub's name unless only one is joined.

## When there is no entry

| Symptom                                                   | Cause                                                                                      |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| the panel reads **no remote desktop is shared right now** | no machine is running `nagent rdp start`, or the sharing machine is offline                |
| the hub marks the machine `rdp_nobody_seated`             | nobody is signed in at that machine's screen                                               |
| the hub marks the machine `rdp_screen_not_allowed`        | the Wayland session has not granted screen sharing; the grant is given once at that screen |
| **Connect** is rejected with `rdp_no_address`             | the machine published no address the client reaches                                        |
| **Connect** is rejected with `rdp_no_desktop`             | this session has no screen to open a viewer on                                             |
