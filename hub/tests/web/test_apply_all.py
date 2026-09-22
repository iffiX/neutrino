"""What an Apply does when xray refuses what it was handed, or a step of the
routing state fails.

The three artifacts an Apply installs are independent: the xray configuration,
the routing state, and dnsmasq. xray is the only one a person can break from
the panel, and it used to be applied first and to abort the rest — so a bad exit
node left the LAN with no firewall rules and no DNS until it was fixed. The
routing state is one pass of steps; a failed step reaches the page, and a step
waiting on a port or a lease does not.
"""

import subprocess

import pytest

from neutrino_hub.exceptions import StreamRefusedError
from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.router.constants import (
    ROUTER_CODE_COMMAND_FAILED,
    ROUTER_CODE_LEASE_PENDING,
    ROUTER_STEP_APPLIED,
    ROUTER_STEP_FAILED,
    ROUTER_STEP_PENDING,
)
from neutrino_hub.modules.router.steps import RouterStepResult
from neutrino_hub.web import panel_runtime as runtime_module
from neutrino_hub.web.panel_runtime import PanelRuntime

CONFIG = {
    "router/network.json": {"mode": "server", "interfaces": []},
    "xray/routing.json": {
        "is_proxy_enabled": False,
        "is_geoip_split_enabled": False,
        "direct_domains": [],
        "direct_ips": [],
        "is_local_proxy_enabled": False,
        "socks_ports": [],
        "remote_dns": {"address": "1.1.1.1", "port": 53},
        "direct_dns": {"address": "223.5.5.5", "port": 53},
    },
    "xray/nodes.json": {"nodes": []},
}


class _RefusingApplier:
    """An xray that will not load what it is given."""

    def apply(self, config) -> None:
        raise subprocess.CalledProcessError(
            1,
            ["xray", "run", "-test"],
            stderr="xray rejected the rendered config: bad address",
        )


class _AcceptingApplier:
    """An xray that loads what it is given."""

    def apply(self, config) -> None:
        pass


@pytest.fixture
def applied(monkeypatch):
    """A runtime whose xray refuses, recording what still reached the system.

    Returns the panel, what reached the system in order, and the results the
    routing pass answers with, which a test may replace.
    """
    written = []
    results: list = [RouterStepResult(name="ruleset", state=ROUTER_STEP_APPLIED)]
    # What the real `install_dnsmasq` compares against: the text on disk. The
    # first install moves it, and installing the same text again does not.
    on_disk: dict = {"config": None}

    class Controller:
        def __init__(self, **keywords):
            self.keywords = keywords

        def reconcile(self, *, only=None):
            written.append(("reconciled", only))
            return list(results)

    def install_dnsmasq(config):
        written.append(("installed dnsmasq", config))
        is_moved = on_disk["config"] != config
        on_disk["config"] = config
        return is_moved

    monkeypatch.setattr(runtime_module, "read_config", lambda name: CONFIG[name])
    monkeypatch.setattr(runtime_module, "write_config", lambda name, data: None)
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _RefusingApplier)
    monkeypatch.setattr(runtime_module, "RouterStateController", Controller)
    monkeypatch.setattr(runtime_module, "install_dnsmasq", install_dnsmasq)
    monkeypatch.setattr(
        runtime_module.channel_state,
        "push_states",
        lambda runtime, role: written.append(("pushed states", role)),
    )
    panel = object.__new__(PanelRuntime)
    panel.is_config_dirty = True
    panel.settings = {}
    return panel, written, results


def test_a_refused_xray_config_does_not_take_the_firewall_with_it(applied):
    panel, written, _ = applied

    with pytest.raises(RuntimeError):
        panel._apply_all_blocking()

    assert ("reconciled", None) in written


def test_a_refused_xray_config_does_not_take_dns_with_it(applied):
    panel, written, _ = applied

    with pytest.raises(RuntimeError):
        panel._apply_all_blocking()

    assert [step for step, _ in written].count("installed dnsmasq") == 1


def test_the_apply_still_reports_that_xray_refused(applied):
    """Reported, not swallowed: the page is where somebody learns the proxy is
    running the configuration from before their change."""
    panel, _, _ = applied

    with pytest.raises(RuntimeError) as refusal:
        panel._apply_all_blocking()

    assert "xray rejected" in str(refusal.value)


def test_a_refused_apply_leaves_the_configuration_dirty(applied):
    """The panel goes on showing there is something to apply, because there is:
    xray is running what it was running before."""
    panel, _, _ = applied

    with pytest.raises(RuntimeError):
        panel._apply_all_blocking()

    assert panel.is_config_dirty


def test_a_failed_routing_step_reaches_the_page_by_name(applied, monkeypatch):
    panel, written, results = applied
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
        panel._apply_all_blocking()

    assert "interface enp1s0" in str(failure.value)
    assert [step for step, _ in written].count("installed dnsmasq") == 1


def test_a_step_waiting_on_a_lease_is_not_a_failure(applied, monkeypatch):
    panel, _, results = applied
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _AcceptingApplier)
    results[:] = [
        RouterStepResult(
            name="interface enp2s0",
            state=ROUTER_STEP_PENDING,
            code=ROUTER_CODE_LEASE_PENDING,
        )
    ]

    panel._apply_all_blocking()

    assert not panel.is_config_dirty


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


def _with_devices(panel, monkeypatch, sessions):
    monkeypatch.setattr(
        runtime_module.PanelRuntime,
        "desired_state_for",
        lambda self, device: ("h-" + device, {"modules": {}}),
    )
    panel.agent_sessions = sessions


def test_the_interfaces_are_applied_before_dnsmasq_binds_them(applied, monkeypatch):
    """dnsmasq restarted before a LAN has its new address has nothing to
    listen on."""
    panel, written, _ = applied
    _with_devices(panel, monkeypatch, _Sessions([]))

    panel._apply_network_blocking("enp1s0")

    steps = [step for step, _ in written]
    assert steps.index("reconciled") < steps.index("installed dnsmasq")


def test_dnsmasq_is_restarted_only_when_its_configuration_moved(applied, monkeypatch):
    """A restart empties a thousand cached names, and an apply that changed
    nothing about DNS has no reason to."""
    panel, _, _ = applied
    _with_devices(panel, monkeypatch, _Sessions([]))

    first = panel._apply_network_blocking(None)
    second = panel._apply_network_blocking(None)

    assert "dnsmasq restarted" in first
    assert "dnsmasq restarted" not in second


def test_both_apply_paths_install_the_same_configuration(applied, monkeypatch):
    """They used to read different routing, so each overwrote the other's file
    and both restarted dnsmasq."""
    panel, written, _ = applied
    _with_devices(panel, monkeypatch, _Sessions([]))

    panel._apply_network_blocking(None)
    with pytest.raises(RuntimeError):
        panel._apply_all_blocking()

    installed = [config for step, config in written if step == "installed dnsmasq"]
    assert installed[0] == installed[1]


def test_applying_the_network_hands_every_online_device_its_state(applied, monkeypatch):
    """The shares' fence and a git server's address derive from the network,
    so a network change that never reaches a device leaves its shares
    refusing a network that was just opened."""
    panel, written, _ = applied
    sessions = _Sessions(["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"])
    _with_devices(panel, monkeypatch, sessions)

    summary = panel._apply_network_blocking(None)

    assert [key for key, _, _ in sessions.pushed] == [
        "aa:bb:cc:dd:ee:ff",
        "11:22:33:44:55:66",
    ]
    assert sessions.pushed[0][1] == "h-aa:bb:cc:dd:ee:ff"
    assert "desired state pushed to 2 devices" in summary


def test_applying_the_network_hands_every_client_its_state(applied, monkeypatch):
    """The address set a client holds derives from the network too, and the
    push after the devices' is how a change reaches it."""
    panel, written, _ = applied
    _with_devices(panel, monkeypatch, _Sessions([]))

    panel._apply_network_blocking(None)

    steps = [step for step, _ in written]
    assert ("pushed states", CHANNEL_ROLE_CLIENT) in written
    assert steps.index("installed dnsmasq") < steps.index("pushed states")


def test_a_box_with_no_device_online_applies_its_network_all_the_same(
    applied, monkeypatch
):
    panel, written, _ = applied
    _with_devices(panel, monkeypatch, _Sessions([]))

    summary = panel._apply_network_blocking(None)

    assert ("reconciled", None) in written
    assert "desired state" not in summary


def test_a_device_that_will_not_take_the_push_does_not_fail_the_network(
    applied, monkeypatch
):
    """The network is applied by then; a socket that did not answer in
    time is named in the summary rather than raised."""
    panel, written, _ = applied
    sessions = _Sessions(["aa:bb:cc:dd:ee:ff"], refusing=["aa:bb:cc:dd:ee:ff"])
    _with_devices(panel, monkeypatch, sessions)

    summary = panel._apply_network_blocking(None)

    assert ("reconciled", None) in written
    assert "desired state not pushed to aa:bb:cc:dd:ee:ff" in summary
