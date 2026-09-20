"""The shell the install unit runs, run for real against stubbed programs.

The package manager, systemctl, curl and nhub are scripts on a PATH of the
test's own, each saying and exiting what one case needs; the state file the
script leaves is read back the way the panel reads it.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from neutrino_hub.modules.hub_update.installer import HubUpdatePlan, render_script
from neutrino_hub.modules.hub_update.state import HubUpdateStateFile


def stub(bin_dir: Path, name: str, *, body: str) -> None:
    """One program on PATH, saying and exiting what a test wants."""
    program = bin_dir / name
    program.write_text("#!/bin/sh\n" + body + "\n")
    program.chmod(0o755)


@pytest.fixture
def box(tmp_path):
    """A directory for the unit, and a PATH where everything passes."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    directory = tmp_path / "hub_update"
    directory.mkdir()
    stub(bin_dir, "apt-get", body='echo "Setting up neutrino-hub ($*)"')
    stub(bin_dir, "systemctl", body="exit 0")
    stub(bin_dir, "curl", body="exit 0")
    stub(bin_dir, "nhub", body='echo "0.3.1"')
    return bin_dir, directory


def plan_for(directory: Path, *, rollback: bool = True) -> HubUpdatePlan:
    return HubUpdatePlan(
        from_version="0.3.0",
        to_version="0.3.1",
        package=directory / "neutrino-hub_0.3.1_amd64.deb",
        rollback=directory / "neutrino-hub_0.3.0_amd64.deb" if rollback else None,
        family="debian",
        port=8080,
        units=("neutrino_hub_web", "neutrino_hub_router"),
        started_at="2026-09-20T15:00:00Z",
    )


def run_script(box, *, rollback: bool = True) -> tuple[int, dict]:
    """Run the rendered script and read the record it left."""
    bin_dir, directory = box
    script = directory / "update.sh"
    script.write_text(
        render_script(
            plan_for(directory, rollback=rollback),
            directory=directory,
            gate_timeout_s=1,
            poll_s=0.2,
        )
    )
    environment = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    result = subprocess.run(
        ["sh", str(script)], capture_output=True, text=True, env=environment
    )
    raw = json.loads((directory / "state.json").read_text())
    return result.returncode, raw


def test_an_install_the_gate_passes_is_installed(box):
    code, raw = run_script(box)

    assert code == 0
    assert raw["stage"] == "installed"
    assert raw["from_version"] == "0.3.0"
    assert raw["to_version"] == "0.3.1"
    assert raw["started_at"] == "2026-09-20T15:00:00Z"
    assert raw["finished_at"].endswith("Z")
    assert raw["reason"] == ""
    assert "Setting up neutrino-hub" in raw["output"]
    assert "neutrino-hub_0.3.1_amd64.deb" in raw["output"]


def test_the_record_loads_the_way_the_panel_reads_it(box):
    _, directory = box
    run_script(box)

    record = HubUpdateStateFile(path=directory / "state.json").load()

    assert record is not None
    assert record.stage == "installed"
    assert (directory / "state.json").stat().st_mode & 0o777 == 0o600


def test_a_package_manager_that_fails_brings_the_rollback_in(box):
    bin_dir, _ = box
    stub(
        bin_dir,
        "apt-get",
        body='case "$*" in *0.3.1*) echo "dpkg: error"; exit 100;; *) echo "back";; esac',
    )
    stub(bin_dir, "nhub", body='echo "0.3.0"')

    code, raw = run_script(box)

    assert code == 1
    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "package_install_failed"
    assert "dpkg: error" in raw["output"]
    assert "back" in raw["output"]


def test_a_gate_that_never_passes_rolls_back_and_says_which_check_failed(box):
    bin_dir, _ = box
    stub(bin_dir, "nhub", body='echo "0.3.0"')

    code, raw = run_script(box)

    assert code == 1
    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "health_gate_failed"
    assert "gate: timed out after 1s: version=0.3.0" in raw["output"]


def test_a_gate_reports_every_check_that_failed(box):
    bin_dir, _ = box
    stub(
        bin_dir,
        "systemctl",
        body='case "$*" in *router*) [ "$1" = "is-active" ] && [ "$2" != "--quiet" ] && echo failed; exit 3;; esac; exit 0',
    )
    stub(bin_dir, "curl", body="exit 7")
    stub(bin_dir, "nhub", body='echo "0.3.0"')

    _, raw = run_script(box, rollback=False)

    assert raw["stage"] == "failed"
    assert "neutrino_hub_router=failed" in raw["output"]
    assert "http=failed" in raw["output"]
    assert "version=0.3.0" in raw["output"]


def test_without_a_rollback_a_failed_gate_is_failed(box):
    bin_dir, _ = box
    stub(bin_dir, "nhub", body='echo "0.3.0"')

    code, raw = run_script(box, rollback=False)

    assert code == 1
    assert raw["stage"] == "failed"
    assert raw["reason"] == "health_gate_failed"


def test_a_rollback_whose_gate_fails_too_is_failed_for_the_first_reason(box):
    bin_dir, _ = box
    stub(bin_dir, "nhub", body='echo "9.9.9"')

    code, raw = run_script(box)

    assert code == 1
    assert raw["stage"] == "failed"
    assert raw["reason"] == "health_gate_failed"


def test_the_rollback_is_gated_on_the_version_it_started_from(box):
    bin_dir, directory = box
    marker = directory / "rolled"
    stub(
        bin_dir,
        "apt-get",
        body=f'case "$*" in *0.3.0*) touch {marker};; esac; echo ok',
    )
    stub(
        bin_dir,
        "nhub",
        body=f"if [ -e {marker} ]; then echo 0.3.0; else echo 0.0.1; fi",
    )

    _, raw = run_script(box)

    assert raw["stage"] == "rolled_back"
    assert raw["reason"] == "health_gate_failed"


def test_whatever_the_install_prints_survives_as_json(box):
    bin_dir, _ = box
    stub(
        bin_dir,
        "apt-get",
        body="printf 'say \"hi\"\\tback\\\\slash\\r\\nline two\\033[0m\\n'",
    )

    _, raw = run_script(box)

    assert raw["output"] == 'say "hi" back\\slash\nline two[0m\n'


def test_only_the_tail_of_a_long_log_is_kept(box):
    bin_dir, _ = box
    stub(bin_dir, "apt-get", body="seq 1 5000")

    _, raw = run_script(box)

    assert len(raw["output"].encode()) <= 4096 + 16
    assert raw["output"].endswith("5000\n")
    assert not raw["output"].startswith("1\n")
