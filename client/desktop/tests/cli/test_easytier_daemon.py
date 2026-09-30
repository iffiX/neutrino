"""``nclient easytier-daemon``: the daemon put together, and its verb.

The platform is a fake over a temporary directory and the core a fake
process, so the whole daemon runs here: its state directory is made for
root alone, what it held is restored and run at start with no client
asking, a join over the real socket starts the core, a stop takes the core
and the socket down. The verb is the one the system runs as root, and the
one no person is refused for being root.
"""

import os

import pytest

import neutrino_client.cli.easytier_daemon as daemon_cli
import neutrino_client.core.easytier_supervisor as supervisor_module
from neutrino_client.cli import entry
from neutrino_client.control.easytier_socket import ask_easytier_daemon
from neutrino_client.platforms.base import ClientPlatform
from tests.conftest import discard


class DaemonPlatform(ClientPlatform):
    """Answers where the daemon lives from a temporary directory."""

    def __init__(self, tmp_path):
        self.state = str(tmp_path / "state")
        self.address = str(tmp_path / "easytier.sock")
        self.bound = []

    def easytier_state_dir(self):
        return self.state

    def easytier_daemon_address(self):
        return self.address

    def bind_child_process(self, process):
        self.bound.append(process)


class FakeCore:
    def __init__(self, argv, env):
        self.argv = argv
        self.env = env
        self.status = None
        self.stdout = None
        self.pid = 1

    def poll(self):
        return self.status

    def terminate(self):
        self.status = -15

    def kill(self):
        self.status = -9

    def wait(self, timeout=None):
        return self.status


@pytest.fixture
def cores(monkeypatch):
    started = []

    def start(argv, env):
        core = FakeCore(argv, env)
        started.append(core)
        return core

    monkeypatch.setattr(supervisor_module, "start_core_process", start)
    monkeypatch.setattr(daemon_cli, "bundled_path", lambda binary: "/opt/" + binary)
    return started


def test_the_daemon_makes_its_state_for_root_alone_and_answers(tmp_path, cores):
    platform = DaemonPlatform(tmp_path)

    parts = daemon_cli.start_daemon(platform, platform.state, discard)
    try:
        answer = ask_easytier_daemon(platform.address, {"verb": "status"})
    finally:
        daemon_cli.stop_daemon(parts, discard)

    assert os.stat(platform.state).st_mode & 0o777 == 0o700
    assert answer == {"networks": [], "console": None, "is_running": False}
    assert cores == []
    assert not os.path.exists(platform.address)


def test_a_join_over_the_socket_starts_the_core_and_a_stop_ends_it(tmp_path, cores):
    platform = DaemonPlatform(tmp_path)
    parts = daemon_cli.start_daemon(platform, platform.state, discard)
    try:
        answer = ask_easytier_daemon(
            platform.address,
            {
                "verb": "join",
                "network_name": "home",
                "network_secret": "s3cret",  # scan: allow
                "peer": "tcp://203.0.113.7:11010",
                "hostname": "box",
            },
        )
    finally:
        daemon_cli.stop_daemon(parts, discard)

    assert answer["networks"] == ["home"] and answer["is_running"] is True
    (core,) = cores
    assert core.argv[0] == "/opt/easytier-core"
    assert "--config-dir" in core.argv
    assert platform.bound == [core]
    assert core.status == -15


def test_what_was_joined_comes_back_at_start_with_no_client(tmp_path, cores):
    platform = DaemonPlatform(tmp_path)
    parts = daemon_cli.start_daemon(platform, platform.state, discard)
    ask_easytier_daemon(
        platform.address,
        {
            "verb": "join_console",
            "config_server": "tcp://et-web.console.easytier.net:22020/etk_a",
            "is_secure_mode": True,
        },
    )
    daemon_cli.stop_daemon(parts, discard)

    parts = daemon_cli.start_daemon(platform, platform.state, discard)
    daemon_cli.stop_daemon(parts, discard)

    assert len(cores) == 2
    assert cores[1].argv[-3:] == [
        "--config-server",
        "tcp://et-web.console.easytier.net:22020/etk_a",
        "--secure-mode=true",
    ]


def test_a_second_daemon_on_a_live_socket_is_refused(tmp_path, cores):
    platform = DaemonPlatform(tmp_path)
    parts = daemon_cli.start_daemon(platform, platform.state, discard)
    try:
        with pytest.raises(OSError):
            daemon_cli.start_daemon(platform, platform.state, discard)
        assert ask_easytier_daemon(platform.address, {"verb": "status"})
    finally:
        daemon_cli.stop_daemon(parts, discard)


def test_a_platform_with_no_easytier_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(daemon_cli, "detect_platform", lambda: ClientPlatform())

    assert daemon_cli.main() == 1
    assert "no EasyTier daemon" in capsys.readouterr().err


def test_the_verb_runs_the_daemon_as_root(monkeypatch):
    seen = []
    monkeypatch.setattr(entry.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(entry.sys, "argv", ["nclient", "easytier-daemon"])
    monkeypatch.setattr(
        entry.easytier_daemon,
        "main",
        lambda *, is_service: seen.append(is_service) or 0,
    )

    assert entry.main() == 0
    assert seen == [False]


def test_the_windows_service_passes_its_flag(monkeypatch):
    seen = []
    monkeypatch.setattr(entry.sys, "argv", ["nclient", "easytier-daemon", "--service"])
    monkeypatch.setattr(
        entry.easytier_daemon,
        "main",
        lambda *, is_service: seen.append(is_service) or 0,
    )

    assert entry.main() == 0
    assert seen == [True]


def test_the_verb_is_not_in_a_persons_help(monkeypatch, capsys):
    monkeypatch.setattr(entry.sys, "argv", ["nclient", "--help"])

    with pytest.raises(SystemExit):
        entry.main()

    assert "easytier-daemon" not in capsys.readouterr().out
