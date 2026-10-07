"""What the runtime does when an agent's channel opens or ends, and when an
overlay's device moves.

The devices page is told, the published list is recomposed, and every
client is handed its state, whose terminals list each machine's presence,
so a client's dots follow the machines at once rather than at its next
report. An overlay device found at run time that the loaded ruleset does not
name yet runs one converge step, and nothing else does; so do network
resolvers the last render did not use.
"""

import json
import threading
import time

import pytest

from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.overlay.constants import OVERLAY_ENGINES
from neutrino_hub.modules.router import controller, routes
from neutrino_hub.web import channel_state
from neutrino_hub.web import panel_runtime as runtime_module
from neutrino_hub.web.constants import WEB_EVENT_DEVICES
from neutrino_hub.web.panel_runtime import PanelRuntime


class RecordingEvents:
    def __init__(self):
        self.published = []

    def publish(self, event_type, key="", data=None):
        self.published.append(event_type)


class CountingServices:
    def __init__(self):
        self.refreshes = 0

    def schedule_refresh(self) -> None:
        self.refreshes += 1


def test_an_agent_coming_or_going_pushes_every_client_its_state(monkeypatch):
    pushed = []
    done = threading.Event()

    def push_states(runtime, role):
        pushed.append((runtime, role, threading.current_thread().name))
        done.set()

    monkeypatch.setattr(runtime_module.channel_state, "push_states", push_states)
    panel = object.__new__(PanelRuntime)
    panel.events = RecordingEvents()
    panel.published_services = CountingServices()

    panel._publish_devices()

    assert done.wait(timeout=5)
    assert pushed == [(panel, CHANNEL_ROLE_CLIENT, "client_state_push")]
    assert panel.events.published == [WEB_EVENT_DEVICES]
    assert panel.published_services.refreshes == 1


class CountingConverge:
    def __init__(self):
        self.passes = 0

    def __call__(self, only=None) -> str:
        self.passes += 1
        return "applied"


def following(monkeypatch, found: dict, recorded: "dict | None") -> tuple:
    """A runtime on EasyTier whose devices are found as given."""
    if recorded is not None:
        controller.ROUTER_OVERLAY_DEVICES_PATH.write_text(json.dumps(recorded))
    monkeypatch.setattr(
        runtime_module,
        "read_config",
        lambda name: {"overlays": [{"provider": "easytier"}]},
    )
    monkeypatch.setattr(runtime_module, "overlay_devices", lambda network: found)
    monkeypatch.setattr(runtime_module, "read_proxy_routing", lambda: {})
    passes = CountingConverge()
    panel = object.__new__(PanelRuntime)
    panel.converge_network_blocking = passes
    return panel, passes


def test_a_new_overlay_device_runs_one_converge(monkeypatch):
    panel, passes = following(monkeypatch, {"easytier": ["tun0"]}, {"easytier": []})

    assert panel.follow_overlay_devices() is True
    assert passes.passes == 1


def test_the_device_the_ruleset_already_names_runs_nothing(monkeypatch):
    panel, passes = following(
        monkeypatch, {"easytier": ["tun0"]}, {"easytier": ["tun0"]}
    )

    assert panel.follow_overlay_devices() is False
    assert passes.passes == 0


def test_an_engine_unit_started_again_runs_one_converge(monkeypatch):
    """A unit that starts again has a cgroup of a new id, which the loaded
    ruleset does not match."""
    panel, passes = following(
        monkeypatch, {"easytier": ["tun0"]}, {"easytier": ["tun0"]}
    )
    path = "system.slice/neutrino_hub_easytier.service"
    controller.ROUTER_ENGINE_CGROUPS_PATH.write_text(json.dumps({path: 11}))
    monkeypatch.setattr(runtime_module, "engine_cgroups", lambda routing: {path: 12})

    assert panel.follow_overlay_devices() is True
    assert passes.passes == 1


def test_the_engine_cgroups_the_ruleset_already_names_run_nothing(monkeypatch):
    panel, passes = following(
        monkeypatch, {"easytier": ["tun0"]}, {"easytier": ["tun0"]}
    )
    path = "system.slice/neutrino_hub_easytier.service"
    controller.ROUTER_ENGINE_CGROUPS_PATH.write_text(json.dumps({path: 11}))
    monkeypatch.setattr(runtime_module, "engine_cgroups", lambda routing: {path: 11})

    assert panel.follow_overlay_devices() is False
    assert passes.passes == 0


def test_outside_linux_a_moved_interface_set_runs_one_converge(on_windows, monkeypatch):
    """The firewall rules are scoped again when an adapter comes back under a
    new name, from the same pass that follows the overlay devices."""
    panel, passes = following(
        monkeypatch, {"easytier": ["tun0"]}, {"easytier": ["tun0"]}
    )
    monkeypatch.setattr(runtime_module, "is_interface_set_moved", lambda: True)

    assert panel.follow_overlay_devices() is True
    assert passes.passes == 1


def test_outside_linux_the_interface_set_the_rules_name_runs_nothing(
    on_windows, monkeypatch
):
    panel, passes = following(
        monkeypatch, {"easytier": ["tun0"]}, {"easytier": ["tun0"]}
    )
    monkeypatch.setattr(runtime_module, "is_interface_set_moved", lambda: False)

    assert panel.follow_overlay_devices() is False
    assert passes.passes == 0


def test_the_network_carries_the_devices_the_ruleset_names(monkeypatch):
    panel, _ = following(monkeypatch, {}, {"easytier": ["tun0"]})

    assert panel.network().exposed_overlay_device_names == ["tun0"]


# --- the network's resolvers --------------------------------------------------

LEASED = [{"address": "192.168.1.1", "port": 53}]


def following_resolvers(monkeypatch, routing: dict, found: list) -> tuple:
    """A runtime whose network's resolvers are read as given."""
    files = {"router/network.json": {"mode": "router"}, "xray/routing.json": routing}
    monkeypatch.setattr(runtime_module, "read_config", lambda name: dict(files[name]))
    monkeypatch.setattr(runtime_module, "read_network_resolvers", lambda network: found)
    passes = CountingConverge()
    panel = object.__new__(PanelRuntime)
    panel.converge_network_blocking = passes
    panel.proxy = FakeProxy(routing)
    return panel, passes


class FakeProxy:
    """The proxy's part, holding the routing options the test gave."""

    def __init__(self, routing: dict):
        self._routing = routing

    def routing(self) -> dict:
        return dict(self._routing)

    def has_direct_resolvers(self, routing: dict) -> bool:
        return bool(routing.get("direct_dns"))


def test_a_lease_naming_new_resolvers_runs_one_converge(monkeypatch):
    routes.record_network_resolvers([{"address": "223.5.5.5", "port": 53}])
    panel, passes = following_resolvers(monkeypatch, {"direct_dns": []}, LEASED)

    assert panel.follow_network_resolvers() is True
    assert passes.passes == 1


def test_the_resolvers_the_last_render_used_run_nothing(monkeypatch):
    routes.record_network_resolvers(LEASED)
    panel, passes = following_resolvers(monkeypatch, {"direct_dns": []}, LEASED)

    assert panel.follow_network_resolvers() is False
    assert passes.passes == 0


@pytest.mark.feature("proxy")
def test_outside_linux_a_direct_list_of_its_own_reads_nothing(on_windows, monkeypatch):
    """No dnsmasq runs there, so the network's resolvers matter only while
    the direct list follows them."""
    panel, passes = following_resolvers(
        monkeypatch, {"direct_dns": [{"address": "119.29.29.29", "port": 53}]}, LEASED
    )
    monkeypatch.setattr(
        runtime_module,
        "read_network_resolvers",
        lambda network: pytest.fail("read with a direct list of its own"),
    )

    assert panel.follow_network_resolvers() is False
    assert passes.passes == 0


class OwnMachineDevices:
    """The device rows: one on the hub's own machine, one elsewhere."""

    def __init__(self):
        self.rows = {
            "own": type("Row", (), {"machine_id": "hub-machine"})(),
            "other": type("Row", (), {"machine_id": "laptop"})(),
        }

    def get(self, key):
        return self.rows.get(key)


def test_the_hubs_own_device_is_handed_loopback_first(monkeypatch):
    """A state whose addresses lack loopback would take it from the hub's own
    agent; its state names loopback first, every other device's does not."""
    panel = object.__new__(PanelRuntime)
    devices = OwnMachineDevices()
    monkeypatch.setattr(runtime_module, "DeviceRegistry", lambda: devices)
    monkeypatch.setattr(runtime_module, "machine_id", lambda: "hub-machine")
    monkeypatch.setattr(runtime_module, "channel_urls", lambda runtime: [])
    monkeypatch.setattr(
        runtime_module, "own_agent_urls", lambda runtime: ["https://127.0.0.1:8443"]
    )

    assert panel._device_urls("own") == ["https://127.0.0.1:8443"]
    assert panel._device_urls("other") == []
    assert panel._device_urls("gone") == []


class SlowEnginePart:
    """NetBird's part on a hub whose own daemon is not running: its status
    command takes ten seconds before it gives up."""

    asked = 0

    def address(self):
        SlowEnginePart.asked += 1
        time.sleep(10)
        return ""


def slow_engines(monkeypatch):
    from neutrino_hub.modules.easytier import ops as easytier_ops
    from neutrino_hub.modules.overlay import ops as overlay_ops

    SlowEnginePart.asked = 0
    monkeypatch.setattr(
        overlay_ops, "overlay_parts", lambda: {"netbird": SlowEnginePart}
    )

    def slow_easytier():
        SlowEnginePart.asked += 1
        time.sleep(2)
        return []

    monkeypatch.setattr(easytier_ops, "console_device_names", slow_easytier)
    monkeypatch.setattr(overlay_ops, "console_device_names", slow_easytier)


@pytest.mark.skipif("netbird" not in OVERLAY_ENGINES, reason="this tree has no NetBird")
def test_a_clients_hello_asks_no_engine_and_is_settled_within_a_second(
    on_windows, monkeypatch
):
    """The reported bug: on Windows the welcome waited 24 s on NetBird's and
    EasyTier's status commands, and the app gave up after ten."""
    slow_engines(monkeypatch)
    monkeypatch.setattr(
        runtime_module,
        "_held_addresses",
        lambda is_ipv6: {
            "NetBird": ["100.64.0.5/16"],
            "Ethernet": ["192.168.10.105/24"],
        },
    )
    monkeypatch.setattr(
        runtime_module, "rendered_overlay_devices", lambda: {"netbird": ["NetBird"]}
    )
    panel = object.__new__(PanelRuntime)
    panel.client_scope = {}
    panel.client_reached = {}
    monkeypatch.setattr(panel, "host_scopes", lambda: [], raising=False)

    started = time.monotonic()
    channel_state.note_client_scope(
        panel, "client-one", peer_host="100.64.0.9", reached_host="100.64.0.5"
    )
    took = time.monotonic() - started

    assert took < 1.0
    assert SlowEnginePart.asked == 0
    assert panel.overlay_networks() == {
        "netbird": ["100.64.0.5/16"],
        "easytier": [],
    }
    assert panel.interface_networks() == ["192.168.10.105/24"]
    assert panel.client_reached["client-one"] == "netbird"


@pytest.mark.skipif("netbird" not in OVERLAY_ENGINES, reason="this tree has no NetBird")
def test_on_linux_an_engine_the_converge_did_not_record_rides_its_own_device(
    monkeypatch,
):
    from neutrino_hub.modules.overlay import ops as overlay_ops

    slow_engines(monkeypatch)
    monkeypatch.setattr(overlay_ops, "_is_easytier_console_mode", lambda: False)
    monkeypatch.setattr(
        runtime_module,
        "_held_addresses",
        lambda is_ipv6: {"wt0": ["100.64.0.5/16"], "enp1s0": ["192.168.1.5/24"]},
    )
    monkeypatch.setattr(runtime_module, "rendered_overlay_devices", lambda: {})
    panel = object.__new__(PanelRuntime)

    assert panel.overlay_networks()["netbird"] == ["100.64.0.5/16"]
    assert panel.interface_networks() == ["192.168.1.5/24"]
    assert SlowEnginePart.asked == 0
