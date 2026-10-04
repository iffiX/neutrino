"""The converge step every writer of the network, the proxy and the overlays
runs, with the system under it replaced.

Its steps run in one order under the router lock: the enabled engines start,
the routing state is reconciled, dnsmasq and xray restart where their text
moved, every device and every client is handed its state, and only then do
the engines turned off stop. A step that fails stops none of the others: a
refused xray configuration used to abort the rest and leave the LAN with no
firewall and no DNS until somebody fixed a node.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from neutrino_hub.exceptions import StreamRefusedError
from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.overlay.config import enabled_providers, set_enabled
from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER, OVERLAY_NETBIRD
from neutrino_hub.modules.router.constants import (
    ROUTER_CODE_COMMAND_FAILED,
    ROUTER_CODE_LEASE_PENDING,
    ROUTER_STEP_APPLIED,
    ROUTER_STEP_FAILED,
    ROUTER_STEP_CHANGE_CODES,
    ROUTER_STEP_PENDING,
)
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer
from neutrino_hub.modules.router.share_fence import share_subnets
from neutrino_hub.modules.router.steps import RouterStepResult
from neutrino_hub.web import panel_runtime as runtime_module
from neutrino_hub.web.panel_runtime import PanelRuntime
from tests.conftest import FakeMsvcrt

ROUTING = {
    "is_proxy_enabled": True,
    "is_overlay_proxy_enabled": True,
    "is_geoip_split_enabled": False,
    "direct_domains": [],
    "direct_ips": [],
    "is_local_proxy_enabled": False,
    "socks_ports": [],
    "remote_dns": [{"address": "1.1.1.1", "port": 53}],
    "direct_dns": [],
}
# The network's resolvers the converge reads.
NETWORK_RESOLVERS = [{"address": "192.0.2.1", "port": 53}]

ROUTER_NETWORK = {
    "mode": "router",
    "interfaces": [
        {
            "name": "enp1s0",
            "role": "lan",
            "lan": {"address": "192.168.100.1", "prefix_len": 24},
        },
        {"name": "enp2s0", "role": "wan"},
    ],
    "overlays": [{"provider": "netbird"}],
}

# Where the kernel holds an address, for the share fence.
ADDRESSES = {
    "enp1s0": "192.168.100.1/24",
    "enp2s0": "198.51.100.9/25",
    "wt0": "100.64.0.1/16",
    "easytier": "10.0.0.1/24",
}


class _RefusingApplier:
    """An xray that will not load what it is given."""

    def apply_if_changed(self, config) -> bool:
        raise subprocess.CalledProcessError(
            1,
            ["xray", "run", "-test"],
            stderr="xray rejected the rendered config: bad address",
        )


class _AcceptingApplier:
    """An xray that loads what it is given."""

    def apply_if_changed(self, config) -> bool:
        return True


class _Health:
    def __init__(self, *, is_down: bool):
        self.is_down = is_down


class _ExitController:
    """The exit controller's windows: one node down, one alive."""

    def healths(self) -> dict:
        return {"node_hk1": _Health(is_down=True), "node_hk2": _Health(is_down=False)}


class _Sessions:
    """The live sockets: who is online, and what each was handed."""

    def __init__(self, online, refusing=()):
        self.online = list(online)
        self.refusing = set(refusing)
        self.pushed: list = []

    def keys(self):
        return list(self.online)

    def push_state_from_thread(self, key, document, timeout=5.0):
        if key in self.refusing:
            raise StreamRefusedError("agent_never_reported", {"device": key})
        self.pushed.append((key, document["hash"], document))


@pytest.fixture
def applied(monkeypatch):
    """A runtime whose xray refuses, recording what reached the system.

    Returns the panel, what reached the system in order, the results the
    routing pass answers with, which a test may replace, and the files it
    reads, which a test may edit.
    """
    written = []
    results: list = [RouterStepResult(name="ruleset", state=ROUTER_STEP_APPLIED)]
    files = {
        "router/network.json": {"mode": "server", "interfaces": []},
        "xray/routing.json": dict(ROUTING, is_proxy_enabled=False),
        "xray/nodes.json": {"nodes": []},
    }
    # What the real `install_dnsmasq` compares against: the text on disk. The
    # first install moves it, and installing the same text again does not.
    on_disk: dict = {"config": None}

    class Controller:
        def __init__(self, **keywords):
            self.keywords = keywords

        def reconcile_locked(self, *, only=None):
            written.append(("reconciled", only))
            return list(results)

    class Switcher:
        changes: list = []

        def start(self, network, *, report=None):
            written.append(("started", enabled_providers(network)))
            return []

        def stop(self, network, *, report=None):
            written.append(("stopped", enabled_providers(network)))
            return []

    def install_dnsmasq(config):
        written.append(("installed dnsmasq", config))
        is_moved = on_disk["config"] != config
        on_disk["config"] = config
        return is_moved

    monkeypatch.setattr(
        runtime_module, "read_config", lambda name: copy.deepcopy(files[name])
    )
    monkeypatch.setattr(runtime_module, "write_config", lambda name, data: None)
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _RefusingApplier)
    monkeypatch.setattr(runtime_module, "RouterStateController", Controller)
    monkeypatch.setattr(runtime_module, "OverlaySwitcher", Switcher)

    class Guard:
        def check(self, network):
            written.append(("routes checked", None))
            return []

    monkeypatch.setattr(runtime_module, "install_dnsmasq", install_dnsmasq)
    monkeypatch.setattr(runtime_module, "OverlayRouteGuard", Guard)
    monkeypatch.setattr(
        runtime_module,
        "read_network_resolvers",
        lambda network: copy.deepcopy(NETWORK_RESOLVERS),
    )
    monkeypatch.setattr(
        runtime_module,
        "record_network_resolvers",
        lambda rows: files.__setitem__("recorded resolvers", rows),
    )
    monkeypatch.setattr(
        runtime_module.channel_state,
        "push_states",
        lambda runtime, role: written.append(("pushed states", role)),
    )
    panel = object.__new__(PanelRuntime)
    panel.exit_controller = _ExitController()
    panel.is_config_dirty = True
    panel.settings = {}
    panel.agent_sessions = _Sessions([])
    panel.overlay_route_conflicts = []
    monkeypatch.setattr(
        runtime_module.PanelRuntime,
        "desired_state_for",
        lambda self, device: ("h-" + device, {"modules": {}}),
    )
    return panel, written, results, files


def steps_of(written) -> list:
    return [step for step, _ in written]


# --- the order --------------------------------------------------------------


def test_the_steps_run_in_their_order(applied, monkeypatch):
    panel, written, _, _ = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)
    panel.agent_sessions = _Sessions(["aa:bb:cc:dd:ee:ff"])

    changes = panel.converge_network_blocking()

    assert steps_of(written) == [
        "started",
        "reconciled",
        "installed dnsmasq",
        "pushed states",
        "stopped",
        "routes checked",
    ]
    assert {"code": "xray_restarted", "params": {}} in changes
    assert {"code": "devices_pushed", "params": {"count": 1}} in changes


def test_the_networks_resolvers_reach_dnsmasq_and_xray_and_are_recorded(
    applied, monkeypatch
):
    panel, written, _, files = applied
    rendered = {}

    class Applier:
        def apply_if_changed(self, config) -> bool:
            rendered["xray"] = config
            return True

    monkeypatch.setattr(runtime_module, "XrayConfigApplier", Applier)

    panel.converge_network_blocking()

    (dnsmasq,) = [config for step, config in written if step == "installed dnsmasq"]
    assert "server=192.0.2.1#53" in dnsmasq.splitlines()
    assert files["recorded resolvers"] == NETWORK_RESOLVERS
    assert "xray" in rendered


def test_every_peer_is_pushed_before_an_engine_stops(applied):
    """A client reached through the engine being turned off hears the new
    state while its socket still stands, and nobody waits for it to say so."""
    panel, written, _, _ = applied

    with pytest.raises(RuntimeError):
        panel.converge_network_blocking()

    steps = steps_of(written)
    assert steps.index("pushed states") < steps.index("stopped")
    assert ("pushed states", CHANNEL_ROLE_CLIENT) in written


def test_the_steps_run_under_the_router_lock(applied, monkeypatch):
    """The resident router unit takes the same lock, so it cannot apply the
    configuration half way through a converge."""
    panel, written, _, _ = applied
    held = []

    class Lock:
        def __enter__(self):
            held.append(True)

        def __exit__(self, *exc):
            held.append(False)

    monkeypatch.setattr(runtime_module, "router_lock", Lock)
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)

    panel.converge_network_blocking()

    assert held == [True, False]


# --- a step that fails stops none of the others ------------------------------


def test_a_refused_xray_config_does_not_take_the_firewall_or_dns_with_it(applied):
    panel, written, _, _ = applied

    with pytest.raises(RuntimeError) as refusal:
        panel.converge_network_blocking()

    assert ("reconciled", None) in written
    assert steps_of(written).count("installed dnsmasq") == 1
    assert "xray rejected" in str(refusal.value)
    assert [failure["code"] for failure in refusal.value.failures] == ["xray_refused"]


def test_a_refused_apply_leaves_the_configuration_dirty(applied):
    """The panel goes on showing there is something to apply, because there is:
    xray is running what it was running before."""
    panel, _, _, _ = applied

    with pytest.raises(RuntimeError):
        panel.converge_network_blocking()

    assert panel.is_config_dirty


def test_an_engine_that_will_not_start_stops_none_of_the_rest(applied, monkeypatch):
    panel, written, _, _ = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)

    class Switcher:
        changes: list = []

        def start(self, network, *, report=None):
            raise subprocess.CalledProcessError(1, ["systemctl"], stderr="no unit")

        def stop(self, network, *, report=None):
            written.append(("stopped", []))
            return []

    monkeypatch.setattr(runtime_module, "OverlaySwitcher", Switcher)

    with pytest.raises(RuntimeError) as failure:
        panel.converge_network_blocking()

    assert "overlay" in str(failure.value)
    assert steps_of(written) == [
        "reconciled",
        "installed dnsmasq",
        "pushed states",
        "stopped",
        "routes checked",
    ]


def test_a_failed_routing_step_reaches_the_page_by_name(applied, monkeypatch):
    panel, written, results, _ = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)
    results[:] = [
        RouterStepResult(
            name="interface enp1s0",
            state=ROUTER_STEP_FAILED,
            code=ROUTER_CODE_COMMAND_FAILED,
            detail="Device for nexthop is not up",
        )
    ]

    with pytest.raises(RuntimeError) as failure:
        panel.converge_network_blocking()

    assert "interface enp1s0" in str(failure.value)
    assert failure.value.failures == [
        {
            "code": ROUTER_CODE_COMMAND_FAILED,
            "params": {"detail": "Device for nexthop is not up"},
        }
    ]
    assert steps_of(written).count("installed dnsmasq") == 1


def test_a_step_waiting_on_a_lease_is_not_a_failure(applied, monkeypatch):
    panel, _, results, _ = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)
    results[:] = [
        RouterStepResult(
            name="interface enp2s0",
            state=ROUTER_STEP_PENDING,
            code=ROUTER_CODE_LEASE_PENDING,
        )
    ]

    panel.converge_network_blocking()

    assert not panel.is_config_dirty


# --- text that did not move restarts nothing --------------------------------


def test_the_interfaces_are_applied_before_dnsmasq_binds_them(applied):
    """dnsmasq restarted before a LAN has its new address has nothing to
    listen on."""
    panel, written, _, _ = applied

    with pytest.raises(RuntimeError):
        panel.converge_network_blocking("enp1s0")

    assert ("reconciled", "enp1s0") in written
    steps = steps_of(written)
    assert steps.index("reconciled") < steps.index("installed dnsmasq")


def test_dnsmasq_is_restarted_only_when_its_configuration_moved(applied, monkeypatch):
    """A restart empties a thousand cached names, and a converge that changed
    nothing about DNS has no reason to."""
    panel, _, _, _ = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)

    first = panel.converge_network_blocking()
    second = panel.converge_network_blocking()

    assert {"code": "dnsmasq_restarted", "params": {}} in first
    assert {"code": "dnsmasq_restarted", "params": {}} not in second


# --- the devices and the clients --------------------------------------------


def test_every_online_device_is_handed_its_state(applied, monkeypatch):
    """The shares' fence and a git server's address derive from the network,
    so a network change that never reaches a device leaves its shares
    refusing a network that was just opened."""
    panel, _, _, _ = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)
    panel.agent_sessions = _Sessions(["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"])

    changes = panel.converge_network_blocking()

    assert [key for key, _, _ in panel.agent_sessions.pushed] == [
        "aa:bb:cc:dd:ee:ff",
        "11:22:33:44:55:66",
    ]
    assert panel.agent_sessions.pushed[0][1] == "h-aa:bb:cc:dd:ee:ff"
    assert {"code": "devices_pushed", "params": {"count": 2}} in changes


def test_a_device_that_will_not_take_the_push_does_not_fail_the_converge(
    applied, monkeypatch
):
    """The network is applied by then; a socket that did not answer in time
    is named in the changes rather than raised."""
    panel, written, _, _ = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)
    panel.agent_sessions = _Sessions(
        ["aa:bb:cc:dd:ee:ff"], refusing=["aa:bb:cc:dd:ee:ff"]
    )

    changes = panel.converge_network_blocking()

    assert ("reconciled", None) in written
    assert {
        "code": "devices_not_pushed",
        "params": {"devices": "aa:bb:cc:dd:ee:ff"},
    } in changes


LOCALES_DIR = Path(__file__).resolve().parents[2] / "frontend/src/locales"


def test_every_change_an_apply_answers_with_is_a_code_both_languages_word(
    applied, monkeypatch
):
    """The page words the answer itself, so an apply that changed every step
    there is answers only with codes each catalog has a sentence for."""
    panel, _, results, _ = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)
    results[:] = [
        RouterStepResult(
            name=f"{kind} enp1s0", state=ROUTER_STEP_APPLIED, changes=["x"]
        )
        for kind in ROUTER_STEP_CHANGE_CODES
    ] + [RouterStepResult(name="unnamed", state=ROUTER_STEP_APPLIED, changes=["x"])]

    class Switcher:
        changes = [
            {"code": code, "params": {"title": "NetBird"}}
            for code in (
                "overlay_updated",
                "overlay_started",
                "overlay_started_no_address",
                "overlay_stopped",
            )
        ]

        def start(self, network, *, report=None):
            return []

        def stop(self, network, *, report=None):
            return []

    monkeypatch.setattr(runtime_module, "OverlaySwitcher", Switcher)
    panel.agent_sessions = _Sessions(["aa", "bb"], refusing=["bb"])

    changes = panel.converge_network_blocking()

    assert {"code": "xray_restarted", "params": {}} in changes
    assert len(changes) == len(ROUTER_STEP_CHANGE_CODES) + 1 + 4 + 4
    for language in sorted(path.name for path in LOCALES_DIR.iterdir()):
        worded = set()
        for path in (LOCALES_DIR / language).glob("*.json"):
            worded |= set(json.loads(path.read_text(encoding="utf-8")))
        for change in changes:
            assert f"code.{change['code']}" in worded, (language, change)


def test_the_nodes_measured_down_reach_the_renderer(applied, monkeypatch):
    panel, _, _, _ = applied
    seen = {}

    class Renderer:
        def __init__(self, **keywords):
            seen.update(keywords)

        def render(self) -> dict:
            return {}

    monkeypatch.setattr(runtime_module, "XrayConfigRenderer", Renderer)
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)

    panel.converge_network_blocking()

    assert seen["down_tags"] == {"node_hk1"}


# --- engines on and off, one at a time --------------------------------------


class _LinkStatus:
    """The links the share fence reads, from the fixed address table."""

    class _Link:
        def __init__(self, name, address):
            self.name = name
            self.ipv4_address = address

    def all_links(self):
        return [self._Link(name, address) for name, address in ADDRESSES.items()]


def test_every_switch_leaves_what_a_fresh_render_would(applied, monkeypatch):
    """EasyTier on, NetBird off, NetBird on, EasyTier off: after each, the
    firewall, the proxy's configuration, the devices' share fence and the
    clients' overlays are what rendering the stored configuration from
    nothing gives, because nothing of the set before survives a converge."""
    panel, _, _, files = applied
    files["router/network.json"] = copy.deepcopy(ROUTER_NETWORK)
    files["xray/routing.json"] = dict(ROUTING)
    seen: dict = {}

    class Controller:
        def reconcile_locked(self, *, only=None):
            network = RouterNetworkConfig.from_dict(files["router/network.json"])
            seen["ruleset"] = RouterNftRenderer(
                network=network, routing=files["xray/routing.json"], xray_uid=999
            ).render()
            return []

    class Applier:
        def apply_if_changed(self, config) -> bool:
            seen["xray"] = config
            return True

    def push_states(runtime, role):
        seen[role] = enabled_providers(runtime.network())

    monkeypatch.setattr(runtime_module, "RouterStateController", Controller)
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", Applier)
    monkeypatch.setattr(runtime_module.channel_state, "push_states", push_states)
    monkeypatch.setattr(runtime_module, "RouterLinkStatus", _LinkStatus)
    monkeypatch.setattr(runtime_module, "device_addresses", lambda: dict(ADDRESSES))
    monkeypatch.setattr(
        runtime_module.PanelRuntime,
        "desired_state_for",
        lambda self, device: ("h", {"allowed_subnets": self.share_subnets()}),
    )
    panel.agent_sessions = _Sessions(["aa:bb:cc:dd:ee:ff"])

    for provider, is_enabled in (
        (OVERLAY_EASYTIER, True),
        (OVERLAY_NETBIRD, False),
        (OVERLAY_NETBIRD, True),
        (OVERLAY_EASYTIER, False),
    ):
        network = RouterNetworkConfig.from_dict(files["router/network.json"])
        set_enabled(network, provider, is_enabled=is_enabled)
        files["router/network.json"] = network.to_dict()

        panel.converge_network_blocking()

        fresh = RouterNetworkConfig.from_dict(files["router/network.json"])
        assert (
            seen["ruleset"]
            == RouterNftRenderer(
                network=fresh, routing=files["xray/routing.json"], xray_uid=999
            ).render()
        )
        assert (
            seen["xray"]
            == runtime_module.XrayConfigRenderer(
                node_list=panel.node_list(), routing=files["xray/routing.json"]
            ).render()
        )
        fence = share_subnets(
            network=fresh,
            link_addresses=dict(ADDRESSES),
            device_addresses=dict(ADDRESSES),
        )
        pushed = panel.agent_sessions.pushed[-1][2]
        assert pushed["allowed_subnets"] == fence
        assert seen[CHANNEL_ROLE_CLIENT] == enabled_providers(fresh)
        for name in fresh.exposed_overlay_device_names:
            assert f'"{name}"' in seen["ruleset"]

    assert seen[CHANNEL_ROLE_CLIENT] == [OVERLAY_NETBIRD]
    assert '"easytier"' not in seen["ruleset"]
    assert "10.0.0.0/24" not in pushed["allowed_subnets"]


@pytest.mark.parametrize("system", ["darwin", "win32"])
def test_macos_and_windows_run_no_dnsmasq(applied, monkeypatch, system):
    panel, written, _, _ = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)
    monkeypatch.setattr("sys.platform", system)
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt())

    panel.converge_network_blocking()

    assert steps_of(written) == [
        "started",
        "reconciled",
        "pushed states",
        "stopped",
        "routes checked",
    ]


def test_macos_and_windows_render_xray_without_the_transparent_inbound(
    applied, monkeypatch, elsewhere
):
    panel, _, _, files = applied
    files["xray/routing.json"] = dict(ROUTING, is_proxy_enabled=True)
    handed = []

    class Recording:
        def apply_if_changed(self, config) -> bool:
            handed.append(config)
            return True

    monkeypatch.setattr(runtime_module, "XrayConfigApplier", Recording)

    panel.converge_network_blocking()

    (config,) = handed
    tags = [inbound["tag"] for inbound in config["inbounds"]]
    assert "tproxy_in" not in tags
    assert "dns_in" in tags
