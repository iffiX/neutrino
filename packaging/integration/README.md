# Integration checks

Checks that need a machine with the hub installed and running on it. Nothing
here is in `hub/tests`, and nothing here runs in CI: every one of them
reconfigures a box's network, installs packages, or both.

## What is here

| File | What it checks |
| --- | --- |
| `test_panel_api_network.py` | Every operation the Network page offers: exposure, the three modes, one interface at a time, VLANs on a trunk, the panel's own port. |
| `test_panel_api_proxy.py` | The exit-node list, the SOCKS listeners, the direct lists and the resolvers. |
| `test_declared_services.py` | What the Services page is drawn from, and every action it refuses. |
| `test_panel_api_modules.py` | The Modules page for a device with no agent: the catalog, the states, and every refusal. |
| `test_install_a_module.py` | That a module actually installs on a managed machine through the panel — the one check here that runs a package manager; on the same machine, a saved configuration read back as written, its unit's journal, and the refusal a write with no body gets. |
| `test_panel_api_devices.py` | The device register: naming a scan row, renaming by id, forgetting, and fifty at once. |
| `test_install_footprint.py` | That a server or side_gateway install left the machine addressing itself. |
| `test_mode_matrix.py` | Every mode, every ordered switch between them, the one-arm and multi-uplink shapes, and the proxy's behaviour in each — the contract network.md states. |
| `test_reinstall.py` | That installing the same version over a working box keeps every configuration file and restarts what runs the new code. |
| `test_panel_update.py` | That the update unit the panel hands a package to installs it, holds its gate, records the result, and puts the previous package back when the gate cannot pass. |
| `test_agent_channel.py` | The channel end to end: the link's role and fingerprint, the join over pinned TLS, and a tampered link refused on the device. |
| `test_agent_removal.py` | That removing the agent's package from a managed machine takes a unit named as a module names its units, leaves one named as the hub names its own, keeps the file share serving its share, and that an install after it reports that share once. |
| `test_device_lifecycle.py` | Every transition of the binding: scan, name, install, self-update, the two protocol refusals, the hub forgetting, the link back, and leaving. |
| `test_enrollment_ticket.py` | That a client link outlives a panel restart: the ticket file holds its hash at mode 0600, and the link joins once over the pinned agent port and is refused `ticket_spent` the second time. Run as root. |
| `test_relay.py` | That the relay reads `connected` against a server the tester owns, a client link ends with the relay's address, and a client handed only that address joins through it and is told `reached_through: relay`. Needs `NEUTRINO_RELAY_HOST` and `NEUTRINO_RELAY_KEY_FILE`; `../lab/make_vps.sh` builds a server for it. |
| `test_reset_hands_back.py` | That `nhub reset all` gave the network back. |
| `connect_probe.py` | Not a test: run by hand on any machine that reaches a hub's agent port. It joins with a client link read from a file or stdin, opens one `connect` stream to an entry or the panel, sends one DNS query as a datagram when `--udp` names a UDP entry, prints one JSON line, and leaves. |
| `run_on_box.sh` | The single-mode lifecycle, from an uninstalled machine and back to one. |
| `run_mode_matrix.sh` | The matrix lifecycle: install, server, the whole walk, reset. |

`panel_client.py` is the signed-in caller; `machine_state.py` reads the facts
about the box that no API can answer. The VMs the suite runs on are built and
driven from `../lab/`.

## Running them

Against a box that is already set up, from the box itself:

```bash
cd packaging/integration
NEUTRINO_PANEL_PASSWORD=... python3 -m pytest test_panel_api_network.py -q
```

The whole lifecycle, from a machine with no hub on it, as root. It installs
the distribution's pytest if the box has none:

```bash
./run_on_box.sh /path/to/neutrino-hub_0.4.0_amd64.deb side_gateway
```

The package file keeps its release name, `neutrino-hub_<version>_<arch>.deb`
for a deb, because `nhub update --package` reads the version off the name and
rejects any other name with `package_name_mismatch`.

Options, each also readable from the environment:

| Option | Environment | What it says |
| --- | --- | --- |
| `--panel` | `NEUTRINO_PANEL_URL` | Where the panel answers. Default: loopback, by the scheme and port in the box's `web/settings.json`; an `https` panel is trusted by the box's own authority. |
| `--password` | `NEUTRINO_PANEL_PASSWORD` | Its password. Without it every check skips. |
| `--before` | `NEUTRINO_BEFORE_STATE` | The machine's state from before the install, written by `machine_state.write_snapshot()`. |
| `--mode` | `NEUTRINO_SETUP_MODE` | Which mode the box was set up in. |
| `--package` | `NEUTRINO_PACKAGE` | The package file, for the checks that install it a second time. |

Without a password the suite skips rather than fails, so a `pytest` from the
repository root walks past it instead of taking a workstation's network apart.

## The mini network

The matrix wants a machine with three ports and a neighbour to serve.
`../lab/setup_vms.sh` builds exactly that on a libvirt host, and
`../lab/run_lab.py` builds it, pushes this suite and a package into the hub,
and runs the matrix there:

```bash
export NEUTRINO_VM_LAB=/var/lib/neutrino_vm_lab
sg libvirt -c "python3 packaging/lab/run_lab.py neutrino-hub_0.5.0_amd64.deb"
sg libvirt -c "python3 packaging/lab/run_lab.py neutrino-hub_0.5.0_amd64.deb --distro ubuntu --version 22.04 --lifecycle"
```

`id_lab` is the key `setup_vms.sh` generated for the `lab` account on both
VMs, and `run_lab.py` copies it beside the suite; it is what the lifecycle
walks in `run_on_box.sh` reach the client with. They fail naming it when it
is not beside them: a walk that passed by skipping is a walk that tested
nothing.

The distro and version name the exact cloud image, so a behaviour seen on
`debian 12` is pinned to that release rather than to whatever the lab had
lying around. `--client` turns the client VM's lease from a skipped check
into an assertion. The matrix also runs on any lesser machine — the checks
that need a port the box does not have skip and say so.

The file order is the run order. `test_panel_api_network.py` and
`test_mode_matrix.py` each walk a box from one shape to the next, and each
check starts from where the last left it.
