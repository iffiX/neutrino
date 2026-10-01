"""Capture the guide's screenshots from a live panel and the client's window.

Reads ``shots.json``, signs in to the panel, switches the panel's language for
each language's shots and puts the language back at the end, and for every
shot sets the viewport, opens the page, waits for the element, redraws a
QR code from the shot's ``redraw_qr`` stand-in, replaces what
``redact.json`` names inside the page, and writes the element at twice the
pixel density to ``images/guide/<language>/<file>``. Each shot's
replacements are printed after it.

Client shots are taken from the client's own window page, served by
``client_window.py`` from ``client_state.json``. App and OS shots are listed
and skipped; the README says how they are taken.

Run it from a machine that reaches the panel::

    python3 capture.py --panel https://192.168.50.1:8443 --headed

Playwright for Python is a development dependency: ``pip install -e
"hub[screenshots]"`` and ``python3 -m playwright install chromium``.
"""

import argparse
import getpass
import json
import os
import pathlib
import re
import sys

import qrcode
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
CAPTURED_SOURCES = ("panel", "client")
DEVICE_SCALE = 2
WAIT_TIMEOUT_MS = 30_000
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


# The panel's QR code element, and the border it draws around the code.
QR_SELECTOR = ".qr_code"
QR_BORDER_MODULES = 4

# Runs inside the page: draws the given modules into every QR code element,
# one unit square per dark module, and returns how many it redrew.
REDRAW_QR_SCRIPT = """
([selector, modules]) => {
  const size = modules.length;
  const parts = [];
  modules.forEach((cells, row) => cells.forEach((isDark, col) => {
    if (isDark) parts.push('M' + col + ' ' + row + 'h1v1h-1z');
  }));
  const codes = document.querySelectorAll(selector);
  for (const code of codes) {
    code.setAttribute('viewBox', '0 0 ' + size + ' ' + size);
    for (const rect of code.querySelectorAll('rect')) {
      rect.setAttribute('width', size);
      rect.setAttribute('height', size);
    }
    for (const path of code.querySelectorAll('path')) {
      path.setAttribute('d', parts.join(''));
    }
  }
  return codes.length;
}
"""


def qr_modules(text: str) -> list:
    """The dark modules of a QR code of ``text``, border included, by row."""
    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, border=QR_BORDER_MODULES
    )
    code.add_data(text)
    code.make(fit=True)
    return code.get_matrix()


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


def take(
    page, shot: dict, labels: dict, rules: list, *, base_url: str, viewports: dict
) -> None:
    """Take one shot and print what was replaced in it.

    Args:
        page: The Playwright page.
        shot: The shot table's entry.
        labels: The labels of the shot's language.
        rules: The redaction rules.
        base_url: Where the panel or the client page is served.
        viewports: The table's viewport sizes.

    Raises:
        playwright.sync_api.Error: When the page or the element does not appear.
    """
    page.set_viewport_size(viewports[shot["viewport"]])
    page.goto(base_url + shot.get("url", "/"))
    if shot.get("manual"):
        print(f"\n{shot['language']}/{shot['file']}: {shot['manual']}")
        input("Press Enter when the page shows it. ")
    page.wait_for_selector(resolve(shot["wait_for"], labels), timeout=WAIT_TIMEOUT_MS)
    page.wait_for_load_state("networkidle")
    if shot.get("redraw_qr"):
        redrawn = page.evaluate(
            REDRAW_QR_SCRIPT, [QR_SELECTOR, qr_modules(shot["redraw_qr"])]
        )
        print(f"  {redrawn} QR code redrawn from {shot['redraw_qr']}")
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


def main() -> int:
    """Take the selected shots.

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
    arguments = parser.parse_args()
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
    if panel_shots and not arguments.panel:
        parser.error("panel shots need --panel")
    is_headed = arguments.headed or any(
        shot.get("manual") for shot in panel_shots + client_shots
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not is_headed)
        try:
            capture_panel(browser, panel_shots, rules, arguments, table["viewports"])
            capture_client(browser, client_shots, rules, table["viewports"])
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
