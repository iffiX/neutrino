"""What a privileged SSH command sends, and over which channel.

The sudo password and the agent's heartbeat token land in the device's process
table if they travel in the command string, so what these pin is that both
travel over stdin: the command asyncssh is handed never contains either, and
the stdin payload carries the password line first, then whatever the command
itself reads.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.devices.constants import SSH_UNSUPPORTED_OS_STATUS
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator, SshCredentials

SUDO_PASSWORD = "a-sudo-password"  # scan: allow
TOKEN = "a-heartbeat-token"
GATEWAY_URL = "http://192.168.100.1"


class FakeSftp:
    """Records uploads instead of transferring them."""

    def __init__(self, uploads: list):
        self._uploads = uploads

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def put(self, local_path, remote_path):
        self._uploads.append((local_path, remote_path))


class FakeConnection:
    """Answers ``uname -s`` with one kernel name and records everything."""

    def __init__(self, kernel: str = "Linux"):
        self.kernel = kernel
        self.commands: list[str] = []
        self.uploads: list = []

    async def run(self, command, check=False, timeout=None, input=None):
        self.commands.append(command)
        stdout = f"{self.kernel}\n" if "uname -s" in command else ""
        return SimpleNamespace(stdout=stdout, stderr="", exit_status=0)

    def start_sftp_client(self):
        return FakeSftp(self.uploads)


def operator(
    *, username: str = "iffi", sudo_password: str | None = None
) -> DeviceSshOperator:
    credentials = SshCredentials(
        host="192.168.100.2",
        port=22,
        username=username,
        sudo_password=sudo_password,
    )
    return DeviceSshOperator(credentials=credentials)


def fake_connect(connection: FakeConnection):
    @asynccontextmanager
    async def connect():
        yield connection

    return connect


def capture_run_stream(op: DeviceSshOperator) -> dict:
    captured: dict = {}

    async def run_stream(command, *, input_text=None):
        captured["command"] = command
        captured["input_text"] = input_text
        yield "[installer output]\n"

    op.run_stream = run_stream
    return captured


def test_root_runs_the_command_bare():
    assert operator(username="root")._sudo_wrap("whoami") == ("whoami", None)


def test_root_passes_the_commands_stdin_through():
    command, payload = operator(username="root")._sudo_wrap("cat", f"{TOKEN}\n")
    assert command == "cat"
    assert payload == f"{TOKEN}\n"


def test_passwordless_sudo_sends_nothing_on_stdin():
    command, payload = operator()._sudo_wrap("whoami")
    assert command == "sudo -n bash -lc whoami"
    assert payload is None


def test_passwordless_sudo_passes_the_commands_stdin_through():
    command, payload = operator()._sudo_wrap("cat", f"{TOKEN}\n")
    assert command == "sudo -n bash -lc cat"
    assert payload == f"{TOKEN}\n"


def test_the_sudo_password_travels_on_stdin_not_in_the_command():
    command, payload = operator(sudo_password=SUDO_PASSWORD)._sudo_wrap("whoami")
    assert command == "sudo -S -p '' bash -lc whoami"
    assert SUDO_PASSWORD not in command
    assert payload == f"{SUDO_PASSWORD}\n"


def test_the_commands_own_stdin_follows_the_password_line():
    command, payload = operator(sudo_password=SUDO_PASSWORD)._sudo_wrap(
        "cat", f"{TOKEN}\n"
    )
    assert SUDO_PASSWORD not in command
    assert TOKEN not in command
    assert payload == f"{SUDO_PASSWORD}\n{TOKEN}\n"


def test_run_privileged_once_feeds_the_composed_stdin():
    op = operator(sudo_password=SUDO_PASSWORD)
    captured: dict = {}

    async def run_once(command, *, timeout_s=20, input_text=None):
        captured["command"] = command
        captured["input_text"] = input_text
        return 0, ""

    op.run_once = run_once

    asyncio.run(op.run_privileged_once("systemctl restart x"))

    assert SUDO_PASSWORD not in captured["command"]
    assert captured["input_text"] == f"{SUDO_PASSWORD}\n"


def test_run_privileged_stream_feeds_the_composed_stdin():
    op = operator(sudo_password=SUDO_PASSWORD)
    captured = capture_run_stream(op)

    async def drain():
        async for _ in op.run_privileged_stream("systemctl poweroff"):
            pass

    asyncio.run(drain())

    assert SUDO_PASSWORD not in captured["command"]
    assert captured["input_text"] == f"{SUDO_PASSWORD}\n"


@pytest.fixture
def package(tmp_path):
    path = tmp_path / "neutrino_agent-latest.tar.gz"
    path.write_bytes(b"tarball")
    return path


async def install_lines(op: DeviceSshOperator, package) -> list[str]:
    lines = []
    async for chunk in op.install_client(
        package_path=package, gateway_url=GATEWAY_URL, token=TOKEN
    ):
        lines.append(chunk)
    return lines


def test_install_refuses_a_device_that_is_not_linux(package):
    op = operator(sudo_password=SUDO_PASSWORD)
    connection = FakeConnection(kernel="Darwin")
    op._connect = fake_connect(connection)
    captured = capture_run_stream(op)

    lines = asyncio.run(install_lines(op, package))

    assert any("unsupported OS Darwin" in line for line in lines)
    assert lines[-1] == f"\n[exit {SSH_UNSUPPORTED_OS_STATUS}]\n"
    assert connection.uploads == []
    assert captured == {}


def test_install_sends_the_token_and_password_over_stdin(package):
    op = operator(sudo_password=SUDO_PASSWORD)
    op._connect = fake_connect(FakeConnection())
    captured = capture_run_stream(op)

    asyncio.run(install_lines(op, package))

    assert "--token-stdin" in captured["command"]
    assert GATEWAY_URL in captured["command"]
    assert TOKEN not in captured["command"]
    assert SUDO_PASSWORD not in captured["command"]
    assert captured["input_text"] == f"{SUDO_PASSWORD}\n{TOKEN}\n"


def test_install_without_a_sudo_password_sends_only_the_token(package):
    op = operator()
    op._connect = fake_connect(FakeConnection())
    captured = capture_run_stream(op)

    asyncio.run(install_lines(op, package))

    assert TOKEN not in captured["command"]
    assert captured["input_text"] == f"{TOKEN}\n"


def test_install_as_root_sends_only_the_token(package):
    op = operator(username="root")
    op._connect = fake_connect(FakeConnection())
    captured = capture_run_stream(op)

    asyncio.run(install_lines(op, package))

    assert "sudo" not in captured["command"]
    assert TOKEN not in captured["command"]
    assert captured["input_text"] == f"{TOKEN}\n"
