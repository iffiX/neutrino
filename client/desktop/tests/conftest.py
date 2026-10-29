"""Suite-wide isolation and the shared fakes, defined once.

The autouse redirect keeps every store off the real machine: the platform's
configuration directory, and with it the bindings, the state store and the
mount credentials, all land in ``tmp_path``, and the control socket in a
runtime directory of its own. The fakes here are the ones more than one
directory drives: the client platform, the resident, the injected clock,
the link builder and the log sink. ``HUB_SERVICES`` is what one hub sends
in a state; ``SERVICES`` is the two-hub list the resident merges from it,
each entry stamped with its ``hub_id``.

A guard on every process a test starts refuses by name the service and
session managers, the mount tools, everything that asks for authorization,
the package managers, the tools that change the machine's network, the
person's browser and clipboard, the overlays the client carries and
``ssh``: a test that reaches one fails naming the command, rather than
opening a password dialog or a browser on the developer's desktop. A
program of one of these names that a test placed under the temporary
directory, a fake, runs. Python's own ``webbrowser`` is refused the same
way. An audit hook fails a test that writes, creates, renames or removes a
file outside its temporary folders.
"""

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import webbrowser
import zlib

import pytest

import neutrino_client.cli.wording as wording_module
import neutrino_client.core.enrollment as enrollment
from neutrino_client.platforms.base import ClientPlatform
from neutrino_client.platforms.darwin import DarwinPlatform
from neutrino_client.platforms.linux import LinuxPlatform
from neutrino_client.platforms.windows import WindowsPlatform

# The programs no test may start on the real machine: the service and
# session managers, the mount tools and everything that asks for
# authorization, the package managers, the tools that change the machine's
# network or the Windows and macOS system, the person's browser and
# clipboard, the overlays and tools the client carries, and ssh. A program
# of one of these names that a test placed under the temporary directory, a
# fake on its own PATH, runs.
REFUSED_PROGRAMS = frozenset(
    {
        "systemctl",
        "systemd-run",
        "loginctl",
        "journalctl",
        "sudo",
        "pkexec",
        "runuser",
        "su",
        "doas",
        "mount",
        "umount",
        "mount.cifs",
        "umount.cifs",
        "mount_smbfs",
        "diskutil",
        "osascript",
        "open",
        "launchctl",
        "installer",
        "pkgutil",
        "apt",
        "apt-get",
        "dpkg",
        "dnf",
        "yum",
        "rpm",
        "zypper",
        "pacman",
        "nft",
        "iptables",
        "ip6tables",
        "ufw",
        "firewall-cmd",
        "resolvectl",
        "nmcli",
        "sysctl",
        "modprobe",
        "net",
        "net.exe",
        "netsh",
        "netsh.exe",
        "cmdkey",
        "cmdkey.exe",
        "icacls",
        "icacls.exe",
        "schtasks",
        "schtasks.exe",
        "sc",
        "sc.exe",
        "reg",
        "reg.exe",
        "msiexec",
        "msiexec.exe",
        "xdg-open",
        "gio",
        "x-www-browser",
        "sensible-browser",
        "firefox",
        "chromium",
        "google-chrome",
        "wl-copy",
        "wl-paste",
        "xclip",
        "xsel",
        "pbcopy",
        "pbpaste",
        "notify-send",
        "netbird",
        "easytier-core",
        "easytier-cli",
        "rustdesk",
        "cc-switch",
        "ssh",
    }
)
# PowerShell, which a test runs only on a script it wrote under the
# temporary directory.
POWERSHELL_PROGRAMS = frozenset({"powershell", "powershell.exe", "pwsh", "pwsh.exe"})
# ``ip`` only reads, unless one of these words is in it.
MUTATING_IP_VERBS = frozenset(
    {"add", "del", "delete", "replace", "change", "set", "flush", "monitor"}
)
# The audit events that change a file by name, each to the places of its
# paths. A place is the position of a path and the position of the folder
# descriptor it is relative to, or None.
FILE_CHANGE_EVENTS = {
    "os.chmod": ((0, 2),),
    "os.chown": ((0, 3),),
    "os.link": ((1, 3),),
    "os.mkdir": ((0, 2),),
    "os.remove": ((0, 1),),
    "os.rename": ((0, 2), (1, 3)),
    "os.rmdir": ((0, 1),),
    "os.symlink": ((1, 2),),
    "os.truncate": ((0, None),),
    "os.utime": ((0, 3),),
    "shutil.copyfile": ((1, None),),
    "shutil.copytree": ((1, None),),
    "shutil.move": ((0, None), (1, None)),
    "shutil.rmtree": ((0, 1),),
}
# Every audit event the file guard reads: the changes by name, ``open`` and
# the bind of a Unix socket.
FILE_AUDIT_EVENTS = frozenset(FILE_CHANGE_EVENTS) | {"open", "socket.bind"}
# The flags of an ``os.open`` that writes or creates.
FILE_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

_real_popen = subprocess.Popen
_real_system = os.system
_real_exec = {
    name: getattr(os, name) for name in ("execv", "execve", "execvp", "execvpe")
}


def _refuses(command, environment=None) -> "str | None":
    """Why a test must not start a command on the real machine, or None when it may.

    Args:
        command: The argument vector, or a shell line.
        environment: The environment it starts with; None is the test's own.

    Returns:
        The reason naming the program; None for a program of no refused
        name, one found under the temporary directory, PowerShell on a
        script there, and an ``ip`` that only reads.
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
    if name == "ip":
        if MUTATING_IP_VERBS.intersection(words[1:]):
            return "ip would change an address, a link, a route or a rule"
        return None
    if name not in REFUSED_PROGRAMS:
        return None
    path = (environment or os.environ).get("PATH", os.defpath)
    found = program if os.sep in program else shutil.which(program, path=path)
    if found and os.path.realpath(found).startswith(under_temp):
        return None
    return f"{name} changes the machine or the desktop, or asks for authorization to"


@pytest.fixture(autouse=True)
def _no_test_reaches_the_machine(monkeypatch):
    """Fail a test at once when it would start a refused program on the real machine.

    ``subprocess.run``, ``call`` and ``check_output`` start every process
    through ``Popen``. Code under test catches ``Exception`` in places, so
    the refusal is a pytest failure, which it does not catch, and the test
    also fails at its end when something swallowed it. A refused ``exec``
    in a forked child ends that child.
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

    def guarded_exec(name):
        def run(program, argv, *rest):
            reason = _refuses([program] + list(argv)[1:])
            if reason is not None:
                os.write(2, f"refused {program}: {reason}\n".encode())
                os._exit(127)
            return _real_exec[name](program, argv, *rest)

        return run

    def guarded_browser(url, *arguments, **keywords):
        refuse("the person's browser", ["webbrowser", url])

    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    monkeypatch.setattr(os, "system", guarded_system)
    for name in _real_exec:
        monkeypatch.setattr(os, name, guarded_exec(name))
    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, guarded_browser)
    yield refused
    if refused:
        pytest.fail(f"the test tried to start a refused program: {refused}")


# The folders the running test may change, and the paths the file guard
# refused in it. ``refused`` is None between tests.
_file_guard = {"roots": (), "refused": None}


def _named_path(path, folder) -> "str | None":
    """The absolute path of a name an audit event changes.

    Args:
        path: The path, relative to ``folder`` when that is a descriptor.
        folder: The descriptor of a folder, or None or -1 for none.

    Returns:
        The path with its folder resolved and its last name kept; None for
        a descriptor, or a folder this system cannot name.
    """
    if isinstance(path, int):
        return None
    path = os.fsdecode(os.fspath(path))
    if not os.path.isabs(path) and isinstance(folder, int) and folder >= 0:
        try:
            path = os.path.join(os.readlink(f"/proc/self/fd/{folder}"), path)
        except OSError:
            return None
    head, name = os.path.split(os.path.abspath(path))
    return os.path.join(os.path.realpath(head), name)


def _changed_paths(event: str, arguments: tuple) -> list:
    """The paths an audit event writes, creates, renames or removes.

    Args:
        event: The audit event.
        arguments: Its arguments.

    Returns:
        Each absolute path. A write through ``open`` resolves the whole
        path, and every other change resolves the folder of the name.
    """
    if event == "open":
        path, mode, flags = arguments
        is_write = isinstance(mode, str) and any(letter in mode for letter in "wax+")
        if isinstance(flags, int) and flags & FILE_WRITE_FLAGS:
            is_write = True
        if not is_write or isinstance(path, int):
            return []
        return [os.path.realpath(os.fsdecode(os.fspath(path)))]
    if event == "socket.bind":
        address = arguments[1]
        if isinstance(address, bytes):
            address = os.fsdecode(address)
        if not isinstance(address, str) or address[:1] in ("", "\0"):
            return []
        return [_named_path(address, None)]
    paths = []
    for path_at, folder_at in FILE_CHANGE_EVENTS[event]:
        if folder_at is not None and folder_at < len(arguments):
            path = _named_path(arguments[path_at], arguments[folder_at])
        else:
            path = _named_path(arguments[path_at], None)
        if path is not None:
            paths.append(path)
    return paths


def _is_test_owned(path: str) -> bool:
    """Whether a test may change a path: under its temporary folders, a
    bytecode cache, or the null device."""
    if path == os.devnull or "__pycache__" in path.split(os.sep):
        return True
    return any(
        path == root or path.startswith(root + os.sep) for root in _file_guard["roots"]
    )


def _guard_files(event: str, arguments: tuple) -> None:
    """Fail the running test when an audit event changes a file outside its
    temporary folders.

    Raises:
        pytest.fail.Exception: Naming the test, the path and the event.
    """
    refused = _file_guard["refused"]
    if refused is None or event not in FILE_AUDIT_EVENTS:
        return
    for path in _changed_paths(event, arguments):
        if not _is_test_owned(path):
            test = os.environ.get("PYTEST_CURRENT_TEST", "a test")
            refused.append(path)
            pytest.fail(
                f"{test} would change {path} on this machine ({event}); "
                "point it under tmp_path, or stub what writes it",
                pytrace=True,
            )


sys.addaudithook(_guard_files)


@pytest.fixture(autouse=True)
def _no_test_changes_a_file_of_the_machine(tmp_path_factory):
    """Fail a test at once when it would change a file outside its temporary folders.

    The audit hook checks every thread. Code under test catches
    ``Exception`` in places. The refusal is a pytest failure it does not
    catch, and the test also fails at its end when something swallowed it.
    """
    _file_guard["roots"] = (
        os.path.realpath(tempfile.gettempdir()),
        os.path.realpath(tmp_path_factory.getbasetemp()),
    )
    refused: list = []
    _file_guard["refused"] = refused
    yield refused
    _file_guard["refused"] = None
    if refused:
        pytest.fail(f"the test tried to change a file of the machine: {refused}")


SAME_USER = {"account": "alice", "uid": 1000, "is_same_user": True}
OTHER_USER = {"account": "bob", "uid": 1001, "is_same_user": False}

HUB_SERVICES = [
    {
        "id": "ai",
        "type": "ai",
        "title": "AI tools",
        "payload": {
            "endpoint": "http://hub:8080",
            "protocol": "anthropic",
            "models": ["m1", "m2"],
        },
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "svc_wiki",
        "type": "web",
        "title": "Wiki",
        "payload": {"url": "http://w/"},
        "is_healthy": True,
        "source": "declared",
        "description": "declared by hand",
    },
    {
        "id": "svc_tcp",
        "type": "port",
        "title": "tcp",
        "payload": {"host": "h", "port": 5432},
        "is_healthy": True,
        "source": "module",
        "description": "published by container mysql:8.0",
    },
    {
        "id": "share_media",
        "type": "file",
        "title": "media",
        "payload": {"protocol": "smb", "host": "hub", "share": "media"},
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "rdp_s9",
        "type": "rdp",
        "title": "studio",
        "payload": {"protocol": "rustdesk", "host": "192.168.100.6", "port": 21118},
        "is_healthy": True,
        "source": "device",
        "description": "shared from studio",
    },
]

# What the second hub sends; its ids overlap the first's on purpose.
OFFICE_SERVICES = [
    {
        "id": "ai",
        "type": "ai",
        "title": "Office AI",
        "payload": {
            "endpoint": "http://office:8080",
            "protocol": "anthropic",
            "models": ["o1"],
        },
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "svc_docs",
        "type": "web",
        "title": "Docs",
        "payload": {"url": "http://docs/"},
        "is_healthy": True,
        "source": "declared",
        "description": "declared by hand",
    },
    {
        "id": "svc_tcp",
        "type": "port",
        "title": "office db",
        "payload": {"host": "office", "port": 5432},
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "share_media",
        "type": "file",
        "title": "office media",
        "payload": {"protocol": "smb", "host": "office", "share": "media"},
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "rdp_lab",
        "type": "rdp",
        "title": "lab",
        "payload": {"protocol": "rustdesk", "host": "10.0.0.6", "port": 21118},
        "is_healthy": True,
        "source": "device",
        "description": "shared from lab",
    },
]


def with_hub(entries: list, hub_id: str) -> list:
    """One hub's entries the way the resident merges them, stamped with the hub."""
    return [dict(entry, hub_id=hub_id) for entry in entries]


SERVICES = with_hub(HUB_SERVICES, "h1") + with_hub(OFFICE_SERVICES, "h2")


@pytest.fixture(autouse=True)
def _isolated_person_paths(tmp_path, monkeypatch):
    config_dir = str(tmp_path / "config")
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()

    def redirected(self) -> str:
        return config_dir

    for platform_class in (
        ClientPlatform,
        DarwinPlatform,
        LinuxPlatform,
        WindowsPlatform,
    ):
        monkeypatch.setattr(platform_class, "config_dir", redirected)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # cc-switch's store is named to it through the process's environment;
    # each test starts with none named and leaves none behind.
    monkeypatch.delenv("CC_SWITCH_CONFIG_DIR", raising=False)
    (tmp_path / "home").mkdir()


# The real ask of the EasyTier daemon, for the tests that drive it.
REAL_ASK_HOLD = wording_module.ask_hold


@pytest.fixture(autouse=True)
def _isolated_network(monkeypatch):
    """No route is looked at and no EasyTier daemon of this machine is asked
    who holds it, unless a test says otherwise."""
    monkeypatch.setattr(wording_module, "ask_hold", lambda verb: {})
    monkeypatch.setattr(enrollment, "default_source_address", lambda urls: "")


@pytest.fixture
def config_path(tmp_path):
    """The binding file the autouse redirect already points the client at."""
    return tmp_path / "config" / "client.json"


class Clock:
    """An injected clock: time moves only when a test says so."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def link_for(payload: dict) -> str:
    """An enrollment link over one payload as a hub writes it: compact JSON,
    zlib level 9, unpadded base64url; ``role`` defaults to client."""
    body = {"role": "client", **payload}
    text = json.dumps(body, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(zlib.compress(text, 9)).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def discard(message: str) -> None:
    """Swallow the log lines."""


# The hub's static public key a link carries, and this client's private key.
HUB_KEY = "11" * 32
PRIVATE_KEY = "22" * 32
BINDING = {
    "id": "c1",
    "name": "box",
    "hub_id": "h1",
    "hub_name": "home",
    "gateway_url": "tcp://127.0.0.1:9",
    "gateway_urls": [],
    "hub_key": HUB_KEY,
    "private_key": PRIVATE_KEY,
    "fingerprint": "",
    "token": "tok",
    "overlays": [],
    "is_overlay_on": False,
    "overlay_pick": "",
}
OFFICE_BINDING = {
    "id": "c2",
    "name": "box",
    "hub_id": "h2",
    "hub_name": "office",
    "gateway_url": "tcp://office.lan:8443",
    "gateway_urls": [],
    "hub_key": HUB_KEY,
    "private_key": PRIVATE_KEY,
    "fingerprint": "",
    "token": "tok2",
    "overlays": [],
    "is_overlay_on": False,
    "overlay_pick": "",
}


def bind(path, url="tcp://127.0.0.1:9", fingerprint="", bindings=None) -> None:
    """The bindings on disk, the way ``client.json`` keeps them.

    Args:
        path: The binding file.
        url: The first binding's gateway url.
        fingerprint: The first binding's fingerprint.
        bindings: Every binding to write; None writes the one binding.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if bindings is None:
        binding = dict(BINDING, gateway_url=url, fingerprint=fingerprint)
        if fingerprint:
            binding.update(hub_key="", private_key="")
        bindings = [binding]
    path.write_text(json.dumps({"bindings": list(bindings), "exit_hub_id": ""}))


# The overlay part of a hub row: a NetBird network this machine is on.
OVERLAY_ROW = {
    "network": "netbird",
    "networks": [
        {"provider": "netbird", "network": "api.netbird.io"},
        {"provider": "easytier", "network": "home"},
    ],
    "state": "on",
    "stage": "",
    "is_waiting": False,
    "address": "100.64.0.7",
    "error": None,
}
# The jobs of a hub at rest.
IDLE_JOBS = {"is_refreshing": False, "overlay_job": "", "is_leaving": False}
HUB_ROW = {
    "hub_id": "h1",
    "hub_name": "home",
    "binding_id": "c1",
    "gateway_url": "https://hub.lan:8443",
    "software": "neutrino_hub/0.3.0",
    "connection": "connected",
    "wait_reason": "",
    "wait_code": None,
    "next_round_at": None,
    "is_pending": False,
    "last_error": None,
    "is_exit": True,
    "overlay": dict(OVERLAY_ROW),
    "jobs": dict(IDLE_JOBS),
}
# The machines the first hub offers a terminal on, as the resident merges them.
TERMINALS = [
    {"hub_id": "h1", "device_id": "d_lepton", "name": "lepton", "is_online": True},
    {"hub_id": "h1", "device_id": "d_muon", "name": "muon", "is_online": False},
]
# The sessions the first hub lists for this client.
TERMINAL_SESSIONS = [
    {
        "hub_id": "h1",
        "session_id": "s1",
        "device_id": "d_lepton",
        "owner": "client:c1",
        "is_owned": True,
        "is_persistent": True,
        "is_shared": False,
        "attached_count": 0,
        "title": "zsh",
        "started_at": 1700000000,
    }
]
OFFICE_ROW = {
    "hub_id": "h2",
    "hub_name": "office",
    "binding_id": "c2",
    "gateway_url": "https://office.lan:8443",
    "software": "neutrino_hub/0.3.0",
    "connection": "connected",
    "wait_reason": "",
    "wait_code": None,
    "next_round_at": None,
    "is_pending": False,
    "last_error": None,
    "is_exit": False,
    "overlay": {
        "network": "",
        "networks": [],
        "state": "off",
        "stage": "",
        "is_waiting": False,
        "address": "",
        "error": None,
    },
    "jobs": dict(IDLE_JOBS),
}


class FakeClientPlatform(ClientPlatform):
    """A platform whose mounts are in memory and whose peer is scripted."""

    os_name = "linux"

    def __init__(self):
        self.peer = dict(SAME_USER)
        self.peer_error = None
        self.fs_calls = []
        self.fs_error = None
        self.attached = set()
        self.attach_calls = []
        self.detach_calls = []
        self.attach_error = None
        self.detach_error = None
        # Where the system places a volume when no location is given.
        self.volume_location = ""
        self.has_tooling = True
        self.opened_urls = []
        self.started = []
        self.start_error = None
        self.socket_path = ""
        self.answered = []
        self.on_answer = None
        self.answer_error = None
        self.answer_output = ""
        self.language = "en"

    def system_language(self) -> str:
        return self.language

    def control_socket_path(self) -> str:
        if self.socket_path:
            return self.socket_path
        return os.path.join(os.environ["XDG_RUNTIME_DIR"], "neutrino", "client.sock")

    def read_peer_identity(self, connection) -> dict:
        if self.peer_error is not None:
            raise self.peer_error
        return dict(self.peer)

    def list_directories(self, *, path: str) -> list:
        self.fs_calls.append(("list", path))
        if self.fs_error is not None:
            raise self.fs_error
        return ["docs", "media"]

    def make_directory(self, *, path: str) -> None:
        self.fs_calls.append(("mkdir", path))
        if self.fs_error is not None:
            raise self.fs_error
        # Only a POSIX-absolute path (the tmp_path the mount cases use) is
        # made on disk; a foreign-OS path a routes case passes is recorded
        # and left alone, so no test writes outside its tmp_path.
        if path.startswith("/"):
            os.makedirs(path, exist_ok=True)

    def has_mount_tooling(self) -> bool:
        return self.has_tooling

    def attach_share(self, *, share_url, location, credentials_path, port=0) -> str:
        self.attach_calls.append(
            {
                "share_url": share_url,
                "port": port,
                "location": location,
                "credentials_path": credentials_path,
            }
        )
        if self.attach_error is not None:
            raise self.attach_error
        attached_at = location or self.volume_location
        self.attached.add(attached_at)
        return attached_at

    def detach_share(self, *, location: str) -> None:
        self.detach_calls.append(location)
        if self.detach_error is not None:
            raise self.detach_error
        self.attached.discard(location)

    def is_share_attached(self, *, location: str) -> bool:
        return location in self.attached

    def open_url(self, url: str) -> None:
        self.opened_urls.append(url)

    def start_on_screen(self, argv: list):
        if self.start_error is not None:
            raise self.start_error
        process = FakeProcess(list(argv))
        self.started.append(process)
        return process

    def run_answering(self, argv: list, *, prompt, answer, timeout_s) -> tuple:
        if self.answer_error is not None:
            raise self.answer_error
        self.answered.append((list(argv), prompt, answer))
        if self.on_answer is not None:
            self.on_answer(list(argv))
        return 0, self.answer_output


class FakeTransportChannel:
    """The client's local channel to its transport, in process and scripted.

    Every command is recorded and answered from ``answers`` (``{command:
    callable(fields) -> answer}``, empty by default); every frame sent is
    recorded as ``(binding, frame)``; a stream opens on ``open_stream``,
    which a test sets, else :class:`FakeStreamEnd` accepts it. Lines for a
    binding reach the session through its listener, which ``deliver`` calls.

    Attributes:
        commands: ``(name, fields)`` of every command, in order.
        frames: ``(binding, frame)`` of every frame sent, in order.
        opens: ``(binding, open_record)`` of every stream opened.
        listeners: The binding listeners, by label.
    """

    def __init__(self):
        self.commands = []
        self.frames = []
        self.opens = []
        self.answers = {}
        self.listeners = {}
        self.ready_listeners = []
        self.lost_listeners = []
        self.forward_end_listeners = []
        self.is_running = True
        self.stream_factory = None
        self.started = 0
        self.stopped = 0

    def listen_binding(self, binding, listener):
        self.listeners[binding] = listener

    def forget_binding(self, binding, listener=None):
        held = self.listeners.get(binding)
        if listener is None or held == listener:
            self.listeners.pop(binding, None)

    def on_ready(self, listener):
        self.ready_listeners.append(listener)

    def on_lost(self, listener):
        self.lost_listeners.append(listener)

    def on_forward_end(self, listener):
        self.forward_end_listeners.append(listener)

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def is_ready(self):
        return self.is_running

    def wait_ready(self, timeout_s):
        return self.is_running

    def command(self, command, fields, timeout_s=5):
        from neutrino_client.exceptions import GatewayUnreachable

        if not self.is_running:
            raise GatewayUnreachable("the client's transport is not running")
        self.commands.append((command, dict(fields)))
        answer_of = self.answers.get(command)
        return {} if answer_of is None else dict(answer_of(dict(fields)))

    def send_frame(self, binding, frame, is_last=False):
        from neutrino_client.exceptions import GatewayUnreachable

        if not self.is_running:
            raise GatewayUnreachable("the client's transport is not running")
        self.frames.append((binding, dict(frame)))

    def open_stream(self, binding, open_record, **kwargs):
        self.opens.append((binding, dict(open_record)))
        if self.stream_factory is not None:
            return self.stream_factory(binding, dict(open_record), **kwargs)
        return FakeStreamEnd()

    def deliver(self, binding, line):
        """Hand one event or frame line to a binding's session, as the transport does."""
        self.listeners[binding](dict(line, binding=binding))

    def frames_of(self, frame_type):
        return [
            frame for _binding, frame in self.frames if frame.get("type") == frame_type
        ]

    def commands_of(self, name):
        return [fields for command, fields in self.commands if command == name]


class FakeStreamEnd:
    """A stream the far side accepted, whose bytes and close a test scripts.

    Attributes:
        sent: The bytes sent on it.
        resizes: ``(cols, rows)`` of every resize.
        is_eof_sent: Whether ``send_eof`` was called.
    """

    kind = "shell"

    def __init__(self, pieces=(), close=None, refusal=None):
        import queue as queue_module

        self.sent = []
        self.resizes = []
        self.is_eof_sent = False
        self.is_closed_here = False
        self._pieces = queue_module.Queue()
        for piece in pieces:
            self._pieces.put(piece)
        self._close = dict(close or {})
        self._refusal = refusal
        if refusal is not None:
            self._pieces.put(b"")

    @property
    def is_done(self):
        return self.is_closed_here or self._refusal is not None

    @property
    def is_accepted(self):
        return self._refusal is None

    def wait_accept(self, timeout_s):
        return self._refusal is None

    def end(self, close=None):
        """The far side ends the stream with a close's params."""
        self._close = dict(close or {})
        self._pieces.put(b"")

    def push(self, data):
        self._pieces.put(bytes(data))

    def read(self, timeout_s):
        import queue as queue_module

        try:
            return self._pieces.get(timeout=max(timeout_s, 0.001))
        except queue_module.Empty:
            return None

    def send(self, data):
        from neutrino_client.exceptions import GatewayUnreachable

        if self.is_done:
            raise GatewayUnreachable("ended")
        self.sent.append(bytes(data))

    def send_eof(self):
        self.is_eof_sent = True

    def resize(self, cols, rows):
        from neutrino_client.exceptions import GatewayUnreachable

        if self.is_done:
            raise GatewayUnreachable("ended")
        self.resizes.append((cols, rows))

    def close(self):
        self.is_closed_here = True
        self._pieces.put(b"")

    def refusal(self):
        return dict(self._refusal) if self._refusal else None

    def wait_close(self, timeout_s):
        from neutrino_client.exceptions import GatewayRefusedDetail

        if self._refusal is not None:
            raise GatewayRefusedDetail(
                code=self._refusal["code"], params=dict(self._refusal["params"])
            )
        return dict(self._close)


def echo_server():
    """A real echo server on a loopback port of its own: ``(port, close)``."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def echo(connection) -> None:
        while True:
            try:
                data = connection.recv(4096)
            except OSError:
                break
            if not data:
                break
            connection.sendall(data)
        connection.close()

    def serve() -> None:
        while True:
            try:
                connection, _address = server.accept()
            except OSError:
                return
            threading.Thread(target=echo, args=(connection,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return port, server.close


def round_trip(port: int, payload: bytes) -> bytes:
    """Send bytes to a loopback port and read the same number back."""
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.sendall(payload)
    received = b""
    while len(received) < len(payload):
        chunk = client.recv(65536)
        if not chunk:
            break
        received += chunk
    client.close()
    return received


class FakeProcess:
    """A spawned viewer, remembered instead of run."""

    def __init__(self, argv: list):
        self.argv = argv
        self.returncode = None
        self.is_terminated = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.is_terminated = True
        self.returncode = 0

    def wait(self, timeout=None) -> int:
        return self.returncode if self.returncode is not None else 0

    def kill(self) -> None:
        self.returncode = -9


class FakeResident:
    """The resident the route table and the CLI talk to, scripted."""

    def __init__(self, *, platform=None):
        self.platform = platform if platform is not None else FakeClientPlatform()
        self.connected_links = []
        self.language_value = "en"
        self.theme_value = "dark"
        self.connect_error = None
        self.disconnected = []
        self.service_calls = []
        self.service_reply = {}
        self.service_error = None
        self.shows = 0
        self.shutdowns = 0
        self.is_shut_down = threading.Event()
        self.relaunches = 0
        self.is_bound = True
        self.hubs_value = [dict(HUB_ROW), dict(OFFICE_ROW)]
        self.reconnects = []
        self.refreshes = 0
        self.exits = []
        self.overlay_calls = []
        self.overlay_reply = {}
        self.forward_settings = []
        self.forward_reply = {}
        self.panel_opens = []
        self.panel_reply = {}
        self.clipboard_reply = {"text": "echo pasted\n"}
        self.clipboard_written = []
        self.clipboard_write_reply = {}
        self.notices_value = []
        self.terminal_calls = []
        self.terminal_reply = {"terminal_id": "t1"}
        self.session_reply = {}
        self.typed = []
        self.shown = [b"$ "]
        # The loopback port each forwarded entry listens on, by service key.
        self.forward_ports = {"h1/svc_tcp": 5432}
        self.states = {
            "mounts": [
                {
                    "record_id": "r1",
                    "hub_id": "h1",
                    "entry_id": "share_media",
                    "path": "/home/alice/nas/media",
                    "username": "alice",
                    "is_attached": True,
                    "state": "mounted",
                    "code": "",
                    "params": {},
                }
            ],
            "ai": {
                "is_enabled": True,
                "is_active": True,
                "state": "installed",
                "code": "",
                "params": {},
            },
            "ai_tool_configs": {"claude": {"default": "m1"}},
            "viewers": {},
        }

    def hostname(self) -> str:
        return "box"

    def language(self) -> str:
        return self.language_value

    def set_language(self, language: str) -> None:
        self.language_value = language

    def theme(self) -> str:
        return self.theme_value

    def set_theme(self, theme: str) -> None:
        self.theme_value = theme

    def terminal_font_size(self) -> int:
        return self.__dict__.get("font_size", 13)

    def set_terminal_font_size(self, size: int) -> None:
        self.font_size = size

    def platform_tuple(self) -> dict:
        return {"os": "linux", "family": "debian", "arch": "amd64"}

    def home(self) -> str:
        return "/home/alice"

    def mount_location_shape(self) -> str:
        return "path"

    def suggest_mount_location(self) -> str:
        return ""

    def mount_location_choices(self) -> list:
        return []

    def is_connected(self) -> bool:
        return self.is_bound

    def exit_hub_id(self) -> str:
        for hub in self.hubs():
            if hub.get("is_exit"):
                return hub["hub_id"]
        return ""

    def hubs(self) -> list:
        return json.loads(json.dumps(self.hubs_value)) if self.is_bound else []

    def service_entries(self) -> list:
        return json.loads(json.dumps(SERVICES)) if self.is_bound else []

    def entry_rows(self) -> list:
        return [
            dict(
                entry,
                job="",
                last_error=None,
                local_port="auto",
                forward=self.forward_ports.get(f"{entry['hub_id']}/{entry['id']}"),
            )
            for entry in self.service_entries()
        ]

    def notices(self) -> list:
        return [dict(notice) for notice in self.notices_value]

    def close_notice(self, notice_id: str) -> None:
        self.notices_value = [
            notice for notice in self.notices_value if notice.get("id") != notice_id
        ]

    def service_states(self) -> dict:
        return json.loads(json.dumps(self.states))

    def terminal_entries(self) -> list:
        return json.loads(json.dumps(TERMINALS)) if self.is_bound else []

    def terminal_sessions(self) -> list:
        return json.loads(json.dumps(TERMINAL_SESSIONS)) if self.is_bound else []

    def connect_overlay(self, hub_id: str) -> dict:
        self.overlay_calls.append(("connect", hub_id))
        return dict(self.overlay_reply)

    def cancel_overlay(self, hub_id: str) -> dict:
        self.overlay_calls.append(("cancel", hub_id))
        return dict(self.overlay_reply)

    def disconnect_overlay(self, hub_id: str) -> dict:
        self.overlay_calls.append(("disconnect", hub_id))
        return dict(self.overlay_reply)

    def read_clipboard(self) -> dict:
        return dict(self.clipboard_reply)

    def write_clipboard(self, text: str) -> dict:
        self.clipboard_written.append(text)
        return dict(self.clipboard_write_reply)

    def pick_overlay(self, hub_id: str, provider: str) -> dict:
        self.overlay_calls.append(("pick", hub_id, provider))
        return dict(self.overlay_reply)

    def open_terminal(
        self,
        hub_id: str,
        device_id: str,
        cols: int,
        rows: int,
        session_id="",
        is_shared=False,
        account="",
    ):
        call = ("open", hub_id, device_id, cols, rows)
        call += (session_id,) if session_id else ()
        call += ("shared",) if is_shared else ()
        call += (("account", account),) if account else ()
        self.terminal_calls.append(call)
        return dict(self.terminal_reply)

    def open_exec(
        self,
        hub_id: str,
        device_id: str,
        argv: list,
        is_tty: bool,
        cols,
        rows,
        account="",
    ):
        call = ("exec", hub_id, device_id, list(argv), is_tty, cols, rows)
        call += (("account", account),) if account else ()
        self.terminal_calls.append(call)
        return dict(self.terminal_reply)

    def attach_terminal(self, terminal_id: str, read) -> None:
        self.terminal_calls.append(("attach", terminal_id))
        while True:
            data = read(4096)
            if not data:
                return
            self.typed.append(data)

    def terminal_output(self, terminal_id: str, write) -> None:
        self.terminal_calls.append(("output", terminal_id))
        for data in self.shown:
            write(data)

    def has_terminal(self, terminal_id: str) -> bool:
        return terminal_id == self.terminal_reply.get("terminal_id")

    def resize_terminal(self, terminal_id: str, cols: int, rows: int) -> dict:
        self.terminal_calls.append(("resize", terminal_id, cols, rows))
        return {}

    def terminal_result(self, terminal_id: str) -> dict:
        self.terminal_calls.append(("result", terminal_id))
        return {"exit_code": 0}

    def open_window_terminal(
        self,
        hub_id: str,
        device_id: str,
        cols: int,
        rows: int,
        session_id="",
        account="",
    ):
        call = ("window", hub_id, device_id, cols, rows)
        call += (session_id,) if session_id else ()
        call += (("account", account),) if account else ()
        self.terminal_calls.append(call)
        return dict(self.terminal_reply)

    def persist_terminal(
        self, terminal_id: str, is_persistent=None, is_shared=None
    ) -> dict:
        self.terminal_calls.append(("persist", terminal_id, is_persistent, is_shared))
        return dict(self.session_reply)

    def persist_terminal_session(
        self, hub_id: str, session_id: str, is_persistent=None, is_shared=None
    ) -> dict:
        self.terminal_calls.append(
            ("persist_session", hub_id, session_id, is_persistent, is_shared)
        )
        return dict(self.session_reply)

    def stop_terminal_session(self, hub_id: str, session_id: str) -> dict:
        self.terminal_calls.append(("stop", hub_id, session_id))
        return dict(self.session_reply)

    def terminal_input(self, terminal_id: str, data: bytes) -> dict:
        if not self.has_terminal(terminal_id):
            return {"code": "unknown_terminal", "params": {}}
        self.typed.append(data)
        return {}

    def clear_terminal(self, terminal_id: str) -> dict:
        self.terminal_calls.append(("clear", terminal_id))
        if not self.has_terminal(terminal_id):
            return {"code": "unknown_terminal", "params": {}}
        return {}

    def open_panel(self, hub_id: str) -> dict:
        self.panel_opens.append(hub_id)
        return dict(self.panel_reply)

    def close_terminal(self, terminal_id: str) -> dict:
        self.terminal_calls.append(("close", terminal_id))
        if not self.has_terminal(terminal_id):
            return {"code": "unknown_terminal", "params": {}}
        return {}

    def list_directories(self, path: str) -> list:
        return self.platform.list_directories(path=path)

    def make_directory(self, path: str) -> None:
        self.platform.make_directory(path=path)

    def connect(self, link: str) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected_links.append(link)
        self.is_bound = True

    def leave(self, hub_id: str = "") -> None:
        hub = self._hub(hub_id)
        self.disconnected.append(hub["hub_id"])
        self.hubs_value = [row for row in self.hubs_value if row is not hub]
        self.is_bound = bool(self.hubs_value)

    def reconnect(self, hub_id: str = "") -> None:
        hub = self._hub(hub_id)
        self.reconnects.append(hub_id)
        hub["connection"] = "connecting"

    def refresh(self) -> None:
        self.refreshes += 1

    def set_exit(self, hub_id: str) -> dict:
        rows = self.hubs_value if self.is_bound else []
        chosen = [row for row in rows if hub_id in (row["hub_id"], row["binding_id"])]
        if not chosen:
            return {"code": "unknown_hub", "params": {"hub_id": hub_id}}
        if chosen[0]["connection"] != "connected":
            return {"code": "no_exit_hub", "params": {"hub_id": hub_id}}
        self.exits.append(chosen[0]["hub_id"])
        for row in rows:
            row["is_exit"] = row is chosen[0]
        return {}

    def request_show(self) -> None:
        self.shows += 1

    def shutdown(self) -> None:
        self.shutdowns += 1
        self.is_shut_down.set()

    def arrange_relaunch(self) -> None:
        self.relaunches += 1

    def subscribe(self, watcher) -> None:
        self.__dict__.setdefault("watchers", []).append(watcher)

    def is_ssh_include_enabled(self) -> bool:
        return self.__dict__.get("ssh_include", False)

    def ssh_config(self) -> dict:
        return {"path": "/home/alice/.ssh/neutrino_config", "text": "Host lab.nt\n"}

    def apply_settings(self, body: dict) -> dict:
        self.__dict__.setdefault("settings_calls", []).append(dict(body))
        reply = self.__dict__.get("settings_reply", {})
        if reply:
            return dict(reply)
        if "language" in body:
            self.language_value = body["language"]
        if "theme" in body:
            self.theme_value = body["theme"]
        if "is_ssh_include_enabled" in body:
            self.ssh_include = body["is_ssh_include_enabled"]
        return {}

    def app_rows(self) -> list:
        return list(self.__dict__.get("apps_value", []))

    def open_app(self, hub_id: str, app_id: str) -> dict:
        self.__dict__.setdefault("app_calls", []).append(("use", hub_id, app_id))
        return dict(self.forward_reply)

    def open_app_page(self, hub_id: str, app_id: str) -> dict:
        self.__dict__.setdefault("app_calls", []).append(("open", hub_id, app_id))
        return dict(self.forward_reply)

    def stop_app(self, hub_id: str, app_id: str) -> dict:
        self.__dict__.setdefault("app_calls", []).append(("stop", hub_id, app_id))
        return dict(self.forward_reply)

    def configure_app(self, hub_id: str, app_id: str, ports: dict) -> dict:
        self.forward_settings.append((hub_id, app_id, dict(ports)))
        return dict(self.forward_reply)

    def open_ssh_proxy(self, hub_id: str, entry_id: str) -> dict:
        self.terminal_calls.append(("ssh_proxy", hub_id, entry_id))
        return dict(self.terminal_reply)

    def service_action(self, service_type: str, body: dict) -> dict:
        self.service_calls.append((service_type, dict(body)))
        if self.service_error is not None:
            raise self.service_error
        return dict(self.service_reply)

    def _hub(self, needle: str) -> dict:
        """The hub row a needle names, the way the resident resolves one."""
        rows = self.hubs_value if self.is_bound else []
        if not needle:
            if len(rows) == 1:
                return rows[0]
            raise KeyError(needle)
        for hub in rows:
            if needle in (hub["hub_id"], hub["binding_id"]):
                return hub
        raise KeyError(needle)


def completed(command=(), returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        list(command), returncode, stdout=stdout, stderr=stderr
    )
