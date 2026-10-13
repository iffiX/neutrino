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

from neutrino_hub.modules.hub_update.installer import HubUpdatePlan, render_script
from neutrino_hub.modules.hub_update.state import HubUpdateStateFile

STAGING = ["downloading neutrino-hub_0.3.1_amd64.deb  40 MB", "checked"]
HANDED_OVER = [*STAGING, "installing; the panel restarts now"]
AGENT_PACKAGE = "/var/lib/neutrino/hub/agent_cache/neutrino-agent_0.3.1_amd64.deb"


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
    directory: Path, *, rollback: bool = True, python: str = ""
) -> HubUpdatePlan:
    return HubUpdatePlan(
        from_version="0.3.0",
        to_version="0.3.1",
        package=directory / "neutrino-hub_0.3.1_amd64.deb",
        rollback=directory / "neutrino-hub_0.3.0_amd64.deb" if rollback else None,
        family="debian",
        port=8080,
        https_port=8444,
        units=("neutrino_hub_web", "neutrino_hub_router"),
        started_at="2026-09-20T15:00:00Z",
        python=python,
        steps=tuple(STAGING),
    )


def run_script(
    box,
    *,
    rollback: bool = True,
    available_kb: int = 2_000_000,
    python: str = "",
    agent_wait_s: int = 120,
) -> tuple[int, dict]:
    """Run the rendered script and read the record it left."""
    bin_dir, directory = box
    meminfo = directory / "meminfo"
    meminfo.write_text(
        f"MemTotal:        4000000 kB\nMemAvailable:    {available_kb} kB\n"
    )
    script = directory / "update.sh"
    script.write_text(
        render_script(
            plan_for(directory, rollback=rollback, python=python),
            directory=directory,
            gate_timeout_s=1,
            poll_s=0.2,
            meminfo_path=str(meminfo),
            agent_command=str(bin_dir / "nagent"),
            agent_wait_s=agent_wait_s,
        )
    )
    environment = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    result = subprocess.run(
        ["sh", str(script)], capture_output=True, text=True, env=environment
    )
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
        "no agent on this machine",
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


def agent_stubs(bin_dir: Path, directory: Path, *, package: str = AGENT_PACKAGE):
    """An installed agent at 0.3.0, and an interpreter naming the package the
    cache holds for it."""
    (directory / "agent_version").write_text("0.3.0\n")
    stub(bin_dir, "nagent", body=f"cat {directory / 'agent_version'}")
    stub(bin_dir, "hub_python", body=f'echo "{package}"')


def test_the_boxs_own_agent_is_reinstalled_from_the_cache_after_the_gate(box):
    bin_dir, directory = box
    agent_stubs(bin_dir, directory)

    code, raw = run_script(box, python=str(bin_dir / "hub_python"))

    calls = installs(directory)
    assert calls[0].endswith("neutrino-hub_0.3.1_amd64.deb")
    assert calls[1].endswith(AGENT_PACKAGE)
    assert code == 0
    assert raw["stage"] == "installed"
    assert raw["steps"][-3:] == ["panel answers", "agent updated to 0.3.1", "done"]
    assert f"agent: reinstalling {AGENT_PACKAGE}" in raw["output"]


def test_an_agent_already_at_the_caches_version_is_left_alone(box):
    """A same-version update reinstalls the hub but not the agent, so the
    agent and the desktop share it hosts keep running."""
    bin_dir, directory = box
    agent_stubs(bin_dir, directory)
    (directory / "agent_version").write_text("0.3.1\n")

    code, raw = run_script(box, python=str(bin_dir / "hub_python"))

    assert code == 0
    assert raw["stage"] == "installed"
    assert raw["steps"][-2:] == ["agent already 0.3.1", "done"]
    assert len(installs(directory)) == 1


def test_an_agent_that_will_not_reinstall_leaves_the_hub_installed(box):
    bin_dir, directory = box
    agent_stubs(bin_dir, directory)
    stub(
        bin_dir,
        "apt-get",
        body='case "$*" in *neutrino-agent*) exit 100;; esac\n' + apt_get(directory),
    )

    code, raw = run_script(box, python=str(bin_dir / "hub_python"))

    assert code == 0
    assert raw["stage"] == "installed"
    assert raw["steps"][-2:] == ["agent update failed: apt-get exited 100", "done"]


def test_a_cache_with_no_agent_for_this_machine_installs_none(box):
    bin_dir, directory = box
    agent_stubs(bin_dir, directory, package="")

    _, raw = run_script(box, python=str(bin_dir / "hub_python"))

    assert len(installs(directory)) == 1
    assert raw["steps"][-2:] == [
        "agent update failed: no agent package for this machine",
        "done",
    ]
    assert "this hub carries no agent for this machine" in raw["output"]


def test_a_box_with_no_agent_gets_none(box):
    bin_dir, directory = box
    agent_stubs(bin_dir, directory)
    (bin_dir / "nagent").unlink()

    _, raw = run_script(box, python=str(bin_dir / "hub_python"))

    assert len(installs(directory)) == 1
    assert raw["steps"][-2:] == ["no agent on this machine", "done"]


def test_a_rolled_back_hub_reinstalls_no_agent(box):
    bin_dir, directory = box
    agent_stubs(bin_dir, directory)
    stub(bin_dir, "curl", body=f"grep -q 0.3.0 {directory / 'hub_version'}")

    _, raw = run_script(box, python=str(bin_dir / "hub_python"))

    assert raw["stage"] == "rolled_back"
    assert not any("neutrino-agent" in line for line in installs(directory))


def agent_updating(bin_dir: Path, directory: Path, *, answers: int) -> None:
    """A systemctl whose agent update unit runs for this many questions, and
    whose last answer finds the agent updated by it."""
    count = directory / "asked"
    stub(
        bin_dir,
        "systemctl",
        body=(
            '[ "$1" = list-units ] || exit 0\n'
            '[ "$6" = neutrino_agent_update.service ] || exit 0\n'
            f"echo x >> {count}\n"
            f'if [ "$(wc -l < {count})" -le {answers} ]; then\n'
            '  echo "neutrino_agent_update.service loaded active running sh -c"\n'
            f"else echo 0.3.1 > {directory / 'agent_version'}; fi"
        ),
    )


def test_the_agents_own_update_is_waited_out_before_the_reinstall(box):
    """The agent's own update, started on the new hub's welcome, installed
    the target first; the script reinstalls nothing."""
    bin_dir, directory = box
    agent_stubs(bin_dir, directory)
    agent_updating(bin_dir, directory, answers=3)

    code, raw = run_script(box, python=str(bin_dir / "hub_python"))

    assert code == 0
    assert len((directory / "asked").read_text().splitlines()) == 4
    assert raw["steps"][-2:] == ["agent already 0.3.1", "done"]
    assert not any("neutrino-agent" in line for line in installs(directory))


def test_an_agent_update_that_never_ends_is_waited_out_only_so_long(box):
    bin_dir, directory = box
    agent_stubs(bin_dir, directory)
    agent_updating(bin_dir, directory, answers=10**6)

    code, raw = run_script(box, python=str(bin_dir / "hub_python"), agent_wait_s=1)

    assert code == 0
    assert raw["steps"][-2:] == ["agent updated to 0.3.1", "done"]
