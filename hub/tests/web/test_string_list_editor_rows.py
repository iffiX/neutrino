"""Editors side by side share their rows, held against ui_behavior.md.

What these pin: the row grid gives each editor its three rows, and every place
that sets editors side by side uses it, so a longer hint moves no list.
"""

from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"


def text(name: str) -> str:
    return (FRONTEND_SRC_DIR / name).read_text(encoding="utf-8")


def test_the_row_grid_gives_each_editor_three_shared_rows():
    css = " ".join(text("components/string_list_editor.css").split())

    assert (
        ".string_list_row > .string_list_editor { display: grid; "
        "grid-row: span 3; grid-template-rows: subgrid; }"
    ) in css


def test_the_container_editor_sets_its_lists_in_the_row_grid():
    assert 'className="container_editor_lists string_list_row"' in text(
        "components/containers_panels.tsx"
    )


def test_the_proxy_page_lines_up_its_dns_lists_and_its_direct_lists():
    page = FRONTEND_SRC_DIR / "pages/proxy_page.tsx"
    if not page.exists():
        return
    assert '<div className="string_list_row">' in page.read_text(encoding="utf-8")
    css = " ".join(text("pages/proxy_page.css").split())
    assert ".proxy_lists > .proxy_subcard { display: grid; grid-row: span 4;" in css
