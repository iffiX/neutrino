"""What a privileged SSH command sends, and over which channel.

The sudo password and the enrollment link land in the device's process table
if they travel in the command string, so what these pin is that both travel
over stdin: the command asyncssh is handed never contains either, and the
stdin payload carries the password line first, then whatever the command
itself reads. The password is the call's own argument, typed for one
install and held by no credentials object. The install half pins the
package flow: the family the device's own tools pick, EPEL enabled before
the rpm on the RHEL family, and a failure stopping before the join.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import asyncssh
import pytest

from neutrino_hub.exceptions import AgentArtifactFetchError
from neutrino_hub.modules.devices.agent_package import AgentPackageCache
from neutrino_hub.modules.devices.constants import (
    SSH_UNREACHABLE_STATUS,
    SSH_UNSUPPORTED_OS_STATUS,
)
from neutrino_hub.modules.devices.ssh_ops import (
    HOST_KEY_CHANGED_MESSAGE,
    DeviceSshOperator,
    SshCredentials,
    epel_command,
    package_tools,
)
from neutrino_hub.web.task_stream import TaskStream, TaskStreamRegistry

SUDO_PASSWORD = "a-sudo-password"  # scan: allow
LINK = "neutrino://enroll/eyJmYWtlIjogdHJ1ZX0"
# Any secret-shaped line a wrapped command reads from its own stdin.
TOKEN = "a-secret-line"  # scan: allow


class FakeSftp:
    """Records directories made and uploads instead of transferring them."""

    def __init__(self, uploads: list, dirs: list | None = None):
        self._uploads = uploads
        self._dirs = [] if dirs is None else dirs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def mkdir(self, path):
        self._dirs.append(path)

    async def put(self, local_path, remote_path):
        self._uploads.append((local_path, remote_path))


class RefusingSftp(FakeSftp):
    """Refuses every upload the way sftp-server refuses a file it cannot write."""

    async def put(self, local_path, remote_path):
        raise asyncssh.SFTPPermissionDenied("Permission denied")


class FakeConnection:
    """Answers ``uname -s``, ``uname -m``, ``command -v`` and the read of
    ``/etc/os-release``, and records everything."""

    def __init__(
        self,
        kernel: str = "Linux",
        tools: tuple = ("dpkg",),
        machine: str = "x86_64",
        os_release: str = "",
    ):
        self.kernel = kernel
        self.tools = tools
        self.machine = machine
        self.os_release = os_release
        self.commands: list[str] = []
        self.uploads: list = []
        self.dirs: list[str] = []

    async def run(self, command, check=False, timeout=None, input=None):
        self.commands.append(command)
        stdout = ""
        exit_status = 0
        if "uname -s" in command:
            stdout = f"{self.kernel}\n"
        elif "uname -m" in command:
            stdout = f"{self.machine}\n"
        elif command == "cat /etc/os-release":
            stdout = self.os_release
        elif command.startswith("command -v "):
            tool = command.split()[-1]
            exit_status = 0 if tool in self.tools else 1
        return SimpleNamespace(stdout=stdout, stderr="", exit_status=exit_status)

    def start_sftp_client(self):
        return FakeSftp(self.uploads, self.dirs)


def operator(*, username: str = "iffi") -> DeviceSshOperator:
    credentials = SshCredentials(host="192.168.100.2", port=22, username=username)
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


def plan(op: DeviceSshOperator, command: str, input_text=None, sudo_password=None):
    return asyncio.run(op._sudo_plan(command, input_text, sudo_password))


def test_root_needs_no_probe_and_no_wrap():
    op = operator(username="root")
    calls = stub_probe(op, is_passwordless=False)

    assert plan(op, "cat", f"{TOKEN}\n") == (("cat", f"{TOKEN}\n"), "")
    assert calls == []


def test_a_passwordless_account_never_receives_the_typed_password():
    """The probe asks sudo itself, so a password the account does not need
    never leaves the hub — and never lies in wait on anyone's stdin."""
    op = operator()
    stub_probe(op, is_passwordless=True)

    (command, payload), refusal = plan(op, "cat", f"{TOKEN}\n", SUDO_PASSWORD)

    assert refusal == ""
    assert command == "sudo -n bash -lc cat"
    assert payload == f"{TOKEN}\n"
    assert SUDO_PASSWORD not in (payload or "")


def test_a_prompting_account_gets_exactly_one_password_line():
    op = operator()
    stub_probe(op, is_passwordless=False)

    (command, payload), refusal = plan(op, "cat", f"{TOKEN}\n", SUDO_PASSWORD)

    assert refusal == ""
    assert command == "sudo -S -p '' -k bash -lc cat"
    assert SUDO_PASSWORD not in command
    assert TOKEN not in command
    assert payload == f"{SUDO_PASSWORD}\n{TOKEN}\n"


def test_a_prompting_account_with_no_password_given_is_refused():
    op = operator()
    stub_probe(op, is_passwordless=False)

    planned, refusal = plan(op, "whoami")

    assert planned is None
    assert "none was given" in refusal


def test_the_probe_runs_once_per_operator():
    op = operator()
    calls = stub_probe(op, is_passwordless=False)

    plan(op, "whoami", None, SUDO_PASSWORD)
    plan(op, "cat", None, SUDO_PASSWORD)

    assert [c["command"] for c in calls].count("sudo -n true") == 1


def test_run_privileged_once_probes_then_feeds_the_composed_stdin():
    op = operator()
    calls = stub_probe(op, is_passwordless=False)

    asyncio.run(
        op.run_privileged_once("systemctl restart x", sudo_password=SUDO_PASSWORD)
    )

    assert calls[0]["command"] == "sudo -n true"
    assert SUDO_PASSWORD not in calls[1]["command"]
    assert calls[1]["input_text"] == f"{SUDO_PASSWORD}\n"


def test_run_privileged_stream_feeds_the_composed_stdin():
    op = operator()
    op._is_sudo_passwordless = False
    captured = capture_run_stream(op)

    async def drain():
        async for _ in op.run_privileged_stream(
            "systemctl poweroff", sudo_password=SUDO_PASSWORD
        ):
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

    assert any("none was given" in line for line in lines)
    assert lines[-1] == "\n[exit 1]\n"
    assert captured == {}


@pytest.fixture
def packages(tmp_path) -> AgentPackageCache:
    """One package per family and machine, the way the hub carries them."""
    pinned = tmp_path / "packages"
    pinned.mkdir()
    for name in (
        "neutrino-agent_0.1.0_amd64.deb",
        "neutrino-agent_0.1.0_arm64.deb",
        "neutrino-agent-0.1.0-1.x86_64.rpm",
        "neutrino-agent-0.1.0-1.aarch64.rpm",
        "neutrino-agent-0.1.0-1-x86_64.pkg.tar.zst",
    ):
        (pinned / name).write_bytes(name.encode())
    return AgentPackageCache(
        root=tmp_path / "agent_cache",
        manifest_path=tmp_path / "agent_packages.json",
        pinned_dir=pinned,
    )


async def install_task(
    op: DeviceSshOperator, packages: AgentPackageCache, sudo_password=None
) -> TaskStream:
    """The install run as the panel starts it, a task, once it has finished."""
    stream = TaskStreamRegistry().start(
        label="install_client d1",
        source=op.install_client(
            packages=packages, enrollment_link=LINK, sudo_password=sudo_password
        ),
    )
    while not stream.is_finished:
        await asyncio.sleep(0)
    return stream


async def install_lines(
    op: DeviceSshOperator, packages: AgentPackageCache, sudo_password=None
) -> list[str]:
    return (await install_task(op, packages, sudo_password)).buffer


def capture_privileged_once(op: DeviceSshOperator, codes=(0, 0, 0)) -> list:
    calls: list = []
    remaining = list(codes)

    async def run_privileged_once(
        command, *, timeout_s=30, input_text=None, sudo_password=None
    ):
        calls.append(
            {
                "command": command,
                "input_text": input_text,
                "sudo_password": sudo_password,
            }
        )
        return remaining.pop(0), "[remote output]"

    op.run_privileged_once = run_privileged_once
    return calls


def test_install_refuses_a_device_that_is_not_linux(packages):
    op = operator()
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
    op = operator()
    connection = FakeConnection(tools=("dpkg",))
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    lines = asyncio.run(install_lines(op, packages, SUDO_PASSWORD))

    assert connection.uploads[0][1].endswith(".deb")
    assert "apt-get install" in calls[1]["command"]
    assert calls[2]["command"] == f"nagent join --yes {LINK}"
    assert calls[2]["input_text"] is None
    assert [call["sudo_password"] for call in calls] == [SUDO_PASSWORD] * 3
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
    calls = capture_privileged_once(op, codes=(0, 1))

    lines = asyncio.run(install_lines(op, packages))

    assert len(calls) == 2
    assert lines[-1] == "\n[exit 1]\n"


class UploadRefusingConnection(FakeConnection):
    """A device whose sftp-server refuses the package."""

    def start_sftp_client(self):
        return RefusingSftp(self.uploads, self.dirs)


class StaleTmpSftp(FakeSftp):
    """Refuses a write to ``/tmp/<package name>``, the way sftp-server refuses
    a file of that name another account owns."""

    async def put(self, local_path, remote_path):
        if remote_path == f"/tmp/{Path(local_path).name}":
            raise asyncssh.SFTPPermissionDenied("Permission denied")
        await super().put(local_path, remote_path)


class StaleTmpConnection(FakeConnection):
    """A device whose ``/tmp`` holds another account's file of the package's
    name."""

    def start_sftp_client(self):
        return StaleTmpSftp(self.uploads, self.dirs)


def not_linux(op, packages):
    connection = FakeConnection(kernel="Darwin")
    op._connect = fake_connect(connection)
    capture_privileged_once(op)
    return connection


def no_package_manager(op, packages):
    connection = FakeConnection(tools=())
    op._connect = fake_connect(connection)
    capture_privileged_once(op)
    return connection


def unproduced_package(op, packages):
    def package(*, family, architecture):
        raise AgentArtifactFetchError("artifact_unreachable", platform="linux/amd64")

    packages.package = package
    connection = FakeConnection(tools=("dpkg",))
    op._connect = fake_connect(connection)
    capture_privileged_once(op)
    return connection


def refused_login(op, packages):
    @asynccontextmanager
    async def connect():
        raise asyncssh.PermissionDenied(
            "Permission denied for user iffi on host 192.168.100.2"
        )
        yield

    op._connect = connect
    capture_privileged_once(op)


def changed_host_key(op, packages):
    @asynccontextmanager
    async def connect():
        raise asyncssh.HostKeyNotVerifiable(
            "Host key is not trusted for host 192.168.100.2"
        )
        yield

    op._connect = connect
    capture_privileged_once(op)


def refused_upload(op, packages):
    connection = UploadRefusingConnection(tools=("dpkg",))
    op._connect = fake_connect(connection)
    capture_privileged_once(op)
    return connection


def refused_epel(op, packages):
    connection = FakeConnection(tools=("rpm",), os_release=ROCKY)
    op._connect = fake_connect(connection)
    capture_privileged_once(op, codes=(1,))
    return connection


def failed_install(op, packages):
    connection = FakeConnection(tools=("dpkg",))
    op._connect = fake_connect(connection)
    capture_privileged_once(op, codes=(0, 100))
    return connection


def failed_join(op, packages):
    connection = FakeConnection(tools=("dpkg",))
    op._connect = fake_connect(connection)
    capture_privileged_once(op, codes=(0, 0, 3))
    return connection


def crashed_step(op, packages):
    connection = FakeConnection(tools=("dpkg",))
    op._connect = fake_connect(connection)

    async def run_privileged_once(command, **_options):
        raise RuntimeError("the step crashed")

    op.run_privileged_once = run_privileged_once
    return connection


def joined(op, packages):
    connection = FakeConnection(tools=("dpkg",))
    op._connect = fake_connect(connection)
    capture_privileged_once(op)
    return connection


@pytest.mark.parametrize(
    "prepare, status, words",
    [
        (not_linux, SSH_UNSUPPORTED_OS_STATUS, "[unsupported OS Darwin"),
        (no_package_manager, SSH_UNSUPPORTED_OS_STATUS, "enrollment link instead"),
        (unproduced_package, SSH_UNSUPPORTED_OS_STATUS, "could not be produced"),
        (refused_login, SSH_UNREACHABLE_STATUS, "[connection failed: Permission"),
        (
            changed_host_key,
            SSH_UNREACHABLE_STATUS,
            f"[connection failed: {HOST_KEY_CHANGED_MESSAGE}]",
        ),
        (refused_upload, 1, "[upload failed: Permission denied]"),
        (refused_epel, 1, "[EPEL could not be enabled"),
        (failed_install, 100, "[installing the deb package]"),
        (failed_join, 3, "[joining this hub]"),
        (joined, 0, "[joining this hub]"),
    ],
    ids=[
        "not_linux",
        "no_package_manager",
        "unproduced_package",
        "refused_login",
        "changed_host_key",
        "refused_upload",
        "refused_epel",
        "failed_install",
        "failed_join",
        "joined",
    ],
)
def test_every_end_of_the_install_is_its_exit_line_and_its_task_status(
    packages, prepare, status, words
):
    """A refused upload ended with no exit line and its task read "exit 0"."""
    op = operator()
    prepare(op, packages)

    stream = asyncio.run(install_task(op, packages))

    assert any(words in line for line in stream.buffer)
    assert stream.buffer[-1] == f"\n[exit {status}]\n"
    assert stream.exit_code == status


def test_a_changed_host_key_is_worded_by_the_hub_not_by_asyncssh():
    """A changed host key showed asyncssh's "Host key is not trusted"."""
    op = operator()
    changed_host_key(op, None)

    code, output = asyncio.run(op.run_once("uname -s"))

    assert (code, output) == (SSH_UNREACHABLE_STATUS, HOST_KEY_CHANGED_MESSAGE)


def test_each_install_uploads_into_a_directory_made_for_it(packages):
    """The package went to ``/tmp/<package name>`` on every install."""
    connections = []
    for _ in range(2):
        op = operator()
        connections.append(FakeConnection(tools=("dpkg",)))
        op._connect = fake_connect(connections[-1])
        calls = capture_privileged_once(op)
        asyncio.run(install_task(op, packages))

        (made,) = connections[-1].dirs
        ((local_path, remote_path),) = connections[-1].uploads
        assert made.startswith("/tmp/neutrino_agent.")
        assert remote_path == f"{made}/{Path(local_path).name}"
        assert remote_path in calls[1]["command"]
    assert connections[0].dirs != connections[1].dirs


def test_a_file_another_account_left_in_tmp_does_not_stop_the_install(packages):
    """A file of the package's name in /tmp ended the install with sftp's
    "Permission denied"."""
    op = operator()
    op._connect = fake_connect(StaleTmpConnection(tools=("dpkg",)))
    capture_privileged_once(op)

    stream = asyncio.run(install_task(op, packages))

    assert stream.buffer[-1] == "\n[exit 0]\n"
    assert stream.exit_code == 0


@pytest.mark.parametrize(
    "prepare",
    [refused_upload, refused_epel, failed_install, failed_join, crashed_step, joined],
    ids=[
        "refused_upload",
        "refused_epel",
        "failed_install",
        "failed_join",
        "crashed_step",
        "joined",
    ],
)
def test_the_upload_directory_is_removed_whatever_the_end(packages, prepare):
    """The package stayed on the device after every install."""
    op = operator()
    connection = prepare(op, packages)

    asyncio.run(install_task(op, packages))

    (made,) = connection.dirs
    assert connection.commands[-1] == f"LANG=C.UTF-8 LC_ALL=C.UTF-8 rm -rf -- {made}"


@pytest.mark.parametrize(
    "prepare",
    [not_linux, no_package_manager, unproduced_package],
    ids=["not_linux", "no_package_manager", "unproduced_package"],
)
def test_an_install_that_made_no_directory_removes_none(packages, prepare):
    op = operator()
    connection = prepare(op, packages)

    asyncio.run(install_task(op, packages))

    assert connection.dirs == []
    assert not any("rm -rf" in command for command in connection.commands)


def test_the_deb_install_refreshes_the_package_lists_before_it_installs(packages):
    """The agent deb depends on packages apt resolves from the device's own
    lists; an image whose lists are empty answers "not installable" until
    they are fetched."""
    op = operator()
    op._connect = fake_connect(FakeConnection(tools=("dpkg",)))
    calls = capture_privileged_once(op)

    asyncio.run(install_lines(op, packages))

    assert calls[0]["command"].endswith("apt-get update")
    assert "apt-get install" in calls[1]["command"]
    assert calls[2]["command"].startswith("nagent join")


def test_a_refresh_the_device_refuses_is_said_and_the_install_still_runs(packages):
    """A device with lists that are stale rather than empty can still carry
    every dependency, so the refusal is reported and the install decides."""
    op = operator()
    op._connect = fake_connect(FakeConnection(tools=("dpkg",)))
    calls = capture_privileged_once(op, codes=(1, 0, 0))

    lines = asyncio.run(install_lines(op, packages))

    assert any("could not be refreshed" in line for line in lines)
    assert "apt-get install" in calls[1]["command"]
    assert lines[-1] == "\n[exit 0]\n"


def test_the_rpm_install_asks_for_no_refresh(packages):
    """dnf fetches the metadata it needs itself; only apt has to be told."""
    op = operator()
    op._connect = fake_connect(FakeConnection(tools=("rpm",)))
    calls = capture_privileged_once(op)

    asyncio.run(install_lines(op, packages))

    assert len(calls) == 2
    assert "dnf" in calls[0]["command"]


ROCKY = (
    'NAME="Rocky Linux"\nID="rocky"\nID_LIKE="rhel centos fedora"\nVERSION_ID="9.4"\n'
)
ALMA = 'ID="almalinux"\nID_LIKE="rhel centos fedora"\nVERSION_ID="9.5"\n'
RHEL = 'ID="rhel"\nID_LIKE="fedora"\nVERSION_ID="9.4"\n'
FEDORA = "ID=fedora\nVERSION_ID=41\n"
CRB_EPEL = "dnf config-manager --set-enabled crb && dnf install -y epel-release"


@pytest.mark.parametrize(
    "os_release, machine, command",
    [
        (ROCKY, "x86_64", CRB_EPEL),
        (ALMA, "aarch64", CRB_EPEL),
        (
            RHEL,
            "x86_64",
            "subscription-manager repos --enable "
            "codeready-builder-for-rhel-9-x86_64-rpms && dnf install -y "
            "https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm",
        ),
        (
            RHEL,
            "aarch64",
            "subscription-manager repos --enable "
            "codeready-builder-for-rhel-9-aarch64-rpms && dnf install -y "
            "https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm",
        ),
        (FEDORA, "x86_64", ""),
        ('ID=debian\nVERSION_ID="12"\n', "x86_64", ""),
        ("", "x86_64", ""),
    ],
)
def test_epel_is_enabled_the_way_epel_says_on_each_system(os_release, machine, command):
    assert epel_command(os_release, machine) == command


@pytest.mark.parametrize("os_release", [ROCKY, ALMA, RHEL])
def test_the_rpm_install_enables_epel_first_on_the_rhel_family(packages, os_release):
    """The agent's rpm names xdotool, which the RHEL family has in EPEL."""
    op = operator()
    connection = FakeConnection(tools=("rpm",), os_release=os_release)
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    lines = asyncio.run(install_lines(op, packages, SUDO_PASSWORD))

    assert "cat /etc/os-release" in connection.commands
    assert calls[0]["command"] == epel_command(os_release, "x86_64")
    assert "dnf reinstall" in calls[1]["command"]
    assert calls[2]["command"] == f"nagent join --yes {LINK}"
    assert [call["sudo_password"] for call in calls] == [SUDO_PASSWORD] * 3
    assert any("enabling EPEL" in line for line in lines)
    assert lines[-1] == "\n[exit 0]\n"


ARCH = 'NAME="Arch Linux"\nID=arch\n'
MANJARO = 'NAME="Manjaro Linux"\nID=manjaro\nID_LIKE=arch\n'
ENDEAVOUR = 'NAME="EndeavourOS"\nID="endeavouros"\nID_LIKE="arch"\n'


@pytest.mark.parametrize("os_release", [ARCH, MANJARO, ENDEAVOUR])
def test_the_arch_install_refreshes_the_lists_and_installs_the_file(
    packages, os_release
):
    """pacman -S takes names alone, and an image's package lists are empty."""
    op = operator()
    connection = FakeConnection(tools=("pacman",), os_release=os_release)
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    lines = asyncio.run(install_lines(op, packages, SUDO_PASSWORD))

    assert calls[0]["command"] == "pacman -Sy --noconfirm"
    assert calls[1]["command"].startswith("pacman -U --noconfirm /tmp/neutrino_agent.")
    assert calls[1]["command"].endswith(".pkg.tar.zst")
    assert calls[2]["command"] == f"nagent join --yes {LINK}"
    assert lines[-1] == "\n[exit 0]\n"


def test_an_arch_machine_holding_dpkg_and_rpm_installs_the_arch_package(packages):
    """The Arch repositories hold both tools."""
    op = operator()
    connection = FakeConnection(tools=("dpkg", "rpm", "pacman"), os_release=ARCH)
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    asyncio.run(install_lines(op, packages, SUDO_PASSWORD))

    assert any(call["command"].startswith("pacman -U") for call in calls)
    assert connection.uploads[0][1].endswith(".pkg.tar.zst")


def test_a_debian_machine_holding_pacman_installs_the_deb(packages):
    op = operator()
    connection = FakeConnection(
        tools=("dpkg", "pacman"), os_release='ID=debian\nVERSION_ID="12"\n'
    )
    op._connect = fake_connect(connection)
    calls = capture_privileged_once(op)

    asyncio.run(install_lines(op, packages, SUDO_PASSWORD))

    assert not any("pacman" in call["command"] for call in calls)


@pytest.mark.parametrize(
    "os_release, first",
    [(ARCH, "arch"), (MANJARO, "arch"), (ROCKY, "deb"), ("", "deb")],
)
def test_a_device_tries_its_own_system_s_package_first(os_release, first):
    assert package_tools(os_release)[0][0] == first


def test_epel_that_cannot_be_enabled_ends_the_task_before_the_package(packages):
    op = operator()
    op._connect = fake_connect(FakeConnection(tools=("rpm",), os_release=ROCKY))
    calls = capture_privileged_once(op, codes=(1,))

    lines = asyncio.run(install_lines(op, packages))

    assert len(calls) == 1
    assert any("EPEL could not be enabled" in line for line in lines)
    assert lines[-1] == "\n[exit 1]\n"


@pytest.mark.parametrize(
    "tools, os_release",
    [(("rpm",), FEDORA), (("dpkg",), 'ID=debian\nVERSION_ID="12"\n')],
)
def test_fedora_and_a_deb_take_no_epel_step(packages, tools, os_release):
    op = operator()
    op._connect = fake_connect(FakeConnection(tools=tools, os_release=os_release))
    calls = capture_privileged_once(op)

    asyncio.run(install_lines(op, packages))

    assert not any(
        word in call["command"]
        for call in calls
        for word in ("epel", "crb", "subscription-manager")
    )
