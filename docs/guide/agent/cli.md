---
title: nagent commands
---

# nagent commands

Every `nagent` subcommand runs as root on a managed machine. Run without root, a subcommand prints its reason and the `sudo` line, then exits with status 2. The table lists the subcommands as `nagent --help` does.

| Command                 | Arguments and flags                                                                                                                                                       | What it does                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `nagent connect <link>` | `<link>` is the `neutrino://enroll/` link from the hub; with it omitted, the command prompts for it. `--yes` replaces an existing binding without a confirmation prompt   | Joins the hub the link names: writes the binding and starts the service.                              |
| `nagent disconnect`     |                                                                                                                                                                           | Leaves the hub and removes the binding.                                                               |
| `nagent status`         |                                                                                                                                                                           | Prints what this machine is bound to, read over the agent's root-only control socket.                 |
| `nagent sync`           |                                                                                                                                                                           | Fetches this machine's desired state from the hub now.                                                |
| `nagent run`            |                                                                                                                                                                           | Runs the agent in the foreground; it is what the systemd unit starts.                                 |
| `nagent rdp start`      | `--user <account>` names the account whose desktop is shared. With it omitted, the account that invoked `sudo` is shared, or else the one account signed in at the screen | Shares this desktop at the seat password the hub set.                                                 |
| `nagent rdp stop`       |                                                                                                                                                                           | Stops sharing this desktop. On a machine that is not sharing, it prints that and exits with status 0. |

| Flag        | Where       | What it does                          |
| ----------- | ----------- | ------------------------------------- |
| `--version` | `nagent`    | Prints the package version and exits. |
| `-h`        | every level | Prints that level's help and exits.   |

`nagent` with no subcommand, and `nagent rdp` with no action, print their help and exit with status 2.
