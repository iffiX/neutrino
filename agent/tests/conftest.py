"""Suite-wide isolation and the shared fakes, defined once.

The autouse redirect keeps every store off the real machine: the binding
file, the machine's own state store, the credentials directory, the
configured marks and the package directory all land in ``tmp_path``, and
the AI gateway forward an agent builds listens on a port the system picks.
A guard on every process a test starts refuses by name the firewalls, the
network tools, the service and package managers, Podman and every other
program that reads or changes the machine or asks for authorization to, an
agent a test builds on this system's own platform observes none of its
modules, and each test has a hub clock of its own. The fakes here are the ones more than one directory drives:
the control channel's platform and agent, the injected clock, the link
builder and the log sink.
"""

import base64
import functools
import json
import os
import shutil
import subprocess
import tempfile
import zlib

import pytest

import neutrino_agent.core.engine as engine_module
import neutrino_agent.core.enrollment as enrollment
import neutrino_agent.core.loop as loop_module
import neutrino_agent.core.store as store_module
import neutrino_agent.modules.remote_desktop.darwin_applier as darwin_applier_module
import neutrino_agent.modules.remote_desktop.linux_applier as linux_applier_module
import neutrino_agent.modules.remote_desktop.windows_applier as windows_applier_module
import neutrino_agent.modules.shared.hub_clock as hub_clock_module
from neutrino_agent.modules.shared.hub_clock import HubClock
from neutrino_agent.modules.shared.subprocess_run import CommandResult
import neutrino_agent.platforms.base as platforms_base_module
import neutrino_agent.platforms.darwin as darwin_module
import neutrino_agent.platforms.detect as detect_module
import neutrino_agent.platforms.linux as linux_module
import neutrino_agent.platforms.powershell_host as powershell_host_module
import neutrino_agent.platforms.windows as windows_module
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.powershell_host import (
    WINDOWS_POWERSHELL_HOST_CALL_TIMEOUT_S,
    WINDOWS_POWERSHELL_HOST_OPS,
    WindowsPowerShellHost,
)
from neutrino_agent.platforms.windows import WindowsPlatform
from neutrino_agent.platforms.windows_processes import WindowsProcessEntry
from neutrino_agent.streams.ai_forward import AiGatewayForward

# The programs no test may start on the real machine: the firewalls the
# relays' rules go to, the tools that read or change the machine's network,
# the service managers, package managers, container engines and account
# tools that change it or ask for authorization to, and the system services
# a test fakes. A program of one of these names that a test placed under the
# temporary directory, a fake on its own PATH, runs.
REFUSED_PROGRAMS = frozenset(
    {
        "ufw",
        "firewall-cmd",
        "firewall-offline-cmd",
        "nft",
        "iptables",
        "ip6tables",
        "netsh",
        "ip",
        "systemctl",
        "systemd-run",
        "journalctl",
        "loginctl",
        "podman",
        "sudo",
        "pkexec",
        "runuser",
        "su",
        "apt",
        "apt-get",
        "dpkg",
        "dnf",
        "yum",
        "rpm",
        "zypper",
        "pacman",
        "virsh",
        "useradd",
        "userdel",
        "usermod",
        "groupadd",
        "groupdel",
        "chpasswd",
        "passwd",
        "smbpasswd",
        "pdbedit",
        "zfs",
        "zpool",
        "modprobe",
        "sysctl",
        "mount",
        "umount",
        "reboot",
        "shutdown",
        "poweroff",
        "launchctl",
        "hdiutil",
        "installer",
        "pkgutil",
        "dscl",
        "sysadminctl",
        "msiexec",
        "msiexec.exe",
        "wsl",
        "wsl.exe",
        "dism",
        "dism.exe",
        "schtasks",
        "sc",
        "sc.exe",
    }
)
# PowerShell, which a test runs only on a script it wrote under the
# temporary directory.
POWERSHELL_PROGRAMS = frozenset({"powershell", "powershell.exe", "pwsh", "pwsh.exe"})

_real_popen = subprocess.Popen
_real_system = os.system


def _refuses(command, environment=None) -> "str | None":
    """Why a test must not start a command on the real machine, or None when it may.

    Args:
        command: The argument vector, or a shell line.
        environment: The environment it starts with; None is the test's own.

    Returns:
        The reason naming the program; None for a program of no refused
        name, one found under the temporary directory, and PowerShell on a
        script there.
    """
    if isinstance(command, (str, bytes)):
        words = os.fsdecode(command).split()
    else:
        words = [os.fsdecode(word) for word in command]
    if not words:
        return None
    program = words[0]
    name = os.path.basename(program).lower()
    under_temp = os.path.realpath(tempfile.gettempdir()) + os.sep
    if name in POWERSHELL_PROGRAMS:
        script = words[words.index("-File") + 1] if "-File" in words[:-1] else ""
        if script and os.path.realpath(script).startswith(under_temp):
            return None
        return f"{name} runs only a script a test wrote"
    if name not in REFUSED_PROGRAMS:
        return None
    path = (environment or os.environ).get("PATH", os.defpath)
    found = program if os.sep in program else shutil.which(program, path=path)
    if found and os.path.realpath(found).startswith(under_temp):
        return None
    return f"{name} changes or reads the machine, or asks for authorization to"


@pytest.fixture(autouse=True)
def _no_test_reaches_the_machine(monkeypatch):
    """Fail a test at once when it would start a refused program on the real machine.

    ``subprocess.run``, ``call`` and ``check_output`` start every process
    through ``Popen``. Code under test catches ``Exception`` in places, so
    the refusal is a pytest failure, which it does not catch, and the test
    also fails at its end when something swallowed it.
    """
    refused: list = []

    def refuse(reason: str, command) -> None:
        test = os.environ.get("PYTEST_CURRENT_TEST", "a test")
        refused.append(reason)
        pytest.fail(
            f"{test} would start {command!r} on this machine ({reason}); "
            "patch the module's run, or put a fake on PATH under tmp_path",
            pytrace=True,
        )

    class GuardedPopen(_real_popen):
        def __init__(self, command, *arguments, **keywords):
            reason = _refuses(command, keywords.get("env"))
            if reason is not None:
                refuse(reason, command)
            super().__init__(command, *arguments, **keywords)

    def guarded_system(command):
        reason = _refuses(command)
        if reason is not None:
            refuse(reason, command)
        return _real_system(command)

    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    monkeypatch.setattr(os, "system", guarded_system)
    yield refused
    if refused:
        pytest.fail(f"the test tried to start a refused program: {refused}")


def _moduleless_platform():
    """This system's platform without the capabilities that build package runners.

    An agent a test builds on its own platform then observes no module of
    the machine the suite runs on: no Samba, no Podman.
    """
    platform = detect_module.detect_platform()
    platform.capabilities = frozenset(
        platform.capabilities - {"packages", "hub_packages", "smb_server"}
    )
    return platform


@pytest.fixture(autouse=True)
def _agent_observes_no_module_of_this_machine(monkeypatch):
    monkeypatch.setattr(loop_module, "detect_platform", _moduleless_platform)


@pytest.fixture(autouse=True)
def _isolated_machine_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(tmp_path / "agent.json"))
    monkeypatch.setattr(store_module, "AGENT_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(platforms_base_module, "AGENT_DATA_DIR_POSIX", str(tmp_path))
    monkeypatch.setattr(
        engine_module, "AGENT_CONFIGURED_DIR", str(tmp_path / "configured")
    )
    monkeypatch.setattr(platforms_base_module, "AGENT_VAR_DIR", str(tmp_path))


@pytest.fixture(autouse=True)
def _isolated_ai_forward(monkeypatch):
    """The AI gateway forward an agent builds asks for a port the system
    picks, never for the machine's own 8317."""
    monkeypatch.setattr(
        loop_module, "AiGatewayForward", functools.partial(AiGatewayForward, port=0)
    )


@pytest.fixture(autouse=True)
def _isolated_network(monkeypatch):
    """No route is looked at, unless a test says otherwise."""
    monkeypatch.setattr(enrollment, "default_source_address", lambda urls: "")


def _no_transport(*_arguments, **_keywords):
    raise OSError("no transport is started in tests")


@pytest.fixture(autouse=True)
def _no_transport_started(monkeypatch):
    """No test starts ``neutrino_transport``: a test that needs one hands the
    agent a :class:`~tests.transport.fake_transport.FakeTransport`."""
    monkeypatch.setattr(loop_module, "start_transport", _no_transport)
    monkeypatch.setattr(loop_module, "one_shot_transport", _no_transport)
    monkeypatch.setattr(enrollment, "one_shot_transport", _no_transport)


@pytest.fixture(autouse=True)
def _no_system_commands_from_the_appliers(monkeypatch):
    """The remote desktop appliers run nothing on the real machine: a test
    that builds one without its own ``run`` gets a runner that refuses
    every command, so no ``systemctl`` reaches the system or asks a
    session's polkit for rights."""

    def refused(argv, **_):
        return CommandResult(
            command=list(argv),
            exit_code=1,
            stdout="",
            stderr="no commands run in tests",
        )

    for module in (linux_applier_module, darwin_applier_module, windows_applier_module):
        monkeypatch.setattr(module, "run_command", refused)


def _no_powershell(argv):
    raise OSError("no PowerShell is started in tests")


@pytest.fixture(autouse=True)
def _no_powershell_host(monkeypatch):
    """The agent's one PowerShell host starts nothing: a test that needs the
    host hands its platform or applier a :class:`RecordingHost`."""
    monkeypatch.setattr(
        powershell_host_module,
        "_AGENT_HOST",
        WindowsPowerShellHost(start_process=_no_powershell),
    )


@pytest.fixture(autouse=True)
def _fresh_hub_clock(monkeypatch):
    """Each test starts with a hub clock of its own at offset zero, so an
    offset one test's welcome set reaches no other test."""
    monkeypatch.setattr(hub_clock_module, "_HUB_CLOCK", HubClock())


@pytest.fixture
def config_path(tmp_path):
    """The binding file the autouse redirect already points the agent at."""
    return tmp_path / "agent.json"


class Clock:
    """An injected clock: time moves only when a test says so."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def link_for(payload: dict) -> str:
    """The link a hub writes: compact JSON, zlib level 9, unpadded base64url."""
    text = json.dumps(payload, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(zlib.compress(text, 9)).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def discard(message: str) -> None:
    """Swallow the log lines."""


BINDING_ID = "dev-1"
BINDING_TOKEN = "tok"
MACHINE_ID = "machine-1"
HUB_KEY = "ab" * 32
PRIVATE_KEY = "cd" * 32


def bind(path, url="tcp://127.0.0.1:9", urls=None) -> None:
    """Write a complete binding file, the way a join leaves it.

    Args:
        path: The binding file.
        url: The address that last answered.
        urls: Every address the hub answers on; None writes no list.
    """
    binding = {
        "gateway_url": url,
        "id": BINDING_ID,
        "token": BINDING_TOKEN,
        "hub_key": HUB_KEY,
        "private_key": PRIVATE_KEY,
        "machine_id": MACHINE_ID,
    }
    if urls is not None:
        binding["gateway_urls"] = list(urls)
    path.write_text(json.dumps(binding))


class FakeControlPlatform(AgentPlatform):
    os_name = "linux"

    def human_accounts(self) -> list:
        return ["alice", "bob"]

    def agent_service_start_hint(self) -> str:
        return "sudo systemctl enable --now neutrino_agent.service"


class FakeSocketPlatform(FakeControlPlatform):
    """The control platform plus the socket path the CLI commands ask for."""

    def __init__(self, socket_path: str):
        self._socket_path = socket_path

    def control_socket_path(self) -> str:
        return self._socket_path


class FakeControlAgent:
    def __init__(self):
        self.joined_links = []
        self.is_left = False
        self.join_error = None
        self.error = None
        self.is_socket_open = False
        self.sync_reply = {}
        self.syncs = 0
        self.share = {
            "is_shared": False,
            "state": "not_shared",
            "port": 21118,
            "account": "",
            "attention": "",
            "has_password": False,
        }

    def platform(self) -> dict:
        return {"os": "linux", "family": "debian", "arch": "x86_64"}

    def module_states(self) -> dict:
        return {
            "remote_desktop": {
                "state": "stopped",
                "is_active": False,
                "code": "",
                "params": {},
                "details": {},
            }
        }

    def state_hash(self) -> str:
        return "h1"

    def last_error(self):
        return self.error

    def is_online(self) -> bool:
        return self.is_socket_open

    def accounts(self) -> list:
        return ["alice", "bob"]

    def rdp_state(self) -> dict:
        return dict(self.share)

    def sync(self) -> dict:
        self.syncs += 1
        return dict(self.sync_reply)

    def join(self, link):
        if self.join_error is not None:
            raise self.join_error
        self.joined_links.append(link)

    def leave(self):
        self.is_left = True


def completed(stdout: str = "", returncode: int = 0):
    """A finished process as ``subprocess.run`` hands it back."""
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class FakeSystemd:
    """systemd for the agent's unit: ``is-active``, ``enable --now``, ``stop``."""

    platform_class = LinuxPlatform
    platform_module = linux_module

    def __init__(self):
        self.calls: list = []
        self.is_running = False
        self.is_refusing = False

    def __call__(self, command, **kwargs):
        command = list(command)
        self.calls.append(command)
        if command[:2] == ["systemctl", "is-active"]:
            word = "active" if self.is_running else "inactive"
            return completed(word + "\n", 0 if self.is_running else 3)
        if self.is_refusing:
            return completed("", 1)
        if command[:3] == ["systemctl", "enable", "--now"]:
            self.is_running = True
        elif command[:2] == ["systemctl", "stop"]:
            self.is_running = False
        return completed("")


class FakeServiceControlManager:
    """The Windows service control manager through ``sc``; a start or a stop
    reads pending once before it settles."""

    platform_class = WindowsPlatform
    platform_module = windows_module

    def __init__(self):
        self.calls: list = []
        self.is_running = False
        self.is_refusing = False
        self._pending = 0

    def __call__(self, command, **kwargs):
        command = list(command)
        self.calls.append(command)
        if command[:2] == ["sc", "query"]:
            if self._pending:
                number, self._pending = self._pending, 0
            else:
                number = 4 if self.is_running else 1
            return completed(f"        STATE              : {number}  WORD\n")
        if self.is_refusing:
            return completed("[SC] StartService FAILED 1058", 1058)
        if command[:2] == ["sc", "start"]:
            self.is_running, self._pending = True, 2
        elif command[:2] == ["sc", "stop"]:
            self.is_running, self._pending = False, 3
        return completed("")


class FakeLaunchd:
    """launchd for the agent's job: ``print``, ``bootstrap``, ``kickstart``,
    ``bootout``."""

    platform_class = DarwinPlatform
    platform_module = darwin_module

    def __init__(self):
        self.calls: list = []
        self.is_running = False
        self.is_refusing = False

    def __call__(self, command, **kwargs):
        command = list(command)
        self.calls.append(command)
        if command[:2] == ["launchctl", "print"]:
            if not self.is_running:
                return completed("", 113)
            return completed("system/com.neutrino.agent = {\n\tstate = running\n}\n")
        if self.is_refusing:
            return completed("", 5)
        if command[:2] == ["launchctl", "kickstart"]:
            self.is_running = True
        elif command[:2] == ["launchctl", "bootout"]:
            self.is_running = False
        return completed("")


@pytest.fixture(params=[FakeSystemd, FakeServiceControlManager, FakeLaunchd])
def service_manager(request, monkeypatch):
    """Each platform's service manager, faked, answering for this machine."""
    import neutrino_agent.cli.start as start_module
    import neutrino_agent.cli.status as status_module
    import neutrino_agent.cli.stop as stop_module

    manager = request.param()
    monkeypatch.setattr(manager.platform_module.subprocess, "run", manager)
    platform = manager.platform_class()

    def this_platform():
        return platform

    for module in (start_module, status_module, stop_module):
        monkeypatch.setattr(module, "detect_platform", this_platform)
    monkeypatch.setattr(status_module, "SERVICE_SETTLE_POLL_S", 0)
    return manager


class FakeBatchLogon:
    """The batch logon right: each hold and release recorded as ``(op,
    args)``, nothing granted.

    A test that hands it the host's ``calls`` list reads both in one order.
    """

    def __init__(self, calls=None):
        self.calls: list = calls if calls is not None else []
        self.taken: list = []

    def hold(self, account, task, password):
        self.calls.append(("batch_logon_hold", {"account": account, "task": task}))

    def release(self, account, task):
        self.calls.append(("batch_logon_release", {"account": account, "task": task}))
        return False

    def release_all(self):
        self.calls.append(("batch_logon_release_all", {}))
        return list(self.taken)


class RecordingHost:
    """The PowerShell host: each operation and its arguments recorded, a canned
    answer given.

    Every operation must be one the library has, and its arguments must
    travel as JSON. An answer is a dict, an exception to raise, or a
    function of the arguments.
    """

    def __init__(self, answers=None):
        self.calls: list = []
        self.answers = dict(answers or {})

    def call(self, op, args, *, timeout_s=WINDOWS_POWERSHELL_HOST_CALL_TIMEOUT_S):
        assert op in WINDOWS_POWERSHELL_HOST_OPS, op
        self.calls.append((op, json.loads(json.dumps(args))))
        answer = self.answers.get(op, {})
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer(args)
        return json.loads(json.dumps(answer))

    def ops(self) -> list:
        """The operations asked, in order."""
        return [op for op, _args in self.calls]

    def args_of(self, op) -> list:
        """The arguments of every call of one operation, in order."""
        return [args for asked, args in self.calls if asked == op]


class FakeProcessTable:
    """The machine's processes: each one's parent, start, name, command line
    and program, the listeners on each port, and the ones ended."""

    def __init__(self, processes=(), listeners=None):
        """
        Args:
            processes: ``(pid, parent pid, create time, name, command line,
                program)`` per process.
            listeners: Each port to the pids listening on it.
        """
        self.processes = list(processes)
        self.listeners = dict(listeners or {})
        self.ended: list = []
        self.is_refusing = False

    def entries(self) -> list:
        if self.is_refusing:
            raise OSError("the kernel refused the process table")
        return [
            WindowsProcessEntry(pid, parent, created, name, 0, 0)
            for pid, parent, created, name, _command, _program in self.processes
        ]

    def command_line(self, pid) -> str:
        return next((p[4] for p in self.processes if p[0] == pid), "")

    def image_path(self, pid) -> str:
        return next((p[5] for p in self.processes if p[0] == pid), "")

    def listener_pids(self, port) -> list:
        return list(self.listeners.get(port, []))

    def end(self, pids) -> None:
        self.ended.extend(pids)
