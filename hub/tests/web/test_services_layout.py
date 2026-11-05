"""The Services page at a phone's width: an address of any length stays inside
its row, and so does every chip and button of the row.

What these pin: an entry's chip is one line whose address shows at most 56
characters and ends in an ellipsis past that or at the row's edge, while the
kind and the state word stay whole and the title holds the address whole; a
host beside the title is cut the same way; an app's row is one flex line, so
each part is as wide as the row; the row's end wraps its buttons and its
badge.
"""

from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
# The longest address a chip shows before its ellipsis, in characters.
ADDRESS_CHARACTERS = 56


def rule(selector: str) -> str:
    """The body of one rule of the Services page's stylesheet."""
    path = FRONTEND_SRC_DIR / "pages/services_page.css"
    style = " ".join(path.read_text(encoding="utf-8").split())
    return style.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def page_source() -> str:
    path = FRONTEND_SRC_DIR / "pages/services_page.tsx"
    return " ".join(path.read_text(encoding="utf-8").split())


def test_a_long_address_ends_in_an_ellipsis_inside_its_chip():
    """A 200-character address pushed its row's chips out of the box on a
    phone, and wrapped it showed a path nobody reads."""
    address = rule(".app_entry_address")
    assert f"max-width: {ADDRESS_CHARACTERS}ch;" in address
    assert "min-width: 0;" in address
    assert "overflow: hidden;" in address
    assert "text-overflow: ellipsis;" in address
    assert "white-space: nowrap;" in address


def test_the_chip_s_title_holds_the_whole_address():
    assert 'title={address === "" ? undefined : address}' in page_source()


def test_the_kind_and_the_state_word_stay_whole():
    chip = rule(".app_entry")
    assert "white-space" not in chip
    assert "max-width: 100%;" in chip


def test_a_host_beside_the_title_is_cut_the_same_way():
    machine = rule(".app_row_machine")
    assert f"max-width: {ADDRESS_CHARACTERS}ch;" in machine
    assert "text-overflow: ellipsis;" in machine
    assert "white-space: nowrap;" in machine
    assert 'className="app_row_machine mono" title={machine}' in page_source()


def test_an_app_row_is_one_flex_line():
    """Wrapping, the row sized each part by its widest content, and a chip
    with a cut address grew past the row on a phone."""
    assert "flex-wrap: nowrap;" in rule(".app_row")


def test_the_row_s_end_wraps_its_buttons_and_its_badge():
    assert "flex-wrap: wrap;" in rule(".app_row_end")
