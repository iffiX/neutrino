"""Rendering the hub's units for the installation they are being written into.

A checkout runs the hub from the tree it sits in and its units say where that
is; a package carries the hub inside its own environment, where those same
lines would name a directory inside the environment. Getting this wrong gives
a unit that starts nothing, which is how a packaged box ends up with a panel
that never comes up.
"""

import re

import pytest

from neutrino_hub.system import units
from neutrino_hub.system.units import SystemdUnitInstaller

TEMPLATE = """[Unit]
Documentation=file://@REPO_ROOT@/docs/standard/misc/config.md

[Service]
WorkingDirectory=@REPO_ROOT@/hub
Environment=PYTHONPATH=@REPO_ROOT@/hub
ExecStart=@PYTHON@ -m neutrino_hub.cli.run
"""


@pytest.fixture
def installer():
    return SystemdUnitInstaller()


def test_a_checkout_unit_names_the_tree_it_runs_from(installer, monkeypatch):
    monkeypatch.setattr(units, "is_packaged", _false)
    monkeypatch.setattr(units, "checkout_root", _fake_checkout)

    rendered = installer.render(TEMPLATE, "/repo/.venv/bin/python")

    assert "WorkingDirectory=/repo/hub" in rendered
    assert "ExecStart=/repo/.venv/bin/python -m neutrino_hub.cli.run" in rendered
    assert "@REPO_ROOT@" not in rendered


def test_a_packaged_unit_drops_the_lines_that_would_name_its_own_environment(
    installer, monkeypatch
):
    monkeypatch.setattr(units, "is_packaged", _true)

    rendered = installer.render(TEMPLATE, "/opt/neutrino/python/bin/python3")

    assert "WorkingDirectory" not in rendered
    assert "PYTHONPATH" not in rendered
    assert "@REPO_ROOT@" not in rendered
    assert "ExecStart=/opt/neutrino/python/bin/python3" in rendered
    assert rendered.endswith("\n")


def test_the_proxy_core_has_a_unit_of_its_own(installer):
    """It travels in the package, so no vendor script installs one to patch."""
    assert (
        units.SYSTEM_UNIT_TEMPLATES["neutrino_hub_xray.service"]
        == "neutrino_hub_xray.service"
    )


def test_the_lan_name_service_is_the_hubs_own_unit():
    """The distribution's is not handed the generated file the same way twice:
    Debian passes --conf-dir on the command line, Arch reads nothing from
    /etc/dnsmasq.d at all, and there the packaged unit started with defaults,
    took port 53 from systemd-resolved and left the box with no DNS."""
    from neutrino_hub.system.constants import SYSTEM_CORE_UNITS

    assert SYSTEM_CORE_UNITS["dnsmasq"] == "neutrino_hub_dnsmasq.service"
    assert "neutrino_hub_dnsmasq.service" in units.SYSTEM_UNIT_TEMPLATES.values()


def _true() -> bool:
    return True


def _false() -> bool:
    return False


def _fake_checkout():
    from pathlib import Path

    return Path("/repo")


def test_every_unit_the_hub_owns_is_named_for_the_package_that_owns_it():
    """One prefix, so `systemctl list-units neutrino_hub_*` is the whole hub."""
    for unit in units.SYSTEM_UNIT_TEMPLATES.values():
        assert unit.startswith("neutrino_hub_"), unit


def test_each_unit_starts_one_process_through_the_hub():
    """The unit names no path of its own; the hub knows where its files are."""
    from neutrino_hub.utils.constants import UTILS_DATA_DIR

    for template_name in (
        "neutrino_hub_web.service",
        "neutrino_hub_xray.service",
        "neutrino_hub_cliproxyapi.service",
        "neutrino_hub_dnsmasq.service",
    ):
        text = (UTILS_DATA_DIR / "services" / template_name).read_text()
        started = [line for line in text.splitlines() if line.startswith("ExecStart=")]
        assert len(started) == 1, template_name
        assert "neutrino_hub.cli.entry run --only-" in started[0], template_name


def test_no_rendered_unit_keeps_a_placeholder():
    """A unit written with @PYTHON@ still in it fails at exec with that as
    the path, which is what happened to the AI gateway: its provisioner read
    the template and wrote it without going through this.

    A placeholder rather than any `@`: a templated unit names its siblings by
    instance, and `neutrino_hub_supplicant@%i.service` is an ordinary way to
    spell one."""
    from neutrino_hub.utils.constants import UTILS_DATA_DIR

    installer = SystemdUnitInstaller()
    for template in sorted((UTILS_DATA_DIR / "services").glob("*.service")):
        text = template.read_text(encoding="utf-8")
        for is_packaged_value in (True, False):
            units.is_packaged = lambda: is_packaged_value
            rendered = installer.render(text, "/opt/neutrino/python/bin/python3")
            left = re.findall(r"@[A-Z_]+@", rendered)
            assert not left, f"{template.name}, packaged={is_packaged_value}: {left}"


def test_the_units_the_panel_restarts_are_not_rate_limited():
    """systemd stops a unit after five starts in ten seconds and leaves it
    down until the window clears. The panel restarts these by design — every
    interface saved, every proxy applied — so a person editing two interfaces
    in a row lost DHCP and DNS on the LAN, and every apply after that answered
    with the limiter's own message.

    The directive belongs in [Unit]; systemd ignores it in [Service], which is
    what makes this worth pinning rather than trusting to review.
    """
    from neutrino_hub.utils.constants import UTILS_DATA_DIR

    for name in ("neutrino_hub_dnsmasq.service", "neutrino_hub_xray.service"):
        text = (UTILS_DATA_DIR / "services" / name).read_text(encoding="utf-8")
        unit_section = text.split("[Service]")[0]
        assert "StartLimitIntervalSec=0" in unit_section, name
