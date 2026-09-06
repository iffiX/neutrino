"""What a privileged SSH command sends, and over which channel.

The sudo password and the enrollment link land in the device's process table
if they travel in the command string, so what these pin is that both travel
over stdin: the command asyncssh is handed never contains either, and the
stdin payload carries the password line first, then whatever the command
itself reads. The install half pins the package flow: the family the device's
own tools pick, and a failure stopping before the join.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.devices.constants import SSH_UNSUPPORTED_OS_STATUS
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator, SshCredentials

SUDO_PASSWORD = "a-sudo-password"  # scan: allow
LINK = "neutrino://enroll/eyJmYWtlIjogdHJ1ZX0"
# Any secret-shaped line a wrapped command reads from its own stdin.
TOKEN = "a-secret-line"  # scan: allow


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
    """Answers ``uname -s``, ``uname -m`` and ``command -v``, and records
    everything."""

    def __init__(
        self,
        kernel: str = "Linux",
        tools: tuple = ("dpkg",),
        machine: str = "x86_64",
    ):
        self.kernel = kernel
        self.tools = tools
        self.machine = machine
        self.commands: list[str] = []
        self.uploads: list = []

    async def run(self, command, check=False, timeout=None, input=None):
        self.commands.append(command)
        stdout = ""
        exit_status = 0
        if "uname -s" in command:
            stdout = f"{self.kernel}\n"
        elif "uname -m" in command:
            stdout = f"{self.machine}\n"
        elif command.startswith("command -v "):
            tool = command.split()[-1]
            exit_status = 0 if tool in self.tools else 1
        return SimpleNamespace(stdout=stdout, stderr="", exit_status=exit_status)

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


def stub_probe(op: DeviceSshOperator, *, is_passwordless: bool) -> list:
    """Answer ``sudo -n true`` without a network, recording every run_once."""
    calls: list = []

    async def run_once(command, *, timeout_s=20, input_text=None):
        calls.append({"command": command, "input_text": input_text})
        if command == "sudo -n true":
            return (0 if is_passwordless else 1), ""
        return 0, ""

    op.run_once = run_once
    return calls


def plan(op: DeviceSshOperator, command: str, input_text=None):
    return asyncio.run(op._sudo_plan(command, input_text))


def test_root_needs_no_probe_and_no_wrap():
    op = operator(username="root")
    calls = stub_probe(op, is_passwordless=False)

    assert plan(op, "cat", f"{TOKEN}\n") == (("cat", f"{TOKEN}\n"), "")
    assert calls == []


def test_a_passwordless_account_never_receives_the_stored_password():
    """The probe asks sudo itself, so a password the account does not need
    never leaves the hub — and never lies in wait on anyone's stdin."""
    op = operator(sudo_password=SUDO_PASSWORD)
    stub_probe(op, is_passwordless=True)

    (command, payload), refusal = plan(op, "cat", f"{TOKEN}\n")

    assert refusal == ""
    assert command == "sudo -n bash -lc cat"
    assert payload == f"{TOKEN}\n"
    assert SUDO_PASSWORD not in (payload or "")


def test_a_prompting_account_gets_exactly_one_password_line():
    op = operator(sudo_password=SUDO_PASSWORD)
    stub_probe(op, is_passwordless=False)

    (command, payload), refusal = plan(op, "cat", f"{TOKEN}\n")

    assert refusal == ""
    assert command == "sudo -S -p '' -k bash -lc cat"
    assert SUDO_PASSWORD not in command
    assert TOKEN not in command
    assert payload == f"{SUDO_PASSWORD}\n{TOKEN}\n"


def test_a_prompting_account_with_no_stored_password_is_refused():
    op = operator()
    stub_probe(op, is_passwordless=False)

    planned, refusal = plan(op, "whoami")

    assert planned is None
    assert "none is stored" in refusal


def test_the_probe_runs_once_per_operator():
    op = operator(sudo_password=SUDO_PASSWORD)
    calls = stub_probe(op, is_passwordless=False)

    plan(op, "whoami")
    plan(op, "cat")

    assert [c["command"] for c in calls].count("sudo -n true") == 1


def test_run_privileged_once_probes_then_feeds_the_composed_stdin():
    op = operator(sudo_password=SUDO_PASSWORD)
    calls = stub_probe(op, is_passwordless=False)

    asyncio.run(op.run_privileged_once("systemctl restart x"))

    assert calls[0]["command"] == "sudo -n true"
    assert SUDO_PASSWORD not in calls[1]["command"]
    assert calls[1]["input_text"] == f"{SUDO_PASSWORD}\n"


def test_run_privileged_stream_feeds_the_composed_stdin():
    op = operator(sudo_password=SUDO_PASSWORD)
    op._is_sudo_passwordless = False
    captured = capture_run_stream(op)

    async def drain():
        async for _ in op.run_privileged_stream("systemctl poweroff"):
            pass

    asyncio.run(drain())

    assert SUDO_PASSWORD not in captured["command"]
    assert captured["input_text"] == f"{SUDO_PASSWORD}\n"


def test_a_refused_stream_reports_and_runs_nothing():
    op = operator()
    op._is_sudo_passwordless = False
    captured = capture_run_stream(op)

    async def collect():
        return [chunk async for chunk in op.run_privileged_stream("whoami")]

    lines = asyncio.run(collect())

    assert any("none is stored" in line for line in lines)
    assert lines[-1] == "\n[exit 1]\n"
    assert captured == {}


@pytest.fixture
def packages(tmp_path) -> dict:
    """One package per family and machine, the way the hub carries them."""
    built = {}
    for family, names in (
        (
            "deb",
            {
                "amd64": "neutrino-agent_0.1.0_amd64.deb",
                "arm64": "neutrino-agent_0.1.0_arm64.deb",
            },
        ),
        (
            "rpm",
            {
                "amd64": "neutrino-agent-0.1.0-1.x86_64.rpm",
                "arm64": "neutrino-agent-0.1.0-1.aarch64.rpm",
            },
        ),
    ):
        for architecture, name in names.items():
            path = tmp_path / name
            path.write_bytes(family.encode())
            built.setdefault(family, {})[architecture] = path
    return built


async def install_lines(op: DeviceSshOperator, packages: dict) -> list[str]:
    lines = []
    async for chunk in op.install_client(packages=packages, enrollment_link=LINK):
        lines.append(chunk)
    return lines


def capture_privileged_once(op: DeviceSshOperator, codes=(0, 0)) -> list:
    calls: list = []
    remaining = list(codes)

    async def run_privileged_once(command, *, timeout_s=30, input_text=None):
        calls.append({"command": command, "input_text": input_text})
        return remaining.pop(0), "[remote output]"

    op.run_privileged_once = run_privileged_once
    return calls


def test_install_refuses_a_device_that_is_not_linux(packages):
    op = operator(sudo_password=SUDO_PASSWORD)
    connection = FakeConnection(kernel="Darwin")
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    lines = asyncio.run(install_lines(op, packages))

    assert any("unsupported OS Darwin" in line for line in lines)
    assert lines[-1] == f"\n[exit {SSH_UNSUPPORTED_OS_STATUS}]\n"
    assert connection.uploads == []
    assert calls == []


def test_install_picks_deb_and_joins_with_the_link_on_argv(packages):
    """The link was shaped for a command line; stdin stays sudo's alone, so
    an account whose sudo never prompts cannot shift what connect reads."""
    op = operator(sudo_password=SUDO_PASSWORD)
    connection = FakeConnection(tools=("dpkg",))
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    lines = asyncio.run(install_lines(op, packages))

    assert connection.uploads[0][1].endswith(".deb")
    assert "apt-get install" in calls[0]["command"]
    assert calls[1]["command"] == f"nagent connect --yes {LINK}"
    assert calls[1]["input_text"] is None
    assert lines[-1] == "\n[exit 0]\n"


def test_install_picks_rpm_where_dpkg_is_absent(packages):
    op = operator()
    connection = FakeConnection(tools=("rpm",))
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    asyncio.run(install_lines(op, packages))

    assert connection.uploads[0][1].endswith(".rpm")
    assert "dnf install" in calls[0]["command"]


def test_install_uploads_the_package_for_the_machine_that_answers(packages):
    """The package carries an interpreter, so the device's machine picks the
    file as much as its package manager does."""
    op = operator()
    connection = FakeConnection(tools=("dpkg",), machine="aarch64")
    op._connect = fake_connect(connection)
    capture_privileged_once(op)

    asyncio.run(install_lines(op, packages))

    assert connection.uploads[0][1].endswith("_arm64.deb")


def test_install_stops_where_the_hub_has_nothing_for_the_machine(packages):
    """A machine the hub carries no build for is refused before anything is
    uploaded, and the refusal names what answered."""
    op = operator()
    connection = FakeConnection(tools=("dpkg",), machine="riscv64")
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    lines = asyncio.run(install_lines(op, packages))

    assert any("riscv64" in line for line in lines)
    assert any("enrollment link instead" in line for line in lines)
    assert connection.uploads == []
    assert calls == []


def test_install_stops_where_no_package_manager_answers(packages):
    op = operator()
    connection = FakeConnection(tools=())
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    lines = asyncio.run(install_lines(op, packages))

    assert any("enrollment link instead" in line for line in lines)
    assert connection.uploads == []
    assert calls == []


def test_a_failed_install_never_reaches_the_join(packages):
    op = operator()
    op._connect = fake_connect(FakeConnection(tools=("dpkg",)))
    calls = capture_privileged_once(op, codes=(1,))

    lines = asyncio.run(install_lines(op, packages))

    assert len(calls) == 1
    assert lines[-1] == "\n[exit 1]\n"
