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
| `test_mode_matrix.py` | Every mode, every ordered switch between them, the one-arm and multi-uplink shapes, and the proxy's behaviour in each — the contract network.md states. |
| `test_reinstall.py` | That installing the same version over a working box keeps every configuration file and restarts what runs the new code. |
| `test_reset_hands_back.py` | That `nhub reset all` gave the network back. |
| `run_on_box.sh` | The single-mode lifecycle, from an uninstalled machine and back to one. |
| `run_mode_matrix.sh` | The matrix lifecycle: install, server, the whole walk, reset. |
| `setup_vms.sh` | The mini network the matrix wants: a hub with three ports and a client on the served wire, on a distro and version named to pin behaviour. |

`panel_client.py` is the signed-in caller; `machine_state.py` reads the facts
about the box that no API can answer; `vm_exec.py` drives a lab VM through the
QEMU guest agent, which survives everything the tests do to its network.

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
| `--package` | `NEUTRINO_PACKAGE` | The package file, for the checks that install it a second time. |

Without a password the suite skips rather than fails, so a `pytest` from the
repository root walks past it instead of taking a workstation's network apart.

## The mini network

The matrix wants a machine with three ports and a neighbour to serve, and
`setup_vms.sh` builds exactly that on a libvirt host:

```bash
./setup_vms.sh debian 12          # or: ubuntu 24.04, alma 9, arch rolling …
python3 vm_exec.py nmxhub 'mkdir -p /opt/integration'
for f in *.py *.sh pytest.ini; do python3 vm_exec.py nmxhub push "$PWD/$f" "/opt/integration/$f"; done
python3 vm_exec.py nmxhub push neutrino-hub_0.1.0_amd64.deb /tmp/hub.deb
python3 vm_exec.py nmxhub 'bash /opt/integration/run_mode_matrix.sh /tmp/hub.deb --client'
```

The distro and version name the exact cloud image, so a behaviour seen on
`debian 12` is pinned to that release rather than to whatever the lab had
lying around. `--client` turns the client VM's lease from a skipped check
into an assertion. The matrix also runs on any lesser machine — the checks
that need a port the box does not have skip and say so.

The file order is the run order. `test_panel_api_network.py` and
`test_mode_matrix.py` each walk a box from one shape to the next, and each
check starts from where the last left it.
