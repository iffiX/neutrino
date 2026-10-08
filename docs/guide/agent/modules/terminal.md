---
title: Terminal
---

# Terminal

The **Terminal** module sets which account a terminal on a managed machine runs as, and which shell program it starts. Every managed machine has the tab, because the agent's own package includes the module, and it has nothing to install or uninstall.

| System  | What you can set                                   |
| ------- | -------------------------------------------------- |
| Linux   | the account and the shell program                  |
| macOS   | the account and the shell program                  |
| Windows | the shell program; a terminal there runs as SYSTEM |

## Set the account and the shell

1. On the **Terminal** tab of the [Modules](../modules.md) page, pick an **Account**. The default is **The agent's own (root; SYSTEM on Windows)**.
1. Optional: fill **Shell program** with a program's full path, or select **Browse…** and select the program among the machine's files.
1. Select **Apply terminal**.

![The Terminal tab of server, with an account picked](/guide/en/modules_terminal_tab.webp)

An empty **Shell program** means the account's login shell, and PowerShell on Windows. A terminal for an account starts in that account's home folder, with its environment.

The settings hold for every terminal opened afterwards, from the panel's [Terminals](../terminals.md) page and from a client. A terminal already open keeps what it runs, and a container's shell keeps its own.

## Refusals

| Code                     | Cause                                                   |
| ------------------------ | ------------------------------------------------------- |
| `account_unknown`        | the machine has no account by that name                 |
| `path_invalid`           | the shell program is not a full path                    |
| `shell_program_unusable` | the program is missing on the machine, or it cannot run |

A terminal that opens after its account or its program has gone from the machine closes with `account_unknown` or `shell_program_unusable`. It does not fall back to root.
