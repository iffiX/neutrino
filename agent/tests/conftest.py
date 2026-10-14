"""Suite-wide isolation and the shared fakes, defined once.

The autouse redirect keeps every store off the real machine: the binding
file, the machine's own state store, the credentials directory, the
configured marks and the package directory all land in ``tmp_path``, and
the AI gateway forward an agent builds listens on a port the system picks.
The fakes here are the ones more than one directory drives: the control
channel's platform and agent, the injected clock, the link builder and the
log sink.
"""

import base64
import functools
import json
import subprocess
import zlib

import pytest

import neutrino_agent.core.engine as engine_module
import neutrino_agent.core.enrollment as enrollment
import neutrino_agent.core.loop as loop_module
import neutrino_agent.core.store as store_module
import neutrino_agent.modules.remote_desktop.darwin_applier as darwin_applier_module
import neutrino_agent.modules.remote_desktop.linux_applier as linux_applier_module
import neutrino_agent.modules.remote_desktop.windows_applier as windows_applier_module
from neutrino_agent.modules.shared.subprocess_run import CommandResult
import neutrino_agent.platforms.base as platforms_base_module
import neutrino_agent.platforms.darwin as darwin_module
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
    """The AI gateway forward an agent builds listens on a port the system
    picks, never on the machine's own 8317, and looks for a channel often."""
    monkeypatch.setattr(
        loop_module,
        "AiGatewayForward",
        functools.partial(AiGatewayForward, port=0, poll_s=0.02),
    )


@pytest.fixture(autouse=True)
def _isolated_network(monkeypatch):
    """The hub's name resolves to nothing and no route is looked at, unless a
    test says otherwise; a round waits nothing between addresses."""
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "")
    monkeypatch.setattr(enrollment, "default_source_address", lambda urls: "")
    monkeypatch.setattr(loop_module, "AGENT_ROTATE_DELAY_S", 0)


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


def bind(path, url="http://127.0.0.1:9", fingerprint="", urls=None) -> None:
    """Write a complete binding file, the way a join leaves it.

    Args:
        path: The binding file.
        url: The address that last answered.
        fingerprint: The pinned fingerprint.
        urls: Every address the hub answers on; None writes a file of the
            0.3.0 shape, without the list.
    """
    binding = {
        "gateway_url": url,
        "id": BINDING_ID,
        "token": BINDING_TOKEN,
        "fingerprint": fingerprint,
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
