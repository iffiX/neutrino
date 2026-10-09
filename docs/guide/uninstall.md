---
title: Uninstall
---

# Uninstall

Each Neutrino package comes off on its own. The hub comes off its computer, an agent off each managed machine, and a client off each phone and laptop. Removing the hub leaves the agent on the same computer installed, so that computer takes two removals. To remove everything, take the clients off first, then the agents, and the hub last, since a client and an agent leave through the hub.

## Hub

### Return the hub to a fresh state

To keep the hub installed and start it over, run one of these commands on the hub's computer. On Windows, run it without `sudo` in an administrator PowerShell.

| Command                   | What it does                                                                                                                                                    |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sudo nhub reset network` | hands the computer's network back: the firewall, the network engines and the resolver. It stops the panel and keeps the configuration                           |
| `sudo nhub reset all`     | hands the network back, returns the configuration to its first state, deletes the keys, tokens and certificate authorities the hub made, and stops the services |

Each command asks `[y/N]` before it acts, and `--yes` skips the question. After `nhub reset all` the vault is gone, so a backup from the **Settings** page is the only way to get the configuration back. The computer's own agent stays installed, and the panel returns after `sudo nhub setup`.

### Remove the hub package

On Linux, the package's removal runs `nhub reset network` before the files go, so the computer gets its network back.

| Command                        | Program files | Configuration, `/etc/neutrino/hub` | State and logs, `/var/lib/neutrino/hub` and `/var/log/neutrino/hub` |
| ------------------------------ | ------------- | ---------------------------------- | ------------------------------------------------------------------- |
| `sudo apt remove neutrino-hub` | deleted       | kept                               | kept                                                                |
| `sudo apt purge neutrino-hub`  | deleted       | deleted                            | deleted                                                             |
| `sudo dnf remove neutrino-hub` | deleted       | kept                               | kept                                                                |
| `sudo pacman -R neutrino-hub`  | deleted       | kept                               | kept                                                                |

After `dnf remove` or `pacman -R`, delete what stays with this command:

```bash
sudo rm -rf /etc/neutrino/hub /var/lib/neutrino/hub /var/log/neutrino/hub
```

On Windows, open **Settings** > **Apps** > **Installed apps** and uninstall **Neutrino Hub**. The removal runs `nhub reset network` itself, which deletes the hub's firewall rules. The configuration and the state under `C:\ProgramData\Neutrino\hub` stay.

On macOS, the hub's package has no uninstaller. These commands reset the hub, which deletes its configuration and keys, then stop it and delete every file the package installed. Download a backup from the **Settings** page first to keep the configuration for later:

```bash
sudo nhub reset all --yes
sudo launchctl bootout system/com.neutrino.hub
sudo rm -f /Library/LaunchDaemons/com.neutrino.hub.plist /usr/local/bin/nhub
sudo rm -rf "/Library/Application Support/Neutrino/hub" /Library/Logs/Neutrino/hub "/Applications/Neutrino Hub.app"
sudo pkgutil --forget com.neutrino.hub
```

## Agent

Remove the agent from each managed machine:

1. On the machine, run `sudo nagent leave`. On Windows, run `nagent leave` in an administrator PowerShell. The machine leaves its hub, and the agent stays installed.
1. Remove the package with the command for the machine's system, from the following table.
1. On the panel's **Devices** page, select the machine, then **Forget device**. The panel deletes the machine's row and its saved credentials.

| System         | Remove with                                                                     | What else the removal does                                                                                                        |
| -------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Debian, Ubuntu | `sudo apt remove neutrino-agent`                                                | runs `nagent service uninstall`; `sudo apt purge neutrino-agent` also deletes `/etc/neutrino/agent` and `/var/lib/neutrino/agent` |
| Fedora, RHEL   | `sudo dnf remove neutrino-agent`                                                | runs `nagent service uninstall`, and keeps `/etc/neutrino/agent`                                                                  |
| Windows        | **Settings** > **Apps** > **Installed apps**, then uninstall **Neutrino Agent** | runs `nagent service uninstall --yes`                                                                                             |
| macOS          | `sudo nagent service uninstall`                                                 | the package has no uninstaller, so this command also removes the agent itself, RustDesk and the package's receipt                 |

`nagent service uninstall` stops the agent and takes away what its modules added to run. That covers their services, launchd jobs, scheduled tasks and firewall rules, and the file share's fence. The shares, the accounts the modules created and the modules' data stay.

On a Mac, the agent's configuration and state stay after `nagent service uninstall`. Delete them with this command:

```bash
sudo rm -rf "/Library/Application Support/Neutrino/agent" /Library/Logs/Neutrino/agent
```

## Client

Remove the client from each phone and laptop:

1. In the client, on each hub's row, select **Leave**, then select **Press again to leave**. The hub deletes the client's row. On a computer, `nclient leave --yes` does the same from a terminal.
1. If the client's row is still on the panel's **Clients** page, select **Delete** on it.
1. Remove the app with the way for the device's system, from the following table.

| System         | Remove with                                                                      | What stays                                                                                               |
| -------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Debian, Ubuntu | `sudo apt remove neutrino-client`                                                | each person's `~/.config/neutrino/client`; `sudo apt purge neutrino-client` deletes it for every account |
| Fedora, RHEL   | `sudo dnf remove neutrino-client`                                                | each person's `~/.config/neutrino/client`                                                                |
| Windows        | **Settings** > **Apps** > **Installed apps**, then uninstall **Neutrino Client** | your configuration, while **Keep my configuration** is selected in the removal dialog                    |
| macOS          | the commands after this table                                                    | your `~/Library/Application Support/Neutrino/client`                                                     |
| Android        | uninstall the app as any other app                                               | nothing of the app                                                                                       |

On a Mac, the client's package has no uninstaller. These commands stop its NetBird and EasyTier services and delete what the package installed:

```bash
sudo launchctl bootout system/com.neutrino.client.netbird
sudo launchctl bootout system/com.neutrino.client.easytier
sudo rm -f /Library/LaunchDaemons/com.neutrino.client.netbird.plist /Library/LaunchDaemons/com.neutrino.client.easytier.plist /usr/local/bin/nclient
sudo rm -rf "/Applications/Neutrino Client.app" "/Library/Application Support/Neutrino/client" /Library/Logs/Neutrino/client
sudo pkgutil --forget com.neutrino.client
```

## What stays on the machine

These folders stay until you delete them: after a removal on Linux without a purge, on Windows, and after `nagent service uninstall` on a Mac. In the paths, `<package>` is `hub`, `agent` or `client`.

| Holds             | Linux                       | macOS                                                    | Windows                                    |
| ----------------- | --------------------------- | -------------------------------------------------------- | ------------------------------------------ |
| configuration     | `/etc/neutrino/`            | `/Library/Application Support/Neutrino/<package>/config` | `C:\ProgramData\Neutrino\<package>\config` |
| state             | `/var/lib/neutrino/`        | `/Library/Application Support/Neutrino/<package>/state`  | `C:\ProgramData\Neutrino\<package>\state`  |
| logs              | `/var/log/neutrino/`        | `/Library/Logs/Neutrino/`                                | `C:\ProgramData\Neutrino\<package>\log`    |
| a person's client | `~/.config/neutrino/client` | `~/Library/Application Support/Neutrino/client`          | `%APPDATA%\Neutrino\client`                |

An agent also leaves what its modules made: the shares, the accounts they created, CloudCLI's files in each home and the modules' data. Your own files and your Claude Code sessions stay as they were.
