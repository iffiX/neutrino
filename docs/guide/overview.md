---
title: Overview
---

# Overview

Neutrino is three packages: a hub on one always-on Linux box, an agent on every
machine the hub manages, and a client in every person's session. This page is
the shape of that arrangement. For the commands, read [CLI](./cli.md); for the
walk that installs it, read [Quick start](./quick-start.md).

What the shape does not cover:

- The hub runs on Linux, x86-64 or ARM64. The agent runs on Linux. There is no
  Windows agent and no macOS agent, and the client refuses macOS by name.
- The panel is HTTP. Reach it over the LAN, or over an overlay.
- The agent has no window. It is joined and driven from a terminal.
- A machine whose agent is offline cannot be edited. The panel refuses the
  change rather than queueing it.

## Three packages

| Package           | Tree      | Platforms           | Runs as                            | Job                                                                                                         |
| ----------------- | --------- | ------------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `neutrino-hub`    | `hub/`    | Linux x86-64, ARM64 | root, panel and units              | Router (xray, nftables, dnsmasq), AI gateway, overlay, discovery, relay, clients, credentials               |
| `neutrino-agent`  | `agent/`  | Linux               | root, headless, listens on nothing | Samba, Gitea, Podman, ZFS and the RustDesk host on a machine, the hub box included                          |
| `neutrino-client` | `client/` | Linux, Windows      | a person's session, never root     | Mount a share, open a service, forward a port, view a desktop, switch a machine's AI tools onto the gateway |

- The hub box can be small, because it hosts no module itself. Samba, Gitea,
  Podman, ZFS and the RustDesk host all run under the agent.
- Every machine that owns a disk, a GPU or a desktop gets an agent. Setup
  installs one on the hub box too.
- Each package carries its own interpreter, so no machine's Python is touched.
  The hub carries xray, CLIProxyAPI, the NetBird client, the EasyTier engine
  and the agent packages it hands out; the agent carries the RustDesk host; the
  client carries cc-switch and the RustDesk viewer. Every carried binary is
  pinned by version and sha256 in its module's `constants.py`.

![The Dashboard with live throughput, the exits in use and DNS queries](/guide/en/dashboard.webp)

## One hub, agents, clients

```text
studio  --agent channel-->  home-hub  <--client channel--  laptop
                            (the hub never dials back)
```

- **The channel**: the agent opens one persistent WebSocket to the hub, over
  TLS pinned by the fingerprint inside its enrollment link. Desired state,
  shell, files, commands, reports and operation streams all ride on it.
- **Direction**: the hub never dials a device. SSH exists only to install or
  reinstall an agent.
- **Presence**: online, version and last seen live in memory. Nothing about a
  socket reaches `config/`.
- **Desired state**: the hub composes one document per device from `config/`.
  The agent keeps a copy, compares it on connect, and applies what differs.
- **Offline**: editing a module of an offline device is refused, with "The
  agent is offline."
- **Source of truth**: `config/<module>/*.json` and nothing else. Every change
  is render, then validate, then apply, and the panel and `nhub apply` drive
  the same pipeline.

## The panel's two groups

The rail splits by who the page acts on. **Hub** pages act on the box itself;
**Agent** pages act on a machine running the agent, the hub box included.

| Hub page    | What it is for                         |
| ----------- | -------------------------------------- |
| Dashboard   | Live throughput, exits and DNS         |
| Network     | Interface roles, uplinks and DHCP      |
| Overlay     | Remote access to this gateway          |
| Proxy       | Exit nodes, split routing and DNS      |
| AI          | One endpoint for every AI tool         |
| Devices     | LAN hosts and remote actions           |
| Clients     | Machines that reach the hub as clients |
| Services    | What the hub publishes to devices      |
| Credentials | SSH keys and AI provider tokens        |
| Settings    | Password, backup and versions          |

| Agent page | What it is for                           |
| ---------- | ---------------------------------------- |
| Terminals  | A shell on a managed machine             |
| Files      | Browse and move files on a machine       |
| Samba      | Shares a machine serves over SMB         |
| Gitea      | The private git server                   |
| Containers | Containers a machine runs through podman |
| ZFS        | Pools, datasets and disk health          |

![The sidebar, with the Hub group above the Agent group](/guide/en/sidebar_groups.webp)

::: tip
The hub box carries an agent of its own, so one machine can be the hub, the
Samba server and a shared desktop at the same time. Its Agent pages act on it
like any other device.
:::

- Every group of settings ends with one apply bar. Saving and applying are one
  action.
- A panel WebSocket at `/ws/events` invalidates page caches. Nothing polls,
  except tables reading a daemon's own state.
- Every refusal from the backend is a code with parameters, never an English
  sentence. The wording lives in the frontend catalogs, which is why the panel
  and the client both speak English and Simplified Chinese.

## Reaching home from outside

One overlay runs at a time: none, NetBird or EasyTier. The choice is the
overlay row in `config/router/network.json`, which the firewall reads too. Both
engines run under the hub's own units, from `/opt/neutrino/bin`.

![The Overlay page, with the none, NetBird and EasyTier choices](/guide/en/overlay_chooser.webp)

Whether this box answers on the overlay is set under Network, Exposure. For the
engines themselves, see [Overlay with NetBird](./overlay-netbird.md) and
[Overlay with EasyTier](./overlay-easytier.md).

## Versions

The three packages carry one version number. A mismatch is asked to upgrade,
never negotiated with, and there are no migrations.

- A client that is ahead refuses with "this client ({client_version}) is newer
  than the hub ({hub_version}); update the hub first".
- A device drawer holding a mismatched agent reads "This agent is a different
  version from the hub."

![The Settings page's About section, with the hub version and the package versions](/guide/en/settings_about.webp)

Upgrade in one order: the hub, then the agents, then the clients. The commands
are in [Upgrade and reset](./upgrade-reset.md).
