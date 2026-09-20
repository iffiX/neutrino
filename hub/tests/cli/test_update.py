"""`nhub update`: what it says, when it asks, and what it hands to systemd."""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from neutrino_hub.cli import update as update_module
from neutrino_hub.exceptions import HubUpdateError
from neutrino_hub.modules.hub_update.state import HubUpdateRecord, HubUpdateStateFile


class Release:
    def __init__(self, version: str):
        self.version = version
        self.tag = f"v{version}"
        self.published_at = "2026-10-01T12:00:00Z"
        self.notes = "\n".join(f"line {index}" for index in range(30))
        self.page_url = f"https://example.invalid/{version}"
        self.asset_name = f"neutrino-hub_{version}_amd64.deb"
        self.asset_url = f"https://example.invalid/{self.asset_name}"
        self.asset_size = 100 * 1024 * 1024
        self.checksums_url = "https://example.invalid/SHA256SUMS"


class Installer:
    """An installer whose releases and unit are the test's own."""

    def __init__(self, state, *, latest=None):
        self.checker = SimpleNamespace(latest=lambda: latest)
        self.state = state
        self.is_active = False
        self.rollback_available = True
        self.prepared = []
        self.launched = []

    def is_unit_active(self):
        return self.is_active

    def is_rollback_available(self, current):
        return self.rollback_available

    def is_rollback_present(self, current):
        return False

    def prepare(self, found, *, current, port, on_progress):
        on_progress("downloading")
        self.prepared.append((found.version, current, port))
        return SimpleNamespace(from_version=current, to_version=found.version)

    def plan_for_file(self, package, *, current, port, on_progress):
        on_progress(f"{package.name} is in place")
        self.prepared.append((package.name, current, port))
        return SimpleNamespace(from_version=current, to_version="0.3.1")

    def launch(self, plan):
        self.launched.append(plan)


@pytest.fixture
def box(monkeypatch, tmp_path):
    """The command over a stub installer, a fast wait and a recorded prompt."""
    state = HubUpdateStateFile(path=tmp_path / "state.json")
    installer = Installer(state)
    answers: list = []
    asked: list = []
    monkeypatch.setattr(update_module, "_installer", lambda: installer)
    monkeypatch.setattr(update_module, "is_packaged", lambda: True)
    monkeypatch.setattr(update_module, "HUB_VERSION", "0.3.0")
    monkeypatch.setattr(update_module, "_configured_port", lambda: 8090)
    monkeypatch.setattr(update_module, "UPDATE_WAIT_POLL_S", 0.01)
    monkeypatch.setattr(update_module, "UPDATE_WAIT_TIMEOUT_S", 1)
    monkeypatch.setattr(
        update_module,
        "free_bytes",
        lambda size, *, is_rollback_fetched: (size * 4, 10**12),
    )
    monkeypatch.setattr(
        update_module, "check_space", lambda size, *, is_rollback_fetched: None
    )

    def ask(question: str) -> str:
        asked.append(question)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr("builtins.input", ask)
    return installer, answers, asked


def settle(state: HubUpdateStateFile, stage: str, **overrides) -> None:
    """Write the record the unit would leave, from another thread."""
    values = {
        "stage": stage,
        "from_version": "0.3.0",
        "to_version": "0.3.1",
        "started_at": "s",
        "finished_at": "f",
    }
    values.update(overrides)
    threading.Timer(0.05, lambda: state.save(HubUpdateRecord(**values))).start()


def test_a_checkout_cannot_update_itself(box, monkeypatch, capsys):
    monkeypatch.setattr(update_module, "is_packaged", lambda: False)

    assert update_module.update(is_confirmed=True, package=None) == 2
    assert "checkout" in capsys.readouterr().err


def test_nothing_published_is_nothing_to_do(box, capsys):
    installer, _, asked = box

    assert update_module.update(is_confirmed=False, package=None) == 0
    assert "nothing has been published yet" in capsys.readouterr().out
    assert asked == []
    assert installer.launched == []


def test_the_newest_release_already_running_is_nothing_to_do(box, capsys):
    installer, _, asked = box
    installer.checker.latest = lambda: Release("0.3.0")

    assert update_module.update(is_confirmed=False, package=None) == 0
    assert "already on the newest release" in capsys.readouterr().out
    assert asked == []


def test_a_new_major_is_not_installed_from_here(box, capsys):
    installer, _, asked = box
    installer.checker.latest = lambda: Release("1.0.0")

    assert update_module.update(is_confirmed=True, package=None) == 2
    assert "upgrade guide" in capsys.readouterr().err
    assert asked == []
    assert installer.launched == []


def test_the_release_is_described_before_the_question(box, capsys):
    installer, answers, asked = box
    installer.checker.latest = lambda: Release("0.3.1")
    answers.append("n")

    assert update_module.update(is_confirmed=False, package=None) == 1

    out = capsys.readouterr().out
    assert "running 0.3.0; newest release 0.3.1" in out
    assert "published 2026-10-01T12:00:00Z; 100 MB" in out
    assert "https://example.invalid/0.3.1" in out
    assert "  line 0" in out
    assert "  line 19" in out
    assert "  line 20" not in out
    assert "  …" in out
    assert "needs 400 MB free" in out
    assert asked == ["install 0.3.1 over 0.3.0? [y/N] "]
    assert installer.prepared == []
    assert installer.launched == []


def test_a_missing_rollback_is_said_before_the_question(box, capsys):
    installer, answers, _ = box
    installer.checker.latest = lambda: Release("0.3.1")
    installer.rollback_available = False
    answers.append("n")

    update_module.update(is_confirmed=False, package=None)

    assert "nothing can be put back" in capsys.readouterr().out


def test_too_little_room_is_refused_without_asking(box, monkeypatch, capsys):
    installer, _, asked = box
    installer.checker.latest = lambda: Release("0.3.1")

    def short(size, *, is_rollback_fetched):
        raise HubUpdateError(
            "disk_space_short", path="/var/lib", needed_bytes=400, free_bytes=1
        )

    monkeypatch.setattr(update_module, "check_space", short)

    assert update_module.update(is_confirmed=False, package=None) == 1
    assert "disk_space_short" in capsys.readouterr().err
    assert asked == []


def test_a_yes_stages_hands_over_and_waits_for_the_record(box, capsys):
    installer, answers, asked = box
    installer.checker.latest = lambda: Release("0.3.1")
    answers.append("y")
    settle(installer.state, "installed")

    assert update_module.update(is_confirmed=False, package=None) == 0

    out = capsys.readouterr().out
    assert asked == ["install 0.3.1 over 0.3.0? [y/N] "]
    assert installer.prepared == [("0.3.1", "0.3.0", 8090)]
    assert [plan.to_version for plan in installer.launched] == ["0.3.1"]
    assert "downloading" in out
    assert "handed to systemd as neutrino_hub_update" in out
    assert "installed 0.3.1 over 0.3.0" in out


def test_the_flag_skips_the_question(box):
    installer, _, asked = box
    installer.checker.latest = lambda: Release("0.3.1")
    settle(installer.state, "installed")

    assert update_module.update(is_confirmed=True, package=None) == 0
    assert asked == []
    assert len(installer.launched) == 1


def test_a_rollback_is_reported_with_its_reason(box, capsys):
    installer, _, _ = box
    installer.checker.latest = lambda: Release("0.3.1")
    settle(
        installer.state,
        "rolled_back",
        reason="health_gate_failed",
        output="gate: timed out",
    )

    assert update_module.update(is_confirmed=True, package=None) == 1

    err = capsys.readouterr().err
    assert "rolled_back: 0.3.1 was given up on (health_gate_failed)" in err
    assert "gate: timed out" in err


def test_a_record_that_never_settles_says_where_to_look(box, capsys):
    installer, _, _ = box
    installer.checker.latest = lambda: Release("0.3.1")

    assert update_module.update(is_confirmed=True, package=None) == 1
    assert "journalctl -u neutrino_hub_update" in capsys.readouterr().err


def test_an_update_already_under_way_is_refused(box, capsys):
    installer, _, _ = box
    installer.is_active = True

    assert update_module.update(is_confirmed=True, package=None) == 1
    assert "already under way" in capsys.readouterr().err


def test_a_package_file_is_asked_about_by_name_and_staged(box, tmp_path, capsys):
    installer, answers, asked = box
    brought = tmp_path / "neutrino-hub_0.3.1_amd64.deb"
    brought.write_bytes(b"deb")
    answers.append("y")
    settle(installer.state, "installed")

    assert update_module.update(is_confirmed=False, package=brought) == 0

    assert asked == ["install neutrino-hub_0.3.1_amd64.deb over 0.3.0? [y/N] "]
    assert installer.prepared == [("neutrino-hub_0.3.1_amd64.deb", "0.3.0", 8090)]
    assert "is in place" in capsys.readouterr().out


def test_a_package_file_that_is_not_there_is_an_error(box, tmp_path, capsys):
    installer, _, _ = box

    assert update_module.update(is_confirmed=True, package=tmp_path / "x.deb") == 1
    assert "is not a file" in capsys.readouterr().err
    assert installer.launched == []


def test_a_staging_that_fails_is_reported_with_its_reason(box, capsys):
    installer, _, _ = box
    installer.checker.latest = lambda: Release("0.3.1")

    def failing(found, *, current, port, on_progress):
        raise HubUpdateError("package_sha256_mismatch", name=found.asset_name)

    installer.prepare = failing

    assert update_module.update(is_confirmed=True, package=None) == 1
    assert (
        "package_sha256_mismatch (name=neutrino-hub_0.3.1_amd64.deb)"
        in capsys.readouterr().err
    )
    assert installer.launched == []


def test_the_command_is_registered_and_needs_root():
    from neutrino_hub.cli.entry import COMMANDS

    assert COMMANDS["update"][0] == "neutrino_hub.cli.update"
