---
title: Gitea
---

# Gitea

With the **Gitea** module, a managed Linux machine runs a private git server, and every client opens it from its list of web entries. The hub fetches a pinned Gitea release for amd64 or arm64, and the agent installs it beside git from the machine's own packages.

Before you start, select **Install** and then **Configure** on the **Gitea** tab of the [Modules](../modules.md) page. The **Access** and **Administrator** sections open under the tab.

![The Gitea tab with its Access section](/guide/en/gitea.webp)

## Set the access

**Access** holds the settings that must agree with the hub. Repositories, accounts and every other setting are managed in Gitea itself.

1. Set the **Port** Gitea listens on.
1. Optional: set the **Root URL** that clone addresses start with. Left empty, it comes from the machine's address.
1. Optional: turn on **Open registration** so visitors can create their own accounts.
1. Select **Apply access**. The machine rewrites `app.ini` and restarts Gitea.

**Open Gitea** beside the section title opens the server in a new browser tab while the service runs.

## Create the administrator

A new Gitea has no account. To create the first one:

1. Under **Administrator**, fill the username, the password and, if you want one, the email.
1. Select **Create administrator**.

The button is available after the service has started. After the administrator exists, the section shows its name with **Reset password**, which sets a new password for it.

## A Gitea installed by hand

The hub configures only the Gitea it installed itself. A Gitea somebody installed by hand reports its port and keeps its own settings.

## Where it is published

Gitea is a row under **Web** on the [Services](../../hub/services.md) page, described as published by the gitea module on that machine. In the [Desktop client](../../client/desktop.md), it is an entry in the **Web** panel with **Open**, and the Android app lists it on its web screen.
