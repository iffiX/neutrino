---
title: Troubleshooting
---

# Troubleshooting

Each section is one surface where a symptom appears, and each row is one symptom as the interface shows it, with its cause and the fix. Find the code or the label you see, then follow the row.

## The panel is unreachable

| Symptom                                            | Cause                                                                  | Fix                                                                                                     |
| -------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| the browser reaches nothing at `http://<hub>:8080` | the unit is down, the port was moved, or this network is not exposed   | run `systemctl status neutrino_hub_web` on the box; read **Panel port** and **Exposure** on **Network** |
| `https://` is refused                              | the panel is plain HTTP                                                | open the `http://` address                                                                              |
| signing in to one hub signs you out of another     | two hubs behind one hostname share a session cookie scoped to the host | reach them by different hostnames                                                                       |

`<hub>` is the box's address.

## Locked out

| Symptom                                 | Cause                          | Fix                                                                     |
| --------------------------------------- | ------------------------------ | ----------------------------------------------------------------------- |
| **Locked after repeated failures.**     | too many wrong passwords       | run `sudo nhub unlock` on the box; it also lifts every fail2ban SSH ban |
| **Wrong password.** and it is forgotten | the panel password is lost     | run `sudo nhub reset password` on the box; every session is signed out  |
| the vault passphrase is lost            | the passphrase has no recovery | `nhub reset all`, then setup again and every credential entered again   |

## A device is offline

| Symptom                                                | Cause                                                         | Fix                                                                              |
| ------------------------------------------------------ | ------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| an action is rejected with `agent_offline`             | the agent is not connected                                    | on the machine, run `systemctl status neutrino_agent`, then `sudo nagent status` |
| the drawer reads `agent_wire_stale`                    | the agent speaks an older channel than the hub                | **Reinstall agent** in the drawer, or a fresh link                               |
| the drawer reads `agent_newer_than_hub`                | the agent is a later release than the hub                     | upgrade the hub first                                                            |
| `nagent status` reads `hub_untrusted`                  | the hub was reset or reinstalled, and its certificate changed | enroll again with a fresh link from **Add by link**                              |
| the machine is listed and its modules cannot be edited | an offline machine is rejected, and nothing is queued         | bring the machine back, then apply again                                         |

## The client does not connect

| Symptom                 | Cause                                                    | Fix                                                                  |
| ----------------------- | -------------------------------------------------------- | -------------------------------------------------------------------- |
| `hub_unreachable`       | port 8443 on the hub is not reachable from this computer | check the network or the overlay, and **Exposure** on the hub        |
| `enroll_refused`        | the link expired, or was consumed                        | create a fresh link on **Clients**; a link is valid for five minutes |
| `link_unreadable`       | the paste was cut short                                  | copy the whole line from the hub                                     |
| `link_not_for_client`   | the link is from **Devices**                             | create one on **Clients**                                            |
| `hub_untrusted`         | the hub was reset or reinstalled                         | paste a fresh link                                                   |
| `client_disabled`       | the client is switched off on **Clients**                | **Enable** it there                                                  |
| `client_newer_than_hub` | the client is a later release than the hub               | upgrade the hub, then paste a fresh link                             |
| `gui_webkitgtk_missing` | WebKitGTK is absent on Linux                             | install the packages the message names, then start the client again  |
| `gui_webview2_missing`  | WebView2 is absent on Windows                            | install the runtime the message names, then start the client again   |
| `root_refused`          | the client was started with `sudo`                       | start it from your own account                                       |

## A share does not mount

| Symptom                                  | Cause                                                              | Fix                                                         |
| ---------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------- |
| `mountpoint_invalid`                     | the path is outside your home                                      | give a folder under your home, such as `~/nas/media`        |
| `mountpoint_not_drive_letter`            | Windows takes a drive letter                                       | pick an unused letter, such as `N:`                         |
| `mountpoint_not_empty`                   | the folder holds files                                             | pick an empty folder                                        |
| `mount_not_authorized`                   | the polkit prompt was dismissed, or you are not at the console     | select **Mount** again and confirm the prompt               |
| `mount_tooling_missing`                  | the root helper or `mount.cifs` is absent                          | reinstall the client package, which depends on `cifs-utils` |
| `credentials_missing`                    | the saved credentials file is gone                                 | select **Config** and type the password again               |
| the row is greyed, **not reachable now** | the serving machine is off, or this network is not in **Exposure** | bring the machine back, or expose the network on the hub    |

## An AI tool ignores the gateway

| Symptom                                           | Cause                                          | Fix                                                                                                |
| ------------------------------------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `no_endpoint`                                     | the hub has issued this client no key          | on the hub's **AI** page, revoke the client's key so a new one is issued, or rejoin the client     |
| the tools use their own configuration             | **Save** in the dialog only stages             | switch **Enabled** on and select **Apply**; `nclient service ai show` prints where the tools point |
| the panel reads `gateway_unreachable`             | the gateway process is down                    | run `systemctl status neutrino_hub_cliproxyapi` on the box                                         |
| a tool reaches nothing after the port was changed | the endpoint on the machine names the old port | apply the entry again on each client, and paste the new endpoint into hand-keyed tools             |

## An overlay peer is missing

| Symptom                                              | Cause                                                        | Fix                                                                          |
| ---------------------------------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| NetBird's badge reads **management unreachable**     | the hub cannot reach the management plane from where it sits | switch on **Send Neutrino Hub's own traffic through the proxy** on **Proxy** |
| NetBird's **Peers** is empty                         | no other device has logged in                                | log in on the other device with the NetBird app                              |
| a NetBird route is listed but the LAN is unreachable | the subnet has no Access Control Policy in the console       | add the policy to the Resource                                               |
| EasyTier reads **No machine has joined yet.**        | the other machine's name or secret differs                   | copy the command again with **Copy with the secret**                         |
| an EasyTier peer joins and the LAN is unreachable    | the subnet is not exported                                   | add it under **Exported networks** and apply                                 |
| the box is silent on the overlay with either engine  | the overlay is not in **Exposure**                           | tick it under **Network**, **Exposure**                                      |

## Where the logs are

| What                           | Where                                                                                                                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| the setup run                  | `/var/log/neutrino/setup.log` on the box                                                                                                                                       |
| the hub's own logs             | `/var/log/neutrino/` on the box                                                                                                                                                |
| a hub unit                     | `journalctl -u neutrino_hub_web -n 200`, and likewise `neutrino_hub_xray`, `neutrino_hub_dnsmasq`, `neutrino_hub_cliproxyapi`, `neutrino_hub_netbird`, `neutrino_hub_easytier` |
| the agent on a machine         | `journalctl -u neutrino_agent -n 200` on that machine                                                                                                                          |
| the AI gateway, from the panel | **Journal** on the **AI** page                                                                                                                                                 |
| what a render produces         | `sudo nhub apply --dry-run` on the box                                                                                                                                         |
