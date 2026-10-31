"""CloudCLI's hooks: Node.js, each account's install, the service, the login.

What these pin: the node artifact, a tarball or a zip with one Node.js
directory, lands through the shared unpack under the module's root,
read-only, replacing the one before, and an older build's directory goes;
the npm artifact's registries are ranked and the first naming the pinned
integrity is used with ``--registry``, each host of an npm setting is set
in turn, a failure runs again on the next registry or host and the last
failure is reported, and no registry naming the integrity is
``download_failed`` naming each registry and why; npm runs as the account
with its cache inside the app directory and an empty file as the account's
configuration, as a transient service that may take ``OOMPolicy=stop`` on
Linux and as the account's own process on a Mac, and a failure names its
step; on Linux an install service left running is waited for and its work
taken, and stopped past the install's time, and a service of the install's
name still loaded or a machine shutting down makes the step wait; on Windows an install runs as a
task left running, the account reads installing with the install's log
meanwhile, an ended task is judged by its result and the app directory and
one a shutdown cut runs again with no failure kept,
the account's batch logon right held from the task's start until then; each
instance's service runs Node.js with the account's server script from an
environment written from scratch whose ``PATH`` lists Node's directory, the
account's usual command directories and the system's and names no gateway,
root-only on every system; the record keeps the loopback port and the
database across applies; and the forwarder, driven against a fake CloudCLI,
registers the administrator on the first start, refuses an administrator
with another password once and asks to start afresh, never passes the
register and login routes on, trades a token for CloudCLI's login kept in
the browser and the cookie, passes a login CloudCLI issued on with its body
and a WebSocket both ways, and answers 401 to a request with neither.
"""

import base64
import functools
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

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.cloudcli import hooks as hooks_module
from neutrino_agent.modules.cloudcli.config import CloudcliConfig, jwt_secret
from neutrino_agent.modules.cloudcli.hooks import (
    NATIVE_CHECK_EXIT,
    CloudcliHooks,
    cookie_name,
    install_output,
    is_app_ready,
    is_login_valid,
    node_dir,
    node_path,
    npm_arguments,
    npm_environment,
    npm_failure,
    render_install_script,
    service_environment,
)
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.http_forward import InstanceForwarder, mint_token
from neutrino_agent.modules.shared.package import unpack_artifact
from neutrino_agent.modules.shared.source_fetch import SourceProbe
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform
from tests.conftest import FakeBatchLogon, RecordingHost

SECRET = "instance-secret"  # scan: allow
PASSWORD = "hub-password-1"  # scan: allow
NOW = 1_800_000_000
NODE = "node-v22.23.3-linux-x64"
COOKIE = "neutrino_0123456789ab"
INSTANCE = {
    "account": "ann",
    "web_password": PASSWORD,
    "token_secret": SECRET,
    "password": "login-pw",
    "local_name": "cloudcli-ann.m.localhost",
    "cookie_name": COOKIE,
}
CONFIG = CloudcliConfig.from_dict({"instances": [INSTANCE]})
INTEGRITY = "sha512-pinned"
REGISTRY = "https://registry.npmmirror.com"
HOST = "https://m/bs3"
HOST_SETTING = "npm_config_better_sqlite3_binary_host"
HOST_FILE = "/v1/file.tar.gz"


class HeldRecipe(dict):
    """A recipe, with the state's source sets that come with it as ``sets``."""

    def __init__(self, recipe: dict, sets: dict):
        super().__init__(recipe)
        self.sets = sets


def npm_sets(registries) -> dict:
    """The state's source sets with an ``npm`` set of these registries."""
    return {
        "npm": {
            "probe": "/npm/latest",
            "sources": list(registries),
            "variables": ["npm_config_registry"],
        }
    }


def recipe(registries=(REGISTRY,), hosts=(HOST,)) -> HeldRecipe:
    """CloudCLI's recipe, its npm artifact naming the ``npm`` set of these registries."""
    return HeldRecipe(
        {
            "runner": "cloudcli",
            "method": "hub",
            "params": {
                "version": "1.37.3",
                "artifacts": [
                    {"name": "node", "kind": "tar_gz", "directory": "node"},
                    {
                        "name": "cloudcli",
                        "kind": "npm",
                        "package": "@cloudcli-ai/cloudcli",
                        "digest": INTEGRITY,
                        "source_set": "npm",
                        "hosts": {HOST_SETTING: list(hosts)} if hosts else {},
                        "hosts_probe": {HOST_SETTING: HOST_FILE} if hosts else {},
                    },
                ],
            },
        },
        npm_sets(registries),
    )


class Probe:
    """Sources answering as set: each registry's integrity and speed, each host's speed."""

    def __init__(self, integrities=None, speeds=None):
        self.integrities = dict(integrities or {})
        self.speeds = dict(speeds or {})
        self.asked: list = []

    def __call__(self, url, *, source="", is_document=False):
        self.asked.append(url)
        source = source or url
        speed = self.speeds.get(source, 1.0)
        if speed is None:
            return SourceProbe(source=source, reason="unreachable", detail="refused")
        integrity = self.integrities.get(source, INTEGRITY)
        body = json.dumps(
            {"versions": {"1.37.3": {"dist": {"integrity": integrity}}}}
        ).encode()
        return SourceProbe(source=source, is_answered=True, speed=speed, body=body)


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


def land_package(app: str, *, is_finished: bool = True) -> None:
    """Write the app directory as npm leaves it; unfinished holds no lockfile."""
    package = os.path.join(app, "node_modules", "@cloudcli-ai", "cloudcli")
    os.makedirs(package, exist_ok=True)
    with open(os.path.join(package, "package.json"), "w", encoding="utf-8") as stream:
        stream.write('{"version": "1.37.3"}')
    for name in ("better-sqlite3", "node-pty", "bcrypt"):
        native = os.path.join(app, "node_modules", name)
        os.makedirs(native, exist_ok=True)
        with open(
            os.path.join(native, "package.json"), "w", encoding="utf-8"
        ) as stream:
            stream.write("{}")
    if is_finished:
        with open(
            os.path.join(app, "package-lock.json"), "w", encoding="utf-8"
        ) as stream:
            stream.write("{}")


def hooks_for(os_name, module_dir, *, held=None, **kwargs) -> CloudcliHooks:
    tools = {
        key: kwargs.pop(key)
        for key in ("run", "powershell", "batch_logon")
        if key in kwargs
    }
    kwargs.setdefault("probe", Probe())
    hooks = CloudcliHooks(platform=Platform(os_name), log=lambda line: None, **kwargs)
    held = held if held is not None else recipe()
    hooks.take_recipe(held)
    hooks.take_source_sets(getattr(held, "sets", {}))
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


def with_node(tmp_path, os_name="linux", directory="node") -> str:
    module_dir = tmp_path / "state" / "cloudcli"
    if os_name == "windows":
        (module_dir / directory).mkdir(parents=True)
        (module_dir / directory / "node.exe").write_text("")
    else:
        (module_dir / directory / "bin").mkdir(parents=True)
        (module_dir / directory / "bin" / "node").write_text("")
    return str(module_dir)


# --- Node.js ---


NODE_ARTIFACT = {"name": "node", "kind": "tar_gz", "directory": "node"}


def unpack(hooks, archive, kind="tar_gz"):
    """The node artifact through the shared unpack, then the hooks' tidy."""
    unpack_artifact(
        dict(NODE_ARTIFACT, kind=kind),
        archive,
        module_dir=hooks.machine.module_dir,
        join=os.path.join,
    )
    hooks.after_install()


def test_node_lands_under_node_without_the_archives_top_directory(tmp_path):
    hooks = hooks_for("linux", str(tmp_path / "cloudcli"))
    assert hooks.verify() is False

    unpack(hooks, tarball(tmp_path / "node.tar.gz"))

    node = tmp_path / "cloudcli" / "node"
    assert sorted(os.listdir(tmp_path / "cloudcli")) == ["node"]
    assert node_dir(str(tmp_path / "cloudcli")) == str(node)
    binary = node_path(str(node), "linux")
    assert open(binary, "rb").read() == b"#!node"
    assert stat.S_IMODE(os.stat(binary).st_mode) & 0o222 == 0
    assert os.readlink(os.path.join(node, "bin", "npm")).endswith("npm-cli.js")
    assert hooks.verify() is True
    assert hooks.node == binary


def test_a_new_node_replaces_the_one_before_and_an_older_builds_directory_goes(
    tmp_path,
):
    hooks = hooks_for("linux", str(tmp_path / "cloudcli"))
    stale = tmp_path / "cloudcli" / "node-v22.22.0-linux-x64" / "bin"
    stale.mkdir(parents=True)
    (stale / "node").write_text("")
    unpack(hooks, tarball(tmp_path / "a.tar.gz", extra=[(f"{NODE}/old", b"x")]))

    unpack(hooks, tarball(tmp_path / "b.tar.gz", top="node-v22.24.0-linux-x64"))

    assert os.listdir(tmp_path / "cloudcli") == ["node"]
    assert not (tmp_path / "cloudcli" / "node" / "old").exists()


def test_an_older_builds_directory_left_behind_goes_at_the_next_apply(tmp_path):
    hooks = hooks_for("linux", str(tmp_path / "cloudcli"))
    stale = tmp_path / "cloudcli" / "node-v22.22.0-linux-x64" / "bin"
    stale.mkdir(parents=True)
    (stale / "node").write_text("")

    assert hooks.prepare_module() == []

    assert os.listdir(tmp_path / "cloudcli") == []


def test_a_zip_lands_the_same(tmp_path):
    path = tmp_path / "node.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("node-v22.23.3-win-x64/node.exe", b"MZ")
    hooks = hooks_for("windows", str(tmp_path / "cloudcli"))

    unpack(hooks, str(path), kind="zip")

    node = str(tmp_path / "cloudcli" / "node")
    assert os.path.isfile(os.path.join(node, "node.exe"))
    assert hooks.node == ntpath.join(node, "node.exe")


# --- npm ---


def test_npm_keeps_to_the_app_directory_and_runs_against_the_registry_named():
    app = "/home/ann/.local/share/neutrino/agent/cloudcli/app"

    named = npm_environment(app)

    assert "npm_config_registry" not in named
    assert named["npm_config_cache"] == app + "/.npm"
    assert named["npm_config_userconfig"] == app + "/.npmrc"
    assert npm_arguments(
        app, package="@cloudcli-ai/cloudcli", version="1.37.3", registry=REGISTRY
    ) == [
        "install",
        "@cloudcli-ai/cloudcli@1.37.3",
        "--prefix",
        app,
        "--registry",
        REGISTRY,
    ]
    held = npm_environment(
        app, extra={"npm_config_x": "y", "npm_config_cache": "/elsewhere"}
    )
    assert held["npm_config_x"] == "y" and held["npm_config_cache"] == app + "/.npm"


# What a Node.js that cannot resolve npm's own script prints, as on Windows
# for an account that cannot read the attributes of a parent directory.
NODE_CRASH = """node:fs:2791
      const stats = binding.lstat(base, true, undefined, true /* throwIfNoEntry */);
                            ^

Error: EPERM: operation not permitted, lstat 'C:\\ProgramData\\Neutrino\\agent\\state'
    at Object.realpathSync (node:fs:2791:29)
    at toRealPath (node:internal/modules/helpers:61:13)
    at Function._findPath (node:internal/modules/cjs/loader:760:22) {
  errno: -4048,
  code: 'EPERM',
  syscall: 'lstat',
  path: 'C:\\\\ProgramData\\\\Neutrino\\\\agent\\\\state'
}

Node.js v22.23.3
"""


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
                    "found\ngyp ERR! build error\nnpm error path "
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
                    "detail": "npm error code ETIMEDOUT\nnpm error network "
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
        (
            NODE_CRASH + NODE_CRASH,
            (
                "cloudcli_npm_install_failed",
                {
                    "account": "ann",
                    "detail": "Error: EPERM: operation not permitted, lstat "
                    "'C:\\ProgramData\\Neutrino\\agent\\state'",
                },
            ),
        ),
    ],
)
def test_a_failed_install_names_its_step(output, expected):
    failure = npm_failure(output, "ann")

    assert (failure.code, failure.params) == expected


def test_a_failure_keeps_its_last_whole_lines_within_its_length():
    last = "npm error " + "x" * 150 + " 5"
    output = "\n".join(f"npm error {'x' * 150} {n}" for n in range(5)) + "\n" + last

    detail = npm_failure(output, "ann").params["detail"]

    assert len(detail) <= 400
    assert detail.startswith("... ")
    assert detail.endswith("\n" + last)


# --- the install on Linux ---


def write_log(command: list, output: str) -> None:
    """Write a service's output where systemd-run's StandardOutput names, as systemd does."""
    for part in command:
        if part.startswith("StandardOutput=file:"):
            path = part.split(":", 1)[1]
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(output)


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
        # The install service's ActiveState answers in turn, then inactive.
        self.active_states: list = []
        # Called once when the install service left running ends.
        self.on_ended = None
        self.waiting_seen: list = []
        self.slept: list = []
        self.run_error = ""
        self.system_state = "running"

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[:2] == ["systemctl", "show"] and "ActiveState" in command:
            self.waiting_seen.append(self.hooks.installing)
            if not self.active_states:
                return CommandResult(list(command), 0, "inactive\n", "")
            state = self.active_states.pop(0)
            if not self.active_states and self.on_ended is not None:
                self.on_ended()
            return CommandResult(list(command), 0, state + "\n", "")
        if command[:2] == ["systemctl", "show"]:
            return CommandResult(list(command), 0, self.unit_result + "\n", "")
        if command[:2] == ["systemctl", "is-system-running"]:
            return CommandResult(list(command), 0, self.system_state + "\n", "")
        if command[0] == "systemd-run":
            self.installing_seen.append(self.hooks.installing)
            if self.npm_exit == 0:
                land_package(command[command.index("--prefix") + 1])
            write_log(command, self.npm_output)
            return CommandResult(list(command), self.npm_exit, "", self.run_error)
        if "-e" in command:
            return CommandResult(list(command), self.check_exit, self.check_output, "")
        return CommandResult(list(command), 0, "", "")

    def install_call(self):
        return next(call for call in self.calls if call[0] == "systemd-run")

    def sleep(self, seconds):
        self.slept.append(seconds)


@pytest.fixture
def linux(tmp_path):
    machine = Machine()
    hooks = hooks_for("linux", with_node(tmp_path), run=machine, sleep=machine.sleep)
    machine.hooks = hooks
    home = str(tmp_path / "home" / "ann")
    return hooks, machine, AccountEntry(1000, 1000, home, "/bin/bash")


def test_an_install_runs_npm_as_the_account_in_a_transient_service(linux, tmp_path):
    """Its output goes to a log systemd opens: under SELinux on Rocky 9 the
    agent's pipes, which ``--pipe`` passes, failed the start with
    ``Connection reset by peer``."""
    hooks, machine, entry = linux

    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    started = machine.install_call()
    log = os.path.join(hooks.machine.module_dir, "run", "install_ann.log")
    assert started[: started.index("--")] == [
        "systemd-run",
        "--unit=neutrino_cloudcli_install_ann.service",
        "--quiet",
        "--wait",
        "-p",
        "OOMPolicy=stop",
        "-p",
        f"StandardOutput=file:{log}",
        "-p",
        f"StandardError=file:{log}",
    ]
    assert not os.path.exists(log)
    install = started[started.index("--") + 1 :]
    app = os.path.join(
        entry.home, ".local", "share", "neutrino", "agent", "cloudcli", "app"
    )
    assert install[:6] == ["runuser", "-u", "ann", "--", "env", "-i"]
    assert f"npm_config_cache={app}/.npm" in install
    assert f"npm_config_userconfig={app}/.npmrc" in install
    assert not any(part.startswith("npm_config_registry=") for part in install)
    assert "npm_config_better_sqlite3_binary_host=https://m/bs3" in install
    assert f"HOME={entry.home}" in install
    assert "RES_OPTIONS=single-request-reopen" in install
    assert install[-6:] == [
        "install",
        "@cloudcli-ai/cloudcli@1.37.3",
        "--prefix",
        app,
        "--registry",
        REGISTRY,
    ]
    assert (
        'rm -rf "$0/package-lock.json" "$0/package.json" "$0/node_modules"'
        in install[install.index("sh") + 2]
    )
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
    assert caught.value.params["detail"] == "npm error code ECONNRESET"
    assert hooks.installing == frozenset()


def test_an_install_unit_still_loaded_makes_the_step_wait(linux):
    hooks, machine, entry = linux
    machine.npm_exit = 1
    machine.run_error = (
        "Failed to start transient service unit: Unit "
        "neutrino_cloudcli_install_ann.service was already loaded or has a "
        "fragment file."
    )

    with pytest.raises(ModuleInstallPending):
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert len([call for call in machine.calls if call[0] == "systemd-run"]) == 1


def test_an_install_a_shutdown_stopped_makes_the_step_wait(linux):
    hooks, machine, entry = linux
    machine.npm_exit = 143
    machine.system_state = "stopping"

    with pytest.raises(ModuleInstallPending):
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert hooks.installing == frozenset()


def test_a_log_an_earlier_install_left_is_not_read_as_this_ones(linux):
    hooks, machine, entry = linux
    log = os.path.join(hooks.machine.module_dir, "run", "install_ann.log")
    os.makedirs(os.path.dirname(log))
    with open(log, "w", encoding="utf-8") as stream:
        stream.write("npm error an earlier failure\n")
    machine.npm_exit = 1
    machine.npm_output = "npm error code ETIMEDOUT"

    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert caught.value.params["detail"] == "npm error code ETIMEDOUT"


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


def test_an_install_left_running_is_waited_for_and_its_work_taken(linux):
    hooks, machine, entry = linux
    app = os.path.join(
        entry.home, ".local", "share", "neutrino", "agent", "cloudcli", "app"
    )
    machine.active_states = ["active", "active", "deactivating"]
    machine.on_ended = functools.partial(land_package, app)

    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert notes == []
    assert not any(call[0] == "systemd-run" for call in machine.calls)
    assert machine.slept == [5, 5, 5]
    assert machine.waiting_seen == [frozenset()] + [frozenset({"ann"})] * 3
    assert hooks.installing == frozenset()


def test_a_tree_npm_did_not_finish_runs_npm_again(linux):
    hooks, machine, entry = linux
    app = os.path.join(
        entry.home, ".local", "share", "neutrino", "agent", "cloudcli", "app"
    )
    land_package(app, is_finished=False)

    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert notes == ["installed CloudCLI for ann"]
    assert any(call[0] == "systemd-run" for call in machine.calls)


def test_an_app_holds_a_whole_install_once_npm_wrote_its_lockfile(tmp_path):
    app = str(tmp_path / "app")
    land_package(app, is_finished=False)
    assert is_app_ready(app, "1.37.3") is False

    land_package(app)
    assert is_app_ready(app, "1.37.3") is True
    assert is_app_ready(app, "1.37.4") is False


def test_an_install_left_running_that_ends_without_the_app_runs_npm_after(linux):
    hooks, machine, entry = linux
    machine.active_states = ["activating"]

    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert notes == ["installed CloudCLI for ann"]
    shown = machine.calls.index(
        [
            "systemctl",
            "show",
            "-p",
            "ActiveState",
            "--value",
            "neutrino_cloudcli_install_ann.service",
        ]
    )
    assert shown < machine.calls.index(machine.install_call())
    assert machine.slept == [5]


def test_an_install_left_running_past_the_install_time_is_stopped(linux):
    hooks, machine, entry = linux
    machine.active_states = ["active"] * 400

    hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert len(machine.slept) == 360
    stop = ["systemctl", "stop", "neutrino_cloudcli_install_ann.service"]
    assert machine.calls.index(stop) < machine.calls.index(machine.install_call())


# --- the registries and the hosts ---


class Attempts:
    """npm and the native check as the account on Linux, answered per registry and host."""

    def __init__(self, hooks, failures):
        self.hooks = hooks
        self.failures = dict(failures)
        self.tried: list = []
        self.calls: list = []

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[:2] == ["systemctl", "show"]:
            return CommandResult(list(command), 0, "success\n", "")
        if command[0] == "systemd-run":
            registry = command[command.index("--registry") + 1]
            host = next(
                (
                    part.split("=", 1)[1]
                    for part in command
                    if part.startswith(HOST_SETTING + "=")
                ),
                "",
            )
            self.tried.append((registry, host))
            output = self.failures.get((registry, host), "")
            if output:
                write_log(command, output)
                return CommandResult(list(command), 1, "", "")
            land_package(command[command.index("--prefix") + 1])
        return CommandResult(list(command), 0, "", "")


def attempted(tmp_path, held, probe, failures):
    machine = Attempts(None, failures)
    hooks = hooks_for("linux", with_node(tmp_path), run=machine, held=held, probe=probe)
    entry = AccountEntry(1000, 1000, str(tmp_path / "home" / "ann"), "/bin/bash")
    return hooks, machine, entry


def test_the_fastest_registry_naming_the_integrity_is_used_with_the_fastest_host(
    tmp_path,
):
    probe = Probe(
        integrities={"https://wrong.example": "sha512-other"},
        speeds={
            "https://wrong.example": 100.0,
            "https://slow.example": 1.0,
            "https://fast.example": 10.0,
            "https://h-slow": 1.0,
            "https://h-fast": 10.0,
        },
    )
    held = recipe(
        registries=(
            "https://slow.example",
            "https://wrong.example",
            "https://fast.example",
        ),
        hosts=("https://h-slow", "https://h-fast"),
    )
    hooks, machine, entry = attempted(tmp_path, held, probe, {})

    hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert machine.tried == [("https://fast.example", "https://h-fast")]
    assert "https://wrong.example/@cloudcli-ai%2Fcloudcli" in probe.asked
    assert f"https://h-fast{HOST_FILE}" in probe.asked


def test_a_failed_install_runs_again_on_the_next_registry_and_host(tmp_path):
    probe = Probe(speeds={"https://a.example": 10.0, "https://b.example": 1.0})
    held = recipe(registries=("https://b.example", "https://a.example"), hosts=(HOST,))
    failures = {("https://a.example", HOST): "npm error code ECONNRESET"}
    hooks, machine, entry = attempted(tmp_path, held, probe, failures)

    assert hooks.prepare(CONFIG, CONFIG.instances[0], entry) == [
        "installed CloudCLI for ann"
    ]

    assert machine.tried == [("https://a.example", HOST), ("https://b.example", HOST)]


def test_a_native_module_that_fails_on_one_host_runs_again_with_the_next(tmp_path):
    probe = Probe(speeds={"https://h1": 10.0, "https://h2": 1.0})
    held = recipe(hosts=("https://h2", "https://h1"))
    failures = {
        (REGISTRY, "https://h1"): "prebuild-install warn\ngyp ERR! better-sqlite3"
    }
    hooks, machine, entry = attempted(tmp_path, held, probe, failures)

    hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert machine.tried == [(REGISTRY, "https://h1"), (REGISTRY, "https://h2")]


def test_the_last_failure_is_the_one_reported(tmp_path):
    probe = Probe(speeds={"https://a.example": 10.0, "https://b.example": 1.0})
    held = recipe(registries=("https://a.example", "https://b.example"), hosts=())
    failures = {
        ("https://a.example", ""): "npm error code ECONNRESET",
        ("https://b.example", ""): "npm error code E404",
    }
    hooks, machine, entry = attempted(tmp_path, held, probe, failures)

    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert caught.value.code == "cloudcli_npm_install_failed"
    assert caught.value.params["detail"] == "npm error code E404"
    assert machine.tried == [("https://a.example", ""), ("https://b.example", "")]


def test_no_registry_naming_the_integrity_is_download_failed(tmp_path):
    probe = Probe(
        integrities={"https://a.example": "sha512-other"},
        speeds={"https://b.example": None},
    )
    held = recipe(registries=("https://a.example", "https://b.example"))
    hooks, machine, entry = attempted(tmp_path, held, probe, {})

    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert caught.value.code == "download_failed"
    assert caught.value.params == {
        "file": "@cloudcli-ai/cloudcli@1.37.3",
        "sources": [
            {
                "source": "https://a.example",
                "reason": "digest_mismatch",
                "detail": "the registry names sha512-other",
            },
            {
                "source": "https://b.example",
                "reason": "unreachable",
                "detail": "refused",
            },
        ],
    }
    assert machine.tried == []


def test_a_recipe_naming_no_npm_package_is_download_failed(tmp_path):
    hooks, machine, entry = attempted(
        tmp_path, {"runner": "cloudcli", "method": "hub", "params": {}}, Probe(), {}
    )

    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert caught.value.code == "download_failed"
    assert machine.tried == []


def test_the_windows_script_tries_each_registry_and_host_in_turn(windows):
    hooks, host, entry = windows
    hooks._probe = Probe(speeds={"https://a.example": 10.0, "https://h1": 10.0})
    held = recipe(
        registries=("https://b.example", "https://a.example"),
        hosts=("https://h2", "https://h1"),
    )
    hooks.take_recipe(held)
    hooks.take_source_sets(held.sets)

    hooks.prepare_module()
    hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    script = hooks.machine.module_dir + "\\run\\install_ann.cmd"
    with open(script, encoding="utf-8") as stream:
        lines = stream.read().splitlines()
    tried = [
        line.split("--registry ", 1)[1].split(" ", 1)[0]
        for line in lines
        if "--registry" in line
    ]
    hosts = [line for line in lines if line.startswith(f'set "{HOST_SETTING}=')]
    assert tried == [
        "https://a.example",
        "https://a.example",
        "https://b.example",
        "https://b.example",
    ]
    assert hosts == [
        f'set "{HOST_SETTING}=https://h1"',
        f'set "{HOST_SETTING}=https://h2"',
        f'set "{HOST_SETTING}=https://h1"',
        f'set "{HOST_SETTING}=https://h2"',
    ]
    assert lines[-1] == "exit /b %NEUTRINO_INSTALL_RESULT%"


# --- the install on a Mac ---


def test_a_mac_install_runs_npm_as_the_account(tmp_path):
    calls = []

    def run_as(entry, command, *, environment, timeout_s):
        calls.append((entry, list(command), dict(environment), timeout_s))
        if "install" in command:
            land_package(command[command.index("--prefix") + 1])
        return CommandResult(list(command), 0, "", "")

    hooks = hooks_for("darwin", with_node(tmp_path, "darwin"), run_as=run_as)
    entry = AccountEntry(501, 20, str(tmp_path / "Users" / "ann"), "/bin/zsh")

    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    install, check = calls
    assert install[0] is entry
    assert install[1][-6:-3] == ["install", "@cloudcli-ai/cloudcli@1.37.3", "--prefix"]
    assert install[1][-2:] == ["--registry", REGISTRY]
    assert install[2]["PATH"].endswith("node/bin:/usr/bin:/bin:/usr/sbin:/sbin")
    assert install[2]["npm_config_userconfig"].endswith("cloudcli/app/.npmrc")
    assert install[3] == 1800
    assert "createRequire" in check[1][-1]
    assert notes == ["installed CloudCLI for ann"]


# --- the install on Windows ---


def granted(argv, **_):
    """icacls granting whatever it is asked, each call recorded."""
    GRANTS.append(list(argv))
    return CommandResult(command=list(argv), exit_code=0, stdout="", stderr="")


GRANTS: list = []


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
    monkeypatch.setattr(
        hooks_module, "is_app_ready", lambda app, version: held["is_ready"]
    )
    return held


@pytest.fixture
def windows(tmp_path, ready):
    GRANTS.clear()
    host = RecordingHost({"task_states": {"tasks": []}})
    hooks = hooks_for(
        "windows",
        with_node(tmp_path, "windows"),
        powershell=host,
        run=granted,
        batch_logon=FakeBatchLogon(host.calls),
    )
    return hooks, host, AccountEntry(0, 0, "C:\\Users\\ann", "")


def test_an_install_is_started_as_a_task_and_left_to_run(windows):
    hooks, host, entry = windows

    hooks.prepare_module()
    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert notes == []
    assert host.ops() == ["task_states", "batch_logon_hold", "task_run_once"]
    assert host.args_of("batch_logon_hold") == [
        {"account": "ann", "task": "neutrino_cloudcli_install_ann"}
    ]
    assert host.args_of("task_states") == [{"prefix": "neutrino_cloudcli_install_"}]
    (started,) = host.args_of("task_run_once")
    script = hooks.machine.module_dir + "\\run\\install_ann.cmd"
    log = hooks.machine.module_dir + "\\run\\install_ann.log"
    assert started == {
        "task": "neutrino_cloudcli_install_ann",
        "program": "cmd.exe",
        "arguments": f'/s /c "{script} >> {log} 2>&1"',
        "account": "ann",
        "password": "login-pw",  # scan: allow
        "timeout_s": 4 * 3600,
    }
    with open(script, encoding="utf-8") as stream:
        text = stream.read()
    assert "@cloudcli-ai/cloudcli@1.37.3" in text
    assert f"--registry {REGISTRY} || goto :attempt_1" in text
    assert 'set "npm_config_registry=' not in text
    with open(log, encoding="utf-8") as stream:
        assert stream.read() == ""
    assert [grant[1] for grant in GRANTS] == [script, log]
    assert all(
        grant[2:5] == ["/inheritance:r", "/grant:r", "ann:M"] for grant in GRANTS
    )
    assert hooks.installing == frozenset({"ann"})
    assert hooks.install_log("ann").endswith("cloudcli\\run\\install_ann.log")
    assert hooks.install_log("bob") == ""


@pytest.mark.parametrize("state", ["Running", "Queued"])
def test_a_running_install_starts_nothing_and_keeps_waiting(windows, state):
    hooks, host, entry = windows
    host.answers["task_states"] = {"tasks": [install_task(state, 0x41301)]}

    hooks.prepare_module()
    hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert host.ops() == ["task_states"]
    assert hooks.installing == frozenset({"ann"})


def test_each_windows_attempt_removes_what_an_earlier_npm_wrote_before_its_npm():
    node = "C:\\node\\node.exe"
    text = render_install_script(
        app="C:\\app",
        node=node,
        npm="C:\\node\\npm-cli.js",
        package="@cloudcli-ai/cloudcli",
        version="1.37.3",
        attempts=[("https://a.example", {}), ("https://b.example", {})],
    )

    lines = text.split("\r\n")
    cleans = [i for i, line in enumerate(lines) if "rmSync" in line]
    npms = [i for i, line in enumerate(lines) if " install " in line]
    assert len(cleans) == 2
    assert [clean + 1 for clean in cleans] == npms
    assert lines[cleans[0]].endswith("|| goto :attempt_1")
    assert lines[cleans[1]].endswith("|| goto :attempt_2")
    assert lines[cleans[0]].startswith(f'"{node}" -e "for (const name of [')
    assert "'package-lock.json','package.json','node_modules'" in lines[cleans[0]]
    assert lines.index('cd /d "C:\\app" || exit /b 1') < cleans[0]


def test_an_ended_install_is_unregistered_and_judged(windows, ready):
    hooks, host, entry = windows
    host.answers["task_states"] = {"tasks": [install_task("Ready", 0)]}
    script = hooks.machine.module_dir + "\\run\\install_ann.cmd"
    with open(script, "w", encoding="utf-8") as stream:
        stream.write("@echo off\r\n")
    ready["is_ready"] = True

    hooks.prepare_module()
    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert host.ops() == ["task_states", "task_remove", "batch_logon_release"]
    assert host.args_of("task_remove") == [{"task": "neutrino_cloudcli_install_ann"}]
    assert host.args_of("batch_logon_release") == [
        {"account": "ann", "task": "neutrino_cloudcli_install_ann"}
    ]
    assert not os.path.exists(script)
    assert notes == ["installed CloudCLI for ann"]
    assert hooks.installing == frozenset()


@pytest.mark.parametrize("result", [0x41306, 0x8007042B, 0x800704C7, 0xC000013A])
def test_an_install_a_shutdown_cut_runs_again_and_keeps_no_failure(windows, result):
    hooks, host, entry = windows
    host.answers["task_states"] = {"tasks": [install_task("Ready", result)]}
    log = hooks.machine.module_dir + "\\run\\install_ann.log"
    with open(log, "w", encoding="utf-8") as stream:
        stream.write("npm error gyp ERR! not ok\nbetter-sqlite3\n")

    notes = hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert notes == []
    assert host.ops() == [
        "task_states",
        "task_remove",
        "batch_logon_release",
        "batch_logon_hold",
        "task_run_once",
    ]
    assert hooks.installing == frozenset({"ann"})
    with open(log, encoding="utf-8") as stream:
        assert stream.read() == ""


def test_an_app_already_there_starts_no_install(windows, ready):
    hooks, host, entry = windows
    ready["is_ready"] = True

    hooks.prepare_module()

    assert hooks.prepare(CONFIG, CONFIG.instances[0], entry) == []
    assert host.ops() == ["task_states"]


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
    hooks, host, entry = windows
    host.answers["task_states"] = {"tasks": [install_task("Ready", result)]}
    log = hooks.machine.module_dir + "\\run\\install_ann.log"
    with open(log, "w", encoding="utf-8") as stream:
        stream.write(output)

    hooks.prepare_module()
    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert (caught.value.code, caught.value.params) == expected


def test_only_the_end_of_a_long_install_output_is_judged(tmp_path):
    log = tmp_path / "install.log"
    log.write_bytes(b"\xef\xbb\xbf" + b"x" * 9000 + b"npm error last")

    output = install_output(str(log))

    assert len(output) == 8000
    assert output.endswith("npm error last")
    assert install_output(str(tmp_path / "absent.log")) == ""


def test_a_refused_login_is_credential_invalid(windows):
    hooks, host, entry = windows
    host.answers["task_run_once"] = ModuleApplyError(
        "credential_invalid", {"account": "ann"}
    )

    hooks.prepare_module()
    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert caught.value.code == "credential_invalid"
    assert host.ops()[-2:] == ["task_run_once", "batch_logon_release"]


# --- the record and the service ---


def test_the_record_keeps_the_loopback_port_and_the_database_across_applies(tmp_path):
    ports = iter([41000, 41001])
    hooks = hooks_for("linux", with_node(tmp_path), pick_port=lambda: next(ports))
    instance = CONFIG.instances[0]

    first = hooks.record(CONFIG, instance, {"port": 3001})
    again = hooks.record(CONFIG, instance, first)
    fresh = hooks.record(CONFIG, instance, dict(first, database="auth-x.db"))

    assert first == {
        "account": "ann",
        "port": 3001,
        "upstream_port": 41000,
        "web_password": PASSWORD,
        "token_secret": SECRET,
        "database": "auth.db",
        "local_name": "cloudcli-ann.m.localhost",
        "cookie_name": COOKIE,
    }
    assert again == first
    assert fresh["database"] == "auth-x.db" and fresh["upstream_port"] == 41000
    assert CloudcliHooks.forwarder_fields == (
        "account",
        "port",
        "upstream_port",
        "web_password",
        "token_secret",
        "local_name",
        "cookie_name",
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
        hooks_for("darwin", with_node(tmp_path / "mac", "darwin"))
        .service(CONFIG.instances[0], ANN, record)
        .command[1]
        .endswith("index.js")
    )


def test_an_environment_is_written_from_scratch_naming_no_gateway():
    config = CloudcliConfig.from_dict(
        {
            "gateway_url": "http://10.0.0.1:8317",
            "gateway_key": "k",
            "instances": [{"account": "ann", "token_secret": "s"}],
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
        "cookie_name": COOKIE,
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
    """One request on a connection it closes, its Host loopback's."""
    request = request.replace(b"Host: x\r\n", b"").replace(
        b"\r\n\r\n", b"\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n", 1
    )
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
    assert f"Set-Cookie: {COOKIE}=".encode() in head
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
        f"GET /api/y HTTP/1.1\r\nHost: x\r\nCookie: {COOKIE}={login}\r\n\r\n".encode(),
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
            f"GET /ws?token={login} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            "Connection: Upgrade\r\nUpgrade: websocket\r\n\r\n".encode()
        )
        received = b""
        while b"\r\n\r\n" not in received:
            received += client.recv(65536)
        assert received.startswith(b"HTTP/1.1 101")
        client.sendall(b"ping")
        echoed = client.recv(65536)

    assert echoed == b"PING"


def test_the_registries_are_the_ones_the_state_s_npm_set_names(tmp_path):
    probe = Probe()
    held = recipe(registries=("https://set.example",))
    hooks, machine, entry = attempted(tmp_path, held, probe, {})

    hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert probe.asked[0].startswith("https://set.example/")
    assert machine.tried[0][0] == "https://set.example"


def test_a_set_the_state_does_not_carry_is_download_failed(tmp_path):
    held = HeldRecipe(recipe(), {})
    hooks, machine, entry = attempted(tmp_path, held, Probe(), {})

    with pytest.raises(ModuleApplyError) as caught:
        hooks.prepare(CONFIG, CONFIG.instances[0], entry)

    assert caught.value.code == "download_failed"
    assert machine.tried == []
