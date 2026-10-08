---
title: CloudCLI
---

# CloudCLI

CloudCLI is a web page for AI coding sessions, published on npm as `@cloudcli-ai/cloudcli`. The **CloudCLI** module runs it at version 1.37.3, one instance per account on a managed machine.

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
1. Optional: change the **Port**. The first instance gets 3001.
1. On a Windows machine, pick the account's login under **Windows login for** the account.
1. Select **Apply CloudCLI**.

![The CloudCLI tab of server with one running instance](/guide/en/cloudcli_panel.webp)

You install CloudCLI on the machine for each account: the module's installer fetches Node.js and runs npm as that account, which takes several minutes. The tab reads **installing** meanwhile. Each instance runs as its account, and its row reads **running** or **not running**. On Windows, store the account's login under **Logins** on the [Credentials](../../hub/credentials.md) page before you pick it.

When an install or an apply fails, the row names the code, listed under [CloudCLI](../../reference/troubleshooting.md#cloudcli) in troubleshooting. After fixing the cause, select **Apply CloudCLI** again.

## What the service finds on its PATH

CloudCLI looks up the tools it starts, such as Claude Code or Codex, in the `PATH` the agent writes for the instance's service:

| System  | The service's `PATH`, in order                                                                                  |
| ------- | --------------------------------------------------------------------------------------------------------------- |
| Linux   | the module's Node.js folder, `~/.local/bin`, `~/bin`, `/usr/local/bin`, `/usr/bin`, `/bin`                      |
| macOS   | the module's Node.js folder, `~/.local/bin`, `~/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`, `/bin` |
| Windows | the module's Node.js folder, `%APPDATA%\npm`, then the account's own `PATH`                                     |

CloudCLI itself reports a tool it cannot find there. Install such a tool as the account, into one of these folders. [Point a machine's AI tools at the gateway](./ai_tools.md) points the tools' settings at the hub.

## Open it from a client

Each running instance is a row under **Web** on the [Services](../../hub/services.md) page, titled **CloudCLI** with the account in parentheses. **Open** on a client's **Web** page opens CloudCLI's page signed in. The agent's forwarder in front of CloudCLI signs in with a password the hub generated, and rejects CloudCLI's own register and sign-in addresses with 401.
