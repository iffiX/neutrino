---
title: Troubleshooting
---

# Troubleshooting

Find the code or the words on your screen in the section named after the place they appear; each row gives the cause and the fix. In the tables, `<hub>` stands for the address of the machine that runs the hub.

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

| Symptom                                                                                      | Cause                                                                                                                 | Fix                                                                                                      |
| -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **Locked after repeated failures.**                                                          | too many wrong passwords                                                                                              | run `sudo nhub unlock` on the hub; it also lifts every fail2ban SSH ban                                  |
| **Wrong password.** and it is forgotten                                                      | the panel password is lost                                                                                            | run `sudo nhub reset password` on the hub; every session is signed out                                   |
| the vault passphrase is lost                                                                 | the running hub still reads the vault with its own working key; a backup taken under the lost passphrase stays sealed | run `sudo nhub vault rekey` on the hub to set a new passphrase, then download a new backup               |
| `vault_locked`, on a client's row or a module, or **Vault locked** on the **SSH Relay** card | the box has no working copy of the vault's data key, so nothing stored in the vault opens                             | restore a backup under **Settings** with its vault passphrase; the restore writes the working copy again |

## The Credentials page rejects a key

| Symptom                 | Cause                          | Fix                                                                |
| ----------------------- | ------------------------------ | ------------------------------------------------------------------ |
| `key_is_public`         | the pasted key is a public key | paste the private key, with its BEGIN and END lines                |
| `key_passphrase_needed` | the private key is encrypted   | fill **Key passphrase** with the key's passphrase, then save again |

## Restoring a backup fails

With any of these codes, nothing is restored.

| Symptom                         | Cause                                                                                          | Fix                                                                   |
| ------------------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `backup_wrong_extension`        | the file is not a backup this panel writes                                                     | pick the archive that **Download backup** saved                       |
| `backup_corrupt`                | the archive is damaged                                                                         | download the backup again, or pick an older one                       |
| `vault_passphrase_wrong`        | the passphrase does not open this backup                                                       | type the passphrase that was set when the backup was taken            |
| `backup_mode_unavailable`       | the backup sets a mode this hub does not offer, such as a side gateway on the mainland edition | restore it on a hub of the full edition, on Linux                     |
| the restore's apply stops short | the files are restored, and one step of the apply failed                                       | fix the cause the dialog names, then run `sudo nhub apply` on the hub |

## A device is offline

| Symptom                                                 | Cause                                                          | Fix                                                                                                     |
| ------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `agent_offline`, in the panel or on a client's row      | the machine's agent is not connected to the hub                | on the machine, run `sudo nagent status`; when it reads the service as stopped, run `sudo nagent start` |
| the machine is listed and its modules cannot be changed | an offline machine rejects every change, and nothing is queued | bring the machine back, then apply again                                                                |

## A program is turned away by the hub

An agent shows these codes in `nagent status`. A client shows them as words on its hub row, listed under [The state line of a hub row](#the-state-line-of-a-hub-row).

| Symptom            | Cause                                                                                                           | Fix                                                                                                                                                                                                                           |
| ------------------ | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `protocol_too_old` | the program is a 0.3 or 0.4 package, which speaks an older protocol than a 0.5.0 hub accepts                    | install the 0.5.0 package on that machine, which `nagent --version` confirms, and join with a new link. A 0.4 hub cannot be upgraded to 0.5.0: remove it and install 0.5.0 fresh, as [Settings](../hub/settings.md) describes |
| `protocol_too_new` | the program speaks a newer protocol than the hub                                                                | update the hub under **Settings**; the binding stays and the program connects again                                                                                                                                           |
| `hub_untrusted`    | the hub was reset or installed again, and its certificate changed                                               | join again with a fresh link, from **Add by link** on **Devices** for an agent and from **Clients** for a client                                                                                                              |
| `binding_unknown`  | the machine's row was removed on the hub's **Devices** or **Clients** page, and the program deleted its binding | join again with a new link                                                                                                                                                                                                    |

## Joining a hub fails

| Symptom                                                                      | Cause                                                                                              | Fix                                                                                                                   |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `link_not_for_client` or `link_not_for_agent`                                | the link is for the other kind of program: **Clients** makes client links, **Devices** agent links | make a link on the right page                                                                                         |
| `link_unreadable`                                                            | the pasted link is cut off                                                                         | copy the whole link again                                                                                             |
| `ticket_spent`                                                               | the link is used or older than 30 minutes                                                          | on a client, select **Leave** on the row; then join with a new link                                                   |
| `admission_paused`                                                           | the hub paused joins after too many failed ones                                                    | leave the client running; it joins again after the seconds the code names                                             |
| `unsupported_remote_install`, in the **Install agent** dialog on **Devices** | the machine reports a system other than Linux, and the SSH installer is for Linux                  | install the agent on the machine itself and join it with a link, as [Install an agent](../install/agent.md) describes |

## The state line of a hub row

The client window and the Android app show these words under a hub's name. A countdown runs live, and at 0 the line reads **Connecting…** again.

| Symptom                                                     | Cause                                                                                  | Fix                                                                                  |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| **Connecting…** for a long time                             | the client is dialling every address of the hub, and a dial waits out its connect time | wait for the round to end; the line then names a reason                              |
| **The hub did not answer · retrying in 5 s**                | no address of the hub answered, and the device is not on the hub's virtual network     | check that the hub runs and that the device reaches one way in, then select refresh  |
| **The hub is not on the virtual network · retrying in 5 s** | no address answered while the device is on the hub's virtual network                   | check the hub's badge for that network on its **Access** page                        |
| **No network**                                              | the device has no network at all                                                       | connect the device to a network; the client dials when one comes up                  |
| **Certificate mismatch · retrying in 60 s**                 | the certificate at the hub's address differs from the one the link pinned              | after a reset or a new install of the hub, select **Leave** and join with a new link |
| **The hub pauses new devices · retrying in 60 s**           | the hub paused joins after too many failed ones                                        | leave the client running; it joins again when the countdown ends                     |
| **The hub does not know this device**                       | the hub's **Clients** page no longer lists this client                                 | select **Leave**, the row's only button, then join with a new link                   |
| **Version too old**                                         | the client and the hub speak different protocol numbers                                | update the older of the two, then select refresh                                     |
| **Join refused ·** and the reason                           | the hub rejected the link's ticket, as for a used or expired link                      | select **Leave**, then join with a new link from **Clients**                         |
| **Replaced by another client · Reconnect**                  | another client connected to the hub as this one                                        | select **Reconnect** to take the hub back                                            |
| **Disabled by the hub**                                     | the client is switched off on **Clients**, and every action returns `client_disabled`  | select **Enable** on its row there; the line changes by itself                       |

## The client does not connect

| Symptom                 | Cause                                                  | Fix                                                                         |
| ----------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------- |
| `hub_unreachable`       | port 8443 on the hub is unreachable from this computer | check the network, the ways in on **Access**, and **Exposure** on the hub   |
| `gui_webkitgtk_missing` | WebKitGTK is absent on Linux                           | install the packages the message names, then start the client again         |
| `gui_webview2_missing`  | WebView2 is absent on Windows                          | install the runtime the message names, then start the client again          |
| `root_refused`          | the client was started with `sudo`                     | start it from your own account                                              |
| `client_held`           | another account's client runs on this computer         | quit the client in that account, or sign that account out, then start yours |

## The virtual network does not connect

These show on a hub row's **Virtual network** line, in the desktop client and in the Android app. The client tries a failed connect only when you select **Connect** again.

| Symptom                                                                                             | Cause                                                                                                       | Fix                                                                                                                                                                   |
| --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Connecting…** with **This machine is registered with the console. Attach it to a network there.** | in console mode, the console has not attached the device to a network yet                                   | attach the device to the hub's network in the EasyTier console, as [EasyTier](../hub/easytier.md) describes                                                           |
| `overlay_join_failed`, with the engine's own words after it                                         | NetBird or EasyTier rejected the join; with NetBird, the hub often holds a one-time setup key already spent | create a reusable key in the NetBird console, paste it with **Replace** on the NetBird card, then select **Connect** again, as [NetBird](../hub/netbird.md) describes |
| `overlay_other_network`                                                                             | this device is on another NetBird network or on another hub's virtual network                               | on the other hub's row, select **Disconnect** on its virtual network line, then connect this one                                                                      |
| `overlay_daemon_down`                                                                               | the NetBird or EasyTier service on this computer is stopped                                                 | reinstall the client                                                                                                                                                  |
| `bundle_missing`                                                                                    | this install has no NetBird or EasyTier                                                                     | reinstall the client                                                                                                                                                  |
| `overlay_no_address`                                                                                | the engine gave the device no address within 90 seconds                                                     | check the device's own network, then select **Connect** again                                                                                                         |
| `overlay_console_invalid`                                                                           | EasyTier cannot use the console address the hub named                                                       | correct the console address on the hub's EasyTier card and apply                                                                                                      |
| `overlay_withdrawn`                                                                                 | the hub no longer publishes that network to this client                                                     | turn the network on again on the hub's **Access** page, or add the virtual network to the client's permission on **Clients**                                          |

## Access

| Symptom                                                                                        | Cause                                                                                          | Fix                                                                                                                                                                                                           |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| turning an engine on, or saving an EasyTier address, is rejected with `overlay_subnet_overlap` | the engine's network overlaps the other engine's or a network the hub holds an address on      | change EasyTier's **This box's address** or the LAN's address on **Network**; NetBird's network is always `100.64.0.0/10`                                                                                     |
| the **Access** page shows `overlay_default_route_refused` in red                               | a peer or the console gave the hub a default route through the network, and the hub deleted it | remove the exit route for the hub in the NetBird or EasyTier console; the hub keeps its own uplink as the way out                                                                                             |
| `overlay_route_overlap` with **The hub cannot take it away**                                   | a route on the network overlaps one of the hub's networks, and the hub could not deselect it   | change or remove that route in the NetBird or EasyTier console                                                                                                                                                |
| `direct_host_invalid`                                                                          | **Public address** under the **Direct** card is neither a host name nor an IP address          | type a host name or an IP address, then select **Apply access**                                                                                                                                               |
| `easytier_config_server_invalid`                                                               | the pasted text is neither a console address nor a token                                       | paste the whole address after `--config-server`, of the form `tcp://host:22020/token`                                                                                                                         |
| `easytier_invalid`                                                                             | **Manual bootstrap peers** is chosen and no bootstrap peer is listed                           | add at least one bootstrap peer, then apply again                                                                                                                                                             |
| the hub does not respond on a virtual network                                                  | that network is not in **Exposure**                                                            | tick it under **Exposure** on **Network**                                                                                                                                                                     |
| NetBird's badge reads **not joined**                                                           | the hub has no NetBird identity, or its last login expired                                     | join again with a new setup key                                                                                                                                                                               |
| NetBird's badge reads **management unreachable**                                               | the hub cannot reach NetBird's management server                                               | on the hub, check the uplink, that DNS resolves the management server's name, and the management URL                                                                                                          |
| NetBird's badge reads **not running**                                                          | NetBird is stopped                                                                             | turn the card on and select **Apply access**                                                                                                                                                                  |
| NetBird's **Peers** is empty                                                                   | no other device has joined the network                                                         | on a client, select **Connect** on the hub row's virtual network line                                                                                                                                         |
| a client reaches the hub over NetBird and the hub's LAN devices stay unreachable               | the console has no access policy for the LAN route                                             | add the network and its policy in the NetBird console, as [LAN devices over NetBird](../scenarios/netbird_lan_routes.md) describes                                                                            |
| EasyTier reads **No machine has joined yet.**                                                  | the other machine's network name or secret differs                                             | copy the command again with **Copy with the secret**                                                                                                                                                          |
| a device joins over EasyTier and the hub's LAN devices stay unreachable                        | the LAN subnet is not routed on the network                                                    | in manual mode, add the subnet under **Exported networks** and apply; in console mode, add it as a subnet proxy in the console, as [LAN devices over EasyTier](../scenarios/easytier_lan_routes.md) describes |
| the **SSH Relay** card's **Status** reads **Not configured**                                   | **Server**, **Account**, or the key or login is empty or gone                                  | fill in the settings and select **Apply SSH Relay**                                                                                                                                                           |
| **Authentication failed**                                                                      | the server rejected the key or the password                                                    | check the key's line in the account's `authorized_keys`, or the password and `PasswordAuthentication`                                                                                                         |
| **Forward refused**                                                                            | the server refused the listener, or another program holds the port                             | check that `permitlisten` names the **Public port**, and free the port on the server                                                                                                                          |
| **Public port closed**                                                                         | the forward runs, and the public address returns no answer or another certificate              | check `GatewayPorts clientspecified`, the provider's firewall and the server's firewall                                                                                                                       |
| **Host key changed**                                                                           | the server presents a key other than the one recorded                                          | if you replaced or reinstalled the server, select **Forget host key**                                                                                                                                         |
| **Server unreachable**                                                                         | SSH could not reach the server, or the connection dropped                                      | check **Server** and **SSH port**, and that the server is up                                                                                                                                                  |

## Network settings are refused

| Symptom                                                                                                                  | Cause                                                              | Fix                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `network_invalid` with the field `role`: the panel reads that the port cannot answer with the role **Disabled**          | a port ticked under **Exposure** has the role **Disabled**         | give the port the role **WAN** or **LAN**, or untick it under **Exposure**, then apply again      |
| **Country code** reads **Two letters, such as DE. 5 GHz needs one.**, or `network_invalid` with the field `country_code` | an access point on 5 GHz has no valid two-letter country code      | type the code of the country the hub is in under **Country code**, such as `DE`, then apply again |
| `port_out_of_range`, on the **Network**, **Access**, **Proxy** or **Settings** page                                      | a port field holds a number outside 1 to 65535                     | type a port from 1 to 65535, then apply again                                                     |
| `port_already_in_use`                                                                                                    | another program on the hub's computer already listens on that port | pick another port, or stop the program that holds it                                              |
| `resolver_required`, on the **Proxy** page                                                                               | the **Remote resolvers (proxied names)** list is empty             | add at least one resolver, then select **Apply route**                                            |

## Errors on the Modules page

A tab of the **Modules** page shows these codes under its state word or on a row, and a refused apply names one.

### Every module

| Symptom                                                                                 | Cause                                                  | Fix                                                                                                       |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| `module_fetch_failed`, with the download's own words after it                           | the hub could not download the module's install file   | check that the hub reaches the internet, then select **Install** again                                    |
| a module is greyed with **This machine's system cannot run it**, or `no_platform_build` | the module has no build for this machine's system      | pick another machine; [Supported platforms](./platforms.md#modules-by-system) lists each module's systems |
| `gitea_git_missing`                                                                     | a Mac or a Windows machine has no usable git for Gitea | install git, then select **Install** again                                                                |

### Instances of VS Code, code-server and CloudCLI

These codes also come from the **Terminal** tab and from the accounts under **Global configuration**.

| Symptom              | Cause                                                                      | Fix                                                                            |
| -------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `account_unknown`    | the machine has no account by that name                                    | type the name of an account that exists on the machine, or create it there     |
| `account_invalid`    | the name cannot be an account name on that machine                         | type a valid account name                                                      |
| `account_duplicate`  | two instances name the same account                                        | remove one of them                                                             |
| `port_duplicate`     | two instances use the same port                                            | give each instance its own **Port**                                            |
| `port_invalid`       | the port is outside 1024 to 65535                                          | type a port in that range                                                      |
| `credential_missing` | a Windows instance has no login picked                                     | pick the account's login under **Windows login for** the account               |
| `credential_invalid` | Windows no longer accepts the instance's login, as after a password change | add a login with the new password on **Credentials**, pick it, and apply again |
| `token_missing`      | the hub sent no connection token for the instance                          | apply the module again                                                         |
| `secret_missing`     | the hub sent no token secret for a code-server instance                    | apply the module again                                                         |

### CloudCLI

| Symptom                          | Cause                                                                          | Fix                                                                                                                         |
| -------------------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `cloudcli_node_download_failed`  | Node.js for CloudCLI could not be fetched or unpacked                          | check that the machine reaches the internet, then select **Apply CloudCLI**                                                 |
| `cloudcli_npm_install_failed`    | npm failed to install CloudCLI for the account; the row shows npm's last lines | fix what npm's lines name, then select **Apply CloudCLI**                                                                   |
| `cloudcli_native_module_failed`  | better-sqlite3, node-pty or bcrypt could not fetch its prebuilt binary         | check the machine's internet access, then select **Apply CloudCLI**                                                         |
| `cloudcli_install_out_of_memory` | the machine ran out of memory during the npm install                           | free memory on the machine, then select **Apply CloudCLI**                                                                  |
| `cloudcli_port_taken`            | another program on the machine holds the instance's port                       | change the instance's **Port**, then apply again                                                                            |
| `cloudcli_register_failed`       | the account's CloudCLI already has an administrator with another password      | wait: the agent starts that CloudCLI afresh with a new sign-in file, then signs in again every 30 seconds until it succeeds |

### VS Code

| Symptom              | Cause                                                         | Fix                                                         |
| -------------------- | ------------------------------------------------------------- | ----------------------------------------------------------- |
| `terms_not_accepted` | nobody accepted Microsoft's terms for VS Code on this machine | select **Open and accept the terms** on the **VS Code** tab |

### code-server

| Symptom                       | Cause                                                    | Fix                                                                   |
| ----------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------- |
| `code_server_download_failed` | the release could not be fetched or unpacked             | check that the machine reaches the internet, then apply again         |
| `code_server_port_taken`      | another program on the machine holds the instance's port | change the instance's **Port** and select **Apply code-server** again |

### Remote desktop

The tab, the device's drawer on **Devices**, and a client's **Connect** show these codes. **Apply remote desktop** tries a failed step again.

| Symptom                  | Cause                                                                     | Fix                                                                               |
| ------------------------ | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `rdp_takeover_failed`    | a step of starting the agent's RustDesk failed; the code names the step   | fix what the step names, then select **Apply remote desktop**                     |
| `rdp_restore_failed`     | a step of putting back the machine's own RustDesk failed                  | fix what the step names, then select **Apply remote desktop**                     |
| `rdp_nobody_seated`      | nobody is signed in at the machine's screen                               | sign in at that machine's own screen                                              |
| `rdp_screen_not_allowed` | a Wayland session has not allowed screen sharing                          | allow screen sharing one time at that machine's own screen                        |
| `rdp_permissions_needed` | the Mac has not given RustDesk **Screen Recording** and **Accessibility** | grant both to RustDesk in that Mac's **System Settings** > **Privacy & Security** |

### Terminal

| Symptom                  | Cause                                                   | Fix                                                             |
| ------------------------ | ------------------------------------------------------- | --------------------------------------------------------------- |
| `path_invalid`           | the shell program is not a full path                    | type the program's full path, or pick it with **Browse…**       |
| `shell_program_unusable` | the program is missing on the machine, or it cannot run | pick a program that exists and runs, or clear **Shell program** |

### AI tools

| Symptom                                                                               | Cause                                                        | Fix                                                                       |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------- |
| `switch_failed`                                                                       | cc-switch could not point the account's tools at the gateway | read the words on the account's row, then turn the setting off and on     |
| `cc_switch_download_failed`                                                           | the machine could not get cc-switch from the hub             | check that the hub reaches the internet, then turn the setting off and on |
| **cc-switch did not put the tools back to their own settings:** and cc-switch's words | the switch back failed, and the control stays on             | fix what cc-switch printed, then select the control again                 |

## A client page cannot reach its service

The hub or the agent of the providing machine returns these codes, and the client shows them on the entry's row.

| Symptom                             | Cause                                                                                                      | Fix                                                           |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `connect_failed` with `refused`     | nothing listens on the service's port on that machine                                                      | start the service, or the module, on that machine             |
| `connect_failed` with `timeout`     | the service did not respond within 10 seconds                                                              | check that the machine and the service are up                 |
| `connect_failed` with `unreachable` | the hub has no route to a service declared by hand on **Services**                                         | check the declared address, and that the hub's LAN reaches it |
| `port_not_published`                | the machine stopped publishing the port: the container, the instance or the share stopped                  | start it again on the **Modules** page                        |
| `connect_limit`                     | the client has 256 connections open through the hub                                                        | close forwards or programs the client does not need           |
| `permission_denied`                 | the client's permission on **Clients** leaves out that kind of entry, that machine, terminals or the panel | widen the client's permission on **Clients**                  |
| `service_unknown`                   | the hub no longer publishes the entry                                                                      | select refresh; the entry leaves the list                     |
| `port_taken`                        | another program on this computer listens on the entry's **Fixed** local port                               | select **Configure** on the row and pick another port         |
| `web_token_missing`                 | the hub sent no token for a VS Code, code-server or CloudCLI entry                                         | select **Open** again                                         |

## A share does not mount on a computer

| Symptom                                  | Cause                                                                                                  | Fix                                                                                                                       |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `mountpoint_invalid`                     | the path is outside your home                                                                          | give a folder under your home, such as `~/nas/media`                                                                      |
| `mountpoint_not_drive_letter`            | Windows mounts a share at a drive letter                                                               | pick an unused letter, such as `N:`                                                                                       |
| `mountpoint_not_empty`                   | the folder holds files                                                                                 | pick an empty folder                                                                                                      |
| `mountpoint_in_use`                      | another entry, from any hub, mounts at that path                                                       | pick another folder or drive                                                                                              |
| `mount_not_authorized`                   | the polkit prompt or the macOS login dialog was dismissed                                              | select **Mount** again and confirm the prompt                                                                             |
| `mount_tooling_missing`                  | `mount.cifs` or the client's mount helper is absent                                                    | install the client package again, which depends on `cifs-utils`                                                           |
| `pkexec_missing`                         | the computer has no `pkexec`, which a mount on Linux goes through                                      | install the `pkexec` package, then select **Mount** again                                                                 |
| `mount_timed_out`                        | on macOS, the system did not finish the mount within ten minutes                                       | select **Mount** again                                                                                                    |
| `credentials_missing`                    | the saved credentials file is gone                                                                     | select **Configure** and type the password again                                                                          |
| `share_login_rejected`                   | the share rejected the username or the password                                                        | select **Configure** and enter both again                                                                                 |
| `share_access_denied`                    | the share accepts the login and denies that account access                                             | pick the user under **Who may use it** for that share on the **Modules** page                                             |
| `share_not_found`                        | the host has no share by that name                                                                     | check the share on the **Modules** page or on **Services**                                                                |
| `share_session_conflict`                 | Windows holds a connection to that server under another login                                          | disconnect that connection in Windows, then select **Mount** again                                                        |
| `files_adapter_unavailable` on Windows   | the `NeutrinoClientFiles` service is missing, stopped or failing, so the files adapter could not start | read the words after the code, run `sc query NeutrinoClientFiles`, and install the client again if the service is missing |
| `files_adapter_in_use` on Windows        | another account's client holds the files adapter                                                       | quit the client in that account, or sign that account out; the mount runs again after that                                |
| the row is greyed, **Not reachable now** | the serving machine is off or not connected to the hub                                                 | bring the machine back                                                                                                    |

A computer shows `share_unreachable` for the same causes as a phone, listed in the next section.

## A share is unreachable on a phone

The Files app on the phone shows the Android app's shares, and reports a failure as the code's sentence.

| Symptom                                                               | Cause                                                                | Fix                                                                                                                |
| --------------------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `share_unreachable`, with the hub's row not **Connected**             | the device cannot reach the hub's port 8443                          | bring the hub's row to **Connected** through any way in on **Access**: the LAN, NetBird, EasyTier or the SSH Relay |
| `share_unreachable` while the hub's row reads **Connected**           | the machine that serves the share is off or not connected to the hub | bring the machine back                                                                                             |
| Files reads **Give this share's password on the Files screen first.** | the share has no login on this phone yet                             | open the share on the app's **Files** screen, enter the username and password, and select **Connect**              |

## A terminal closes

| Symptom             | Cause                                                                                          | Fix                                                                   |
| ------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `session_not_owned` | the session belongs to another viewer and is not shared                                        | ask its owner to switch on **Shared**, or open a terminal of your own |
| `session_unknown`   | the session ended, or the agent restarted or updated, which ends every session on that machine | open a new terminal on the machine                                    |
| `shell_unknown`     | the hub no longer holds the shell the client resized                                           | close the terminal in the client and open it again                    |
| `unknown_terminal`  | the hub offers no terminal on that machine, or `nclient terminal` named an unknown machine     | pick a machine the client's **Terminals** page lists                  |

## A remote desktop does not open

A code about the sharing machine's screen, such as `rdp_nobody_seated`, is under [Remote desktop](#remote-desktop).

| Symptom                                          | Cause                                                     | Fix                                                              |
| ------------------------------------------------ | --------------------------------------------------------- | ---------------------------------------------------------------- |
| the page reads **No shared remote desktops yet** | no machine is sharing, or the sharing machine is offline  | turn on **Share this machine's desktop** on that machine's tab   |
| `rdp_viewer_open`                                | a viewer is already open on that desktop from this client | close the open viewer, then select **Connect** again             |
| `rdp_not_shared`                                 | the machine stopped sharing                               | turn the share on again on that machine's **Remote desktop** tab |
| `rdp_no_desktop`                                 | this session has no screen to open a viewer on            | connect from a desktop session                                   |
| `rdp_launch_failed`                              | the viewer did not start, with the reason after the code  | fix the reason, then select **Connect** again                    |

## An AI tool ignores the gateway

| Symptom                                                                            | Cause                                                                                            | Fix                                                                                                                    |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `no_endpoint`                                                                      | the hub has issued this client no key                                                            | on the hub's **AI** page, revoke the client's key so a new one is issued, or join the client again                     |
| `no_exit_hub`                                                                      | the switch was turned on for a hub that is not connected                                         | wait until the hub's row reads **Connected**, then turn the switch on                                                  |
| the tools keep their own configuration after **Save** in **AI tool configuration** | **Save** keeps the model choices and points nothing                                              | switch on **The AI tools use this gateway** on the entry's row; `nclient service ai show` prints where the tools point |
| the panel reads `gateway_unreachable`                                              | the gateway process is down                                                                      | run `systemctl status neutrino_hub_cliproxyapi` on the hub                                                             |
| a tool reaches nothing                                                             | the tools point at the client's forward on `127.0.0.1`, which listens only while the client runs | start the client, or keep it running in the tray                                                                       |
| `login_expired`                                                                    | a subscription sign-in on the **AI** page took too long                                          | select **Try again** and finish the sign-in in the browser                                                             |
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
