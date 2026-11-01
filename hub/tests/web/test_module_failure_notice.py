"""The notice of a failed module row with no task, held against ui_text.md.

What these pin: ``ui.modules.failed_step`` says in both languages what
ui_text.md writes; the notice heads the failure's words with the step the row
names, in the step list's own words; the failure's words keep their line
breaks in the notice as they do under a step; and a module stopped against its
want words its code in the notice at the top of its tab.
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


def test_a_module_stopped_against_its_want_words_its_code_in_the_notice():
    page = source("machine_modules.tsx")

    assert (
        'NOTICED_STATES.includes(row.state) || (row.state === "stopped" && '
        "row.want !== WANT_STOPPED)"
    ) in page
    assert '{isCodeNoticed(activeRow) && activeRow.code !== "" &&' in page


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


def test_a_row_waiting_behind_a_required_modules_restart_shows_its_notice():
    source = (COMPONENTS_DIR / "machine_modules.tsx").read_text(encoding="utf-8")

    assert "required?.code === REBOOT_REQUIRED_CODE" in source
    assert "isInTransit && owedRestart !== undefined" in source
    assert source.count("{restartButton}") == 1
    assert "REBOOT_REQUIRED_CODE && restartButton" in source
