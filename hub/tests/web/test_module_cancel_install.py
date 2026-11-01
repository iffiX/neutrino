"""The Cancel of a module's first install on its tab, held against ui_text.md.

What these pin: the six words in both languages; a first install read from
the row alone, a state of the two a first install reads with a running task
whose plan has a ``verify`` step and does not pull and start; a first start
with a long step read from the plan the same way, ``npm`` on a row that is not
active, ``tex`` beside ``replica_set``, and none with ``switch``; Cancel in
Install's place in the danger tier, for every module with no module named; its
dialog, the uninstall line and its tone beside two buttons that do not both
read as cancelling; the press going to the route of Uninstall with no press
noted; Cancelling read from the row's ``want`` and kept by the page through the
uninstall that follows; the buttons of a row in transit staying dead around it.
"""

import json
from pathlib import Path

import pytest

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"
COMPONENTS_DIR = FRONTEND_SRC_DIR / "components"
WORDS = {
    "en": {
        "ui.modules.cancel": "Cancel",
        "ui.modules.cancelling": "Cancelling",
        "ui.modules.cancel_title": "Cancel the install of {module} on {device}",
        "ui.modules.cancel_body": (
            "The running step ends first, no further step runs, and what the "
            "install left is removed."
        ),
        "ui.modules.cancel_confirm": "Cancel install",
        "ui.modules.cancel_keep": "Keep installing",
    },
    "zh-CN": {
        "ui.modules.cancel": "取消",
        "ui.modules.cancelling": "正在取消",
        "ui.modules.cancel_title": "取消在 {device} 上安装 {module}",
        "ui.modules.cancel_body": (
            "正在运行的这一步先走完，之后的步骤不再运行，安装留下的内容都会移除。"
        ),
        "ui.modules.cancel_confirm": "取消安装",
        "ui.modules.cancel_keep": "继续安装",
    },
}


def page() -> str:
    source = (COMPONENTS_DIR / "machine_modules.tsx").read_text(encoding="utf-8")
    return " ".join(source.split())


@pytest.mark.parametrize("language", list(WORDS))
def test_the_words_say_what_ui_text_writes(language):
    path = FRONTEND_SRC_DIR / "locales" / language / "modules.json"
    words = json.loads(path.read_text(encoding="utf-8"))

    assert {key: words.get(key) for key in WORDS[language]} == WORDS[language]


def test_a_first_install_is_read_from_the_row_s_state_and_plan():
    assert 'const FIRST_INSTALL_STATES = ["installing", "queued"];' in page()
    assert 'const INSTALL_PLAN_STEP = "verify";' in page()
    assert (
        "function runningPlan(row: DeviceModuleView): string[] { "
        "return row.task !== null && row.task.is_running "
        "? row.task.steps.map((step) => step.name) : []; }"
    ) in page()
    assert (
        "(FIRST_INSTALL_STATES.includes(row.state) && "
        "plan.includes(INSTALL_PLAN_STEP) && "
        "!IMAGE_CHANGE_STEPS.every((step) => plan.includes(step)))"
    ) in page()


def test_a_container_module_s_version_change_is_no_first_install():
    assert 'const IMAGE_CHANGE_STEPS = ["pull", "start"];' in page()


def test_a_first_start_with_a_long_step_is_read_from_the_plan():
    assert (
        'const FIRST_START_STATES = ["installed", ...FIRST_INSTALL_STATES];' in page()
    )
    assert 'const EVERY_START_LONG_STEP = "npm";' in page()
    assert 'const FRESH_START_LONG_STEPS = ["replica_set", "tex"];' in page()
    assert (
        "(FIRST_START_STATES.includes(row.state) && isLongFirstStart(row, plan))"
    ) in page()
    assert (
        "function isLongFirstStart(row: DeviceModuleView, plan: string[]): boolean { "
        "return ( !plan.includes(VERSION_SWITCH_STEP) && "
        "((plan.includes(EVERY_START_LONG_STEP) && !row.is_active) || "
        "FRESH_START_LONG_STEPS.every((step) => plan.includes(step))) ); }"
    ) in page()


def test_a_version_switch_and_a_running_module_show_no_cancel():
    assert 'const VERSION_SWITCH_STEP = "switch";' in page()
    first_start = page().split('const FIRST_START_STATES = ["installed"')[1]
    assert '"running"' not in first_start.split(";")[0]
    assert '"stopped"' not in first_start.split(";")[0]


def test_cancel_stands_in_install_s_place_in_the_danger_tier():
    assert (
        "{isCancelShown ? ( <CancelButton isCancelling={isRowCancelling} "
        "isEnabled={isAgentOnline && !isBusy && !isRowCancelling} "
        "isBusy={busyAction === CANCEL_BUSY} onClick={askCancel} /> ) : ( "
        '<ActionButton action="install"'
    ) in page()
    assert 'className="button button--danger"' in page()
    assert '{t(isCancelling ? "ui.modules.cancelling" : "ui.modules.cancel")}' in page()


def test_every_module_takes_one_cancel():
    body = page()
    names = (
        "runningPlan",
        "isFirstInstall",
        "isLongFirstStart",
        "isCancelling",
        "isCancelKept",
        "CancelButton",
    )
    for name in names:
        start = body.index(f"function {name}(")
        assert "activeModule" not in body[start : start + 400]
        for module in ("podman", "ayakaleaf", "cloudcli", "HERMES", "CONTAINERS"):
            assert module not in body[start : start + 400]


def test_the_dialog_says_what_is_deleted_and_keeps_installing_outside_it():
    assert (
        'confirm.ask({ title: t("ui.modules.cancel_title", { '
        "module: moduleTitle(activeRow.name, activeRow.title), device: deviceName, }), "
        'body: t("ui.modules.cancel_body"), '
        "detail: uninstallLine(activeRow.uninstall_data), "
        "isDanger: activeRow.uninstall_data?.is_deleted === true, "
        'confirmLabel: t("ui.modules.cancel_confirm"), '
        'cancelLabel: t("ui.modules.cancel_keep"), '
        'onConfirm: () => void act("uninstall", CANCEL_BUSY), });'
    ) in page()


def test_the_press_goes_to_uninstall_s_route_and_notes_no_press():
    assert "setBusyAction(busy);" in page()
    assert (
        "if (busy === CANCEL_BUSY) { setCancels((current) => [...current, activeModule]); "
        "} else { notePress(activeModule, action); }"
    ) in page()
    assert "`/agent/module/${action}`" in page()


def test_cancelling_is_read_from_the_row_and_kept_through_the_uninstall():
    assert (
        "function isCancelling(row: DeviceModuleView): boolean { "
        "return isFirstInstall(row) && row.want === WANT_ABSENT; }"
    ) in page()
    assert (
        "function isCancelKept(row: DeviceModuleView, cancels: string[]): boolean { "
        "return ( isCancelling(row) || (cancels.includes(row.name) && "
        "row.want === WANT_ABSENT && isRowInTransit(row)) ); }"
    ) in page()
    assert (
        "const isRowCancelling = reportedRow !== undefined && "
        "isCancelKept(reportedRow, cancels);"
    ) in page()
    assert (
        "const isCancelShown = reportedRow !== undefined && "
        "(isRowCancelling || isFirstInstall(reportedRow));"
    ) in page()


def test_the_other_buttons_of_a_row_in_transit_stay_dead():
    assert (
        "const canAct = activeRow !== undefined && isAgentOnline && !isBusy && "
        "!isInTransit;"
    ) in page()
    assert (
        'action="uninstall" isEnabled={ canAct && '
        "(isPresent || FAILED_STATES.includes(activeRow.state)) }"
    ) in page()


def test_a_failed_install_keeps_install_and_uninstall_and_has_no_cancel():
    assert "FIRST_INSTALL_STATES" in page()
    assert (
        '"install_failed"'
        not in page().split("const FIRST_INSTALL_STATES")[1].split(";")[0]
    )
    assert (
        'action="install" isEnabled={ canAct && (activeRow.state === "absent" || '
        'activeRow.state === "install_failed" || isRetried(activeRow, "installed")) }'
    ) in page()
