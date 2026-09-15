---
title: Modules
---

# Modules

The **Modules** page puts one module's software on one managed machine and configures it there: a file share, a git server, containers, or ZFS storage. Everything on the page belongs to the machine picked at the top, and every press goes to that machine through its agent.

Before you start, the machine runs the agent and is online. An offline machine shows **The agent is offline**, and the presses are unavailable until it answers again.

## Pick a machine and a module

1. Under **Which machine**, select a machine.
1. Under **Modules on this machine**, select a tab.

A tab shows the module's name, a dot and one word for where the module is on that machine. The four are **File share**, **Gitea**, **Containers** and **ZFS storage**.

The `+` at the end of the row opens **Shown modules**. A check there adds a tab and clearing one removes it, for this machine alone. A machine with no choice recorded shows a tab for every module its agent has reported on, and an empty row reads **No module tabs yet; add one with +.**

## What the state word means

| Word                             | The machine                                                       |
| -------------------------------- | ----------------------------------------------------------------- |
| **not installed**                | has none of the module's software                                 |
| **installed**                    | has the software, and the hub has never configured it             |
| **stopped**                      | has the hub's configuration applied, with the service stopped     |
| **running**                      | has the hub's configuration applied, with the service running     |
| **installing**, **uninstalling** | is in the middle of that step                                     |
| **failed**                       | reported that the last step failed, with the reason under the tab |
| **unsupported**                  | runs an agent that has no code for this module                    |
| **never reported**               | has said nothing about this module                                |

Software somebody installed by hand reads as **installed**, and nothing on the machine changes until **Configure**.

## Install, start and stop

| Press         | What happens on the machine                                             | Available when the tab reads                              |
| ------------- | ----------------------------------------------------------------------- | --------------------------------------------------------- |
| **Install**   | the packages are installed, and nothing is configured                   | **not installed**, **failed**                             |
| **Start**     | the packages are installed, the configuration applied, the service runs | **installed**, **stopped**                                |
| **Stop**      | the configuration is applied and the service stops                      | **running**, or **installed** with the service already up |
| **Uninstall** | the packages and the configuration the hub wrote are removed            | **installed**, **stopped**, **running**, **failed**       |

An install's and an uninstall's lines appear under the tab in **Output**, with a dot reading **running**, **finished** or **failed**. The ZFS install compiles a kernel module on a distribution that packages none for the running kernel; that takes several minutes and prints in the same place. A module with no build for the machine's platform is rejected with `no_platform_build`.

## Uninstall

**Uninstall** opens a confirmation naming the module and the machine. Nothing is removed until it is confirmed.

::: warning
The package is removed and the configuration the hub wrote is deleted. Pools, share directories, repositories and container volumes stay on the machine.
:::

## Configure

**Configure** opens the module's own sections under the tab and moves the tab to **running**: the hub's configuration is applied on the machine and the service starts. The press is available from **installed**, **stopped** and **running**.

The first **Configure** on a module the hub holds no configuration for takes what the machine already has as the hub's own, so the first push changes nothing there:

| Tab             | What the first **Configure** takes over                                                                   |
| --------------- | --------------------------------------------------------------------------------------------------------- |
| **File share**  | the shares and the user accounts already on the machine                                                   |
| **Containers**  | the containers already there, with their images, ports, volumes and environment, and the registry mirrors |
| **Gitea**       | nothing; the hub configures the instance it installs itself                                               |
| **ZFS storage** | nothing; there is no wanted pool list                                                                     |

From then on the hub's copy is the only truth, and every apply writes the whole configuration back to the machine.

## What each tab opens

| Tab             | Its sections                                       | Page                          |
| --------------- | -------------------------------------------------- | ----------------------------- |
| **File share**  | Shares, Users, Now serving                         | [Samba](./samba.md)           |
| **Gitea**       | Access, Administrator                              | [Gitea](./gitea.md)           |
| **Containers**  | Declared containers, Running now, Registry mirrors | [Containers](./containers.md) |
| **ZFS storage** | Pools, Topology, Datasets                          | [ZFS](./zfs.md)               |
