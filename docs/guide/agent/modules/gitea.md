---
title: Gitea
---

# Gitea

The **Gitea** module configures a managed machine as a private git server, one per machine, on Linux, macOS or Windows. You install Gitea's official release binary on the machine, at the one version the hub pins.

## Install it

1. On the **Gitea** tab of the [Modules](../modules.md) page, select **Install**.
1. Select **Configure**. The **Access** and **Administrator** sections open under the tab.

On Linux, the install brings git from the machine's own packages. On a Mac, git comes from the command line developer tools, Xcode or Homebrew, and on Windows from Git for Windows. Either must be on the machine before the install.

## Set the access

**Access** holds the settings that must agree with the hub; everything else is managed in Gitea itself.

1. Set the **Port** Gitea listens on.
1. Optional: set the **Root URL** that clone addresses start with. Left empty, it comes from the machine's address.
1. Optional: turn on **Open registration** so visitors can create their own accounts.
1. Select **Apply access**.

![The Gitea tab with its Access section](/guide/en/gitea.webp)

**Open Gitea** beside the section title opens the server in a new browser tab while the service runs.

## Create the administrator

A new Gitea has no account, and **Create administrator** is available after **Configure** starts the service.

1. Under **Administrator**, fill the username, the password and, optionally, the email.
1. Select **Create administrator**.

The section then offers **Reset password**.

## On macOS and Windows

- Clones and pushes go over HTTP.
- Gitea runs as the hidden account `neutrino_gitea` on a Mac, and as LocalSystem on Windows.
- **Uninstall** keeps the data folder and the account, so a later install serves the same repositories.

The hub configures only the Gitea it installed; one installed by hand reports its port and keeps its own settings. Gitea is a row under **Web** on the [Services](../../hub/services.md) page, and a client opens it with **Open** on its **Web** page.
