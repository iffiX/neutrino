---
title: nclient commands
---

# nclient commands

`nclient` drives the desktop client from a terminal on Linux, Windows or macOS, under a person's own account. The table lists its subcommands in the order `nclient --help` prints them.

## Privileges

Run as root, every subcommand prints `root_refused` and exits with status 2. One person's client runs on a computer at a time. While another account's client runs, `nclient gui` exits with no window, and every subcommand except `quit` prints `client_held` and exits with status 1.

## Subcommands

`--hub <name>` names a hub on `leave`, `terminal` and every `service` subcommand. With several hubs and none named, the command prints `ambiguous_hub`; an unknown name gives `unknown_hub`. `<ref>` is an entry's number in `nclient service list`, or its id.

| Command                                 | Arguments and flags                                            | What it does                                                             |
| --------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `nclient join <link>`                   | the link from a hub's **Clients** page, else a prompt          | Joins the hub the link names, beside the others.                         |
| `nclient leave`                         | `--yes` skips the `[y/N]` question                             | Leaves one hub and ends its forwards, mounts and viewers.                |
| `nclient status`                        | `--json` prints one JSON object                                | Prints the version, each hub's state and the client's.                   |
| `nclient gui`                           | `--hidden` starts without showing the window                   | Runs the client and its window.                                          |
| `nclient quit`                          |                                                                | Stops the running client, or prints `resident_not_running`.              |
| `nclient terminal <machine>`            | `--session <id>` attaches to a kept session                    | Opens a shell on the machine, named or by id; exits with 1 on a refusal. |
| `nclient service list`                  |                                                                | Prints every published entry, by hub and then by kind.                   |
| `nclient service web open <ref>`        |                                                                | Opens one link in the browser.                                           |
| `nclient service port forward <ref>`    | `--local-port <port>`, the port to prefer                      | Relays one port to this computer's loopback address.                     |
| `nclient service port unforward <ref>`  |                                                                | Closes that relay.                                                       |
| `nclient service file config <ref>`     | `--path <path>`, `--username <name>`; the password at a prompt | Saves a share's path and login, and mounts it.                           |
| `nclient service file mount <ref>`      |                                                                | Mounts a share again with its saved login.                               |
| `nclient service file unmount <ref>`    |                                                                | Unmounts a share and keeps its login.                                    |
| `nclient service ai show`               |                                                                | Prints where this person's AI tools point.                               |
| `nclient service ai apply hub`          | the model flags; `--hub` makes that hub the exit               | Points the AI tools at the exit hub's gateway.                           |
| `nclient service ai apply off`          |                                                                | Puts the AI tools back to their own configuration.                       |
| `nclient service desktop connect <ref>` |                                                                | Opens the viewer at one shared desktop.                                  |

The model flags are `--claude-default`, `--claude-opus`, `--claude-sonnet`, `--claude-haiku`, `--codex-model`, `--codex-effort` (`minimal`, `low`, `medium` or `high`) and `--gemini-model`. An omitted flag keeps the saved choice, and `''` means the gateway default. On a computer with the agent installed, `ai show` adds the `ai_tools_managed` line, and both `ai apply` forms print `ai_tools_managed` and exit with status 1.

`nclient easytier-daemon` and `nclient files-daemon`, absent from `--help`, run the client's EasyTier service and the Windows `NeutrinoClientFiles` service.

## Global flags

`nclient --version` prints the package version, and `-h` prints the help of its level; both exit at once. `nclient` with no subcommand, `nclient service` with no kind, and a kind with no action print their help and exit with status 2. On macOS, the app bundle opened from the Finder starts as `nclient gui`.

## What status prints

```text
neutrino-client 0.5.0
hub        hub  https://192.168.100.1:8443  Connected · LAN · 12 ms  exit
resident   running
```

Each hub line holds the hub's name, its address and its state line as the window shows it; `exit` marks the hub the AI tools point at. `resident` reads `running`, or `not running` with the command that starts the client.

The exit status is 0 while the client runs and every hub is connected, and 1 otherwise. `--json` prints one object, with the same exit status:

```json
{
  "hubs": [
    {
      "connection": "connected",
      "gateway_url": "https://192.168.100.1:8443",
      "hub_id": "f3c1",
      "hub_name": "hub",
      "is_exit": true,
      "last_error": null,
      "next_round_at": null,
      "reached_through": "lan",
      "rtt_ms": 12,
      "wait_code": null,
      "wait_reason": ""
    }
  ],
  "is_running": true,
  "version": "0.5.0"
}
```

| Field             | Holds                                                          |
| ----------------- | -------------------------------------------------------------- |
| `connection`      | `connected`, `connecting`, `waiting`, `replaced` or `disabled` |
| `wait_reason`     | while `waiting`, the reason, such as `hub_silent`              |
| `wait_code`       | the `{code, params}` behind the wait, or `null`                |
| `next_round_at`   | the Unix time a countdown ends, or `null`                      |
| `reached_through` | the path: `lan`, `direct`, `netbird`, `easytier` or `relay`    |
| `rtt_ms`          | the last round trip in whole milliseconds, or `null`           |
| `is_exit`         | whether the AI tools point at this hub                         |
| `last_error`      | the last `{code, params}` the channel returned, or `null`      |
