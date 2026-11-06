"""A module whose data moves forward only, on the machine page, held against the standard.

What these pin: the version dialog greys out each version the view marks
``is_older_than_run``, and **Follow the tested version** while the tested
row is marked, and asks nothing before any other press; no downgrade
dialog and none of its words are left; the tab shows the upgrade only chip
after the kind chip from the row's ``is_data_forward_only``; and its word
says in both languages what ui_text.md writes.
"""

import json
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
DESIGN_DIR = HUB_DIR.parent / "skills/core-code-author/design"
CHIP = {"en": "Upgrade only", "zh-CN": "只能升级"}
GONE = (
    "ui.modules.downgrade_title",
    "ui.modules.downgrade_body",
    "ui.modules.install_version_confirm",
)


def source(name: str) -> str:
    path = FRONTEND_SRC_DIR / "components" / name
    return " ".join(path.read_text(encoding="utf-8").split())


def words(language: str) -> dict:
    path = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_version_older_than_the_newest_run_cannot_be_pressed():
    block = source("module_version_block.tsx")

    assert (
        "disabled={ view.is_locked || entry.is_older_than_run || "
        "busyVersion !== null }"
    ) in block
    assert "onClick={() => void choose(entry.version)}" in block


def test_a_row_that_cannot_be_pressed_is_greyed_out():
    path = FRONTEND_SRC_DIR / "components" / "module_version_block.css"
    css = " ".join(path.read_text(encoding="utf-8").split())

    assert (
        ".module_version_row:disabled { color: var(--color-text-faint); "
        "cursor: default; }"
    ) in css


def test_follow_the_tested_version_is_dead_while_the_tested_one_is_older():
    block = source("module_version_block.tsx")

    assert (
        "const isTestedOlderThanRun = view.versions.some( (entry) => "
        "entry.is_tested && entry.is_older_than_run, );"
    ) in block
    assert "disabled={busyVersion !== null || isTestedOlderThanRun}" in block


def test_no_press_asks_before_it_installs_a_version():
    block = source("module_version_block.tsx")

    assert "useConfirm" not in block
    assert "downgrade" not in block


@pytest.mark.parametrize("language", list(CHIP))
def test_the_downgrade_words_are_gone(language):
    assert not set(GONE) & set(words(language))


def test_the_tab_shows_the_upgrade_only_chip_after_the_kind_chip():
    page = source("machine_modules.tsx")
    chips = page[page.index("function ModuleChips(") :]
    chips = chips[: chips.index("/** ")]

    assert chips.index("{t(kindKey)}") < chips.index(
        '{row.is_data_forward_only && ( <span className="badge">'
        '{t("ui.modules.forward_only")}</span> )}'
    )


@pytest.mark.parametrize("language", list(CHIP))
def test_the_chip_says_what_ui_text_writes(language):
    text = " ".join((DESIGN_DIR / "ui_text.md").read_text(encoding="utf-8").split())

    assert words(language)["ui.modules.forward_only"] == CHIP[language]
    assert (
        "| `ui.modules.forward_only`, the chip of a module whose data moves "
        f"forward only | {CHIP['en']} | {CHIP['zh-CN']} |"
    ) in text
