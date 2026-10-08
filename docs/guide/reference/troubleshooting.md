---
title: Troubleshooting
---

# Troubleshooting

Each section covers the place a symptom shows up, and each row gives a symptom, its cause and the fix. In the tables, `<hub>` stands for the address of the machine that runs the hub.

## The panel is unreachable

| Symptom                                                                         | Cause                                                                                                          | Fix                                                                                                                                       |
| ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| the browser reaches nothing at `http://<hub>:8080`                              | the panel's unit is down, the port moved, or this network is not exposed                                       | run `systemctl status neutrino_hub_web` on the hub, then read **Panel ports** and **Exposure** on **Network**                             |
| `http://<hub>:8080` moves to `https://<hub>`, which reaches nothing             | HTTPS is on, so the HTTP port sends every browser to the HTTPS port, and that port is unreachable from here    | read **HTTPS port** under **Panel ports** on **Network**, and check that the port is open on the way to the hub                           |
| the session ends after a panel port changed                                     | the panel restarted on the new port, and the session cookie is named after the port, `neutrino_session_<port>` | sign in again at the new address                                                                                                          |
| the session ends after **Enable HTTPS** or **Disable HTTPS**                    | the switch ends the session, and the port you left deletes the cookie when it sends you on                     | sign in again at the address the page moved to                                                                                            |
| after **Disable HTTPS**, signing in over `http://` comes back to the login card | the browser kept the `Secure` cookie from the HTTPS port and keeps it over the new one                         | select **Clear the old session** on the login card, or open the `https://` address one time, which sends you back with the cookie removed |

## The browser warns about the certificate

These rows apply to the HTTPS port. The hub's own certificate authority signs its certificate, and a browser trusts that authority only after it is installed there and the browser restarts.

| Symptom                                                                                                        | Cause                                                                                           | Fix                                                                                                                                                |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| the browser says the certificate authority is not trusted                                                      | the authority is not installed on this device                                                   | open `http://<hub>:8080`, select **Install certificate** under **Settings** > **HTTPS**, follow the steps for this device, and restart the browser |
| **Enable HTTPS** is greyed and the line beside it reads **Install the certificate, then restart the browser.** | this browser rejected the HTTPS port's certificate                                              | install the authority for this system, restart the browser, and open the `http://` address again                                                   |
| Chrome shows **Not secure** after the authority was imported                                                   | Chrome was told to proceed past a certificate warning before the import                         | restart Chrome                                                                                                                                     |
| Firefox warns and Chrome on the same machine does not                                                          | Firefox keeps its own list of authorities                                                       | follow the **Linux, Firefox** steps under **Install certificate**                                                                                  |
| every browser warns again after a change on **Settings**                                                       | **Regenerate certificate** made a new authority                                                 | install the new authority on each device and restart the browser; `http://<hub>:8080/api/hub/setting/https/authority` serves it while HTTPS is on  |
| the browser says the certificate is for another name                                                           | the address in the browser is missing from **Certificate names**, as a public address always is | open the panel at a name or address listed there, such as `hub.neutrino.internal` on the LAN                                                       |

## Locked out

| Symptom                                 | Cause                                                                                                                 | Fix                                                                                        |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| **Locked after repeated failures.**     | too many wrong passwords                                                                                              | run `sudo nhub unlock` on the hub; it also lifts every fail2ban SSH ban                    |
| **Wrong password.** and it is forgotten | the panel password is lost                                                                                            | run `sudo nhub reset password` on the hub; every session is signed out                     |
| the vault passphrase is lost            | the running hub still reads the vault with its own working key; a backup taken under the lost passphrase stays sealed | run `sudo nhub vault rekey` on the hub to set a new passphrase, then download a new backup |

## A device is offline

| Symptom                                                 | Cause                                                          | Fix                                                                                                     |
| ------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `agent_offline`, in the panel or on a client's row      | the machine's agent is not connected to the hub                | on the machine, run `sudo nagent status`; when it reads the service as stopped, run `sudo nagent start` |
| the machine is listed and its modules cannot be changed | an offline machine rejects every change, and nothing is queued | bring the machine back, then apply again                                                                |

## A program is turned away by the hub

An agent shows these codes in `nagent status`, and a client on its hub's row.

| Symptom            | Cause                                                                                        | Fix                                                                                                                                                                                                                                        |
| ------------------ | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `protocol_too_old` | the program is a 0.3 or 0.4 package, which speaks an older protocol than a 0.5.0 hub accepts | install the 0.5.0 package on that machine, which `nagent --version` confirms, and join with a new link from the hub. A 0.4 hub cannot be upgraded to 0.5.0: remove it and install 0.5.0 fresh, as [Settings](../hub/settings.md) describes |
| `protocol_too_new` | the program speaks a newer protocol than the hub                                             | update the hub under **Settings**; the binding stays and the program connects again                                                                                                                                                        |
| `hub_untrusted`    | the hub was reset or installed again, and its certificate changed                            | join again with a fresh link, from **Add by link** on **Devices** for an agent and from **Clients** for a client                                                                                                                           |

## Access

| Symptom                                                                                        | Cause                                                                                          | Fix                                                                                                                                                                                                           |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| turning an engine on, or saving an EasyTier address, is rejected with `overlay_subnet_overlap` | the engine's network overlaps the other engine's or a network the hub holds an address on      | change EasyTier's **This box's address** or the LAN's address on **Network**; NetBird's network is always `100.64.0.0/10`                                                                                     |
| the **Access** page shows `overlay_default_route_refused` in red                               | a peer or the console gave the hub a default route through the network, and the hub deleted it | remove the exit route for the hub in the NetBird or EasyTier console; the hub keeps its own uplink as the way out                                                                                             |
| `overlay_route_overlap` with **The hub cannot take it away**                                   | a route on the network overlaps one of the hub's networks, and the hub could not deselect it   | change or remove that route in the NetBird or EasyTier console                                                                                                                                                |
| the hub does not respond on a virtual network                                                  | that network is not in **Exposure**                                                            | tick it under **Exposure** on **Network**                                                                                                                                                                     |
| NetBird's badge reads **management unreachable**                                               | the hub cannot reach NetBird's management plane                                                | on the hub, check that the uplink is up and that DNS resolves the management plane's name                                                                                                                     |
| NetBird's **Peers** is empty                                                                   | no other device has joined the network                                                         | on a client, select **Connect** on the hub row's virtual network line                                                                                                                                         |
| after a client joins with a scan or a pasted link, its line reads `overlay_join_failed`        | the hub holds a one-time setup key, which the first device spent                               | create a reusable key in the NetBird console, paste it with **Replace** on the NetBird card, then select **Connect** on the client again, as [NetBird](../hub/netbird.md) describes                           |
| a client reaches the hub over NetBird and the hub's LAN devices stay unreachable               | the console has no access policy for the LAN route                                             | add the network and its policy in the NetBird console, as [LAN devices over NetBird](../scenarios/netbird_lan_routes.md) describes                                                                            |
| EasyTier reads **No machine has joined yet.**                                                  | the other machine's network name or secret differs                                             | copy the command again with **Copy with the secret**                                                                                                                                                          |
| a client's virtual network line stays at **Connecting…** with the console's reason under it    | in console mode, the console has not attached the device to a network yet                      | attach the device to the hub's network in the EasyTier console, as [EasyTier](../hub/easytier.md) describes                                                                                                   |
| a device joins over EasyTier and the hub's LAN devices stay unreachable                        | the LAN subnet is not routed on the network                                                    | in manual mode, add the subnet under **Exported networks** and apply; in console mode, add it as a subnet proxy in the console, as [LAN devices over EasyTier](../scenarios/easytier_lan_routes.md) describes |
| the **SSH Relay** card's **Status** reads anything but **Connected**                           | the hub's SSH forward to your server is down, or the public port is closed                     | read the status table on [SSH Relay](../hub/relay.md#read-the-status); each status there has its fix                                                                                                          |

## Network settings are refused

| Symptom                                                                                                                  | Cause                                                         | Fix                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `network_invalid` with the field `role`: the panel reads that the port cannot answer with the role **Disabled**          | a port ticked under **Exposure** has the role **Disabled**    | give the port the role **WAN** or **LAN**, or untick it under **Exposure**, then apply again      |
| **Country code** reads **Two letters, such as DE. 5 GHz needs one.**, or `network_invalid` with the field `country_code` | an access point on 5 GHz has no valid two-letter country code | type the code of the country the hub is in under **Country code**, such as `DE`, then apply again |

## A module does not install

| Symptom                                                                                 | Cause                                                | Fix                                                                                                       |
| --------------------------------------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `module_fetch_failed`, with the download's own words after it                           | the hub could not download the module's install file | check that the hub reaches the internet, then select **Install** again                                    |
| a module is greyed with **This machine's system cannot run it**, or `no_platform_build` | the module has no build for this machine's system    | pick another machine; [Supported platforms](./platforms.md#modules-by-system) lists each module's systems |

## A terminal closes

| Symptom             | Cause                                                                                          | Fix                                                                         |
| ------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `session_not_owned` | the session belongs to another viewer and is not shared                                        | ask its owner to switch on **Shared**, or open a terminal of your own       |
| `session_unknown`   | the session ended, or the agent restarted or updated, which ends every session on that machine | open a new terminal on the machine                                          |
| `shell_unknown`     | the hub no longer holds the shell the client resized                                           | close the terminal in the client and open it again                          |
| `unknown_terminal`  | `nclient terminal` named a machine no joined hub offers a terminal on                          | run `nclient terminal` with a machine the client's **Terminals** page lists |

## The client does not connect

| Symptom                 | Cause                                                                  | Fix                                                                                                           |
| ----------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `hub_unreachable`       | port 8443 on the hub is unreachable from this computer                 | check the network, the way in on **Access** (NetBird, EasyTier or the SSH Relay), and **Exposure** on the hub |
| `ticket_spent`          | the link expired or was used                                           | leave the hub in the client and join with a fresh link from **Clients**; a link works for thirty minutes      |
| `admission_paused`      | the hub paused new joins after too many failed ones                    | leave the client running; it joins again after the seconds the code names                                     |
| `link_unreadable`       | the paste was cut short                                                | copy the whole line from the hub                                                                              |
| `link_not_for_client`   | the link is from **Devices**                                           | create one on **Clients**                                                                                     |
| `client_disabled`       | the client is switched off on **Clients**                              | select **Enable** on its row there                                                                            |
| `permission_denied`     | the client's permission leaves out that kind of entry, or that machine | widen the client's permission on **Clients**                                                                  |
| `gui_webkitgtk_missing` | WebKitGTK is absent on Linux                                           | install the packages the message names, then start the client again                                           |
| `gui_webview2_missing`  | WebView2 is absent on Windows                                          | install the runtime the message names, then start the client again                                            |
| `root_refused`          | the client was started with `sudo`                                     | start it from your own account                                                                                |
| `client_held`           | another account's client runs on this computer                         | quit the client in that account, or sign that account out, then start yours                                   |

## A client page cannot reach its service

The client opens every page through the hub, so these codes come from the hub or from the agent of the providing machine. The client shows the code on the entry's row.

| Symptom                             | Cause                                                                                     | Fix                                                           |
| ----------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `connect_failed` with `refused`     | nothing listens on the service's port on that machine                                     | start the service, or the module, on that machine             |
| `connect_failed` with `timeout`     | the service did not respond within 10 seconds                                             | check that the machine and the service are up                 |
| `connect_failed` with `unreachable` | the hub has no route to a service declared by hand on **Services**                        | check the declared address, and that the hub's LAN reaches it |
| `port_not_published`                | the machine stopped publishing the port: the container, the instance or the share stopped | start it again on the **Modules** page                        |
| `connect_limit`                     | the client has 256 connections open through the hub                                       | close forwards or programs the client does not need           |
| `port_taken`                        | another program on this computer listens on the entry's **Fixed** local port              | select **Configure** on the row and pick another port         |

## A share does not mount on a computer

| Symptom                                  | Cause                                                                                                  | Fix                                                                                                                       |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `mountpoint_invalid`                     | the path is outside your home                                                                          | give a folder under your home, such as `~/nas/media`                                                                      |
| `mountpoint_not_drive_letter`            | Windows mounts a share at a drive letter                                                               | pick an unused letter, such as `N:`                                                                                       |
| `mountpoint_not_empty`                   | the folder holds files                                                                                 | pick an empty folder                                                                                                      |
| `mount_not_authorized`                   | the polkit prompt or the macOS login dialog was dismissed                                              | select **Mount** again and confirm the prompt                                                                             |
| `mount_tooling_missing`                  | `mount.cifs` or the client's mount helper is absent                                                    | install the client package again, which depends on `cifs-utils`                                                           |
| `pkexec_missing`                         | the computer has no `pkexec`, which a mount on Linux goes through                                      | install the `pkexec` package, then select **Mount** again                                                                 |
| `credentials_missing`                    | the saved credentials file is gone                                                                     | select **Configure** and type the password again                                                                          |
| `share_login_rejected`                   | the share rejected the username or the password                                                        | select **Configure** and enter both again                                                                                 |
| `files_adapter_unavailable` on Windows   | the `NeutrinoClientFiles` service is missing, stopped or failing, so the files adapter could not start | read the words after the code, run `sc query NeutrinoClientFiles`, and install the client again if the service is missing |
| `files_adapter_in_use` on Windows        | another account's client holds the files adapter                                                       | quit the client in that account, or sign that account out; the mount runs again after that                                |
| the row is greyed, **Not reachable now** | the serving machine is off or not connected to the hub                                                 | bring the machine back                                                                                                    |

## A share is unreachable on a phone

The Files app on the phone shows the Android app's shares, and reports a failure as the code's sentence.

| Symptom                                                               | Cause                                                                | Fix                                                                                                                |
| --------------------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `share_unreachable`, with the hub's row not **Connected**             | the phone cannot reach the hub's port 8443                           | bring the hub's row to **Connected** through any way in on **Access**: the LAN, NetBird, EasyTier or the SSH Relay |
| `share_unreachable` while the hub's row reads **Connected**           | the machine that serves the share is off or not connected to the hub | bring the machine back                                                                                             |
| Files reads **Give this share's password on the Files screen first.** | the share has no login on this phone yet                             | open the share on the app's **Files** screen, enter the username and password, and select **Connect**              |

## A remote desktop does not open

| Symptom                  | Cause                                                                     | Fix                                                                               |
| ------------------------ | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `rdp_viewer_open`        | a viewer is already open on that desktop from this client                 | close the open viewer, then select **Connect** again                              |
| `rdp_nobody_seated`      | nobody is signed in at the sharing machine's screen                       | sign in at that machine's own screen                                              |
| `rdp_screen_not_allowed` | the sharing machine's desktop has not allowed screen sharing yet          | allow screen sharing one time at that machine's own screen                        |
| `rdp_permissions_needed` | the Mac has not given RustDesk **Screen Recording** and **Accessibility** | grant both to RustDesk in that Mac's **System Settings** > **Privacy & Security** |

## An AI tool ignores the gateway

| Symptom                                                                            | Cause                                                                                            | Fix                                                                                                                    |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `no_endpoint`                                                                      | the hub has issued this client no key                                                            | on the hub's **AI** page, revoke the client's key so a new one is issued, or join the client again                     |
| the tools keep their own configuration after **Save** in **AI tool configuration** | **Save** keeps the model choices and points nothing                                              | switch on **The AI tools use this gateway** on the entry's row; `nclient service ai show` prints where the tools point |
| the panel reads `gateway_unreachable`                                              | the gateway process is down                                                                      | run `systemctl status neutrino_hub_cliproxyapi` on the hub                                                             |
| a tool reaches nothing                                                             | the tools point at the client's forward on `127.0.0.1`, which listens only while the client runs | start the client, or keep it running in the tray                                                                       |
| `login_expired`                                                                    | a subscription sign-in on the **AI** page took too long                                          | select **Sign in** again and finish it in the browser                                                                  |
| a machine's account row reads `cc_switch_download_failed`                          | the agent could not download cc-switch from the hub                                              | check that the hub reaches the internet, then turn the **Global configuration** switch off and on again                |
| the client's **AI** page is greyed with `ai_tools_managed`'s sentence              | the Neutrino agent is installed on this computer, and it sets the AI tools                       | set the AI tools on the hub's **Modules** page, under **Global configuration** for this machine                        |

## Where the logs are

| What                           | Where                                                                                                                                                                                                                     |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| the setup run                  | `setup.log` in the hub's log directory, `/var/log/neutrino/hub/setup.log` on Linux                                                                                                                                        |
| the hub on Linux               | each unit's journal: `journalctl -u neutrino_hub_web -n 200`, and likewise `neutrino_hub_xray`, `neutrino_hub_dnsmasq`, `neutrino_hub_cliproxyapi`, `neutrino_hub_netbird`, `neutrino_hub_easytier`, `neutrino_hub_relay` |
| the hub on macOS and Windows   | one `<name>.log` per process in `/Library/Logs/Neutrino/hub/` on macOS and `C:\ProgramData\Neutrino\hub\log\` on Windows                                                                                                  |
| a hub update                   | `journalctl -u neutrino_hub_update` on Linux; `hub_update.log` in the hub's log directory on macOS and Windows                                                                                                            |
| the agent on Linux             | `journalctl -u neutrino_agent -n 200` on that machine                                                                                                                                                                     |
| the agent on Windows           | `C:\ProgramData\Neutrino\agent\log\agent.log`                                                                                                                                                                             |
| the agent on macOS             | `/Library/Logs/Neutrino/agent/agent.log`                                                                                                                                                                                  |
| the desktop client             | `client.log` in `~/.config/neutrino/client/` on Linux, `~/Library/Logs/Neutrino/client/` on macOS, and `%LOCALAPPDATA%\Neutrino\client\` on Windows                                                                       |
| the client's EasyTier daemon   | `/var/log/neutrino/client/` on Linux, `/Library/Logs/Neutrino/client/` on macOS, and `C:\ProgramData\Neutrino\client\log\` on Windows                                                                                     |
| the AI gateway, from the panel | **Journal** on the **AI** page                                                                                                                                                                                            |
| what a render produces         | `sudo nhub apply --dry-run` on the hub                                                                                                                                                                                    |
