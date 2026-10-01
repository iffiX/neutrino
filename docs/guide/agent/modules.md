---
title: Modules
---

# Modules

A module is one piece of server software that the hub installs, runs and configures on a managed machine. The **Modules** page drives the modules of one machine at a time.

Before you start, the machine runs the agent and is online. While its agent is offline, the page reads **The agent is offline** and every button is unavailable.

## Pick a machine and a module

1. Under **Which machine**, select a machine.
1. Under **Modules on this machine**, select a tab.

Each tab shows the module's title, a dot and a state word. The titles come from the hub's module catalog and read the same in every panel language: **File share**, **Gitea**, **Containers**, **VS Code** and **ZFS storage**.

The **+** at the end of the tab row opens the list of modules. A check adds that module's tab for this machine, and clearing it removes the tab. A machine with no choice saved shows a tab for every module its agent reported on.

![The module list open, with the modules this machine cannot run greyed out](/guide/en/modules_picker_greyed.webp)

A module the machine's system cannot run is greyed out in the list and never shows as a tab. Its row reads **This machine's system cannot run it**:

| Module          | Linux                                     | Windows                     | macOS                       |
| --------------- | ----------------------------------------- | --------------------------- | --------------------------- |
| **File share**  | Samba                                     | the system's own SMB server | the system's own SMB server |
| **Gitea**       | amd64 and arm64                           | no                          | no                          |
| **Containers**  | yes                                       | no                          | no                          |
| **ZFS storage** | yes                                       | no                          | no                          |
| **VS Code**     | amd64 and arm64, with glibc 2.28 or newer | amd64                       | Apple silicon               |

The catalog also lists AnyDesk and TeamViewer. Neither appears on this page: the remote desktop panel in a device's drawer on the [Devices](../hub/devices.md) page reads and sets them up.

## What the state word means

| Word                             | The machine                                                           |
| -------------------------------- | --------------------------------------------------------------------- |
| **not installed**                | has none of the module's software                                     |
| **installed**                    | has the software, running or not, and the hub has never configured it |
| **stopped**                      | has the hub's configuration applied, with the service stopped         |
| **running**                      | has the hub's configuration applied, with the service running         |
| **installing**, **uninstalling** | is in the middle of that step                                         |
| **failed**                       | reported that the last step failed, with the reason under the tab     |
| **unsupported**                  | runs an older agent with no code for this module                      |
| **never reported**               | has said nothing about this module                                    |

## Install, start and stop

| Button        | What happens on the machine                                                   | Available when the tab reads                              |
| ------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------- |
| **Install**   | the software is installed, and nothing is configured or started               | **not installed**, **failed**                             |
| **Start**     | the software is installed, the configuration applied, and the service started | **installed**, **stopped**                                |
| **Stop**      | the configuration is applied and the service stops                            | **running**, or **installed** with the service already up |
| **Uninstall** | the software and the configuration the hub wrote are removed                  | **installed**, **stopped**, **running**, **failed**       |

The box under the tabs shows **Output** while an install or an uninstall runs, with a dot reading **running**, **finished** or **failed**. The rest of the time it shows the last 200 lines of the module's own journal on the machine. A distribution can lack a ZFS kernel module for the running kernel. The ZFS install then builds one, which takes several minutes and prints in the same box.

A module the catalog has no build of for the machine's platform is rejected with `no_platform_build`.

## Uninstall

**Uninstall** opens a confirmation naming the module and the machine, and nothing is removed until you confirm.

::: warning
The software is removed and the configuration the hub wrote is deleted. Pools, share folders, repositories and container volumes stay on the machine.
:::

## Configure

**Configure** does what **Start** does, then opens the module's own sections under the tabs. It is available when the tab reads **installed**, **stopped** or **running**. Pressed again, it reads **Hide configuration** and closes the sections.

When the hub holds no configuration for a module, the first **Configure** takes what the machine already has as the hub's own. The first apply then changes nothing there:

| Tab             | What the first **Configure** takes over                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **File share**  | on Linux, the shares and accounts already on the machine; on Windows and macOS, only the shares and accounts this module made earlier |
| **Containers**  | the containers already there, with their images, ports, volumes and environment, and the registry mirrors                             |
| **Gitea**       | the instance the hub installed; a Gitea installed by hand reports its port and keeps its own settings                                 |
| **VS Code**     | nothing                                                                                                                               |
| **ZFS storage** | nothing; the sections show what the machine reports about its disks                                                                   |

From then on the hub's copy is the only truth, and every apply writes the whole configuration back to the machine.

## What each tab opens

| Tab             | Its sections                                       |
| --------------- | -------------------------------------------------- |
| **File share**  | Shares, Users, Now serving                         |
| **Gitea**       | Access, Administrator                              |
| **Containers**  | Running now, Registry mirrors, Declared containers |
| **VS Code**     | Instances                                          |
| **ZFS storage** | Topology, Pools, Datasets                          |
