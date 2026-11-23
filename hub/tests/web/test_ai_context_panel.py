"""The AI page's Context length panel, held against ui_text.md and the hub's bounds.

What these pin: every word of the panel says what ui_text.md writes in both
languages; the panel reads ``/hub/ai/context`` again at each ``ai_usage``
and each ``config`` event; its fields are bounded by the hub's least and
most set length, a field outside them showing ``code.context_length_invalid``
and disabling the bar; a length equal to the default is written as null; an
Ollama name's machines link to the machine page's Ollama tab with its panels
open; and the panel stands after Accounts and before Access.
"""

import json
import re
from pathlib import Path

import pytest

from neutrino_hub.modules.ai.constants import (
    AI_CONTEXT_LENGTH_MAX,
    AI_CONTEXT_LENGTH_MIN,
)

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
PANEL_PATH = FRONTEND_SRC_DIR / "components/ai_context_panel.tsx"
PAGE_PATH = FRONTEND_SRC_DIR / "pages/ai_page.tsx"
UI_TEXT = HUB_DIR.parent / "skills/core-code-author/design/ui_text.md"


def ui_text_words() -> dict:
    """The panel's words as ui_text.md writes them, by language and key."""
    words = {"en": {}, "zh-CN": {}}
    for line in UI_TEXT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `ui.ai.context_") and not line.startswith(
            "| `code.context_length_invalid`"
        ):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        keys = re.findall(r"`([a-z_.]+)`", cells[0])
        english = cells[1].split(", ") if len(keys) > 1 else [cells[1]]
        chinese = cells[2].split("、") if len(keys) > 1 else [cells[2]]
        for key, en, zh in zip(keys, english, chinese):
            words["en"][key] = en
            words["zh-CN"][key] = zh
    return words


def worded(language: str) -> dict:
    found = {}
    for name in ("modules.json", "codes.json"):
        found.update(json.loads((LOCALES_DIR / language / name).read_text("utf-8")))
    return found


def panel_source() -> str:
    return " ".join(PANEL_PATH.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_every_word_of_the_panel_says_what_ui_text_writes(language):
    words = ui_text_words()[language]
    catalog = worded(language)

    assert len(words) == 12
    for key, sentence in words.items():
        assert catalog[key] == sentence


def test_every_word_the_panel_uses_is_written_in_ui_text():
    used = set(
        re.findall(r't\("((?:ui\.ai\.context|code\.context)[a-z_]*)"', panel_source())
    )

    assert used <= set(ui_text_words()["en"])
    assert "ui.ai.context_col_source" in used


def test_the_panel_reads_the_lengths_again_at_each_ai_usage_and_config_event():
    source = panel_source()

    assert 'const CONTEXT_PATH = "/hub/ai/context";' in source
    assert 'const CONTEXT_SET_PATH = "/hub/ai/context/set";' in source
    assert (
        "const CONTEXT_INVALIDATE_ON = [ { type: HUB_EVENT_AI_USAGE }, "
        "{ type: HUB_EVENT_CONFIG }, ];"
    ) in source


def test_a_field_outside_the_hub_s_bounds_shows_the_refusal_and_disables_the_bar():
    source = panel_source()

    assert f"const CONTEXT_LENGTH_MIN = {AI_CONTEXT_LENGTH_MIN};" in source
    assert f"const CONTEXT_LENGTH_MAX = {AI_CONTEXT_LENGTH_MAX:_};" in source
    assert (
        't("code.context_length_invalid", { min: CONTEXT_LENGTH_MIN, '
        "max: CONTEXT_LENGTH_MAX, })"
    ) in source
    assert "isApplyDisabled={!isValid}" in source
    assert (
        "lengths[row.model] = length === row.default_context_length ? null : length;"
        in source
    )


def test_an_ollama_machine_links_to_its_ollama_tab_with_its_panels_open():
    assert (
        "return `/agents/${encodeURIComponent(deviceId)}?module=ollama&configure=1`;"
        in panel_source()
    )


def test_the_panel_stands_after_accounts_and_before_access():
    page = " ".join(PAGE_PATH.read_text(encoding="utf-8").split())

    accounts = page.index("<AiAccountsPanel />")
    context = page.index("<AiContextPanel />")
    access = page.index("<AiAccessPanel")
    assert accounts < context < access
