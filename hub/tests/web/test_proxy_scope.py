"""Whose traffic the proxy is taking, as the status strip will report it."""

import json
from pathlib import Path

import pytest

from neutrino_hub.modules.firewall.renderer import FirewallExposure
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.nft_renderer import RouterNftRenderer
from neutrino_hub.web import panel_runtime as runtime_module
from neutrino_hub.web.panel_runtime import PanelRuntime

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"

# The dead exits notice's words by language, as ui_text.md has them.
DEAD_EXITS_WORDS = {
    "en": {
        "ui.proxy.dead_exits": (
            "Every enabled exit node is unreachable. Traffic sent to the proxy "
            "(the LAN's names included) fails until one answers."
        ),
        "ui.proxy.dead_exits_fallback": (
            "Every enabled exit node is unreachable, so traffic sent to the proxy "
            "is leaving through the WAN instead, under this machine's own address."
        ),
    },
    "zh-CN": {
        "ui.proxy.dead_exits": (
            "所有启用的出口节点都不可达。在有节点应答之前，"
            "送往代理的流量都会失败，局域网的域名解析也一样。"
        ),
        "ui.proxy.dead_exits_fallback": (
            "所有启用的出口节点都不可达，送往代理的流量正改从 WAN 出去，"
            "用的是这台机器自己的地址。"
        ),
    },
}

# The two tproxy statements the renderer can emit, told apart the way the
# scope reader tells them apart: the hub's own diversion hairpins through
# loopback, the LAN's does not.
LAN_DIVERSION = (
    "        meta l4proto { tcp, udp } tproxy ip to 127.0.0.1:12345 "
    "meta mark set 0x1 accept\n"
)
HUB_DIVERSION = (
    '        iifname "lo" ip daddr != @reserved_v4 fib daddr type != local '
    "meta l4proto { tcp, udp } tproxy ip to 127.0.0.1:12345 meta mark set 0x1 "
    "accept\n"
)


class FakeProxy:
    """The proxy's part, reading the files the test holds."""

    def __init__(self, config: dict):
        self._config = config

    def routing(self) -> dict:
        return self._config["xray/routing.json"]

    def node_list(self):
        from neutrino_hub.modules.xray.node_config import XrayNodeList

        return XrayNodeList.from_dict(self._config["xray/nodes.json"])


def routing(**overrides) -> dict:
    base = {
        "is_proxy_enabled": True,
        "is_local_proxy_enabled": False,
    }
    base.update(overrides)
    return base


def runtime_with(
    monkeypatch,
    tmp_path,
    *,
    routing: dict,
    ruleset: str | None,
    network: dict | None = None,
    nodes: dict | None = None,
) -> PanelRuntime:
    runtime = object.__new__(PanelRuntime)
    config = {
        "xray/routing.json": routing,
        "router/network.json": network or {"mode": "server", "interfaces": []},
        "xray/nodes.json": nodes or {"nodes": []},
    }
    monkeypatch.setattr(runtime_module, "read_config", lambda name: config[name])
    runtime.proxy = FakeProxy(config)
    path = tmp_path / "router.nft"
    if ruleset is not None:
        path.write_text(ruleset, encoding="utf-8")
    monkeypatch.setattr(runtime_module, "ROUTER_NFT_PATH", path)
    return runtime


@pytest.mark.feature("proxy")
def test_every_switch_off_is_off(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(is_proxy_enabled=False),
        ruleset="chain prerouting {\n}\n",
    )

    assert runtime.proxy_scope() == "off"


@pytest.mark.feature("proxy")
def test_the_kernel_outranks_a_switch_nobody_applied(monkeypatch, tmp_path):
    """A switch turned off and not yet applied is a firewall still diverting,
    and the strip answers for the traffic, not the form."""
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(is_proxy_enabled=False),
        ruleset=LAN_DIVERSION,
    )

    assert runtime.proxy_scope() == "lan"


@pytest.mark.feature("proxy")
def test_a_diverted_lan_reads_as_lan(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch, tmp_path, routing=routing(), ruleset=LAN_DIVERSION
    )

    assert runtime.proxy_scope() == "lan"


@pytest.mark.feature("proxy")
def test_both_diversions_read_as_both(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(),
        ruleset=LAN_DIVERSION + HUB_DIVERSION,
    )

    assert runtime.proxy_scope() == "lan+hub"


@pytest.mark.feature("proxy")
def test_the_hub_alone_reads_as_hub(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch, tmp_path, routing=routing(), ruleset=HUB_DIVERSION
    )

    assert runtime.proxy_scope() == "hub"


@pytest.mark.feature("proxy")
def test_nothing_sent_to_the_proxy_reads_as_unused(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(),
        ruleset="chain prerouting {\n}\n",
    )

    assert runtime.proxy_scope() == "unused"


@pytest.mark.feature("proxy")
@pytest.mark.parametrize("is_proxied", [True, False], ids=["proxied", "direct"])
def test_an_earlier_builds_listener_reads_as_nothing(monkeypatch, tmp_path, is_proxied):
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(
            is_proxy_enabled=False,
            socks_ports=[{"port": 1080, "is_proxied": is_proxied}],
        ),
        ruleset="chain prerouting {\n}\n",
    )

    assert runtime.proxy_scope() == "off"


@pytest.mark.feature("proxy")
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


OVERLAY_NETWORK = {
    "mode": "router",
    "interfaces": [
        {"name": "enp2s0", "role": "wan"},
        {"name": "enp1s0", "role": "lan", "lan": {"address": "192.168.100.1"}},
    ],
    "overlays": [{"provider": "netbird", "is_exposed": True}],
}


@pytest.mark.feature("proxy")
def test_the_diverted_overlay_reads_beside_the_lan(monkeypatch, tmp_path):
    """The interfaces the forwarded tproxy takes from are the set on the
    line before it; which of them are overlays is the network's to say."""
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(is_overlay_proxy_enabled=True),
        ruleset='        iifname != { "enp1s0", "wt0" } return\n' + LAN_DIVERSION,
        network=OVERLAY_NETWORK,
    )

    assert runtime.proxy_scope() == "lan+overlay"


@pytest.mark.feature("proxy")
def test_the_overlay_alone_reads_as_overlay(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing(is_proxy_enabled=False, is_overlay_proxy_enabled=True),
        ruleset='        iifname != { "wt0" } return\n' + LAN_DIVERSION + HUB_DIVERSION,
        network=OVERLAY_NETWORK,
    )

    assert runtime.proxy_scope() == "overlay+hub"


SERVED_INTERFACES = [
    {"name": "enp2s0", "role": "wan"},
    {"name": "enp1s0", "role": "lan", "lan": {"address": "192.168.100.1"}},
]
NETBIRD_EXPOSED = [{"provider": "netbird", "is_enabled": True, "is_exposed": True}]
EASYTIER_EXPOSED = [{"provider": "easytier", "is_enabled": True, "is_exposed": True}]
NETBIRD_CLOSED = [{"provider": "netbird", "is_enabled": True, "is_exposed": False}]
LAN = {"is_proxy_enabled": True}
OVERLAY = {"is_overlay_proxy_enabled": True}
HUB = {"is_local_proxy_enabled": True}
SERVER = {"mode": "server", "interfaces": [{"name": "enp1s0"}]}
ROUTER = {"mode": "router", "interfaces": SERVED_INTERFACES}
SIDE_GATEWAY = {"mode": "side_gateway", "interfaces": SERVED_INTERFACES[1:]}


def switches(*scopes: dict) -> dict:
    """The routing options with the scopes named on and every other off."""
    routing = {
        "is_proxy_enabled": False,
        "is_overlay_proxy_enabled": False,
        "is_local_proxy_enabled": False,
    }
    for scope in scopes:
        routing.update(scope)
    return routing


@pytest.mark.feature("proxy")
@pytest.mark.parametrize(
    ("network", "overlays", "routing", "scope"),
    [
        (ROUTER, [], switches(LAN), "lan"),
        (SIDE_GATEWAY, [], switches(LAN), "lan"),
        (ROUTER, [], switches(LAN, HUB), "lan+hub"),
        (ROUTER, NETBIRD_EXPOSED, switches(OVERLAY), "overlay"),
        (SIDE_GATEWAY, NETBIRD_EXPOSED, switches(OVERLAY), "overlay"),
        (SERVER, NETBIRD_EXPOSED, switches(OVERLAY), "overlay"),
        (SERVER, EASYTIER_EXPOSED, switches(OVERLAY), "overlay"),
        (ROUTER, NETBIRD_EXPOSED, switches(LAN, OVERLAY), "lan+overlay"),
        (SERVER, NETBIRD_EXPOSED, switches(OVERLAY, HUB), "overlay+hub"),
        (ROUTER, NETBIRD_EXPOSED, switches(LAN, OVERLAY, HUB), "lan+overlay+hub"),
        (SERVER, [], switches(HUB), "hub"),
        (ROUTER, [], switches(HUB), "hub"),
        (ROUTER, [], switches(OVERLAY), "unused"),
        (SERVER, [], switches(OVERLAY), "unused"),
        (SERVER, NETBIRD_CLOSED, switches(OVERLAY), "unused"),
        (SERVER, [], switches(LAN), "unused"),
        (SERVER, NETBIRD_EXPOSED, switches(), "off"),
    ],
)
def test_the_ruleset_rendered_for_each_scope_reads_back(
    monkeypatch, tmp_path, network, overlays, routing, scope
):
    network = {**network, "overlays": overlays}
    ruleset = RouterNftRenderer(
        network=RouterNetworkConfig.from_dict(network),
        routing=routing,
        xray_uid=999,
        exposure=FirewallExposure(),
    ).render()
    runtime = runtime_with(
        monkeypatch, tmp_path, routing=routing, ruleset=ruleset, network=network
    )

    assert runtime.proxy_scope() == scope


@pytest.mark.feature("proxy")
@pytest.mark.parametrize(
    ("overlays", "routing", "scope"),
    [
        ([], switches(HUB), "hub"),
        ([], switches(OVERLAY), "hub"),
        (NETBIRD_EXPOSED, switches(OVERLAY), "overlay+hub"),
        (NETBIRD_EXPOSED, switches(OVERLAY, HUB), "overlay+hub"),
        (NETBIRD_EXPOSED, switches(), "off"),
    ],
)
def test_outside_linux_the_overlay_switch_alone_takes_the_machine(
    monkeypatch, tmp_path, overlays, routing, scope
):
    """The two scopes share one TUN, and its routes are the machine's."""
    runtime = runtime_with(
        monkeypatch,
        tmp_path,
        routing=routing,
        ruleset=None,
        network={**SERVER, "overlays": overlays},
    )
    monkeypatch.setattr(runtime_module, "is_linux", lambda: False)

    assert runtime.proxy_scope() == scope


@pytest.mark.feature("proxy")
def test_the_notice_shows_for_every_scope_that_takes_traffic():
    notice = (FRONTEND_SRC_DIR / "components/dead_exits_notice.tsx").read_text(
        encoding="utf-8"
    )
    assert (
        'latestFrame.proxy_scope !== "off" && latestFrame.proxy_scope !== "unused";'
    ) in notice
    strip = (FRONTEND_SRC_DIR / "proxy_status.ts").read_text(encoding="utf-8")
    for word in ("lan", "overlay", "hub"):
        assert f'{word}: "state.{word}",' in strip


@pytest.mark.feature("proxy")
@pytest.mark.parametrize("page", ["dashboard_page.tsx", "proxy_page.tsx"])
def test_each_page_reads_the_notice_s_fallback_from_the_frame(page):
    source = " ".join(
        (FRONTEND_SRC_DIR / "pages" / page).read_text(encoding="utf-8").split()
    )
    assert "<DeadExitsNotice" in source
    assert "isFallingBack={latestFrame?.exit_tag === DIRECT_EXIT_TAG}" in source


@pytest.mark.feature("proxy")
def test_the_panel_s_direct_exit_is_the_tag_the_hub_falls_back_to():
    from neutrino_hub.modules.xray.constants import XRAY_DIRECT_TAG

    strip = (FRONTEND_SRC_DIR / "proxy_status.ts").read_text(encoding="utf-8")
    assert f'export const DIRECT_EXIT_TAG = "{XRAY_DIRECT_TAG}";' in strip


@pytest.mark.feature("proxy")
def test_the_notice_s_tone_and_words_follow_the_fallback():
    notice = " ".join(
        (FRONTEND_SRC_DIR / "components/dead_exits_notice.tsx")
        .read_text(encoding="utf-8")
        .split()
    )
    assert 'notice--${isFallingBack ? "warn" : "error"}' in notice
    assert (
        'isFallingBack ? t("ui.proxy.dead_exits_fallback") : t("ui.proxy.dead_exits")'
    ) in notice


@pytest.mark.feature("proxy")
@pytest.mark.parametrize("language", sorted(DEAD_EXITS_WORDS))
def test_the_notice_s_words_in_both_languages(language):
    catalog = json.loads(
        (FRONTEND_SRC_DIR / "locales" / language / "network.json").read_text(
            encoding="utf-8"
        )
    )
    for key, words in DEAD_EXITS_WORDS[language].items():
        assert catalog[key] == words


def test_a_tree_without_the_proxy_is_off(monkeypatch, tmp_path):
    runtime = runtime_with(
        monkeypatch, tmp_path, routing=routing(), ruleset=LAN_DIVERSION
    )
    runtime.proxy = None

    assert runtime.proxy_scope() == "off"
