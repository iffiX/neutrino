---
title: nclient commands
---

# nclient commands

`nclient` drives the desktop client from a terminal on Linux, Windows or macOS, under a person's own account. The table lists its subcommands in the order `nclient --help` prints them.

## Privileges

Run as root, every subcommand prints `root_refused` and exits with status 2. One person's client runs on a computer at a time. While another account's client runs, `nclient gui` exits with no window, and every subcommand except `quit` prints `client_held` and exits with status 1.

## Choosing a hub

`--hub <name>` names a hub on `leave`, every `terminal` subcommand and every `service` subcommand. With several hubs and none named, the command prints `ambiguous_hub`; an unknown name gives `unknown_hub`.

## Subcommands

`<ref>` is an entry's number in `nclient service list`, or its id. `<machine>` is a machine's name or id; a machine named after a `terminal` subcommand goes after `open`. `<session-id>` is a session id, or a prefix of it that matches one session on that machine. A prefix that matches several prints each of them and exits with status 2.

| Command                                           | Arguments and flags                                                                                                                   | What it does                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `nclient join <link>`                             | the link from a hub's **Clients** page, else a prompt                                                                                 | Joins the hub the link names, beside the others.                                                                                                                                                                                                                                                                                                                                     |
| `nclient leave`                                   | `--yes` skips the `[y/N]` question                                                                                                    | Leaves one hub and ends its forwards, mounts and viewers.                                                                                                                                                                                                                                                                                                                            |
| `nclient status`                                  | `--json` prints one JSON object                                                                                                       | Prints the version, each hub's state and the client's.                                                                                                                                                                                                                                                                                                                               |
| `nclient gui`                                     | `--hidden` starts without showing the window                                                                                          | Runs the client and its window.                                                                                                                                                                                                                                                                                                                                                      |
| `nclient quit`                                    |                                                                                                                                       | Stops the running client, or prints `resident_not_running`.                                                                                                                                                                                                                                                                                                                          |
| `nclient terminal list`                           | `--json` prints one JSON object                                                                                                       | Prints each online machine the client can open a shell or run a command on, and the sessions it keeps. Each session shows its id's first eight characters, title, account, owner and how many windows are attached, and whether this client owns it, keeps it or shares it. Exits with 0, or 1 when the running client cannot be reached.                                            |
| `nclient terminal open <machine>`                 | `--persistent` keeps the session after its last window closes; `--shared` lists it for every client with **Terminals** on the machine | Opens a new shell on the machine in this terminal; `nclient terminal <machine>` does the same. Exits with 0 when the shell closes, 1 on a refusal, 2 when no hub offers the machine.                                                                                                                                                                                                 |
| `nclient terminal attach <machine> <session-id>`  |                                                                                                                                       | Attaches this terminal to a session the machine keeps, one this client owns or a shared one, and prints its kept output first. Exits as `open` does, and with 2 for a session the machine does not list.                                                                                                                                                                             |
| `nclient terminal exec <machine> -- <command>`    | `<command>` is the program and its arguments; `--tty` runs it on a pseudo-terminal, for programs such as `top` and `vim`              | Runs one command on the machine, as the account its Terminal module names, root by default. Standard input goes to the command unchanged, and its standard output and standard error come back apart; each can be a file or a pipe. Needs **Remote commands** in the client's permission. Exits with the command's own status, 125 on a refusal, 126 when no hub offers the machine. |
| `nclient terminal persist <machine> <session-id>` | `--on` or `--off`                                                                                                                     | With `--on`, keeps the session after its last window closes; with `--off`, the session ends when its last window closes. Only the session's owner can change it; another client gets `session_not_owned`. Exits with 0, 1 on a refusal, 2 for a session the machine does not list.                                                                                                   |
| `nclient terminal share <machine> <session-id>`   | `--on` or `--off`                                                                                                                     | With `--on`, every other client with **Terminals** on the machine lists the session and can attach; `--off` closes their windows on it at once. Only the session's owner can change it. Exits as `persist` does.                                                                                                                                                                     |
| `nclient terminal stop <machine> <session-id>`    |                                                                                                                                       | Ends a session the machine keeps, as **Stop** on the panel's **Terminals** page does. Exits as `persist` does.                                                                                                                                                                                                                                                                       |
| `nclient service list`                            |                                                                                                                                       | Prints every published entry, by hub and then by kind.                                                                                                                                                                                                                                                                                                                               |
| `nclient service web open <ref>`                  |                                                                                                                                       | Opens one link in the browser.                                                                                                                                                                                                                                                                                                                                                       |
| `nclient service port forward <ref>`              | `--local-port <port>`, the port to prefer                                                                                             | Relays one port to this computer's loopback address.                                                                                                                                                                                                                                                                                                                                 |
| `nclient service port unforward <ref>`            |                                                                                                                                       | Closes that relay.                                                                                                                                                                                                                                                                                                                                                                   |
| `nclient service file config <ref>`               | `--path <path>`, `--username <name>`; the password at a prompt                                                                        | Saves a share's path and login, and mounts it.                                                                                                                                                                                                                                                                                                                                       |
| `nclient service file mount <ref>`                |                                                                                                                                       | Mounts a share again with its saved login.                                                                                                                                                                                                                                                                                                                                           |
| `nclient service file unmount <ref>`              |                                                                                                                                       | Unmounts a share and keeps its login.                                                                                                                                                                                                                                                                                                                                                |
| `nclient service ai show`                         |                                                                                                                                       | Prints where this person's AI tools point.                                                                                                                                                                                                                                                                                                                                           |
| `nclient service ai apply hub`                    | the model flags; `--hub` makes that hub the exit                                                                                      | Points the AI tools at the exit hub's gateway.                                                                                                                                                                                                                                                                                                                                       |
| `nclient service ai apply off`                    |                                                                                                                                       | Puts the AI tools back to their own configuration.                                                                                                                                                                                                                                                                                                                                   |
| `nclient service desktop connect <ref>`           |                                                                                                                                       | Opens the viewer at one shared desktop.                                                                                                                                                                                                                                                                                                                                              |

`exec` exits with 125 and 126 for its own outcomes, so they stay apart from a remote command's own 1 and 2, as with `ssh` and `docker`.

The model flags are `--claude-default`, `--claude-opus`, `--claude-sonnet`, `--claude-haiku`, `--codex-model`, `--codex-effort` (`minimal`, `low`, `medium` or `high`) and `--gemini-model`. An omitted flag keeps the saved choice, and `''` means the gateway default. On a computer with the agent installed, `ai show` adds the `ai_tools_managed` line, and both `ai apply` forms print `ai_tools_managed` and exit with status 1.

`nclient easytier-daemon` and `nclient files-daemon`, absent from `--help`, run the client's EasyTier service and the Windows `NeutrinoClientFiles` service.

## Terminal examples

Each line runs against a machine named `server`. The first two run one command each, and the rest open a persistent session, list it, share it, attach to it, stop sharing it and end it:

```bash
nclient terminal exec server -- uptime
cat dump.sql | nclient terminal exec server -- psql app | tee result.txt
nclient terminal open server --persistent
nclient terminal list
nclient terminal share server 3f2a --on
nclient terminal attach server 3f2a
nclient terminal share server 3f2a --off
nclient terminal stop server 3f2a
```

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
