#!/usr/bin/env python3
"""Check every English manual page of the site against the length and word limits.

Run: python3 tmp-docs/docs_draft/check_pages_en.py [page ...]

Pages are paths under en/, such as hub/install.md; with none, every page is
checked. Reports per page: the value line's words, the lines above the first
H2, the total lines and the longest sentence. Exits 1 when any page fails.

A line under the title is one list item, one table row (the separator row is
not counted) or one plain paragraph. A code group is one line, since one tab
shows at a time. A grey picture box is not a line.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "en"
SKIP = {"index.md", "app.md"}
EXPECTED_PAGES = 59

VALUE_MIN, VALUE_MAX = 6, 45
TOP_LINES_MAX = 10
PAGE_LINES_MAX = 60
LONG_PAGES = {
    "reference/troubleshooting.md": 400,
    "reference/nclient.md": 120,
    "reference/nhub.md": 80,
    "reference/nagent.md": 80,
    "reference/platforms.md": 100,
    "reference/glossary.md": 90,
    "reference/panel_menu.md": 90,
    "hub/uninstall.md": 80,
    "hub/install.md": 80,
    "hub/network.md": 80,
    "hub/proxy.md": 80,
    "hub/settings.md": 80,
    "hub/what_it_holds.md": 80,
    "access/desktop.md": 80,
    "share/web_share.md": 80,
    "share/security.md": 120,
    "deploy/containers.md": 80,
}
SENTENCE_MAX = 25
LABEL_MAX = 20

APP_PAGES = {
    f"deploy/{name}.md"
    for name in (
        "cloudcli codeg hermes_webui vscode code_server terminal ssh gitea "
        "ayakaleaf siyuan remote_desktop file_share containers claude_code codex"
    ).split()
}
APP_HEADINGS = ["Supported systems", "Install", "Use", "Share", "Risks and limits", "Settings", "Uninstall"]

# skills/doc-author/english.md "Banned words" and "Voice", plus the promotion rules.
BANNED_WORDS = [
    "simply", "simple", "easy", "easily", "just", "obviously", "please", "currently", "utilize",
    "utilizes", "leverage", "via", "may", "might", "should", "above", "below", "robust", "seamless",
    "seamlessly", "powerful", "comprehensive", "delve", "harness", "embark", "landscape", "tapestry",
    "we", "us", "our", "let's", "I", "click", "clicks", "once", "VPN", "Moreover", "Furthermore",
    "Additionally", "Firstly", "Secondly", "Ultimately",
]
BANNED_PHRASES = [
    "note that", "it is worth noting", "keep in mind", "at the moment", "for now", "in order to",
    "e.g.", "i.e.", "etc.", "and/or", "navigate to", "In conclusion", "In short", "as mentioned",
    "this page", "Here's", "Below you'll find", "—", "–", "Neutrino Hub's",
]
BANNED_WORD = re.compile(r"\b(" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b", re.IGNORECASE)
# Pages that survey vendors state a reading date.
DATED_PAGES = {
    "compare.md", "access/ways_in.md", "access/sakurafrp.md", "access/openfrp.md",
    "access/netbird.md", "access/easytier.md",
}
DATE = re.compile(r"20\d\d-\d\d-\d\d")
# Protection thresholds stay out of the manual.
THRESHOLDS = re.compile(
    r"5 to 30 seconds|20 to 100|0 to 64|128 connections|64 connections|512 connections|"
    r"within 60 seconds|30 attempts|0x00|0x16|BLAKE2s-"
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?:;])\s+")


def visible(text: str) -> str:
    """Return a line as the reader sees it, with the Markdown marks removed."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.replace("**", "").replace("`", "").strip()


def prose(text: str) -> str:
    """Return a line without bold labels, inline code and link targets."""
    text = re.sub(r"\*\*[^*]+\*\*", "", text)
    text = re.sub(r"`[^`]*`", "", text)
    return visible(text)


def table_cells(line: str) -> list[str]:
    """Return the visible cells of one table row."""
    return [visible(cell) for cell in line.strip().strip("|").split("|")]


def words(text: str) -> int:
    """Return the number of words in a line."""
    return len(re.findall(r"[A-Za-z0-9][\w'./:-]*", text))


def check_page(relative: str, text: str) -> dict:
    """Measure one page and collect its failures."""
    failures = []
    source = text.splitlines()
    title_at = next((i for i, l in enumerate(source) if l.strip()), 0)
    if not source[title_at].startswith("# "):
        failures.append("the first line is not a title")
    rest = source[title_at + 1 :]
    value_at = next((i for i, l in enumerate(rest) if l.strip()), 0)
    value = visible(rest[value_at]) if rest else ""
    value_words = words(re.split(r"(?<=\.)\s", value)[0])
    if not VALUE_MIN <= value_words <= VALUE_MAX:
        failures.append(f"first sentence is {value_words} words")
    if re.match(r"\s*([-|#]|\d+\.\s|<|:::|`{3})", rest[value_at]):
        failures.append("no plain value line right under the title")
    first = re.split(r"(?<=\.)\s", value)[0]
    if not re.search(r"\b(is|are|you|your)\b", first, re.IGNORECASE):
        failures.append(f"first sentence neither defines nor speaks to you: {first}")

    lines, headings, top_lines, pictures = [], [], 0, 0
    in_fence, in_group, above_first_heading = False, False, True
    for raw in rest[value_at + 1 :]:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            if not in_group:
                lines.append(("command", stripped))
                top_lines += above_first_heading
            continue
        if stripped.startswith(":::"):
            if stripped != ":::":
                lines.append(("command", "(block)"))
                top_lines += above_first_heading
            in_group = stripped != ":::"
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading = stripped.lstrip("# ").strip()
            if level > 4:
                failures.append(f"heading too deep: {stripped}")
            if heading[-1] in ".:?!":
                failures.append(f"heading ends in punctuation: {stripped}")
            if "**" in heading:
                failures.append(f"bold inside a heading: {stripped}")
            if level == 2:
                headings.append(heading)
            above_first_heading = False
            continue
        if stripped.startswith("<div"):
            pictures += 1
            continue
        if stripped.startswith("!["):
            label = re.match(r"!\[([^\]]*)\]", stripped)
            if label and words(label.group(1)) > LABEL_MAX:
                failures.append(f"picture label is {words(label.group(1))} words")
            continue
        if re.fullmatch(r"\|[\s:|-]+\|", stripped):
            continue
        if stripped.startswith("|"):
            lines.append(("row", " | ".join(table_cells(stripped))))
            top_lines += above_first_heading
            continue
        lines.append(("line", re.sub(r"^([-*]|\d+\.)\s+", "", stripped)))
        top_lines += above_first_heading

    budget = LONG_PAGES.get(relative, PAGE_LINES_MAX)
    if len(lines) > budget:
        failures.append(f"{len(lines)} lines, budget {budget}")
    if top_lines > TOP_LINES_MAX:
        failures.append(f"{top_lines} lines above the first heading")

    longest = 0
    for kind, body in lines:
        if kind != "line":
            continue
        for sentence in SENTENCE_SPLIT.split(visible(body)):
            count = words(sentence)
            longest = max(longest, count)
            if count > SENTENCE_MAX:
                failures.append(f"{count} words in one sentence: {sentence[:90]}")

    if relative in APP_PAGES:
        found = [h for h in headings if h in APP_HEADINGS]
        if found != APP_HEADINGS:
            failures.append(f"app headings are {found}, expected {APP_HEADINGS}")

    text_prose = "\n".join(
        prose(line) for line in rest if not line.lstrip().startswith(("![", "<", "```", "|---"))
    )
    for found in sorted(set(BANNED_WORD.findall(text_prose))):
        failures.append(f"banned word: {found}")
    lowered = text_prose.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in lowered:
            failures.append(f"banned phrase: {phrase}")
    whole = "\n".join(rest)
    if DATE.search(whole) and relative not in DATED_PAGES:
        failures.append("a date on a page that surveys no vendor")
    found = THRESHOLDS.search(whole)
    if found:
        failures.append(f"a protection threshold: {found.group(0)}")
    return {
        "value": value_words,
        "top": top_lines,
        "lines": len(lines),
        "longest": longest,
        "failures": failures,
    }


def main() -> int:
    """Check the named pages, or every page, and print one row each."""
    if len(sys.argv) > 1:
        pages = [ROOT / name for name in sys.argv[1:]]
    else:
        pages = sorted(p for p in ROOT.rglob("*.md") if p.relative_to(ROOT).as_posix() not in SKIP)
    passing = 0
    for page in pages:
        relative = page.relative_to(ROOT).as_posix()
        if not page.exists():
            print(f"{relative:36s} missing")
            continue
        report = check_page(relative, page.read_text(encoding="utf-8"))
        mark = "" if not report["failures"] else "  FAIL"
        print(f"{relative:36s} {report['value']:4d} {report['top']:4d} {report['lines']:5d} {report['longest']:5d}{mark}")
        for failure in report["failures"]:
            print(f"    {failure}")
        passing += not report["failures"]
    print()
    if len(sys.argv) == 1:
        print(f"pages found: {len(pages)}, expected {EXPECTED_PAGES}")
    print(f"pages passing: {passing}/{len(pages)}")
    return 0 if passing == len(pages) and (len(sys.argv) > 1 or len(pages) == EXPECTED_PAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
