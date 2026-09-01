"""What an Apply does when xray refuses what it was handed.

The three artifacts an Apply installs are independent: the xray configuration,
the nftables ruleset, and dnsmasq. xray is the only one a person can break from
the panel, and it used to be applied first and to abort the rest — so a bad exit
node left the LAN with no firewall rules and no DNS until it was fixed.
"""

import pytest

from neutrino_hub.modules.router.constants import ROUTER_NFT_PATH as NFT_PATH
from neutrino_hub.utils.subprocess_run import CommandError
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
        raise CommandError("xray rejected the rendered config: bad address")


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
    return panel, written


def test_a_refused_xray_config_does_not_take_the_firewall_with_it(applied):
    panel, written = applied

    with pytest.raises(CommandError):
        panel._apply_all_blocking()

    assert ("loaded", "nft") in written


def test_a_refused_xray_config_does_not_take_dns_with_it(applied):
    panel, written = applied

    with pytest.raises(CommandError):
        panel._apply_all_blocking()

    assert any(step == "ran" for step, _ in written)


def test_the_apply_still_reports_that_xray_refused(applied):
    """Reported, not swallowed: the page is where somebody learns the proxy is
    running the configuration from before their change."""
    panel, _ = applied

    with pytest.raises(CommandError) as refusal:
        panel._apply_all_blocking()

    assert "xray rejected" in str(refusal.value)


def test_the_ruleset_is_recorded_only_after_the_kernel_takes_it(applied):
    """The panel reads that file to say where traffic is going. Written first,
    it answers with where traffic was about to go."""
    panel, written = applied

    with pytest.raises(CommandError):
        panel._apply_all_blocking()

    steps = [step for step in written if step[1] in ("nft", str(NFT_PATH))]
    assert steps.index(("loaded", "nft")) < steps.index(("wrote", str(NFT_PATH)))


def test_a_refused_apply_leaves_the_configuration_dirty(applied):
    """The panel goes on showing there is something to apply, because there is:
    xray is running what it was running before."""
    panel, _ = applied

    with pytest.raises(CommandError):
        panel._apply_all_blocking()

    assert panel.is_config_dirty
