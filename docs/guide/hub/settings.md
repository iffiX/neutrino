---
title: Settings
---

# Settings

The **Settings** page runs the panel itself: its HTTPS, its name, password, language and theme, the configuration backup, and updates of the hub. The commands that reset the box from a terminal are at the end of this page.

## HTTPS

The panel listens on two ports: HTTP, `8080` unless setup chose another, and HTTPS, `443` unless setup chose another. Both ports serve the panel whether HTTPS is on or off, and both are set under **Panel ports** on the [Network](./network.md#panel-ports) page. The HTTPS port serves a certificate signed by a certificate authority this hub makes for itself.

**Enable HTTPS** makes the HTTP port send every browser to the HTTPS address. Do it in this order on each device: install the authority, restart the browser, then enable HTTPS.

### Install the authority

Before you start, open the panel at its `http://` address on the device you are setting up.

1. Under **HTTPS**, select **Install certificate**. The browser downloads the authority as a `.crt` file named after this hub.
1. In the row of systems, select yours. The system this page is open on is already selected and marked **this device**.
1. Follow the steps for your system in the following table.
1. Close the browser and open it again.

| System          | Steps after the download                                                                                                                                    |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Windows         | Open the file, choose **Install Certificate** and **Local Machine**, and place it in **Trusted Root Certification Authorities**.                            |
| macOS           | Open the file to add it to the login keychain. In Keychain Access, open the Neutrino authority and set **When using this certificate** to **Always Trust**. |
| Linux, Chrome   | Open `chrome://certificate-manager`, then **Custom** > **Trusted certificates** > **Import**, and pick the file.                                            |
| Linux, Firefox  | Open **Settings** > **Privacy & Security** > **View Certificates**, import the file on **Authorities**, and tick **Trust this CA to identify websites**.    |
| Android         | Open **Settings** > **Security** > **Encryption & credentials** > **Install a certificate** > **CA certificate**, then pick the file.                       |
| iPhone and iPad | Download the file in Safari, install the profile under **Settings**, then turn on full trust in **General** > **About** > **Certificate Trust Settings**.   |

On macOS, closing the certificate window asks for your password to confirm the trust setting.

![The Keychain Access trust dialog set to Always Trust](/guide/os/os_mac_keychain_trust.webp)

A Chrome that was told to proceed past a certificate warning shows **Not secure** for the panel until it restarts, even after the import.

### Turn HTTPS on

Open the panel's `http://` address after the browser restarts. The **HTTPS** section fetches a test address from the HTTPS port, and the line beside its buttons reports the result:

| Line                                                   | What it means                                                    |
| ------------------------------------------------------ | ---------------------------------------------------------------- |
| **This browser trusts the certificate.**               | **Enable HTTPS** is available                                    |
| **Install the certificate, then restart the browser.** | the browser rejected the certificate; **Enable HTTPS** is greyed |

Select **Enable HTTPS**. The page moves to the `https://` address, and from then on the HTTP port sends every browser there. **Disable HTTPS** ends your session and moves the page back to the `http://` address, where you sign in again.

![The HTTPS section with HTTPS on and its status lines](/guide/en/settings_https_on.webp)

The certificate names the box's private and overlay addresses, `127.0.0.1`, `localhost`, the box's host name and `hub.neutrino.internal`. A browser that opens the panel at a public address warns even with the authority installed.

### Read the status lines

| Line                       | What it shows                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------- |
| **Addresses**              | the `http://` and `https://` addresses of this host, the one in use marked **current** |
| **Authority SHA-256**      | the authority's fingerprint, to compare with what a device shows                       |
| **Authority created**      | when the authority was made                                                            |
| **Certificate names**      | every address and name the panel's certificate covers                                  |
| **Certificate issued**     | when the current certificate was signed                                                |
| **Certificate expires**    | when it runs out                                                                       |
| **Last automatic renewal** | the last time the hub signed a new certificate by itself                               |

The hub signs a new certificate when the box's addresses change, and 30 days before the old one expires. A browser that trusts the authority accepts each new certificate.

### Regenerate the authority

**Regenerate certificate** replaces the authority and the certificate, and every browser that installed the old authority warns again until it installs the new one. On an `https://` page the button is greyed, with **Turn HTTPS off first to regenerate the certificate.** beside it.

1. If HTTPS is on, select **Disable HTTPS**, and sign in again at the `http://` address.
1. Select **Regenerate certificate**, then confirm. The browser downloads the new authority at once.
1. Install the new authority as in [Install the authority](#install-the-authority), and restart the browser.
1. Select **Enable HTTPS**.

The authority is part of `config/`, so a restored backup keeps the authority browsers already trust.

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

The credentials inside are sealed under the vault's master passphrase, and everything else in the archive is readable by whoever holds the file. The archive holds configuration only: share contents, Gitea repositories, container volumes and ZFS datasets stay on their machines.

## Restore a backup

1. Under **Configuration archive**, select **Restore from file** and pick the archive.
1. In the dialog, fill **Vault passphrase** with the passphrase the backup was sealed with.
1. Select **Restore**.

The archive's files replace every file under `config/`, the hub applies them, and the panel restarts. The page reloads by itself; sign in with the restored password. Agents and clients connect again by themselves.

| Code                      | Cause                                                                                           |
| ------------------------- | ----------------------------------------------------------------------------------------------- |
| `backup_wrong_extension`  | the file is not a backup this panel writes                                                      |
| `backup_corrupt`          | the archive is damaged                                                                          |
| `vault_passphrase_wrong`  | the passphrase does not open this backup                                                        |
| `backup_mode_unavailable` | the backup sets a shape this hub does not offer, such as a side gateway on the mainland edition |

With any of these codes, nothing is restored. When the apply after a restore stops short, the files stay restored; fix the cause the dialog names, then run `sudo nhub apply`. On a different box, each AI subscription account signs in again, because those sign-ins are kept outside `config/`.

## Update the hub

**Update** installs a newer release of the hub on the box it runs on.

1. Under **Update**, select **Check for updates**. The section shows the newest release with its date, size, **Release notes**, and the disk room it needs against what is free.
1. Select **Install** followed by the version, then confirm.

![The Update section showing a newer release](/guide/en/settings_update.webp)

The panel downloads the package and checks it against the release's `SHA256SUMS`. The install then runs outside the panel: on Linux in a systemd unit, `neutrino_hub_update`, and on macOS and Windows in the system's installer. The page returns to the sign-in, and afterwards the section names the old version, the new one and the date.

For up to three minutes after the install, the update checks that the panel returns a page and that its services run. When the check fails, it installs the previous version again, and the section names the reason and shows the **Install log**. The confirmation says beforehand when no previous package exists to fall back on.

With less than 300 MB of memory available, the update stops the panel and the AI gateway before unpacking, and starts them afterwards. After the check passes, it reinstalls the hub box's own agent from the new hub, and agents on other machines update themselves when they connect.

A new major version is not installed from here; the section reads that the version is a new major version. A hub run from a source checkout shows **This hub runs from a checkout; update it with git.**

`sudo nhub update` does the same from a terminal and asks before it installs. `--yes` skips the question, and `--package` installs a package file you downloaded yourself. On Linux, the update's log is in `journalctl -u neutrino_hub_update`.

## Coming from 0.4

A 0.4.0 hub does not update to 0.5.0 in place. To move to 0.5.0:

1. Remove the 0.4.0 hub package from the box.
1. Install 0.5.0 as a new hub, as described in [Install the hub](../install/hub.md), and run `nhub setup`.
1. On each managed machine, install the 0.5.0 agent package and join it with a new link from the **Devices** page.
1. On each computer and phone, install the 0.5.0 client and join it with a new link from the **Clients** page.

A 0.3 or 0.4 agent or client is rejected with `protocol_too_old`, its protocol being older than the hub accepts. A 0.4 backup does not restore on a 0.5.0 hub.

## Reset from a terminal

| Command                    | What it does                                                                                                                             |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `sudo nhub reset password` | sets a new panel password and signs every session out                                                                                    |
| `sudo nhub unlock`         | removes the sign-in lockout after repeated failures, and every fail2ban SSH ban with it                                                  |
| `sudo nhub reset network`  | hands the machine's network back (the firewall, the engines, the resolver), stops the panel, and changes nothing in `config/`            |
| `sudo nhub reset all`      | hands the network back, returns `config/` to the examples, removes the keys, tokens and authorities the box made, and stops the services |

Each `nhub reset` command asks `[y/N]` before it acts, and `--yes` skips the question. `nhub reset all` leaves the box's own agent installed, and the box is reached over SSH until `nhub setup` runs again. Every `nhub` subcommand is on [nhub commands](../commands/nhub.md).
