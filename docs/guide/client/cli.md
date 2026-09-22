---
title: nclient commands
---

# nclient commands

`nclient` drives the client from a terminal and runs from a person's own account. Run as root, every subcommand is rejected with `root_refused` and exits with status 2. The table lists the subcommands as `nclient --help` does.

Every subcommand that acts on one hub takes `--hub`, whose value is that hub's name or its id. With one hub joined the flag can be left out. With several joined and none named, the command is rejected with `ambiguous_hub` and lists the names; a name nobody joined is `unknown_hub`.

## The subcommands

| Command                                 | Arguments and flags                                                                                                                                                                                                                                                                          | What it does                                                                             |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `nclient join <link>`                   | `<link>` is the `neutrino://enroll/` link from a hub's Clients page; with it omitted, the command prompts for it                                                                                                                                                                             | Joins the hub the link names, beside every hub already joined.                           |
| `nclient leave`                         | `--hub <name>`                                                                                                                                                                                                                                                                               | Leaves one hub and undoes what it published on this computer.                            |
| `nclient status`                        |                                                                                                                                                                                                                                                                                              | Prints the version, one line per hub joined, and whether the client runs.                |
| `nclient gui`                           | `--hidden` starts without showing the window                                                                                                                                                                                                                                                 | Runs the client and its window.                                                          |
| `nclient quit`                          |                                                                                                                                                                                                                                                                                              | Stops the running client. With none running, it is rejected with `resident_not_running`. |
| `nclient service list`                  | `--hub <name>` lists that hub alone                                                                                                                                                                                                                                                          | Prints every published entry, by hub and then by kind.                                   |
| `nclient service web open <ref>`        | `<ref>` is the entry's number under its hub in `service list` or its id, here and in every row that follows; `--hub <name>`                                                                                                                                                                  | Opens one link in the browser.                                                           |
| `nclient service port forward <ref>`    | `--local-port <port>`, `--hub <name>`                                                                                                                                                                                                                                                        | Relays one port to this machine's loopback.                                              |
| `nclient service port unforward <ref>`  | `--hub <name>`                                                                                                                                                                                                                                                                               | Closes that relay.                                                                       |
| `nclient service file config <ref>`     | `--path <path>` (required), `--username <name>`, `--hub <name>`; the password is typed at a prompt                                                                                                                                                                                           | Saves a share's login and path, and mounts it.                                           |
| `nclient service file mount <ref>`      | `--hub <name>`                                                                                                                                                                                                                                                                               | Mounts a share again with its saved login.                                               |
| `nclient service file unmount <ref>`    | `--hub <name>`                                                                                                                                                                                                                                                                               | Unmounts a share; its saved login stays.                                                 |
| `nclient service ai show`               | `--hub <name>` shows that hub's gateway; with it omitted, the target hub's                                                                                                                                                                                                                     | Prints where this person's tools point.                                                  |
| `nclient service ai apply hub`          | `--claude-default`, `--claude-opus`, `--claude-sonnet`, `--claude-haiku`, `--codex-model`, `--codex-effort` (`minimal`, `low`, `medium`, `high`), `--gemini-model`; an omitted flag keeps the saved choice, and `''` means the gateway default; `--hub <name>` makes that hub the target first | Points the target hub's tools at its gateway.                                              |
| `nclient service ai apply off`          |                                                                                                                                                                                                                                                                                              | Puts the tools back.                                                                     |
| `nclient service desktop connect <ref>` | `--hub <name>`                                                                                                                                                                                                                                                                               | Opens the viewer at one shared desktop.                                                  |

| Flag        | Where       | What it does                          |
| ----------- | ----------- | ------------------------------------- |
| `--version` | `nclient`   | Prints the package version and exits. |
| `-h`        | every level | Prints that level's help and exits.   |

`nclient` with no subcommand, `nclient service` with no kind, and a kind with no action print their help and exit with status 2.

## What status prints

```text
neutrino-client 0.3.0
hub        home    https://192.168.100.1:8443  connected  exit
hub        office  https://10.8.0.1:8443       reconnecting: the hub cannot be reached
resident   running
```

One line per hub joined, in the order joined: its name, its address, the state of its channel, and the last code that channel returned. The address is the one the channel last connected through, out of every address the hub listens on. `exit` marks the hub this person's AI tools point at. The last line is the client itself, `running` or `not running`. The exit status is 0 while every hub reads `connected` and the client runs, and 1 otherwise.
