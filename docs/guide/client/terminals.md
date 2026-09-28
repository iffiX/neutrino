---
title: Terminals
---

# Terminals

A terminal from the client is a shell on a machine a hub manages, opened in this computer's own terminal program. The hub offers it on each managed machine to a client whose permissions include terminals.

## From the window

1. Open the **Terminals** tab.
1. Find the machine under its hub.
1. Select **Open terminal**.

On Linux the first terminal program found opens, `x-terminal-emulator` first. On Windows it is Windows Terminal, or a console where that is not installed. On macOS it is Terminal.

## From a terminal

```sh
nclient terminal lepton --hub home
```

The machine is named by its name or its id, and `--hub` picks the hub when two hubs offer machines of one name. Resizing the terminal resizes the shell. The command exits with status 0 once the shell ends, 1 on a refusal, and 2 for a machine no hub offers.

## When it is refused

| Code                   | Meaning                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| `permission_denied`    | the hub's **Clients** page does not let this client open terminals |
| `agent_offline`        | the machine is not connected to its hub right now                  |
| `unknown_terminal`     | the hub offers no terminal on that machine                         |
| `terminal_app_missing` | no terminal program was found on this computer                     |
| `kind_unknown`         | the hub runs a version older than 0.4.0; upgrade the hub           |
