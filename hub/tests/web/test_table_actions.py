"""The row actions of a table at a window narrower than the table.

What these pin: each table's box still scrolls in itself, and the actions cell
of the header and of every row stays at its right edge, on an opaque ground,
with its borders on the cell, and the cell gives up its place on a phone's
width. The actions take the room the other columns leave and wrap their
buttons, so the table fits its box in a 1280 px window.
"""

from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
# The pages with such a table, each by the prefix of its file and its classes.
PAGES = ["devices", "clients"]
# The width of each table's box in a 1280 px window, the sidebar, the page's
# margins and the card's padding taken off.
BOX_AT_1280 = {"devices": 982, "clients": 934}


def flat(name: str) -> str:
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("page", PAGES)
def test_the_box_still_scrolls_in_itself(page):
    assert f".{page}_table_scroll {{ overflow-x: auto;" in flat(
        f"pages/{page}_page.css"
    )


def test_the_actions_stay_at_the_right_edge_on_an_opaque_ground():
    assert (
        ".table_actions_cell { position: sticky; right: 0; z-index: 1; "
        "background-color: var(--color-surface); }"
    ) in flat("theme.css")


@pytest.mark.parametrize("page", PAGES)
def test_a_row_being_edited_lays_its_wash_over_the_ground(page):
    assert (
        f".{page}_row--editing td {{ background-image: linear-gradient( "
        "var(--color-accent-wash), var(--color-accent-wash) ); }"
    ) in flat(f"pages/{page}_page.css")


@pytest.mark.parametrize("page", PAGES)
def test_each_cell_keeps_its_own_borders(page):
    style = flat(f"pages/{page}_page.css")
    assert "border-collapse: separate; border-spacing: 0;" in style
    assert "border-collapse: collapse" not in style


def test_a_phone_s_width_lets_the_actions_scroll_with_the_row():
    assert (
        "@media (max-width: 720px) { .table_actions_cell { position: static; } }"
    ) in flat("theme.css")


@pytest.mark.parametrize("page", PAGES)
def test_the_page_keeps_no_copy_of_the_cell(page):
    assert "position: sticky" not in flat(f"pages/{page}_page.css")


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
def test_the_table_fits_its_box_in_a_1280_px_window(page):
    """The table outgrew its box at 1280 and the actions cell covered the
    columns under it, cutting the Chinese ``ui.clients.header_last_seen`` to
    its first two characters."""
    style = flat(f"pages/{page}_page.css")
    rule = style.split(f".{page}_table {{", 1)[1].split("}", 1)[0]
    min_width = int(rule.split("min-width:", 1)[1].split("px", 1)[0])
    assert min_width <= BOX_AT_1280[page]


@pytest.mark.parametrize("page", PAGES)
def test_the_header_and_every_row_name_the_cell(page):
    source = flat(f"pages/{page}_page.tsx")
    assert '<th className="table_actions_cell" />' in source
    assert (
        f'<td className="table_actions_cell"> <div className="{page}_actions">'
        in source
    )
