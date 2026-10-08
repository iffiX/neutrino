---
title: Modules
---

# Modules

The **Modules** page, subtitled **Features configured on each machine**, installs and sets up the server software of one managed machine at a time. When you finish here, the modules you want on the picked machine are installed, running or configured. You can also read the state word on each tab.

Before you start, the machine's agent must be online. The page lists only machines whose agent is online.

## What the page shows

The page has three panels, from top to bottom:

| Panel                    | Holds                                                                                   |
| ------------------------ | --------------------------------------------------------------------------------------- |
| **Which machine**        | the managed machines whose agent is online                                              |
| **Global configuration** | the settings of the picked machine that belong to no module, which are its AI tools     |
| **Module configuration** | the tabs of the machine's modules, and under them the sections of the module you picked |

[Point a machine's AI tools at the gateway](./modules/ai_tools.md) covers **Global configuration**.

## Pick a machine and a module

1. Under **Which machine**, select a machine.
1. Under **Module configuration**, select a tab.

The tabs come in one order: **File share**, **Terminal**, **Remote desktop**, **Gitea**, **VS Code**, **code-server**, **CloudCLI**, **Containers**, **ZFS storage**. The titles read the same in every panel language. Each tab shows its title, a dot and a state word.

The **+** at the end of the tab row opens the list of modules. A check adds that module's tab for this machine, and clearing the check removes the tab. A module the machine's system cannot run is greyed out in the list and never shows as a tab. Its row reads **This machine's system cannot run it**.

![The module list of a Windows machine, with Containers, ZFS storage and code-server greyed out](/guide/en/modules_picker_greyed.webp)

## Terminal and Remote desktop

The agent's own package includes these two modules, so every managed machine has their tabs, and the **+** list leaves them out. Their tabs show the state word and the module's own section. **Install**, **Start**, **Stop**, **Uninstall**, **Configure** and the output box belong to the other tabs alone.

[Terminal](./modules/terminal.md) sets the account and the shell program of new terminals. [Remote desktop](./modules/remote_desktop.md) shares the machine's desktop with clients.

## What the state word means

| Word                             | The machine                                                                                     |
| -------------------------------- | ----------------------------------------------------------------------------------------------- |
| **not installed**                | has none of the module's software                                                               |
| **installed**                    | has the software, running or not, and the hub has never configured it                           |
| **stopped**                      | has the hub's configuration applied, with the service stopped                                   |
| **running**                      | has the hub's configuration applied, with the service running                                   |
| **installing**, **uninstalling** | is in the middle of that step                                                                   |
| **queued**                       | is applying another module first; the agent applies one module at a time, in a fixed order      |
| **failed**                       | reported that the last step failed, with the reason under the tab                               |
| **unsupported**                  | runs an agent older than the module; every field, switch and apply bar of the tab is greyed out |
| **never reported**               | has said nothing about this module                                                              |

## Install, start and stop

| Button        | What happens on the machine                                                   | Available when the tab reads                        |
| ------------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| **Install**   | the software is installed, and nothing is configured or started               | **not installed**                                   |
| **Start**     | the software is installed, the configuration applied, and the service started | **installed**, **stopped**                          |
| **Stop**      | the configuration is applied and the service stops                            | **running**, or **installed** with the service up   |
| **Uninstall** | the software and the configuration the hub wrote are removed                  | **installed**, **stopped**, **running**, **failed** |

After a press, the tab reads **queued** or **installing** at once. Every button of the tab stays greyed until the machine reports a new state, for two minutes at most.

While an install or an uninstall runs, the box under the tabs shows **Output**, with a dot reading **running**, **finished** or **failed**. The rest of the time it shows the last 200 lines of the module's own log on the machine. A ZFS install on a kernel without a ZFS module builds one, which takes several minutes and prints in the same box.

An install that fails and leaves nothing on the machine puts the tab back to **not installed**. The box keeps the reason until your next press, and **Install** starts a fresh install. A step that has started runs to its end.

The hub rejects a press with `no_platform_build` when the catalog has no build of the module for the machine's platform. It rejects a press with `agent_offline` when the machine went offline in the meantime.

On the **VS Code** tab, Microsoft's terms come first, as [VS Code](./modules/vscode.md) describes.

## Try a failed step again

On a tab that reads **failed**, the button of the step that failed stays available: **Install**, **Start** or **Stop**. Select that button again to run the step again. A module section's apply button and **Configure** retry a refused configuration the same way, and that press is the only retry the page has.

## Uninstall

**Uninstall** opens a confirmation that names the module and the machine. Nothing is removed until you confirm.

::: warning
The software is removed and the configuration the hub wrote is deleted. Pools, share folders, repositories and container volumes stay on the machine.
:::

Removing the agent itself also leaves the machine's shares and accounts in place. [nagent commands](../commands/nagent.md) lists what `nagent service uninstall` takes away.

## Configure

**Configure** does what **Start** does, then opens the module's sections under the tabs. Selected again, it reads **Hide configuration** and closes them.

When the hub holds no configuration for a module, the first **Configure** takes what the machine already has as the hub's own. The first apply then changes nothing on the machine:

| Tab             | What the first **Configure** takes over                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **File share**  | on Linux, the shares and accounts already on the machine; on Windows and macOS, only the shares and accounts this module made earlier |
| **Gitea**       | the instance the hub installed; a Gitea installed by hand reports its port and keeps its own settings                                 |
| **VS Code**     | nothing                                                                                                                               |
| **code-server** | nothing                                                                                                                               |
| **CloudCLI**    | nothing                                                                                                                               |
| **Containers**  | the containers already there, with their images, ports, volumes and environment, and the registry mirrors                             |
| **ZFS storage** | nothing; the sections show what the machine reports about its disks                                                                   |

From then on, the hub's copy is the only truth, and each apply writes the whole configuration back to the machine.

## What each tab opens

| Tab                | Its sections                                       |
| ------------------ | -------------------------------------------------- |
| **File share**     | Shares, Users, Now serving                         |
| **Terminal**       | **Account** and **Shell program**                  |
| **Remote desktop** | one switch, **Share this machine's desktop**       |
| **Gitea**          | Access, Administrator                              |
| **VS Code**        | Instances                                          |
| **code-server**    | Instances                                          |
| **CloudCLI**       | Instances                                          |
| **Containers**     | Running now, Registry mirrors, Declared containers |
| **ZFS storage**    | Topology, Pools, Datasets                          |
