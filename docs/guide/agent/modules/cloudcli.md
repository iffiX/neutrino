---
title: CloudCLI
---

# CloudCLI

CloudCLI is a web page for AI coding sessions, published on npm as `@cloudcli-ai/cloudcli`. The **CloudCLI** module runs it at version 1.37.3, one instance per account on a managed machine. When you finish here, each account you picked has a running instance, and **Open** in a client opens its page already signed in.

| System  | Machines that run it                      |
| ------- | ----------------------------------------- |
| Linux   | amd64 and arm64, with glibc 2.28 or newer |
| Windows | amd64 and arm64                           |
| macOS   | Apple silicon and Intel                   |

## Add an instance

1. On the **CloudCLI** tab of the [Modules](../modules.md) page, select **Install**.
1. Select **Configure**. The **Instances** section opens under the tab.
1. Select **Add instance**.
1. Fill **Account** with the name of an account on the machine.
1. Optional: change the **Port**. The first instance gets 3001, and each new one the port after the highest in use.
1. On a Windows machine, pick the account's login under **Windows login for** the account.
1. Select **Apply CloudCLI**.

![The CloudCLI tab of server with one running instance](/guide/en/cloudcli_panel.webp)

You install CloudCLI on the machine for each account, with npm, as that account. While npm runs for an account, the tab reads **installing**. Each instance then runs as its account, and its row reads **running** or **not running**.

On Windows, the agent starts each instance with the account's login. Store the login under **Logins** on the [Credentials](../../hub/credentials.md) page before you pick it.

## What the service finds on its PATH

The service of each instance starts with a `PATH` the agent writes, and the tools CloudCLI starts are looked up in it:

| System  | The service's `PATH`, in order                                                                                  |
| ------- | --------------------------------------------------------------------------------------------------------------- |
| Linux   | the module's Node.js folder, `~/.local/bin`, `~/bin`, `/usr/local/bin`, `/usr/bin`, `/bin`                      |
| macOS   | the module's Node.js folder, `~/.local/bin`, `~/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`, `/bin` |
| Windows | the module's Node.js folder, `%APPDATA%\npm`, then the account's own `PATH`                                     |

The agent checks none of these folders and looks for no tool by name. A tool CloudCLI cannot find there, such as Claude Code or Codex, is reported by CloudCLI itself. Install such a tool as the account, into one of these folders.

## Point its AI tools at the gateway

The Claude Code and Codex that CloudCLI starts read the account's own settings. [Point a machine's AI tools at the gateway](./ai_tools.md) points those settings at the hub.

## Open it from a client

Each running instance is a row under **Web** on the [Services](../../hub/services.md) page, titled **CloudCLI** with the account in parentheses. On a client's **Web** page, **Open** fetches a fresh token from the hub each time, which works once, within 60 seconds.

The agent's forwarder in front of CloudCLI checks the token and signs in to CloudCLI with a password the hub generated. The browser then opens on CloudCLI's page, signed in. The forwarder answers CloudCLI's own register and sign-in addresses with 401, so nobody signs up or signs in there directly.

## When it fails

| Code                             | Cause                                                                               |
| -------------------------------- | ----------------------------------------------------------------------------------- |
| `cloudcli_node_download_failed`  | Node.js for CloudCLI could not be fetched or unpacked                               |
| `cloudcli_npm_install_failed`    | npm failed to install CloudCLI for the account; the row shows npm's last lines      |
| `cloudcli_native_module_failed`  | better-sqlite3, node-pty or bcrypt could not fetch its prebuilt binary              |
| `cloudcli_install_out_of_memory` | the machine ran out of memory during the npm install                                |
| `cloudcli_port_taken`            | another program on the machine holds the instance's port                            |
| `cloudcli_register_failed`       | the account's CloudCLI already has an administrator with another password           |
| `account_unknown`                | the machine has no account by that name                                             |
| `account_invalid`                | the name cannot be an account name on that machine                                  |
| `account_duplicate`              | two instances name the same account                                                 |
| `port_duplicate`                 | two instances use the same port                                                     |
| `port_invalid`                   | the port is outside 1024 to 65535                                                   |
| `credential_missing`             | a Windows instance has no login picked                                              |
| `credential_invalid`             | Windows no longer accepts the instance's login; pick an updated one and apply again |
