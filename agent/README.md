# neutrino_agent

The device agent for [neutrino](https://github.com/iffiX/neutrino).

Installed on a managed machine, it keeps that machine converged on what the
hub says should be true: it reports health and human accounts every few
seconds, reconciles the hub-controlled functions (a remote desktop, the SSH
server), runs the small set of commands the hub sends back, and updates
itself when the hub runs a later release.

Its own code is standard library only. The package carries the interpreter
that runs it and the bindings its window draws through, so it installs on a
machine with no Python at all and touches none the machine already has. What a
Linux package still asks for is the C stack under WebKitGTK; Windows and macOS
ask for nothing.

One package per platform and machine: `amd64` and `arm64` on Linux, `x64` and
`arm64` on Windows, one universal build on macOS. 32-bit ARM is not published.

## Installing

Normally you do not run this by hand: the hub's **Devices** page installs the
agent over SSH, or hands out an enrollment link for machines the hub cannot
reach first. On such a machine, install the native package and paste the link:

```bash
sudo apt install ./neutrino-agent_<version>_amd64.deb
sudo nagent connect neutrino://enroll/...
```

The package enables `neutrino_agent.service`; `nagent gui` opens its window,
which accepts the same link.

## Building the packages

```bash
python3 packaging/build_deb.py --output-dir dist/ --architecture amd64
python3 packaging/build_rpm.py --output-dir dist/ --architecture x86_64
python3 packaging/build_msi.py --output-dir dist/ --architecture x64
python3 packaging/build_pkg.py --output-dir dist/
```

The two Linux builds compile the window's bindings, so each runs in a
container of the family and the machine it is for —
`packaging/build_release.py` drives that matrix. The `.msi` needs Windows and
WiX; the `.pkg` needs macOS.

The hub's own package build bakes the Linux pair in for its own machine, so
the hub and the agent it hands out cannot drift.

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
which document settles what. [`skills/core-code-author/`](../skills/core-code-author/SKILL.md)
holds the detail.
