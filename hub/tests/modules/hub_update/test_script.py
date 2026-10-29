"""The shell the install unit runs, run for real against stubbed programs.

The package manager, systemctl, curl, nhub and nagent are scripts on a PATH
of the test's own. apt-get writes down the version of each package it
installs, and nhub and nagent say the version written, so the script reads
back what it installed the way it does on a box. The state file the script
leaves is read back the way the panel reads it. The kernel's memory figure is
a file of the test's own too.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from neutrino_hub.modules.hub_update import installer as installer_module
from neutrino_hub.modules.hub_update.installer import HubUpdatePlan, render_script
from neutrino_hub.modules.hub_update.state import HubUpdateStateFile

STAGING = ["downloading neutrino-hub_0.3.1_amd64.deb  40 MB", "checked"]
HANDED_OVER = [*STAGING, "installing; the panel restarts now"]


def stub(bin_dir: Path, name: str, *, body: str) -> None:
    """One program on PATH, saying and exiting what a test wants."""
    program = bin_dir / name
    program.write_text("#!/bin/sh\n" + body + "\n")
    program.chmod(0o755)


def apt_get(directory: Path, *, failing: str = "", is_changing: bool = False) -> str:
    """An apt-get that writes down every call and the version it installs.

    Args:
        directory: Where the calls and the installed versions are written.
        failing: A version whose install exits 100.
        is_changing: Whether the failing install still leaves its version.
    """
    calls = directory / "calls"
    hub = directory / "hub_version"
    agent = directory / "agent_version"
    failure = ""
    if failing:
        left = f"echo {failing} > {hub}; " if is_changing else ""
        failure = f'case "$*" in *neutrino-hub_{failing}_*) {left}echo "dpkg: error"; exit 100;; esac\n'
    return (
        f'echo "apt-get $*" >> {calls}\n'
        + failure
        + 'for word in "$@"; do\n'
        + f'  case "$word" in *neutrino-hub_*) echo "$word" | sed -E "s/.*_([0-9.]+)_.*/\\1/" > {hub};;\n'
        + f'    *neutrino-agent_*) echo "$word" | sed -E "s/.*_([0-9.]+)_.*/\\1/" > {agent};; esac\n'
        + "done\n"
        + 'echo "Setting up $*"'
    )


@pytest.fixture
def box(tmp_path):
    """A directory for the unit, and a PATH where everything passes."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    directory = tmp_path / "hub_update"
    directory.mkdir()
    (directory / "hub_version").write_text("0.3.0\n")
    stub(bin_dir, "apt-get", body=apt_get(directory))
    stub(bin_dir, "systemctl", body="exit 0")
    stub(bin_dir, "curl", body=f'echo "curl $*" >> {directory / "probes"}; exit 0')
    stub(bin_dir, "nhub", body=f"cat {directory / 'hub_version'}")
    return bin_dir, directory


def plan_for(
    directory: Path, *, rollback: bool = True, family: str = "debian"
) -> HubUpdatePlan:
    return HubUpdatePlan(
        from_version="0.3.0",
        to_version="0.3.1",
        package=directory / "neutrino-hub_0.3.1_amd64.deb",
        rollback=directory / "neutrino-hub_0.3.0_amd64.deb" if rollback else None,
        family=family,
        port=8080,
        https_port=8444,
        units=("neutrino_hub_web", "neutrino_hub_router"),
        started_at="2026-09-20T15:00:00Z",
        steps=tuple(STAGING),
    )


def run_script(
    box,
    *,
    rollback: bool = True,
    available_kb: int = 2_000_000,
    family: str = "debian",
    gate_timeout_s: int = 1,
) -> tuple[int, dict]:
    """Run the rendered script and read the record it left; what it wrote to
    its standard error is left beside the record."""
    bin_dir, directory = box
    meminfo = directory / "meminfo"
    meminfo.write_text(
        f"MemTotal:        4000000 kB\nMemAvailable:    {available_kb} kB\n"
    )
    script = directory / "update.sh"
    script.write_text(
        render_script(
            plan_for(directory, rollback=rollback, family=family),
            directory=directory,
            gate_timeout_s=gate_timeout_s,
            poll_s=0.2,
            meminfo_path=str(meminfo),
        )
    )
    environment = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    result = subprocess.run(
        ["sh", str(script)], capture_output=True, text=True, env=environment
    )
    (directory / "stderr").write_text(result.stderr)
    raw = json.loads((directory / "state.json").read_text())
    return result.returncode, raw


def installs(directory: Path) -> list:
    calls = directory / "calls"
    return calls.read_text().splitlines() if calls.exists() else []


def test_an_install_the_gate_passes_is_installed(box):
    code, raw = run_script(box)

    assert code == 0
    assert raw["stage"] == "installed"
    assert raw["from_version"] == "0.3.0"
    assert raw["to_version"] == "0.3.1"
    assert raw["started_at"] == "2026-09-20T15:00:00Z"
    assert raw["finished_at"].endswith("Z")
    assert raw["reason"] == ""
    assert raw["steps"] == [
        *HANDED_OVER,
        "installed 0.3.1",
        "panel answers",
        "done",
    ]
    assert "Setting up" in raw["output"]
    assert "neutrino-hub_0.3.1_amd64.deb" in raw["output"]


def test_the_record_loads_the_way_the_panel_reads_it(box):
    _, directory = box
    run_script(box)

    record = HubUpdateStateFile(path=directory / "state.json").load()

    assert record is not None
    assert record.stage == "installed"
    assert record.steps[-1] == "done"
    assert (directory / "state.json").stat().st_mode & 0o777 == 0o600


def test_each_step_is_written_as_it_is_taken(box):
    """The gate's probe copies the record it finds, mid-run."""
    bin_dir, directory = box
    stub(
        bin_dir,
        "curl",
        body=f"[ -e {directory}/mid.json ] || cp {directory}/state.json {directory}/mid.json; exit 0",
    )

    run_script(box)

    mid = json.loads((directory / "mid.json").read_text())
    assert mid["stage"] == "installing"
    assert mid["finished_at"] == ""
    assert mid["steps"] == [*HANDED_OVER, "installed 0.3.1"]


def test_a_gate_with_no_time_left_probes_once_before_it_looks_at_the_clock(box):
    _, directory = box

    code, raw = run_script(box, gate_timeout_s=0)

    assert code == 0
    assert raw["stage"] == "installed"
    assert len((directory / "probes").read_text().splitlines()) == 1


def test_a_package_manager_that_changed_nothing_is_failed_at_once(box):
    """No gate is held and nothing is put back: the box never left 0.3.0."""
    _, directory = box
    stub(box[0], "apt-get", body=apt_get(directory, failing="0.3.1"))

    code, raw = run_script(box)

    assert code == 1
    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "package_install_failed"
    assert raw["steps"] == [
        *HANDED_OVER,
        "install failed: apt-get exited 100",
        "nothing changed, still 0.3.0",
        "done",
    ]
    assert len(installs(directory)) == 1
    assert not (directory / "probes").exists()
    assert "dpkg: error" in raw["output"]


def test_a_package_manager_that_exits_zero_and_installs_nothing_is_failed(box):
    """dnf5 answers a reinstall of a version not installed so."""
    bin_dir, directory = box
    stub(bin_dir, "apt-get", body="echo 'Nothing to do.'")

    _, raw = run_script(box)

    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "package_install_failed"
    assert raw["steps"][-3:] == [
        "install failed: found version 0.3.0",
        "nothing changed, still 0.3.0",
        "done",
    ]
    assert not (directory / "probes").exists()


def test_a_package_manager_that_failed_halfway_brings_the_rollback_in(box):
    bin_dir, directory = box
    stub(bin_dir, "apt-get", body=apt_get(directory, failing="0.3.1", is_changing=True))

    code, raw = run_script(box)

    assert code == 1
    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "package_install_failed"
    assert raw["steps"][len(HANDED_OVER) :] == [
        "install failed: apt-get exited 100",
        "rolled back to 0.3.0",
        "done",
    ]
    assert installs(directory)[1].endswith("neutrino-hub_0.3.0_amd64.deb")


def test_a_gate_that_never_passes_rolls_back_and_says_which_check_failed(box):
    bin_dir, directory = box
    stub(bin_dir, "curl", body=f"grep -q 0.3.0 {directory / 'hub_version'}")

    code, raw = run_script(box)

    assert code == 1
    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "health_gate_failed"
    assert raw["steps"][len(HANDED_OVER) :] == [
        "installed 0.3.1",
        "panel did not answer in 1 s",
        "rolled back to 0.3.0",
        "done",
    ]
    assert "gate: timed out after 1s: panel=failed" in raw["output"]


def test_a_probe_the_panel_refuses_says_nothing_on_the_units_error_stream(box):
    """The unit's standard error is the journal."""
    bin_dir, directory = box
    stub(
        bin_dir,
        "curl",
        body=f"[ -e {directory}/probed ] && exit 0\n"
        f"touch {directory}/probed\n"
        'echo "curl: (7) Failed to connect" >&2; exit 7',
    )

    _, raw = run_script(box)

    assert raw["stage"] == "installed"
    assert "Failed to connect" not in (directory / "stderr").read_text()


def test_a_gate_reports_every_check_that_failed(box):
    bin_dir, _ = box
    stub(
        bin_dir,
        "systemctl",
        body='case "$*" in *router*) [ "$1" = "is-active" ] && [ "$2" != "--quiet" ] && echo failed; exit 3;; esac; exit 0',
    )
    stub(bin_dir, "curl", body="exit 7")

    _, raw = run_script(box, rollback=False)

    assert raw["stage"] == "failed"
    assert "neutrino_hub_router=failed" in raw["output"]
    assert "panel=failed" in raw["output"]


def test_without_a_rollback_a_failed_gate_is_failed(box):
    bin_dir, _ = box
    stub(bin_dir, "curl", body="exit 7")

    code, raw = run_script(box, rollback=False)

    assert code == 1
    assert raw["stage"] == "failed"
    assert raw["reason"] == "health_gate_failed"
    assert raw["steps"][-3:] == [
        "panel did not answer in 1 s",
        "rollback failed: no package of 0.3.0",
        "done",
    ]


def test_a_rollback_whose_gate_fails_too_is_failed_for_the_first_reason(box):
    bin_dir, _ = box
    stub(bin_dir, "curl", body="exit 7")

    code, raw = run_script(box)

    assert code == 1
    assert raw["stage"] == "failed"
    assert raw["reason"] == "health_gate_failed"
    assert raw["steps"][-2:] == [
        "rollback failed: panel did not answer in 1 s",
        "done",
    ]


def test_a_rollback_the_package_manager_refuses_is_failed(box):
    bin_dir, directory = box
    stub(bin_dir, "curl", body="exit 7")
    stub(bin_dir, "apt-get", body=apt_get(directory, failing="0.3.0"))

    _, raw = run_script(box)

    assert raw["stage"] == "failed"
    assert raw["reason"] == "health_gate_failed"
    assert raw["steps"][-2:] == ["rollback failed: apt-get exited 100", "done"]


def test_whatever_the_install_prints_survives_as_json(box):
    bin_dir, directory = box
    stub(
        bin_dir,
        "apt-get",
        body=apt_get(directory)
        + "\nprintf 'say \"hi\"\\tback\\\\slash\\r\\nline two\\033[0m\\n'",
    )

    _, raw = run_script(box)

    assert raw["output"].endswith('say "hi" back\\slash\nline two[0m\n')


def test_a_progress_line_ended_by_a_carriage_return_keeps_its_break(box):
    bin_dir, directory = box
    stub(
        bin_dir,
        "apt-get",
        body=apt_get(directory)
        + "\nprintf '(Reading database ... 5%%\\r(Reading database ... 10%%\\rdone\\n'",
    )

    _, raw = run_script(box)

    assert raw["output"].endswith(
        "(Reading database ... 5%\n(Reading database ... 10%\ndone\n"
    )


def test_only_the_tail_of_a_long_log_is_kept(box):
    bin_dir, directory = box
    stub(bin_dir, "apt-get", body=apt_get(directory) + "\nseq 1 5000")

    _, raw = run_script(box)

    assert len(raw["output"].encode()) <= 4096 + 16
    assert raw["output"].endswith("5000\n")
    assert not raw["output"].startswith("1\n")


# --- a machine short of memory ----------------------------------------------


def recording_systemctl(bin_dir: Path, calls: Path) -> None:
    """A systemctl that says every unit is running and writes down each call."""
    stub(bin_dir, "systemctl", body=f'echo "systemctl $*" >> {calls}; exit 0')


def test_short_of_memory_the_panel_and_the_gateway_stop_for_the_unpack(box):
    bin_dir, directory = box
    calls = directory / "calls"
    recording_systemctl(bin_dir, calls)

    code, raw = run_script(box, available_kb=200_000)

    lines = calls.read_text().splitlines()
    install = next(i for i, line in enumerate(lines) if line.startswith("apt-get"))
    assert lines.index("systemctl stop neutrino_hub_web") < install
    assert lines.index("systemctl stop neutrino_hub_cliproxyapi") < install
    assert lines.index("systemctl start neutrino_hub_web") > install
    assert lines.index("systemctl start neutrino_hub_cliproxyapi") > install
    assert code == 0
    assert raw["stage"] == "installed"
    assert "200000 kB available" in raw["output"]


def test_with_memory_to_spare_nothing_is_stopped(box):
    bin_dir, directory = box
    calls = directory / "calls"
    recording_systemctl(bin_dir, calls)

    run_script(box, available_kb=900_000)

    assert "systemctl stop" not in calls.read_text()


def test_a_failed_install_starts_again_what_it_stopped(box):
    bin_dir, directory = box
    calls = directory / "calls"
    recording_systemctl(bin_dir, calls)
    stub(bin_dir, "apt-get", body=apt_get(directory, failing="0.3.1"))

    _, raw = run_script(box, rollback=False, available_kb=100_000)

    assert raw["stage"] == "rolled_back"
    assert "systemctl start neutrino_hub_web" in calls.read_text()


# --- the box's own agent ----------------------------------------------------


def test_the_update_installs_no_agent(box):
    """The panel's start brings the box's own agent to the new version."""
    bin_dir, directory = box
    (directory / "agent_version").write_text("0.3.0\n")
    stub(bin_dir, "nagent", body=f"cat {directory / 'agent_version'}")

    code, raw = run_script(box)

    assert code == 0
    assert raw["steps"][-2:] == ["panel answers", "done"]
    assert not [call for call in installs(directory) if "neutrino-agent" in call]
    assert (directory / "agent_version").read_text() == "0.3.0\n"


# --- arch: pacman's lock ----------------------------------------------------


def arch_box(box, monkeypatch, *, is_locked: bool) -> Path:
    """pacman in place of apt-get, and its lock file a file of the test's."""
    bin_dir, directory = box
    stub(bin_dir, "pacman", body=apt_get(directory))
    lock = directory / "db.lck"
    if is_locked:
        lock.write_text("")
        subprocess.Popen(["sh", "-c", f"sleep 1.5; rm {lock}"])
    monkeypatch.setattr(installer_module, "HUB_UPDATE_PACMAN_LOCK_PATH", str(lock))
    return lock


def test_a_held_pacman_lock_is_a_step_before_the_install_waits(box, monkeypatch):
    arch_box(box, monkeypatch, is_locked=True)

    code, raw = run_script(box, family="arch")

    assert code == 0
    assert raw["steps"] == [
        *HANDED_OVER,
        "waiting for the package manager",
        "installed 0.3.1",
        "panel answers",
        "done",
    ]


def test_a_free_pacman_lock_says_nothing(box, monkeypatch):
    arch_box(box, monkeypatch, is_locked=False)

    _, raw = run_script(box, family="arch")

    assert raw["stage"] == "installed"
    assert "waiting for the package manager" not in raw["steps"]
