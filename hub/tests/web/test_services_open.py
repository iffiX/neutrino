"""The Services page's Open, read from the page's source.

What these pin: Open is on each web entry and on no other, hidden while a
client's token opened the session and disabled while the entry reads
unhealthy; the tab opens before the request and with no opener, and goes to
the entry's scheme and path at the panel's own host and the forward's port,
the token added; every word is in both languages.
"""

import json
import re
from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
WORDS = ("ui.services.open",)
CODES = ("code.entry_unknown", "code.forward_port_unavailable")


def page_source() -> str:
    path = FRONTEND_SRC_DIR / "pages/services_page.tsx"
    return " ".join(path.read_text(encoding="utf-8").split())


def function_body(name: str) -> str:
    source = page_source()
    start = source.index(f"function {name}(")
    following = source.find(" function ", start + 1)
    return source[start:] if following < 0 else source[start:following]


def catalog(language: str, name: str) -> dict:
    return json.loads((LOCALES_DIR / language / name).read_text(encoding="utf-8"))


def test_open_is_on_each_web_entry_while_the_panel_was_reached_directly():
    row = function_body("AppRow")

    assert 'isOpenShown && entry.type === "web" && (' in row
    assert "entry.is_healthy === false" in row
    assert "isOpenShown={!isOpenedByClient}" in page_source()
    assert "const { isOpenedByClient } = useAuth();" in page_source()


def test_the_tab_opens_before_the_request_with_no_opener():
    row = function_body("AppRow")

    opening = row.index('window.open("", "_blank")')
    asking = row.index("apiPost<ServiceEntryOpenView>(OPEN_PATH, request)")
    assert opening < asking
    assert "tab.opener = null;" in row
    assert "tab.location.replace(url);" in row
    assert "tab?.close();" in row


def test_the_tab_goes_to_the_panels_host_at_the_forwards_port():
    address = function_body("openedAddress")

    assert "`${scheme}://${hubHost(false)}:${opened.port}`" in address
    assert "address.searchParams.set(TOKEN_PARAM, opened.token);" in address
    assert 'const TOKEN_PARAM = "tkn";' in page_source()
    assert 'const OPEN_PATH = "/hub/service/entry/open";' in page_source()


def test_every_word_is_in_both_languages():
    for language in ("en", "zh-CN"):
        devices = catalog(language, "devices.json")
        codes = catalog(language, "codes.json")
        assert all(devices.get(key) for key in WORDS)
        assert all(codes.get(key) for key in CODES)
    assert re.search(
        r"\{minimum\}.*\{maximum\}",
        catalog("zh-CN", "codes.json")["code.forward_port_unavailable"],
    )
