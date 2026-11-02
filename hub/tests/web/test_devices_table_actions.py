"""The Agents table's row actions at a window narrower than the table.

What these pin: the box still scrolls in itself, and the actions cell of the
header and of every row stays at its right edge, on an opaque ground, with its
borders on the cell, and the cell gives up its place on a phone's width.
"""

from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"


def flat(name: str) -> str:
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def test_the_box_still_scrolls_in_itself():
    assert ".devices_table_scroll { overflow-x: auto;" in flat("pages/devices_page.css")


def test_the_actions_stay_at_the_right_edge_on_an_opaque_ground():
    assert (
        ".devices_cell--actions { position: sticky; right: 0; z-index: 1; "
        "background: var(--color-surface); }"
    ) in flat("pages/devices_page.css")


def test_a_row_being_renamed_lays_its_wash_over_the_ground():
    assert (
        ".devices_row--editing .devices_cell--actions { background: "
        "linear-gradient(var(--color-accent-wash), var(--color-accent-wash)), "
        "var(--color-surface); }"
    ) in flat("pages/devices_page.css")


def test_each_cell_keeps_its_own_borders():
    style = flat("pages/devices_page.css")
    assert "border-collapse: separate; border-spacing: 0;" in style
    assert "border-collapse: collapse" not in style


def test_a_phone_s_width_lets_the_actions_scroll_with_the_row():
    assert (
        "@media (max-width: 720px) { .devices_cell--actions { position: static; } }"
    ) in flat("pages/devices_page.css")


def test_the_header_and_every_row_name_the_cell():
    page = flat("pages/devices_page.tsx")
    assert '<th className="devices_cell--actions" />' in page
    assert (
        '<td className="devices_cell--actions"> <div className="devices_actions">'
        in page
    )
