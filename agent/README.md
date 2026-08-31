# neutrino_agent

The device agent for [neutrino](https://github.com/iffiX/neutrino).

Installed on a LAN machine, it reports that machine's health to the gateway
panel every few seconds and runs the small set of commands the gateway sends
back — reboot, shut down, install a remote-desktop client, update itself. That
is what turns a device the gateway merely *scanned* into one it can *manage*.

It is standard library only and runs on Python 3.9 or newer, so it installs on a
stock Raspberry Pi or a minimal Ubuntu with nothing but `python3` present.

## Installing

Normally you do not run this by hand: open the gateway panel's **Devices** tab,
give a device its SSH credentials, and press **Install neutrino_agent**. The
gateway uploads the package and runs the installer for you.

To install manually:

```bash
sudo ./install.sh --gateway-url http://192.168.100.1:8080 --token <token>
```

The token is issued by the gateway, one per device. The installer copies the
agent to `/opt/neutrino_agent`, writes `/etc/neutrino_agent/agent.json`,
verifies it can reach the gateway, then enables and starts
`neutrino_agent.service`.

## Building the package

```bash
pip install -e .
python3 -m neutrino_agent.build_package \
    --output-dir ../config/devices/packages
```

This writes `neutrino_agent-<version>.tar.gz` and
`neutrino_agent-latest.tar.gz`. The gateway serves the latter to devices.

## Checking an install

```bash
nagent status                      # what it is bound to, and whether the hub answers
journalctl -u neutrino_agent -f    # follow the running agent
```

## How it works

The agent polls; the gateway never connects inbound. Every few seconds it posts
its metrics to `/api/agent/heartbeat`, and the reply carries any queued
commands, which it runs and reports back. Because nothing has to reach *in*, a
device behind NAT, on Wi-Fi, or asleep needs no special setup, and a gateway
reboot is invisible.

Four modules, each with one job:

| Module | Job |
| --- | --- |
| `neutrino_agent/metrics.py` | Reads CPU, memory, disk, and temperature from `/proc` and `/sys` |
| `neutrino_agent/http_channel.py` | Posts to the gateway and parses replies |
| `neutrino_agent/ops.py` | Runs the allow-listed actions on this host |
| `neutrino_agent/agent.py` | The loop that joins the three |

The agent runs as root, so the actions it will perform are a closed list in
`neutrino_agent/ops.py`. There is deliberately no generic command runner.

## Working on this repo

Read [`AGENTS.md`](../AGENTS.md) first — it indexes the standard and says
which document settles what. [`docs/standard/`](../docs/standard/README.md)
holds the detail.
