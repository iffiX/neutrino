---
title: code-server
---

# code-server

The **code-server** module runs code-server, the browser build of VS Code that Coder publishes under the MIT licence, once per account on a managed machine. A desktop client or the Android app opens each instance through a forward on its own `127.0.0.1`. You install code-server on the machine from Coder: the module's installer fetches Coder's standalone release at one pinned version, and the agent unpacks and runs it.

| System  | Machines that run it                      |
| ------- | ----------------------------------------- |
| Linux   | amd64 and arm64, with glibc 2.28 or newer |
| macOS   | Apple silicon and Intel                   |
| Windows | none; the tab is greyed out               |

In the mainland edition the installer fetches the same release from the USTC mirror, `mirrors.ustc.edu.cn`. That mirror keeps only Coder's latest release. When it no longer has the pinned version, the installer takes the mirror's current release, checked by HTTPS alone.

## Turn it on

1. On the **code-server** tab of the [Modules](../modules.md) page, select **Install**.
1. Select **Configure**. The **Instances** section opens under the tab.

The line at the top of the section reads **You install code-server, Coder's MIT-licensed editor, on this machine.**, followed by **Installed:** and the version once the machine reports one.

## Add an instance

1. Under **Instances**, select **Add instance**.
1. Fill **Account** with the name of an account on the machine.
1. Optional: change the **Port**. The first instance gets 8443, and each new one the port after the highest in use.
1. Select **Apply code-server**. The machine saves the instances and starts code-server for each account.

Each instance runs as its account, so the files it creates belong to that account. Its settings and extensions are in code-server's own folders under the account's home. Its row reads **running** or **not running**, and a reason appears under the row when the machine reports one.

The port is where the agent's forwarder listens on the machine's loopback. code-server itself listens on a socket that only its account and root can open.

## Extensions

The editor installs extensions from Open VSX, code-server's own extension gallery. Claude Code and Codex are among the extensions published there. Search for them in the editor's **Extensions** view, as in VS Code.

## Refusals on apply

| Code                          | Cause                                                    |
| ----------------------------- | -------------------------------------------------------- |
| `account_unknown`             | the machine has no account by that name                  |
| `account_invalid`             | the name cannot be an account name on that machine       |
| `account_duplicate`           | two instances name the same account                      |
| `port_duplicate`              | two instances use the same port                          |
| `port_invalid`                | the port is outside 1024 to 65535                        |
| `secret_missing`              | the hub sent no token secret for the instance            |
| `code_server_download_failed` | the release could not be fetched or unpacked             |
| `code_server_port_taken`      | another program on the machine holds the instance's port |

## Open it from a client

Each running instance is a row under **Web** on the [Services](../../hub/services.md) page, titled **code-server** with the account in parentheses. On the client's **Web** page, **Open** makes a forward through the hub and opens the instance in the browser with a fresh token. The token works once, within 60 seconds. The forwarder then sets a login cookie in that browser, which lasts seven days.
