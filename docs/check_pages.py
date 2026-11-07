#!/usr/bin/env python3
"""Check every Chinese manual page of the site against the length and word limits.

Run: python3 tmp-docs/docs_draft/check_pages.py

Reports per page: the value line's length, the lines above the first H2, the
total lines and the longest clause. Exits 1 when any page fails.

A line under the title is one list item, one table row (the separator row is
not counted) or one plain paragraph. A code group is one line, since one tab
shows at a time. A grey picture box is not a line.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP = {"index.md", "app.md", "README.md", "SOURCES.md", "layout_demo.md"}
EXPECTED_PAGES = 59

VALUE_MIN, VALUE_MAX = 10, 60
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
    "deploy/containers.md": 80,
}
CLAUSE_MAX = 40
LABEL_MAX = 30
PICTURES_MAX = 2
PICTURE_LIMITS = {"access/sakurafrp.md": 3, "access/openfrp.md": 3}

APP_PAGES = {
    f"deploy/{name}.md"
    for name in (
        "cloudcli codeg hermes_webui vscode code_server terminal ssh gitea "
        "ayakaleaf siyuan remote_desktop file_share containers claude_code codex"
    ).split()
}
APP_HEADINGS = ["支持的系统", "安装", "使用", "分享", "注意", "设置", "卸载"]

BANNED_ALWAYS = [
    "VPN", "翻墙", "收费", "会员", "福瑞", "手搓", "内网穿透", "常开", "我们",
    "—", "Jupyter", "Ollama", "模组", "来自：", "待核", "给谁看", "中微子",
    "Web 分享", "网页分享", "设备页", "证书不匹配", "综上", "总之", "以上就是", "装上",
]
# Words a page uses only inside a label quoted from the screen.
LABEL_ONLY = ["机器"]
# Screen labels quoted in bold that hold a banned word or mark.
VENDOR_LABELS = ["**VPN与设备管理**", "**OpenAI 兼容 — /chat/completions**"]
# Everyday words that stand in for a term, or lines that talk about the page.
TERMS = [
    "钥匙", "认出", "认不出", "认得", "碰到", "碰得到", "碰不到", "守着", "开头字节", "拿掉", "拿走", "点几下",
    "就行", "就好", "看一眼", "一眼", "多半", "同学", "信得过", "勾上", "封着", "一把", "这一块", "小块",
    "小程序", "拷走", "拷出", "存走", "搬到", "这一页", "这里说的", "连回来", "这一关", "归你管", "写着",
    "替你", "替设备", "替浏览器", "不帮", "是这样的", "简单说", "一句话概括", "说白了", "请查看", "请先",
]
# Pages that survey vendors state a reading date.
DATED_PAGES = {
    "compare.md", "access/ways_in.md", "access/sakurafrp.md", "access/openfrp.md",
    "access/netbird.md", "access/easytier.md",
}
DATE = re.compile(r"20\d\d-\d\d-\d\d")
# Protection thresholds stay out of the manual.
THRESHOLDS = re.compile(r"5 到 30 秒|20 到 100|0 到 64|128 个|64 个|512 个|60 秒内|30 次|0x00|0x16|BLAKE2s-")
NETWORK_RIVALS = ("frp", "EasyTier", "NetBird")
PASSIVE = re.compile(r"被(?!控端|动)")
CLAUSE_SPLIT = re.compile(r"[，。；：、！？,;]")


def visible(text: str) -> str:
    """Return a line as the reader sees it, with the Markdown marks removed."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.replace("**", "").replace("`", "").strip()


def table_cells(line: str) -> list[str]:
    """Return the visible cells of one table row."""
    return [visible(cell) for cell in line.strip().strip("|").split("|")]


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
    if len(value) < VALUE_MIN:
        failures.append(f"first sentence is {len(value)} characters")
    if re.match(r"\s*([-|#]|\d+\.\s|<|:::|`{3})", rest[value_at]):
        failures.append("no plain value line right under the title")

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
            if level > 4:
                failures.append(f"heading too deep: {stripped}")
            if stripped.rstrip()[-1] in "：:。.？?":
                failures.append(f"heading ends in punctuation: {stripped}")
            if level == 2:
                headings.append(stripped.lstrip("# ").strip())
            above_first_heading = False
            continue
        if stripped.startswith("<div"):
            pictures += 1
            label = re.sub(r"<[^>]+>", "", stripped)
            if len(label) > LABEL_MAX:
                failures.append(f"picture label is {len(label)} characters")
            continue
        if re.fullmatch(r"\|[\s:|-]+\|", stripped):
            continue
        if stripped.startswith("|"):
            lines.append(("row", "  ".join(table_cells(stripped))))
            top_lines += above_first_heading
            continue
        lines.append(("line", visible(re.sub(r"^([-*]|\d+\.)\s+", "", stripped))))
        top_lines += above_first_heading

    readable = [body for kind, body in lines if kind == "line"]
    clauses = [c.strip() for body in readable for c in CLAUSE_SPLIT.split(body)]
    longest = max(clauses, key=len, default="")
    for clause in clauses:
        if len(clause) >= CLAUSE_MAX:
            failures.append(f"{len(clause)} characters in one clause: {clause}")

    if relative in APP_PAGES:
        found = [h for h in headings if h in APP_HEADINGS]
        if found != APP_HEADINGS:
            failures.append(f"app headings are {found}, expected {APP_HEADINGS}")

    quoted = "\n".join(rest)
    for label in VENDOR_LABELS:
        quoted = quoted.replace(label, "")
    words = visible(quoted)
    # A label in bold is spelled as the screen shows it.
    unlabelled = visible(re.sub(r"\*\*[^*]+\*\*", "", "\n".join(rest)))
    for banned in BANNED_ALWAYS:
        if banned in words:
            failures.append(f"banned word: {banned}")
    if PASSIVE.search(unlabelled):
        failures.append("a sentence with 被")
    for word in LABEL_ONLY:
        if word in unlabelled:
            failures.append(f"{word} outside a screen label")
    prose = "\n".join(
        line for line in rest if not line.lstrip().startswith(("![", "<div", "```"))
    )
    prose = visible(re.sub(r"\*\*[^*]+\*\*", "", re.sub(r"`[^`]*`", "", prose)))
    for word in TERMS:
        if word in prose:
            failures.append(f"everyday word: {word}")
    if DATE.search(words) and relative not in DATED_PAGES:
        failures.append("a date on a page that surveys no vendor")
    found = THRESHOLDS.search(words)
    if found:
        failures.append(f"a protection threshold: {found.group(0)}")
    first = re.split(r"[。！？]", value)[0]
    if "？" in value.split("。")[0] or not ("是" in first or "你" in first):
        failures.append(f"first sentence neither defines nor speaks to you: {first}")
    if relative in APP_PAGES and "开始支持的微子·中枢版本" not in words:
        failures.append("no support table with the first version")
    if relative == "compare.md" and any(n in words for n in NETWORK_RIVALS):
        failures.append("compare page names a way to connect")

    return {
        "page": relative,
        "value": len(value),
        "top": top_lines,
        "lines": len(lines),
        "longest": longest,
        "failures": failures,
    }


def main() -> int:
    """Check all pages and print the report."""
    pages = sorted(
        path
        for path in ROOT.rglob("*.md")
        if path.relative_to(ROOT).as_posix() not in SKIP
        and not {"node_modules", ".vitepress", "en"} & set(path.relative_to(ROOT).parts)
    )
    wanted = sys.argv[1:]
    results = [
        check_page(path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in pages
    ]
    print(f"{'page':<34}{'value':>6}{'top':>5}{'lines':>6}{'clause':>7}")
    for result in results:
        if wanted and result["page"] not in wanted:
            continue
        mark = "" if not result["failures"] else "  FAIL"
        print(
            f"{result['page']:<34}{result['value']:>6}{result['top']:>5}{result['lines']:>6}"
            f"{len(result['longest']):>7}{mark}"
        )
        for failure in result["failures"]:
            print(f"    {failure}")

    openings: dict[str, list[str]] = {}
    for path in pages:
        body = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(body) > 1:
            openings.setdefault(visible(body[1])[:6], []).append(path.relative_to(ROOT).as_posix())
    for start, names in openings.items():
        if len(names) > 1 and not wanted:
            print(f"same opening {start!r}: {', '.join(names)}")

    passing = sum(1 for result in results if not result["failures"])
    print()
    print(f"pages found: {len(results)}, expected {EXPECTED_PAGES}")
    print(f"pages passing: {passing}/{len(results)}")
    return 0 if passing == len(results) == EXPECTED_PAGES else 1


if __name__ == "__main__":
    sys.exit(main())
