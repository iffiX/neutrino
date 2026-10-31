"""The Access page's words for the SSH relay and the two frp ways in.

A frp section words its state from the catalog, so every state the hub
reports has a sentence in both languages. The names on the cards are fixed
ones, and OpenFrp's terms ask for its notice in Chinese word for word.
"""

import json
from pathlib import Path

import pytest

from neutrino_hub.web.constants import WEB_DEFAULT_LANGUAGE, WEB_LANGUAGES

LOCALES_DIR = Path(__file__).resolve().parents[2] / "frontend/src/locales"

# The frp state codes, network.md "The frp states".
FRP_STATES = (
    "disabled",
    "not_signed_in",
    "vault_locked",
    "no_tunnel",
    "loopback_port_taken",
    "config_failed",
    "connecting",
    "connected",
    "proxy_refused",
    "port_closed",
    "login_failed",
    "unreachable",
)


def catalog(language: str, name: str) -> dict:
    """One catalog file's sentences.

    Args:
        language: The language directory.
        name: The file name.

    Returns:
        The parsed object.
    """
    return json.loads((LOCALES_DIR / language / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("state", FRP_STATES)
@pytest.mark.parametrize("language", list(WEB_LANGUAGES))
def test_every_frp_state_has_a_word(language, state):
    assert f"state.frp_{state}" in catalog(language, "network.json")


@pytest.mark.parametrize(
    "language, key, word",
    [
        ("en", "ui.overlay.relay_title", "SSH relay"),
        ("zh-CN", "ui.overlay.relay_title", "SSH 中继"),
        ("en", "ui.overlay.sakurafrp_title", "SakuraFrp"),
        ("zh-CN", "ui.overlay.sakurafrp_title", "SakuraFrp"),
        ("en", "ui.overlay.openfrp_title", "OpenFrp"),
        ("zh-CN", "ui.overlay.openfrp_title", "OpenFrp"),
        ("en", "state.frp_no_tunnel", "Enabled, not connected"),
        ("zh-CN", "state.frp_no_tunnel", "已启用，未连接"),
        (
            "zh-CN",
            "ui.overlay.openfrp_notice",
            "此项目由社区开发，OpenFrp 官方不负责除节点问题以外的技术支持",
        ),
        ("zh-CN", "ui.overlay.openfrp_openapi", "使用 OpenFrp OPENAPI"),
    ],
)
def test_the_access_page_names_its_ways_in(language, key, word):
    assert catalog(language, "network.json")[key] == word


def test_no_english_sentence_capitalises_the_ssh_relay():
    for path in (LOCALES_DIR / WEB_DEFAULT_LANGUAGE).glob("*.json"):
        assert "SSH Relay" not in path.read_text(encoding="utf-8"), path.name


def test_a_tunnel_row_shows_the_tunnel_s_name_beside_its_node():
    panel = " ".join(
        (LOCALES_DIR.parent / "components" / "frp_panels.tsx")
        .read_text(encoding="utf-8")
        .split()
    )

    assert (
        '<span>{t("ui.overlay.frp_name")}</span> '
        '<span>{t("ui.overlay.frp_node")}</span>'
    ) in panel
    assert (
        '<span className="frp_tunnel_name">{tunnel.name}</span> '
        '<span className="frp_tunnel_node">{tunnel.node_name}</span>'
    ) in panel


@pytest.mark.parametrize("language, word", [("en", "Tunnel"), ("zh-CN", "隧道")])
def test_the_tunnel_s_name_column_is_worded(language, word):
    path = LOCALES_DIR / language / "network.json"
    words = json.loads(path.read_text(encoding="utf-8"))

    assert words["ui.overlay.frp_name"] == word
