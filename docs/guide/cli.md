---
title: CLI
---

# CLI

Three programs: `nhub` on the hub box, `nagent` on a managed machine, `nclient`
in a person's session. This page lists their verbs and flags. For how to use
one, follow the link on the verb.

- `nhub` needs root for every verb but `run` and `scan-secrets`. Without it, it
  prints the `sudo` line and exits 2.
- `nagent` needs root for every verb, each with its own stated reason.
- `nclient` refuses to run as root: "the client runs as a person, never as
  root", exit 2.
- There is no `nagent gui`, no `nagent module` and no `nagent service`. The
  panel's own hints still mention the first.
- `nhub setup --yes` does not exist. Setup's non-interactive forms are
  `--stdin` and `--json PATH`.
- A program called with no subcommand prints help and returns 2. An `nhub`
  verb stopped with Ctrl-C prints `nhub <command> was stopped` and returns 130.

## nhub

Top-level flags: `--version`, `--dev`, `-h`.

### setup

Set this gateway up, once. Root.

| Flag          | Meaning                                                    |
| ------------- | ---------------------------------------------------------- |
| `--stdin`     | read every answer, as one JSON object, from standard input |
| `--json PATH` | read every answer from this JSON file                      |

`--stdin` and `--json` exclude each other. See [Quick start](./quick-start.md).

### run

Run the control panel in the foreground. No root: this is every unit's
`ExecStart`, and systemd starts the proxy core deliberately unprivileged.

| Flag                                                                                                      | Meaning                                        |
| --------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `--host HOST`                                                                                             | address to bind                                |
| `--port PORT`                                                                                             | port to bind (default: from config)            |
| `--reload`                                                                                                | restart the panel on source changes            |
| `--interface INTERFACE`                                                                                   | which interface, for the per-interface engines |
| `--only-web`, `--only-xray`, `--only-cliproxyapi`, `--only-dnsmasq`, `--only-supplicant`, `--only-dhcpcd` | run only that process, as its unit does        |

### stop

Stop what the hub runs on this box. Root.

| Flag                                                                                                                       | Meaning                                        |
| -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `--interface INTERFACE`                                                                                                    | which interface, for the per-interface engines |
| `--only-web`, `--only-cliproxyapi`, `--only-dnsmasq`, `--only-xray`, `--only-router`, `--only-supplicant`, `--only-dhcpcd` | stop only that service                         |

### apply

Render every generated config from `config/`, validate it, and make it true on
the box. Root.

| Flag                                                | Meaning                                                         |
| --------------------------------------------------- | --------------------------------------------------------------- |
| `--only {router,xray,dnsmasq,cliproxyapi,easytier}` | render and apply only this component; repeatable (default: all) |
| `--dry-run`                                         | render and print the artifacts without writing or applying them |
| `--skip-apply`                                      | write the generated files but do not restart any service        |

The unit files ship in the package rather than being rendered, so an upgrade
that changes one lands here, and a unit already current is left alone. See
[Proxy](./proxy.md) and [Network modes](./network-modes.md).

### unlock

Clear the login lockout and every fail2ban SSH ban. Root. No flags. See
[Upgrade and reset](./upgrade-reset.md).

### reset

Return part of the box to a fresh state. Root.

| Argument   | Meaning                                                                                      |
| ---------- | -------------------------------------------------------------------------------------------- |
| `all`      | configuration back to the examples, every collected key and token gone, the services stopped |
| `password` | a new panel password, and every session signed out                                           |
| `--stdin`  | read the new password from standard input rather than prompting                              |

See [Upgrade and reset](./upgrade-reset.md).

### vault rekey

Wrap the data key under a new master passphrase. Root. `vault` takes this one
action.

| Flag      | Meaning                                                           |
| --------- | ----------------------------------------------------------------- |
| `--stdin` | read the new passphrase from standard input rather than prompting |

Nothing sealed is re-encrypted: the data key does not change, only what opens
it. See [Backup and restore](./backup-restore.md).

### scan-secrets

Check what a commit would carry. No root. A development command.

| Flag           | Meaning                                                    |
| -------------- | ---------------------------------------------------------- |
| `--staged`     | only files staged for the next commit                      |
| `--history`    | every blob in every reachable commit, not the working tree |
| `--no-entropy` | skip the high-entropy rule, which is the noisiest          |
| `--no-vendor`  | skip detect-secrets and gitleaks even when installed       |
| `--quiet`      | print findings only, no summary                            |

## nagent

Top-level flags: `--version`, `-h`. There is no `--dev`.

### connect

Join the hub a link names. Root, because "it writes the binding and starts the
service".

| Argument | Meaning                                                                         |
| -------- | ------------------------------------------------------------------------------- |
| `link`   | the `neutrino://enroll` link from the hub; omit it to paste at a prompt instead |
| `--yes`  | replace an existing binding without asking                                      |

See [Devices and remote desktop](./devices-remote-desktop.md).

### disconnect

Leave the hub. Root, because "it removes the binding". No flags.

### status

What this machine is bound to. Root, because "it asks the agent over its
root-only control socket". No flags.

### sync

Ask the hub for this machine's state now. Root, for the same reason as
`status`. No flags.

### run

Run the agent in the foreground. Root, because "the agent manages this
machine". No flags.

### rdp start

Share this desktop at the seat password the hub set. Root, because "it
configures this machine's desktop share".

| Flag          | Meaning                                                                                |
| ------------- | -------------------------------------------------------------------------------------- |
| `--user USER` | whose desktop; unnamed, the account that invoked sudo or the one account at the screen |

See [Devices and remote desktop](./devices-remote-desktop.md).

### rdp stop

Stop sharing this desktop. Root. No flags. On a machine that is not sharing it
prints "this machine's desktop is not shared" and returns 0.

## nclient

Top-level flags: `--version`, `-h`. Every verb runs as the person, never as
root.

### connect

Join the hub a link names.

| Argument | Meaning                                                                         |
| -------- | ------------------------------------------------------------------------------- |
| `link`   | the `neutrino://enroll` link from the hub; omit it to paste at a prompt instead |
| `--yes`  | replace an existing binding without asking                                      |

See [Clients](./clients.md).

### disconnect

Leave the hub. No flags.

### status

What this person is bound to. No flags.

### gui

Run the client and its window. See [Clients](./clients.md).

| Flag       | Meaning                          |
| ---------- | -------------------------------- |
| `--hidden` | start without showing the window |

### quit

Stop the running client. No flags. With nothing running it answers "the client
is not running".

### service

What the hub publishes for this person. `service` with no kind prints help and
returns 2, and so does a kind with no action.

| Kind      | Action      | Arguments                                              | Meaning                                      |
| --------- | ----------- | ------------------------------------------------------ | -------------------------------------------- |
| `list`    | none        | none                                                   | every published entry, nested by kind        |
| `web`     | `open`      | `ref`                                                  | open one link in the browser                 |
| `port`    | `forward`   | `ref`, `--local-port LOCAL_PORT`                       | relay one port to this machine's loopback    |
| `port`    | `unforward` | `ref`                                                  | close that relay                             |
| `file`    | `config`    | `ref`, `--path PATH` (required), `--username USERNAME` | save a share's login and path, and mount it  |
| `file`    | `mount`     | `ref`                                                  | mount a share again with its saved login     |
| `file`    | `unmount`   | `ref`                                                  | unmount a share; its saved login stays       |
| `ai`      | `show`      | none                                                   | where this person's tools point              |
| `ai`      | `apply`     | `{hub,off}` and the model flags below                  | point the tools at the hub, or put them back |
| `desktop` | `connect`   | `ref`                                                  | open the viewer at one shared desktop        |

`ref` is "the entry's number in `service list`, or its id".

`ai apply` takes `hub` or `off`: "hub points the tools at the gateway; off puts
them back". Its model flags are `--claude-default`, `--claude-opus`,
`--claude-sonnet`, `--claude-haiku`, `--codex-model`, `--gemini-model` and
`--codex-effort`, each "omit to keep, pass `''` for the gateway default".
`--codex-effort` takes `minimal`, `low`, `medium`, `high` or `''`. See
[AI gateway](./ai-gateway.md) and [Clients](./clients.md).

## Shared flags

| Flag           | Where                                          | Meaning                                                    |
| -------------- | ---------------------------------------------- | ---------------------------------------------------------- |
| `--version`    | all three                                      | prints the package version and exits                       |
| `-h`, `--help` | every level of every parser                    | prints help and exits                                      |
| `--dev`        | `nhub` only                                    | runs against `hub_dev_root/` in the working copy           |
| `--stdin`      | `nhub setup`, `nhub reset`, `nhub vault rekey` | reads the secret from standard input rather than prompting |
| `--yes`        | `nagent connect`, `nclient connect`            | replaces an existing binding without asking                |

`--dev` refuses outside a working copy: "--dev runs from a working copy, and
this hub came from a package".
