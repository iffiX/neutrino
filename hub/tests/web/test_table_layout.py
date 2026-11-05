"""The Agents and Clients tables: a table in a box that holds every column,
and a card per row in a narrower one, with no sideways scrolling.

What these pin: the box lays the table out by its own width and never scrolls
sideways; the cards start under the width every column needs, which a 1280 px
window holds; each field in a card carries its column's header as its label
and keeps its place on one grid every card shares, its tracks filling the card;
the actions stand at the card's right edge; and in the table the actions take
the room the other columns leave and wrap their buttons.
"""

import re
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
# The pages with such a table, each by the prefix of its file and its classes.
PAGES = ["devices", "clients"]
# The width each table needs for every column, and the width of its box in a
# 1280 px window, the sidebar, the page's margins and the frame's padding
# taken off.
COLUMNS_WIDTH = {"devices": 968, "clients": 860}
BOX_AT_1280 = {"devices": 982, "clients": 934}
# The fields' line of each card grid, widest first, and the box widths under
# which the narrower ones start.
GRIDS = {
    "devices": [
        ["address", "mac", "status", "version", "seen"],
        ["address mac status", "version seen ."],
        ["address mac", "status status", "version seen"],
    ],
    "clients": [
        ["hostname", "platform", "version", "status", "seen"],
        ["hostname platform version", "status seen ."],
        ["hostname platform", "version status", "seen ."],
    ],
}
NARROWER = {"devices": [718, 510], "clients": [624, 380]}


def flat(name: str) -> str:
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def card_rules(page: str) -> str:
    """The rules a box narrower than every column applies."""
    style = flat(f"pages/{page}_page.css")
    query = f"@container {page}_table (max-width: {COLUMNS_WIDTH[page] - 1}px) {{"
    assert query in style
    return style.split(query, 1)[1]


@pytest.mark.parametrize("page", PAGES)
def test_the_box_lays_the_table_out_by_its_own_width(page):
    style = flat(f"pages/{page}_page.css")
    box = style.split(f".{page}_table_box {{", 1)[1].split("}", 1)[0]
    assert f"container: {page}_table / inline-size;" in box
    assert f'{page}_table_box">' in flat(f"pages/{page}_page.tsx")


@pytest.mark.parametrize("page", PAGES)
def test_nothing_in_the_table_scrolls_sideways(page):
    style = flat(f"pages/{page}_page.css")
    assert "overflow-x: auto" not in style
    assert "overflow: auto" not in style
    assert "position: sticky" not in style
    assert f"{page}_table_scroll" not in flat(f"pages/{page}_page.tsx")


def test_no_cell_is_kept_at_the_edge_of_a_scrolling_box():
    assert ".table_actions_cell" not in flat("theme.css")


@pytest.mark.parametrize("page", PAGES)
def test_a_1280_px_window_holds_every_column(page):
    """The table outgrew its box at 1280 and the actions cell covered the
    columns under it, cutting the Chinese ``ui.clients.header_last_seen`` to
    its first two characters."""
    assert COLUMNS_WIDTH[page] <= BOX_AT_1280[page]
    rule = flat(f"pages/{page}_page.css").split(f".{page}_table {{", 1)[1]
    assert "min-width" not in rule.split("}", 1)[0]


@pytest.mark.parametrize("page", PAGES)
def test_a_narrow_box_lays_each_row_out_as_a_card(page):
    rules = card_rules(page)
    assert (
        f".{page}_table, .{page}_table tbody, .{page}_table td {{ display: block; }}"
        in rules
    )
    assert f".{page}_table colgroup, .{page}_table thead {{ display: none; }}" in rules
    row = rules.split(f".{page}_row {{", 1)[1].split("}", 1)[0]
    assert "display: grid;" in row


@pytest.mark.parametrize("page", PAGES)
def test_every_card_lines_its_fields_up_on_one_grid(page):
    """In a card the fields followed one another, so an offline machine's short
    status moved the version and the last seen left of the cards above it."""
    rules = card_rules(page)
    source = flat(f"pages/{page}_page.tsx")
    for areas in GRIDS[page]:
        names = set(" ".join(areas).split()) - {"."}
        for name in names:
            assert f".{page}_cell--{name} {{ grid-area: {name}; }}" in rules
            assert f"{page}_cell--{name}" in source
    assert f'"{" ".join(GRIDS[page][0])}"' in rules


@pytest.mark.parametrize("page", PAGES)
def test_the_tracks_stretch_from_their_table_column_s_width(page):
    """In a card the fields kept their own widths and left the right of the card
    empty."""
    style = flat(f"pages/{page}_page.css")
    widths = [
        int(style.split(f".{page}_col--{column} {{ width: ", 1)[1].split("px", 1)[0])
        for column in GRIDS[page][0]
    ]
    tracks = " ".join(f"minmax({width}px, 1fr)" for width in widths)
    assert f"grid-template-columns: {tracks};" in card_rules(page)


@pytest.mark.parametrize("page", PAGES)
def test_a_narrower_box_wraps_the_fields_onto_the_same_grid(page):
    style = flat(f"pages/{page}_page.css")
    for width, areas in zip(NARROWER[page], GRIDS[page][1:]):
        query = f"@container {page}_table (max-width: {width - 1}px) {{"
        assert query in style
        grid = style.split(query, 1)[1].split("} }", 1)[0]
        assert " ".join(f'"{line}"' for line in areas) in grid


@pytest.mark.parametrize("page", PAGES)
def test_the_actions_stand_at_the_card_s_right_edge(page):
    assert "flex-start" not in card_rules(page)
    actions = flat(f"pages/{page}_page.css").split(f".{page}_actions {{", 1)[1]
    assert "justify-content: flex-end;" in actions.split("}", 1)[0]


@pytest.mark.parametrize("page", PAGES)
def test_a_field_in_a_card_is_labelled_whole_by_its_header(page):
    source = flat(f"pages/{page}_page.tsx")
    headers = re.findall(rf'<th>{{t\("(ui\.\w+\.header_\w+)"\)}}</th>', source)
    labels = re.findall(r'data-label={t\("(ui\.\w+\.header_\w+)"\)}', source)
    assert headers[1:] == labels
    label = card_rules(page).split(f".{page}_table td[data-label]::before {{", 1)[1]
    label = label.split("}", 1)[0]
    assert "content: attr(data-label);" in label
    assert "white-space: nowrap;" in label


@pytest.mark.parametrize("page", PAGES)
def test_a_row_being_edited_lays_its_wash_over_the_ground(page):
    wash = (
        "{ background-image: linear-gradient( "
        "var(--color-accent-wash), var(--color-accent-wash) ); }"
    )
    assert f".{page}_row--editing td {wash}" in flat(f"pages/{page}_page.css")
    assert f".{page}_row--editing {wash}" in card_rules(page)


@pytest.mark.parametrize("page", PAGES)
def test_the_actions_take_what_the_other_columns_leave(page):
    source = flat(f"pages/{page}_page.tsx")
    assert f'<col className="{page}_col--name" />' in source
    assert "<col /> </colgroup>" in source
    assert f".{page}_col--actions" not in flat(f"pages/{page}_page.css")


@pytest.mark.parametrize("page", PAGES)
def test_the_actions_wrap_rather_than_widen_the_table(page):
    assert f".{page}_actions {{ display: flex; flex-wrap: wrap;" in flat(
        f"pages/{page}_page.css"
    )


@pytest.mark.parametrize("page", PAGES)
def test_every_row_names_its_actions_cell(page):
    source = flat(f"pages/{page}_page.tsx")
    assert (
        f'<td className="{page}_cell--actions"> <div className="{page}_actions">'
        in source
    )
