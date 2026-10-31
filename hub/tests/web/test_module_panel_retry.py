"""A failed module's account panel, held against ui_behavior.md.

What these pin: the one panel of the account layer lights its apply bar and
its frame while the module reads ``failed`` or ``install_failed``; its apply
sends ``/set`` with a changed list and the module's ``/apply`` with nothing
changed, and waits for the machine's report after either; a failure standing
at the press ends that wait only after ``OLD_FAILURE_LIMIT_MS`` or a report
out of it.
"""

from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"


def flat(name: str) -> str:
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def test_the_bar_and_the_frame_are_lit_while_the_module_reads_failed():
    panel = flat("components/instances_panel.tsx")
    hook = flat("use_settled_apply.ts")

    assert 'export const FAILED_STATES = ["failed", "install_failed"];' in hook
    assert "const isPending = isDirty || FAILED_STATES.includes(saved.state);" in panel
    assert 'isPending ? "settings_group--dirty" : ""' in panel
    assert "<ApplyBar isDirty={isPending}" in panel


def test_an_apply_with_nothing_changed_sends_the_modules_apply_and_waits():
    panel = flat("components/instances_panel.tsx")
    apply = panel[panel.index("const apply = async") :]
    apply = apply[: apply.index("} catch (cause")]

    assert apply.index("if (isDirty) {") < apply.index("`${basePath}/set`")
    assert apply.index("`${basePath}/set`") < apply.index("} else {")
    assert apply.index("} else {") < apply.index("`${basePath}/apply`")
    assert "{ device_id: deviceId }" in apply
    assert apply.index("`${basePath}/apply`") < apply.index("resource.reload();")
    assert apply.index("resource.reload();") < apply.index("settle.begin();")


def test_a_failure_standing_at_the_press_ends_the_wait_after_its_limit():
    hook = flat("use_settled_apply.ts")
    follow = hook[hook.index("if (!isSettling || report === null)") :]
    follow = follow[: follow.index("[isSettling, isFailureOld, report, want]")]

    assert "const OLD_FAILURE_LIMIT_MS = 5_000;" in hook
    assert "if (!isFailureOld) { setIsSettling(false); }" in follow
    assert follow.index("if (isFailing(report))") < follow.index(
        "setIsFailureOld(false);"
    )
    assert "() => setIsFailureOld(false), OLD_FAILURE_LIMIT_MS," in hook
    assert (
        "const begin = useCallback(() => { setIsApplied(false); "
        "setIsFailureOld(true); setIsSettling(true); }, []);"
    ) in hook
