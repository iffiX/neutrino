"""The EasyTier daemon's state and the requests that change it.

A recording supervisor stands in for the core. Pinned here: every refusal
the daemon answers and with which code, what a join writes and with which
mode, that the state directory alone is what a restart reads back, the
core's argument vector and environment for each kind of state (never a
core with nothing configured, a console only in the environment, a manual
network only through its directory), that an unchanged join restarts
nothing, and that no answer carries a secret or a console's address.
"""

import json
import os

import pytest

from neutrino_client.constants import CLIENT_EASYTIER_RPC_PORTAL
from neutrino_client.core.easytier_daemon import EasytierDaemon, console_digest
from tests.conftest import discard

SECRET = 's3cret "quoted"'  # scan: allow
CONSOLE = "tcp://et-web.console.easytier.net:22020/etk_abc123"  # scan: allow
CORE = "/opt/neutrino_client/easytier/easytier-core"


class RecordingSupervisor:
    """Counts each restart and reads the command the daemon would run."""

    def __init__(self):
        self.commands = []
        self.is_running = False
        self.daemon = None

    def apply(self):
        command = self.daemon.core_command()
        self.commands.append(command)
        self.is_running = command is not None


def make_daemon(tmp_path, core_path=CORE):
    supervisor = RecordingSupervisor()
    daemon = EasytierDaemon(
        state_dir=str(tmp_path / "state"),
        core_path=core_path,
        supervisor=supervisor,
        log=discard,
    )
    supervisor.daemon = daemon
    return daemon, supervisor


def join_request(**changes):
    request = {
        "verb": "join",
        "network_name": "home",
        "network_secret": SECRET,
        "peer": "tcp://203.0.113.7:11010",
        "hostname": "box",
    }
    request.update(changes)
    return request


def console_request(**changes):
    request = {"verb": "join_console", "config_server": CONSOLE, "is_secure_mode": True}
    request.update(changes)
    return request


# --- refusals ---


@pytest.mark.parametrize(
    "request_, code",
    [
        (None, "overlay_request_invalid"),
        ("join", "overlay_request_invalid"),
        ({}, "overlay_request_invalid"),
        ({"verb": "delete"}, "overlay_request_invalid"),
        (join_request(network_name="../etc"), "overlay_network_invalid"),
        (join_request(network_name=""), "overlay_network_invalid"),
        (join_request(network_name=7), "overlay_network_invalid"),
        (join_request(peer="http://203.0.113.7:11010"), "overlay_peer_invalid"),
        (join_request(peer="tcp://203.0.113.7"), "overlay_peer_invalid"),
        (join_request(peer="tcp://h:1/path"), "overlay_peer_invalid"),
        (join_request(network_secret=""), "overlay_secret_missing"),
        (join_request(network_secret="x" * 5000), "overlay_secret_missing"),
        (join_request(hostname="a b"), "overlay_request_invalid"),
        (
            console_request(config_server="http://c.example:1/t"),
            "overlay_console_invalid",
        ),
        (console_request(config_server="tcp://c.example/t"), "overlay_console_invalid"),
        (console_request(config_server="tcp://c.example:1"), "overlay_console_invalid"),
        (
            console_request(config_server="tcp://c.example:1/a/b"),
            "overlay_console_invalid",
        ),
        (
            console_request(config_server="tcp://u@c.example:1/t"),
            "overlay_console_invalid",
        ),
        (console_request(is_secure_mode="yes"), "overlay_request_invalid"),
        ({"verb": "leave", "network_name": "a/b"}, "overlay_network_invalid"),
    ],
)
def test_every_refusal_is_typed_and_changes_nothing(tmp_path, request_, code):
    daemon, supervisor = make_daemon(tmp_path)

    answer = daemon.handle(request_)

    assert answer["code"] == code
    assert supervisor.commands == []
    assert daemon.networks() == [] and daemon.console() is None


def test_an_install_without_the_core_refuses_a_join(tmp_path):
    daemon, _supervisor = make_daemon(tmp_path, core_path="")

    assert daemon.handle(join_request()) == {
        "code": "bundle_missing",
        "params": {"binary": "easytier-core"},
    }
    assert daemon.handle(console_request())["code"] == "bundle_missing"


def test_a_second_console_is_another_network(tmp_path):
    daemon, supervisor = make_daemon(tmp_path)
    daemon.handle(console_request())

    answer = daemon.handle(console_request(config_server="tcp://o.example:1/etk_o"))

    assert answer["code"] == "overlay_other_network"
    assert daemon.console()["config_server"] == CONSOLE
    assert len(supervisor.commands) == 1


# --- joining and leaving ---


def test_a_join_writes_the_networks_file_for_root_alone(tmp_path):
    daemon, supervisor = make_daemon(tmp_path)

    answer = daemon.handle(join_request())

    path = tmp_path / "state" / "networks" / "home.toml"
    assert os.stat(path).st_mode & 0o777 == 0o600
    text = path.read_text()
    assert r'network_secret = "s3cret \"quoted\""' in text  # scan: allow
    assert 'uri = "tcp://203.0.113.7:11010"' in text
    assert 'hostname = "box"' in text
    assert answer == {"networks": ["home"], "console": None, "is_running": True}
    assert len(supervisor.commands) == 1


def test_an_unchanged_join_restarts_nothing(tmp_path):
    daemon, supervisor = make_daemon(tmp_path)
    daemon.handle(join_request())
    daemon.handle(console_request())

    daemon.handle(join_request())
    daemon.handle(console_request())

    assert len(supervisor.commands) == 2


def test_a_changed_secret_or_secure_mode_restarts_the_core(tmp_path):
    daemon, supervisor = make_daemon(tmp_path)
    daemon.handle(join_request())
    daemon.handle(console_request())

    daemon.handle(join_request(network_secret="other"))
    daemon.handle(console_request(is_secure_mode=False))

    assert len(supervisor.commands) == 4
    assert daemon.console()["is_secure_mode"] is False


def test_leaving_takes_the_network_and_the_console_away(tmp_path):
    daemon, supervisor = make_daemon(tmp_path)
    daemon.handle(join_request())
    daemon.handle(console_request())

    assert daemon.handle({"verb": "leave", "network_name": "home"})["networks"] == []
    assert daemon.handle({"verb": "leave_console"})["console"] is None
    assert supervisor.commands[-1] is None
    assert supervisor.is_running is False


def test_leaving_what_is_not_there_restarts_nothing(tmp_path):
    daemon, supervisor = make_daemon(tmp_path)

    daemon.handle({"verb": "leave", "network_name": "home"})
    daemon.handle({"verb": "leave_console"})

    assert supervisor.commands == []


# --- the core's command ---


def test_nothing_configured_runs_no_core(tmp_path):
    daemon, _supervisor = make_daemon(tmp_path)

    assert daemon.core_command() is None


def test_manual_networks_run_the_core_on_their_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("ET_NETWORK_NAME", "stray")
    monkeypatch.setenv("PATH", "/usr/bin")
    daemon, _supervisor = make_daemon(tmp_path)
    daemon.handle(join_request())

    argv, env = daemon.core_command()

    assert argv == [
        CORE,
        "--rpc-portal",
        CLIENT_EASYTIER_RPC_PORTAL,
        "--console-log-level",
        "warn",
        "--config-dir",
        str(tmp_path / "state" / "networks"),
    ]
    assert "ET_NETWORK_NAME" not in env
    assert "ET_CONFIG_SERVER" not in env
    assert env["PATH"] == "/usr/bin"


def test_a_console_reaches_the_core_in_its_environment_alone(tmp_path):
    daemon, _supervisor = make_daemon(tmp_path)
    daemon.handle(console_request())

    argv, env = daemon.core_command()

    assert "--config-dir" not in argv
    assert all("etk_abc123" not in part for part in argv)
    assert env["ET_CONFIG_SERVER"] == CONSOLE
    assert env["ET_SECURE_MODE"] == "true"


def test_a_console_and_a_network_run_one_core_with_both(tmp_path):
    daemon, _supervisor = make_daemon(tmp_path)
    daemon.handle(join_request())
    daemon.handle(console_request(is_secure_mode=False))

    argv, env = daemon.core_command()

    assert "--config-dir" in argv
    assert env["ET_CONFIG_SERVER"] == CONSOLE
    assert "ET_SECURE_MODE" not in env


# --- persistence ---


def test_a_restart_restores_what_the_directory_holds(tmp_path):
    first, _supervisor = make_daemon(tmp_path)
    first.handle(join_request())
    first.handle(join_request(network_name="office"))
    first.handle(console_request())

    second, supervisor = make_daemon(tmp_path)
    second.restore()

    assert second.networks() == ["home", "office"]
    assert second.console() == {"config_server": CONSOLE, "is_secure_mode": True}
    (command,) = supervisor.commands
    assert command is not None


def test_a_restore_with_nothing_runs_nothing_and_makes_the_directory(tmp_path):
    daemon, supervisor = make_daemon(tmp_path)

    daemon.restore()

    assert (tmp_path / "state" / "networks").is_dir()
    assert supervisor.commands == [None]


def test_a_console_file_the_daemon_did_not_write_is_no_console(tmp_path):
    daemon, _supervisor = make_daemon(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "console.json").write_text(
        json.dumps({"config_server": "tcp://h:1/a b"})
    )

    assert daemon.console() is None
    assert daemon.core_command() is None


def test_the_console_file_is_root_alone(tmp_path):
    daemon, _supervisor = make_daemon(tmp_path)
    daemon.handle(console_request())

    path = tmp_path / "state" / "console.json"
    assert os.stat(path).st_mode & 0o777 == 0o600


# --- what an answer carries ---


def test_no_answer_carries_a_secret_or_a_consoles_address(tmp_path):
    daemon, _supervisor = make_daemon(tmp_path)
    answers = [
        daemon.handle(join_request()),
        daemon.handle(console_request()),
        daemon.handle({"verb": "status"}),
    ]

    words = json.dumps(answers)
    assert "s3cret" not in words and "etk_abc123" not in words  # scan: allow
    assert answers[-1]["console"] == {
        "digest": console_digest(CONSOLE),
        "is_secure_mode": True,
    }


def test_a_write_that_fails_is_a_typed_refusal(tmp_path, monkeypatch):
    daemon, supervisor = make_daemon(tmp_path)

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("neutrino_client.core.files.write_text", refuse)

    assert daemon.handle(join_request()) == {
        "code": "overlay_restart_failed",
        "params": {"detail": "Permission denied"},
    }
    assert supervisor.commands == []
