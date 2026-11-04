"""The command line programs' words and catalog entries, held against the standard.

What these pin: Codex and Claude Code are one catalog entry each in the
``code`` category, where the one ``ai_cli`` entry stood, and its words are
gone in both languages; each title is the fixed name; and every key of
ui_text.md's "The command line programs' words" says in both languages what
the standard writes, the ``ui.*`` keys in ``modules.json`` and the
``code.*`` keys in ``codes.json``.
"""

import json
import re
from pathlib import Path

import pytest

from neutrino_hub.modules.devices.constants import DEVICE_MODULE_CATALOG_PATH

HUB_DIR = Path(__file__).resolve().parents[2]
LOCALES_DIR = HUB_DIR / "frontend/src/locales"
UI_TEXT = HUB_DIR.parent / "skills/core-code-author/design/ui_text.md"
LANGUAGES = ("en", "zh-CN")
PROGRAMS = ("claude_code", "codex")
ROW_PATTERN = re.compile(r"^\| `([a-z_.]+)` \| (.+) \| (.+) \|$")


def words(language: str, name: str) -> dict:
    return json.loads((LOCALES_DIR / language / name).read_text(encoding="utf-8"))


def standard_rows() -> dict:
    """Key to ``(English, Chinese)`` from the section of ui_text.md."""
    text = UI_TEXT.read_text(encoding="utf-8")
    start = text.index("## The command line programs' words")
    section = text[start : text.index("\n## ", start + 1)]
    rows = {}
    for line in section.splitlines():
        match = ROW_PATTERN.match(line.strip())
        if match:
            rows[match.group(1)] = (match.group(2), match.group(3))
    return rows


def test_each_program_is_one_entry_of_the_code_category_where_ai_cli_stood():
    catalog = json.loads(DEVICE_MODULE_CATALOG_PATH.read_text(encoding="utf-8"))
    names = [item["name"] for item in catalog["modules"]]
    categories = {item["name"]: item["category"] for item in catalog["modules"]}

    assert "ai_cli" not in names
    assert names[names.index("hermes_webui") + 1 :][:2] == list(PROGRAMS)
    assert {name: categories[name] for name in PROGRAMS} == dict.fromkeys(
        PROGRAMS, "code"
    )


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_ai_cli_entry_and_its_gemini_line_are_gone(language):
    held = words(language, "modules.json")

    assert "ui.module_catalog.ai_cli" not in held
    assert "ui.module_title.ai_cli" not in held
    assert not any("Gemini" in value for key, value in held.items() if "ai_cli" in key)


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_program_s_title_is_its_fixed_name(language):
    held = words(language, "modules.json")

    assert held["ui.module_title.claude_code"] == "Claude Code"
    assert held["ui.module_title.codex"] == "Codex"


def test_the_standard_names_every_key_of_the_programs():
    assert set(standard_rows()) == {
        "ui.module_catalog.codex",
        "ui.module_catalog.claude_code",
        "ui.codex.owner_notice",
        "ui.claude_code.owner_notice",
        "ui.codex.apply",
        "ui.claude_code.apply",
        "ui.program.apply_hint",
        "ui.program.macos_path_hint",
        "code.copy_version_unsupported",
        "code.link_name_taken",
        "code.module_not_service",
    }


@pytest.mark.parametrize("key", sorted(standard_rows()))
def test_each_word_says_what_ui_text_writes_in_both_languages(key):
    english, chinese = standard_rows()[key]
    name = "codes.json" if key.startswith("code.") else "modules.json"

    assert words("en", name)[key] == english
    assert words("zh-CN", name)[key] == chinese
