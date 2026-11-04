"""Terminal's row and the wait of its apply, held against ui_text.md and ui_behavior.md.

What these pin: ``state.ready`` says in both languages what ui_text.md writes;
the panel's descriptor table marks Terminal alone as a module without a
program; its enabled row reads ``state.ready`` with a dot that does not pulse
while the module reads ``running``, and the running dot otherwise; every other
module's row keeps the running dot; its apply counts each row as running, so it
waits for the module's state alone, and a row's code still fails it.
"""

import json
import re
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
WORDS = {"en": "ready", "zh-CN": "可用"}


def flat(text: str) -> str:
    return " ".join(text.split())


def panel() -> str:
    source = FRONTEND_SRC_DIR / "components" / "instances_panel.tsx"
    return flat(source.read_text(encoding="utf-8"))


def descriptors() -> dict:
    """Each descriptor's text in the panel's table, by module name."""
    source = FRONTEND_SRC_DIR / "module_descriptors.ts"
    table = source.read_text(encoding="utf-8")
    table = table[table.index("MODULE_DESCRIPTORS") :]
    return dict(re.findall(r"^  (\w+): \{\n(.*?)^  \},$", table, re.M | re.S))


@pytest.mark.parametrize("language", list(WORDS))
def test_the_ready_word_says_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "common.json"
    words = json.loads(path.read_text(encoding="utf-8"))

    assert words["state.ready"] == WORDS[language]


def test_terminal_alone_is_a_module_without_a_program():
    table = descriptors()
    marked = [name for name, text in table.items() if "isWithoutProgram" in text]

    assert "ssh_server" in table
    assert marked == ["terminal"]
    assert "isWithoutProgram: true," in table["terminal"]


def test_the_row_of_a_running_module_without_a_program_reads_ready():
    text = panel()

    assert (
        "const isReady = descriptor.isWithoutProgram === true "
        "&& saved.state === STATE_RUNNING;"
    ) in text
    assert "isReady={isReady}" in text
    assert (
        '{row.is_enabled && (isReady ? ( <StatusDot tone="ok" '
        'label={t("state.ready")} isPulsing={false} /> ) : ( <StatusDot '
        'tone={row.is_running ? "ok" : "idle"} '
        'label={t(row.is_running ? "state.running" : "state.stopped")} /> ))}'
    ) in text


def test_its_apply_waits_for_the_module_s_state_alone():
    text = panel()

    assert (
        "useSettledApply( reportOf(saved, descriptor), "
        "isWaitingForStart || descriptor.isProgram === true ? want : WANT_RUNNING, )"
    ) in text
    assert "const report = reportOf(saved, descriptor);" in text
    assert (
        "is_running: row.is_running || descriptor.isWithoutProgram === true, "
        "code: row.code,"
    ) in text
