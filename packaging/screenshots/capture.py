"""Capture the guide's screenshots from a live panel, the client's window and the consoles.

Reads ``shots.json``, signs in to the panel, switches the panel's language for
each language's shots and puts the language back at the end, and for every
shot sets the viewport, opens the page, waits for the element, redraws a
QR code from the shot's ``redraw_qr`` stand-in, hides what the shot's ``hide``
selectors match, replaces what ``redact.json`` names inside the page, and
writes the element at twice the pixel density to
``images/guide/<language>/<file>``. Each shot's replacements are printed
after it.

Client shots are taken from the client's own window page, served by
``client_window.py`` from ``client_state.json``. Console shots open an
absolute URL in a browser profile kept outside the repository, signed in once
with ``--console-login``. App and OS shots are listed and skipped; the README
says how they are taken.

Run it from a machine that reaches the panel::

    python3 capture.py --panel https://192.168.50.1:8443 --headed
    python3 capture.py --console-login https://app.netbird.io/
    python3 capture.py --source console

Playwright for Python is a development dependency: ``pip install -e
"hub[screenshots]"`` and ``python3 -m playwright install chromium``.
"""

import argparse
import base64
import getpass
import io
import json
import os
import pathlib
import re
import sys

import qrcode
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from client_window import ClientWindowServer

HERE = pathlib.Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
SHOTS_FILE = HERE / "shots.json"
REDACT_FILE = HERE / "redact.json"
REDACT_LOCAL_FILE = HERE / "redact.local.json"
CLIENT_STATE_FILE = HERE / "client_state.json"
IMAGES_DIR = REPOSITORY / "images" / "guide"
PANEL_LOCALES = REPOSITORY / "hub" / "frontend" / "src" / "locales"
CLIENT_LOCALES = REPOSITORY / "client" / "desktop" / "frontend" / "locales"

# The shot table's language directories, and the language each one is drawn in.
SHOT_LANGUAGES = {"en": "en", "zh": "zh-CN"}
CAPTURED_SOURCES = ("panel", "client", "console")
# The browser profile the console shots are taken from: the variable that
# names it, and where it goes when the variable is not set.
CONSOLE_PROFILE_VARIABLE = "NEUTRINO_CONSOLE_PROFILE"
CONSOLE_PROFILE_DEFAULT = (
    pathlib.Path.home() / ".cache" / "neutrino" / "screenshots" / "console_profile"
)
DEVICE_SCALE = 2
WAIT_TIMEOUT_MS = 30_000
NETWORK_IDLE_TIMEOUT_MS = 10_000
PRESS_SETTLE_MS = 800
PRESS_TIMEOUT_MS = 5_000
# A label key inside a selector, ``{ui.settings.https_title}``.
LABEL_KEY = re.compile(r"\{(ui\.[A-Za-z0-9_.]+)\}")

# Runs inside the page: replaces each rule's matches in text nodes, input
# values and two attributes, and returns what it replaced per rule.
REDACT_SCRIPT = """
(rules) => {
  const report = {};
  const isPrivate = (address) => {
    const [a, b] = address.split('.').map(Number);
    return a === 10 || a === 127 || a === 0 || a >= 224 ||
      (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) ||
      (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254);
  };
  const scrub = (text) => {
    let result = text;
    for (const rule of rules) {
      const pattern = rule.literal !== undefined
        ? new RegExp(rule.literal.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'), 'g')
        : new RegExp(rule.regex, rule.flags);
      result = result.replace(pattern, (match) => {
        if (rule.is_public_ipv4_only && isPrivate(match)) return match;
        if (match === rule.replace) return match;
        (report[rule.name] = report[rule.name] || []).push(match);
        return rule.replace;
      });
    }
    return result;
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const scrubbed = scrub(node.nodeValue);
    if (scrubbed !== node.nodeValue) node.nodeValue = scrubbed;
  }
  for (const field of document.querySelectorAll('input, textarea')) {
    const scrubbed = scrub(field.value);
    if (scrubbed !== field.value) field.value = scrubbed;
  }
  for (const name of ['title', 'aria-label']) {
    for (const element of document.querySelectorAll('[' + name + ']')) {
      const value = element.getAttribute(name);
      const scrubbed = scrub(value);
      if (scrubbed !== value) element.setAttribute(name, scrubbed);
    }
  }
  return report;
}
"""

# Runs inside the page: hides every element the selectors match, and returns
# how many.
# The panel's QR code image, and the border it draws around the code.
QR_SELECTOR = "img.qr_code"
QR_BORDER_MODULES = 4

# Runs inside the page: points every QR code image at the given PNG, waits
# for each to decode, and returns how many it replaced.
REDRAW_QR_SCRIPT = """
async ([selector, url]) => {
  const images = Array.from(document.querySelectorAll(selector))
    .filter((image) => image.src !== url);
  for (const image of images) {
    image.src = url;
    await image.decode();
  }
  return images.length;
}
"""


def qr_png_url(text: str) -> str:
    """A QR code of ``text`` as a PNG data URL, border included.

    Args:
        text: What the code holds.

    Returns:
        ``data:image/png;base64,`` and the PNG.
    """
    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, border=QR_BORDER_MODULES
    )
    code.add_data(text)
    code.make(fit=True)
    buffer = io.BytesIO()
    code.make_image().save(buffer)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def redraw_qr(page, text: str) -> int:
    """Point the page's QR code images at a code of ``text``.

    Args:
        page: The Playwright page.
        text: The stand-in the code is drawn from.

    Returns:
        How many images were replaced.

    Raises:
        playwright.sync_api.Error: When the page is gone.
    """
    return page.evaluate(REDRAW_QR_SCRIPT, [QR_SELECTOR, qr_png_url(text)])


def hide(page, selectors: list) -> int:
    """Hide every element the selectors match.

    Args:
        page: The Playwright page.
        selectors: Playwright selectors, CSS or its own engines such as
            ``:has-text()``.

    Returns:
        How many elements were hidden.

    Raises:
        playwright.sync_api.Error: When the page is gone or a selector is bad.
    """
    count = 0
    for selector in selectors:
        for handle in page.locator(selector).element_handles():
            handle.evaluate("element => { element.style.visibility = 'hidden'; }")
            count += 1
    return count


def read_rules() -> list:
    """The redaction rules, the local literals after the committed ones.

    Returns:
        One dict per rule, a pattern or a literal, in the order applied.

    Raises:
        OSError: When ``redact.json`` cannot be read.
        json.JSONDecodeError: When a rules file is not JSON.
    """
    rules = []
    files = [REDACT_FILE] + ([REDACT_LOCAL_FILE] if REDACT_LOCAL_FILE.exists() else [])
    for path in files:
        table = json.loads(path.read_text())
        rules.extend(table.get("patterns", []))
        for literal in table.get("literals", []):
            rules.append(
                {
                    "name": f"literal:{literal['find'][:2]}…",
                    "literal": literal["find"],
                    "replace": literal["replace"],
                }
            )
    # Literals go first, so a hub name inside an address is replaced whole.
    return [rule for rule in rules if "literal" in rule] + [
        rule for rule in rules if "literal" not in rule
    ]


def read_labels(directory: pathlib.Path, language: str) -> dict:
    """Every label of one catalog directory or file, by key.

    Args:
        directory: The panel's locales directory or the client's.
        language: ``en`` or ``zh-CN``.

    Returns:
        The labels by key.

    Raises:
        OSError: When a catalog cannot be read.
    """
    labels = {}
    single = directory / f"{language}.json"
    files = (
        [single] if single.exists() else sorted((directory / language).glob("*.json"))
    )
    for path in files:
        labels.update(json.loads(path.read_text()))
    return labels


def resolve(selector: str, labels: dict) -> str:
    """A selector with each ``{label.key}`` replaced by the label's text.

    Args:
        selector: The selector from the shot table.
        labels: The labels of the shot's language.

    Returns:
        The selector Playwright takes.

    Raises:
        KeyError: When a key is not in the catalog.
    """
    return LABEL_KEY.sub(lambda match: labels[match.group(1)], selector)


def masked(value: str) -> str:
    """The first characters of a replaced value, for the report."""
    return value if len(value) <= 4 else value[:4] + "…"


def console_profile() -> pathlib.Path:
    """The browser profile the console shots are taken from, owner-only.

    Returns:
        ``NEUTRINO_CONSOLE_PROFILE``, or
        ``~/.cache/neutrino/screenshots/console_profile`` when it is not set.

    Raises:
        OSError: When the directory cannot be created.
    """
    path = pathlib.Path(
        os.environ.get(CONSOLE_PROFILE_VARIABLE) or CONSOLE_PROFILE_DEFAULT
    ).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def take(
    page, shot: dict, labels: dict, rules: list, *, base_url: str, viewports: dict
) -> None:
    """Take one shot and print what was replaced in it.

    Args:
        page: The Playwright page.
        shot: The shot table's entry.
        labels: The labels of the shot's language.
        rules: The redaction rules.
        base_url: Where the panel or the client page is served; empty for a
            console shot, whose ``url`` is absolute.
        viewports: The table's viewport sizes.

    Raises:
        playwright.sync_api.Error: When the page or the element does not appear.
    """
    page.set_viewport_size(viewports[shot["viewport"]])
    page.goto(
        base_url + shot.get("url", "/"),
        wait_until="load" if base_url else "domcontentloaded",
        timeout=WAIT_TIMEOUT_MS * 2,
    )
    if shot.get("manual"):
        print(f"\n{shot['language']}/{shot['file']}: {shot['manual']}")
        input("Press Enter when the page shows it. ")
    page.wait_for_selector(resolve(shot["wait_for"], labels), timeout=WAIT_TIMEOUT_MS)
    for selector in shot.get("press", []):
        target = page.locator(resolve(selector, labels)).first
        try:
            target.click(timeout=PRESS_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            print(f"  nothing to press for {selector}")
            continue
        page.wait_for_timeout(PRESS_SETTLE_MS)
    for selector, text in shot.get("fill", {}).items():
        page.locator(resolve(selector, labels)).first.fill(text)
    if shot.get("wait_after"):
        page.wait_for_selector(
            resolve(shot["wait_after"], labels), timeout=WAIT_TIMEOUT_MS
        )
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        print("  the page kept talking; taken after the wait_for element appeared")
    if shot.get("redraw_qr"):
        redrawn = redraw_qr(page, shot["redraw_qr"])
        if redrawn:
            print(f"  {redrawn} QR code redrawn from {shot['redraw_qr']}")
        else:
            print(f"  no {QR_SELECTOR} in the page, nothing redrawn")
    if shot.get("hide"):
        hidden = hide(page, [resolve(selector, labels) for selector in shot["hide"]])
        print(f"  {hidden} elements hidden")
    report = page.evaluate(REDACT_SCRIPT, rules)
    target = IMAGES_DIR / shot["language"] / shot["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if shot["element"] == "viewport":
        page.screenshot(path=str(target))
    else:
        page.locator(resolve(shot["element"], labels)).first.screenshot(
            path=str(target)
        )
    print(f"{target.relative_to(REPOSITORY)}")
    for name, values in sorted(report.items()):
        shown = ", ".join(sorted({masked(value) for value in values}))
        print(f"  {name}: {len(values)} replaced ({shown})")
    if not report:
        print("  nothing replaced")


def panel_language(context, base_url: str, language: str) -> str:
    """Set the panel's language and return the one it had.

    Args:
        context: The signed-in browser context.
        base_url: The panel's address.
        language: ``en`` or ``zh-CN``.

    Returns:
        The language before the change.

    Raises:
        RuntimeError: When the panel rejects the change.
    """
    settings = context.request.get(f"{base_url}/api/hub/setting").json()
    answer = context.request.post(
        f"{base_url}/api/hub/setting/set",
        data={"listen_port": settings["listen_port"], "language": language},
    )
    if not answer.ok:
        raise RuntimeError(f"the panel rejected language {language}: {answer.text()}")
    return str(settings["language"])


def sign_in(context, base_url: str, password: str) -> None:
    """Open a panel session in the browser context.

    Raises:
        RuntimeError: When the panel rejects the password.
    """
    answer = context.request.post(
        f"{base_url}/api/hub/auth/login", data={"password": password}
    )
    if not answer.ok or not answer.json().get("is_authenticated"):
        raise RuntimeError(f"{base_url} rejected the password")


def chosen(shots: list, arguments) -> list:
    """The shots the command line selects."""
    picked = []
    for shot in shots:
        if arguments.only and shot["file"].removesuffix(".png") not in arguments.only:
            continue
        if arguments.language and shot["language"] != arguments.language:
            continue
        if arguments.source and shot["source"] != arguments.source:
            continue
        picked.append(shot)
    return picked


def capture_panel(
    browser, shots: list, rules: list, arguments, viewports: dict
) -> None:
    """Take the panel's shots, one language at a time, and restore the language."""
    if not shots:
        return
    base_url = arguments.panel.rstrip("/")
    password = os.environ.get("NEUTRINO_PANEL_PASSWORD") or getpass.getpass(
        "Panel password: "
    )
    context = browser.new_context(
        device_scale_factor=DEVICE_SCALE,
        ignore_https_errors=arguments.ignore_https_errors,
    )
    sign_in(context, base_url, password)
    original = None
    try:
        for directory, language in SHOT_LANGUAGES.items():
            batch = [shot for shot in shots if shot["language"] == directory]
            if not batch:
                continue
            before = panel_language(context, base_url, language)
            original = before if original is None else original
            labels = read_labels(PANEL_LOCALES, language)
            for shot in batch:
                if shot.get("is_signed_out"):
                    guest = browser.new_context(
                        device_scale_factor=DEVICE_SCALE,
                        ignore_https_errors=arguments.ignore_https_errors,
                    )
                    take(
                        guest.new_page(),
                        shot,
                        labels,
                        rules,
                        base_url=base_url,
                        viewports=viewports,
                    )
                    guest.close()
                else:
                    page = context.new_page()
                    take(
                        page,
                        shot,
                        labels,
                        rules,
                        base_url=base_url,
                        viewports=viewports,
                    )
                    page.close()
    finally:
        if original is not None:
            panel_language(context, base_url, original)
        context.close()


def capture_client(browser, shots: list, rules: list, viewports: dict) -> None:
    """Take the client window's shots from the served page."""
    for directory, language in SHOT_LANGUAGES.items():
        batch = [shot for shot in shots if shot["language"] == directory]
        if not batch:
            continue
        server = ClientWindowServer(state_path=CLIENT_STATE_FILE, language=language)
        server.start()
        context = browser.new_context(device_scale_factor=DEVICE_SCALE)
        labels = read_labels(CLIENT_LOCALES, language)
        try:
            for shot in batch:
                page = context.new_page()
                take(
                    page, shot, labels, rules, base_url=server.url, viewports=viewports
                )
                page.close()
        finally:
            context.close()
            server.stop()


def capture_console(
    playwright, shots: list, rules: list, viewports: dict, cdp_url: str = ""
) -> None:
    """Take the console shots from the signed-in profile, in a visible window.

    Args:
        playwright: The Playwright driver.
        shots: The console entries to take.
        rules: The redaction rules.
        viewports: The viewport table.
        cdp_url: When set, the address of a browser already open on the
            profile, reached over the Chrome DevTools Protocol; its first
            context holds the sign-in; a console's tab already open there is
            reused, so the console keeps its session, and only pages opened
            here are closed. Empty opens the profile directory itself.
    """
    if not shots:
        return
    if cdp_url:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        for shot in shots:
            origin = "/".join(shot["url"].split("/", 3)[:3])
            kept = next((p for p in context.pages if p.url.startswith(origin)), None)
            page = kept or context.new_page()
            session = context.new_cdp_session(page)
            size = viewports[shot["viewport"]]
            session.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": size["width"],
                    "height": size["height"],
                    "deviceScaleFactor": DEVICE_SCALE,
                    "mobile": False,
                },
            )
            try:
                take(page, shot, {}, rules, base_url="", viewports=viewports)
            finally:
                session.detach()
                if kept is None:
                    page.close()
        return
    context = playwright.chromium.launch_persistent_context(
        str(console_profile()), headless=False, device_scale_factor=DEVICE_SCALE
    )
    try:
        for shot in shots:
            page = context.new_page()
            take(page, shot, {}, rules, base_url="", viewports=viewports)
            page.close()
    finally:
        context.close()


def console_login(playwright, urls: list) -> None:
    """Open the consoles in the kept profile, one tab each, to sign in by hand.

    Args:
        playwright: The Playwright driver.
        urls: The consoles' addresses.

    Raises:
        OSError: When the profile directory cannot be created.
        playwright.sync_api.Error: When the browser does not start.
    """
    context = playwright.chromium.launch_persistent_context(
        str(console_profile()), headless=False, device_scale_factor=DEVICE_SCALE
    )
    try:
        pages = list(context.pages)
        for url in urls:
            page = pages.pop() if pages else context.new_page()
            page.goto(url)
        input("Sign in, then press Enter. ")
    finally:
        context.close()


def main() -> int:
    """Take the selected shots, or sign in to the consoles.

    Returns:
        0 when every selected shot was taken.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--panel", help="the panel's address, for panel shots")
    parser.add_argument("--only", nargs="+", help="file names without .png")
    parser.add_argument("--language", choices=sorted(SHOT_LANGUAGES))
    parser.add_argument("--source", choices=CAPTURED_SOURCES)
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument(
        "--ignore-https-errors",
        action="store_true",
        help="accept a panel certificate the browser does not trust",
    )
    parser.add_argument(
        "--console-cdp",
        metavar="URL",
        help="take console shots through a browser already open on the profile, "
        "reached over the DevTools protocol at this address",
    )
    parser.add_argument(
        "--console-login",
        nargs="+",
        metavar="URL",
        help="open each console in the kept profile to sign in, then exit",
    )
    arguments = parser.parse_args()
    if arguments.console_login:
        with sync_playwright() as playwright:
            console_login(playwright, arguments.console_login)
        return 0
    table = json.loads(SHOTS_FILE.read_text())
    shots = chosen(table["shots"], arguments)
    rules = read_rules()
    for shot in shots:
        if shot["source"] not in CAPTURED_SOURCES:
            print(
                f"skipped {shot['language']}/{shot['file']}: {shot['source']} shot, see README.md"
            )
    panel_shots = [shot for shot in shots if shot["source"] == "panel"]
    client_shots = [shot for shot in shots if shot["source"] == "client"]
    console_shots = [shot for shot in shots if shot["source"] == "console"]
    if panel_shots and not arguments.panel:
        parser.error("panel shots need --panel")
    is_headed = arguments.headed or any(
        shot.get("manual") for shot in panel_shots + client_shots
    )
    with sync_playwright() as playwright:
        if panel_shots or client_shots:
            browser = playwright.chromium.launch(headless=not is_headed)
            try:
                capture_panel(
                    browser, panel_shots, rules, arguments, table["viewports"]
                )
                capture_client(browser, client_shots, rules, table["viewports"])
            finally:
                browser.close()
        capture_console(
            playwright,
            console_shots,
            rules,
            table["viewports"],
            cdp_url=arguments.console_cdp or "",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
