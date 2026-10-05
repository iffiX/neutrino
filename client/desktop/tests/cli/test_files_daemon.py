"""``nclient files-daemon``: the daemon put together, and its verb.

The platform is a fake over a temporary directory, tun2socks a fake process
and giving the adapter its address a recorded call, so the whole daemon
runs here over a real socket: it serves nobody at start, an ``up`` starts
tun2socks and gives the adapter its address, a ``down`` and a stop end it.
The verb is the one the Windows service runs, and no person sees it.
"""

import os

import pytest

import neutrino_client.cli.files_daemon as daemon_cli
import neutrino_client.core.files_daemon as files_daemon_module
from neutrino_client.cli import entry
from neutrino_client.control.easytier_socket import ask_easytier_daemon
from neutrino_client.platforms.base import ClientPlatform
from tests.conftest import discard

UP = {"verb": "up", "port": 40001, "user": "u1", "password": "p1"}


class FilesPlatform(ClientPlatform):
    """Answers where the daemon lives from a temporary directory."""

    def __init__(self, tmp_path):
        self.logs = str(tmp_path / "log" / "client")
        self.address = str(tmp_path / "files.sock")
        self.bound = []
        self.configured = 0

    def files_daemon_address(self):
        return self.address

    def easytier_log_dir(self):
        return self.logs

    def configure_files_adapter(self):
        self.configured += 1

    def bind_child_process(self, process):
        self.bound.append(process)


class FakeTun2socks:
    def __init__(self, argv, env):
        self.argv = argv
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
def started(monkeypatch):
    processes = []

    def start(argv, env):
        process = FakeTun2socks(argv, env)
        processes.append(process)
        return process

    import neutrino_client.core.easytier_supervisor as supervisor_module

    monkeypatch.setattr(supervisor_module, "start_core_process", start)
    monkeypatch.setattr(daemon_cli, "bundled_path", lambda binary: "C:\\" + binary)
    monkeypatch.setattr(files_daemon_module, "adapter_carries", lambda: True)
    return processes


def test_the_daemon_serves_nobody_at_start_and_answers(tmp_path, started):
    platform = FilesPlatform(tmp_path)

    parts = daemon_cli.start_daemon(platform, discard)
    try:
        answer = ask_easytier_daemon(platform.address, {"verb": "status"})
    finally:
        daemon_cli.stop_daemon(parts, discard)

    assert answer == {"is_up": False, "port": 0}
    assert started == []
    assert os.path.isfile(os.path.join(platform.logs, "tun2socks.log"))
    assert not os.path.exists(platform.address)


def test_up_over_the_socket_starts_tun2socks_and_a_stop_ends_it(tmp_path, started):
    platform = FilesPlatform(tmp_path)
    parts = daemon_cli.start_daemon(platform, discard)
    try:
        answer = ask_easytier_daemon(platform.address, dict(UP))
    finally:
        daemon_cli.stop_daemon(parts, discard)

    assert answer == {"is_up": True, "port": 40001}
    (process,) = started
    assert process.argv[0] == "C:\\tun2socks"
    assert "socks5://u1:p1@127.0.0.1:40001" in process.argv  # scan: allow
    assert platform.configured == 1
    assert platform.bound == [process]
    assert process.status == -15


def test_down_over_the_socket_ends_tun2socks(tmp_path, started):
    platform = FilesPlatform(tmp_path)
    parts = daemon_cli.start_daemon(platform, discard)
    try:
        ask_easytier_daemon(platform.address, dict(UP))
        answer = ask_easytier_daemon(platform.address, {"verb": "down"})
    finally:
        daemon_cli.stop_daemon(parts, discard)

    assert answer == {"is_up": False, "port": 0}
    assert started[0].status == -15


def test_a_request_over_the_size_limit_is_the_files_refusal(tmp_path, started):
    platform = FilesPlatform(tmp_path)
    parts = daemon_cli.start_daemon(platform, discard)
    try:
        answer = ask_easytier_daemon(
            platform.address, {"verb": "up", "user": "u" * 70000}
        )
    finally:
        daemon_cli.stop_daemon(parts, discard)

    assert answer == {"code": "files_adapter_unavailable", "params": {}}


def test_a_second_daemon_on_a_live_socket_is_refused(tmp_path, started):
    platform = FilesPlatform(tmp_path)
    parts = daemon_cli.start_daemon(platform, discard)
    try:
        with pytest.raises(OSError):
            daemon_cli.start_daemon(platform, discard)
    finally:
        daemon_cli.stop_daemon(parts, discard)


def test_a_platform_with_no_files_adapter_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(daemon_cli, "detect_platform", lambda: ClientPlatform())

    assert daemon_cli.main() == 1
    assert "no files adapter on this platform" in capsys.readouterr().err


def test_the_windows_service_passes_its_flag(monkeypatch):
    seen = []
    monkeypatch.setattr(entry.sys, "argv", ["nclient", "files-daemon", "--service"])
    monkeypatch.setattr(
        entry.files_daemon,
        "main",
        lambda *, is_service: seen.append(is_service) or 0,
    )

    assert entry.main() == 0
    assert seen == [True]


def test_the_verb_is_not_in_a_persons_help(monkeypatch, capsys):
    monkeypatch.setattr(entry.sys, "argv", ["nclient", "--help"])

    with pytest.raises(SystemExit):
        entry.main()

    assert "files-daemon" not in capsys.readouterr().out
