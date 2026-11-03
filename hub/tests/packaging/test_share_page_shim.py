"""The shim of the App share page, checked on the file the page ships.

The shim tags no page, link or form of the app with its tab, and sends the
worker no message. An address the app opens in another tab still names the
tab that opened it.
"""

import pathlib

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[3]
SHIM = (REPOSITORY_ROOT / "share_page" / "shim.js").read_text(encoding="utf-8")


def test_the_shim_tags_only_an_address_opened_in_another_tab():
    for name in (
        "__neutrino_tab",
        "TAB_PARAM",
        "navigating",
        "beforeunload",
        "MutationObserver",
        "HTMLFormElement",
        "submit",
        "tagFollowed",
        "postMessage",
        "history.replaceState",
    ):
        assert name not in SHIM, name
    assert 'const FROM_PARAM = "__neutrino_from";' in SHIM
    assert "target.searchParams.set(FROM_PARAM, tab);" in SHIM
    assert 'document.addEventListener("click", tagAnchor, true);' in SHIM
