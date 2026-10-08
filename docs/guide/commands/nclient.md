---
title: nclient commands
---

# nclient commands

From a terminal, `nclient` drives the desktop client on Linux, Windows or macOS under a person's own account. The table lists its subcommands in the order `nclient --help` prints them.

## Privileges

Run as root, every subcommand prints `root_refused` and exits with status 2. `nclient leave` asks a `[y/N]` question before it leaves, and `--yes` leaves without asking. With no terminal on standard input and no `--yes`, it prints a line naming `--yes` and exits with status 1.

One person's client runs on a computer at a time. While another account's client runs, every subcommand except `gui` and `quit` prints `client_held` with that account's name and exits with status 1. `nclient gui` exits with no window and no message.

## Choosing a hub

Every subcommand that acts on one hub takes `--hub`, whose value is that hub's name or id, written `<name>` in the table. With one hub joined, the flag can be left out. With several joined and none named, the command prints `ambiguous_hub`; a name no joined hub has gives `unknown_hub`.

## Subcommands

In the `service` rows, `<ref>` is the entry's number under its hub in `nclient service list`, or the entry's id.

| Command                                 | Arguments and flags                                                                                                                                                                                                                                                                          | What it does                                                                                                                                                                                                                    |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nclient join <link>`                   | `<link>` is the `neutrino://enroll/` link from a hub's **Clients** page; omitted, the command reads it at a prompt                                                                                                                                                                           | Joins the hub the link names, beside every hub already joined.                                                                                                                                                                  |
| `nclient leave`                         | `--hub <name>`; `--yes` leaves without the question                                                                                                                                                                                                                                          | Leaves one hub and ends what it published on this computer: its forwards, mounts and viewers.                                                                                                                                   |
| `nclient status`                        | `--json` prints one JSON object                                                                                                                                                                                                                                                              | Prints the version, one line per hub joined, and whether the client runs.                                                                                                                                                       |
| `nclient gui`                           | `--hidden` starts without showing the window                                                                                                                                                                                                                                                 | Runs the client and its window.                                                                                                                                                                                                 |
| `nclient quit`                          |                                                                                                                                                                                                                                                                                              | Stops the running client. With none running, it prints `resident_not_running`.                                                                                                                                                  |
| `nclient terminal <machine>`            | `<machine>` is a machine's name or id; `--session <id>` attaches to a shell session the machine keeps; `--hub <name>`                                                                                                                                                                        | Opens a shell on that machine in this terminal. Exits with status 0 after the shell closes, 1 on a refusal, and 2 for a machine no hub offers.                                                                                  |
| `nclient service list`                  | `--hub <name>` lists that hub alone                                                                                                                                                                                                                                                          | Prints every published entry, by hub and then by kind.                                                                                                                                                                          |
| `nclient service web open <ref>`        | `--hub <name>`                                                                                                                                                                                                                                                                               | Opens one link in the browser.                                                                                                                                                                                                  |
| `nclient service port forward <ref>`    | `--local-port <port>` is the loopback port to prefer; `--hub <name>`                                                                                                                                                                                                                         | Relays one port to this computer's loopback address.                                                                                                                                                                            |
| `nclient service port unforward <ref>`  | `--hub <name>`                                                                                                                                                                                                                                                                               | Closes that relay.                                                                                                                                                                                                              |
| `nclient service file config <ref>`     | `--path <path>` (required), `--username <name>`, `--hub <name>`; the password is typed at a prompt                                                                                                                                                                                           | Saves a share's login and path, and mounts it.                                                                                                                                                                                  |
| `nclient service file mount <ref>`      | `--hub <name>`                                                                                                                                                                                                                                                                               | Mounts a share again with its saved login.                                                                                                                                                                                      |
| `nclient service file unmount <ref>`    | `--hub <name>`                                                                                                                                                                                                                                                                               | Unmounts a share; its saved login stays.                                                                                                                                                                                        |
| `nclient service ai show`               | `--hub <name>` shows that hub's gateway                                                                                                                                                                                                                                                      | Prints where this person's AI tools point. On a computer with the agent installed, it adds the `ai_tools_managed` line.                                                                                                         |
| `nclient service ai apply hub`          | `--claude-default`, `--claude-opus`, `--claude-sonnet`, `--claude-haiku`, `--codex-model`, `--codex-effort` (`minimal`, `low`, `medium`, `high`), `--gemini-model`; an omitted flag keeps the saved choice, and `''` means the gateway default; `--hub <name>` makes that hub the exit first | Points the AI tools at the exit hub's gateway, the hub the tools point at. On a computer with the agent installed, it prints `ai_tools_managed`, changes nothing and exits with status 1; the hub's panel sets the tools there. |
| `nclient service ai apply off`          |                                                                                                                                                                                                                                                                                              | Puts the AI tools back to their own configuration. On a computer with the agent installed, it prints `ai_tools_managed` and exits with status 1.                                                                                |
| `nclient service desktop connect <ref>` | `--hub <name>`                                                                                                                                                                                                                                                                               | Opens the viewer at one shared desktop.                                                                                                                                                                                         |

`nclient easytier-daemon` and `nclient files-daemon` are absent from `--help`. The first is the entry of the client's EasyTier service, run as root by systemd and launchd and as SYSTEM on Windows. The second is the entry of the Windows `NeutrinoClientFiles` service, run as SYSTEM.

## Global flags

| Flag        | Where       | What it does                          |
| ----------- | ----------- | ------------------------------------- |
| `--version` | `nclient`   | Prints the package version and exits. |
| `-h`        | every level | Prints that level's help and exits.   |

`nclient` with no subcommand, `nclient service` with no kind, and a kind with no action print their help and exit with status 2. On macOS, the app bundle opened from the Finder starts as `nclient gui`.

## What status prints

```text
neutrino-client 0.5.0
hub        hub  https://192.168.100.1:8443  connected · LAN · 12 ms  exit
resident   running
```

Each hub line starts with the word `hub`, then holds the hub's name, the address its channel last connected through, and the channel's state. A connected hub adds the path and the last round trip. Another state adds the last code's sentence after a colon, as in `down: The hub cannot be reached`.

`exit` marks the hub this person's AI tools point at. The last line, `resident`, is the running client itself: `running`, or `not running` with the command that starts it.

The exit status is 0 while every hub reads `connected` and the client runs, and 1 otherwise. With `--json`, the command prints one object instead and exits with the same status:

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
      "reached_through": "lan",
      "rtt_ms": 12
    }
  ],
  "is_running": true,
  "version": "0.5.0"
}
```

| Field             | Holds                                                                                                                               |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `connection`      | `connected`, `connecting`, `down`, `pending`, `replaced` or `disabled`; empty while no client runs                                  |
| `reached_through` | the path the channel took: `lan`, `direct`, `netbird`, `easytier` or `relay`; empty before the hub names one                        |
| `rtt_ms`          | the last round trip in whole milliseconds; `null` before the first measure, while the hub is not connected, or while no client runs |
| `is_exit`         | whether the AI tools point at this hub                                                                                              |
| `last_error`      | the last `{code, params}` the channel returned, or `null`                                                                           |
