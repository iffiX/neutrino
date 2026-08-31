"""Rendering the hub's units for the installation they are being written into.

A checkout runs the hub from the tree it sits in and its units say where that
is; a package carries the hub inside its own environment, where those same
lines would name a directory inside the environment. Getting this wrong gives
a unit that starts nothing, which is how a packaged box ends up with a panel
that never comes up.
"""

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
    assert units.SYSTEM_UNIT_TEMPLATES["xray.service"] == "xray.service"


def _true() -> bool:
    return True


def _false() -> bool:
    return False


def _fake_checkout():
    from pathlib import Path

    return Path("/repo")
