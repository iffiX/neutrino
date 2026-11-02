"""The service worker of the App share page, checked on the file the page ships.

A script navigation carries no tag. With several shells open the worker gives it
to the one tab whose pages told the worker they are leaving, and a redirect keeps
its navigation's tab, so a download leaves the app's page in the frame. Any other
case takes the blank page that loads itself again, and never another tab.
"""

import pathlib
import re

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKER = (REPOSITORY_ROOT / "share_page" / "sw.js").read_text(encoding="utf-8")


def function(signature: str) -> str:
    """One top-level function of the worker.

    Args:
        signature: The line that opens the function.

    Returns:
        The function's text.
    """
    start = WORKER.index(signature)
    return WORKER[start : WORKER.index("\n}\n", start)]


def constant(name: str) -> int:
    """One number the worker declares.

    Args:
        name: The constant's name.

    Returns:
        Its value.
    """
    return int(re.search(rf"^const {name} = (\d+);$", WORKER, re.MULTILINE).group(1))


def test_an_untagged_navigation_ends_at_the_blank_page_when_no_tab_is_told():
    route = function("async function route(event, url) {")
    sole = route.index(
        "tab = (await soleTab()) || (await leavingTab(request.referrer));"
    )
    blank = route.index('return request.method === "GET" ? retagPage() : failure(')
    assert sole < blank


def test_the_wait_outlasts_a_late_message_and_the_age_outlasts_the_wait():
    assert constant("LEAVING_WAIT_MS") == 50
    assert constant("LEAVING_AGE_MAX_MS") == 300


def test_the_pages_are_counted_after_the_wait():
    leaving_tab = function("async function leavingTab(referrer) {")
    waited = leaving_tab.index("setTimeout(resolve, LEAVING_WAIT_MS)")
    counted = leaving_tab.index("leaving = freshLeaving();")
    assert waited < counted


def test_a_told_tab_counts_only_alone_and_with_its_own_referrer():
    leaving_tab = function("async function leavingTab(referrer) {")
    assert (
        "if (tabs.size !== 1 || !leaving.some((page) => page.address === referrer)) "
        "return null;" in leaving_tab
    )


def test_a_page_past_the_age_limit_counts_no_more():
    fresh = function("function freshLeaving() {")
    assert "const oldest = Date.now() - LEAVING_AGE_MAX_MS;" in fresh
    assert "leaving.filter((page) => page.at >= oldest)" in fresh


def test_the_worker_keeps_a_told_page_with_its_tab_address_and_time():
    assert (
        'else if (data.type === "leaving" && data.tab) {\n'
        "    leaving = freshLeaving();\n"
        "    leaving.push({ tab: data.tab, address: data.address, at: Date.now() });"
        in WORKER
    )


def test_a_navigation_removes_its_tab_s_pages_before_it_waits_for_the_shell():
    route = function("async function route(event, url) {")
    removed = route.index(
        "if (isNavigation) leaving = leaving.filter((page) => page.tab !== tab);"
    )
    assert removed < route.index("await shellOf(tab)")


def test_a_navigation_s_redirect_keeps_its_tab():
    route = function("async function route(event, url) {")
    assert (
        "if (isNavigation) return withTab(await send(shell, sent, false), tab, url);"
        in route
    )
    with_tab = function("async function withTab(response, tab, url) {")
    assert "next.searchParams.set(TAB_PARAM, tab);" in with_tab
    assert (
        'headers.set("location", next.pathname + next.search + next.hash);' in with_tab
    )


def test_a_redirect_stays_as_it_was_for_one_shell_and_another_site():
    with_tab = function("async function withTab(response, tab, url) {")
    assert (
        "!REDIRECT_STATUSES.has(response.status) || !location || (await soleTab())"
        in with_tab
    )
    origin = with_tab.index(
        "if (next.origin !== self.location.origin) return response;"
    )
    assert origin < with_tab.index("next.searchParams.set(TAB_PARAM, tab);")


def test_a_request_that_is_no_navigation_still_follows_its_redirects_in_the_worker():
    route = function("async function route(event, url) {")
    assert (
        'if (request.redirect !== "follow") return send(shell, sent, false);' in route
    )
    assert "return follow(shell, sent);" in route
