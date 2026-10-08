---
title: Gitea
---

# Gitea

The **Gitea** module runs one private git server per managed machine, on Linux, macOS or Windows, and every client opens it from its **Web** page. You install Gitea's official release binary on the machine, at the one version the hub pins. At the end of this page Gitea is running, it has an administrator, and a client opens it.

## Install it

1. On the **Gitea** tab of the [Modules](../modules.md) page, select **Install**.
1. Select **Configure**. The **Access** and **Administrator** sections open under the tab.

On Linux, the install brings git from the machine's own packages. On macOS and Windows, git must be on the machine before the install:

| System  | The git Gitea uses                                                       |
| ------- | ------------------------------------------------------------------------ |
| macOS   | the git of the command line developer tools or of Xcode, else Homebrew's |
| Windows | Git for Windows                                                          |

Without a usable git, the install is rejected with `gitea_git_missing`. Install git, then select **Install** again.

## Set the access

**Access** holds the settings that must agree with the hub. Repositories, accounts and every other setting are managed in Gitea itself.

1. Set the **Port** Gitea listens on.
1. Optional: set the **Root URL** that clone addresses start with. Left empty, it comes from the machine's address.
1. Optional: turn on **Open registration** so visitors can create their own accounts.
1. Select **Apply access**. The machine rewrites `app.ini` and restarts Gitea.

![The Gitea tab with its Access section](/guide/en/gitea.webp)

**Open Gitea** beside the section title opens the server in a new browser tab while the service runs.

## Create the administrator

A new Gitea has no account. The **Create administrator** button is available after the service has started.

1. Under **Administrator**, fill the username, the password and, if you want one, the email.
1. Select **Create administrator**.

The section then shows the administrator's name with **Reset password**, which sets a new password for that account.

## On macOS and Windows

- Clones and pushes go over HTTP; Gitea serves no SSH on these systems.
- On a Mac, Gitea runs as the hidden account `neutrino_gitea`.
- On Windows, Gitea runs as LocalSystem.
- **Uninstall** removes the service and the binary, and keeps the data folder and the account. A later install serves the same repositories and accounts.

## A Gitea installed by hand

The hub configures only the Gitea it installed itself. A Gitea somebody installed by hand reports its port and keeps its own settings.

## Where it is published

Gitea is a row under **Web** on the [Services](../../hub/services.md) page, described as published by the gitea module on that machine. A client opens it from its **Web** page with **Open**, in the [Desktop client](../../client/desktop.md) and in the Android app alike.
