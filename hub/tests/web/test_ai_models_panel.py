"""The AI page's Models panel, held against ui_text.md and the hub's bounds.

What these pin: every word of the panel says what ui_text.md writes in both
languages; the panel reads ``/hub/ai/model`` again at each ``ai_usage`` and
each ``config`` event; a cloud row holds the name, the sources, the
read-only length and **Configure**, and the panel has no apply bar; the
dialog holds the length and the prices, and its **Save** writes
``model/set`` for its one name, a length or a price equal to the default
written as null, and is disabled with nothing changed; a length outside the
hub's least and most set length shows ``code.context_length_invalid``, and
a price number out of range or a pair half empty shows ``code.price_invalid``;
an Ollama row has no **Configure**, and its machines link to the machine
page's Ollama tab with its panels open; and the panel stands after Accounts
and before Access.
"""

import json
import re
from pathlib import Path

import pytest

from neutrino_hub.modules.ai.constants import (
    AI_CONTEXT_LENGTH_MAX,
    AI_CONTEXT_LENGTH_MIN,
    AI_PRICE_MAX,
    AI_PRICE_MIN,
)

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
PANEL_PATH = FRONTEND_SRC_DIR / "components/ai_models_panel.tsx"
PAGE_PATH = FRONTEND_SRC_DIR / "pages/ai_page.tsx"
UI_TEXT = HUB_DIR.parent / "skills/core-code-author/design/ui_text.md"
# The keys of the panel's words in ui_text.md.
PANEL_KEY_PATTERN = re.compile(
    r"^(ui\.ai\.(models_|model_|context_|price_|currency_|no_price|details_|source_)"
    r"|code\.(context_length_invalid|price_invalid|currency_invalid))"
)


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


def part(start: str, end: str) -> str:
    """The panel's source from one marker to the next."""
    source = panel_source()
    begin = source.index(start)
    return source[begin : source.index(end, begin)]


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_every_word_of_the_panel_says_what_ui_text_writes(language):
    words = ui_text_words()[language]
    catalog = worded(language)

    assert len(words) == 33
    for key, sentence in words.items():
        assert catalog[key] == sentence


def test_every_word_the_panel_uses_is_written_in_ui_text():
    used = set(re.findall(r'"((?:ui\.ai|code)\.[a-z_]+)"', panel_source()))

    assert used <= set(ui_text_words()["en"]) | {"ui.ai.cancel", "ui.ai.saving"}
    for key in (
        "ui.ai.models_title",
        "ui.ai.model_configure",
        "ui.ai.model_configure_title",
        "ui.ai.model_context_length",
        "ui.ai.price_input",
        "ui.ai.price_unit",
        "ui.ai.price_reset",
        "ui.ai.currency_cny",
        "ui.ai.model_save",
        "ui.ai.model_details",
        "ui.ai.model_details_title",
        "ui.ai.details_api_value",
        "ui.ai.details_price",
        "ui.ai.source_account",
        "ui.ai.source_provider",
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


def test_a_cloud_row_holds_the_name_the_sources_the_length_and_configure():
    row = part("{cloud.map((row) => (", "{ollama.map(")

    assert '<span className="ai_models_model mono" title={row.model}>' in row
    assert "<SourceChips sources={row.sources} />" in row
    assert '<span className="ai_models_value mono">{lengthOf(row)}</span>' in row
    assert 't("ui.ai.model_configure")' in row
    assert "setConfiguring(row.model);" in row
    assert "{detailsButton(row.model)}" in row
    assert "<input" not in row


def test_the_panel_has_no_apply_bar_and_no_draft():
    source = panel_source()

    assert "ApplyBar" not in source
    assert "useDraft" not in source


def test_save_writes_the_one_name_with_defaults_as_null():
    dialog = part("function ModelDialog(", "interface ModelDetailsDialogProps")

    assert (
        "update.lengths = { [row.model]: length === row.default_context_length "
        "? null : length, };"
    ) in dialog
    assert (
        "update.prices = { [row.model]: price === null || isDefaultPrice(row, price) "
        "? null : price, };"
    ) in dialog
    assert "if (isLengthChanged(row, text)) {" in dialog
    assert "if (isPriceChanged(row, text)) {" in dialog
    assert "onSaved(await apiPost<AiModelResponse>(MODEL_SET_PATH, update));" in dialog
    assert (
        "disabled={!isChanged || !isLengthValid || !isPriceValid || isSaving}" in dialog
    )
    assert (
        "fallback !== null && price.input === fallback.input && "
        "price.output === fallback.output && price.currency === fallback.currency"
    ) in panel_source()


def test_cancel_escape_and_the_backdrop_write_nothing():
    source = panel_source()
    dialog = part("function ModelDialog(", "interface ModelDetailsDialogProps")

    assert "<DialogFrame" in dialog
    assert "hasHeadClose={false} onClose={onCancel}" in dialog
    assert "onCancel={() => { setConfiguring(null); }}" in source
    assert 't("ui.ai.cancel")' in dialog


def test_a_length_outside_the_hub_s_bounds_shows_the_refusal():
    source = panel_source()

    assert f"const CONTEXT_LENGTH_MIN = {AI_CONTEXT_LENGTH_MIN};" in source
    assert f"const CONTEXT_LENGTH_MAX = {AI_CONTEXT_LENGTH_MAX:_};" in source
    assert (
        't("code.context_length_invalid", { min: CONTEXT_LENGTH_MIN, '
        "max: CONTEXT_LENGTH_MAX, })"
    ) in source


def test_a_price_out_of_range_or_half_empty_shows_the_refusal():
    source = panel_source()

    assert f"const PRICE_MIN = {AI_PRICE_MIN};" in source
    assert f"const PRICE_MAX = {AI_PRICE_MAX:_};" in source
    assert r"const PRICE_PATTERN = /^\d+(\.\d{1,6})?$/;" in source
    assert 't("code.price_invalid", { min: PRICE_MIN, max: PRICE_MAX })' in source
    # Both empty pass on a name with no default alone; one empty never passes.
    assert (
        'if (text.input.trim() === "" && text.output.trim() === "") { '
        "return row.default_price === null ? null : undefined; }"
    ) in source
    assert "if (input === null || output === null) { return undefined; }" in source


def test_an_ollama_row_has_details_and_no_configure():
    ollama_row = part("{ollama.map((row) => (", "{configured !== null")

    assert "{detailsButton(row.model)}" in ollama_row
    assert "model_configure" not in ollama_row
    assert "<input" not in ollama_row
    assert "price" not in ollama_row


def test_details_stands_in_one_column_on_every_row():
    style = " ".join(
        (FRONTEND_SRC_DIR / "components/ai_models_panel.css")
        .read_text(encoding="utf-8")
        .split()
    )

    assert ".ai_models_configure { grid-column: 5; }" in style
    assert ".ai_models_details { grid-column: 6; }" in style
    # The name as wide as the longest, the room left before the buttons.
    assert (
        "grid-template-columns: minmax(12ch, max-content) minmax(0, max-content) "
        "max-content minmax(0, 1fr) max-content max-content;"
    ) in style
    assert "max-width: 36ch;" in style


def test_the_details_dialog_reads_the_activity_range_and_edits_nothing():
    dialog = part("function ModelDetailsDialog(", "interface FigureProps")
    page = " ".join(PAGE_PATH.read_text(encoding="utf-8").split())

    assert "<AiModelsPanel range={range} />" in page
    assert "useApiResource<AiUsageResponse>(apiPath(USAGE_PATH, { range }))" in dialog
    assert "t(RANGE_WORD_KEYS[range])" in dialog
    assert "<DialogFrame" in dialog
    assert "hasHeadClose" not in dialog
    assert "apiPost" not in dialog
    assert 'const OLLAMA_UPSTREAM_PREFIX = "ollama:";' in panel_source()
    assert "OLLAMA_UPSTREAM_PREFIX + machine.device_id" in dialog
    assert "counters={upstreams.get(source.id)}" in dialog


def test_the_details_figures_and_boxes():
    dialog = part("function ModelDetailsDialog(", "interface FigureProps")
    source_box = part("function SourceBox(", "interface MachineBoxProps")
    machine_box = part("function MachineBox(", "/** A box's requests")

    assert 't("ui.usage.header_requests")' in dialog
    assert "{hasAmount(row?.api_value) && (" in dialog
    assert '{cloud !== null && ( <Figure label={t("ui.ai.details_price")}' in (dialog)
    assert 'source.price === null ? t("ui.ai.no_price")' in source_box
    assert 't("ui.ai.context_setting", {' in machine_box
    assert 'value === length ? "ai_model_box_in_force" : "faint"' in machine_box
    assert "price" not in machine_box


def test_an_ollama_machine_links_to_its_ollama_tab_with_its_panels_open():
    assert (
        "return `/agents/${encodeURIComponent(deviceId)}?module=ollama&configure=1`;"
        in panel_source()
    )


def test_the_panel_stands_after_accounts_and_before_access():
    page = " ".join(PAGE_PATH.read_text(encoding="utf-8").split())

    accounts = page.index("<AiAccountsPanel />")
    models = page.index("<AiModelsPanel")
    access = page.index("<AiAccessPanel")
    assert accounts < models < access
