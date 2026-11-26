"""The AI page's Models panel, held against ui_text.md and the hub's bounds.

What these pin: every word of the panel says what ui_text.md writes in both
languages; the panel reads ``/hub/ai/model`` again at each ``ai_usage`` and
each ``config`` event; the lengths and the prices are one draft behind one
bar written with one ``model/set``; a length field outside the hub's least
and most set length shows ``code.context_length_invalid``, and a price
number out of range or a pair half empty shows ``code.price_invalid``, each
disabling the bar; a length or a price equal to the default is written as
null; an Ollama row has no price field, and its machines link to the
machine page's Ollama tab with its panels open; and the panel stands after
Accounts and before Access.
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
PANEL_PATH = FRONTEND_SRC_DIR / "components/ai_models_panel.tsx"
PAGE_PATH = FRONTEND_SRC_DIR / "pages/ai_page.tsx"
UI_TEXT = HUB_DIR.parent / "skills/core-code-author/design/ui_text.md"
# The keys of the panel's words in ui_text.md.
PANEL_KEY_PATTERN = re.compile(
    r"^(ui\.ai\.(models_|context_|price_|currency_|no_price)"
    r"|code\.(context_length_invalid|price_invalid|currency_invalid))"
)
# The prices a person may set, as ai.md's "A price a person sets" bounds them.
PRICE_MIN = 0
PRICE_MAX = 10000


def ui_text_words() -> dict:
    """The panel's words as ui_text.md writes them, by language and key."""
    words = {"en": {}, "zh-CN": {}}
    for line in UI_TEXT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        keys = re.findall(r"`([a-z_.]+)`", cells[0])
        if not keys or not all(PANEL_KEY_PATTERN.match(key) for key in keys):
            continue
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

    assert len(words) == 24
    for key, sentence in words.items():
        assert catalog[key] == sentence


def test_every_word_the_panel_uses_is_written_in_ui_text():
    used = set(re.findall(r'"((?:ui\.ai|code)\.[a-z_]+)"', panel_source()))

    assert used <= set(ui_text_words()["en"])
    for key in (
        "ui.ai.models_title",
        "ui.ai.price_col_input",
        "ui.ai.price_unit",
        "ui.ai.price_reset",
        "ui.ai.currency_cny",
        "ui.ai.models_apply",
        "code.price_invalid",
    ):
        assert key in used


def test_the_panel_reads_the_models_again_at_each_ai_usage_and_config_event():
    source = panel_source()

    assert 'const MODEL_PATH = "/hub/ai/model";' in source
    assert 'const MODEL_SET_PATH = "/hub/ai/model/set";' in source
    assert (
        "const MODEL_INVALIDATE_ON = [ { type: HUB_EVENT_AI_USAGE }, "
        "{ type: HUB_EVENT_CONFIG }, ];"
    ) in source


def test_the_lengths_and_the_prices_are_one_draft_written_by_one_bar():
    source = panel_source()

    assert source.count("useDraft(") == 1
    assert source.count("<ApplyBar") == 1
    assert "const isDirty = lengthChanged.length > 0 || priceChanged.length > 0;" in (
        source
    )
    assert "apiPost<AiModelResponse>(MODEL_SET_PATH, { lengths, prices })" in source
    assert 'label={t("ui.ai.models_apply")}' in source
    assert 'hint={t("ui.ai.models_apply_hint")}' in source


def test_a_length_outside_the_hub_s_bounds_shows_the_refusal_and_disables_the_bar():
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


def test_a_price_out_of_range_or_half_empty_shows_the_refusal():
    source = panel_source()

    assert f"const PRICE_MIN = {PRICE_MIN};" in source
    assert f"const PRICE_MAX = {PRICE_MAX:_};" in source
    assert r"const PRICE_PATTERN = /^\d+(\.\d{1,6})?$/;" in source
    assert 't("code.price_invalid", { min: PRICE_MIN, max: PRICE_MAX })' in source
    # Both empty pass on a name with no default alone; one empty never passes.
    assert (
        'if (text.input.trim() === "" && text.output.trim() === "") { '
        "return row.default_price === null ? null : undefined; }"
    ) in source
    assert "if (input === null || output === null) { return undefined; }" in source
    assert "draftPrice(row, textOf(row)) !== undefined" in source


def test_a_price_equal_to_the_default_is_written_as_null():
    source = panel_source()

    assert (
        "prices[row.model] = price === null || isDefaultPrice(row, price) ? null : price;"
        in source
    )
    assert (
        "fallback !== null && price.input === fallback.input && "
        "price.output === fallback.output && price.currency === fallback.currency"
    ) in source


def test_an_ollama_row_has_no_price_field():
    source = panel_source()
    ollama_row = source[source.index("function OllamaModelRow(") :]
    ollama_row = ollama_row[: ollama_row.index("interface SourceChipsProps")]

    assert "<input" not in ollama_row
    assert "price" not in ollama_row
    assert "<Picker" not in ollama_row


def test_an_ollama_machine_links_to_its_ollama_tab_with_its_panels_open():
    assert (
        "return `/agents/${encodeURIComponent(deviceId)}?module=ollama&configure=1`;"
        in panel_source()
    )


def test_the_panel_stands_after_accounts_and_before_access():
    page = " ".join(PAGE_PATH.read_text(encoding="utf-8").split())

    accounts = page.index("<AiAccountsPanel />")
    models = page.index("<AiModelsPanel />")
    access = page.index("<AiAccessPanel")
    assert accounts < models < access
