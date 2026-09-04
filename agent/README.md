# neutrino_agent

The device agent for [neutrino](https://github.com/iffiX/neutrino).

Installed on a managed machine, it keeps that machine converged on what the
hub says should be true: it reports health and human accounts every few
seconds, reconciles the hub-controlled functions (a remote desktop, the SSH
server), runs the small set of commands the hub sends back, and updates
itself when the hub runs a later release.

It is standard library only and runs on Python 3.9 or newer, so it installs
on a stock Raspberry Pi or a minimal Ubuntu with nothing but `python3`
present.

## Installing

Normally you do not run this by hand: the hub's **Devices** page installs the
agent over SSH, or hands out an enrollment link for machines the hub cannot
reach first. On such a machine, install the native package and paste the link:

```bash
sudo apt install ./neutrino-agent_<version>_all.deb
sudo nagent connect neutrino://enroll/...
```

The package enables `neutrino_agent.service`, whose local page on
`http://127.0.0.1:8765` accepts the same link from a browser.

## Building the packages

```bash
python3 packaging/build_deb.py --output-dir dist/    # Debian family
python3 packaging/build_rpm.py --output-dir dist/    # RHEL family
python3 packaging/build_exe.py --output-dir dist/    # Windows installer
```

The hub's own package build bakes these in, so the hub and the agent it hands
out cannot drift.

## Checking an install

```bash
nagent status                      # what it is bound to, and whether the hub answers
journalctl -u neutrino_agent -f    # follow the running agent
```

## How it works

The agent polls; the hub never connects inbound. Every few seconds it posts
its heartbeat to `/api/agent/heartbeat` over a fingerprint-pinned TLS
channel, and the reply carries the desired state, the catalog, and any queued
commands. Because nothing has to reach *in*, a device behind NAT, on Wi-Fi,
or asleep needs no special setup, and a hub reboot is invisible.

The tree, one seam and three layers on top of it:

| Where | Job |
| --- | --- |
| `neutrino_agent/platforms/` | One class per platform behind one contract: accounts, account file work, step-down, power, metrics, packages, the SSH server |
| `neutrino_agent/functions/` | The reconcile engine and one reconciler per function kind |
| `neutrino_agent/services/` | What the machine's people do with what the hub publishes; the AI switcher's store lives here |
| `neutrino_agent/cli/` | The `nagent` subcommands |
| `neutrino_agent/agent.py` | The loop that joins them |
| `neutrino_agent/http_channel.py` | Posts to the hub and parses replies, pinned by certificate fingerprint |

The agent runs as root, so the actions it will perform are a closed list in
`neutrino_agent/ops.py`. There is deliberately no generic command runner.

## Working on this repo

Read [`AGENTS.md`](../AGENTS.md) first — it indexes the standard and says
which document settles what. [`docs/standard/`](../docs/standard/README.md)
holds the detail.
