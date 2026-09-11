<div align="center">

<img src="images/web/banner.webp" width="100%" alt="Neutrino banner" />

# One box at home. Every machine you own inherits it.

**English** · [中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/license-MIT-0a0e14?labelColor=0a0e14&color=22d3ee)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-0a0e14?labelColor=0a0e14&color=22d3ee)](https://github.com/iffiX/neutrino/releases)
[![Hub: Linux](https://img.shields.io/badge/hub-Linux%20x86--64%20%C2%B7%20ARM64-0a0e14?labelColor=0a0e14&color=a78bfa)](#what-runs-where)
[![Agent: Linux](https://img.shields.io/badge/agent-Linux-0a0e14?labelColor=0a0e14&color=a78bfa)](#what-runs-where)
[![Client: Linux · Windows](https://img.shields.io/badge/client-Linux%20%C2%B7%20Windows-0a0e14?labelColor=0a0e14&color=a78bfa)](#what-runs-where)

A neutrino passes through walls without touching them.<br/>
The wall is still there. It just stops being yours.

**[Install](#install)** · **[Documentation](https://iffix.github.io/neutrino/)** · [Showcase](#showcase) · [Panel](#the-panel) · [Why](#why-i-built-it)

</div>

Neutrino is a self-hosted control plane for one person's machines: a hub, an
agent on each machine it manages, and a client in each person's session.

Set a service up once on the hub and it is a button in every client window:
Open, Connect, Config then Apply, Mount, Connect.

The hub is a flashed TV box or a Pi; the NAS, the workstation and the GPU box
keep their jobs and get an agent.

<a href="images/web/one_click.webp"><img src="images/web/one_click.webp" width="100%" alt="The Services page on the hub beside the client window, the same five entries on both" /></a>

The Services page on the hub, and the client window on a laptop.

## Install

### Hub

```bash
sudo apt install ./neutrino-hub_0.2.0_amd64.deb && sudo nhub setup
```

Setup asks six screens: Language, Secrets, Shape, Ports, Proxy, Ready. Server
mode leaves every address on the box alone and tells no device to route
through it. The panel is then at `http://<hub>:8080`.

### Agent

Open the Devices page, press "Add by link", and run the link on the machine
within five minutes:

```bash
sudo nagent connect '<link>'
```

The device drawer installs the agent over SSH instead, if you prefer.

### Client

Open the Clients page, press "New client link", and paste the link into the
client window on that machine.

The hub's `.rpm` and Arch package, and the client's `.msi`, are on
[Releases](https://github.com/iffiX/neutrino/releases). The full walk with
screenshots is the [Quick start](https://iffix.github.io/neutrino/quick-start.html).

## Documentation

- [Quick start](https://iffix.github.io/neutrino/quick-start.html)
- [Guides](https://iffix.github.io/neutrino/overview.html)
- [CLI reference](https://iffix.github.io/neutrino/cli.html)

## Showcase

Chores that stop: copying API keys onto every machine, remembering which
address a share is at, opening an SSH tunnel by hand each time, hunting for a
RustDesk ID, setting up a proxy per box.

| Panel           | Set on the hub                      | Where the entry comes from                        | The client's button   |
| --------------- | ----------------------------------- | ------------------------------------------------- | --------------------- |
| Web             | a link                              | the Gitea module, or declared by hand             | "Open"                |
| Ports           | a port                              | a container's published port, or declared by hand | "Connect"             |
| AI              | providers and accounts              | the AI gateway                                    | "Config" then "Apply" |
| Files           | a share                             | the Samba module, or declared by hand             | "Mount"               |
| Remote desktops | nothing; the machine shares its own | `sudo nagent rdp start`                           | "Connect"             |

<table>
<tr valign="top">
<td width="33%"><img src="images/screenshots/client_web.webp" width="100%" alt="The client's Web panel with one link and an Open button" /></td>
<td width="33%"><img src="images/screenshots/client_ports.webp" width="100%" alt="The client's Ports panel forwarding a port to localhost" /></td>
<td width="33%"><img src="images/screenshots/client_ai.webp" width="100%" alt="The client's AI panel with Config and Apply" /></td>
</tr>
<tr valign="top">
<td><img src="images/screenshots/client_files.webp" width="100%" alt="The client's Files panel mounting the media share" /></td>
<td><img src="images/screenshots/client_desktops.webp" width="100%" alt="The client's Remote desktops panel with a Connect button" /></td>
<td><img src="images/screenshots/client_windows.webp" width="100%" alt="The same client window on Windows" /></td>
</tr>
</table>

- AI keys are minted per client and metered on the hub.
- "Config" points Claude Code, Codex and Gemini CLI at the gateway through cc-switch; off restores each tool's own configuration.
- Files mount under your home directory on Linux, or on drive `N:` on Windows.
- A forwarded port answers at `127.0.0.1:<port>` on the client's machine.
- The remote desktop seat password is held by the hub and never shown.
- Linux and Windows run the same client window.

## The panel

<table>
<tr valign="top">
<td width="50%"><a href="images/screenshots/dashboard.webp"><img src="images/screenshots/dashboard.webp" width="100%" alt="Dashboard with throughput, exits and DNS queries" /></a><p>Dashboard: what the hub routes right now.</p></td>
<td width="50%"><a href="images/screenshots/devices.webp"><img src="images/screenshots/devices.webp" width="100%" alt="Devices page listing managed and unmanaged machines" /></a><p>Devices: enroll a machine with a link.</p></td>
</tr>
<tr valign="top">
<td><a href="images/screenshots/services.webp"><img src="images/screenshots/services.webp" width="100%" alt="Services page with the web, ports, AI and files groups" /></a><p>Services: declare a service by hand.</p></td>
<td><a href="images/screenshots/ai_accounts.webp"><img src="images/screenshots/ai_accounts.webp" width="100%" alt="AI providers, subscription accounts and gateway keys" /></a><p>AI: sign in to a subscription once.</p></td>
</tr>
<tr valign="top">
<td><a href="images/screenshots/proxy.webp"><img src="images/screenshots/proxy.webp" width="100%" alt="Proxy page with exit nodes and split routing" /></a><p>Proxy: add an exit node from a share link.</p></td>
<td><a href="images/screenshots/samba.webp"><img src="images/screenshots/samba.webp" width="100%" alt="Samba page with shares, users and sessions" /></a><p>Samba: publish a share.</p></td>
</tr>
</table>

<div align="center">

<img src="images/screenshots/dashboard_portrait.webp" width="200" alt="Dashboard on a phone" /> <img src="images/screenshots/proxy_portrait.webp" width="200" alt="Proxy page on a phone" />
<img src="images/screenshots/ai_portrait.webp" width="200" alt="AI page on a phone" /> <img src="images/screenshots/services_portrait.webp" width="200" alt="Services page on a phone" />

</div>

The panel is drawn for phone width too.

## What runs where

| Package           | Platforms           | Runs as                            | Job                                                                            |
| ----------------- | ------------------- | ---------------------------------- | ------------------------------------------------------------------------------ |
| `neutrino-hub`    | Linux x86-64, ARM64 | root, panel and units              | Router, AI gateway, overlay, discovery, relay, clients, credentials            |
| `neutrino-agent`  | Linux               | root, headless, listens on nothing | Samba, Gitea, Podman, ZFS and the RustDesk host on a machine                   |
| `neutrino-client` | Linux, Windows      | a person's session, never root     | Mount a share, open a service, forward a port, view a desktop, switch AI tools |

One version for all three; a mismatch is asked to upgrade. The hub box can be
small because it hosts nothing itself. macOS runs none of the three.

## Security

<img src="images/web/warning_en.webp" width="100%" alt="Keep the hub on a network you own, and enroll only machines you trust" />

- The hub and the agent run as root. The client never does, and its one
  escalation is a polkit helper that mounts a share.
- The panel is HTTP. Reach it over the LAN or over an overlay.
- An enrollment link expires in five minutes and is consumed once, the agent
  channel's TLS is pinned by the fingerprint inside that link, and the vault is
  sealed under the passphrase set during setup.

## Why I built it

Neutrino started as a tool for my own workstation, laptop, and small machines
at home. I use it for my development environment.

<table>
<tr valign="top">
<td width="50%" align="center"><img src="images/web/panel_0.webp" width="220" alt="The Neutrino mascot facing a network barrier" /><p><b>Reaching the tools was the first problem.</b></p></td>
<td width="50%" align="center"><img src="images/web/panel_5.webp" width="220" alt="The mascot using a laptop with no connection to its home network" /><p><b>I go travelling. The workstation does not.</b></p></td>
</tr>
<tr valign="top">
<td align="center"><img src="images/web/panel_4.webp" width="220" alt="The mascot surrounded by computers and tangled cables" /><p><b>No machine of mine is difficult. All of them together are.</b></p></td>
<td align="center"><img src="images/web/panel_2.webp" width="220" alt="The mascot trying to organize a growing collection of hard drives" /><p><b>Data grows quietly.</b></p></td>
</tr>
<tr valign="top">
<td align="center"><img src="images/web/panel_3.webp" width="220" alt="Git, SSH, file and container service icons surrounding the mascot" /><p><b>Everything worked. Each thing lived somewhere else.</b></p></td>
<td align="center"><img src="images/web/panel_1.webp" width="220" alt="The mascot between two separate AI API endpoints" /><p><b>I was tired of copying the same keys around.</b></p></td>
</tr>
</table>

<details>
<summary><b>Architecture</b></summary>

<img src="images/web/architecture.svg" width="100%" alt="A remote machine reaches the hub over the overlay; the hub drives agents, AI, storage and services" />

**Design**

- **Single source of truth**: `config/`; every change is render, validate, apply; the panel and the CLI share the path; no migrations.
- **Hub hosts nothing**: Samba, Gitea, Podman, ZFS and RustDesk run under the agent on the machine that owns the disk or the GPU.
- **One channel**: the agent opens one WebSocket to the hub over TLS pinned by the enrollment link; the hub never dials; SSH only installs.
- **Desired state**: one document per device composed from `config/`, diffed and applied on connect; an offline device is refused, not queued.
- **Published services**: module entries plus hand-declared entries, pushed to every client.
- **One overlay**: none, NetBird or EasyTier; one row in `config/router/network.json`, which the firewall reads too.
- **Privilege**: hub and agent root, client never; the client's one escalation is a polkit mount helper.
- **One version**: three packages; a mismatch is asked to upgrade.

**Components**

- **Hub**: router (xray, nftables, dnsmasq; server, side gateway, router) · AI gateway (CLIProxyAPI, per-client keys, metering) · overlay (NetBird client, EasyTier engine) · panel (FastAPI, React, `/ws/events`) · vault.
- **Agent**: samba · gitea · podman · zfs · rustdesk host · terminal and file streams.
- **Client**: tray and window · port forwarder · mount helper · cc-switch · RustDesk viewer.

</details>

<details>
<summary><b>Development</b></summary>

**Requirements**: Python 3.12+, Node 24+, black, pytest.

```bash
pip install -e "hub[dev]" && pip install -e agent && pip install -e client
black --check hub agent client
cd hub && pytest -q
cd hub/frontend && npm run build
nhub apply --dry-run
```

**Tree**: `hub/` the hub package and the panel · `agent/` the device agent ·
`client/` the tray and window · `config/` the source of truth at runtime ·
`docs/` the documentation site · `packaging/` the VM integration rig.
Contributing standard: [AGENTS.md](AGENTS.md).

</details>

## Acknowledgements

Neutrino configures and carries work by others:
[Xray-core](https://github.com/XTLS/Xray-core),
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI),
[cpa-usage-keeper](https://github.com/Willxup/cpa-usage-keeper),
[NetBird](https://netbird.io), [EasyTier](https://github.com/EasyTier/EasyTier),
[cc-switch](https://github.com/SaladDay/cc-switch-cli),
[RustDesk](https://rustdesk.com), [Gitea](https://about.gitea.com),
[Samba](https://www.samba.org), [Podman](https://podman.io),
[OpenZFS](https://openzfs.org),
[dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html),
[hostapd](https://w1.fi/hostapd/) and [v2fly geodata](https://github.com/v2fly).
Claude Code and ChatGPT assisted with implementation, debugging, design and
documentation; the author reviews every release.

## License

[MIT](LICENSE).

<div align="center">

<img src="images/web/outro.webp" width="100%" alt="The Neutrino mascot at rest" />

# Let creation be fun again.

Spend less time maintaining the environment.<br/>
Spend more of it on whatever made you build one in the first place.

</div>
