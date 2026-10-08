---
title: code-server
---

# code-server

Coder publishes code-server, the browser build of VS Code, under the MIT licence. The **code-server** module runs it once per account on a managed Linux machine or Mac. You install code-server on the machine from Coder, at one pinned version of its standalone release.

| System  | Machines that run it                      |
| ------- | ----------------------------------------- |
| Linux   | amd64 and arm64, with glibc 2.28 or newer |
| macOS   | Apple silicon and Intel                   |
| Windows | none; the tab is greyed out               |

In the mainland edition, the release comes from the USTC mirror, `mirrors.ustc.edu.cn`, which keeps only Coder's latest release. The installer checks the pinned version against its SHA-256, and takes the mirror's current release, checked by HTTPS alone, when the pinned one is gone.

## Add an instance

1. On the **code-server** tab of the [Modules](../modules.md) page, select **Install**.
1. Select **Configure**. The **Instances** section opens under the tab, and its top line names the installed version.
1. Select **Add instance**.
1. Fill **Account** with the name of an account on the machine.
1. Optional: change the **Port**. The first instance gets 8443.
1. Select **Apply code-server**.

Each instance runs as its account, with its settings and extensions in code-server's own folders under the account's home. Its row reads **running** or **not running**, with a reason when the machine reports one. A refused apply names its code, listed under [code-server](../../reference/troubleshooting.md#code-server) in troubleshooting.

## Extensions and AI tools

The editor installs extensions from Open VSX, code-server's own gallery, where Claude Code and Codex are published. [Point a machine's AI tools at the gateway](./ai_tools.md) switches the tools of every account that runs code-server here.

## Open it from a client

Each running instance is a row under **Web** on the [Services](../../hub/services.md) page, titled **code-server** with the account in parentheses. A client whose permission on the hub's **Clients** page includes **Web pages** on that machine opens it with **Open** on its **Web** page. The forwarder then sets a login cookie in that browser for seven days; after it expires, select **Open** again.

## Ports

For each instance, the agent runs a forwarder that listens at `127.0.0.1` on the instance's **Port**. code-server itself listens on a socket only its account and root open. The port is a number from 1024 to 65535, one per instance on the machine, apart from the hub's port 8443. The hub publishes it as the instance's **Web** entry, and **Add instance** offers the port after the highest one in use.

A development server or any other program started in the editor's terminal stays unpublished, because the agent connects clients to its machine's published ports alone. To reach one from a client, select **Declare service** on the [Services](../../hub/services.md#declare-a-service-by-hand) page. Declare a **Web** or **Port** entry with the machine's address and the program's port. The hub connects to that address directly, so the program must listen on an address the hub reaches, such as `0.0.0.0`.
