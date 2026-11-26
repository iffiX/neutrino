"""The AI page's Accounts panel, held against ui_behavior.md and ui_text.md.

What these pin: the account rows' words say what ui_text.md writes in both
languages; the accounts are a table of one line each with fixed columns and
the buttons at the line's end while their box holds them, measured as the
Agents table is, and a card each in a narrower box; in a card the service,
the label with the windows under it, and the three right-aligned lines each
in a column the cards share, and the buttons at the card's foot; Pause and
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


def test_the_accounts_are_a_table_by_the_agents_tables_measure():
    source = flat(PANEL_PATH)
    style = flat(STYLE_PATH)

    assert 'useTableCards(tableBoxRef, ".ai_account_actions")' in source
    assert "ref={tableBoxRef}" in source
    assert 'ai_accounts_box ${isCards ? "ai_accounts_box--cards" : ""}' in source
    assert "container: ai_accounts / inline-size;" in rule(style, ".ai_accounts_box")
    assert "table-layout: fixed;" in rule(style, ".ai_accounts")
    columns = re.findall(r'<col className="ai_accounts_col--(\w+)" />', source)
    assert columns == [
        "service",
        "identity",
        "windows",
        "counts",
        "status",
        "updated",
        "actions",
    ]
    for column in columns[:-1]:
        assert re.search(r"width: \d+px;", rule(style, f".ai_accounts_col--{column}"))
    # No header row: the hidden one keeps the padding the measure reads.
    assert '<thead className="ai_accounts_head">' in source
    assert ".ai_accounts_head { display: none; }" in style


def test_a_narrow_box_turns_each_account_into_a_card_on_one_grid():
    style = flat(STYLE_PATH)
    cards = ".ai_accounts_box--cards"

    assert (
        f"{cards} .ai_accounts, {cards} .ai_accounts td {{ display: block; }}"
    ) in style
    assert (
        f"{cards} .ai_accounts colgroup, {cards} .ai_accounts thead "
        "{ display: none; }"
    ) in style
    assert "grid-template-columns: max-content minmax(0, 1fr) max-content;" in rule(
        style, f"{cards} .ai_accounts tbody"
    )
    assert "grid-template-columns: subgrid;" in rule(style, f"{cards} .ai_account_row")
    assert "grid-area: 1 / 1;" in rule(style, f"{cards} .ai_account_cell--service")
    assert "grid-area: 1 / 2;" in rule(style, f"{cards} .ai_account_cell--identity")
    assert "grid-column: 2;" in rule(style, f"{cards} .ai_account_cell--windows")
    for cell, area in (("counts", "1 / 3"), ("status", "2 / 3"), ("updated", "3 / 3")):
        assert f"grid-area: {area};" in rule(style, f"{cards} .ai_account_cell--{cell}")
    assert "grid-row: 4;" in rule(style, f"{cards} .ai_account_cell--actions")


def test_the_three_lines_are_right_aligned():
    style = flat(STYLE_PATH)

    assert (
        ".ai_account_cell--counts, .ai_account_cell--updated { text-align: right; }"
        in (style)
    )
    assert "font-variant-numeric: tabular-nums;" in rule(style, ".ai_account_counts")


def test_the_buttons_are_right_aligned_in_their_cell():
    source = flat(PANEL_PATH)
    style = flat(STYLE_PATH)

    assert source.index('<td className="ai_account_cell--actions">') > source.index(
        '<td className="ai_account_cell--updated">'
    )
    assert "justify-content: flex-end;" in rule(style, ".ai_account_actions")


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

    assert "@container ai_accounts (max-width: 520px) {" in style
    assert "860px" not in style
    assert "In a panel under 520 px wide the card stacks in the same order" in (
        behavior
    )
