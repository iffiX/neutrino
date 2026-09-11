"""Switching engines, with systemd and the provisioner replaced by fakes.

The order is what these pin: every engine that was not chosen is stood down
before the chosen one is started, because they share a tunnel device, a peer
port and — for two of the same product — one state file.
"""

import pytest

from neutrino_hub.modules.overlay import ops
from neutrino_hub.modules.overlay.constants import (
    OVERLAY_EASYTIER,
    OVERLAY_NETBIRD,
    OVERLAY_NONE,
)
from neutrino_hub.system.provisioning import ProvisionResult


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
