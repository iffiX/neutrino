---
title: Settings
---

# Settings

The **Settings** page runs the panel itself: whether it speaks HTTPS, its password, language and theme, the configuration backup, and updates of the hub. The commands that reset the box from a terminal are at the end of this page.

## HTTPS

The panel speaks HTTP or HTTPS on its one port. Under HTTPS, the panel's certificate is signed by a certificate authority this hub makes for itself. A browser that has installed that authority opens the panel with no warning.

`nhub setup` has a switch for HTTPS and makes the authority either way. The **HTTPS** section switches the scheme later, and it offers the authority to install whether HTTPS is on or off.

### Install the authority

Install the authority on each device before you turn HTTPS on, and the first HTTPS page loads with no warning. Under **HTTPS**, select **Install certificate**. The browser downloads `neutrino-<hub>-ca.crt`, where `<hub>` is this hub's name, and the steps for the device in front of you open beneath the button.

| System          | Steps after the download                                                                                                                                    |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Windows         | Open the file, choose **Install Certificate** and **Local Machine**, place it in **Trusted Root Certification Authorities**, then restart the browser.      |
| macOS           | Open the file to add it to the login keychain. In Keychain Access, open the Neutrino authority and set **When using this certificate** to **Always Trust**. |
| Linux, Chrome   | Open `chrome://certificate-manager`, import the file under **Custom** as trusted for websites, then restart Chrome.                                         |
| Linux, Firefox  | Open **Settings** > **Privacy & Security** > **View Certificates**, import the file on **Authorities**, and tick **Trust this CA to identify websites**.    |
| Android         | Open **Settings** > **Security** > **Encryption & credentials** > **Install a certificate** > **CA certificate**, then pick the file.                       |
| iPhone and iPad | Download the file in Safari, install the profile under **Settings**, then turn on full trust in **General** > **About** > **Certificate Trust Settings**.   |

On macOS, you confirm the trust setting with your password when you close the certificate window.

![The Keychain Access trust dialog set to Always Trust](/guide/os/os_mac_keychain_trust.webp)

### Turn HTTPS on

- Under **HTTPS**, select **Turn HTTPS on**.

The panel restarts on HTTPS at the same host and port, and the page moves to the `https://` address within eight seconds. **Turn HTTPS off** moves it back to HTTP the same way.

![The HTTPS section with HTTPS on and its status lines](/guide/en/settings_https_on.webp)

The certificate names the box's private and overlay addresses, `127.0.0.1`, `localhost`, the box's host name and `hub.neutrino.internal`. A browser that opens the panel at a public address warns even with the authority installed.

### Read the status lines

| Line                       | What it shows                                                    |
| -------------------------- | ---------------------------------------------------------------- |
| **Scheme**                 | HTTP or HTTPS                                                    |
| **Authority SHA-256**      | the authority's fingerprint, to compare with what a device shows |
| **Authority created**      | when the authority was made                                      |
| **Certificate names**      | every address and name the panel's certificate covers            |
| **Certificate issued**     | when the current certificate was signed                          |
| **Certificate expires**    | when it runs out                                                 |
| **Last automatic renewal** | the last time the hub signed a new certificate by itself         |

The hub signs a new certificate when the box's addresses change and 30 days before the old one expires. A browser that trusts the authority accepts each new certificate.

### Regenerate the authority

**Regenerate certificate** replaces the authority and the certificate after a confirmation. Every browser that installed the old authority warns again until it installs the new one. The authority is part of `config/`, so a restored backup keeps the one browsers already trust.

## Hub name, password, language and theme

| Section            | Fields                                                           | Button              |
| ------------------ | ---------------------------------------------------------------- | ------------------- |
| **Hub name**       | **Name**, the name every joined client shows this hub under      | **Apply name**      |
| **Panel password** | **Current password**, **New password**, **Confirm new password** | **Change password** |
| **Language**       | **Language**, the language the panel is drawn in                 | **Apply language**  |
| **Appearance**     | **Theme**: **System**, **Dark** or **Light**                     | **Apply theme**     |

Other sessions stay signed in after a password change. **System** takes the color scheme from the browser. The desktop client has a language and a theme of its own.

## Back up the configuration

Under **Configuration archive**, select **Download backup**. The browser saves a `.tar.gz` of the whole of `config/`.

The credentials inside are sealed under the vault master passphrase. Everything else in the archive is readable by whoever holds the file. The archive holds configuration only: share contents, Gitea repositories, container volumes and ZFS datasets stay on their machines.

## Restore a backup

1. Under **Configuration archive**, select **Restore from file** and pick the archive.
1. In the dialog, fill **Vault master password** with the passphrase of the vault the backup was taken from.
1. Select **Restore**.

The archive's files replace every file under `config/`, the hub applies them, and the panel restarts. The page reloads by itself; sign in with the restored password.

The hub rejects a file that is not a `.tar.gz` with `backup_wrong_extension`. It rejects a damaged archive with `backup_corrupt` and a wrong passphrase with `vault_passphrase_wrong`, and restores nothing in either case. When the apply stops short, the files stay restored; fix the cause the dialog names, then run `sudo nhub apply`.

The agents and clients connect again by themselves. On a different box, each AI subscription account signs in again, because those sign-ins are kept outside `config/`.

## Update the hub

**Update** installs a newer release of the hub on the box it runs on.

1. Under **Update**, select **Check for updates**. The section shows the newest release with its date, size, **Release notes**, and the disk room it needs against what is free.
1. Select **Install** followed by the version, then confirm.

![The Update section showing a newer release](/guide/en/settings_update.webp)

The panel downloads the package and checks it against the release's `SHA256SUMS`. A systemd unit, `neutrino_hub_update`, then installs it outside the panel. The page returns to the sign-in, and afterwards the section names the old version, the new one and the date.

For up to three minutes after the install, the unit checks that the panel returns a page and that the routing services are running. When they fail the check, the unit installs the previous version again, and the section names the reason and shows the **Install log**. The confirmation states beforehand when no previous package exists to fall back on.

When the box has less than 300 MB of memory available, the unit stops the panel and the AI gateway before unpacking. It starts them again afterwards. After the check passes, the unit reinstalls the hub box's own agent from the new hub. Agents on other machines update themselves from the new hub when the hub still admits their protocol.

A new major version is not installed from here, because a major changes the shape of `config/`. A hub run from a source checkout shows **This hub runs from a checkout; update it with git.**

`sudo nhub update` does the same from a terminal and prompts for confirmation before it installs. `--yes` skips the question, and `--package` installs a package file you downloaded yourself. The unit's log is in `journalctl -u neutrino_hub_update`.

## Upgrade from 0.4

The hub, the agent and the client share one version number, and 0.5.0 speaks protocol 3 only. The hub rejects a 0.3 or 0.4 agent or client with `protocol_too_old`, which means its protocol number is below the hub's lowest. Those peers keep their binding but do not update themselves from the hub. Upgrade in this order:

1. On the hub box, install 0.5.0 from **Update**, with `sudo nhub update`, or with the hub package as in [Install the hub](./install.md).
1. If the hub box's own device is **Offline** on [Devices](./devices.md), install the 0.5.0 agent package on the hub box with `apt` or `dnf`.
1. For each Linux machine the hub reaches over SSH, select **Reinstall agent** in its drawer and complete the SSH dialog.
1. On each other Linux machine, install the 0.5.0 agent package with `apt` or `dnf`.
1. On each Windows machine, run the 0.5.0 agent `.msi`.
1. On each Mac, install the 0.5.0 agent `.pkg`.
1. On each person's computer, install the 0.5.0 client package, and on each phone, install the Android app.

Each agent and client connects again with the binding it had. One that stays rejected joins with a fresh link from **Devices** or **Clients**.

## Reset from a terminal

| Command                    | What it does                                                                                                                             |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `sudo nhub reset password` | sets a new panel password and signs every session out                                                                                    |
| `sudo nhub unlock`         | removes the login lockout after repeated failures, and every fail2ban SSH ban with it                                                    |
| `sudo nhub reset all`      | hands the network back, returns `config/` to the examples, removes the keys, tokens and authorities the box made, and stops the services |

`nhub reset all` leaves the box's own agent installed. The box is then reached over SSH until `nhub setup` runs again. Every `nhub` subcommand is on [nhub commands](../commands/nhub.md).
