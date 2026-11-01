"""The AI page's Access words and its Endpoint line, held against ui_text.md.

What these pin: ``ui.ai.access_hint`` and ``ui.ai.keys_empty_hint`` say in both
languages what ui_text.md writes; the Endpoint line, ``ui.ai.port_reached_at``
and ``ui.ai.port_moves_to`` show the address the gateway listens on and never
the panel's host; the panel's comment and the configuration's docstring name
no machine the gateway cannot serve.
"""

import json
from pathlib import Path

import pytest

from neutrino_hub.modules.cliproxyapi.config import CliproxyApiConfig
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_LISTEN_HOST

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
WORDS = {
    "en": {
        "ui.ai.access_hint": "For a tool on the hub's machine, or one using an SSH tunnel to it.",
        "ui.ai.keys_empty_hint": "Generate one for a tool on the hub's machine.",
    },
    "zh-CN": {
        "ui.ai.access_hint": "给中枢这台机器上的工具用，或经 SSH 隧道连到它的工具用。",
        "ui.ai.keys_empty_hint": "给中枢这台机器上的工具生成一个。",
    },
}


def flat(text: str) -> str:
    return " ".join(text.split())


def page() -> str:
    source = FRONTEND_SRC_DIR / "pages" / "ai_page.tsx"
    return flat(source.read_text(encoding="utf-8"))


@pytest.mark.parametrize("language", list(WORDS))
def test_the_access_words_say_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))

    for key, words in WORDS[language].items():
        assert catalog[key] == words


def test_the_endpoint_line_shows_the_address_the_gateway_listens_on():
    text = page()

    assert f'const GATEWAY_HOST = "{CLIPROXYAPI_LISTEN_HOST}";' in text
    assert (
        "function originWith(port: number): string { "
        "return `http://${GATEWAY_HOST}:${port}`; }"
    ) in text
    assert "const endpoint = originWith(view.listen_port);" in text
    assert "<AiAccessPanel endpoint={endpoint}" in text


def test_the_port_field_shows_the_same_address():
    text = page()

    assert 't("ui.ai.port_reached_at", { origin: endpoint })' in text
    assert 't("ui.ai.port_moves_to", { origin: originWith(port ?? 0), })' in text


def test_the_page_never_reads_the_panel_s_host():
    assert "useHubHost" not in page()


def test_the_access_panel_s_comment_names_no_machine_the_gateway_cannot_serve():
    source = FRONTEND_SRC_DIR / "components" / "ai_access_panel.tsx"
    text = source.read_text(encoding="utf-8")
    comment = flat(text[: text.index("*/")].replace("*", ""))

    assert "a tool on the hub's machine, or one using an SSH tunnel to it" in comment
    for word in ("phone", "tablet", "laptop"):
        assert word not in comment


def test_the_configuration_names_the_hub_s_loopback():
    assert (
        "listen_port: Port the AI gateway listens on, on the hub's loopback."
        in flat(CliproxyApiConfig.__doc__)
    )
    assert "LAN" not in CliproxyApiConfig.__doc__


@pytest.mark.parametrize(
    ("language", "key", "words"),
    [
        ("en", "ui.ai.key_default_name", "tool"),
        ("en", "ui.ai.key_name_placeholder", "e.g. my tool"),
        (
            "en",
            "ui.ai.port_apply_warning",
            "A tool set up by hand with a generated key stops reaching the gateway "
            "until its endpoint is changed too.",
        ),
        ("zh-CN", "ui.ai.key_default_name", "工具"),
        ("zh-CN", "ui.ai.key_name_placeholder", "例如 我的工具"),
        (
            "zh-CN",
            "ui.ai.port_apply_warning",
            "手动配置了生成密钥的工具，在地址改过来之前都连不上网关。",
        ),
    ],
)
def test_a_key_s_words_name_a_tool_and_no_other_machine(language, key, words):
    catalog = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    assert json.loads(catalog.read_text(encoding="utf-8"))[key] == words
