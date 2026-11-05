"""The Agents and Clients tables: a table in a box that holds every column
with each row's actions on one line, and a card per row in a narrower one,
with no sideways scrolling.

What these pin: the page measures its box against the fixed columns and the
widest row's actions and turns every row into a card when they do not fit,
so the table's actions never wrap; the cards' grids follow the box's width
through container queries; each field in a card carries its column's header
as its label and keeps its place on one grid every card shares, its tracks
filling the card; the actions stand at the card's right edge.
"""

import re
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
# The pages with such a table, each by the prefix of its file and its classes.
PAGES = ["devices", "clients"]
# The fields' line of each card grid, widest first, and the box widths under
# which the narrower ones start.
GRIDS = {
    "devices": [
        ["address", "mac", "status", "version", "seen"],
        ["address mac status", "version seen ."],
        ["address mac mac", "status version seen"],
        ["address mac", "status status", "version seen"],
    ],
    "clients": [
        ["hostname", "platform", "version", "status", "seen"],
        ["hostname platform version", "status seen ."],
        ["hostname platform", "version status", "seen ."],
    ],
}
NARROWER = {"devices": [718, 510, 408], "clients": [624, 380]}
# The action groups each page measures: a row being renamed shows Save and
# Cancel alone on Agents and is left out.
ACTIONS_SELECTOR = {
    "devices": ".devices_row:not(.devices_row--editing) .devices_actions",
    "clients": ".clients_actions",
}


def flat(name: str) -> str:
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def card_rules(page: str) -> str:
    """The rules a box whose rows are cards applies."""
    style = flat(f"pages/{page}_page.css")
    first = f".{page}_table_box--cards .{page}_table,"
    assert first in style
    return style[style.index(first) :]


@pytest.mark.parametrize("page", PAGES)
def test_the_box_lays_the_table_out_by_its_own_width(page):
    style = flat(f"pages/{page}_page.css")
    box = style.split(f".{page}_table_box {{", 1)[1].split("}", 1)[0]
    assert f"container: {page}_table / inline-size;" in box
    assert f"{page}_table_box" in flat(f"pages/{page}_page.tsx")


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
def test_the_page_measures_its_box_against_the_columns_and_the_actions(page):
    """At 1280 the Agents actions wrapped onto a second line in a range of
    widths, the row twice as tall as its fields."""
    source = flat(f"pages/{page}_page.tsx")
    assert (
        f'useTableCards( tableBoxRef, "{ACTIONS_SELECTOR[page]}", )' in source
        or f'useTableCards(tableBoxRef, "{ACTIONS_SELECTOR[page]}")' in source
    )
    assert "ref={tableBoxRef}" in source
    assert f'{page}_table_box ${{isCards ? "{page}_table_box--cards" : ""}}' in source
    hook = flat("use_table_cards.ts")
    assert "new ResizeObserver(measure)" in hook
    assert "box.clientWidth < width" in hook
    assert "document.fonts.ready.then(measure)" in hook


def test_the_measure_takes_every_column_but_the_actions_and_the_widest_group():
    hook = flat("use_table_cards.ts")
    assert '[...box.querySelectorAll("col")].slice(0, -1)' in hook
    assert "Math.max(...groups.map(oneLineWidth))" in hook
    assert 'box.querySelector("thead th:last-child")' in hook


def test_with_no_group_to_measure_the_layout_stays():
    """A single machine being renamed shows Save and Cancel alone, and the
    table turned back and forth while it was edited."""
    hook = flat("use_table_cards.ts")
    assert "if (groups.length === 0) { return null; }" in hook
    assert "if (isActive && width !== null) {" in hook


@pytest.mark.parametrize("page", PAGES)
def test_a_narrow_box_lays_each_row_out_as_a_card(page):
    rules = card_rules(page)
    cards = f".{page}_table_box--cards"
    assert (
        f"{cards} .{page}_table, {cards} .{page}_table tbody, "
        f"{cards} .{page}_table td {{ display: block; }}"
    ) in rules
    assert (
        f"{cards} .{page}_table colgroup, {cards} .{page}_table thead "
        "{ display: none; }"
    ) in rules
    row = rules.split(f"{cards} .{page}_row {{", 1)[1].split("}", 1)[0]
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
def test_the_tracks_stretch_to_the_card_s_width(page):
    """In a card the fields kept their own widths and left the right of the card
    empty."""
    rules = card_rules(page)
    row = rules.split(f".{page}_table_box--cards .{page}_row {{", 1)[1]
    tracks = row.split("grid-template-columns:", 1)[1].split(";", 1)[0]
    assert re.fullmatch(r"( minmax\(\d+px, 1fr\)){5}", tracks)


@pytest.mark.parametrize("page", PAGES)
def test_a_narrower_box_wraps_the_fields_onto_the_same_grid(page):
    style = flat(f"pages/{page}_page.css")
    for width, areas in zip(NARROWER[page], GRIDS[page][1:]):
        query = (
            f"@container {page}_table (max-width: {width - 1}px) {{ "
            f".{page}_table_box--cards .{page}_row {{"
        )
        assert query in style
        grid = style.split(query, 1)[1].split("} }", 1)[0]
        assert " ".join(f'"{line}"' for line in areas) in grid


def test_a_narrow_agents_card_sets_the_version_and_the_last_seen_beside_the_rings():
    """In two columns the rings took a line with empty room to their right,
    and the version and the last seen the next."""
    style = flat("pages/devices_page.css")
    grid = style.split("@container devices_table (max-width: 509px) {", 1)[1]
    grid = grid.split("} }", 1)[0]
    assert "grid-template-columns: 174px repeat(2, minmax(0, 1fr));" in grid


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
def test_every_row_names_its_actions_cell(page):
    source = flat(f"pages/{page}_page.tsx")
    assert (
        f'<td className="{page}_cell--actions"> <div className="{page}_actions">'
        in source
    )
