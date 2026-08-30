<div align="center">

![Neutrino](images/web/banner.webp)

**A small self-hosted hub for your personal developer environment.**

Leave one always-on Debian or Ubuntu machine at home.
Let it hold your network, your machines, your AI configuration, your storage and your services.
Then reach all of it from wherever you are.

</div>

---

# What is stopping you?

<table>
<tr>
<td width="33%" align="center"><img src="images/web/panel_0.webp" width="260" /></td>
<td width="33%" align="center"><img src="images/web/panel_1.webp" width="260" /></td>
<td width="33%" align="center"><img src="images/web/panel_2.webp" width="260" /></td>
</tr>
<tr valign="top">
<td><b>A wall — or just another "Access Denied"?</b><br/><br/>A repository will not clone. A package will not download. An AI provider refuses the connection. You only wanted to get some work done; reaching the tools became the first problem.</td>
<td><b>Do you need another token — or one place to keep them?</b><br/><br/>Anthropic, OpenAI, Hugging Face, GitHub, whatever came out last month. Why does every new machine need another copy of the same credentials, and another afternoon configuring the same tools?</td>
<td><b>Do you need more disks — or somewhere that makes sense of the ones you have?</b><br/><br/>Data grows quietly. Eventually, remembering where everything lives becomes a job of its own.</td>
</tr>
<tr>
<td width="33%" align="center"><img src="images/web/panel_3.webp" width="260" /></td>
<td width="33%" align="center"><img src="images/web/panel_4.webp" width="260" /></td>
<td width="33%" align="center"><img src="images/web/panel_5.webp" width="260" /></td>
</tr>
<tr valign="top">
<td><b>Do you need more services — or fewer places to look for them?</b><br/><br/>Gitea, containers, files, SSH, a model endpoint. Everything works. Each one just happens to live behind a different address, port, login and dashboard.</td>
<td><b>Too many machines — or too many machines to babysit separately?</b><br/><br/>A workstation, a Pi, an old server, a GPU box. None of them is difficult. Together they somehow become annoying.</td>
<td><b>Why does everything work perfectly — until you leave home?</b><br/><br/>Your machines, files and services are still there. Why should your environment fall apart because you moved somewhere else?</td>
</tr>
</table>

---

# Install Neutrino and pierce barriers

**Reclaim your personal digital realm** — your machines, AI, files, services
and access, connected as one environment you control.

**1. Install the Hub** on your always-on machine.

```bash
sudo apt install ./neutrino-hub_<version>_amd64.deb
sudo nhub install
```

**2. Open the panel** at `http://<hub-address>` and set your password.

**3. Add what you need** — proxy nodes, NetBird, storage, services.

**4. Install the Agent** on a computer you want to connect.

```bash
sudo apt install ./neutrino-agent_<version>_all.deb
sudo nagent connect <enrollment link from the panel>
```

**5. Pick what that machine should have**, and let it set itself up.

Windows and macOS installers are published with each release. Full
documentation is in [`docs/`](docs/).

---

# What does it actually do?

<img src="images/web/architecture.svg" width="100%" alt="Outside reaches one Neutrino Hub over NetBird; the hub fronts AI, storage, devices and services" />

## Connect

> Why should every device solve networking on its own?

Routing, transparent proxying, DNS without leaks, LAN topology, NetBird for
getting back in from outside. Configure the path once on the Hub, and let the
machines behind it use it.

<!-- screenshot: Network / Proxy / NetBird -->

## Manage

> Why remember how to reach every machine?

LAN discovery, stored SSH credentials, a terminal in the browser, file
transfer, Wake-on-LAN, reboot and shutdown, remote desktop deployment, and
live CPU, memory, disk, GPU and process readings from every device running the
Agent.

<!-- screenshot: Devices -->

## Configure

> Why raise every new development machine from scratch?

```text
Give the Hub SSH access
          ↓
Choose what this machine needs
          ↓
Tools · Claude Code / Codex · proxy · AI endpoint · shares
          ↓
Ready
```

Turn a fresh machine into *your* development machine in one pass, instead of
repeating an afternoon of setup you have already done three times.

<!-- screenshot: Device drawer, module list -->

## Centralize

> Why should credentials live on every laptop?

Providers and API keys are kept on the Hub. The Hub runs an AI gateway, and
the Agent points each machine's Claude Code, Codex or Gemini CLI at it through
cc-switch. Change a key once, on the Hub, instead of repairing every machine.

Activating a tool keeps a copy of that machine's existing configuration, and
deactivating restores it exactly — permission rules, model choice and all.

<!-- screenshot: AI / Credentials -->

## Store

> Why should storage become another separate admin job?

ZFS pools and datasets, disk health, guided replacement, Samba shares.
Storage is optional: Neutrino can behave like a lightweight NAS when you need
one, and does not ask you to turn it into one.

<!-- screenshot: Storage -->

## Serve

> Why should every small service become another URL to remember?

Gitea, containers through Podman, and whatever else you run — reachable inside
your own LAN and overlay, without putting any of it on the public Internet.

<!-- screenshot: Services / Gitea / Containers -->

---

# Compatibility

| | Runs on | Carries |
| --- | --- | --- |
| **Hub** | Debian family — x86-64, ARM64, ARM | Its own Python environment; your system packages are untouched |
| **Agent** | Linux, Windows, macOS | Nothing. Pure standard library, and one 63 KB package covers every Linux architecture |

There is only one Hub. You do not need a controller on every machine.

---

# Status, roadmap and discussion

<!-- Links to add: roadmap board, issue tracker, discussions, chat. -->

| | |
| --- | --- |
| **Roadmap** | *(board link)* |
| **Issues** | *(tracker link)* |
| **Discussion** | *(link)* |

Tested on Ubuntu, Debian and ARM64 Linux, with agents on Linux, Windows and
macOS. If something breaks on your weird little server, open an issue — weird
little servers are very welcome here.

---

# License

Neutrino is released under the [MIT License](LICENSE). Use it, change it,
ship it — commercially or not — as long as the copyright notice travels
with it.

---

# Acknowledgements

Neutrino was built with extensive help from modern AI development tools,
especially Claude Code and ChatGPT, for implementation, debugging, design
discussion and documentation. Released code and design decisions are reviewed
and maintained by the project author.

---

<div align="center">

![](images/web/outro.webp)

# Let creation be fun again.

Spend less time maintaining the environment.
Spend more of it on whatever made you build one in the first place.

</div>
