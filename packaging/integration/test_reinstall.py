"""What reinstalling the same version over a working box leaves behind.

An upgrade replaces the code under a machine somebody is using, and the two
things it must not get wrong are the configuration and the services. The
configuration is the whole of what that box is — a reinstall that rewrites one
file has thrown away node credentials, device keys, or the mode itself. The
services are what runs the new code: a package that unpacks it and restarts
nothing leaves the old process serving the new frontend, which is a panel
asking its own API for fields that version does not send.

Reinstalling the *same* version is the honest way to test both. It runs every
maintainer script an upgrade runs, and it can be done with the package already
to hand rather than needing two releases to exist.

Run with `--package`, on a box that is already set up; the runner does it as
its own phase.
"""

import pytest

import machine_state

# Every unit that runs the hub's own Python, and therefore has to be running
# the new copy of it once the package is replaced. cliproxyapi and dnsmasq are
# somebody else's binary reading a file we render, so a restart of those is
# `nhub apply`'s business rather than this check's.
HUB_UNITS = ("neutrino_hub_web",)
# What must be up afterwards, whoever restarted it.
LIVE_UNITS = (
    "neutrino_hub_web",
    "neutrino_hub_xray",
    "neutrino_hub_dnsmasq",
)


@pytest.fixture(scope="module")
def reinstalled(package, panel):
    """The box, with its own version installed over it a second time.

    Args:
        package: The package file to reinstall.
        panel: A signed-in client, so the phase fails early and clearly if the
            box was not working before the reinstall.

    Returns:
        What was true before, so the checks can compare against it.
    """
    assert panel.status("GET", "/network") == 200
    before = {
        "config": machine_state.config_digests(),
        "started": {unit: machine_state.started_at(unit) for unit in HUB_UNITS},
    }
    machine_state.reinstall(package)
    return before


def test_the_configuration_is_untouched(reinstalled):
    """Every file byte for byte. `config/` is the whole of what this box is,
    and a package that rewrites one of them has thrown away a node's password,
    a device key, or the mode itself."""
    assert machine_state.config_digests() == reinstalled["config"]


def test_the_panel_is_running_the_code_that_was_just_installed(reinstalled):
    """It serves its own frontend, so nothing else restarts it: left alone it
    goes on running the old Python behind the new page, and the strip asks for
    fields the old API does not send."""
    for unit, was in reinstalled["started"].items():
        assert machine_state.started_at(unit) != was, f"{unit} was not restarted"


def test_everything_is_up_again(reinstalled):
    for unit in LIVE_UNITS:
        assert machine_state.is_active(unit), f"{unit} is not running"


def test_the_panel_answers_again(reinstalled, panel, request):
    """Signing in again, because the restart dropped the session: they live in
    the panel's memory, on purpose. What matters is that the box is usable
    from a browser the moment the package lands."""
    panel.sign_in(request.config.getoption("--password"))

    assert panel.status("GET", "/network") == 200
