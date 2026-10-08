---
title: VS Code
---

# VS Code

Each account on a managed machine can have its own VS Code in the browser through the **VS Code** module. A desktop client or the Android app opens each instance through a forward on its own `127.0.0.1`. You install VS Code Server on the machine under Microsoft's license terms, at one pinned build of Microsoft's standalone VS Code CLI. The agent runs it.

| System  | Machines that run it                      |
| ------- | ----------------------------------------- |
| Linux   | amd64 and arm64, with glibc 2.28 or newer |
| Windows | amd64                                     |
| macOS   | Apple silicon and Intel                   |

## Turn it on

1. On the **VS Code** tab of the [Modules](../modules.md) page, select **Open and accept the terms**. Microsoft's terms open in a new browser tab, and the press records that you accept them for this machine.
1. Select **Install**.
1. Select **Configure**. The **Instances** section opens under the tab.

After the first step, the button reads **Terms accepted** and the rest of the tab appears under it. Each machine records the acceptance once. Until then, the hub rejects an install, a start or a configuration of VS Code there with `terms_not_accepted`.

## Add an instance

1. Under **Instances**, select **Add instance**.
1. Fill **Account** with the name of an account on the machine.
1. Optional: change the **Port**. A new instance gets the port after the highest one in use, starting at 8000.
1. On a Windows machine, pick the account's login under **Windows login for** the account.
1. Select **Apply VS Code**. The machine saves the instances and restarts them.

![The VS Code tab with one instance and its account](/guide/en/vscode_panel.webp)

Each instance runs as its account, so the files it creates belong to that account. Its row reads **running** or **not running**, and a reason appears under the row when the machine reports one.

## Windows logins

Windows starts an instance as its account only with that account's password. Store the account's username and password under **Logins** on the [Credentials](../../hub/credentials.md) page, then pick that login on the instance.

When the account's password changes on Windows, the instance reports `credential_invalid`, and its row says Windows no longer accepts the login. Update the login on the **Credentials** page, or pick another one, and select **Apply VS Code** again.

## Refusals on apply

| Code                 | Cause                                             |
| -------------------- | ------------------------------------------------- |
| `account_unknown`    | the machine has no account by that name           |
| `account_duplicate`  | two instances name the same account               |
| `port_duplicate`     | two instances use the same port                   |
| `port_invalid`       | the port is outside 1024 to 65535                 |
| `credential_missing` | a Windows instance has no login picked            |
| `token_missing`      | the hub sent no connection token for the instance |

## Point its AI tools at the gateway

The accounts that run VS Code here follow the machine's AI tools setting, as [Point a machine's AI tools at the gateway](./ai_tools.md) describes.

## Open it from a client

Each running instance is a row under **Web** on the [Services](../../hub/services.md) page, titled **VS Code** with the account in parentheses. The instance listens on its machine's loopback alone, so a browser cannot open the row's address directly. On a client's **Web** page, **Open** makes a forward through the hub and opens the instance in the browser with a fresh token.
