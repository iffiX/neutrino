"""The notice of a failed module row with no task, held against ui_text.md.

What these pin: ``ui.modules.failed_step`` says in both languages what
ui_text.md writes; the notice heads the failure's words with the step the row
names, in the step list's own words; and the failure's words keep their line
breaks in the notice as they do under a step.
"""

import json
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
COMPONENTS_DIR = FRONTEND_SRC_DIR / "components"
WORDS = {
    "en": "Failed at step {index} of {count}: {step}",
    "zh-CN": "第 {index}/{count} 步失败：{step}",
}


def source(name: str) -> str:
    return " ".join((COMPONENTS_DIR / name).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("language", list(WORDS))
def test_the_heading_says_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    words = json.loads(path.read_text(encoding="utf-8"))

    assert words["ui.modules.failed_step"] == WORDS[language]


def test_the_notice_heads_the_failure_with_the_step_the_row_names():
    page = source("machine_modules.tsx")

    assert (
        '{activeRow.step !== null && ( <span> {t("ui.modules.failed_step", '
        "{ index: activeRow.step.index, count: activeRow.step.count, "
        "step: stepWords( activeRow.step, activeRow.name, 0, manifestTitles, ), })}"
    ) in page


def test_the_failure_s_words_keep_their_line_breaks():
    page = source("machine_modules.tsx")
    styles = source("machine_modules.css")

    assert (
        '<span className="modules_failure_detail"> '
        "{stripAnsi(describeFailure(activeRow, manifestTitles))} </span>"
    ) in page
    assert ".modules_failure_detail { white-space: pre-wrap;" in styles
