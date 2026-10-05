"""Where the panel names the hub's address, held against a client's forward.

A page opened through a client's Panel button is on the client's own
loopback, at a port the client chose. An address built from the page's host
and one of the hub's ports names the client's machine, not the hub, so every
such address goes through ``origins.ts``, which names the hub by a
placeholder on such a page and marks the page's own address as the one in
use. A foreign port on a loopback host is a client's Panel button, which the
hub serves on its HTTP port whatever the HTTPS setting, so the HTTPS card
tells that person the button goes on working; any other host on a foreign
port is a port forward, told which port the forward must reach.
"""

import json
import re
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
ORIGINS = FRONTEND_SRC_DIR / "origins.ts"
HTTPS_PANEL = FRONTEND_SRC_DIR / "components/https_panel.tsx"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"

# An address put together from the page's own host.
HOST_ADDRESS = re.compile(r"://\$\{window\.location\.hostname\}")


def sources() -> list:
    """Every TypeScript source of the panel."""
    return sorted(
        path
        for pattern in ("*.ts", "*.tsx")
        for path in FRONTEND_SRC_DIR.rglob(pattern)
    )


def test_no_page_builds_an_address_from_its_own_host():
    built = [
        path.relative_to(FRONTEND_SRC_DIR).as_posix()
        for path in sources()
        if HOST_ADDRESS.search(path.read_text(encoding="utf-8"))
    ]

    assert built == []


def test_a_page_off_the_panels_ports_names_the_hub_by_a_placeholder():
    origins = ORIGINS.read_text(encoding="utf-8")

    assert "export function isOffPanelPort(" in origins
    assert (
        "pagePort !== (isOnHttps ? ports.https_listen_port : ports.listen_port)"
        in origins
    )
    assert 'isForwarded ? t("ui.api.hub_address") : window.location.hostname' in (
        origins
    )


def test_only_a_loopback_host_off_the_panels_ports_is_a_clients():
    origins = ORIGINS.read_text(encoding="utf-8")

    assert 'const LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "[::1]"];' in origins
    assert 'const LOOPBACK_SUFFIX = ".localhost";' in origins
    assert "return isLoopbackHost && isOffPanelPort(ports);" in origins


def test_the_https_card_tells_a_client_page_from_a_port_forward():
    card = HTTPS_PANEL.read_text(encoding="utf-8")

    assert "const isClientPage = isThroughClient(view);" in card
    assert '? t("ui.settings.https_client_kept")' in card
    assert '"ui.settings.https_forwarded"' in card
    assert "if (isForwarded && !isClientPage) {" in card


def test_the_https_card_marks_the_pages_own_address_through_a_client():
    card = HTTPS_PANEL.read_text(encoding="utf-8")

    assert "{ origin: window.location.origin, isCurrent: true }" in card
    assert '"ui.settings.https_through_client"' in card


@pytest.mark.parametrize(
    "language, file_name, key, word",
    [
        ("en", "devices.json", "ui.api.hub_address", "<hub address>"),
        ("zh-CN", "devices.json", "ui.api.hub_address", "<中枢地址>"),
        ("en", "settings.json", "ui.settings.https_through_client", "through a client"),
        ("zh-CN", "settings.json", "ui.settings.https_through_client", "经客户端"),
        (
            "en",
            "settings.json",
            "ui.settings.https_client_kept",
            "This page comes through a client's Panel button, which goes on"
            " working when HTTPS is switched on or off.",
        ),
        (
            "zh-CN",
            "settings.json",
            "ui.settings.https_client_kept",
            "这个页面经客户端的「面板」按钮打开。开启或关闭 HTTPS 后，这个按钮照常可用。",
        ),
    ],
)
def test_the_words_name_the_hub_and_the_client(language, file_name, key, word):
    catalog = json.loads((LOCALES_DIR / language / file_name).read_text("utf-8"))

    assert catalog[key] == word
