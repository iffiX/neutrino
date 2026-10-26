"""The transport child: where it listens, where its program is, its start
and its stop."""

import os
import socket
import stat
import sys

import pytest

from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform
from neutrino_agent.transport import process as process_module
from neutrino_agent.transport.process import (
    TransportProcess,
    listen_path,
    program_path,
)

# A transport that reads its secret, listens, says so on stderr, and exits
# once its standard input ends.
FAKE_PROGRAM = """#!{python}
import socket, sys, threading
role, option, listen = sys.argv[1:4]
secret = sys.stdin.readline().strip()
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(listen)
server.listen(4)
def accept():
    while True:
        connection, _ = server.accept()
        connection.close()
threading.Thread(target=accept, daemon=True).start()
sys.stderr.write("listening as %s with a secret of %d\\n" % (role, len(secret)))
sys.stderr.flush()
sys.stdin.read()
"""


def test_the_service_and_a_one_shot_listen_where_each_system_says():
    pid = os.getpid()

    assert listen_path("linux") == "/run/neutrino/agent/transport.sock"
    assert listen_path("darwin") == "/var/run/neutrino/agent/transport.sock"
    assert listen_path("windows") == "\\\\.\\pipe\\neutrino_agent_transport"
    assert listen_path("linux", is_one_shot=True) == (
        f"/run/neutrino/agent/transport_{pid}.sock"
    )
    assert listen_path("windows", is_one_shot=True) == (
        f"\\\\.\\pipe\\neutrino_agent_transport_{pid}"
    )


def test_the_program_is_in_the_agents_bin_unless_the_variable_names_one(
    monkeypatch,
):
    monkeypatch.delenv("NEUTRINO_TRANSPORT_BIN", raising=False)

    assert program_path(LinuxPlatform()) == "/opt/neutrino/agent/bin/neutrino_transport"
    assert program_path(DarwinPlatform.__new__(DarwinPlatform)) == (
        "/Library/Application Support/Neutrino/agent/app/bin/neutrino_transport"
    )
    assert program_path(WindowsPlatform.__new__(WindowsPlatform)).endswith(
        "Neutrino\\agent\\bin\\neutrino_transport.exe"
    )
    monkeypatch.setenv("NEUTRINO_TRANSPORT_BIN", "/tmp/own_transport")
    assert program_path(LinuxPlatform()) == "/tmp/own_transport"


@pytest.fixture
def program(tmp_path):
    path = tmp_path / "neutrino_transport"
    path.write_text(FAKE_PROGRAM.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@pytest.fixture
def short_listen(tmp_path_factory):
    directory = tmp_path_factory.mktemp("t", numbered=True)
    path = os.path.join("/tmp", f"nt{os.getpid()}{directory.name}.d", "t.sock")
    yield path
    for leftover in (path, os.path.dirname(path)):
        try:
            os.unlink(leftover) if leftover == path else os.rmdir(leftover)
        except OSError:
            pass


def test_a_start_writes_the_secret_waits_for_the_listener_and_relays_its_log(
    program, short_listen
):
    lines: list = []
    transport = TransportProcess(program=program, listen=short_listen, log=lines.append)

    transport.start()
    try:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.connect(short_listen)
        connection.close()
        assert transport.is_running()
        assert len(transport.secret) == 64
        assert stat.S_IMODE(os.stat(os.path.dirname(short_listen)).st_mode) == 0o700
    finally:
        transport.stop()

    assert not transport.is_running()
    assert "transport: listening as agent with a secret of 64" in lines


def test_a_program_that_exits_at_its_start_is_an_error(tmp_path, short_listen):
    path = tmp_path / "neutrino_transport"
    path.write_text(f"#!{sys.executable}\nraise SystemExit(3)\n")
    path.chmod(0o755)
    transport = TransportProcess(program=str(path), listen=short_listen, log=print)

    with pytest.raises(OSError, match="exited with 3"):
        transport.start()


def test_a_missing_program_is_an_error(short_listen):
    transport = TransportProcess(
        program="/nonexistent/neutrino_transport", listen=short_listen, log=print
    )

    with pytest.raises(OSError):
        transport.start()


def test_a_stale_socket_is_taken_away_before_the_start(program, short_listen):
    os.makedirs(os.path.dirname(short_listen), exist_ok=True)
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(short_listen)
    stale.close()
    transport = TransportProcess(program=program, listen=short_listen, log=print)

    transport.start()
    transport.stop()


def test_a_start_that_never_answers_is_an_error(monkeypatch, tmp_path, short_listen):
    path = tmp_path / "neutrino_transport"
    path.write_text(f"#!{sys.executable}\nimport sys\nsys.stdin.read()\n")
    path.chmod(0o755)
    monkeypatch.setattr(process_module, "TRANSPORT_START_TIMEOUT_S", 0.3)
    transport = TransportProcess(program=str(path), listen=short_listen, log=print)

    with pytest.raises(OSError, match="did not answer"):
        transport.start()
    assert not transport.is_running()
