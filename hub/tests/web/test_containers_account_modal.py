"""Containers' account dialog keeps a refusal of its numbers on screen.

What these pin: **Install** in the dialog writes the Run settings before the
press, a refusal of them shows the code's words in the dialog, and the dialog
closes only once the press may go on.
"""

import json
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
WORDS = {
    "en": "CPUs must be between 0 and {max}.",
    "zh-CN": "非法 CPU 数：要在 0 到 {max} 之间。",
}


def modal() -> str:
    path = FRONTEND_SRC_DIR / "components" / "containers_account_modal.tsx"
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("language", list(WORDS))
def test_the_refusal_says_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "codes.json"
    words = json.loads(path.read_text(encoding="utf-8"))

    assert words["code.machine_cpus_invalid"] == WORDS[language]


def test_a_refused_number_stays_in_the_dialog_with_its_words():
    body = modal()

    assert "await writeMachine(); onChosen(); } catch (cause: unknown) {" in body
    assert "setError(describeError(cause)); setIsSaving(false);" in body
    assert "const shownError = error ??" in body
    assert (
        '{shownError !== null && ( <div className="notice notice--error"> '
        '<Icon name="alert" size={15} /> '
        '<div className="notice_body">{shownError}</div>'
    ) in body
