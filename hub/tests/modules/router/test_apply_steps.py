"""The interface roles applied as steps: one failing does not stop the rest,
an uplink waiting on its lease says so, and an event leaves a unit systemd
is already restarting alone.
"""

import subprocess

import pytest

from neutrino_hub.modules.router import routes
from neutrino_hub.modules.router.constants import (
    ROUTER_CODE_LEASE_PENDING,
    ROUTER_STEP_APPLIED,
    ROUTER_STEP_FAILED,
    ROUTER_STEP_PENDING,
    ROUTER_TRIGGER_APPLY,
    ROUTER_TRIGGER_EVENT,
)
from neutrino_hub.modules.router.interfaces import (
    RouterInterface,
    RouterLanSettings,
    RouterNetworkConfig,
)


class _Plan:
    def uplink(self, name):
        return None


@pytest.fixture
def machine(monkeypatch):
    """No link read, no manager to stand down, no default route to rebuild."""
    monkeypatch.setattr(routes.RouterLinkStatus, "all_links", lambda self: [])
    monkeypatch.setattr(routes, "build_uplink_plan", lambda **keywords: _Plan())
    monkeypatch.setattr(routes.stack, "running_managers", list)
    monkeypatch.setattr(routes.RouterDefaultRouteApplier, "apply", lambda self: [])
    monkeypatch.setattr(
        routes.RouterInterfaceApplier, "apply_resolver", lambda self: []
    )


def _lan(name: str, address: str) -> RouterInterface:
    return RouterInterface(
        name=name,
        role="lan",
        lan=RouterLanSettings(address=address, prefix_len=24, is_dhcp_enabled=False),
    )


def test_a_port_that_fails_does_not_stop_the_next_one(machine, monkeypatch):
    def apply(self, interface):
        if interface.name == "eth0":
            raise subprocess.CalledProcessError(2, ["ip"], stderr="not up")
        return [f"{interface.name} serving"]

    monkeypatch.setattr(routes.RouterInterfaceApplier, "apply", apply)
    network = RouterNetworkConfig(
        mode="router",
        interfaces=[_lan("eth0", "10.0.0.1"), _lan("eth1", "10.0.1.1")],
    )

    results = routes.RouterInterfaceApplier(network=network).apply_steps()

    by_name = {result.name: result.state for result in results}
    assert by_name["interface eth0"] == ROUTER_STEP_FAILED
    assert by_name["interface eth1"] == ROUTER_STEP_APPLIED
    assert "default_route" in by_name and "resolver" in by_name


def test_the_whole_network_apply_raises_after_trying_every_port(machine, monkeypatch):
    applied = []

    def apply(self, interface):
        applied.append(interface.name)
        if interface.name == "eth0":
            raise subprocess.CalledProcessError(2, ["ip"], stderr="not up")
        return []

    monkeypatch.setattr(routes.RouterInterfaceApplier, "apply", apply)
    network = RouterNetworkConfig(
        mode="router",
        interfaces=[_lan("eth0", "10.0.0.1"), _lan("eth1", "10.0.1.1")],
    )

    with pytest.raises(subprocess.CalledProcessError):
        routes.RouterInterfaceApplier(network=network).apply_all()

    assert applied == ["eth0", "eth1"]


class _LeaseClient:
    state = "inactive"
    asked: list = []

    def __init__(self, *, interface):
        self.interface = interface

    def start(self):
        _LeaseClient.asked.append("start")

    def restart(self):
        _LeaseClient.asked.append("restart")

    def stop(self):
        pass


@pytest.fixture
def uplink(machine, monkeypatch):
    """One DHCP uplink whose rendered file is unchanged."""
    _LeaseClient.state, _LeaseClient.asked = "inactive", []
    monkeypatch.setattr(routes, "RouterDhcpClient", _LeaseClient)
    monkeypatch.setattr(routes, "_write_dhcp_config", lambda device, metric: False)
    monkeypatch.setattr(routes.links, "set_up", lambda device: None)
    monkeypatch.setattr(routes.links, "set_mac", lambda device, mac: False)
    monkeypatch.setattr(routes.links, "has_lease", lambda device: False)
    monkeypatch.setattr(routes.links, "retire_carried", lambda devices: ["retired"])
    return RouterNetworkConfig(
        mode="router", interfaces=[RouterInterface(name="eth0", role="wan")]
    )


def _pass(network, trigger):
    return routes.RouterInterfaceApplier(
        network=network, trigger=trigger, is_lease_awaited=False
    )


def test_an_uplink_with_no_lease_yet_waits_for_it(uplink):
    results = _pass(uplink, ROUTER_TRIGGER_EVENT).apply_steps()

    step = next(result for result in results if result.name == "interface eth0")
    assert (step.state, step.code) == (ROUTER_STEP_PENDING, ROUTER_CODE_LEASE_PENDING)


def test_the_lease_arriving_retires_the_address_carried_over(uplink, monkeypatch):
    monkeypatch.setattr(routes.links, "has_lease", lambda device: True)

    results = _pass(uplink, ROUTER_TRIGGER_EVENT).apply_steps()

    step = next(result for result in results if result.name == "interface eth0")
    assert step.state == ROUTER_STEP_APPLIED
    assert "retired" in step.changes


@pytest.mark.parametrize("state", ["activating", "failed"])
def test_an_event_leaves_a_lease_client_systemd_is_restarting(uplink, state):
    """Starting it again from every event is a retry on a timer."""
    _LeaseClient.state = state

    _pass(uplink, ROUTER_TRIGGER_EVENT).apply_steps()

    assert _LeaseClient.asked == []


def test_a_person_applying_restarts_a_lease_client_that_failed(uplink):
    _LeaseClient.state = "failed"

    _pass(uplink, ROUTER_TRIGGER_APPLY).apply_steps()

    assert _LeaseClient.asked == ["start"]


def test_a_stopped_lease_client_is_started_either_way(uplink):
    _pass(uplink, ROUTER_TRIGGER_EVENT).apply_steps()

    assert _LeaseClient.asked == ["start"]
