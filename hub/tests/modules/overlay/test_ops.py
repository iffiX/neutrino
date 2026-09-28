"""Switching engines, with systemd and the provisioner replaced by fakes.

The order is what these pin: every engine that was not chosen is stood down
before the chosen one is started, because they share a tunnel device, a peer
port and — for two of the same product — one state file.
"""

import pytest

from neutrino_hub.modules.easytier import ops as easytier_ops
from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.ops import EASYTIER_CONFIG_NAME
from neutrino_hub.modules.overlay import ops
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_EASYTIER,
    OVERLAY_NETBIRD,
    OVERLAY_NONE,
)
from neutrino_hub.system.provisioning import ProvisionResult
from neutrino_hub.utils.json_file import write_config
from tests.conftest import unlock_vault


class FakeResult:
    def __init__(self, is_success=True):
        self.is_success = is_success


class FakeProvisioner:
    """Stands in for the engine's own installer."""

    calls: list = []

    def provision(self, *, report=None):
        FakeProvisioner.calls.append("provision")
        return ProvisionResult(is_changed=True, message="netbird 0.78.1")


@pytest.fixture
def box(monkeypatch):
    """A machine whose systemd and provisioners only record what was asked."""
    commands: list = []
    FakeProvisioner.calls = []
    monkeypatch.setattr(
        ops, "run", lambda command, **kwargs: commands.append(command) or FakeResult()
    )
    monkeypatch.setattr(ops, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(ops, "OVERLAY_PROVISIONERS", {OVERLAY_NETBIRD: FakeProvisioner})
    return commands


def test_choosing_an_engine_stands_the_others_down_and_starts_it(box):
    message = ops.OverlaySwitcher().converge(OVERLAY_NETBIRD)

    assert box == [["systemctl", "disable", "--now", "neutrino_hub_easytier.service"]]
    assert FakeProvisioner.calls == ["provision"]
    assert message == "netbird 0.78.1"


def test_choosing_none_stands_every_engine_down(box):
    assert ops.OverlaySwitcher().converge(OVERLAY_NONE) == ""

    stood_down = [command[-1] for command in box]
    assert stood_down == [
        "neutrino_hub_netbird.service",
        "neutrino_hub_easytier.service",
    ]
    assert FakeProvisioner.calls == []


def test_an_engine_this_hub_does_not_run_yet_is_refused(box):
    with pytest.raises(NotImplementedError):
        ops.OverlaySwitcher().converge(OVERLAY_EASYTIER)


def test_an_overlay_nobody_runs_is_refused(box):
    with pytest.raises(ValueError):
        ops.OverlaySwitcher().converge("tailscale")


def test_a_development_root_drives_no_units(box, monkeypatch):
    monkeypatch.setattr(ops, "is_dev_root_set", lambda: True)

    ops.OverlaySwitcher().converge(OVERLAY_NETBIRD)

    assert box == []


def test_choosing_easytier_runs_the_engine_on_the_stored_network(box, monkeypatch):
    applied: list = []
    monkeypatch.setattr(
        ops,
        "OVERLAY_PROVISIONERS",
        {OVERLAY_NETBIRD: FakeProvisioner, OVERLAY_EASYTIER: FakeProvisioner},
    )
    monkeypatch.setattr(
        ops,
        "apply_easytier",
        lambda *, hostname: applied.append(FakeProvisioner.calls[:]) or "applied",
    )

    assert ops.OverlaySwitcher().converge(OVERLAY_EASYTIER) == "netbird 0.78.1"

    assert applied == [["provision"]]


def test_switching_away_from_easytier_and_back_restarts_the_stored_console(
    box, monkeypatch, tmp_path
):
    """Choosing NetBird stops EasyTier; choosing EasyTier again starts it on
    the console address config/ still holds, not only enables its unit."""
    unlock_vault(monkeypatch, tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config_dir)
    stored = EasyTierConfig(mode="console", is_secure_mode=True)
    stored.set_config_server("etk_example")  # scan: allow
    write_config(EASYTIER_CONFIG_NAME, stored.to_dict())
    core = tmp_path / "easytier-core"
    core.write_text("")
    monkeypatch.setattr(easytier_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(easytier_ops, "SYSTEM_SYSTEMD_DIR", tmp_path / "systemd")
    monkeypatch.setattr(easytier_ops, "EASYTIER_CORE_PATH", core)
    monkeypatch.setattr(easytier_ops, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(easytier_ops, "refresh_unit", lambda: None)
    monkeypatch.setattr(
        easytier_ops, "run", lambda command, **kwargs: box.append(list(command))
    )
    monkeypatch.setattr(
        ops,
        "OVERLAY_PROVISIONERS",
        {OVERLAY_NETBIRD: FakeProvisioner, OVERLAY_EASYTIER: FakeProvisioner},
    )

    ops.OverlaySwitcher().converge(OVERLAY_NETBIRD)
    ops.OverlaySwitcher().converge(OVERLAY_EASYTIER)

    easytier = [
        command for command in box if command[-1] == "neutrino_hub_easytier.service"
    ]
    assert easytier == [
        ["systemctl", "disable", "--now", "neutrino_hub_easytier.service"],
        ["systemctl", "restart", "neutrino_hub_easytier.service"],
    ]
    dropin = tmp_path / "systemd" / "neutrino_hub_easytier.service.d"
    assert '"--config-server" "etk_example"' in (dropin / "arguments.conf").read_text()
