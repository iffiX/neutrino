"""Whose traffic the proxy is taking, as the status strip will report it."""

from neutrino_hub.web import panel_runtime as runtime_module
from neutrino_hub.web.panel_runtime import PanelRuntime

# The two tproxy statements the renderer can emit, told apart the way the
# scope reader tells them apart: the hub's own diversion hairpins through
# loopback, the LAN's does not.
LAN_DIVERSION = (
    "        meta l4proto { tcp, udp } tproxy ip to 127.0.0.1:12345 "
    "meta mark set 0x1 accept\n"
)
HUB_DIVERSION = (
    '        iifname "lo" meta mark 0x1 meta l4proto { tcp, udp } '
    "tproxy ip to 127.0.0.1:12345 accept\n"
)


def routing(**overrides) -> dict:
    base = {
        "is_proxy_enabled": True,
        "is_local_proxy_enabled": False,
        "socks_ports": [],
    }
    base.update(overrides)
    return base


def runtime_with(
    monkeypatch,
    tmp_path,
    *,
    routing: dict,
    ruleset: str | None,
    network: dict | None = None
) -> PanelRuntime:
    runtime = object.__new__(PanelRuntime)
    config = {
        "xray/routing.json": routing,
        "router/network.json": network or {"mode": "server", "interfaces": []},
    }
    monkeypatch.setattr(runtime_module, "read_config", lambda name: config[name])
    path = tmp_path / "router.nft"
    if ruleset is not None:
        path.write_text(ruleset, encoding="utf-8")
    monkeypatch.setattr(runtime_module, "ROUTER_NFT_PATH", path)
    return runtime


def test_the_master_switch_off_is_off(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(is_proxy_enabled=False),
        ruleset=LAN_DIVERSION,
    )

    assert runtime.proxy_scope() == "off"


def test_a_diverted_lan_reads_as_lan(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch, tmp_path, routing=routing(), ruleset=LAN_DIVERSION
    )

    assert runtime.proxy_scope() == "lan"


def test_both_diversions_read_as_both(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(),
        ruleset=LAN_DIVERSION + HUB_DIVERSION,
    )

    assert runtime.proxy_scope() == "lan_and_hub"


def test_the_hub_alone_reads_as_hub(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch, tmp_path, routing=routing(), ruleset=HUB_DIVERSION
    )

    assert runtime.proxy_scope() == "hub"


def test_a_proxied_port_with_no_diversion_reads_as_ports(monkeypatch, tmp_path):
    """A server's proxy is its listeners.

    Reporting "direct" there would claim traffic is bypassing a proxy every
    pointed application is using.
    """
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(socks_ports=[{"port": 1080, "is_proxied": True}]),
        ruleset="chain prerouting {\n}\n",
    )

    assert runtime.proxy_scope() == "ports"


def test_nothing_sent_to_the_proxy_reads_as_unused(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(socks_ports=[{"port": 1080, "is_proxied": False}]),
        ruleset="chain prerouting {\n}\n",
    )

    assert runtime.proxy_scope() == "unused"


def test_nothing_applied_yet_answers_from_the_configuration(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(),
        ruleset=None,
        network={
            "mode": "router",
            "interfaces": [
                {"name": "enp2s0", "role": "lan", "lan": {"address": "192.168.8.1"}}
            ],
        },
    )

    assert runtime.proxy_scope() == "lan"
