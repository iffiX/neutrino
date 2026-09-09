"""What `nhub reset` returns to a fresh state, and what it leaves alone.

`reset all` is the one command in the hub that destroys something no backup
inside the box holds — the node credentials, the device tokens and the SSH
keys. What is tested here is that it destroys exactly those and nothing near
them, and that `reset password` touches only the password.
"""

import json

import pytest

from neutrino_hub.cli import password, reset
from neutrino_hub.cli import stop as stop_module
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
        (
            "credentials/vault.example.json",
            {"version": 2, "secrets": {}},
        ),
    ):
        path = examples / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))

    (config / "web").mkdir(parents=True)
    (config / "web/settings.json").write_text(
        json.dumps({"admin_password_hash": "real-hash"})
    )
    (config / "xray").mkdir()
    (config / "xray/nodes.json").write_text(json.dumps({"nodes": [{"id": "hk"}]}))
    (config / "devices/aa-bb-cc-dd-ee-ff").mkdir(parents=True)
    (config / "devices/aa-bb-cc-dd-ee-ff/modules.json").write_text("{}")
    (config / "devices/devices.json").write_text("{}")
    (config / "credentials").mkdir(parents=True)
    (config / "credentials/vault.json").write_text(
        json.dumps(
            {
                "version": 2,
                "wrapped_key": {"kdf": "scrypt"},
                "secrets": {"048044bd": {"name": "a key", "kind": "ssh_key"}},
            }
        )
    )
    (config / "web/agent_tls").mkdir()
    (config / "web/agent_tls/certificate.pem").write_text("cert")

    state = config.parent / "state"
    state.mkdir()
    (state / "session.secret").write_text("aa" * 32)
    (state / "vault.key").write_text("bb" * 32)

    monkeypatch.setattr(reset, "UTILS_CONFIG_DIR", config)
    monkeypatch.setattr(reset, "UTILS_EXAMPLES_DIR", examples)
    monkeypatch.setattr(reset, "UTILS_STATE_ROOT", state)
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config)
    monkeypatch.setattr(reset, "stop_everything", lambda: 0)
    return config


def test_reset_all_returns_every_config_to_its_example(box):
    reset._reset_all()

    assert json.loads((box / "xray/nodes.json").read_text()) == {"nodes": []}


def test_reset_all_forgets_the_keys_the_box_was_holding(box):
    """A key left behind after a reset is a key the next owner inherits."""
    reset._reset_all()

    vault = json.loads((box / "credentials/vault.json").read_text())
    assert vault["secrets"] == {}
    assert "wrapped_key" not in vault
    assert not (box / "devices/aa-bb-cc-dd-ee-ff").exists()
    assert (box / "devices/devices.json").exists()
    assert not (box / "web/agent_tls").exists()
    assert not (box.parent / "state" / "session.secret").exists()
    assert not (box.parent / "state" / "vault.key").exists()


def test_reset_all_clears_the_password_so_setup_runs_again(box):
    reset._reset_all()

    assert not password.is_password_set()


def test_reset_password_leaves_every_other_setting_alone(box):
    (box / "web/settings.json").write_text(
        json.dumps(
            {
                "admin_password_hash": "real-hash",
                "listen_port": 9999,
            }
        )
    )

    password.store_password("a-long-enough-password")

    settings = json.loads((box / "web/settings.json").read_text())
    assert settings["listen_port"] == 9999
    assert settings["admin_password_hash"] != "real-hash"
    assert password.is_password_set()


def test_a_box_carrying_only_the_example_has_no_password_yet(box):
    """What makes `nhub setup` a thing that runs once."""
    password.clear_password()

    assert not password.is_password_set()


# --- what is left running afterwards ---


def _controller(monkeypatch, *, is_active=True, refusing=()):
    """A systemd that records what it was asked to stop."""
    asked: list = []

    class Controller:
        def status(self, name):
            return type("Status", (), {"is_installed": True, "is_active": is_active})()

        def control(self, name, action):
            asked.append((name, action))
            if name in refusing:
                raise CommandError("systemctl stop timed out after 60s")

    monkeypatch.setattr(stop_module, "SystemdServiceController", Controller)
    return asked


def test_a_reset_leaves_nothing_of_the_hub_running(monkeypatch, box):
    """A reset is the box before anybody set it up, and on that box none of
    this is running. The panel used to be restarted instead — left answering
    with no password to let anyone in, on a configuration nobody chose."""
    asked = _controller(monkeypatch)
    monkeypatch.setattr(
        reset, "stop_everything", lambda: stop_module.stop(list(stop_module.STOP_ORDER))
    )

    reset._reset_all()

    assert [name for name, _ in asked] == list(stop_module.STOP_ORDER)
    assert {action for _, action in asked} == {"stop"}


def test_the_panel_goes_first(monkeypatch, box):
    """It is what somebody is holding: stopping it while the proxy under it
    is already gone means a page that hangs rather than one that closes."""
    asked = _controller(monkeypatch)
    monkeypatch.setattr(
        reset, "stop_everything", lambda: stop_module.stop(list(stop_module.STOP_ORDER))
    )

    reset._reset_all()

    assert asked[0][0] == "web"


def test_a_service_that_will_not_stop_is_reported_rather_than_raised(
    monkeypatch, box, capsys
):
    """One unit refusing must not hide what happened to the others, and a
    traceback would say the reset failed when what failed was one stop."""
    asked = _controller(monkeypatch, refusing=("xray",))
    monkeypatch.setattr(
        reset, "stop_everything", lambda: stop_module.stop(list(stop_module.STOP_ORDER))
    )

    assert reset._reset_all() == 0
    assert [name for name, _ in asked] == list(stop_module.STOP_ORDER)
    assert "did not stop" in capsys.readouterr().err


def test_what_is_already_stopped_is_not_stopped_again(monkeypatch, box):
    asked = _controller(monkeypatch, is_active=False)
    monkeypatch.setattr(
        reset, "stop_everything", lambda: stop_module.stop(list(stop_module.STOP_ORDER))
    )

    reset._reset_all()

    assert asked == []
