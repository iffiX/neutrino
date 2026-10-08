"""What the guide's screenshot tool does inside a page, and how its table reads.

The tool runs against a live panel and the consoles; what is asserted here is
the part that runs inside a page, against a local page holding the panel's QR
code image, and the table check's reading of an entry that serves several
pages.
"""

import base64
import importlib.util
import sys
from pathlib import Path

import pytest

SCREENSHOTS_DIR = Path(__file__).resolve().parents[3] / "packaging" / "screenshots"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DATA_URL_PREFIX = "data:image/png;base64,"
STAND_IN = "neutrino://enroll/example"
PAGE = """<!doctype html>
<img class="qr_code" src="data:image/png;base64,AAAA" width="240" height="240">
<svg class="qr_code"></svg>
<p class="avatar">alice</p>
"""


def _load(name):
    if str(SCREENSHOTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCREENSHOTS_DIR))
    spec = importlib.util.spec_from_file_location(name, SCREENSHOTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def capture():
    pytest.importorskip("playwright.sync_api")
    pytest.importorskip("qrcode")
    return _load("capture")


@pytest.fixture(scope="module")
def check_shots():
    return _load("check_shots")


@pytest.fixture
def page(capture, tmp_path):
    from playwright.sync_api import Error, sync_playwright

    document = tmp_path / "page.html"
    document.write_text(PAGE)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Error as error:
            pytest.skip(f"chromium is not installed: {error}")
        page = browser.new_page()
        page.goto(document.as_uri())
        yield page
        browser.close()


def test_the_qr_code_is_a_png_data_url(capture):
    url = capture.qr_png_url(STAND_IN)

    assert url.startswith(DATA_URL_PREFIX)
    assert base64.b64decode(url[len(DATA_URL_PREFIX) :]).startswith(PNG_SIGNATURE)


def test_the_qr_code_image_is_replaced_and_keeps_its_size(capture, page):
    before = page.get_attribute("img.qr_code", "src")

    assert capture.redraw_qr(page, STAND_IN) == 1

    after = page.get_attribute("img.qr_code", "src")
    assert after != before
    assert after.startswith(DATA_URL_PREFIX)
    assert page.get_attribute("img.qr_code", "width") == "240"
    assert page.get_attribute("img.qr_code", "height") == "240"
    assert capture.redraw_qr(page, STAND_IN) == 0


def test_hidden_elements_keep_their_place(capture, page):
    assert capture.hide(page, [".avatar", ".absent"]) == 1

    avatar = page.locator(".avatar")
    assert (
        avatar.evaluate("element => getComputedStyle(element).visibility") == "hidden"
    )
    assert avatar.bounding_box()["height"] > 0


def test_an_entry_serves_every_page_it_lists(check_shots):
    table = {
        "shots": [
            {
                "file": "a.png",
                "language": "console",
                "pages": ["hub/overlay.md", "hub/network.md"],
            },
            {
                "file": "b.png",
                "language": "en",
                "page": "hub/ai.md",
                "pages": ["hub/proxy.md", "hub/ai.md"],
            },
            {"file": "c.png", "language": "zh", "page": "hub/ai.md"},
        ]
    }

    assert check_shots.shot_pages(table["shots"][1]) == ["hub/ai.md", "hub/proxy.md"]
    assert check_shots.named_images(table) == {
        ("hub/overlay.md", "console", "a"),
        ("zh-CN/hub/overlay.md", "console", "a"),
        ("hub/network.md", "console", "a"),
        ("zh-CN/hub/network.md", "console", "a"),
        ("hub/ai.md", "en", "b"),
        ("hub/proxy.md", "en", "b"),
        ("zh-CN/hub/ai.md", "zh", "c"),
    }
