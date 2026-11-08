"""Open the built panel demo in a headless browser and check that it draws.

    python3 packaging/ci/check_demo.py demo/dist

Runs on: any machine whose Python has Playwright, with its Chromium
installed by ``python -m playwright install chromium``. Serves the folder at
``/demo/`` on a loopback port and opens the demo twice: as it opens, in
Chinese as the mainland edition, and with ``?lang=en``, in English as the
international edition. Each time the panel's frame opens each page of
``DEMO_PANEL_ROUTES`` and the Proxy page, and the client's frame each tab of
the phone's bar. A page or a tab that fails to draw, an error panel, a Proxy
page in the mainland edition, an uncaught exception, a console error and a
file of the demo the server lacks each fail the check.

Not pure: starts a web server on loopback and a browser.
"""

import argparse
import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# The path the demo is served under, as the site serves it.
DEMO_PATH = "/demo/"
# The window: wide enough for the panel and the phone side by side.
DEMO_VIEWPORT = {"width": 1440, "height": 900}
DEMO_PANEL_FRAME = "#panel_half iframe"
DEMO_CLIENT_FRAME = "#client_frame"
# The panel pages opened in each run, by their hash routes.
DEMO_PANEL_ROUTES = (
    "#/",
    "#/network",
    "#/overlay",
    "#/ai",
    "#/agents",
    "#/clients",
    "#/services",
    "#/credentials",
    "#/settings",
)
DEMO_PROXY_ROUTE = "#/proxy"
# The longest a page, a tab or the demo itself takes to draw.
DEMO_DRAW_TIMEOUT_MS = 15000
DEMO_OPEN_ROUTE = "(route) => { window.location.hash = route; }"
# The panel page drawn: its heading, with no skeleton and no error panel left.
DEMO_PANEL_DRAWN = """() => {
  const page = document.querySelector(".page");
  const heading = page && page.querySelector("h1");
  return page !== null && heading !== null && heading.textContent.trim() !== ""
    && page.querySelector(".skeleton") === null
    && document.querySelector(".error_panel") === null;
}"""
DEMO_PANEL_HEADING = "() => document.querySelector('.page h1').textContent.trim()"
DEMO_PANEL_NOT_FOUND = "() => document.querySelector('.not_found_face') !== null"
# The phone draws no AI tab.
DEMO_CLIENT_TABS = "#tabs button.tab:visible"
# The client tab drawn: the pressed tab marked open, a title and some content.
DEMO_CLIENT_DRAWN = """(label) => {
  const open = document.querySelector("#tabs button.tab.on");
  const content = document.getElementById("content");
  return open !== null && open.textContent.trim() === label
    && document.getElementById("page_title").textContent.trim() !== ""
    && content !== null && content.textContent.trim() !== "";
}"""
DEMO_CLIENT_TITLE = "() => document.getElementById('page_title').textContent.trim()"
DEMO_LANGUAGE = "() => document.documentElement.lang"


class DemoHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the demo's folder under ``DEMO_PATH`` and nothing else."""

    def translate_path(self, path: str) -> str:
        """Map a path under ``DEMO_PATH`` into the folder.

        Args:
            path: The request's path.

        Returns:
            The file's path, or a path that does not exist for a request
            outside ``DEMO_PATH``.
        """
        if not path.startswith(DEMO_PATH):
            return str(Path(self.directory) / "outside_the_demo")
        return super().translate_path("/" + path[len(DEMO_PATH) :])

    def log_message(self, format: str, *arguments) -> None:
        """Print nothing for each request."""


class DemoRunFailures:
    """The failures of one run, as the page's events report them.

    Args:
        run: The run's label, at the start of each line.
    """

    def __init__(self, *, run: str) -> None:
        self.run = run
        self.lines = []

    def add(self, text: str) -> None:
        """Keep one failure.

        Args:
            text: What failed.
        """
        self.lines.append(f"{self.run} {text}")

    def on_page_error(self, error) -> None:
        """Keep an uncaught exception of the page or a frame.

        Args:
            error: Playwright's error.
        """
        self.add(f"page error: {error}")

    def on_console(self, message) -> None:
        """Keep a console error.

        Args:
            message: Playwright's console message.
        """
        if message.type == "error":
            self.add(f"console error: {message.text}")

    def on_response(self, response) -> None:
        """Keep a failed request for a file of the demo.

        Args:
            response: Playwright's response.
        """
        if response.status >= 400 and DEMO_PATH in response.url:
            self.add(f"{response.status} for {response.url}")


def main() -> int:
    """Serve the demo, open it twice, and print what was checked.

    Returns:
        The process exit status: 0 when every check passed, 1 otherwise.

    Raises:
        SystemExit: When the folder holds no ``index.html``.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", help="the built demo, holding index.html")
    arguments = parser.parse_args()
    folder = Path(arguments.folder).resolve()
    if not (folder / "index.html").is_file():
        raise SystemExit(f"{folder} holds no index.html; run npm run build in demo")

    handler = functools.partial(DemoHandler, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f"http://127.0.0.1:{server.server_address[1]}{DEMO_PATH}"
    failures = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                failures += check_run(browser, address, "zh-CN")
                failures += check_run(browser, f"{address}?lang=en", "en")
            finally:
                browser.close()
    finally:
        server.shutdown()
    for failure in failures:
        print(f"FAIL {failure}", flush=True)
    print(f"{len(failures)} failures", flush=True)
    return 1 if failures else 0


def check_run(browser, url: str, language: str) -> list:
    """Open the demo once and walk its panel pages and client tabs.

    Args:
        browser: The Playwright browser.
        url: The demo's address, with its query.
        language: ``zh-CN`` or ``en``, the language the demo opens in. In
            English it opens as the international edition.

    Returns:
        One line per failure, each naming the run and what failed.
    """
    failures = DemoRunFailures(run=f"[{language}]")
    page = browser.new_page(viewport=DEMO_VIEWPORT)
    page.on("pageerror", failures.on_page_error)
    page.on("console", failures.on_console)
    page.on("response", failures.on_response)
    try:
        page.goto(url, wait_until="load")
        page.wait_for_selector(
            "#demo_loading", state="detached", timeout=DEMO_DRAW_TIMEOUT_MS
        )
        panel = frame_of(page, DEMO_PANEL_FRAME)
        client = frame_of(page, DEMO_CLIENT_FRAME)
        check_languages(failures, page.main_frame, panel, client, language)
        for route in DEMO_PANEL_ROUTES:
            check_panel_page(failures, panel, route)
        check_proxy_page(failures, panel, is_international=language == "en")
        check_client_tabs(failures, client)
    except PlaywrightError as error:
        failures.add(f"{type(error).__name__}: {error}")
    finally:
        page.close()
    return failures.lines


def frame_of(page, selector: str):
    """The frame an iframe of the page holds.

    Args:
        page: The demo's page.
        selector: The iframe's selector.

    Returns:
        The Playwright frame.
    """
    return page.locator(selector).first.element_handle().content_frame()


def check_languages(failures, top, panel, client, language: str) -> None:
    """Check the page and both frames are in the run's language.

    Args:
        failures: The run's failures.
        top: The page's own frame.
        panel: The panel's frame.
        client: The client's frame.
        language: The language the run opens in.
    """
    for side, frame in (("page", top), ("panel", panel), ("client", client)):
        found = frame.evaluate(DEMO_LANGUAGE)
        if found != language:
            failures.add(f"the {side} is in {found!r}, not {language!r}")
        else:
            print(f"{failures.run} {side} in {found}", flush=True)


def check_panel_page(failures, panel, route: str) -> None:
    """Open one panel page and wait until it draws.

    Args:
        failures: The run's failures.
        panel: The panel's frame.
        route: The page's hash route.
    """
    if not open_panel_page(failures, panel, route):
        return
    if panel.evaluate(DEMO_PANEL_NOT_FOUND):
        failures.add(f"the panel page {route} is not found")
        return
    heading = panel.evaluate(DEMO_PANEL_HEADING)
    print(f"{failures.run} panel {route}: {heading}", flush=True)


def check_proxy_page(failures, panel, *, is_international: bool) -> None:
    """Check the Proxy page draws in the international edition alone.

    Args:
        failures: The run's failures.
        panel: The panel's frame.
        is_international: Whether the run opens the international edition.
    """
    if not open_panel_page(failures, panel, DEMO_PROXY_ROUTE):
        return
    is_not_found = panel.evaluate(DEMO_PANEL_NOT_FOUND)
    if is_international and is_not_found:
        failures.add("the international edition has no Proxy page")
    elif not is_international and not is_not_found:
        failures.add("the mainland edition has a Proxy page")
    else:
        shown = "not found" if is_not_found else "drawn"
        print(f"{failures.run} panel {DEMO_PROXY_ROUTE}: {shown}", flush=True)


def open_panel_page(failures, panel, route: str) -> bool:
    """Open a panel page by its route and wait until it draws.

    Args:
        failures: The run's failures.
        panel: The panel's frame.
        route: The page's hash route.

    Returns:
        Whether the page drew within ``DEMO_DRAW_TIMEOUT_MS``.
    """
    panel.evaluate(DEMO_OPEN_ROUTE, route)
    try:
        panel.wait_for_function(DEMO_PANEL_DRAWN, timeout=DEMO_DRAW_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        failures.add(f"the panel page {route} did not draw")
        return False
    return True


def check_client_tabs(failures, client) -> None:
    """Press each tab of the phone's bar and wait until it draws.

    Args:
        failures: The run's failures.
        client: The client's frame.
    """
    count = client.locator(DEMO_CLIENT_TABS).count()
    if count == 0:
        failures.add("the client has no tab")
    for index in range(count):
        tab = client.locator(DEMO_CLIENT_TABS).nth(index)
        label = tab.inner_text().strip()
        tab.click(timeout=DEMO_DRAW_TIMEOUT_MS)
        try:
            client.wait_for_function(
                DEMO_CLIENT_DRAWN, arg=label, timeout=DEMO_DRAW_TIMEOUT_MS
            )
        except PlaywrightTimeoutError:
            failures.add(f"the client tab {label!r} did not draw")
            continue
        title = client.evaluate(DEMO_CLIENT_TITLE)
        print(f"{failures.run} client tab {label}: {title}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
