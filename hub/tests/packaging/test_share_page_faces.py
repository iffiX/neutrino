"""The App share page's inline faces against the client's icon files."""

import base64
import re

import pytest

import venv_tree

REPOSITORY_ROOT = venv_tree.HUB_ROOT.parent
INDEX = (REPOSITORY_ROOT / "share_page" / "index.html").read_text(encoding="utf-8")
SHELL = (REPOSITORY_ROOT / "share_page" / "shell.js").read_text(encoding="utf-8")
ICONS_DIR = REPOSITORY_ROOT / "images" / "icons" / "neutrino_client"
FACES_OF_SCREENS = {
    "loading": "waiting",
    "intro": "wink",
    "incomplete": "sad",
    "link": "sad",
    "hub": "sleep",
    "unavailable": "error",
    "elsewhere": "wink",
    "moved": "wink",
}


@pytest.mark.parametrize("face", sorted(set(FACES_OF_SCREENS.values())))
def test_every_path_of_a_face_is_in_the_page(face):
    source = (ICONS_DIR / f"wolf_{face}.svg").read_text(encoding="utf-8")
    drawn = source[source.index('<g id="wolf"') :]

    assert f'<symbol id="wolf_{face}"' in INDEX
    for path in re.findall(r' d="([^"]+)"', drawn):
        assert path in INDEX


def test_each_screen_names_its_face():
    screens = re.search(r"const FACES = \{(.*?)\};", SHELL).group(1)

    assert dict(re.findall(r'(\w+): "(\w+)"', screens)) == FACES_OF_SCREENS


def test_the_page_opens_on_the_loading_face():
    assert '<use id="face" href="#wolf_waiting"/>' in INDEX


def test_the_introduction_s_small_tab_icon_is_the_hand_drawn_file():
    drawn = (ICONS_DIR / "wolf_wink_16.png").read_bytes()

    assert base64.b64encode(drawn).decode() in SHELL
