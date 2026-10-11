"""CloudCLI's hooks: Node.js, each account's install, the service, the login.

What these pin: a tarball or a zip with one Node.js directory lands whole
under the module's root, read-only, replacing the one before, and an
archive that is not one is ``cloudcli_node_download_failed``; npm runs as
the account with its cache inside the app directory and an empty file as
the account's configuration, as a transient service that may take
``OOMPolicy=stop`` on Linux and as the account's own process on a Mac, and a
failure names its step; on Windows an install runs as a task left running,
the account reads installing with the install's log meanwhile, and an
ended task is judged by its result and the app directory; each instance's
service runs Node.js with the account's server script from an environment
written from scratch whose ``PATH`` lists Node's directory, the account's
usual command directories and the system's and names no gateway, root-only
on every system; the record keeps the loopback port and the database across
applies; and the forwarder, driven against a fake CloudCLI, registers the
administrator on the first start, refuses an administrator with another
password once and asks to start afresh, never passes the register and login
routes on, trades a token for CloudCLI's login kept in the browser and the
cookie, passes a login CloudCLI issued on with its body and a WebSocket
both ways, and answers 401 to a request with neither.
"""

import base64
import hashlib
import hmac
import io
import json
import ntpath
import os
import socket
import socketserver
import stat
import tarfile
import threading
import time
import zipfile

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli import hooks as hooks_module
from neutrino_agent.modules.cloudcli.config import CloudcliConfig, jwt_secret
from neutrino_agent.modules.cloudcli.hooks import (
    FINISH_INSTALL_SCRIPT,
    INSTALL_SCRIPT,
    INSTALL_STATUS_SCRIPT,
    NATIVE_CHECK_EXIT,
    CloudcliHooks,
    cookie_name,
    is_login_valid,
    node_dir,
    node_path,
    npm_arguments,
    npm_environment,
    npm_failure,
    service_environment,
    unpack_node,
)
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.http_forward import InstanceForwarder, mint_token
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform

SECRET = "instance-secret"  # scan: allow
PASSWORD = "hub-password-1"  # scan: allow
NOW = 1_800_000_000
NODE = "node-v22.23.3-linux-x64"
INSTANCE = {
    "account": "ann",
    "port": 3001,
    "web_password": PASSWORD,
    "token_secret": SECRET,
    "password": "login-pw",
}
CONFIG = CloudcliConfig.from_dict(
    {
        "npm_registry": "https://registry.npmmirror.com",
        "npm_environment": {"npm_config_better_sqlite3_binary_host": "https://m/bs3"},
        "instances": [INSTANCE],
    }
)
ANN = AccountEntry(1000, 1000, "/home/ann", "/bin/bash")


class Platform(AgentPlatform):
    def __init__(self, os_name="linux"):
        self.os_name = os_name


def tarball(path, top=NODE, extra=()):
    with tarfile.open(path, "w:gz") as archive:
        for name, data in [(f"{top}/bin/node", b"#!node"), *extra]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo(f"{top}/bin/npm")
        link.type = tarfile.SYMTYPE
        link.linkname = "../lib/node_modules/npm/bin/npm-cli.js"
        archive.addfile(link)
    return str(path)


def land_package(app: str) -> None:
    package = os.path.join(app, "node_modules", "@cloudcli-ai", "cloudcli")
    os.makedirs(package, exist_ok=True)
    with open(os.path.join(package, "package.json"), "w", encoding="utf-8") as stream:
        stream.write('{"version": "1.37.3"}')


def hooks_for(os_name, module_dir, **kwargs) -> CloudcliHooks:
    tools = {key: kwargs.pop(key) for key in ("run", "powershell") if key in kwargs}
    hooks = CloudcliHooks(platform=Platform(os_name), log=lambda line: None, **kwargs)
    join = ntpath.join if os_name == "windows" else os.path.join
    machine = ServiceMachine(
        os_name=os_name,
        module_dir=module_dir,
        record_dir=join(os.path.dirname(module_dir), "config", "cloudcli"),
        lookup_account=lambda account: ANN,
        **tools,
    )
    hooks.bind(machine, None)
    return hooks


def with_node(tmp_path, os_name="linux", directory=NODE) -> str:
    module_dir = tmp_path / "state" / "cloudcli"
    if os_name == "windows":
        (module_dir / directory).mkdir(parents=True)
        (module_dir / directory / "node.exe").write_text("")
    else:
        (module_dir / directory / "bin").mkdir(parents=True)
        (module_dir / directory / "bin" / "node").write_text("")
    return str(module_dir)


# --- Node.js ---


def test_a_tarball_lands_whole_and_read_only(tmp_path):
    root = tmp_path / "cloudcli"

    directory = unpack_node(
        tarball(tmp_path / "node.tar.gz"), package_kind="tar", root=str(root)
    )

    assert directory == str(root / NODE)
    assert node_dir(str(root)) == directory
    node = node_path(directory, "linux")
    assert open(node, "rb").read() == b"#!node"
    assert stat.S_IMODE(os.stat(node).st_mode) & 0o222 == 0
    assert os.readlink(os.path.join(directory, "bin", "npm")).endswith("npm-cli.js")


def test_a_new_node_replaces_the_one_before_through_the_hooks(tmp_path):
    hooks = hooks_for("linux", str(tmp_path / "cloudcli"))
    assert hooks.verify() is False

    hooks.install(tarball(tmp_path / "a.tar.gz"), "tar")
    hooks.install(tarball(tmp_path / "b.tar.gz", top="node-v22.24.0-linux-x64"), "tar")

    assert os.listdir(tmp_path / "cloudcli") == ["node-v22.24.0-linux-x64"]
    assert hooks.verify() is True
    assert hooks.node.endswith("node-v22.24.0-linux-x64/bin/node")


def test_a_zip_lands_the_same(tmp_path):
    path = tmp_path / "node.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("node-v22.23.3-win-x64/node.exe", b"MZ")

    directory = unpack_node(
        str(path), package_kind="zip", root=str(tmp_path / "cloudcli")
    )

    assert os.path.isfile(os.path.join(directory, "node.exe"))


@pytest.mark.parametrize("kind", ["tar", "zip", "msi"])
def test_an_archive_that_is_not_one_is_a_failed_node_download(tmp_path, kind):
    path = tmp_path / "junk"
    path.write_bytes(b"<html>")

    with pytest.raises(ModuleApplyError) as caught:
        unpack_node(str(path), package_kind=kind, root=str(tmp_path / "c"))

    assert caught.value.code == "cloudcli_node_download_failed"


def test_an_archive_without_one_node_directory_or_outside_itself_is_refused(tmp_path):
    with pytest.raises(ModuleApplyError) as caught:
        unpack_node(
            tarball(tmp_path / "x.tar.gz", top="something"),
            package_kind="tar",
            root=str(tmp_path / "c"),
        )
    assert caught.value.code == "cloudcli_node_download_failed"

    with pytest.raises(ModuleApplyError):
        unpack_node(
            tarball(tmp_path / "y.tar.gz", extra=[("../escape", b"x")]),
            package_kind="tar",
            root=str(tmp_path / "d"),
        )
    assert not (tmp_path / "escape").exists()


# --- npm ---


def test_npm_keeps_to_the_app_directory_and_the_registry_the_state_names():
    app = "/home/ann/.local/share/neutrino/agent/cloudcli/app"

    named = npm_environment(app, registry="https://registry.npmmirror.com")

    assert named["npm_config_registry"] == "https://registry.npmmirror.com"
    assert "npm_config_registry" not in npm_environment(app)
    assert named["npm_config_cache"] == app + "/.npm"
    assert named["npm_config_userconfig"] == app + "/.npmrc"
    assert npm_arguments(app) == [
        "install",
        "@cloudcli-ai/cloudcli@1.37.3",
        "--prefix",
        app,
    ]
    held = npm_environment(
        app, extra={"npm_config_x": "y", "npm_config_cache": "/elsewhere"}
    )
    assert held["npm_config_x"] == "y" and held["npm_config_cache"] == app + "/.npm"


@pytest.mark.parametrize(
    "output, expected",
    [
        (
            "prebuild-install warn install No prebuilt binaries found\n"
            "gyp ERR! build error\nnpm error path .../node_modules/node-pty",
            (
                "cloudcli_native_module_failed",
                {
                    "account": "ann",
                    "module": "node-pty",
                    "detail": "prebuild-install warn install No prebuilt binaries "
                    "found | gyp ERR! build error | npm error path "
                    ".../node_modules/node-pty",
                },
            ),
        ),
        (
            "npm error code ETIMEDOUT\nnpm error network request failed",
            (
                "cloudcli_npm_install_failed",
                {
                    "account": "ann",
                    "detail": "npm error code ETIMEDOUT | npm error network "
                    "request failed",
                },
            ),
        ),
        (
            "just one line",
            (
                "cloudcli_npm_install_failed",
                {"account": "ann", "detail": "just one line"},
            ),
        ),
    ],
)
def test_a_failed_install_names_its_step(output, expected):
    failure = npm_failure(output, "ann")

    assert (failure.code, failure.params) == expected


# --- the install on Linux ---


class Machine:
    """systemctl, systemd-run and runuser, recorded; answers set per command."""

    def __init__(self):
        self.calls: list = []
        self.npm_exit = 0
        self.npm_output = ""
        self.check_exit = 0
        self.check_output = ""
        self.unit_result = "success"
        self.installing_seen: list = []
        self.hooks = None

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[:2] == ["systemctl", "show"]:
            return CommandResult(list(command), 0, self.unit_result + "\n", "")
        if command[0] == "systemd-run":
            self.installing_seen.append(self.hooks.installing)
            if self.npm_exit == 0:
                land_package(command[command.index("--prefix") + 1])
            return CommandResult(list(command), self.npm_exit, self.npm_output, "")
        if "-e" in command:
            return CommandResult(list(command), self.check_exit, self.check_output, "")
        return CommandResult(list(command), 0, "", "")

    def install_call(self):
        return next(call for call in self.calls if call[0] == "systemd-run")


@pytest.fixture
def linux(tmp_path):
    machine = Machine()
    hooks = hooks_for("linux", with_node(tmp_path), run=machine)
    machine.hooks = hooks
    home = str(tmp_path / "home" / "ann")
    return hooks, machine, AccountEntry(1000, 1000, home, "/bin/bash")


def test_an_install_runs_npm_as_the_account_in_a_transient_service(linux, tmp_path):
    hooks, machine, entry = linux

    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    started = machine.install_call()
    assert started[: started.index("--")] == [
        "systemd-run",
        "--unit=neutrino_cloudcli_install_ann.service",
        "--quiet",
        "--wait",
        "--pipe",
        "-p",
        "OOMPolicy=stop",
    ]
    install = started[started.index("--") + 1 :]
    app = os.path.join(
        entry.home, ".local", "share", "neutrino", "agent", "cloudcli", "app"
    )
    assert install[:6] == ["runuser", "-u", "ann", "--", "env", "-i"]
    assert f"npm_config_cache={app}/.npm" in install
    assert f"npm_config_userconfig={app}/.npmrc" in install
    assert "npm_config_registry=https://registry.npmmirror.com" in install
    assert "npm_config_better_sqlite3_binary_host=https://m/bs3" in install
    assert f"HOME={entry.home}" in install
    assert install[-4:] == ["install", "@cloudcli-ai/cloudcli@1.37.3", "--prefix", app]
    assert 'rm -rf "$0/node_modules"' in install[install.index("sh") + 2]
    assert machine.installing_seen == [frozenset({"ann"})]
    assert hooks.installing == frozenset()
    assert notes == ["installed CloudCLI for ann"]
    assert hooks.prepare(CONFIG, CONFIG.instances[0], entry) == []


def test_a_failed_npm_install_names_its_step_and_reads_installing_no_more(linux):
    hooks, machine, entry = linux
    machine.npm_exit = 1
    machine.npm_output = "npm error code ECONNRESET"

    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert caught.value.code == "cloudcli_npm_install_failed"
    assert hooks.installing == frozenset()


def test_a_native_module_without_its_binary_names_it(linux):
    hooks, machine, entry = linux
    machine.check_exit = NATIVE_CHECK_EXIT
    machine.check_output = "better-sqlite3\n"

    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert (caught.value.code, caught.value.params["module"]) == (
        "cloudcli_native_module_failed",
        "better-sqlite3",
    )


def test_an_install_the_kernel_killed_for_memory_is_its_own_refusal(linux):
    hooks, machine, entry = linux
    machine.npm_exit = 137
    machine.unit_result = "oom-kill"

    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert (caught.value.code, caught.value.params) == (
        "cloudcli_install_out_of_memory",
        {"account": "ann"},
    )
    assert [
        "systemctl",
        "reset-failed",
        "neutrino_cloudcli_install_ann.service",
    ] in machine.calls


# --- the install on a Mac ---


def test_a_mac_install_runs_npm_as_the_account(tmp_path):
    calls = []

    def run_as(entry, command, *, environment, timeout_s):
        calls.append((entry, list(command), dict(environment), timeout_s))
        if "install" in command:
            land_package(command[command.index("--prefix") + 1])
        return CommandResult(list(command), 0, "", "")

    hooks = hooks_for(
        "darwin", with_node(tmp_path, directory="node-v22-darwin"), run_as=run_as
    )
    entry = AccountEntry(501, 20, str(tmp_path / "Users" / "ann"), "/bin/zsh")

    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    install, check = calls
    assert install[0] is entry
    assert install[1][-4:-1] == ["install", "@cloudcli-ai/cloudcli@1.37.3", "--prefix"]
    assert install[2]["PATH"].endswith(
        "node-v22-darwin/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    )
    assert install[2]["npm_config_userconfig"].endswith("cloudcli/app/.npmrc")
    assert install[3] == 1800
    assert "createRequire" in check[1][-1]
    assert notes == ["installed CloudCLI for ann"]


# --- the install on Windows ---


class PowerShell:
    def __init__(self):
        self.calls: list = []
        self.answers: dict = {}
        self.install_tasks: list = []

    def __call__(self, script, document, timeout_s=120):
        self.calls.append((script, document))
        if script == INSTALL_STATUS_SCRIPT:
            return {"tasks": list(self.install_tasks)}
        answer = self.answers.get(script, {})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def scripts(self) -> list:
        return [script for script, _document in self.calls]


def install_task(state, last_result=0):
    return {
        "name": "neutrino_cloudcli_install_ann",
        "state": state,
        "last_result": last_result,
    }


@pytest.fixture
def ready(monkeypatch):
    """Whether the app directory holds CloudCLI and its native modules."""
    held = {"is_ready": False}
    monkeypatch.setattr(hooks_module, "is_app_ready", lambda app: held["is_ready"])
    return held


@pytest.fixture
def windows(tmp_path, ready):
    powershell = PowerShell()
    hooks = hooks_for(
        "windows",
        with_node(tmp_path, "windows", "node-v22.23.3-win-x64"),
        powershell=powershell,
    )
    return hooks, powershell, AccountEntry(0, 0, "C:\\Users\\ann", "")


def test_an_install_is_started_as_a_task_and_left_to_run(windows):
    hooks, powershell, entry = windows

    hooks.prepare_module()
    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert notes == []
    assert powershell.scripts() == [INSTALL_STATUS_SCRIPT, INSTALL_SCRIPT]
    _script, document = powershell.calls[1]
    assert document["account"] == "ann"
    assert document["password"] == "login-pw"
    assert document["task"] == "neutrino_cloudcli_install_ann"
    assert "@cloudcli-ai/cloudcli@1.37.3" in document["script_text"]
    assert 'set "npm_config_registry=https://registry.npmmirror.com"' in (
        document["script_text"]
    )
    assert document["timeout_s"] > 1800
    assert "Start-ScheduledTask" in INSTALL_SCRIPT
    assert "Unregister-ScheduledTask" not in INSTALL_SCRIPT
    assert hooks.installing == frozenset({"ann"})
    assert hooks.install_log("ann").endswith("cloudcli\\run\\install_ann.log")
    assert hooks.install_log("bob") == ""


@pytest.mark.parametrize("state", ["Running", "Queued"])
def test_a_running_install_starts_nothing_and_keeps_waiting(windows, state):
    hooks, powershell, entry = windows
    powershell.install_tasks = [install_task(state, 0x41301)]

    hooks.prepare_module()
    hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert powershell.scripts() == [INSTALL_STATUS_SCRIPT]
    assert hooks.installing == frozenset({"ann"})


def test_an_ended_install_is_unregistered_and_judged(windows, ready):
    hooks, powershell, entry = windows
    powershell.install_tasks = [install_task("Ready", 0)]
    ready["is_ready"] = True

    hooks.prepare_module()
    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert powershell.scripts() == [INSTALL_STATUS_SCRIPT, FINISH_INSTALL_SCRIPT]
    assert powershell.calls[1][1]["task"] == "neutrino_cloudcli_install_ann"
    assert notes == ["installed CloudCLI for ann"]
    assert hooks.installing == frozenset()


def test_an_app_already_there_starts_no_install(windows, ready):
    hooks, powershell, entry = windows
    ready["is_ready"] = True

    hooks.prepare_module()

    assert hooks.prepare(CONFIG, CONFIG.instances[0], entry) == []
    assert powershell.scripts() == [INSTALL_STATUS_SCRIPT]


@pytest.mark.parametrize(
    "result, output, expected",
    [
        (
            NATIVE_CHECK_EXIT,
            "npm ok\nnode-pty\n",
            (
                "cloudcli_native_module_failed",
                {"account": "ann", "module": "node-pty", "detail": "node-pty"},
            ),
        ),
        (
            1,
            "npm error network",
            (
                "cloudcli_npm_install_failed",
                {"account": "ann", "detail": "npm error network"},
            ),
        ),
        (0, "", ("cloudcli_npm_install_failed", {"account": "ann", "detail": ""})),
        (0x8007052E, "", ("credential_invalid", {"account": "ann"})),
    ],
)
def test_a_failed_windows_install_names_its_step(windows, result, output, expected):
    hooks, powershell, entry = windows
    powershell.install_tasks = [install_task("Ready", result)]
    powershell.answers[FINISH_INSTALL_SCRIPT] = {"output": output}

    hooks.prepare_module()
    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert (caught.value.code, caught.value.params) == expected


def test_a_refused_login_is_credential_invalid(windows):
    hooks, powershell, entry = windows
    powershell.answers[INSTALL_SCRIPT] = ModuleApplyError(
        "credential_invalid", {"account": "ann"}
    )

    hooks.prepare_module()
    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert caught.value.code == "credential_invalid"


# --- the record and the service ---


def test_the_record_keeps_the_loopback_port_and_the_database_across_applies(tmp_path):
    ports = iter([41000, 41001])
    hooks = hooks_for("linux", with_node(tmp_path), pick_port=lambda: next(ports))
    instance = CONFIG.instances[0]

    first = hooks.record(CONFIG, instance, {})
    again = hooks.record(CONFIG, instance, first)
    fresh = hooks.record(CONFIG, instance, dict(first, database="auth-x.db"))

    assert first == {
        "account": "ann",
        "port": 3001,
        "upstream_port": 41000,
        "web_password": PASSWORD,
        "token_secret": SECRET,
        "database": "auth.db",
    }
    assert again == first
    assert fresh["database"] == "auth-x.db" and fresh["upstream_port"] == 41000
    assert CloudcliHooks.forwarder_fields == (
        "account",
        "port",
        "upstream_port",
        "web_password",
        "token_secret",
    )


def test_the_service_runs_node_with_the_server_script_from_a_root_only_environment(
    tmp_path,
):
    hooks = hooks_for("linux", with_node(tmp_path))
    record = {"upstream_port": 41234, "database": "auth-20261006T120000Z.db"}

    service = hooks.service(CONFIG.instances[0], ANN, record)

    assert service.command == (hooks.node, "${CLOUDCLI_SERVER}")
    assert service.environment["SERVER_PORT"] == "41234"
    assert service.environment["DATABASE_PATH"].endswith(
        "/cloudcli/auth-20261006T120000Z.db"
    )
    assert service.environment["CLOUDCLI_SERVER"].endswith(
        "/cloudcli/app/node_modules/@cloudcli-ai/cloudcli/dist-server/server/index.js"
    )
    assert service.is_environment_secret is True
    assert service.working_directory == "~"
    assert not [name for name in service.environment if "ANTHROPIC" in name]
    assert (
        hooks_for("darwin", with_node(tmp_path, "darwin", "n"))
        .service(CONFIG.instances[0], ANN, record)
        .command[1]
        .endswith("index.js")
    )


def test_an_environment_is_written_from_scratch_naming_no_gateway():
    config = CloudcliConfig.from_dict(
        {
            "gateway_url": "http://10.0.0.1:8317",
            "gateway_key": "k",
            "instances": [{"account": "ann", "port": 3001, "token_secret": "s"}],
        }
    )

    linux = service_environment(
        config.instances[0],
        upstream_port=41234,
        home="/home/ann",
        os_name="linux",
        node_dir="/var/lib/neutrino/agent/cloudcli/n/bin",
    )
    mac = service_environment(
        config.instances[0],
        upstream_port=41234,
        home="/Users/ann",
        os_name="darwin",
        node_dir="/Library/Application Support/Neutrino/agent/state/cloudcli/n/bin",
    )
    windows = service_environment(
        config.instances[0],
        upstream_port=41234,
        home="C:\\Users\\ann",
        os_name="windows",
        node_dir="C:\\ProgramData\\Neutrino\\agent\\state\\cloudcli\\n",
        join=ntpath.join,
    )

    assert linux == {
        "HOST": "127.0.0.1",
        "SERVER_PORT": "41234",
        "JWT_SECRET": jwt_secret("s"),
        "DATABASE_PATH": "/home/ann/.local/share/neutrino/agent/cloudcli/auth.db",
        "HOME": "/home/ann",
        "PATH": "/var/lib/neutrino/agent/cloudcli/n/bin:/home/ann/.local/bin:"
        "/home/ann/bin:/usr/local/bin:/usr/bin:/bin",
    }
    assert mac["PATH"].split(":")[3:] == [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    assert windows["PATH"] == (
        "C:\\ProgramData\\Neutrino\\agent\\state\\cloudcli\\n;%APPDATA%\\npm;%PATH%"
    )
    assert "HOME" not in windows


# --- the login ---


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_login(secret: str, *, expiry: int, user: str = "ann") -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"userId": 1, "username": user, "exp": expiry}).encode())
    signature = hmac.new(
        secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{_b64(signature)}"


def test_a_login_verifies_only_under_its_secret_and_before_its_expiry():
    secret = jwt_secret(SECRET)

    assert is_login_valid(make_login(secret, expiry=NOW + 60), secret, NOW) is True
    assert is_login_valid(make_login(secret, expiry=NOW - 1), secret, NOW) is False
    assert is_login_valid(make_login("other", expiry=NOW + 60), secret, NOW) is False
    assert is_login_valid("a.b", secret, NOW) is False
    assert is_login_valid("x.y.z", secret, NOW) is False


# --- the forwarder, against a fake CloudCLI on loopback ---


class FakeCloudcli(socketserver.ThreadingTCPServer):
    """CloudCLI's auth routes, an echo of every other request, and a WebSocket echo."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *, is_set_up=False):
        self.users: dict = {}
        self.requests: list = []
        if is_set_up:
            self.users["ann"] = PASSWORD
        super().__init__(("127.0.0.1", 0), FakeCloudcliConnection)
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self):
        self.shutdown()
        self.server_close()


class FakeCloudcliConnection(socketserver.BaseRequestHandler):
    def handle(self):
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = self.request.recv(65536)
            if not chunk:
                return
            received += chunk
        head, _, body = received.partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        method, target, _version = lines[0].split(" ")
        headers = dict(
            (name.strip().lower(), value.strip())
            for name, _, value in (line.partition(":") for line in lines[1:])
        )
        length = int(headers.get("content-length", 0) or 0)
        while len(body) < length:
            body += self.request.recv(65536)
        server = self.server
        server.requests.append((method, target, headers, body))
        if headers.get("upgrade", "").lower() == "websocket":
            self.request.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
            )
            while True:
                data = self.request.recv(65536)
                if not data:
                    return
                self.request.sendall(data.upper())
        if target == "/api/auth/status":
            self._json(200, {"needsSetup": not server.users, "isAuthenticated": False})
        elif target == "/api/auth/register":
            sent = json.loads(body)
            if server.users:
                self._json(403, {"error": "User already exists"})
            else:
                server.users[sent["username"]] = sent["password"]
                self._json(200, {"success": True, "token": "x"})
        elif target == "/api/auth/login":
            sent = json.loads(body)
            if server.users.get(sent["username"]) == sent["password"]:
                login = make_login(jwt_secret(SECRET), expiry=int(time.time()) + 3600)
                self._json(200, {"success": True, "token": login})
            else:
                self._json(401, {"error": "Invalid username or password"})
        else:
            self._json(200, {"echo": target, "body": body.decode()})

    def _json(self, status, document):
        body = json.dumps(document).encode()
        self.request.sendall(
            f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
        )


@pytest.fixture
def cloudcli():
    server = FakeCloudcli()
    yield server
    server.stop()


def record_for(upstream_port, *, account="ann", port=0):
    return {
        "account": account,
        "port": port,
        "upstream_port": upstream_port,
        "web_password": PASSWORD,
        "token_secret": SECRET,
        "database": "auth.db",
    }


def forwarding_hooks(tmp_path, reapply=None) -> CloudcliHooks:
    hooks = hooks_for("linux", str(tmp_path / "cloudcli"))
    hooks.bind(hooks.machine, reapply)
    return hooks


def make_forwarder(hooks, upstream_port, *, account="ann", port=None):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        chosen = port or probe.getsockname()[1]
    return InstanceForwarder(
        name="cloudcli",
        record=record_for(upstream_port, account=account, port=chosen),
        hooks=hooks,
        log=lambda line: None,
        ready_poll_s=0.05,
        retry_s=0.05,
    )


def wait_listening(forwarder, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if forwarder.is_listening:
            return forwarder.listen_address[1]
        time.sleep(0.02)
    raise AssertionError(f"never listened: {forwarder.failure}")


@pytest.fixture
def listening(cloudcli, tmp_path):
    forwarder = make_forwarder(forwarding_hooks(tmp_path), cloudcli.port)
    forwarder.start()
    port = wait_listening(forwarder)
    yield forwarder, port
    forwarder.close()


def ask(port, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(request)
        received = b""
        while True:
            data = client.recv(65536)
            if not data:
                return received
            received += data


def status_of(answer: bytes) -> int:
    return int(answer.split(b" ", 2)[1])


def test_the_administrator_is_registered_on_the_first_start(cloudcli, tmp_path):
    hooks = forwarding_hooks(tmp_path)
    record = record_for(cloudcli.port)

    assert hooks.on_first_start(record) == ""
    assert cloudcli.users == {"ann": PASSWORD}
    assert hooks.on_first_start(record) == ""
    assert cloudcli.users == {"ann": PASSWORD}
    assert hooks.on_first_start(record_for(cloudcli.port, account="al")) != ""


def test_a_short_account_is_registered_under_a_padded_name(cloudcli, tmp_path):
    hooks = forwarding_hooks(tmp_path)

    assert hooks.on_first_start(record_for(cloudcli.port, account="al")) == ""

    assert cloudcli.users == {"al_": PASSWORD}


def test_a_cloudcli_that_does_not_answer_is_an_os_error(tmp_path):
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    holder.close()

    with pytest.raises(OSError):
        forwarding_hooks(tmp_path).on_first_start(record_for(port))


def test_an_administrator_with_another_password_asks_once_to_start_afresh(tmp_path):
    cloudcli = FakeCloudcli(is_set_up=True)
    cloudcli.users["ann"] = "somebody-else"
    asked = []
    hooks = forwarding_hooks(
        tmp_path, reapply=lambda account, **changes: asked.append((account, changes))
    )
    record = record_for(cloudcli.port)
    try:
        assert hooks.on_first_start(record) == "cloudcli_register_failed"
        assert hooks.on_first_start(record) == "cloudcli_register_failed"
        assert len(asked) == 1
        account, changes = asked[0]
        assert account == "ann"
        assert changes["database"].startswith("auth-")
        assert changes["database"].endswith("Z.db")
        cloudcli.users.clear()
        assert hooks.on_first_start(record) == ""
        assert cloudcli.users == {"ann": PASSWORD}
    finally:
        cloudcli.stop()


def test_an_administrator_with_another_password_is_reported_and_never_listens(
    tmp_path,
):
    cloudcli = FakeCloudcli(is_set_up=True)
    cloudcli.users["ann"] = "somebody-else"
    forwarder = make_forwarder(forwarding_hooks(tmp_path), cloudcli.port)
    try:
        forwarder.start()
        deadline = time.monotonic() + 5
        while forwarder.failure[0] == "" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert forwarder.failure == ("cloudcli_register_failed", {"account": "ann"})
        assert forwarder.is_listening is False
    finally:
        forwarder.close()
        cloudcli.stop()


@pytest.mark.parametrize(
    "path",
    ["/api/auth/register", "/api/auth/login", "/API/Auth//Login/", "/api/auth/%6Cogin"],
)
def test_the_register_and_login_routes_are_never_passed_on(listening, cloudcli, path):
    _forwarder, port = listening
    login = make_login(jwt_secret(SECRET), expiry=int(time.time()) + 60)
    seen_before = len(cloudcli.requests)

    answer = ask(
        port,
        f"POST {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {login}\r\n"
        f"Content-Length: 2\r\n\r\n{{}}".encode(),
    )

    assert status_of(answer) == 401
    assert cloudcli.requests[seen_before:] == []


def test_a_request_with_neither_a_token_nor_a_login_is_refused(listening, cloudcli):
    _forwarder, port = listening

    assert status_of(ask(port, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")) == 401
    assert not [request for request in cloudcli.requests if request[1] == "/"]


def test_a_token_is_traded_for_cloudclis_login_kept_in_the_browser(listening):
    _forwarder, port = listening
    token = mint_token(SECRET, expiry=int(time.time()) + 60, nonce=os.urandom(16))

    answer = ask(port, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    again = ask(port, f"GET /?tkn={token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())

    assert status_of(answer) == 200
    head, _, body = answer.partition(b"\r\n\r\n")
    assert b"Content-Type: text/html; charset=utf-8" in head
    assert b"localStorage.setItem(" in body
    assert b'"auth-token"' in body
    assert b"location.replace('/')" in body
    assert f"Set-Cookie: {cookie_name(port)}=".encode() in head
    assert b"HttpOnly" in head
    assert status_of(again) == 401


def test_a_token_that_does_not_verify_is_refused(listening):
    _forwarder, port = listening
    forged = mint_token("other", expiry=int(time.time()) + 60, nonce=os.urandom(16))

    assert (
        status_of(ask(port, f"GET /?tkn={forged} HTTP/1.1\r\nHost: x\r\n\r\n".encode()))
        == 401
    )


def test_a_request_with_cloudclis_login_is_passed_on_with_its_body(listening, cloudcli):
    _forwarder, port = listening
    login = make_login(jwt_secret(SECRET), expiry=int(time.time()) + 60)

    bearer = ask(
        port,
        f"POST /api/x HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {login}\r\n"
        f"Content-Length: 5\r\n\r\nhello".encode(),
    )
    cookie = ask(
        port,
        f"GET /api/y HTTP/1.1\r\nHost: x\r\nCookie: {cookie_name(port)}={login}\r\n\r\n".encode(),
    )
    query = ask(port, f"GET /ws?token={login} HTTP/1.1\r\nHost: x\r\n\r\n".encode())

    assert status_of(bearer) == 200 and b'"body": "hello"' in bearer
    assert status_of(cookie) == 200 and b'"echo": "/api/y"' in cookie
    assert status_of(query) == 200
    assert [
        request[1] for request in cloudcli.requests if request[1].startswith("/api/")
    ][-2:] == ["/api/x", "/api/y"]


def test_a_forged_or_expired_login_is_refused(listening):
    _forwarder, port = listening
    expired = make_login(jwt_secret(SECRET), expiry=int(time.time()) - 1)
    forged = make_login("other", expiry=int(time.time()) + 60)

    for login in (expired, forged):
        answer = ask(
            port,
            f"GET / HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {login}\r\n\r\n".encode(),
        )
        assert status_of(answer) == 401


def test_a_websocket_with_cloudclis_login_is_relayed_both_ways(listening, cloudcli):
    _forwarder, port = listening
    login = make_login(jwt_secret(SECRET), expiry=int(time.time()) + 60)

    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(
            f"GET /ws?token={login} HTTP/1.1\r\nHost: x\r\n"
            "Connection: Upgrade\r\nUpgrade: websocket\r\n\r\n".encode()
        )
        received = b""
        while b"\r\n\r\n" not in received:
            received += client.recv(65536)
        assert received.startswith(b"HTTP/1.1 101")
        client.sendall(b"ping")
        echoed = client.recv(65536)

    assert echoed == b"PING"
