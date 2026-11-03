"""The App share page's one active tab, checked on the files the page ships.

The tab that holds the Web Lock of the page's origin connects and shows the
app. Any other tab shows a waiting screen, connects to nothing and queues a
request for the lock. Use here steals the lock, and the tab that loses it
leaves on the moved screen.
"""

import pathlib
import re

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[3]
SHELL = (REPOSITORY_ROOT / "share_page" / "shell.js").read_text(encoding="utf-8")
INDEX = (REPOSITORY_ROOT / "share_page" / "index.html").read_text(encoding="utf-8")
# The waiting screens' words, as iffi agreed them.
WAITING_WORDS = {
    "en": {
        "elsewhere": '["An app is already open in another tab.", "Only one can be open at a time."]',
        "moved": '["This app is now open in another tab."]',
        "useHere": '"Use here"',
    },
    "zh": {
        "elsewhere": '["已经在另一个标签页打开了一个应用。", "一次只能打开一个。"]',
        "moved": '["这个应用已在另一个标签页打开。"]',
        "useHere": '"在这里使用"',
    },
}


def member(signature: str) -> str:
    """One method of an object of the shell.

    Args:
        signature: The line that opens the method.

    Returns:
        The method's text.
    """
    start = SHELL.index(signature)
    return SHELL[start : SHELL.index("\n  },\n", start)]


def test_the_lock_is_one_name_for_the_whole_origin():
    assert 'const ACTIVE_LOCK = "neutrino_active_tab";' in SHELL
    assert SHELL.count("navigator.locks.request(ACTIVE_LOCK, options,") == 1


def test_a_tab_connects_only_once_it_holds_the_lock():
    start = member("async start() {")
    factless = start.index('this.showFactless(from !== "")')
    taken = start.index("await active.take();")
    assert factless < taken
    assert taken < start.index("worker.start(")
    assert taken < start.index("openSession(")
    assert taken < start.index("stats.startedAt = performance.now();")


def test_a_tab_takes_the_free_lock_and_waits_for_a_held_one():
    take = member("  take() {\n    return new Promise((resolve) => {")
    assert (
        "\n      this.request({ ifAvailable: true }).then((isTaken) => { if (!isTaken) this.wait(); });"
        in take
    )
    wait = member("  wait() {")
    queued = wait.index("this.request({ signal: queued.signal });")
    shown = wait.index("screen.waiting(")
    assert queued < shown


def test_use_here_drops_the_queued_request_and_steals_the_lock():
    wait = member("  wait() {")
    held = wait.index("if (this.isHeld) return;")
    dropped = wait.index("queued.abort();")
    stolen = wait.index("this.request({ steal: true });")
    assert held < dropped < stolen


def test_a_tab_that_loses_the_lock_to_a_steal_leaves():
    request = member("  request(options) {")
    assert (
        ".catch(() => { if (grant && grant === this.grants) page.leave(); });"
        in request
    )
    assert "grant = ++this.grants;" in request
    leave = member("  leave() {")
    ended = leave.index("this.isEnded = true;")
    closed = leave.index("this.session.close();")
    marked = leave.index(
        'if (this.hasAppShown) sessionStorage.setItem(KEPT_MOVED, "1");'
    )
    removed = leave.index('document.getElementById("app").remove();')
    reloaded = leave.index("location.reload();")
    assert ended < closed < marked < removed < reloaded
    assert "sessionStorage.removeItem(KEPT_ACTIVE);" in leave


def test_the_tab_that_takes_the_lock_marks_itself_active():
    request = member("  request(options) {")
    marked = request.index('sessionStorage.setItem(KEPT_ACTIVE, "1");')
    assert marked < request.index("this.onTaken();")


def test_a_tab_is_moved_only_once_its_app_has_shown():
    check = member("  async check(deadline) {")
    shown = check.index("this.hasAppShown = true;")
    assert shown < check.index("sessionStorage.removeItem(KEPT_MOVED);")
    leave = member("  leave() {")
    assert (
        'screen.refuse(sessionStorage.getItem(KEPT_MOVED) ? "moved" : "elsewhere");'
        in leave
    )


def test_a_reload_of_the_active_tab_steals_the_lock_back():
    take = member("  take() {\n    return new Promise((resolve) => {")
    assert "if (isActiveReload()) { this.request({ steal: true }); return; }" in take
    reload = SHELL[SHELL.index("function isActiveReload() {") :]
    reload = reload[: reload.index("\n}\n")]
    assert 'navigation.type === "reload"' in reload
    assert 'sessionStorage.getItem(KEPT_ACTIVE) === "1"' in reload


def test_every_load_but_the_active_tab_s_reload_removes_the_mark_before_it_asks():
    take = member("  take() {\n    return new Promise((resolve) => {")
    reload = take.index(
        "if (isActiveReload()) { this.request({ steal: true }); return; }"
    )
    removed = take.index("sessionStorage.removeItem(KEPT_ACTIVE);")
    asked = take.index("this.request({ ifAvailable: true })")
    assert reload < removed < asked


def test_an_ended_share_releases_the_lock():
    end = member("  endShare() {")
    assert "sessionStorage.removeItem(KEPT_ACTIVE);" in end
    assert "if (active.release) active.release();" in end


def test_a_moved_tab_shows_the_moved_screen():
    wait = member("  wait() {")
    assert (
        'screen.waiting(sessionStorage.getItem(KEPT_MOVED) ? "moved" : "elsewhere", () => {'
        in wait
    )


def test_the_waiting_screens_carry_iffi_s_words():
    for language, words in WAITING_WORDS.items():
        block = re.search(rf"\n  {language}: \{{\n(.*?)\n  \}},", SHELL, re.S).group(1)
        for key, text in words.items():
            assert f"    {key}: {text}," in block, (language, key)


def test_only_the_waiting_screens_show_the_button():
    assert '<button id="use" class="hidden" type="button"></button>' in INDEX
    waiting = member("  waiting(kind, onUse) {")
    assert "button.textContent = words.useHere;" in waiting
    assert 'button.classList.remove("hidden");' in waiting
    for signature in ("  refuse(kind) {", "  loading(title) {"):
        assert 'this.element("use").classList.add("hidden");' in member(signature)


def test_the_page_reads_its_lock_client_from_a_lock_of_its_own():
    own = SHELL[SHELL.index("function ownLockClient(tab) {") :]
    own = own[: own.index("\n}\n")]
    assert 'const name = "neutrino_tab_" + tab;' in own
    assert "const own = held.find((lock) => lock.name === name);" in own
    start = member("  async start(cache) {")
    read = start.index("this.lockClient = await ownLockClient(this.tab);")
    assert read < start.index("await this.announce();")
