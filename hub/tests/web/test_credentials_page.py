"""The token delete dialog, held against ui_behavior.md's "Confirmation".

What these pin: the dialog names each exit node the token keys, joined by
the catalog's separator, and the words in both languages are the ones
ui_text.md writes.
"""

import json
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
UI_TEXT = HUB_DIR.parent / "skills/core-code-author/design/ui_text.md"
WORDS = {
    "en": {
        "ui.credentials.token_delete_node_one": (
            "Node {name} loses this token and is disabled."
        ),
        "ui.credentials.token_delete_nodes": (
            "Nodes {names} lose this token and are disabled."
        ),
        "ui.credentials.name_separator": ", ",
    },
    "zh-CN": {
        "ui.credentials.token_delete_node_one": "节点 {name} 会失去这个令牌并被停用。",
        "ui.credentials.token_delete_nodes": "节点 {names} 会失去这个令牌并被停用。",
        "ui.credentials.name_separator": "、",
    },
}


def flat(name: str) -> str:
    """One frontend file with its whitespace folded to single spaces."""
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("language", list(WORDS))
def test_the_words_say_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "devices.json"
    words = json.loads(path.read_text(encoding="utf-8"))

    for key, word in WORDS[language].items():
        assert words[key] == word


def test_ui_text_writes_the_node_sentences_in_both_languages():
    text = UI_TEXT.read_text(encoding="utf-8")

    for key in (
        "ui.credentials.token_delete_node_one",
        "ui.credentials.token_delete_nodes",
    ):
        assert f"| {WORDS['en'][key]} | {WORDS['zh-CN'][key]} |" in text, key


def test_a_token_view_carries_the_names_of_its_nodes():
    types = flat("api_types.ts")
    token = types.split("export interface TokenView {", 1)[1].split("}", 1)[0]

    assert "node_names: string[];" in token


def test_the_dialog_names_each_node_the_token_keys():
    page = flat("pages/credentials_page.tsx")

    assert "body: tokenDeleteBody(value.provider_count, value.node_names)," in page
    assert (
        'nodeNames.length === 1 ? t("ui.credentials.token_delete_node_one", { '
        'name: nodeNames[0] ?? "", }) : t("ui.credentials.token_delete_nodes", { '
        'names: nodeNames.join(t("ui.credentials.name_separator")), }),'
    ) in page
