"""Starting the enabled overlays and standing the others down, with systemd
and the provisioners replaced by fakes.

Starting and stopping are two calls the converge step keeps apart, so every
peer is handed its new state between them. An engine just started is given a
moment to hold an address, and EasyTier is restarted only when what it would
run changed.
"""

import pytest

from neutrino_hub.modules.easytier import ops as easytier_ops
from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.ops import EASYTIER_CONFIG_NAME
from neutrino_hub.modules.overlay import ops
from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER, OVERLAY_NETBIRD
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.system.provisioning import ProvisionResult
from neutrino_hub.utils.json_file import write_config
from tests.conftest import unlock_vault

NETBIRD_UNIT = "neutrino_hub_netbird.service"
EASYTIER_UNIT = "neutrino_hub_easytier.service"


class FakeResult:
    def __init__(self, is_success=True):
        self.is_success = is_success
        self.stdout = ""


class FakeProvisioner:
    """Stands in for the engine's own installer."""

    calls: list = []

    def provision(self, *, report=None):
        FakeProvisioner.calls.append("provision")
        return ProvisionResult(is_changed=False, message="already provisioned")


class Units:
    """systemd as the switcher reads and drives it."""

    def __init__(self):
        self.active: set = set()
        self.enabled: set = set()
        self.commands: list = []

    def run(self, command, **kwargs):
        self.commands.append(list(command))
        verb, unit = command[1], command[-1]
        if verb == "is-active":
            return FakeResult(unit in self.active)
        if verb == "is-enabled":
            return FakeResult(unit in self.enabled)
        if verb == "disable":
            self.active.discard(unit)
            self.enabled.discard(unit)
        return FakeResult()

    def changes(self) -> list:
        return [
            command
            for command in self.commands
            if command[1] not in ("is-active", "is-enabled")
        ]


@pytest.fixture
def box(monkeypatch):
    """A machine whose systemd and provisioners only record what was asked."""
    units = Units()
    FakeProvisioner.calls = []
    monkeypatch.setattr(ops, "run", units.run)
    monkeypatch.setattr(ops, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(
        ops,
        "OVERLAY_PROVISIONERS",
        {OVERLAY_NETBIRD: FakeProvisioner, OVERLAY_EASYTIER: FakeProvisioner},
    )
    monkeypatch.setattr(ops, "apply_stored_if_changed", lambda *, hostname: "")
    monkeypatch.setattr(ops, "device_addresses", lambda: {"wt0": "100.64.0.1/16"})
    return units


def network_of(*enabled: str) -> RouterNetworkConfig:
    return RouterNetworkConfig.from_dict(
        {
            "overlays": [
                {"provider": key, "is_enabled": key in enabled}
                for key in (OVERLAY_NETBIRD, OVERLAY_EASYTIER)
            ]
        }
    )


def switcher() -> ops.OverlaySwitcher:
    return ops.OverlaySwitcher(address_wait_s=0.0, address_poll_s=0.0)


def test_every_enabled_engine_is_provisioned(box):
    switcher().start(network_of(OVERLAY_NETBIRD, OVERLAY_EASYTIER))

    assert FakeProvisioner.calls == ["provision", "provision"]


def test_starting_stops_nothing(box):
    box.active = {NETBIRD_UNIT, EASYTIER_UNIT}

    switcher().start(network_of(OVERLAY_NETBIRD))

    assert box.changes() == []


def test_an_engine_just_started_is_waited_for_until_it_holds_an_address(box):
    notes = switcher().start(network_of(OVERLAY_NETBIRD))

    assert notes == ["NetBird started"]


def test_an_engine_that_holds_no_address_in_time_is_named(box, monkeypatch):
    monkeypatch.setattr(ops, "device_addresses", lambda: {})

    notes = switcher().start(network_of(OVERLAY_NETBIRD))

    assert notes == ["NetBird started without an address yet"]


def test_an_engine_already_running_is_not_waited_for(box, monkeypatch):
    box.active = {NETBIRD_UNIT}

    def refuse():
        raise AssertionError("waited for a running engine")

    monkeypatch.setattr(ops, "device_addresses", refuse)

    assert switcher().start(network_of(OVERLAY_NETBIRD)) == []


def test_easytier_is_applied_only_when_it_is_enabled(box, monkeypatch):
    applied: list = []
    monkeypatch.setattr(
        ops,
        "apply_stored_if_changed",
        lambda *, hostname: applied.append(hostname) or "applied",
    )
    box.active = {NETBIRD_UNIT, EASYTIER_UNIT}

    switcher().start(network_of(OVERLAY_NETBIRD))
    assert applied == []

    notes = switcher().start(network_of(OVERLAY_EASYTIER))
    assert len(applied) == 1
    assert notes == ["EasyTier: applied"]


def test_stopping_stands_down_only_the_engines_turned_off(box):
    box.active = {NETBIRD_UNIT, EASYTIER_UNIT}
    box.enabled = {NETBIRD_UNIT, EASYTIER_UNIT}

    notes = switcher().stop(network_of(OVERLAY_NETBIRD))

    assert box.changes() == [["systemctl", "disable", "--now", EASYTIER_UNIT]]
    assert notes == ["EasyTier stopped"]


def test_an_engine_already_down_is_left_alone(box):
    assert switcher().stop(network_of()) == []
    assert box.changes() == []


def test_a_development_root_drives_no_units(box, monkeypatch):
    monkeypatch.setattr(ops, "is_dev_root_set", lambda: True)
    box.active = {EASYTIER_UNIT}

    switcher().start(network_of(OVERLAY_NETBIRD))
    switcher().stop(network_of(OVERLAY_NETBIRD))

    assert box.changes() == []


def test_an_engine_this_hub_does_not_run_yet_is_refused(box, monkeypatch):
    monkeypatch.setattr(ops, "OVERLAY_PROVISIONERS", {OVERLAY_NETBIRD: FakeProvisioner})

    with pytest.raises(NotImplementedError):
        switcher().start(network_of(OVERLAY_EASYTIER))


def test_easytier_restarts_once_and_not_again_on_the_same_console(
    box, monkeypatch, tmp_path
):
    """A converge runs on every save anywhere on the page; the engine keeps
    its tunnels unless what it runs changed."""
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

    def engine_run(command, **kwargs):
        box.commands.append(list(command))
        if command[1] == "restart":
            box.active.add(command[-1])
        if command[1] == "is-active":
            return FakeResult(command[-1] in box.active)
        return FakeResult()

    monkeypatch.setattr(easytier_ops, "run", engine_run)
    monkeypatch.setattr(
        ops, "apply_stored_if_changed", easytier_ops.apply_stored_if_changed
    )

    switcher().start(network_of(OVERLAY_EASYTIER))
    switcher().start(network_of(OVERLAY_EASYTIER))

    restarts = [command for command in box.commands if command[1] == "restart"]
    assert restarts == [["systemctl", "restart", EASYTIER_UNIT]]
    dropin = tmp_path / "systemd" / "neutrino_hub_easytier.service.d"
    assert '"--config-server" "etk_example"' in (dropin / "arguments.conf").read_text()


# --- the devices an overlay rides on ----------------------------------------


def network_on(provider: str) -> RouterNetworkConfig:
    return RouterNetworkConfig.from_dict({"overlays": [{"provider": provider}]})


def test_an_easytier_console_rides_on_the_devices_found_by_address(monkeypatch):
    monkeypatch.setattr(ops, "read_easytier", lambda: EasyTierConfig(mode="console"))
    monkeypatch.setattr(ops, "console_device_names", lambda: ["tun0"])

    assert ops.overlay_devices(network_on(OVERLAY_EASYTIER)) == {
        OVERLAY_EASYTIER: ["tun0"]
    }


def test_an_easytier_console_with_no_network_yet_rides_on_nothing(monkeypatch):
    monkeypatch.setattr(ops, "read_easytier", lambda: EasyTierConfig(mode="console"))
    monkeypatch.setattr(ops, "console_device_names", lambda: [])

    assert ops.overlay_devices(network_on(OVERLAY_EASYTIER)) == {OVERLAY_EASYTIER: []}


def test_an_easytier_that_is_off_is_not_looked_up(monkeypatch):
    monkeypatch.setattr(ops, "read_easytier", lambda: EasyTierConfig(mode="console"))

    def refuse():
        raise AssertionError("the engine was asked anyway")

    monkeypatch.setattr(ops, "console_device_names", refuse)
    network = RouterNetworkConfig.from_dict(
        {"overlays": [{"provider": OVERLAY_EASYTIER, "is_enabled": False}]}
    )

    assert ops.overlay_devices(network) == {}


@pytest.mark.parametrize("provider", [OVERLAY_EASYTIER, OVERLAY_NETBIRD])
def test_an_engine_that_names_its_device_is_not_looked_up(monkeypatch, provider):
    monkeypatch.setattr(ops, "read_easytier", lambda: EasyTierConfig(mode="manual"))

    def refuse():
        raise AssertionError("the engine was asked anyway")

    monkeypatch.setattr(ops, "console_device_names", refuse)

    assert ops.overlay_devices(network_on(provider)) == {}
