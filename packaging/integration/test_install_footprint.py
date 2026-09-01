"""What a server or side_gateway install left of the machine it landed on.

Both of those modes promise that the machine goes on
addressing itself: its manager keeps running, its configuration files are not
edited, and its addresses are the ones it already had. That promise is about
files and units, not about anything the panel's API can be asked, which is why
these read the box directly.

They need the machine as it was: run `machine_state.write_snapshot()` before
the package is installed and pass the file with `--before`.
"""

from pathlib import Path

import pytest

import machine_state

MODES_ADDRESSING_NOTHING = ("server", "side_gateway")
CORE_UNITS = (
    "neutrino_hub_web",
    "neutrino_hub_router",
    "neutrino_hub_xray",
    "neutrino_hub_dnsmasq",
)


@pytest.fixture(scope="module", autouse=True)
def only_the_modes_that_address_nothing(mode):
    """Router mode is supposed to take the machine over, so it is not asked
    to have left it alone."""
    if mode not in MODES_ADDRESSING_NOTHING:
        pytest.skip(f"{mode} addresses the machine on purpose")


def test_the_machine_still_runs_its_own_manager(before):
    if not before["manager"]:
        pytest.skip("this machine arrived running no manager this knows about")

    assert machine_state.is_active(before["manager"])


def test_no_manager_of_this_machine_was_masked():
    """Masking is how router mode stops the manager it is replacing. These
    modes replace nothing, so they mask nothing."""
    masked = [
        unit for unit in machine_state.MACHINE_MANAGERS if machine_state.is_masked(unit)
    ]

    assert masked == []


def test_the_addresses_and_routes_are_the_ones_it_had(before):
    assert machine_state.addresses_and_routes() == before["addresses_and_routes"]


def test_the_network_configuration_files_are_untouched(before):
    """Every file's own digest, so a mirror file regenerating itself shows up
    as loudly as a deletion."""
    assert machine_state.config_trees() == before["config_trees"]


def test_resolv_conf_is_untouched(before):
    assert machine_state.resolv_conf() == before["resolv_conf"]


@pytest.mark.parametrize(
    "directory", ["/etc/NetworkManager/conf.d", "/etc/cloud/cloud.cfg.d"]
)
def test_nothing_of_ours_was_dropped_into_another_manager(directory):
    written = [path.name for path in Path(directory).glob("*neutrino*")]

    assert written == []


@pytest.mark.parametrize(
    "pattern", ["neutrino_hub_supplicant@*", "neutrino_hub_dhcpcd@*"]
)
def test_no_engine_of_ours_drives_this_machine(pattern):
    """A supplicant or a lease client of ours on one of its radios is exactly
    the takeover these modes promise not to do."""
    assert machine_state.units_matching(pattern) == []


def test_nothing_was_stood_down():
    """The note a mode that took the machine over leaves so a reset can hand
    it back. There is nothing to hand back."""
    assert not machine_state.MACHINE_STOOD_DOWN_PATH.exists()


@pytest.mark.parametrize("unit", CORE_UNITS)
def test_the_hub_is_doing_its_job_on_it(unit):
    assert machine_state.is_active(unit)


def test_the_interface_it_arrived_on_still_answers(before):
    """An install that firewalls the one interface a machine has is a machine
    nobody can reach."""
    assert machine_state.is_answering_on(before["interface"])


def test_a_server_leaves_forwarded_traffic_alone(mode):
    """It routes nothing, so it is not the firewall for whatever docker or
    libvirt forwards across it, and a drop policy there cuts them off in
    silence."""
    if mode != "server":
        pytest.skip("only a server forwards nothing")
    chain = machine_state.run(["nft", "list", "chain", "inet", "neutrino", "forward"])

    assert "policy accept" in chain
    assert "masquerade" not in machine_state.firewall_table()


def test_a_side_gateway_forwards_for_the_devices_that_name_it(mode):
    if mode != "side_gateway":
        pytest.skip("only a side gateway forwards")

    assert machine_state.run(["sysctl", "-n", "net.ipv4.ip_forward"]).strip() == "1"
    assert "masquerade" in machine_state.firewall_table()


def test_the_box_still_resolves():
    assert machine_state.run(["getent", "hosts", "github.com"]).strip() != ""


def test_the_panel_answers(panel):
    assert panel.status("GET", "/services") == 200
