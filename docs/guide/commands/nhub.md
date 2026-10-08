---
title: nhub commands
---

# nhub commands

`nhub` is the hub's command line, installed with the hub package on the machine that runs the hub. The table lists its subcommands in the order `nhub --help` prints them.

## Subcommands

**Root** marks a subcommand that needs root on Linux and macOS, or an administrator terminal on Windows. Without it, the subcommand prints the line to run and exits with status 2. **Asks** marks a subcommand that asks one `[y/N]` question first. `--yes` answers it; without a terminal and without `--yes`, the subcommand prints a line naming `--yes` and exits with status 1.

| Command             | Arguments and flags                                                             | Root | Asks | What it does                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------- | ---- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `nhub setup`        | `--stdin` reads the answers as JSON; `--json <path>` reads them from a file     | yes  | no   | Sets this machine up one time, in the browser wizard or the terminal. Rejected once a panel password is set.                                |
| `nhub run`          | `--host`, `--port`, `--reload`, `--interface`; one `--only-` flag naming a unit | no   | no   | Runs one hub process in the foreground, as every `neutrino_hub_*` unit does.                                                                |
| `nhub open`         | `--print` prints the address; `--start-service`, `--output <path>` are internal | no   | no   | Opens the panel, or the wizard before setup, in the browser, starting a stopped service after an administrator prompt.                      |
| `nhub start`        | `--interface`; `--yes`; one `--only-` flag naming a unit                        | yes  | yes  | Starts every enabled unit, routing state first and panel last, or the one unit named. On macOS and Windows it starts the hub's one service. |
| `nhub stop`         | `--interface`; `--yes`; one `--only-` flag naming a unit                        | yes  | yes  | Stops every unit, panel first, or the one named; modules and virtual networks keep running. On macOS and Windows it stops the one service.  |
| `nhub status`       |                                                                                 | no   | no   | Prints each hub unit's state on Linux, or the one service's on macOS and Windows. Exits with status 0 while the panel runs.                 |
| `nhub service run`  | `run` is the only action                                                        | yes  | no   | Runs the hub as the Windows service. From a terminal it exits with status 1, and on another system with 2.                                  |
| `nhub apply`        | `--only <component>`; `--dry-run` prints the files; `--skip-apply` only writes  | yes  | no   | Renders every generated configuration from `config/`, validates it and applies it, in the panel's order.                                    |
| `nhub unlock`       |                                                                                 | yes  | no   | Clears the panel's login lockout and every fail2ban SSH ban.                                                                                |
| `nhub reset`        | `all`, `network` or `password`; `--stdin` reads the new password; `--yes`       | yes  | yes  | `password` sets a new panel password. `network` hands the network back. `all` also resets `config/`, deletes the keys and stops the hub.    |
| `nhub update`       | `--yes`; `--package <file>` installs that file instead of the newest release    | yes  | yes  | Installs the newest release, checks the hub's health for three minutes, and puts the previous version back when the check fails.            |
| `nhub vault rekey`  | `--stdin` reads the new passphrase                                              | yes  | no   | Wraps the vault's data key under a new passphrase; nothing sealed is encrypted again.                                                       |
| `nhub scan-secrets` | `--staged`, `--history`, `--no-entropy`, `--no-vendor`, `--quiet`               | no   | no   | Checks the working tree, the staged files or every commit for credentials. A development command.                                           |

The `--only-` flags exist on Linux alone, one per systemd unit: `web`, `xray`, `cliproxyapi`, `dnsmasq`, `relay` for the SSH Relay, `router`, `supplicant` and `dhcpcd`; `--only-supplicant` and `--only-dhcpcd` need `--interface`. `--only <component>` of `nhub apply` takes `router`, `xray`, `dnsmasq`, `cliproxyapi` or `overlay`. `xray` exists in the full edition only. [Uninstall](../uninstall.md) uses `nhub reset network` and `nhub reset all`.

## Global flags

| Flag        | Where                         | What it does                                                                                   |
| ----------- | ----------------------------- | ---------------------------------------------------------------------------------------------- |
| `--version` | `nhub`                        | Prints the package version and exits.                                                          |
| `--dev`     | `nhub`, before the subcommand | Runs against `hub_dev_root/` in a working copy and lifts the root check; a packaged hub exits. |
| `-h`        | every level                   | Prints that level's help and exits.                                                            |

## Exit statuses

| Status | When                                                                                                                            |
| ------ | ------------------------------------------------------------------------------------------------------------------------------- |
| 0      | The subcommand finished, or found nothing to do.                                                                                |
| 1      | The answer to `[y/N]` was no, a step failed, or `nhub status` found the panel stopped.                                          |
| 2      | Root was missing; `nhub` or `nhub reset` named nothing; an `--only-` flag ran off Linux; `nhub update` ran from a working copy. |
| 130    | Ctrl-C stopped the subcommand.                                                                                                  |
