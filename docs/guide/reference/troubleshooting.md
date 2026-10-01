---
title: Troubleshooting
---

# Troubleshooting

Find the code or the label on your screen in the section for the place it appears; its row gives the cause and the fix. In the tables, `<hub>` stands for the address of the hub box.

## The panel is unreachable

| Symptom                                                 | Cause                                                                    | Fix                                                                                                          |
| ------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| the browser reaches nothing at `http://<hub>:8080`      | the panel's unit is down, the port moved, or this network is not exposed | run `systemctl status neutrino_hub_web` on the box, then read **Panel port** and **Exposure** on **Network** |
| one scheme gets an empty or reset page, the other loads | the panel speaks HTTPS or HTTP on its port, one at a time                | open the address with the other scheme; **Scheme** under **Settings** > **HTTPS** shows the one in use       |
| the session ends after the panel port changed           | the session cookie is named after the port, `neutrino_session_<port>`    | sign in again at the new address                                                                             |

## The browser warns about the certificate

These rows apply while HTTPS is on. The panel's certificate is signed by the hub's own certificate authority, which each browser trusts only after it is installed there.

| Symptom                                                   | Cause                                                                                    | Fix                                                                                                                      |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| the browser says the certificate authority is not trusted | the authority is not installed on this device                                            | select **Install certificate** under **Settings** > **HTTPS**, follow the steps for this device, and restart the browser |
| Firefox warns and Chrome on the same machine does not     | Firefox keeps its own list of authorities                                                | follow the **Linux, Firefox** steps under **Install certificate**                                                        |
| every browser warns again after a change on **Settings**  | **Regenerate certificate** made a new authority                                          | install the new authority on each device                                                                                 |
| the browser says the certificate is for another name      | the address in the browser is not under **Certificate names**; a public address never is | open the panel at a name or address listed there, such as `hub.neutrino.internal` on the LAN                             |

## Locked out

| Symptom                                 | Cause                                                                                                                 | Fix                                                                                        |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| **Locked after repeated failures.**     | too many wrong passwords                                                                                              | run `sudo nhub unlock` on the box; it also lifts every fail2ban SSH ban                    |
| **Wrong password.** and it is forgotten | the panel password is lost                                                                                            | run `sudo nhub reset password` on the box; every session is signed out                     |
| the vault passphrase is lost            | the running box still reads the vault with its own working key; a backup taken under the lost passphrase stays sealed | run `sudo nhub vault rekey` on the box to set a new passphrase, then download a new backup |

## A device is offline

| Symptom                                                             | Cause                                                                       | Fix                                                                                                       |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| an action is rejected with `agent_offline`                          | the agent is not connected                                                  | on the machine, run `sudo nagent status`; when it reads the service as stopped, run `sudo nagent start`   |
| the machine is listed and its modules cannot be changed             | an offline machine rejects every change, and nothing is queued              | bring the machine back, then apply again                                                                  |
| a module is greyed out with **This machine's system cannot run it** | the module has no build for this system, the case `no_platform_build` names | pick another machine; [Supported platforms](./platforms.md#modules-by-system) lists each module's systems |

## A program is turned away by the hub

An agent shows these codes in `nagent status`, and a desktop client on its hub's row.

| Symptom            | Cause                                                                                    | Fix                                                                                                                                                                                           |
| ------------------ | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `protocol_too_old` | the program speaks a protocol older than the hub accepts; every 0.3 and 0.4 package does | on a Linux machine, select **Reinstall agent** in its drawer on **Devices**, which installs over SSH; install the 0.5.0 package by hand on Windows, macOS and every client; the binding stays |
| `protocol_too_new` | the program speaks a protocol newer than the hub                                         | update the hub under **Settings**; the binding stays and the program connects again                                                                                                           |
| `hub_untrusted`    | the hub was reset or reinstalled, and its certificate changed                            | join again with a fresh link, from **Add by link** on **Devices** for an agent and from **Clients** for a client                                                                              |

## The overlay

| Symptom                                                                                        | Cause                                                                                          | Fix                                                                                                                    |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| turning an engine on, or saving an EasyTier address, is rejected with `overlay_subnet_overlap` | the engine's network overlaps the other engine's or a network the box holds an address on      | change EasyTier's **Overlay address** or the LAN's address on **Network**; NetBird's network is always `100.64.0.0/10` |
| the **Overlay** page shows `overlay_default_route_refused` in red                              | a peer or the console gave the box a default route through the overlay, and the hub deleted it | remove the exit route for the hub in the NetBird or EasyTier console; the box keeps its own uplink as the way out      |
| `overlay_route_overlap` with **The hub cannot take it away**                                   | an overlay route overlaps one of the box's networks, and the hub could not deselect it         | change or remove that route where the overlay is managed                                                               |
| NetBird's badge reads **management unreachable**                                               | the hub cannot reach the management plane from where it sits                                   | switch on **Send Neutrino Hub's own traffic through the proxy** on **Proxy**                                           |
| NetBird's **Peers** is empty                                                                   | no other device has logged in                                                                  | log in on the other device with the NetBird app                                                                        |
| a NetBird route is listed and the LAN is unreachable                                           | the subnet has no Access Control Policy in the console                                         | add the policy to the Resource                                                                                         |
| EasyTier reads **No machine has joined yet.**                                                  | the other machine's network name or secret differs                                             | copy the command again with **Copy with the secret**                                                                   |
| an EasyTier peer joins and the LAN is unreachable                                              | the subnet is not exported                                                                     | add it under **Exported networks** and apply                                                                           |
| the box is silent on the overlay with either engine                                            | the overlay is not in **Exposure**                                                             | tick it under **Exposure** on **Network**                                                                              |

## A terminal closes

| Symptom            | Cause                                                                                             | Fix                                                                                |
| ------------------ | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `session_taken`    | another window or device attached to the same session, and a session holds one terminal at a time | select the session's tab again to take it back; the other window's terminal closes |
| `session_unknown`  | the session ended, or the agent restarted or updated, which ends every session on that machine    | open a new terminal on the machine                                                 |
| `shell_unknown`    | the hub no longer holds the shell the client resized                                              | close the terminal in the client and open it again                                 |
| `unknown_terminal` | `nclient terminal` named a machine no joined hub offers a terminal on                             | run `nclient terminal` with a machine the client's **Terminals** page lists        |

## The client does not connect

| Symptom                 | Cause                                                                  | Fix                                                                  |
| ----------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `hub_unreachable`       | port 8443 on the hub is not reachable from this computer               | check the network or the overlay, and **Exposure** on the hub        |
| `enroll_refused`        | the link expired or was used                                           | create a fresh link on **Clients**; a link is valid for five minutes |
| `link_unreadable`       | the paste was cut short                                                | copy the whole line from the hub                                     |
| `link_not_for_client`   | the link is from **Devices**                                           | create one on **Clients**                                            |
| `client_disabled`       | the client is switched off on **Clients**                              | select **Enable** on its row there                                   |
| `permission_denied`     | the client's permission leaves out that kind of entry, or that machine | widen the client's permission on **Clients**                         |
| `gui_webkitgtk_missing` | WebKitGTK is absent on Linux                                           | install the packages the message names, then start the client again  |
| `gui_webview2_missing`  | WebView2 is absent on Windows                                          | install the runtime the message names, then start the client again   |
| `root_refused`          | the client was started with `sudo`                                     | start it from your own account                                       |

## A share does not mount on a computer

| Symptom                                  | Cause                                                              | Fix                                                         |
| ---------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------- |
| `mountpoint_invalid`                     | the path is outside your home                                      | give a folder under your home, such as `~/nas/media`        |
| `mountpoint_not_drive_letter`            | Windows mounts a share at a drive letter                           | pick an unused letter, such as `N:`                         |
| `mountpoint_not_empty`                   | the folder holds files                                             | pick an empty folder                                        |
| `mount_not_authorized`                   | the polkit prompt was dismissed, or you are not at the console     | select **Mount** again and confirm the prompt               |
| `mount_tooling_missing`                  | the root helper or `mount.cifs` is absent                          | reinstall the client package, which depends on `cifs-utils` |
| `credentials_missing`                    | the saved credentials file is gone                                 | select **Config** and type the password again               |
| `share_login_rejected`                   | the share rejected the username or the password                    | select **Config** and enter both again                      |
| the row is greyed, **not reachable now** | the serving machine is off, or this network is not in **Exposure** | bring the machine back, or expose the network on the hub    |

## A share is unreachable on a phone

The system's Files app shows the Android app's shares, and reports a failure as the code's sentence.

| Symptom                                                               | Cause                                                                             | Fix                                                                                                                                              |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `share_unreachable`, with the phone away from the LAN                 | the phone's virtual network is off                                                | in the app, select the **Virtual network** chip on the hub's row and wait for it to read **on**                                                  |
| `share_unreachable` while the virtual network is **on**               | the overlay is not in **Exposure**, or the overlay does not route the share's LAN | tick the overlay under **Exposure** on **Network**; for EasyTier add the LAN under **Exported networks**, for NetBird add a route and its policy |
| Files reads **Give this share's password on the Files screen first.** | the share has no login on this phone yet                                          | open the share on the app's Files screen, enter the username and password, and select **Connect**                                                |

## An AI tool ignores the gateway

| Symptom                                               | Cause                                                       | Fix                                                                                                                    |
| ----------------------------------------------------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `no_endpoint`                                         | the hub has issued this client no key                       | on the hub's **AI** page, revoke the client's key so a new one is issued, or join the client again                     |
| the tools keep their own configuration after **Save** | **Save** in **Config** keeps the choices and points nothing | switch on **The AI tools use this gateway** on the entry's row; `nclient service ai show` prints where the tools point |
| the panel reads `gateway_unreachable`                 | the gateway process is down                                 | run `systemctl status neutrino_hub_cliproxyapi` on the box                                                             |
| a tool reaches nothing after the port was changed     | the endpoint on the machine names the old port              | apply the entry again on each client, and paste the new endpoint into tools configured by hand                         |

## Where the logs are

| What                           | Where                                                                                                                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| the setup run                  | `/var/log/neutrino/setup.log` on the box                                                                                                                                       |
| the hub's own logs             | `/var/log/neutrino/` on the box                                                                                                                                                |
| a hub unit                     | `journalctl -u neutrino_hub_web -n 200`, and likewise `neutrino_hub_xray`, `neutrino_hub_dnsmasq`, `neutrino_hub_cliproxyapi`, `neutrino_hub_netbird`, `neutrino_hub_easytier` |
| a hub update                   | `journalctl -u neutrino_hub_update` on the box                                                                                                                                 |
| the agent on Linux             | `journalctl -u neutrino_agent -n 200` on that machine                                                                                                                          |
| the agent on Windows           | `%ProgramData%\Neutrino\agent\agent.log`                                                                                                                                       |
| the agent on macOS             | `/Library/Logs/neutrino_agent.log`                                                                                                                                             |
| the AI gateway, from the panel | **Journal** on the **AI** page                                                                                                                                                 |
| what a render produces         | `sudo nhub apply --dry-run` on the box                                                                                                                                         |
