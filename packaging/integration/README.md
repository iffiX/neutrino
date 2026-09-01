# Integration checks

Checks that need a machine with the hub installed and running on it. Nothing
here is in `hub/tests`, and nothing here runs in CI: every one of them
reconfigures a box's network, installs packages, or both.

## What is here

| File | What it checks |
| --- | --- |
| `test_panel_api_network.py` | Every operation the Network page offers: exposure, the three modes, one interface at a time, VLANs on a trunk, the panel's own port. |
| `test_panel_api_proxy.py` | The exit-node list, the SOCKS listeners, the direct lists and the resolvers. |
| `test_panel_api_services.py` | What the Services page is drawn from, and every action it refuses. |
| `test_panel_api_devices.py` | The device register: adding, renaming, forgetting, and fifty at once. |
| `test_install_footprint.py` | That a server or side_gateway install left the machine addressing itself. |
| `test_reset_hands_back.py` | That `nhub reset all` gave the network back. |
| `run_on_box.sh` | All of the above, from an uninstalled machine and back to one. |

`panel_client.py` is the signed-in caller; `machine_state.py` reads the facts
about the box that no API can answer.

## Running them

Against a box that is already set up, from the box itself:

```bash
cd packaging/integration
NEUTRINO_PANEL_PASSWORD=... python3 -m pytest test_panel_api_network.py -q
```

The whole lifecycle, from a machine with no hub on it, as root. It installs
the distribution's pytest if the box has none:

```bash
./run_on_box.sh /path/to/neutrino-hub_0.1.0_amd64.deb side_gateway
```

Options, each also readable from the environment:

| Option | Environment | What it says |
| --- | --- | --- |
| `--panel` | `NEUTRINO_PANEL_URL` | Where the panel answers. Default `http://127.0.0.1:8080`. |
| `--password` | `NEUTRINO_PANEL_PASSWORD` | Its password. Without it every check skips. |
| `--before` | `NEUTRINO_BEFORE_STATE` | The machine's state from before the install, written by `machine_state.write_snapshot()`. |
| `--mode` | `NEUTRINO_SETUP_MODE` | Which mode the box was set up in. |

Without a password the suite skips rather than fails, so a `pytest` from the
repository root walks past it instead of taking a workstation's network apart.

## In a VM

The hypervisor half is not in this repository: which images exist and how a VM
is booted belongs to whoever runs the lab. Whatever starts the VM copies this
directory and the package in, and runs `run_on_box.sh` inside it — with a
libvirt lab, that is a `sync` and a `run`.

The file order is the run order. `test_panel_api_network.py` walks a box from
one shape to the next, and each check starts from where the last left it.
