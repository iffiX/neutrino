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

## The first open

The first **Open** on an instance shows CloudCLI's own setup screens, signed in as the account. The client fetches a one-time token from the hub, as [Token entries](../../hub/services.md#token-entries) describes, and the forwarder checks it and signs the browser in to CloudCLI. The instance's row on the Modules page reads **running** throughout, since the setup writes settings while the service keeps running.

### CloudCLI's setup

1. On the client's **Web** page, select **Open** on the instance's row.

   ![CloudCLI's Git Configuration screen in the phone's browser](/guide/en/app_cloudcli_first_git.webp)

1. Fill **Git Name** and **Git Email**. CloudCLI saves them in the account's global git settings.
1. Select **Next**.

   ![The Connect Your AI Agents screen, with Claude Code ticked](/guide/en/app_cloudcli_first_agents.webp)

1. Select **Complete Setup**.

On **Connect Your AI Agents**, the tick on **Claude Code** comes from the account's `~/.claude/settings.json`. A session also needs Claude Code installed as the account, in a folder on the service's `PATH`.

### The first project and session

A project is a folder on the machine, and a session is one Claude Code conversation in it. After the setup, the project list is empty:

1. Select the menu button at the top left. The list reads **No projects found**.

   ![The empty project list](/guide/en/app_cloudcli_first_empty.webp)

1. Select the folder button with a plus, at the top of the list.
1. Under **Workspace Path**, type the full path of a folder the account owns.

   ![The Create New Project form with a workspace path](/guide/en/app_cloudcli_first_folder.webp)

1. Select **Next**.
1. Select **Create Project**.
1. Under the project, select **New Session**.

   ![A new session in the notes-app project](/guide/en/app_cloudcli_new.webp)

1. Type a message in the box at the bottom, and select the send button.

The reply appears under the message. The session appears in the project's list, titled with its first message.<!-- 待核: the reply under the message and the session title, not yet seen with Claude Code installed. -->

![The project's list with one session](/guide/en/app_cloudcli_sessions.webp)

A folder where the account runs Claude Code in a terminal also appears as a project, as the empty list's hint says. When the account has no Claude Code, the first message gets an **Error** naming the missing Claude Code binary; install it as described in [What the service finds on its PATH](#what-the-service-finds-on-its-path).
