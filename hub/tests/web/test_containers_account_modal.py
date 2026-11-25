"""Containers' numbers dialog asks no account and keeps a refusal on screen.

What these pin: the dialog asks the CPUs, the memory and the disk of the
default account's Podman machine alone, under ``ui.containers.run_title``,
and opens while the hub holds no Run settings; **Install** in the dialog
writes the Run settings before the press, a refusal of them shows the code's
words in the dialog, and the dialog closes only once the press may go on;
the Run settings and the panels under them name no account.
"""

import json
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
WORDS = {
    "en": "CPUs must be between 0 and {max}.",
    "zh-CN": "非法 CPU 数：要在 0 到 {max} 之间。",
}


def flat_source(name: str) -> str:
    path = FRONTEND_SRC_DIR / "components" / name
    return " ".join(path.read_text(encoding="utf-8").split())


def modal() -> str:
    return flat_source("containers_account_modal.tsx")


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


def test_the_dialog_asks_the_numbers_alone():
    body = modal()

    assert 'title={t("ui.containers.run_title")}' in body
    assert "apiPath(NEW_MACHINE_PATH, { device_id: deviceId, module })" in body
    assert (
        "const request: PodmanMachineUpdate = { device_id: deviceId, ...size };"
    ) in body
    for gone in ("Picker", "PasswordInput", "AccountListView", "ACCOUNT_PATH"):
        assert gone not in body


def test_the_dialog_opens_while_the_hub_holds_no_run_settings():
    page = flat_source("machine_modules.tsx")

    assert "return view.machine === null;" in page
    assert "machine?.account" not in page


def test_the_run_settings_and_the_panels_under_them_name_no_account():
    settings = flat_source("containers_run_settings.tsx")
    panels = flat_source("containers_panels.tsx")

    assert "Picker" not in settings
    assert "draft.account" not in settings
    assert "const isNewWindowsMachine = isWindows && view.machine === null;" in settings
    assert "currentDiskGib(saved.machine_state, defaultAccount)" in settings
    assert "isRunNeeded" not in panels
    assert "podmanReport(saved, isMachineRun, defaultAccount)" in panels
