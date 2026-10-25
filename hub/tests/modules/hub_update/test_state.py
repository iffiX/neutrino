"""The record both the panel and the install unit write."""

import json
import os
import time

import pytest

from neutrino_hub.modules.hub_update.state import (
    HubUpdateRecord,
    HubUpdateStateFile,
    append_step,
    stamp_age_s,
)


def record(stage: str, **overrides) -> HubUpdateRecord:
    values = {
        "stage": stage,
        "from_version": "0.3.0",
        "to_version": "0.3.1",
        "started_at": "2026-09-20T15:00:00Z",
    }
    values.update(overrides)
    return HubUpdateRecord(**values)


def test_a_record_reads_back_as_it_was_written(tmp_path):
    state = HubUpdateStateFile(path=tmp_path / "state.json")
    written = record(
        "rolled_back",
        finished_at="x",
        reason="health_gate_failed",
        output="log",
        steps=["installed 0.3.1", "done"],
    )

    state.save(written)

    assert state.load() == written
    assert (tmp_path / "state.json").stat().st_mode & 0o777 == 0o600


def test_no_file_is_no_record(tmp_path):
    assert HubUpdateStateFile(path=tmp_path / "state.json").load() is None


def test_a_file_that_is_not_a_record_is_no_record(tmp_path):
    path = tmp_path / "state.json"
    state = HubUpdateStateFile(path=path)

    path.write_text("{not json")
    assert state.load() is None
    path.write_text(json.dumps(["a", "list"]))
    assert state.load() is None
    path.write_text(json.dumps({"stage": "dancing"}))
    assert state.load() is None


def test_the_default_path_follows_the_state_root(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path)

    assert HubUpdateStateFile().path == tmp_path / "hub_update" / "state.json"


def test_the_shape_the_unit_writes_is_the_shape_that_loads(tmp_path):
    """The shell script writes the file by hand; its keys are these."""
    path = tmp_path / "state.json"
    path.write_text(
        '{"stage": "installed", "from_version": "0.3.0", "to_version": "0.3.1", '
        '"started_at": "s", "finished_at": "f", "reason": "", "output": "done\\n"}\n'
    )

    loaded = HubUpdateStateFile(path=path).load()

    assert loaded == record(
        "installed", started_at="s", finished_at="f", output="done\n"
    )


def test_a_record_written_before_steps_existed_has_none(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"stage": "installed", "steps": "not a list"}')

    assert HubUpdateStateFile(path=path).load().steps == []


# --- the steps ---


def test_steps_are_kept_one_per_line():
    steps: list = []
    for line in ("downloading a.deb  3 MB", "checked", "installed 0.3.1"):
        append_step(steps, line)

    assert steps == ["downloading a.deb  3 MB", "checked", "installed 0.3.1"]


def test_a_downloads_progress_shares_the_row_of_its_source():
    steps: list = []
    for line in (
        "downloading a.deb  3 MB",
        "hub: fetching a.deb from github.com",
        "hub: fetching a.deb from github.com, 1.0 / 3.0 MB",
        "hub: fetching a.deb from cnb.cool",
        "hub: fetching a.deb from cnb.cool, 3.0 / 3.0 MB",
        "checked",
    ):
        append_step(steps, line)

    assert steps == [
        "downloading a.deb  3 MB",
        "hub: fetching a.deb from github.com, 1.0 / 3.0 MB",
        "hub: fetching a.deb from cnb.cool, 3.0 / 3.0 MB",
        "checked",
    ]


def test_a_stamps_age_is_counted_from_now():
    assert stamp_age_s("2026-10-14T00:00:00Z", now=1_791_936_060.0) == 60.0
    assert stamp_age_s("", now=0) is None


# --- settling a run that died ---


def aged(path, seconds: float = 60) -> None:
    """Make the record look written this many seconds ago."""
    moment = time.time() - seconds
    os.utime(path, (moment, moment))


def test_a_preparation_with_no_task_behind_it_was_interrupted(tmp_path):
    state = HubUpdateStateFile(path=tmp_path / "state.json")
    state.save(record("preparing"))
    aged(state.path)

    settled = state.settle(is_unit_active=False, is_task_running=False)

    assert settled.stage == "failed"
    assert settled.reason == "update_interrupted"
    assert settled.finished_at.endswith("Z")
    assert state.load().stage == "failed"


@pytest.mark.parametrize("stage", ["preparing", "installing", "rolling_back"])
def test_a_record_written_moments_ago_is_not_taken_for_an_interrupted_one(
    tmp_path, stage
):
    """The unit, job or process just started may not be running yet."""
    state = HubUpdateStateFile(path=tmp_path / "state.json")
    state.save(record(stage))
    aged(state.path, 5)

    settled = state.settle(is_unit_active=False, is_task_running=False)

    assert settled.stage == stage
    assert state.load().stage == stage


def test_a_preparation_with_its_task_running_stands(tmp_path):
    state = HubUpdateStateFile(path=tmp_path / "state.json")
    state.save(record("preparing"))

    settled = state.settle(is_unit_active=False, is_task_running=True)

    assert settled.stage == "preparing"


def test_an_install_with_no_unit_behind_it_was_interrupted(tmp_path):
    state = HubUpdateStateFile(path=tmp_path / "state.json")
    state.save(record("installing"))
    aged(state.path)

    settled = state.settle(is_unit_active=False, is_task_running=False)

    assert settled.stage == "failed"
    assert settled.reason == "update_interrupted"


def test_a_rollback_that_died_keeps_the_reason_it_started_for(tmp_path):
    state = HubUpdateStateFile(path=tmp_path / "state.json")
    state.save(record("rolling_back", reason="health_gate_failed"))
    aged(state.path)

    settled = state.settle(is_unit_active=False, is_task_running=False)

    assert settled.stage == "failed"
    assert settled.reason == "health_gate_failed"


def test_an_install_with_its_unit_running_stands(tmp_path):
    state = HubUpdateStateFile(path=tmp_path / "state.json")
    state.save(record("installing"))

    settled = state.settle(is_unit_active=True, is_task_running=False)

    assert settled.stage == "installing"


def test_a_settled_record_is_left_alone(tmp_path):
    state = HubUpdateStateFile(path=tmp_path / "state.json")
    state.save(record("installed", finished_at="f"))

    settled = state.settle(is_unit_active=False, is_task_running=False)

    assert settled.stage == "installed"


def test_no_record_settles_to_none(tmp_path):
    state = HubUpdateStateFile(path=tmp_path / "state.json")

    assert state.settle(is_unit_active=False, is_task_running=False) is None
