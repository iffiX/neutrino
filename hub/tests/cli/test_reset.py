"""What `nhub reset` returns to a fresh state, and what it leaves alone.

`reset all` is the one command in the hub that destroys something no backup
inside the box holds — the node credentials, the device tokens and the SSH
keys. What is tested here is that it destroys exactly those and nothing near
them, and that `reset password` touches only the password.
"""

import json

import pytest

from neutrino_hub.cli import password, reset
from neutrino_hub.utils.subprocess_run import CommandError


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A configured box: real files, collected keys, and the examples beside."""
    examples = tmp_path / "examples"
    config = tmp_path / "config"
    for name, body in (
        (
            "web/settings.example.json",
            {"admin_password_hash": "PLACEHOLDER_ARGON2ID_HASH"},
        ),
        ("xray/nodes.example.json", {"nodes": []}),
    ):
        path = examples / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))

    (config / "web").mkdir(parents=True)
    (config / "web/settings.json").write_text(
        json.dumps({"admin_password_hash": "real-hash", "session_secret": "abc"})
    )
    (config / "xray").mkdir()
    (config / "xray/nodes.json").write_text(json.dumps({"nodes": [{"id": "hk"}]}))
    (config / "gitea").mkdir()
    (config / "gitea/secrets.json").write_text("{}")
    (config / "credentials/ssh_keys").mkdir(parents=True)
    (config / "credentials/ssh_keys/048044bd").write_text("PRIVATE KEY")

    monkeypatch.setattr(reset, "UTILS_CONFIG_DIR", config)
    monkeypatch.setattr(reset, "UTILS_EXAMPLES_DIR", examples)
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config)
    monkeypatch.setattr(reset, "_restart_panel", _do_nothing)
    return config


def _do_nothing() -> None:
    """Stand in for the panel restart, which no test may perform."""


def test_reset_all_returns_every_config_to_its_example(box):
    reset._reset_all()

    assert json.loads((box / "xray/nodes.json").read_text()) == {"nodes": []}


def test_reset_all_forgets_the_keys_no_example_replaces(box):
    """A key left behind after a reset is a key the next owner inherits."""
    reset._reset_all()

    assert not (box / "credentials/ssh_keys/048044bd").exists()
    assert not (box / "gitea/secrets.json").exists()


def test_reset_all_clears_the_password_so_setup_runs_again(box):
    reset._reset_all()

    assert not password.is_password_set()


def test_reset_password_leaves_every_other_setting_alone(box):
    (box / "web/settings.json").write_text(
        json.dumps(
            {
                "admin_password_hash": "real-hash",
                "session_secret": "abc",
                "listen_port": 9999,
            }
        )
    )

    password.store_password("a-long-enough-password")

    settings = json.loads((box / "web/settings.json").read_text())
    assert settings["listen_port"] == 9999
    assert settings["session_secret"] == "abc"
    assert settings["admin_password_hash"] != "real-hash"
    assert password.is_password_set()


def test_a_box_carrying_only_the_example_has_no_password_yet(box):
    """What makes `nhub setup` a thing that runs once."""
    password.clear_password()

    assert not password.is_password_set()


# --- when the last step of a reset will not work ---


def test_a_panel_that_will_not_restart_is_reported_rather_than_raised(monkeypatch):
    """Everything a reset exists to undo is undone before this runs, so a
    service that will not come back is a line to print — a traceback here
    would say the reset failed when what failed was one service starting."""

    class RefusingController:
        def status(self, name):
            return type("Status", (), {"is_installed": True})()

        def control(self, name, action):
            raise CommandError("systemctl restart timed out after 60s")

    monkeypatch.setattr(reset, "SystemdServiceController", RefusingController)

    message = reset._restart_panel()

    assert "did not come back" in message
    assert "timed out" in message


def test_a_box_with_no_panel_unit_has_nothing_to_report(monkeypatch):
    class AbsentController:
        def status(self, name):
            return type("Status", (), {"is_installed": False})()

        def control(self, name, action):
            raise AssertionError("there was nothing to restart")

    monkeypatch.setattr(reset, "SystemdServiceController", AbsentController)

    assert reset._restart_panel() == ""
