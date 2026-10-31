"""The panel's favicon files are the hub's default face."""

import venv_tree
from shared import icons

FRONTEND_PUBLIC_DIR = venv_tree.HUB_ROOT / "frontend" / "public"


def test_the_16_pixel_favicon_is_the_hand_drawn_file():
    source = venv_tree.ICONS_SOURCE_DIR / "wolf_open_16.png"

    assert (FRONTEND_PUBLIC_DIR / "favicon_16.png").read_bytes() == source.read_bytes()


def test_the_32_pixel_favicon_is_what_the_build_makes():
    built = icons.png(32, name="neutrino_hub", face="open")

    assert (FRONTEND_PUBLIC_DIR / "favicon_32.png").read_bytes() == built


def test_the_panel_page_names_both_favicons():
    index = (venv_tree.HUB_ROOT / "frontend" / "index.html").read_text()

    assert 'sizes="16x16" href="/favicon_16.png"' in index
    assert 'sizes="32x32" href="/favicon_32.png"' in index
