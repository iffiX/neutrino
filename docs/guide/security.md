---
title: Security
---

# Security

This page lists what each Neutrino package runs as and who can connect to the hub. Its later sections say where the hub keeps keys and passwords, and which servers it contacts.

## Why the hub runs as root

The hub writes firewall rules, installs packages and starts and stops services, and each of these takes root. It runs as a systemd service on Linux, as the root LaunchDaemon `com.neutrino.hub` on macOS, and as the SYSTEM service `neutrino_hub` on Windows.

On Linux the hub's unit takes away what the hub does not use. It blocks setuid programs, realtime scheduling, changes to the clock, and every socket family but the five the hub needs. Package installs run in a separate unit of their own.

The hub is root already, so the panel stores no sudo password for its own computer. The sudo passwords it keeps belong to managed devices, and the hub uses each one over SSH to its device.

| Package | Runs as                                       |
| ------- | --------------------------------------------- |
| Hub     | root, or SYSTEM on Windows                    |
| Agent   | root, or SYSTEM on Windows                    |
| Client  | your own account; on Android, an ordinary app |

On a managed machine, VS Code and CloudCLI run as the account each instance names. A terminal a client opens runs as root, or as the account the machine's **Terminal** module names.

## Who gets in when port 8443 is open

A device joins the hub with a link that a person signed in to the panel creates. The link holds the fingerprint of the hub's certificate and a ticket that works once, for 30 minutes. After the join, the device connects with a token of its own, and the hub keeps only a hash of that token.

The hub limits connections that have not joined yet:

- The hub closes a connection that sends nothing for 3 seconds (10 on Windows), and one that presents no valid token within 30 seconds.
- At most 128 such connections stay open at once, and the hub closes the oldest to make room for a new one.
- After 30 failed joins within 60 seconds, the hub pauses every new join until the oldest failure is a minute old. Devices that joined before connect as usual.

A joined client opens only the kinds of service and the machines that its row on the **Clients** page allows. Turning a client off or deleting it closes its connections at once. On a new hub the default permissions leave out the panel, so a client opens the panel only after you turn it on for that client.

**Direct** opens port 8443 alone. The panel and the AI gateway answer only on the networks the **Exposure** section of the **Network** page lists, on Linux, macOS and Windows alike.

## The panel

The panel answers on an HTTP port and an HTTPS port, 8080 and 443 unless setup chose others. Until you select **Enable HTTPS** on the **Settings** page, a browser can sign in over plain HTTP.

The HTTPS certificate comes from a certificate authority the hub makes for itself. The authority is limited to private address ranges and local names such as `localhost`, so a browser rejects it for any public website.

Repeated wrong passwords lock the sign-in. [Troubleshooting](./reference/troubleshooting.md) says how to lift the lock.

## Where keys and passwords are kept

The paths are the Linux ones. On macOS and Windows the same files are in the hub's `config` and `state` folders, which only root, or SYSTEM and the administrators, can open.

| What                                                                        | Where                                            | How                                                                                          |
| --------------------------------------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| SSH keys, logins and tokens from the **Credentials** page, AI provider keys | `/etc/neutrino/hub/credentials/vault.json`       | sealed with AES-256-GCM under a data key; the vault passphrase from setup wraps the data key |
| the data key the hub works with                                             | `/var/lib/neutrino/hub/vault.key`                | readable by root alone                                                                       |
| the panel password                                                          | the hub's configuration                          | a scrypt hash                                                                                |
| the keys clients use for the AI gateway                                     | `/etc/neutrino/hub/cliproxyapi/cliproxyapi.json` | sealed under the same data key                                                               |
| AI subscriptions you signed in to                                           | `/var/lib/neutrino/hub/cliproxyapi/auth/`        | token files the gateway writes; a backup leaves them out, and a restored hub signs in again  |
| an agent's token for its hub                                                | `/etc/neutrino/agent/`                           | a file readable by root alone                                                                |
| a client's token for each hub                                               | `~/.config/neutrino/client` on Linux             | in your own account's folder                                                                 |

A backup from the **Settings** page holds the vault as it is on disk. Opening it on another hub takes the vault passphrase.

<!-- 待核: which file under /etc/neutrino/hub holds the panel password's hash; architecture.md says only "a scrypt hash". -->

## Where the hub connects to

The hub and the agents connect to these servers. The full edition uses the first address and the mainland edition the second.

| Connection                             | When                                                               | Full edition                                     | Mainland edition         |
| -------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------ | ------------------------ |
| update check                           | when the hub looks for a newer release                             | `api.github.com`                                 | `gitee.com`              |
| release files                          | when you update the hub, or an agent needs a package the hub lacks | `github.com`                                     | `gitee.com`              |
| Node.js and npm packages, for CloudCLI | when CloudCLI installs                                             | `nodejs.org`, `registry.npmjs.org`, `github.com` | `registry.npmmirror.com` |
| code-server                            | when code-server installs                                          | `github.com`                                     | `mirrors.ustc.edu.cn`    |
| cc-switch, for a machine's AI tools    | when a machine's AI tools switch to the gateway                    | `github.com`                                     | `gitee.com`              |
| the NetBird management server          | while NetBird is on                                                | the server the hub joins                         | none                     |
| the EasyTier console                   | while the console address is set                                   | the address you paste                            | the address you paste    |
| your SSH Relay server                  | while SSH Relay is on                                              | the server you name                              | the server you name      |
| AI providers and subscriptions         | when an AI tool sends a request through the gateway                | the ones you add                                 | the ones you add         |
| exit nodes                             | while the proxy is on                                              | the nodes you import                             | none                     |

The computer's own services, such as DNS lookups and time sync, connect on their own. The operating system runs them, and they are outside this table.

<!-- 待核: whether the VS Code module's download of the VS Code CLI, Gitea's download, and the overlays' own relay and signal servers belong in this table; install_and_dev.md names only the rows above. -->

## Removing Neutrino

[Uninstall](./uninstall.md) removes each package and lists what stays on the machine.
