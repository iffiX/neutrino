"""What an Apply does when xray refuses what it was handed.

The three artifacts an Apply installs are independent: the xray configuration,
the nftables ruleset, and dnsmasq. xray is the only one a person can break from
the panel, and it used to be applied first and to abort the rest — so a bad exit
node left the LAN with no firewall rules and no DNS until it was fixed.
"""

import subprocess

import pytest

from neutrino_hub.exceptions import StreamRefusedError
from neutrino_hub.modules.router.constants import ROUTER_NFT_PATH as NFT_PATH
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


@pytest.fixture
def applied(monkeypatch):
    """A runtime whose xray refuses, recording what still reached the system."""
    written = []
    monkeypatch.setattr(runtime_module, "read_config", lambda name: CONFIG[name])
    monkeypatch.setattr(runtime_module, "write_config", lambda name, data: None)
    monkeypatch.setattr(runtime_module, "lookup_xray_uid", lambda: 0)
    monkeypatch.setattr(runtime_module, "XrayConfigApplier", _RefusingApplier)
    monkeypatch.setattr(
        runtime_module,
        "write_generated",
        lambda path, text: written.append(("wrote", str(path))),
    )
    monkeypatch.setattr(
        runtime_module.RouterRulesetApplier,
        "apply",
        lambda self, ruleset, **kwargs: written.append(("loaded", "nft")),
    )
    monkeypatch.setattr(
        runtime_module,
        "run",
        lambda command, **kwargs: written.append(("ran", command)),
    )
    panel = object.__new__(PanelRuntime)
    panel.is_config_dirty = True
    panel.settings = {}
    return panel, written


def test_a_refused_xray_config_does_not_take_the_firewall_with_it(applied):
    panel, written = applied

    with pytest.raises(RuntimeError):
        panel._apply_all_blocking()

    assert ("loaded", "nft") in written


def test_a_refused_xray_config_does_not_take_dns_with_it(applied):
    panel, written = applied

    with pytest.raises(RuntimeError):
        panel._apply_all_blocking()

    assert any(step == "ran" for step, _ in written)


def test_the_apply_still_reports_that_xray_refused(applied):
    """Reported, not swallowed: the page is where somebody learns the proxy is
    running the configuration from before their change."""
    panel, _ = applied

    with pytest.raises(RuntimeError) as refusal:
        panel._apply_all_blocking()

    assert "xray rejected" in str(refusal.value)


def test_the_ruleset_is_recorded_only_after_the_kernel_takes_it(applied):
    """The panel reads that file to say where traffic is going. Written first,
    it answers with where traffic was about to go."""
    panel, written = applied

    with pytest.raises(RuntimeError):
        panel._apply_all_blocking()

    steps = [step for step in written if step[1] in ("nft", str(NFT_PATH))]
    assert steps.index(("loaded", "nft")) < steps.index(("wrote", str(NFT_PATH)))


def test_a_refused_apply_leaves_the_configuration_dirty(applied):
    """The panel goes on showing there is something to apply, because there is:
    xray is running what it was running before."""
    panel, _ = applied

    with pytest.raises(RuntimeError):
        panel._apply_all_blocking()

    assert panel.is_config_dirty


class _Sessions:
    """The live sockets: who is online, and what each was handed."""

    def __init__(self, online, refusing=()):
        self.online = list(online)
        self.refusing = set(refusing)
        self.pushed: list = []

    def keys(self):
        return list(self.online)

    def push_state_from_thread(self, key, state_hash, desired, timeout=5.0):
        if key in self.refusing:
            raise StreamRefusedError("agent_never_reported", {"device": key})
        self.pushed.append((key, state_hash, desired))


def _with_devices(panel, monkeypatch, sessions):
    monkeypatch.setattr(
        runtime_module.RouterInterfaceApplier, "apply_all", lambda self: []
    )
    monkeypatch.setattr(
        runtime_module.PanelRuntime,
        "desired_state_for",
        lambda self, device: ("h-" + device, {"modules": {}}),
    )
    panel.agent_sessions = sessions


def test_applying_the_network_hands_every_online_device_its_state(applied, monkeypatch):
    """The shares' fence and a git server's address derive from the network,
    so a network change that never reaches a device leaves its shares
    refusing a network that was just opened."""
    panel, written = applied
    sessions = _Sessions(["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"])
    _with_devices(panel, monkeypatch, sessions)

    summary = panel._apply_network_blocking(None)

    assert [key for key, _, _ in sessions.pushed] == [
        "aa:bb:cc:dd:ee:ff",
        "11:22:33:44:55:66",
    ]
    assert sessions.pushed[0][1] == "h-aa:bb:cc:dd:ee:ff"
    assert "desired state pushed to 2 devices" in summary


def test_a_box_with_no_device_online_applies_its_network_all_the_same(
    applied, monkeypatch
):
    panel, written = applied
    _with_devices(panel, monkeypatch, _Sessions([]))

    summary = panel._apply_network_blocking(None)

    assert ("loaded", "nft") in written
    assert "desired state" not in summary


def test_a_device_that_will_not_take_the_push_does_not_fail_the_network(
    applied, monkeypatch
):
    """The network is applied by then; a socket that did not answer in
    time is named in the summary rather than raised."""
    panel, written = applied
    sessions = _Sessions(["aa:bb:cc:dd:ee:ff"], refusing=["aa:bb:cc:dd:ee:ff"])
    _with_devices(panel, monkeypatch, sessions)

    summary = panel._apply_network_blocking(None)

    assert ("loaded", "nft") in written
    assert "desired state not pushed to aa:bb:cc:dd:ee:ff" in summary
