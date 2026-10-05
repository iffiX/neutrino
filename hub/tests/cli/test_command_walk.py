"""The commands a person runs, walked against this tree's own files.

`nhub setup`'s units and config steps, `nhub stop`, `nhub start` and `nhub
reset all` run here with systemd answering from a table and the roots under
`tmp_path`, but with the real service controller and the tree's own
`data/`. A name a command acts on that the tree carries no unit, template or
example for fails here, in either edition's tree: a full tree and the
mainland tree each walk the same steps against what they hold.
"""

import contextlib
from types import SimpleNamespace

import pytest

from neutrino_hub.cli import reset, setup, start, stop
from neutrino_hub.system import systemd_ctl, units
from neutrino_hub.system.constants import (
    SYSTEM_MANAGED_UNITS,
    SYSTEM_SUPERVISED_CORE,
    SYSTEM_SUPERVISED_NAMES,
)
from neutrino_hub.utils.constants import UTILS_DATA_DIR, UTILS_EXAMPLES_DIR

SERVICES_DIR = UTILS_DATA_DIR / "services"


class Asked(list):
    """What systemctl was asked, with the state it answers from."""

    state: dict = {}


class Reporter:
    """What setup's steps report to, kept quiet."""

    def note(self, line: str) -> None:
        del line


@pytest.fixture
def systemctl(monkeypatch):
    """A systemd every unit is installed and enabled in, running as told."""
    asked = Asked()
    state = {"active": "active"}

    def run(command, **keywords):
        asked.append(list(command))
        return SimpleNamespace(
            stdout=(
                "LoadState=loaded\n"
                f"ActiveState={state['active']}\n"
                "UnitFileState=enabled\n"
            ),
            stderr="",
            returncode=0,
            is_success=True,
        )

    monkeypatch.setattr(systemd_ctl, "run", run)
    monkeypatch.setattr("sys.platform", "linux")
    asked.state = state
    return asked


def acted_units(asked: list, verb: str) -> list:
    return [command[2] for command in asked if command[:2] == ["systemctl", verb]]


def test_every_unit_setup_installs_has_its_template_in_the_tree(
    monkeypatch, tmp_path, systemctl
):
    monkeypatch.setattr(units, "SYSTEM_SYSTEMD_DIR", tmp_path)
    monkeypatch.setattr(setup, "_mask_distribution_unit", lambda *args: False)

    setup._step_systemd_units(Reporter())

    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        units.SYSTEM_UNIT_TEMPLATES.values()
    )


def test_every_config_file_setup_copies_has_its_example_in_the_tree(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(setup, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup, "ensure_hub_identity", lambda: False)

    setup._step_config_files(Reporter())

    for relative in setup.CONFIG_FILES:
        assert (tmp_path / relative).is_file(), relative
        assert (
            UTILS_EXAMPLES_DIR / relative.replace(".json", ".example.json")
        ).is_file()


def test_every_service_setup_names_is_one_the_controllers_know():
    for name in setup.SETUP_CORE_SERVICES + setup.SETUP_SERVICES_BEFORE_PANEL:
        assert name in SYSTEM_MANAGED_UNITS, name
    for name in SYSTEM_SUPERVISED_CORE:
        assert name in SYSTEM_SUPERVISED_NAMES, name


def test_every_managed_core_unit_has_its_template_in_the_tree():
    templates = {path.name for path in SERVICES_DIR.iterdir()}
    for name in (*stop.STOP_ORDER, *setup.SETUP_CORE_SERVICES):
        assert SYSTEM_MANAGED_UNITS[name] in templates, name


def test_stop_stops_every_unit_it_names(monkeypatch, systemctl):
    monkeypatch.setattr(stop, "_configured_engines", lambda: [])

    assert stop.stop_everything() == 0
    assert acted_units(systemctl, "stop") == [
        SYSTEM_MANAGED_UNITS[name] for name in stop.STOP_ORDER
    ]


def test_every_stop_and_start_flag_names_a_unit_it_can_act_on(monkeypatch, systemctl):
    for name in stop.STOP_ORDER:
        assert stop.stop([name]) == 0
        assert start.start([name], is_enabled_only=False) == 0


def test_start_starts_every_enabled_unit(systemctl):
    systemctl.state["active"] = "inactive"

    assert start.start(list(start.START_ORDER), is_enabled_only=True) == 0
    assert acted_units(systemctl, "start") == [
        SYSTEM_MANAGED_UNITS[name] for name in start.START_ORDER
    ]


def test_reset_all_stops_everything_it_names(monkeypatch, systemctl):
    """A reset that crashed after it had replaced config/ left a box half
    reset; every stop it runs reaches a unit the tree has."""
    monkeypatch.setattr(stop, "_configured_engines", lambda: [])
    monkeypatch.setattr(reset, "router_lock", contextlib.nullcontext)
    monkeypatch.setattr(reset, "_hand_back_network", lambda: [])
    monkeypatch.setattr(reset, "_forget_collected", lambda: [])
    monkeypatch.setattr(reset, "_forget_logs", lambda: [])
    monkeypatch.setattr(reset, "_restore_examples", lambda: 0)
    monkeypatch.setattr(reset, "clear_password", lambda: None)

    assert reset._reset_all() == 0
    assert set(acted_units(systemctl, "stop")) == {
        SYSTEM_MANAGED_UNITS[name] for name in stop.STOP_ORDER
    }
