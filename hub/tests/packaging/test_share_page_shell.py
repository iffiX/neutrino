"""The shell of the App share page, checked on the file the page ships.

A tab the app opened at an address with a fragment opens the app at that
fragment, and the fragment of a link's facts never reaches the app.
"""

import pathlib

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[3]
SHELL = (REPOSITORY_ROOT / "share_page" / "shell.js").read_text(encoding="utf-8")


def load_method() -> str:
    """The shell's load of the app's first page in the frame."""
    start = SHELL.index("async load(session, token) {")
    return SHELL[start : SHELL.index("\n  },\n", start)]


def test_the_frame_opens_at_the_tab_s_own_fragment_with_no_tab_tag():
    load = load_method()
    passed = load.index(
        "if (isOwnAddress && location.hash && !linkedFacts()) url.hash = location.hash;"
    )
    framed = load.index("frame.src = url.pathname + url.search + url.hash;")
    assert passed < framed
    assert "searchParams" not in load
    assert "TAB_PARAM" not in SHELL


def test_the_address_the_shell_starts_from_holds_no_fragment():
    """A token's redirect takes the place of the root, whatever the fragment."""
    load = load_method()
    assert (
        'let start = isOwnAddress ? location.pathname + location.search : (this.facts.app.path || "/");'
        in load
    )
    assert (
        'if (where && start === "/" && !this.facts.app.path) start = where[1];' in load
    )
