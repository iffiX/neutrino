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
    adapter_carries,
    tun2socks_command,
)

UP = {"verb": "up", "port": 40001, "user": "u1", "password": "p-Secret_1"}


def answered():
    """A probe through the adapter that is answered at once."""
    return True


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
        probe=answered,
    )


def test_tun2socks_runs_on_the_adapter_towards_the_endpoint():
    assert tun2socks_command("t.exe", port=40001, user="u1", password="pw") == [
        "t.exe",
        "--device",
        "tun://neutrino_files",
        "--proxy",
        "socks5://u1:pw@127.0.0.1:40001",  # scan: allow
        "--mtu",
        "1500",
        "--loglevel",
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
        tun2socks_path="",
        configure_adapter=adapter.configure,
        log=lines.append,
        probe=answered,
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
        probe=answered,
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
        probe=answered,
    )

    daemon.handle(dict(UP))

    assert len(tied) == 1 and tied[0].argv[0] == "t.exe"


def test_a_stop_ends_tun2socks_and_serves_nobody(daemon, started):
    daemon.handle(dict(UP))
    daemon.stop()

    assert started[0].status == -15
    assert daemon.status() == {"is_up": False, "port": 0}


class Clock:
    """Time that moves only when a probe or a pause spends it."""

    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class LateProbe:
    """Lost for the first probes, then answered, each probe spending its timeout."""

    def __init__(self, clock, lost):
        self.clock = clock
        self.lost = lost
        self.count = 0

    def __call__(self):
        self.count += 1
        self.clock.now += 2
        return self.count > self.lost


def test_up_is_answered_only_once_a_connection_through_the_adapter_is(
    started, adapter, lines
):
    """For some seconds after its address the adapter loses what it accepts,
    and a mount sent then fails as a refused login."""
    clock = Clock()
    probe = LateProbe(clock, lost=3)
    daemon = FilesAdapterDaemon(
        tun2socks_path="t.exe",
        configure_adapter=adapter.configure,
        log=lines.append,
        start_process=FakeTun2socks,
        probe=probe,
        clock=clock,
        sleep=clock.sleep,
    )

    answer = daemon.handle(dict(UP))

    assert answer == {"is_up": True, "port": 40001}
    assert probe.count == 4
    assert "the adapter carries connections after 9.5 s" in lines


def test_an_adapter_that_never_carries_a_connection_is_refused(adapter, lines):
    clock = Clock()
    processes = []

    def start(argv, env):
        processes.append(FakeTun2socks(argv, env))
        return processes[-1]

    daemon = FilesAdapterDaemon(
        tun2socks_path="t.exe",
        configure_adapter=adapter.configure,
        log=lines.append,
        start_process=start,
        probe=LateProbe(clock, lost=1000),
        clock=clock,
        sleep=clock.sleep,
    )

    answer = daemon.handle(dict(UP))

    assert answer == {
        "code": "files_adapter_unavailable",
        "params": {"detail": "the adapter neutrino_files carries no connection"},
    }
    assert processes[0].status == -15
    assert daemon.status() == {"is_up": False, "port": 0}


class ProbeSocket:
    def __init__(self, outcome):
        self.outcome = outcome
        self.timeouts = []
        self.is_closed = False

    def settimeout(self, value):
        self.timeouts.append(value)

    def recv(self, size):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def close(self):
        self.is_closed = True


@pytest.mark.parametrize(
    "outcome, is_carried",
    [
        (b"", True),
        (ConnectionResetError(10054, "reset"), True),
        (TimeoutError("timed out"), False),
    ],
)
def test_the_probe_counts_an_ended_connection_and_not_a_silent_one(outcome, is_carried):
    dialled = []
    connection = ProbeSocket(outcome)

    def dial(address, timeout):
        dialled.append((address, timeout))
        return connection

    assert adapter_carries(dial) is is_carried
    assert dialled == [(("198.19.255.254", 9), 2)]  # scan: allow
    assert connection.is_closed


def test_a_probe_that_cannot_connect_is_not_carried():
    def dial(address, timeout):
        raise OSError("no route")

    assert adapter_carries(dial) is False


ALICE = {"account": "alice", "pid": 4100}
ALICE_AGAIN = {"account": "Alice", "pid": 4200}
BOB = {"account": "bob", "pid": 5100}
IN_USE = {"code": "files_adapter_in_use", "params": {}}


class Watches:
    """Each watched process, running until the test ends it."""

    def __init__(self):
        self.ended = set()
        self.opened = []
        self.closed = []

    def __call__(self, pid):
        self.opened.append(pid)
        watches = self

        class Watch:
            def is_running(self):
                return pid not in watches.ended

            def close(self):
                watches.closed.append(pid)

        return Watch()


@pytest.fixture
def watches():
    return Watches()


@pytest.fixture
def shared(started, adapter, lines, watches):
    """A daemon two accounts reach through the pipe."""

    def start(argv, env):
        process = FakeTun2socks(argv, env)
        started.append(process)
        return process

    return FilesAdapterDaemon(
        tun2socks_path="C:\\nc\\bin\\tun2socks.exe",
        configure_adapter=adapter.configure,
        log=lines.append,
        start_process=start,
        probe=answered,
        watch_process=watches,
    )


def test_a_second_account_is_refused_and_the_first_keeps_its_adapter(
    shared, started, lines
):
    assert shared.handle(dict(UP), peer=ALICE) == {"is_up": True, "port": 40001}

    answer = shared.handle(dict(UP, port=40009, password="p9"), peer=BOB)

    assert answer == IN_USE
    assert len(started) == 1 and started[0].status is None
    assert "socks5://u1:p-Secret_1@127.0.0.1:40001" in started[0].argv  # scan: allow
    assert shared.status() == {"is_up": True, "port": 40001}
    assert "up from bob refused: the adapter is held by alice" in lines


def test_a_second_account_cannot_take_the_adapter_down(shared, started):
    shared.handle(dict(UP), peer=ALICE)

    assert shared.handle({"verb": "down"}, peer=BOB) == IN_USE
    assert started[0].status is None
    assert shared.handle({"verb": "status"}, peer=BOB) == {
        "is_up": True,
        "port": 40001,
    }


def test_a_later_client_of_the_same_account_is_served_in_its_place(
    shared, started, watches
):
    shared.handle(dict(UP), peer=ALICE)

    answer = shared.handle(dict(UP, port=40002, password="p2"), peer=ALICE_AGAIN)

    assert answer == {"is_up": True, "port": 40002}
    assert len(started) == 2
    assert watches.opened == [4100, 4200]
    assert watches.closed == [4100]


def test_the_holders_down_frees_the_adapter_for_another_account(shared, started):
    shared.handle(dict(UP), peer=ALICE)
    shared.handle({"verb": "down"}, peer=ALICE)

    answer = shared.handle(dict(UP, port=40009, password="p9"), peer=BOB)

    assert answer == {"is_up": True, "port": 40009}


def test_a_holder_that_ended_without_down_frees_the_adapter_within_a_tick(
    shared, started, watches, lines
):
    shared.handle(dict(UP), peer=ALICE)
    watches.ended.add(4100)

    shared.tick()

    assert started[0].status == -15
    assert shared.status() == {"is_up": False, "port": 0}
    assert "the client of alice that held the adapter has ended" in lines
    assert watches.closed == [4100]
    assert shared.handle(dict(UP, port=40009, password="p9"), peer=BOB) == {
        "is_up": True,
        "port": 40009,
    }


def test_a_request_whose_asker_the_pipe_cannot_tell_is_refused_while_held(shared):
    shared.handle(dict(UP), peer=ALICE)

    assert shared.handle(dict(UP, port=40009, password="p9"), peer=None) == IN_USE
    assert shared.handle({"verb": "down"}, peer=None) == IN_USE


def test_a_holder_that_cannot_be_watched_still_holds(started, adapter, lines):
    def refuse(pid):
        raise OSError("access denied")

    daemon = FilesAdapterDaemon(
        tun2socks_path="t.exe",
        configure_adapter=adapter.configure,
        log=lines.append,
        start_process=FakeTun2socks,
        probe=answered,
        watch_process=refuse,
    )
    daemon.handle(dict(UP), peer=ALICE)

    assert daemon.handle(dict(UP, port=40009), peer=BOB) == IN_USE
    assert "the holding client cannot be watched: access denied" in lines
