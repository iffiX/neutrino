---
title: Clients
---

# Clients

The client is the program in a person's session that turns what the hub
publishes into buttons: Open, Connect, Config then Apply, Mount, Connect. It
runs on Linux and on Windows.

Seven things to settle first:

- The client is never root. A command run with sudo is refused: "the client
  runs as a person, never as root".
- macOS is refused by name: "the client does not run on macOS yet".
- Windows runs the client and nothing else. There is no Windows hub and no
  Windows agent.
- A client publishes nothing and takes no modules. If you want to manage that
  machine from the hub, it needs an agent, and
  [Devices and remote desktop](./devices-remote-desktop.md) is the page.
- A client link is not a device link. Each is minted on its own page, and the
  other program refuses it.
- `remove` keeps a person's configuration. Only `purge` takes it.
- EasyTier can never ship in the Windows client, because its Windows build
  statically imports Npcap's `packet.dll`.

## Windows msi

Download `neutrino-client-0.2.0-windows-amd64.msi` from
[Releases](https://github.com/iffiX/neutrino/releases) and run it.

Expect: the installer runs through and adds a Start menu entry. There is an
`arm64` msi beside the `x64` one.

![The Windows installer for the Neutrino client, on its confirmation page](/guide/os/win_msi_installer.webp)

::: warning Windows needs WebView2
The window needs Microsoft's WebView2 runtime. Without it the client refuses
with "the window needs {runtime}; install it and try again".

Install the Evergreen WebView2 runtime from Microsoft, then start the client
again. Nothing else about the install has to be repeated.
:::

## Tray and window

Open the client from the Start menu, or run `nclient gui`.

Expect: a window titled "Neutrino client", with a Status section above a
Services section. Before joining, Services reads "Services appear once you join
a hub."

![The Neutrino client in the Windows tray, with its flyout open](/guide/os/win_tray_flyout.webp)

- Closing the window hides it. The client keeps running.
- The tray menu carries "Open" and "Quit". Quit is what stops it.
- `nclient gui --hidden` starts it in the tray with no window at all.

## Linux deb

```bash
sudo apt install ./neutrino-client_0.2.0_amd64.deb
```

Expect: the postinst prints "Neutrino client installed. Open it and join a
hub:" followed by the command to run.

```bash
nclient gui
```

Expect: the window opens. No `sudo` on that line; the client refuses to run as
root.

::: warning
The window on Linux needs WebKitGTK. Without it the client says "the window
needs WebKitGTK; install it: sudo apt install {packages}".

Install the packages it names, then run `nclient gui` again.
:::

## Paste the link

In the panel, open **Clients**, press "New client link", name it `laptop`, and
press "Create link".

Expect: a notice reading "Paste this link into the client program for laptop.",
with the link and a Copy button. It works for five minutes.

![The Clients page with the new client name field and the Create link button](/guide/en/clients_create_link.webp)

![The client enrollment notice with the link and a Copy button](/guide/en/clients_link_notice.webp)

In the client window, paste the link into the field and press "Connect".

Expect: Status turns "Connected" with `hub {version}` beside it, a "Disconnect"
button appears, and five service panels are drawn.

![The client window before connecting, with the empty link field](/guide/en/client_disconnected.webp)

![The connected client window on Linux, with the five service panels](/guide/en/client_connected.webp)

![The same connected client window on Windows](/guide/en/win_client_connected.webp)

The same from a terminal:

```bash
nclient connect 'neutrino://enroll/PLACEHOLDER_LINK'
```

A device link handed to a client is refused with "that link is for a device
agent, not for a client". The Clients page mints client links; the Devices page
mints device links.

The Clients table in the panel lists Name, Hostname, Platform, Status, Version
and Last seen, and each row can be enabled, disabled or deleted. A client the
hub has switched off reads "Switched off by the hub" and every button in its
window greys out.

## Mount to a drive letter or folder

In the Files panel, press "Config".

Expect: on Linux, "Share username", "Share password" and "Mount path", the path
already filled in as `<home>/nas/<share>`. On Windows, a "Drive" field with a
free letter suggested, captioned "Appears as this drive in File Explorer".

![The client's Files panel with the share username, password and mount path](/guide/en/client_files_config.webp)

Press "Mount".

Expect: the button walks through "waiting for the client…" and "mounting…",
then becomes "Unmount".

![The client's Files panel with media mounted and an Unmount button](/guide/en/client_files_mounted.webp)

![The Windows client mounting the media share to drive N:](/guide/en/win_files_drive_letter.webp)

![The media share as drive N: in Windows File Explorer](/guide/os/win_explorer_mapped.webp)

| Refusal           | What the client says                                  |
| ----------------- | ----------------------------------------------------- |
| bad Linux path    | "give a folder under your home, like ~/nas/share"     |
| bad Windows drive | "give an unused drive letter, like N:"                |
| folder occupied   | "that folder is not empty"                            |
| no polkit answer  | "mounting was not authorized on this machine"         |
| no cifs tooling   | "the mount tooling is missing on this machine"        |
| login forgotten   | "the saved login is gone; enter it again with Config" |

The same from a terminal:

```bash
nclient service file config 1 --path ~/nas/media --username alex
```

A port entry forwards to `127.0.0.1:<port>` on this machine, and the row shows
that address while it is forwarding.

## Settings and language

Press "Settings" at the top of the window.

Expect: the "Client settings" dialog, with a Language picker, "Save" and
"Cancel".

![The client settings dialog with the language picker open](/guide/en/client_settings_language.webp)

The language is the client's own, and it does not follow the panel's.

## Disconnect and uninstall

Press "Disconnect" in Status, or run:

```bash
nclient disconnect
```

Expect: the window goes back to "Not connected", and Services reads "Services
appear once you join a hub."

`nclient status` says what this person is bound to, and `nclient quit` stops
the resident, answering "the client is not running" when there is nothing to
stop.

```bash
sudo apt remove neutrino-client
```

Expect: the residents stop and the installed files go. What the people on the
machine kept stays where it is.

```bash
sudo apt purge neutrino-client
```

Expect: the kept configuration goes too.

::: tip
`remove` keeps your configuration; only `purge` takes it. The maintainer
scripts match a resident by its whole command line, so the shell running the
install is never the one asked to quit.
:::

A client newer than the hub refuses to work and names the order: "this client
({client_version}) is newer than the hub ({hub_version}); update the hub
first". A client the hub no longer knows, or whose hub was reset, reads the
cause and then "rejoin by pasting a fresh link from the hub".

That is the whole path: the same window on both machines, joined, mounted and
removed.
