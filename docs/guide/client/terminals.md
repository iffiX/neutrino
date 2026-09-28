---
title: Terminals
---

# Terminals

A terminal from the client is a shell on a machine a hub manages, shown in a tab of the client's window. The hub offers one on each managed machine to a client whose permissions include terminals.

## From the window

1. Select **Terminals** in the sidebar.
1. Pick the machine in the strip on top. The line under the strip names its hub and the machine.
1. Select **New terminal**.

The shell opens in a new tab under the strip, and the keys typed there go straight to the machine. Resizing the window resizes the shell. The **×** on a tab ends that shell, and a shell that exits closes its own tab. A shell the hub refuses keeps its tab, with the code written in it.

## From a terminal

```sh
nclient terminal lepton --hub home
```

The machine is named by its name or its id, and `--hub` picks the hub when two hubs offer machines of one name. Resizing the terminal resizes the shell. The command exits with status 0 once the shell ends, 1 on a refusal, and 2 for a machine no hub offers.

## When it is refused

| Code                | Meaning                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `permission_denied` | the hub's **Clients** page does not let this client open terminals |
| `agent_offline`     | the machine is not connected to its hub right now                  |
| `unknown_terminal`  | the hub offers no terminal on that machine                         |
| `kind_unknown`      | the hub runs a version older than 0.4.0; upgrade the hub           |
