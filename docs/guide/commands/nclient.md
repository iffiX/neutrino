---
title: nclient commands
---

# nclient commands

From a terminal, `nclient` drives the desktop client on Linux, Windows or macOS under a person's own account. The table lists its subcommands in the order `nclient --help` prints them.

## Privileges

Run as root, every subcommand prints `root_refused` and exits with status 2. `nclient leave` asks a `[y/N]` question before it leaves, and `--yes` leaves without asking. Without a terminal it asks nothing, prints that `--yes` goes ahead, and exits with status 1.

## Choosing a hub

Every subcommand that acts on one hub takes `--hub`, whose value is that hub's name or its id. With one hub joined, the flag can be left out. With several joined and none named, the command prints `ambiguous_hub` with the names; a name no binding has is `unknown_hub`.

## Subcommands

In the `service` rows, `<ref>` is the entry's number under its hub in `nclient service list`, or the entry's id.

| Command                                 | Arguments and flags                                                                                                                                                                                                                                                                          | What it does                                                                                                                                   |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `nclient join <link>`                   | `<link>` is the `neutrino://enroll/` link from a hub's **Clients** page; omitted, the command reads it at a prompt                                                                                                                                                                           | Joins the hub the link names, beside every hub already joined.                                                                                 |
| `nclient leave`                         | `--hub <name>`; `--yes` leaves without the question                                                                                                                                                                                                                                          | Leaves one hub and undoes what it published on this computer: its forwards, mounts and viewers.                                                |
| `nclient status`                        | `--json` prints one JSON object                                                                                                                                                                                                                                                              | Prints the version, one line per hub joined, and whether the client runs.                                                                      |
| `nclient gui`                           | `--hidden` starts without showing the window                                                                                                                                                                                                                                                 | Runs the client and its window.                                                                                                                |
| `nclient quit`                          |                                                                                                                                                                                                                                                                                              | Stops the running client. With none running, it prints `resident_not_running`.                                                                 |
| `nclient terminal <machine>`            | `<machine>` is a machine's name or id; `--session <id>` attaches to a shell session the machine keeps; `--hub <name>`                                                                                                                                                                        | Opens a shell on that machine in this terminal. Exits with status 0 after the shell closes, 1 on a refusal, and 2 for a machine no hub offers. |
| `nclient service list`                  | `--hub <name>` lists that hub alone                                                                                                                                                                                                                                                          | Prints every published entry, by hub and then by kind.                                                                                         |
| `nclient service web open <ref>`        | `--hub <name>`                                                                                                                                                                                                                                                                               | Opens one link in the browser.                                                                                                                 |
| `nclient service port forward <ref>`    | `--local-port <port>` is the loopback port to prefer; `--hub <name>`                                                                                                                                                                                                                         | Relays one port to this computer's loopback.                                                                                                   |
| `nclient service port unforward <ref>`  | `--hub <name>`                                                                                                                                                                                                                                                                               | Closes that relay.                                                                                                                             |
| `nclient service file config <ref>`     | `--path <path>` (required), `--username <name>`, `--hub <name>`; the password is typed at a prompt                                                                                                                                                                                           | Saves a share's login and path, and mounts it.                                                                                                 |
| `nclient service file mount <ref>`      | `--hub <name>`                                                                                                                                                                                                                                                                               | Mounts a share again with its saved login.                                                                                                     |
| `nclient service file unmount <ref>`    | `--hub <name>`                                                                                                                                                                                                                                                                               | Unmounts a share; its saved login stays.                                                                                                       |
| `nclient service ai show`               | `--hub <name>` shows that hub's gateway                                                                                                                                                                                                                                                      | Prints where this person's AI tools point.                                                                                                     |
| `nclient service ai apply hub`          | `--claude-default`, `--claude-opus`, `--claude-sonnet`, `--claude-haiku`, `--codex-model`, `--codex-effort` (`minimal`, `low`, `medium`, `high`), `--gemini-model`; an omitted flag keeps the saved choice, and `''` means the gateway default; `--hub <name>` makes that hub the exit first | Points the AI tools at the exit hub's gateway.                                                                                                 |
| `nclient service ai apply off`          |                                                                                                                                                                                                                                                                                              | Puts the AI tools back to their own configuration.                                                                                             |
| `nclient service desktop connect <ref>` | `--hub <name>`                                                                                                                                                                                                                                                                               | Opens the viewer at one shared desktop.                                                                                                        |

`nclient easytier-daemon` is absent from `--help`. It is the entry of the client's EasyTier service, which systemd and launchd run as root and the Windows service control manager runs as SYSTEM.

## Global flags

| Flag        | Where       | What it does                          |
| ----------- | ----------- | ------------------------------------- |
| `--version` | `nclient`   | Prints the package version and exits. |
| `-h`        | every level | Prints that level's help and exits.   |

`nclient` with no subcommand, `nclient service` with no kind, and a kind with no action print their help and exit with status 2. On macOS, the app bundle opened from Finder starts as `nclient gui`.

## What status prints

```text
neutrino-client 0.5.0
hub        home    https://192.168.100.1:8443  connected  exit
hub        office  https://10.8.0.1:8443       reconnecting: the hub cannot be reached
resident   running
```

Each hub line holds the hub's name, the address its channel last connected through, the channel's state, and the last code that channel returned. `exit` marks the hub this person's AI tools point at. The last line is the client itself, `running` or `not running`. The exit status is 0 while every hub reads `connected` and the client runs, and 1 otherwise.

With `--json`, the command prints one object instead, and exits with the same status:

```json
{
  "hubs": [
    {
      "connection": "connected",
      "gateway_url": "https://192.168.100.1:8443",
      "hub_id": "f3c1",
      "hub_name": "home",
      "is_exit": true,
      "last_error": null,
      "reached_through": "lan"
    }
  ],
  "is_running": true,
  "version": "0.5.0"
}
```

`reached_through` is the way the channel reached the hub: `lan`, `direct`, `netbird`, `easytier` or `relay`. With no client running, `connection` and `reached_through` are empty and `is_running` is `false`.
