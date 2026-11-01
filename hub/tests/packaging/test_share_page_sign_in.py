"""The App share page's sign-in, checked on the file the page ships.

VS Code answers 202 and takes no token while it downloads its server. The frame
loads only after a sign-in that is no 202, so the page waits on its loading
screen and the app's first page is no `Forbidden.`.
"""

import pathlib

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[3]
SHELL = (REPOSITORY_ROOT / "share_page" / "shell.js").read_text(encoding="utf-8")


def method(signature: str) -> str:
    """One method of the shell's page object.

    Args:
        signature: The line that opens the method.

    Returns:
        The method's text.
    """
    start = SHELL.index(signature)
    return SHELL[start : SHELL.index("\n  },\n", start)]


def test_the_sign_in_asks_again_while_the_app_answers_202():
    sign_in = method("async signIn(session, token) {")
    asked = sign_in.index('fetchWhole("GET", path)')
    waited = sign_in.index("while (answer.status === HTTP.preparing) {")
    slept = sign_in.index("await sleep(TIMING.signIn);")
    asked_again = sign_in.index('fetchWhole("GET", path)', slept)
    assert asked < waited < slept < asked_again
    assert "preparing: 202" in SHELL


def test_the_frame_loads_after_the_sign_in_ends():
    load = method("async load(session, token) {")
    signed_in = load.index("await this.signIn(session, token);")
    assert signed_in < load.index("frame.src = ")
    assert "fetchWhole" not in load
