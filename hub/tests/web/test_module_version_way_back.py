"""The way back from a version that failed, on the module's tab.

What these pin: a failed row and an ``install_failed`` row keep the version
block, whose dialog holds **Follow the tested version** and the other versions;
its presses stay dead while the row is in transit; and a row that reports no
version shows no version line and a dead **Update**.
"""

from pathlib import Path

COMPONENTS_DIR = Path(__file__).resolve().parents[2] / "frontend/src/components"


def source(name: str) -> str:
    return " ".join((COMPONENTS_DIR / name).read_text(encoding="utf-8").split())


def test_a_failed_row_keeps_the_version_block():
    page = source("machine_modules.tsx")

    assert 'const FAILED_STATES = ["failed", "install_failed"];' in page
    assert (
        "{(isPresent || FAILED_STATES.includes(activeRow.state)) && !isCarriedRow && "
        "( <ModuleVersionBlock"
    ) in page
    assert "canPress={isAgentOnline && !isInTransit}" in page


def test_a_row_with_no_version_reported_shows_no_line_and_a_dead_update():
    block = source("module_version_block.tsx")

    assert 'const isReported = view.installed !== "";' in block
    assert (
        'const isNewer = isReported && view.newest !== "" && '
        "view.newest !== view.installed;"
    ) in block
    assert "const canUpdate = canPress && isNewer && !view.is_locked;" in block
    assert '{isReported && ( <span className="module_version_line mono">' in block


def test_the_dialog_stays_open_to_a_press_on_a_failed_row():
    block = source("module_version_block.tsx")

    assert "const canPick = canPress;" in block
    assert "onClick={() => void choose(FOLLOW_TESTED)}" in block
