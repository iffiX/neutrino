"""The service worker of the App share page, checked on the file the page ships.

One tab of a browser is active, so the worker sends every request of the app's
frame to the one shell it was given last. It holds nothing that picks among
several tabs.
"""

import pathlib

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


def test_the_worker_keeps_one_shell():
    assert "let activeShell = null;" in WORKER
    assert "new Map()" not in WORKER.split("const pending = new Map();")[0]
    assert "const shells" not in WORKER


def test_the_worker_takes_only_the_shell_of_the_lock_s_holder():
    admit = function("async function admit(data, port) {")
    checked = admit.index("if (await isHolder(data.lockClient)) {")
    taken = admit.index(
        'activeShell = { tab: data.tab, port, cache: String(data.cache || "") };'
    )
    assert checked < taken
    assert admit.index('port.postMessage({ type: "ready" });') > taken
    is_holder = function("async function isHolder(lockClient) {")
    assert "const { held } = await self.navigator.locks.query();" in is_holder
    assert "const lock = held.find((each) => each.name === ACTIVE_LOCK);" in is_holder
    assert "return !lock || lock.clientId === lockClient;" in is_holder


def test_the_announced_shells_are_taken_one_after_another():
    assert (
        "admitting = admitting.then(() => admit(data, event.ports[0])).catch(() => {});"
        in WORKER
    )


def test_the_worker_and_the_shell_name_one_lock():
    shell = (REPOSITORY_ROOT / "share_page" / "shell.js").read_text(encoding="utf-8")
    line = 'const ACTIVE_LOCK = "neutrino_active_tab";'
    assert line in WORKER and line in shell
    assert "lockClient: this.lockClient" in shell


def test_a_navigation_of_the_tab_gets_the_shell_page_from_the_site_s_root():
    """The tab's ``/`` is the shell page, and the frame's ``/`` the app's page."""
    assert 'const SHELL_PAGE = "/";' in WORKER
    assert 'const SHELL_PREFIX = "/__neutrino/";' in WORKER
    shell_page = function("async function shellPage() {")
    assert 'const page = await fetch(SHELL_PAGE, { cache: "no-cache" });' in shell_page
    route = function("async function route(event, url) {")
    answered = route.index(
        'if (isNavigation && request.destination === "document") return shellPage();'
    )
    assert answered < route.index("const shell = await shellOf();")
    assert (
        "if (!isAppHost && asked.pathname.startsWith(SHELL_PREFIX)) return;" in WORKER
    )
    assert WORKER.count("SHELL_PREFIX") == 2


def test_every_request_of_the_frame_goes_to_the_active_shell():
    route = function("async function route(event, url) {")
    assert "const shell = await shellOf();" in route
    assert "searchParams" not in route
    shell_of = function("async function shellOf() {")
    assert "if (!activeShell) await waitFor(() => activeShell !== null);" in shell_of


def test_the_worker_holds_nothing_that_picks_among_tabs():
    for name in (
        "__neutrino_tab",
        "navigating",
        "retagPage",
        "withTab",
        "soleTab",
        "clientTabs",
        "tabOfClient",
        "referrer",
        "resultingClientId",
        "NAVIGATING_WAIT_MS",
        "NAVIGATING_AGE_MAX_MS",
    ):
        assert name not in WORKER, name


def test_a_tab_the_app_opened_takes_the_facts_of_the_active_shell():
    send_facts = function("async function sendFacts(from, port) {")
    waited = send_facts.index("const opener = await shellOf();")
    checked = send_facts.index("if (opener && opener.tab === from)")
    assert waited < checked
    assert "port.postMessage(null);" in send_facts
    assert "event.waitUntil(sendFacts(data.from, event.ports[0]));" in WORKER


def test_a_request_that_is_no_navigation_still_follows_its_redirects_in_the_worker():
    route = function("async function route(event, url) {")
    assert (
        'if (isNavigation || request.redirect !== "follow") return send(shell, sent, false);'
        in route
    )
    assert "return follow(shell, sent);" in route


def test_a_public_response_with_a_max_age_is_kept_though_it_sets_a_cookie():
    """VS Code sets its cookies on every response, its scripts among them."""
    keepable = function("function isKeepable(sent, head, contentType) {")
    assert 'if (sent.method !== "GET" || head.status !== 200) return false;' in keepable
    refused = keepable.index(
        "if (head.hasSetCookie && !isPublicFor(control)) return false;"
    )
    assert (
        keepable.index("if (/(^|[\\s,])(no-store|private)\\b/.test(control))") < refused
    )
    public = function("function isPublicFor(control) {")
    assert "/(^|[\\s,])public\\b/.test(control)" in public
    assert "/(^|[\\s,])max-age=\\d+/.test(control)" in public


def test_the_kept_copy_holds_no_cookie_header():
    dropped = WORKER[WORKER.index("const DROPPED_HEADERS = ") :]
    assert '"set-cookie"' in dropped[: dropped.index(";\n")]
    on_head = function("function onHead(entry, message) {")
    assert "if (DROPPED_HEADERS.has(lower)) continue;" in on_head
    assert (
        "storing = store(entry.shell.cache, entry.sent.url.href, toCache, entry.head);"
        in on_head
    )


def test_a_request_to_the_app_s_own_host_goes_to_the_shell():
    """The app builds its own addresses from the Host the shell sends."""
    shell = (REPOSITORY_ROOT / "share_page" / "shell.js").read_text(encoding="utf-8")
    assert 'const APP_HOST = "127.0.0.1";' in WORKER
    assert 'host: "127.0.0.1"' in shell
    start = WORKER.index('self.addEventListener("fetch", (event) => {')
    handler = WORKER[start : WORKER.index("\n});\n", start)]
    assert (
        "const isAppHost = asked.origin !== self.location.origin && asked.hostname === APP_HOST;"
        in handler
    )
    assert (
        "if (!isAppHost && asked.pathname.startsWith(SHELL_PREFIX)) return;" in handler
    )
    assert "if (asked.origin !== self.location.origin && !isAppHost) return;" in handler
    assert (
        "const url = isAppHost ? new URL(asked.pathname + asked.search, self.location.origin) : asked;"
        in handler
    )
    assert "event.respondWith(route(event, url)" in handler
