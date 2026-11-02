"""The shim of the App share page, checked on the file the page ships.

A link followed in the frame names its tab, so the worker answers it with no
page of its own while several shells are open, and a download leaves the app's
page in the frame.
"""

import pathlib

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[3]
SHIM = (REPOSITORY_ROOT / "share_page" / "shim.js").read_text(encoding="utf-8")


def tag_followed() -> str:
    """The shim's handler of a link followed in the frame."""
    start = SHIM.index("const tagFollowed = (event) => {")
    return SHIM[start : SHIM.index("\n  };\n", start)]


def test_a_followed_link_gets_the_tab_after_the_apps_own_handlers():
    assert 'window.addEventListener("click", tagFollowed);' in SHIM
    handler = tag_followed()
    assert handler.index("event.defaultPrevented") < handler.index(
        "target.searchParams.set(TAB_PARAM, tab);"
    )


def test_a_followed_link_gets_its_own_address_back():
    handler = tag_followed()
    assert 'const original = anchor.getAttribute("href");' in handler
    assert 'setTimeout(() => anchor.setAttribute("href", original), 0);' in handler


def test_a_link_that_leaves_no_page_keeps_its_address():
    handler = tag_followed()
    # A click for another tab, a link with its own target, a link to a fragment
    # of this page, a blob, and another origin.
    assert "event.button !== 0" in handler
    assert "event.ctrlKey || event.metaKey || event.shiftKey || event.altKey" in handler
    assert "/^_self$/i.test(anchor.target)" in handler
    assert "target.pathname === location.pathname" in handler
    assert "target.protocol !== location.protocol" in handler
    assert "target.origin !== location.origin" in handler


def leaving_listener() -> str:
    """The shim's line that tells the worker a page is about to leave."""
    start = SHIM.index('window.addEventListener("beforeunload"')
    return SHIM[start : SHIM.index("\n", start)]


def test_a_page_tells_the_worker_before_it_leaves():
    listener = leaving_listener()
    assert 'type: "leaving", tab, address: location.href.split("#")[0]' in listener
    assert listener.endswith(", true);")


def test_the_shim_never_holds_a_page_back():
    assert "beforeunload" in SHIM
    assert "preventDefault" not in SHIM
    assert "returnValue" not in SHIM


def test_the_listener_goes_on_before_the_app_s_code_can_run():
    """The shim runs at the top of the page, and the listener in its first block."""
    assert SHIM.index('window.addEventListener("beforeunload"') < SHIM.index(
        "const tagAction = (element, attribute) => {"
    )
    assert "worker.controller.postMessage" in leaving_listener()
