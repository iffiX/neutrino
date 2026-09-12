---
title: nhub commands
---

# nhub commands

`nhub` is installed with the hub package on the hub box. The table lists its subcommands as `nhub --help` does, with each one's flags, whether it needs root, and what it does.

| Command             | Arguments and flags                                                                                                                                             | Root | What it does                                                                                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- | ----------------------------------------------------------------------------------------------------------------------------- |
| `nhub setup`        | `--stdin` reads every answer as one JSON object from standard input; `--json <path>` reads them from a file                                                     | yes  | Sets this gateway up, once, through the browser wizard or the terminal's screens.                                             |
| `nhub run`          | `--host`, `--port`, `--reload`, `--interface`; one of `--only-web`, `--only-xray`, `--only-cliproxyapi`, `--only-dnsmasq`, `--only-supplicant`, `--only-dhcpcd` | no   | Runs the control panel, or one process, in the foreground; it is what the systemd units start.                                |
| `nhub stop`         | `--interface`; one of `--only-web`, `--only-cliproxyapi`, `--only-dnsmasq`, `--only-xray`, `--only-router`, `--only-supplicant`, `--only-dhcpcd`                | yes  | Stops what the hub runs on this box, or one service.                                                                          |
| `nhub apply`        | `--only <component>` for `router`, `xray`, `dnsmasq`, `cliproxyapi` or `easytier`, repeatable; `--dry-run`; `--skip-apply`                                      | yes  | Renders every generated configuration from `config/`, validates it and applies it; `--dry-run` prints it and changes nothing. |
| `nhub unlock`       |                                                                                                                                                                 | yes  | Removes the login lockout and every fail2ban SSH ban.                                                                         |
| `nhub reset`        | `all` or `password`; `--stdin` reads the new password from standard input                                                                                       | yes  | Returns the box, or the panel password, to a fresh state.                                                                     |
| `nhub vault rekey`  | `--stdin` reads the new passphrase from standard input                                                                                                          | yes  | Wraps the vault's data key under a new master passphrase; nothing sealed is re-encrypted.                                     |
| `nhub scan-secrets` | `--staged`, `--history`, `--no-entropy`, `--no-vendor`, `--quiet`                                                                                               | no   | Scans the working tree, the staged files or the history for secrets; a development command.                                   |

| Flag        | Where                         | What it does                                                                                        |
| ----------- | ----------------------------- | --------------------------------------------------------------------------------------------------- |
| `--version` | `nhub`                        | Prints the package version and exits.                                                               |
| `--dev`     | `nhub`, before the subcommand | Runs against `hub_dev_root/` in a working copy and lifts the root check; a packaged hub rejects it. |
| `-h`        | every level                   | Prints that level's help and exits.                                                                 |

A subcommand that needs root and is run without it prints the `sudo` line and exits with status 2. `nhub` with no subcommand prints its help and exits with status 2. A command interrupted with Ctrl-C prints that it was stopped and exits with status 130.
