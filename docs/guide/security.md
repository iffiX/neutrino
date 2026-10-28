---
title: Security
---

# Security

The hub and the agent run as root, and the client runs as your own account. Your phone and laptop connect to the hub's port 8443 alone, and every service they open runs inside that one connection. A device gets past that port only after it joins with a link from the panel. The later sections say where the hub keeps keys and passwords, and which servers it contacts.

## Why the hub runs as root

The hub writes firewall rules, installs packages and starts and stops services, and each of these takes root. It runs as a systemd service on Linux, as the root LaunchDaemon `com.neutrino.hub` on macOS, and as the SYSTEM service `neutrino_hub` on Windows.

On Linux the hub's unit takes away what the hub does not use. It blocks setuid programs, realtime scheduling, changes to the clock, and every socket family but the five the hub needs. Package installs run in a separate unit of their own.

The hub is root already, so the panel stores no sudo password for its own computer. The sudo passwords it keeps belong to managed devices, and the hub uses each one over SSH to its device.

| Package | Runs as                                       |
| ------- | --------------------------------------------- |
| Hub     | root, or SYSTEM on Windows                    |
| Agent   | root, or SYSTEM on Windows                    |
| Client  | your own account; on Android, an ordinary app |

On a managed machine, VS Code and CloudCLI run as the account each instance names. A terminal a client opens on a machine, the hub's own computer included, runs as root, or as the account the machine's **Terminal** module names. Only clients with the **Terminals** permission on the **Clients** page open one.

## Who gets in when port 8443 is open

A device joins the hub with a link that a person signed in to the panel creates. The link holds the fingerprint of the hub's certificate and a ticket that works once, for 30 minutes. After the join, the device connects with a token of its own, and the hub keeps only a hash of that token.

The hub limits connections that have not joined yet:

- The hub closes a connection that sends nothing for 3 seconds (10 on Windows), and one that presents no valid token within 30 seconds.
- At most 128 such connections stay open at once, and the hub closes the oldest to make room for a new one.
- After 30 failed joins within 60 seconds, the hub pauses every new join until the oldest failure is a minute old. Devices that joined before connect as usual.

A joined client opens only the kinds of service and the machines that its row on the **Clients** page allows. Turning a client off or deleting it closes its connections at once. On a new hub the default permissions leave out the panel. A client opens the panel only after you turn it on for that client.

**Direct**, the way in through a port forward on your home router, opens the connection port alone, 8443 by default. On every system, the hub's other ports, the panel's among them, accept connections only from the senders in the segments switched on under **Exposure** on the **Network** page. A port forward to 8443 leaves the panel's own ports closed to the internet. The AI gateway listens on the hub's own loopback alone, and clients and managed machines reach it through the connection port.

The hub's firewall rules cover its own ports alone. SSH and every other service on the hub's computer are open or closed by the system's own firewall, in router mode too.

## The panel

The panel listens on an HTTP port and an HTTPS port, 8080 and 443 unless setup chose others. Until you select **Enable HTTPS** on the **Settings** page, a browser can sign in over plain HTTP.

The HTTPS certificate comes from a certificate authority the hub makes for itself. The authority signs only for private address ranges and local names such as `localhost`, so a browser trusts it for no public website.

Repeated wrong passwords lock the sign-in. [Troubleshooting](./reference/troubleshooting.md) says how to lift the lock.

## Where keys and passwords are kept

The paths are the Linux ones. On macOS and Windows the same files are in the hub's `config` and `state` folders, which only root, or SYSTEM and the administrators, can open.

| What                                                                                   | Where                                                                                  | How                                                                                          |
| -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| SSH keys, logins and tokens from the **Credentials** page, your AI API keys among them | `/etc/neutrino/hub/credentials/vault.json`                                             | sealed with AES-256-GCM under a data key; the vault passphrase from setup wraps the data key |
| the data key the hub works with                                                        | `/var/lib/neutrino/hub/vault.key`                                                      | readable by root alone                                                                       |
| the panel password                                                                     | `/etc/neutrino/hub/web/settings.json`                                                  | a scrypt hash                                                                                |
| the keys clients use for the AI gateway                                                | `/etc/neutrino/hub/cliproxyapi/cliproxyapi.json`                                       | sealed under the same data key                                                               |
| the SakuraFrp access key and the OpenFrp login                                         | `/etc/neutrino/hub/overlay/sakurafrp.json`, `/etc/neutrino/hub/overlay/openfrp.json`   | sealed under the same data key                                                               |
| the picked tunnel's frpc file, which holds the vendor account's token                  | `/var/lib/neutrino/hub/sakurafrp/frpc.toml`, `/var/lib/neutrino/hub/openfrp/frpc.toml` | readable by root alone; a backup leaves it out, and the hub fetches it from the vendor again |
| AI subscriptions you signed in to                                                      | `/var/lib/neutrino/hub/cliproxyapi/auth/`                                              | token files the gateway writes; a backup leaves them out, and a restored hub signs in again  |
| an agent's token for its hub                                                           | `/etc/neutrino/agent/`                                                                 | a file readable by root alone                                                                |
| a client's token for each hub                                                          | `~/.config/neutrino/client` on Linux                                                   | in your own account's folder                                                                 |

A backup from the **Settings** page holds the vault as it is on disk. Opening it on another hub takes the vault passphrase.

## Where the hub connects to

The hub and the agents connect to these servers.

| Connection                                                               | When                                                                             | Server                                                           |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| update check                                                             | when the hub looks for a newer release                                           | `api.github.com`                                                 |
| release files                                                            | when you update the hub, or an agent needs a package the hub lacks               | `github.com`                                                     |
| Node.js and npm packages, for CloudCLI                                   | when CloudCLI installs                                                           | `nodejs.org`, `registry.npmjs.org`, `github.com`                 |
| code-server                                                              | when code-server installs                                                        | `github.com`                                                     |
| the VS Code CLI                                                          | when VS Code installs; the editor then fetches its server from Microsoft         | `vscode.download.prss.microsoft.com`                             |
| Gitea                                                                    | when Gitea installs                                                              | `dl.gitea.com`                                                   |
| WSL, Podman and the Podman machine image, for Containers                 | when Containers installs on Windows or macOS                                     | `github.com`                                                     |
| image tags                                                               | when the **Containers** tab lists an image's tags                                | `hub.docker.com`                                                 |
| STUN servers, for the shared desktop                                     | each time a machine's shared desktop starts                                      | `stun.l.google.com`, `stun.cloudflare.com`, `stun.nextcloud.com` |
| cc-switch, for a machine's AI tools                                      | when a machine's AI tools switch to the gateway                                  | `github.com`                                                     |
| the NetBird management server, and the signal and relay servers it names | while NetBird is on                                                              | the server the hub joins                                         |
| the EasyTier console                                                     | while the console address is set                                                 | the address you paste                                            |
| your SSH relay server                                                    | while the SSH relay is on                                                        | the server you name                                              |
| SakuraFrp's interface                                                    | when you save the access key, open or refresh the tunnel list, or apply a tunnel | `api.natfrp.com`                                                 |
| OpenFrp's interface and its login                                        | when you log in, open or refresh the tunnel list, or apply a tunnel              | `api.openfrp.net`, `access.openfrp.net`                          |
| each listed tunnel's node, for its latency                               | when the tunnel list opens or refreshes                                          | the vendor's nodes                                               |
| the picked tunnel's node                                                 | while SakuraFrp or OpenFrp has a tunnel picked and its card is on                | the node of that tunnel                                          |
| AI providers and subscriptions                                           | when an AI tool sends a request through the gateway                              | the ones you add                                                 |
| exit nodes                                                               | while the proxy is on                                                            | the nodes you import                                             |
| the proxy's test addresses                                               | while the proxy measures its exit nodes                                          | `www.gstatic.com`, `www.msftconnecttest.com`                     |

The computer's own services, such as DNS lookups and time sync, connect on their own. The operating system runs them, and they are outside this table.

## Removing Neutrino

[Uninstall](./uninstall.md) removes each package and lists what stays on the machine.
