---
title: nagent commands
---

# nagent commands

`nagent` controls the agent on a managed machine running Linux, Windows or macOS. The table lists its subcommands in the order `nagent --help` prints them.

## Privileges

A subcommand needs root on Linux and macOS, or an administrator terminal on Windows; without it, the subcommand prints the line to run and exits with status 2. `--version`, `-h`, `nagent answer` and `nagent step-down` run under any account.

## Subcommands

**Asks** marks a subcommand that asks one `[y/N]` question first. `--yes` answers it, and a `no` prints `nothing changed` and exits with status 1. Without a terminal and without `--yes`, the answer is no.

| Command                    | Arguments and flags                                                                   | Asks               | What it does                                                                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nagent join <link>`       | the `neutrino://enroll/` link from the hub's **Devices** page, else a prompt; `--yes` | when already bound | Joins the hub the link names and starts the agent's service when it is stopped.                                                                                |
| `nagent leave`             | `--yes`                                                                               | yes                | Leaves the hub and removes the binding; the service keeps running. On an unbound machine it exits with status 1.                                               |
| `nagent status`            |                                                                                       | no                 | Prints the version, the bound hub, the last address, the service's state, and whether the hub accepted the last `hello`. Exits with 0 when bound and accepted. |
| `nagent sync`              |                                                                                       | no                 | Sends this machine's report to the hub now. Exits with status 1 when the service is stopped.                                                                   |
| `nagent start`             | `--yes`                                                                               | yes                | Starts the agent's service and prints its state.                                                                                                               |
| `nagent stop`              | `--yes`                                                                               | yes                | Stops the agent's service until the next boot; the binding is kept.                                                                                            |
| `nagent run`               |                                                                                       | no                 | Runs the agent in the foreground, as the systemd unit and the macOS LaunchDaemon do.                                                                           |
| `nagent service run`       |                                                                                       | no                 | Runs the agent as the Windows service; from a terminal it exits with status 1.                                                                                 |
| `nagent service uninstall` | `--yes`                                                                               | yes                | Stops the agent and removes what its modules added; shares, accounts and data stay. [Uninstall](../uninstall.md) has the rest.                                 |
| `nagent answer`            | `--prompt <text>`, `--answer <keys>`, `--` then the program                           | no                 | Runs a program on its own pseudo console and types the answer at the prompt. The agent runs it on Windows; nobody runs it by hand.                             |
| `nagent step-down`         | `--uid <uid>`, `--gid <gid>`, `--` then the program by full path                      | no                 | Drops to that account and runs the program. The agent runs it on macOS; nobody runs it by hand. Exits with 126 on failure.                                     |

## Global flags

| Flag        | Where       | What it does                          |
| ----------- | ----------- | ------------------------------------- |
| `--version` | `nagent`    | Prints the package version and exits. |
| `-h`        | every level | Prints that level's help and exits.   |

`nagent` with no subcommand and `nagent service` with no action print their help and exit with status 2. `nagent answer` and `nagent step-down` with no program also exit with status 2.
