"""The AI page's Activity panel, held against ui_behavior.md and ui_text.md.

What these pin: the dashboard's range chips start at month and pick one
range for the three tables; each table ends with a **Cost** column drawn by
one cell; amounts read per currency, USD first, joined by `` + `` and never
added, under a cent as ``<$0.01``; a row of unpriced requests alone reads
``ui.usage.no_price``, and the API value stands apart and never inside the
cost; a model-unknown row has no cost; today's line carries today's cost and
its API value; and the words say what ui_text.md writes in both languages.
"""

import json
import re
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
UI_TEXT = HUB_DIR.parent / "skills/core-code-author/design/ui_text.md"
# The Activity panel's words in ui_text.md, by the keys of each row.
ACTIVITY_KEYS = {
    "ui.ai.cost_today",
    "ui.ai.api_value_today",
    "ui.ai.view_models",
    "ui.usage.header_cost",
    "ui.usage.header_model",
    "ui.usage.api_value",
    "ui.usage.no_price",
    "ui.usage.unpriced_requests",
    "ui.usage.model_unknown",
    "ui.usage.models_empty",
}


def flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def page() -> str:
    return flat(FRONTEND_SRC_DIR / "pages/ai_page.tsx")


def component(name: str) -> str:
    return flat(FRONTEND_SRC_DIR / "components" / name)


def ui_text_words() -> dict:
    """The Activity panel's words as ui_text.md writes them."""
    words = {"en": {}, "zh-CN": {}}
    for line in UI_TEXT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        keys = re.findall(r"`([a-z_.]+)`", cells[0])
        if not keys or not set(keys) <= ACTIVITY_KEYS:
            continue
        english = cells[1].split(", ") if len(keys) > 1 else [cells[1]]
        chinese = cells[2].split("、") if len(keys) > 1 else [cells[2]]
        for key, en, zh in zip(keys, english, chinese):
            words["en"][key] = en
            words["zh-CN"][key] = zh
    return words


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_the_words_say_what_ui_text_writes(language):
    catalog = json.loads((LOCALES_DIR / language / "modules.json").read_text("utf-8"))
    words = ui_text_words()[language]

    assert set(words) == ACTIVITY_KEYS
    for key, sentence in words.items():
        assert catalog[key] == sentence


def test_the_range_chips_start_at_month_and_feed_the_three_tables():
    source = page()

    assert 'const RANGE_START: AiUsageRange = "month";' in source
    for range_key in ("day", "week", "month", "year"):
        assert (
            f'{{ value: "{range_key}", labelKey: "ui.usage.range_{range_key}" }}'
            in (source)
        )
    assert "<RangeSwitch" in source
    assert "useState<AiUsageRange>(RANGE_START)" in source
    assert "apiPath(USAGE_PATH, { range })" in source
    assert source.count("useApiResource<AiUsageResponse>(") == 1
    assert "<AiUsageProviders providers={usage.data.providers} />" in source
    assert "<AiUsageKeys keys={usage.data.keys} />" in source
    assert "<AiUsageModels models={usage.data.models} />" in source
    assert 't("ui.ai.view_models")' in source


@pytest.mark.parametrize(
    "name", ["ai_usage_providers.tsx", "ai_usage_keys.tsx", "ai_usage_models.tsx"]
)
def test_each_table_ends_with_the_cost_column(name):
    source = component(name)
    head = source[source.index("<thead>") : source.index("</thead>")]

    assert (
        head.strip()
        .removesuffix("</tr>")
        .strip()
        .endswith('<th className="num">{t("ui.usage.header_cost")}</th>')
    )
    assert "<AiUsageCost counters=" in source


def test_amounts_read_per_currency_usd_first_and_are_never_added():
    source = flat(FRONTEND_SRC_DIR / "ai_usage.ts")

    assert 'const CURRENCY_SIGNS: Record<string, string> = { USD: "$", CNY: "¥" };' in (
        source
    )
    assert 'const CURRENCY_ORDER = ["USD", "CNY"];' in source
    assert "const AMOUNT_UNITS = 1_000_000;" in source
    assert "const AMOUNT_LEAST = 0.01;" in source
    assert '.join(" + ");' in source
    assert (
        "? `<${sign}${AMOUNT_LEAST.toFixed(2)}` : `${sign}${amount.toFixed(2)}`;"
        in (source)
    )
    assert ".filter(([, value]) => value > 0)" in source


def test_the_cost_cell_keeps_the_api_value_apart_and_words_a_missing_price():
    source = component("ai_usage_cost.tsx")

    assert "const cost = formatAmounts(counters.cost);" in source
    assert "const apiValue = formatAmounts(counters.api_value);" in source
    assert 't("ui.usage.api_value", { amount: apiValue })' in source
    assert (
        'return hasUnpriced ? ( <span className="usage_cost_note faint">'
        '{t("ui.usage.no_price")}</span> ) : null;'
    ) in source
    assert (
        't("ui.usage.unpriced_requests", { count: counters.unpriced_requests, })'
        in (source)
    )
    assert "addAmounts" not in source
    assert "counters.cost + " not in source


def test_a_model_unknown_row_has_no_cost():
    source = component("ai_usage_models.tsx")

    assert "const isUnknown = row.model.length === 0;" in source
    assert 't("ui.usage.model_unknown")' in source
    assert "{!isUnknown && <AiUsageCost counters={row} />}" in source
    assert 't("ui.usage.models_empty")' in source


def test_today_s_line_carries_today_s_cost_and_its_api_value():
    source = page()

    assert "const costToday = formatAmounts(view.cost_today);" in source
    assert '{costToday === "" ? "—" : costToday}' in source
    assert 't("ui.ai.cost_today")' in source
    assert "hasAmount(view.api_value_today) && (" in source
    assert "formatAmounts(view.api_value_today)" in source
    assert 't("ui.ai.api_value_today")' in source
