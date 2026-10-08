---
title: Uninstall
---

# Uninstall

Each Neutrino package comes off on its own. The hub comes off its computer, an agent off each managed machine, and a client off each phone and laptop. Removing the hub leaves the agent on the same computer installed, so that computer takes two removals.

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

On Windows, open **Settings** > **Apps** > **Installed apps** and uninstall **Neutrino Hub**. The removal also deletes the hub's firewall rules. The configuration and the state under `C:\ProgramData\Neutrino\hub` stay.

<!-- 待核: whether the Windows hub's removal deletes C:\ProgramData\Neutrino\hub; no standard page or build script says. -->

On macOS, the hub's package has no uninstaller. `sudo nhub reset all` hands the network back and stops the hub. The program and its folders under `/Library/Application Support/Neutrino/hub`, the LaunchDaemon `com.neutrino.hub`, `/usr/local/bin/nhub` and `/Applications/Neutrino Hub.app` stay on the Mac.

<!-- 待核: how to take the hub off a Mac; build_hub_macos.py describes no removal, and no standard page gives one. -->

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

`nagent service uninstall` stops the agent and takes away what its modules added to run. That covers their services, launchd jobs, scheduled tasks and firewall rules, and the file share's fence. The shares, the accounts and the modules' data stay.

On a Mac, the agent's configuration and state stay after `nagent service uninstall`. Delete them with this command:

```bash
sudo rm -rf "/Library/Application Support/Neutrino/agent" /Library/Logs/Neutrino/agent
```

<!-- 待核: whether the two folders above are all a Mac keeps of the agent after `nagent service uninstall`; build_agent_macos.py says only that the configuration and the state stay. -->

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
| macOS          | see the note after this table                                                    | `/Applications/Neutrino Client.app` and your `~/Library/Application Support/Neutrino/client`             |
| Android        | uninstall the app as any other app                                               | nothing of the app                                                                                       |

On a Mac, the client's package has no uninstaller that a standard page or a build script names.

<!-- 待核: how to take the client off a Mac (the bundle, the /usr/local/bin/nclient link and the overlay LaunchDaemons); build_client_macos.py describes no removal. -->

## What stays on the machine

After a removal without a purge, these folders stay. In the paths, `<package>` is `hub`, `agent` or `client`.

| Holds             | Linux                       | macOS                                                    | Windows                                    |
| ----------------- | --------------------------- | -------------------------------------------------------- | ------------------------------------------ |
| configuration     | `/etc/neutrino/`            | `/Library/Application Support/Neutrino/<package>/config` | `C:\ProgramData\Neutrino\<package>\config` |
| state             | `/var/lib/neutrino/`        | `/Library/Application Support/Neutrino/<package>/state`  | `C:\ProgramData\Neutrino\<package>\state`  |
| logs              | `/var/log/neutrino/`        | `/Library/Logs/Neutrino/`                                | `C:\ProgramData\Neutrino\<package>\log`    |
| a person's client | `~/.config/neutrino/client` | `~/Library/Application Support/Neutrino/client`          | `%APPDATA%\Neutrino\client`                |

An agent also leaves what its modules made for people: the shares, the accounts, CloudCLI's files in each home and the modules' data.
