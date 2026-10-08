---
title: code-server
---

# code-server

code-server is the browser build of VS Code that Coder publishes under the MIT licence. The **code-server** module runs it once per account on a managed Linux machine or Mac. A desktop client or the Android app opens each instance through a forward on its own `127.0.0.1`. You install code-server on the machine from Coder, at one pinned version of its standalone release.

| System  | Machines that run it                      |
| ------- | ----------------------------------------- |
| Linux   | amd64 and arm64, with glibc 2.28 or newer |
| macOS   | Apple silicon and Intel                   |
| Windows | none; the tab is greyed out               |

In the mainland edition, the release comes from the USTC mirror, `mirrors.ustc.edu.cn`, which keeps only Coder's latest release. The installer checks the pinned version against its SHA-256. When the mirror no longer has that version, the installer takes the mirror's current release, checked by HTTPS alone.

## Turn it on

1. On the **code-server** tab of the [Modules](../modules.md) page, select **Install**.
1. Select **Configure**. The **Instances** section opens under the tab.

The top line of the section names who installs the editor: **You install code-server, Coder's MIT-licensed editor, on this machine.** After the machine reports a version, the line adds **Installed:** and that version.

## Add an instance

1. Under **Instances**, select **Add instance**.
1. Fill **Account** with the name of an account on the machine.
1. Optional: change the **Port**. The first instance gets 8443, and each new one the port after the highest in use.
1. Select **Apply code-server**. The machine saves the instances and starts code-server for each account.

Each instance runs as its account, so the files it creates belong to that account. Its settings and extensions are in code-server's own folders under the account's home. Its row reads **running** or **not running**, and a reason appears under the row when the machine reports one.

The port is where the agent's forwarder listens on the managed machine's loopback. It is a port of that machine, apart from the hub's own port 8443. code-server itself listens on a socket that only its account and root can open.

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

## Point its AI tools at the gateway

[Point a machine's AI tools at the gateway](./ai_tools.md) switches the tools of every account that runs code-server here.

## Open it from a client

Each running instance is a row under **Web** on the [Services](../../hub/services.md) page, titled **code-server** with the account in parentheses. A client opens it when the hub's **Clients** page gives it **Web pages** on that machine. On the client's **Web** page, **Open** makes a forward through the hub and opens the instance in the browser with a fresh token.

The token works once, within 60 seconds. The forwarder then sets a login cookie in that browser, which lasts seven days. After the cookie expires, select **Open** again.
