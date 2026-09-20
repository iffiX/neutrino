"""The hub installing its own package through the update unit.

`nhub update --package` stages a package file the way the panel stages a
release, and hands it to `neutrino_hub_update`; what these check is that the
unit installs, holds its gate, and writes the record the panel reads, and
that a gate which cannot pass puts the previous package back. Installing the
same version is what makes the first possible with one package to hand; a
plan whose target version cannot come true is what makes the second.

Run with `--package`, on a box that is already set up; the runner does it as
its own phase, after the reinstall.
"""

import json
import subprocess
import time

import pytest

import machine_state

UPDATE_DIR = "/var/lib/neutrino/hub_update"
STATE_FILE = f"{UPDATE_DIR}/state.json"
HUB_PYTHON = "/opt/neutrino/python/bin/python3"
# An install, a gate of three minutes, and the same again for the rollback.
UPDATE_SETTLE_S = 10 * 60
LIVE_UNITS = ("neutrino_hub_web", "neutrino_hub_xray", "neutrino_hub_dnsmasq")


def read_state() -> dict:
    with open(STATE_FILE, encoding="utf-8") as stream:
        return json.load(stream)


def wait_settled() -> dict:
    """The record once the unit has written a final stage."""
    deadline = time.monotonic() + UPDATE_SETTLE_S
    while time.monotonic() < deadline:
        try:
            record = read_state()
        except (OSError, ValueError):
            record = {}
        if record.get("stage") in ("installed", "rolled_back", "failed"):
            return record
        time.sleep(2.0)
    raise AssertionError(f"the update never settled: {read_state()}")


@pytest.fixture(scope="module")
def updated(package, panel):
    """The box, with its own version installed over it by the update unit."""
    assert panel.status("GET", "/hub/network") == 200
    before = {
        "config": machine_state.config_digests(),
        "started": machine_state.started_at("neutrino_hub_web"),
    }
    result = subprocess.run(
        ["nhub", "update", "--yes", "--package", package],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (result.stderr or result.stdout).strip()
    before["record"] = wait_settled()
    return before


def test_the_unit_installed_and_the_gate_passed(updated):
    record = updated["record"]
    assert record["stage"] == "installed", record
    assert record["reason"] == ""
    assert record["from_version"] == record["to_version"]
    assert record["finished_at"].endswith("Z")


def test_the_panel_was_restarted_by_the_install(updated):
    assert machine_state.started_at("neutrino_hub_web") != updated["started"]


def test_the_configuration_is_untouched(updated):
    assert machine_state.config_digests() == updated["config"]


def test_everything_is_up_again(updated):
    for unit in LIVE_UNITS:
        assert machine_state.is_active(unit), f"{unit} is not running"


def test_the_panel_reports_the_update(updated, panel, request):
    panel.sign_in(request.config.getoption("--password"))

    view = panel.read("/hub/setting/release")

    assert view["is_packaged"] is True
    assert view["update"]["stage"] == "installed"
    assert view["task_id"] is None


def test_the_package_stays_as_the_next_rollback(updated, package):
    import os

    assert os.path.isfile(f"{UPDATE_DIR}/{os.path.basename(package)}")


@pytest.fixture(scope="module")
def rolled_back(updated, package):
    """The box, after a plan whose target version can never come true.

    The same package is installed and gated on version 9.9.9, which no
    package prints, so the gate fails and the unit installs the rollback,
    which is that same package gated on the version it does print.
    """
    import os

    staged = f"{UPDATE_DIR}/{os.path.basename(package)}"
    port = int(machine_state.run([HUB_PYTHON, "-c", machine_state.PANEL_PORT_SCRIPT]))
    snippet = f"""
from pathlib import Path
from neutrino_hub import HUB_VERSION
from neutrino_hub.modules.hub_update.installer import HubUpdateInstaller, HubUpdatePlan
from neutrino_hub.modules.hub_update.release import HubReleaseChecker
from neutrino_hub.modules.hub_update.state import HubUpdateStateFile
from neutrino_hub.system.machine import distribution_family
installer = HubUpdateInstaller(checker=HubReleaseChecker(), state=HubUpdateStateFile())
plan = HubUpdatePlan(
    from_version=HUB_VERSION, to_version="9.9.9", package=Path({staged!r}),
    rollback=Path({staged!r}), family=distribution_family(), port={port},
    units=("neutrino_hub_web",), started_at="2026-01-01T00:00:00Z",
)
installer.launch(plan)
"""
    result = subprocess.run([HUB_PYTHON, "-c", snippet], capture_output=True, text=True)
    assert result.returncode == 0, (result.stderr or result.stdout).strip()
    return wait_settled()


def test_a_gate_that_cannot_pass_puts_the_previous_package_back(rolled_back):
    assert rolled_back["stage"] == "rolled_back", rolled_back
    assert rolled_back["reason"] == "health_gate_failed"
    assert "version=" in rolled_back["output"]


def test_the_box_answers_after_the_rollback(rolled_back, panel, request):
    for unit in LIVE_UNITS:
        assert machine_state.is_active(unit), f"{unit} is not running"
    panel.sign_in(request.config.getoption("--password"))

    view = panel.read("/hub/setting/release")

    assert view["update"]["stage"] == "rolled_back"
