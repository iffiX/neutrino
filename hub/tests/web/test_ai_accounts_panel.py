"""The AI page's Accounts panel, held against ui_behavior.md and ui_text.md.

What these pin: the account rows' words say what ui_text.md writes in both
languages; every row is a subgrid of one grid, the service, the identity,
the counts, the status and the three buttons each in a column the rows
share; Pause and Resume keep one width; the windows start under the
identity, each a cell of one width with its reset time in a short form and
the full time as its title; and the panel's two narrower layouts switch at
the widths ui_behavior.md names.
"""

import json
import re
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
PANEL_PATH = FRONTEND_SRC_DIR / "components/ai_accounts_panel.tsx"
STYLE_PATH = FRONTEND_SRC_DIR / "components/ai_accounts_panel.css"
DESIGN_DIR = HUB_DIR.parent / "skills/core-code-author/design"
UI_TEXT = DESIGN_DIR / "ui_text.md"
UI_BEHAVIOR = DESIGN_DIR / "ui_behavior.md"
# The account rows' words in ui_text.md.
ROW_KEY_PATTERN = re.compile(
    r"^(state\.paused|ui\.ai\.(limited_until|plan|plan_until|quota_[a-z0-9]+"
    r"|refresh|pause|resume)|code\.quota_read_[a-z]+)$"
)


def flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def ui_text_words() -> dict:
    """The account rows' words as ui_text.md writes them."""
    words = {"en": {}, "zh-CN": {}}
    for line in UI_TEXT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        keys = re.findall(r"`([a-z_.0-9]+)`", cells[0])
        if not keys or not all(ROW_KEY_PATTERN.match(key) for key in keys):
            continue
        english = cells[1].split(", ") if len(keys) > 1 else [cells[1]]
        chinese = cells[2].split("、") if len(keys) > 1 else [cells[2]]
        for key, en, zh in zip(keys, english, chinese):
            words["en"][key] = en
            words["zh-CN"][key] = zh
    return words


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_the_row_words_say_what_ui_text_writes(language):
    catalog = {}
    for name in ("modules.json", "codes.json"):
        catalog.update(json.loads((LOCALES_DIR / language / name).read_text("utf-8")))
    words = ui_text_words()[language]

    assert len(words) == 15
    for key, sentence in words.items():
        assert catalog[key] == sentence


def test_every_row_shares_the_columns_of_one_grid():
    style = flat(STYLE_PATH)

    assert (
        ".ai_accounts { display: grid; grid-template-columns: max-content "
        "minmax(0, 1fr) max-content max-content max-content max-content "
        "max-content;"
    ) in style
    assert ".ai_account_row { display: grid; grid-column: 1 / -1; " in style
    assert "grid-template-columns: subgrid;" in style
    for selector, column in (
        ("service", "1"),
        ("identity", "2"),
        ("counts", "3"),
        ("status", "4"),
        ("refresh", "5"),
        ("pause", "6"),
        ("delete", "7"),
    ):
        rule = style[style.index(f".ai_account_{selector} {{") :]
        assert f"grid-column: {column};" in rule[: rule.index("}")]


def test_the_counts_are_right_aligned_in_tabular_figures():
    style = flat(STYLE_PATH)
    rule = style[style.index(".ai_account_counts {") :]
    rule = rule[: rule.index("}")]

    assert "justify-self: end;" in rule
    assert "font-variant-numeric: tabular-nums;" in rule


def test_pause_and_resume_keep_one_width():
    source = flat(PANEL_PATH)
    style = flat(STYLE_PATH)

    assert (
        '<span aria-hidden={value.is_disabled}>{t("ui.ai.pause")}</span> '
        '<span aria-hidden={!value.is_disabled}>{t("ui.ai.resume")}</span>'
    ) in source
    assert '.ai_account_pause_words > [aria-hidden="true"] { visibility: hidden; }' in (
        style
    )


def test_the_windows_start_under_the_identity_in_cells_of_one_width():
    source = flat(PANEL_PATH)
    style = flat(STYLE_PATH)

    assert (
        ".ai_account_windows { display: flex; flex-wrap: wrap; grid-column: 2 / 5;"
        in (style)
    )
    assert "width: 92px;" in style
    assert "time: formatShortMoment(window.resets_at)," in source
    assert "time: formatMoment(window.resets_at)," in source
    assert "? formatHourMinute(date) : formatDay(isoTimestamp);" in source
    assert ".ai_account_updated { align-self: center; margin-left: auto;" in style


def test_the_narrow_layouts_switch_at_the_widths_ui_behavior_names():
    style = flat(STYLE_PATH)
    behavior = flat(UI_BEHAVIOR)

    assert ".ai_accounts_group { container: ai_accounts / inline-size; }" in style
    assert "@container ai_accounts (max-width: 860px) {" in style
    assert "@container ai_accounts (max-width: 520px) {" in style
    assert "In a panel under 860 px wide the counts and the status" in behavior
    assert "Under 520 px the label takes the second line whole" in behavior
