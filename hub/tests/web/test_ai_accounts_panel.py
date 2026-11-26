"""The AI page's Accounts panel, held against ui_behavior.md and ui_text.md.

What these pin: the account rows' words say what ui_text.md writes in both
languages; every card is a subgrid of one grid, the service, the label with
the windows under it, and the three right-aligned lines each in a column the
cards share; the buttons at the card's foot, right-aligned; Pause and
Resume keep one width; each window a cell of one width with its reset time
in a short form and the full time as its title; and the card stacking under
the width ui_behavior.md names.
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


def rule(style: str, selector: str) -> str:
    """One rule's body in the flattened style sheet."""
    body = style[style.index(f"{selector} {{") :]
    return body[: body.index("}")]


def test_every_card_shares_the_columns_of_one_grid():
    style = flat(STYLE_PATH)

    assert (
        ".ai_accounts { display: grid; grid-template-columns: max-content "
        "minmax(0, 1fr) max-content;"
    ) in style
    assert "grid-template-columns: subgrid;" in rule(style, ".ai_account_row")
    assert "grid-column: 1;" in rule(style, ".ai_account_service")
    assert "grid-column: 2;" in rule(style, ".ai_account_identity")
    assert "grid-column: 2;" in rule(style, ".ai_account_windows")
    assert "grid-column: 3;" in rule(style, ".ai_account_side")


def test_the_three_lines_are_right_aligned_at_the_card_s_right():
    source = flat(PANEL_PATH)
    style = flat(STYLE_PATH)
    side = source[source.index('<span className="ai_account_side">') :]
    side = side[: side.index("{value.windows.length > 0 && (")]

    assert side.index("ai_account_counts") < side.index("ai_account_status")
    assert side.index("ai_account_status") < side.index("ui.ai.quota_updated")
    assert "align-items: flex-end;" in rule(style, ".ai_account_side")
    assert "font-variant-numeric: tabular-nums;" in rule(style, ".ai_account_counts")


def test_the_buttons_sit_at_the_card_s_foot_right_aligned():
    source = flat(PANEL_PATH)
    style = flat(STYLE_PATH)

    assert source.index('<span className="ai_account_actions">') > source.index(
        '<div className="ai_account_windows">'
    )
    actions = rule(style, ".ai_account_actions")
    assert "grid-column: 1 / -1;" in actions
    assert "justify-content: flex-end;" in actions


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


def test_each_window_is_a_cell_of_one_width_with_its_short_reset_time():
    source = flat(PANEL_PATH)
    style = flat(STYLE_PATH)

    assert "width: 92px;" in rule(style, ".ai_account_window")
    assert "time: formatShortMoment(window.resets_at)," in source
    assert "time: formatMoment(window.resets_at)," in source
    assert "? formatHourMinute(date) : formatDay(isoTimestamp);" in source


def test_the_card_stacks_under_the_width_ui_behavior_names():
    style = flat(STYLE_PATH)
    behavior = flat(UI_BEHAVIOR)

    assert ".ai_accounts_group { container: ai_accounts / inline-size; }" in style
    assert "@container ai_accounts (max-width: 520px) {" in style
    assert "860px" not in style
    assert "In a panel under 520 px wide the card stacks in the same order" in (
        behavior
    )
