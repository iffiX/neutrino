# Tests

```bash
pytest                     # everything that runs unprivileged
sudo pytest                # adds the checks that need root
```

## What is here

One directory per package, mirroring the source tree: `tests/modules/<name>/`,
`tests/system/`, `tests/web/`, `tests/cli/`.

| Path | Covers |
| --- | --- |
| `modules/router/test_interfaces.py` | Parsing `config/router/network.json`, including both older shapes of it |
| `modules/router/test_uplink_plan.py` | Which uplink carries traffic, and why |
| `modules/router/test_nft_renderer.py` | The firewall and TPROXY ruleset |
| `modules/router/test_dnsmasq_renderer.py` | DHCP and DNS for the served networks |
| `modules/router/test_hostapd_renderer.py` | The Wi-Fi access point's configuration |
| `web/test_network_api.py` | The Network tab's API, its validations, and the view |
| `cli/test_reset.py` | What `nhub reset all` destroys, and what it must not |
| `cli/test_password.py` | How the panel password is taken, and what is refused |
| `system/test_units.py` | Rendering a unit for a checkout and for a package |
| `system/test_packages.py` | What the package manager installs, in one list |
| `cli/test_wizard.py` | The answers document a first run takes, and the uplink default |
| `cli/test_setup_writes.py` | What the wizard's answers become in `config/` |
| `cli/test_run_dnsmasq.py` | What `run --only-dnsmasq` hands the binary |
| `cli/test_wizard_context.py` | One set of facts for both ways of answering |
| `cli/test_wizard_handover.py` | Waiting for a browser, and giving up on one |
| `web/test_setup_app.py` | The wizard a browser answers, and its token |
| `cli/test_browser_server.py` | Getting the wizard a port, and never needing one |
| `modules/router/test_modes.py` | The four shapes a gateway is set up as |
| `modules/router/test_lan_resolver.py` | What a served interface leaves the box resolving with |
| `modules/router/test_carried_addresses.py` | Letting go of the address a handover carried, and never before a lease arrives |
| `modules/router/test_credentials.py` | Reading the Wi-Fi keys a machine already held, in four other managers' formats |
| `modules/router/test_supplicant_renderer.py` | What a radio is told to join, and what is never written into the file |
| `modules/router/test_link_kinds.py` | Which interfaces get a role, and which are docker's, the overlay's or a modem |
| `modules/router/test_guest_modes.py` | The modes that address nothing, and that applying one calls nothing |

## Two rules

**Nothing touches the real appliance.** No test reads `config/`, reconfigures an
interface, or restarts a service. The pure layers are exercised directly, and
the layers that talk to the system get a stub that answers from a dictionary —
`StubLinkStatus` and `FakeRuntime` in `conftest.py`. This is not fastidiousness:
these tests are meant to be run *on the gateway*, and a suite that could take
the box off the network is one nobody would dare run there.

**Anything that shells out declares it.** Rendered artifacts are checked against
the real validators wherever that works unprivileged — `dnsmasq --test` does —
and marked `needs_root` where it does not, because `nft -c` opens a netlink
socket. Those skip with a reason instead of failing, so a plain `pytest` is
still green and still meaningful.

## Adding to it

Name the test after the situation, not the function: `test_two_ports_onto_one_upstream_are_one_line`
says what breaks if it regresses, `test_group_by_line` does not. Where a case
exists because something once went wrong on this box, say so in the docstring —
several of these encode failures that took the gateway off the network, and the
reason is the part worth keeping.

Assert against `without_comments(...)` when checking that a directive is
*absent*. The renderers explain themselves in the files they produce, and those
explanations mention the very things a test wants to prove are not there.
