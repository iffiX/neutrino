"""The Services page at a phone's width: an address of any length stays inside
its row, and so does every chip and button of the row.

What these pin: an entry's address breaks anywhere inside its chip and is
never cut short, while the kind and the state word stay whole; a host beside
the title breaks anywhere; the row's end wraps its buttons and its badge.
"""

from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"


def rule(selector: str) -> str:
    """The body of one rule of the Services page's stylesheet."""
    path = FRONTEND_SRC_DIR / "pages/services_page.css"
    style = " ".join(path.read_text(encoding="utf-8").split())
    return style.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def test_an_address_breaks_anywhere_inside_its_chip():
    address = rule(".app_entry_address")
    assert "overflow-wrap: anywhere;" in address
    assert "white-space: normal;" in address
    assert "min-width: 0;" in address


def test_an_address_is_shown_whole():
    """A 200-character address pushed its row's chips out of the box on a
    phone, and an address cut with an ellipsis hid its end."""
    assert "text-overflow" not in rule(".app_entry_address")
    assert "overflow: hidden" not in rule(".app_entry_address")


def test_the_kind_and_the_state_word_stay_whole():
    chip = rule(".app_entry")
    assert "white-space" not in chip
    assert "max-width: 100%;" in chip


def test_a_host_beside_the_title_breaks_anywhere():
    machine = rule(".app_row_machine")
    assert "overflow-wrap: anywhere;" in machine
    assert "min-width: 0;" in machine


def test_the_row_s_end_wraps_its_buttons_and_its_badge():
    assert "flex-wrap: wrap;" in rule(".app_row_end")
