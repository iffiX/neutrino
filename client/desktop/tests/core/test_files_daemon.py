"""The files daemon: tun2socks on the adapter for the resident that asked last.

tun2socks is a fake process and giving the adapter its address a recorded
call, so the whole state machine runs here: up starts tun2socks towards the
endpoint and gives the adapter its address, the same up again changes
nothing, another endpoint restarts it, down ends it, and every failure is
the one refusal with what failed. No answer and no log line carries the
user name or the password.
"""

import pytest

from neutrino_client.core.files_daemon import (
    FilesAdapterDaemon,
    tun2socks_command,
)

UP = {"verb": "up", "port": 40001, "user": "u1", "password": "p-Secret_1"}


class FakeTun2socks:
    def __init__(self, argv, env):
        self.argv = argv
        self.env = env
        self.status = None
        self.stdout = None
        self.pid = 7

    def poll(self):
        return self.status

    def terminate(self):
        self.status = -15

    def kill(self):
        self.status = -9

    def wait(self, timeout=None):
        return self.status


class Adapter:
    """Records each time the adapter is given its address."""

    def __init__(self):
        self.count = 0
        self.error = None

    def configure(self):
        self.count += 1
        if self.error is not None:
            raise self.error


@pytest.fixture
def started():
    return []


@pytest.fixture
def adapter():
    return Adapter()


@pytest.fixture
def lines():
    return []


@pytest.fixture
def daemon(started, adapter, lines):
    def start(argv, env):
        process = FakeTun2socks(argv, env)
        started.append(process)
        return process

    return FilesAdapterDaemon(
        tun2socks_path="C:\\nc\\bin\\tun2socks.exe",
        configure_adapter=adapter.configure,
        log=lines.append,
        start_process=start,
    )


def test_tun2socks_runs_on_the_adapter_towards_the_endpoint():
    assert tun2socks_command("t.exe", port=40001, user="u1", password="pw") == [
        "t.exe",
        "-device",
        "tun://neutrino_files",
        "-proxy",
        "socks5://u1:pw@127.0.0.1:40001",  # scan: allow
        "-mtu",
        "1500",
        "-loglevel",
        "warn",
    ]


def test_nothing_runs_until_a_resident_asks(daemon, started):
    assert daemon.command() is None
    assert daemon.handle({"verb": "status"}) == {"is_up": False, "port": 0}
    assert started == []


def test_up_starts_tun2socks_and_gives_the_adapter_its_address(
    daemon, started, adapter, lines
):
    answer = daemon.handle(dict(UP))

    assert answer == {"is_up": True, "port": 40001}
    (process,) = started
    assert process.argv == tun2socks_command(
        "C:\\nc\\bin\\tun2socks.exe", port=40001, user="u1", password="p-Secret_1"
    )
    assert adapter.count == 1
    assert "p-Secret_1" not in repr(answer)
    assert not any("p-Secret_1" in line or "u1:" in line for line in lines)
    assert "up for the endpoint on 127.0.0.1:40001" in lines


def test_the_same_up_again_changes_nothing(daemon, started, adapter):
    daemon.handle(dict(UP))
    answer = daemon.handle(dict(UP))

    assert answer == {"is_up": True, "port": 40001}
    assert len(started) == 1
    assert adapter.count == 1


def test_another_endpoint_restarts_tun2socks_for_the_one_that_asked_last(
    daemon, started, adapter
):
    daemon.handle(dict(UP))
    answer = daemon.handle(dict(UP, port=40002, password="p2"))

    assert answer == {"is_up": True, "port": 40002}
    assert len(started) == 2
    assert started[0].status == -15
    assert "socks5://u1:p2@127.0.0.1:40002" in started[1].argv  # scan: allow
    assert adapter.count == 2


def test_down_ends_tun2socks(daemon, started, lines):
    daemon.handle(dict(UP))
    answer = daemon.handle({"verb": "down"})

    assert answer == {"is_up": False, "port": 0}
    assert started[0].status == -15
    assert daemon.command() is None
    assert lines[-1] == "down"


@pytest.mark.parametrize(
    "request_",
    [
        None,
        {"verb": "launch"},
        dict(UP, port=0),
        dict(UP, port=True),
        dict(UP, port="40001"),
        dict(UP, user=""),
        dict(UP, password="has space"),
        dict(UP, password="has@at"),
        {"verb": "up"},
    ],
)
def test_a_request_of_another_shape_is_refused(daemon, started, request_):
    assert daemon.handle(request_) == {
        "code": "files_adapter_unavailable",
        "params": {"detail": "request_invalid"},
    }
    assert started == []


def test_an_install_with_no_tun2socks_is_refused(adapter, lines):
    daemon = FilesAdapterDaemon(
        tun2socks_path="", configure_adapter=adapter.configure, log=lines.append
    )

    assert daemon.handle(dict(UP)) == {
        "code": "files_adapter_unavailable",
        "params": {"detail": "bundle_missing"},
    }
    assert "no tun2socks in this install" in lines


def test_a_tun2socks_that_cannot_start_is_refused(adapter, lines):
    def refuse(argv, env):
        raise OSError("not a valid Win32 application")

    daemon = FilesAdapterDaemon(
        tun2socks_path="t.exe",
        configure_adapter=adapter.configure,
        log=lines.append,
        start_process=refuse,
    )

    assert daemon.handle(dict(UP)) == {
        "code": "files_adapter_unavailable",
        "params": {"detail": "tun2socks_not_started"},
    }
    assert "tun2socks could not start: not a valid Win32 application" in lines
    assert adapter.count == 0
    assert daemon.command() is None


def test_an_adapter_that_cannot_take_its_address_ends_tun2socks(
    daemon, started, adapter, lines
):
    adapter.error = OSError("the adapter neutrino_files is not up")

    answer = daemon.handle(dict(UP))

    assert answer == {
        "code": "files_adapter_unavailable",
        "params": {"detail": "the adapter neutrino_files is not up"},
    }
    assert started[0].status == -15
    assert daemon.status() == {"is_up": False, "port": 0}
    assert (
        "the adapter could not be given its address: "
        "the adapter neutrino_files is not up"
    ) in lines


def test_a_tun2socks_that_ended_and_came_back_gets_the_address_again(
    daemon, started, adapter, lines
):
    daemon.handle(dict(UP))
    started[0].status = 2

    assert daemon.status()["is_up"] is False
    daemon.supervisor.tick()
    daemon.supervisor.apply()
    daemon.tick()

    assert len(started) == 2
    assert adapter.count == 2
    assert daemon.status() == {"is_up": True, "port": 40001}
    assert "the adapter has its address again" in lines


def test_a_tick_with_nothing_due_does_nothing(daemon, adapter):
    daemon.tick()
    daemon.handle(dict(UP))
    daemon.tick()

    assert adapter.count == 1


def test_a_started_tun2socks_is_tied_to_the_daemon(adapter):
    tied = []
    daemon = FilesAdapterDaemon(
        tun2socks_path="t.exe",
        configure_adapter=adapter.configure,
        bind_child=tied.append,
        log=print,
        start_process=FakeTun2socks,
    )

    daemon.handle(dict(UP))

    assert len(tied) == 1 and tied[0].argv[0] == "t.exe"


def test_a_stop_ends_tun2socks_and_serves_nobody(daemon, started):
    daemon.handle(dict(UP))
    daemon.stop()

    assert started[0].status == -15
    assert daemon.status() == {"is_up": False, "port": 0}
