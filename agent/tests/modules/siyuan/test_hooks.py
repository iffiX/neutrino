"""SiYuan's hooks: the kernel per account, its settings, its login.

What these pin: the kernel and its working directory are found under the
``app`` artifact by system; each instance's command line names its
workspace and its home directory under the account's data directory and the
kernel's port, through its environment on Linux, and the access code is in
the root-only environment and on no command line, under ``umask 077``; the
workspace is made as the account when it is not there; the record keeps the
kernel's port and what was last written; the settings are written as the
account, with the kernel stopped and started again after, once the kernel
answers and has made them, again when the key, the address or the models
change, and left alone otherwise; the forwarder trades a token for the
kernel's own login, asked with the browser's ``Host`` and no ``Origin``, and
sets the kernel's cookie under the entry's name, passes a request holding
that cookie, and answers 401 to the login path, to a token that does not
verify and to a request with neither; and the version is the build's own.
"""

import http.server
import json
import ntpath
import os
import socket
import subprocess
import threading

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.http_forward import RELAY
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.modules.siyuan.config import (
    SiyuanConfig,
    provider_id,
    settings_digest,
)
from neutrino_agent.modules.siyuan.hooks import (
    SiyuanHooks,
    data_dir,
    kernel_login,
    normal_path,
)
from neutrino_agent.platforms.base import AgentPlatform

SECRET = "instance-secret"  # scan: allow
CODE = "access-code"  # scan: allow
KEY = "gateway-key-of-ann-0123456789abc"  # scan: allow
COOKIE = "neutrino_0123456789ab"
URL = "http://127.0.0.1:8317"
WIN_STATE = "C:\\ProgramData\\Neutrino\\agent\\state\\siyuan"


class Platform(AgentPlatform):
    """A platform that runs a command as the account by running it as the test itself, and records Windows' steps."""

    def __init__(self, os_name="linux"):
        self.os_name = os_name
        self.as_account_calls: list = []
        self.run_calls: list = []

    def run_as_account(self, account, argv, *, stdin="", timeout_s=0, **unused):
        self.run_calls.append((account, list(argv)))
        return subprocess.run(argv, input=stdin, capture_output=True, text=True)

    def as_account(self, account, step, *arguments, password=""):
        self.as_account_calls.append((account, step.__name__, password))
        return None if step.__name__ == "_step_read" else ""


class Recorder:
    """Every command the service layer runs, none of them run."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        return CommandResult(list(command), 0, "", "")


def hooks_for(tmp_path, os_name="linux", **kwargs):
    home = str(tmp_path / "home" / "ann")
    os.makedirs(home, exist_ok=True)
    module_dir = str(tmp_path / "state" / "siyuan")
    recorder = Recorder()
    platform = Platform(os_name)
    hooks = SiyuanHooks(platform=platform, log=lambda line: None, **kwargs)
    entry = AccountEntry(1000, 1000, home, "/bin/bash")

    def lookup(account):
        if account != "ann":
            raise KeyError(account)
        return entry

    machine = ServiceMachine(
        os_name=os_name,
        module_dir=module_dir,
        record_dir=module_dir,
        lookup_account=lookup,
        run=recorder,
    )
    reapplied: list = []
    hooks.bind(machine, lambda account, **changes: reapplied.append((account, changes)))
    return hooks, entry, recorder, platform, reapplied


def config(**changes) -> SiyuanConfig:
    instance = {
        "account": "ann",
        "secret": SECRET,
        "access_code": CODE,
        "gateway_key": KEY,
        "local_name": "siyuan-ann.m.localhost",
        "cookie_name": COOKIE,
    }
    instance.update(changes)
    return SiyuanConfig.from_dict(
        {"instances": [instance], "gateway_url": URL, "models": ["m1", "m2"]}
    )


class Kernel(http.server.ThreadingHTTPServer):
    """A kernel on loopback: its login answers the right code with its cookie."""

    daemon_threads = True

    def __init__(self, *, is_refusing=False):
        self.logins: list = []
        self.is_refusing = is_refusing
        super().__init__(("127.0.0.1", 0), KernelHandler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return self.server_address[1]


class KernelHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.logins.append((self.path, dict(self.headers), body))
        is_good = body.get("authCode") == CODE and not self.server.is_refusing
        data = json.dumps({"code": 0 if is_good else -1}).encode()
        self.send_response(200)
        if is_good:
            self.send_header(
                "Set-Cookie", "siyuan=kernel-login; Path=/; Max-Age=2592000; HttpOnly"
            )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *arguments):
        return


class Request:
    """A request as the forwarder hands it to the rule."""

    def __init__(self, path="/", *, token="", cookies=None, is_token_good=True):
        self.path = path
        self.token = token
        self._cookies = cookies or {}
        self._is_token_good = is_token_good

    def take_token(self):
        return self._is_token_good

    def header(self, name):
        return "siyuan-ann.m.localhost:24200" if name == "host" else ""

    def cookie_values(self, name):
        return [self._cookies[name]] if name in self._cookies else []


# --- the artifact and the service ---


def test_the_kernel_is_found_under_the_app_artifact_by_system(tmp_path):
    linux, *_ = hooks_for(tmp_path)
    mac, *_ = hooks_for(tmp_path, "darwin")
    windows = SiyuanHooks(platform=Platform("windows"), log=lambda line: None)
    windows.bind(
        ServiceMachine(
            os_name="windows",
            module_dir=WIN_STATE,
            record_dir=WIN_STATE,
            lookup_account=lambda account: None,
        ),
        None,
    )
    state = str(tmp_path / "state" / "siyuan")

    assert linux.kernel_path == f"{state}/app/resources/kernel/SiYuan-Kernel"
    assert mac.kernel_path == f"{state}/app/kernel/SiYuan-Kernel"
    assert mac.resources_dir == f"{state}/app"
    assert windows.kernel_path == ntpath.join(
        WIN_STATE, "app", "resources", "kernel", "SiYuan-Kernel.exe"
    )
    assert not linux.verify()
    os.makedirs(os.path.dirname(linux.kernel_path))
    open(linux.kernel_path, "w").close()
    assert linux.verify()


def test_the_code_is_in_the_root_only_environment_and_on_no_command_line(tmp_path):
    hooks, entry, *_ = hooks_for(tmp_path, "darwin")
    instance = config().instances[0]

    service = hooks.service(instance, entry, {"kernel_port": 41000})

    data = data_dir(entry.home, "darwin")
    assert service.command == (
        hooks.kernel_path,
        "serve",
        f"--wd={hooks.resources_dir}",
        f"--workspace={data}/workspace",
        f"--home-dir={data}",
        "--port=41000",
    )
    assert service.environment == {"SIYUAN_ACCESS_AUTH_CODE": CODE}
    assert not any(CODE in word for word in service.command)
    assert service.is_environment_secret
    assert service.umask == "077"
    assert service.listen_port == 41000


def test_on_linux_the_command_line_takes_the_accounts_paths_from_its_environment(
    tmp_path,
):
    hooks, entry, *_ = hooks_for(tmp_path)

    service = hooks.service(config().instances[0], entry, {"kernel_port": 41000})

    data = data_dir(entry.home, "linux")
    assert service.command[3:] == (
        "--workspace=${NEUTRINO_SIYUAN_WORKSPACE}",
        "--home-dir=${NEUTRINO_SIYUAN_DATA}",
        "--port=${NEUTRINO_SIYUAN_PORT}",
    )
    assert service.environment == {
        "SIYUAN_ACCESS_AUTH_CODE": CODE,
        "NEUTRINO_SIYUAN_WORKSPACE": f"{data}/workspace",
        "NEUTRINO_SIYUAN_DATA": data,
        "NEUTRINO_SIYUAN_PORT": "41000",
    }


def test_the_workspace_is_made_as_the_account_once(tmp_path):
    hooks, entry, _recorder, platform, _ = hooks_for(tmp_path)
    workspace = os.path.join(data_dir(entry.home, "linux"), "workspace")

    assert hooks.prepare(config(), config().instances[0], entry) == [
        "made the workspace of ann"
    ]
    assert os.path.isdir(workspace)
    assert os.stat(workspace).st_mode & 0o777 == 0o700
    assert os.stat(os.path.dirname(workspace)).st_mode & 0o777 == 0o700
    assert platform.run_calls[0][0] == "ann"
    assert platform.run_calls[0][1][:2] == ["sh", "-c"]
    assert hooks.prepare(config(), config().instances[0], entry) == []
    assert len(platform.run_calls) == 1


def test_a_workspace_that_cannot_be_made_is_refused(tmp_path):
    hooks, entry, *_ = hooks_for(tmp_path)
    blocked = os.path.join(entry.home, ".local")
    with open(blocked, "w") as stream:
        stream.write("a file where a directory goes")

    with pytest.raises(ModuleApplyError) as raised:
        hooks.prepare(config(), config().instances[0], entry)
    assert raised.value.code == "apply_failed"


def test_on_windows_the_workspace_is_made_acting_as_the_account(tmp_path):
    hooks, entry, _recorder, platform, _ = hooks_for(tmp_path, "windows")
    instance = config(password="login-pw").instances[0]

    hooks.prepare(config(), instance, entry)

    assert platform.as_account_calls == [("ann", "_step_make_dir", "login-pw")]


def test_on_windows_the_settings_wait_for_a_login_and_never_try_one_empty(tmp_path):
    hooks, entry, _recorder, platform, _ = hooks_for(tmp_path, "windows")
    listener, record = started_kernel(tmp_path, hooks, entry)
    with listener:
        with pytest.raises(OSError, match="no settings"):
            hooks.on_first_start(record)
        assert platform.as_account_calls == []

        parsed = config(password="login-pw")
        hooks.record(parsed, parsed.instances[0], {"port": 6810})
        with pytest.raises(OSError, match="no settings"):
            hooks.on_first_start(record)

    assert platform.as_account_calls == [("ann", "_step_read", "login-pw")]


def test_the_record_keeps_the_kernels_port_and_what_was_written(tmp_path):
    hooks, *_ = hooks_for(tmp_path, pick_port=lambda: 41001)
    parsed = config()

    fresh = hooks.record(parsed, parsed.instances[0], {"port": 6810})
    kept = hooks.record(
        parsed,
        parsed.instances[0],
        {"port": 6810, "kernel_port": 41000, "settings_written": "abc"},
    )

    assert fresh["kernel_port"] == 41001
    assert fresh["settings_written"] == ""
    assert fresh["models"] == ["m1", "m2"]
    assert fresh["gateway_url"] == URL
    assert kept["kernel_port"] == 41000
    assert kept["settings_written"] == "abc"


# --- the settings ---


def started_kernel(tmp_path, hooks, entry):
    """A listening socket standing in for the kernel, and the record that names it."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    parsed = config()
    record = hooks.record(parsed, parsed.instances[0], {"port": 6810})
    record["kernel_port"] = listener.getsockname()[1]
    return listener, record


def write_conf(entry, conf: dict) -> str:
    path = os.path.join(data_dir(entry.home, "linux"), "workspace", "conf", "conf.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(conf, stream)
    return path


def test_the_settings_wait_for_the_kernel_and_for_its_first_settings(tmp_path):
    hooks, entry, recorder, *_ = hooks_for(tmp_path)
    listener, record = started_kernel(tmp_path, hooks, entry)
    with listener:
        with pytest.raises(OSError, match="no settings"):
            hooks.on_first_start(record)
    with pytest.raises(OSError):
        hooks.on_first_start(record)
    assert recorder.calls == []


def test_the_settings_are_written_as_the_account_with_the_kernel_stopped(tmp_path):
    hooks, entry, recorder, platform, reapplied = hooks_for(tmp_path)
    listener, record = started_kernel(tmp_path, hooks, entry)
    path = write_conf(
        entry, {"ai": {"providers": []}, "system": {"downloadInstallPkg": True}}
    )
    with listener:
        with pytest.raises(OSError, match="starts again"):
            hooks.on_first_start(record)
        assert hooks.on_first_start(record) == ""

    with open(path, encoding="utf-8") as stream:
        written = json.load(stream)
    assert written["ai"]["providers"][0]["id"] == provider_id()
    assert written["ai"]["providers"][0]["apiKey"] == KEY
    assert written["ai"]["providers"][0]["baseURL"] == URL + "/v1"
    assert written["system"]["downloadInstallPkg"] is False
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert recorder.calls == [
        ["systemctl", "stop", "neutrino_siyuan@ann.service"],
        ["systemctl", "enable", "--now", "neutrino_siyuan@ann.service"],
    ]
    writes = [argv for account, argv in platform.run_calls if "sh" in argv[:1]]
    assert all(account == "ann" for account, _ in platform.run_calls)
    assert writes[-1][-1] == path
    wanted = settings_digest(KEY, URL, ["m1", "m2"])
    assert reapplied == [("ann", {"settings_written": wanted})]


def test_settings_already_written_are_left_alone_and_a_new_key_writes_them_again(
    tmp_path,
):
    hooks, entry, recorder, _platform, reapplied = hooks_for(tmp_path)
    listener, record = started_kernel(tmp_path, hooks, entry)
    write_conf(entry, {})
    record["settings_written"] = settings_digest(KEY, URL, ["m1", "m2"])
    with listener:
        assert hooks.on_first_start(record) == ""
        assert recorder.calls == []

        record["gateway_key"] = "a-new-key-for-ann-0123456789abcd"
        with pytest.raises(OSError):
            hooks.on_first_start(record)

    assert len(recorder.calls) == 2
    assert reapplied[-1][1]["settings_written"] == settings_digest(
        record["gateway_key"], URL, ["m1", "m2"]
    )


def test_settings_that_do_not_read_are_left_and_the_kernel_started_again(tmp_path):
    lines: list = []
    hooks, entry, recorder, *_ = hooks_for(tmp_path)
    hooks._log = lines.append
    listener, record = started_kernel(tmp_path, hooks, entry)
    path = os.path.join(data_dir(entry.home, "linux"), "workspace", "conf", "conf.json")
    os.makedirs(os.path.dirname(path))
    with open(path, "w") as stream:
        stream.write("{not json")
    with listener:
        with pytest.raises(OSError):
            hooks.on_first_start(record)

    assert open(path).read() == "{not json"
    assert recorder.calls[-1][:2] == ["systemctl", "enable"]
    assert lines == ["siyuan: ann's settings do not read"]


# --- the forwarder's rule ---


@pytest.mark.parametrize(
    "path",
    [
        "/api/system/loginAuth",
        "/api/system/loginauth/",
        "//api/system/login%41uth",
        "/API/system/loginAuth",
    ],
)
def test_the_login_path_is_401_whatever_the_request_holds(tmp_path, path):
    hooks, *_ = hooks_for(tmp_path)
    record = {"secret": SECRET, "cookie_name": COOKIE, "kernel_port": 1}

    decision = hooks.admit(Request(path, cookies={COOKIE: "v"}), record)

    assert decision.status == 401
    assert normal_path(path) == "/api/system/loginauth"


def test_a_token_trades_for_the_kernels_login_under_the_entrys_name(tmp_path):
    kernel = Kernel()
    hooks, *_ = hooks_for(tmp_path)
    record = {
        "secret": SECRET,
        "cookie_name": COOKIE,
        "kernel_port": kernel.port,
        "access_code": CODE,
    }
    try:
        decision = hooks.admit(Request("/", token="t"), record)
    finally:
        kernel.shutdown()

    assert decision.status == 302
    headers = dict(decision.headers)
    assert headers["Location"] == "/"
    assert headers["Set-Cookie"] == (
        f"{COOKIE}=kernel-login; Path=/; Max-Age=2592000; HttpOnly"
    )
    path, sent, body = kernel.logins[0]
    assert path == "/api/system/loginAuth"
    assert body == {"authCode": CODE, "rememberMe": True}
    assert sent["Host"] == "siyuan-ann.m.localhost:24200"
    assert "Origin" not in sent


def test_a_token_the_kernel_refuses_is_502_and_a_bad_token_401(tmp_path):
    kernel = Kernel(is_refusing=True)
    hooks, *_ = hooks_for(tmp_path)
    record = {
        "secret": SECRET,
        "cookie_name": COOKIE,
        "kernel_port": kernel.port,
        "access_code": CODE,
    }
    try:
        refused_by_kernel = hooks.admit(Request("/", token="t"), record)
        bad_token = hooks.admit(Request("/", token="t", is_token_good=False), record)
    finally:
        kernel.shutdown()

    assert refused_by_kernel.status == 502
    assert bad_token.status == 401


def test_the_cookie_passes_and_a_request_with_neither_is_401(tmp_path):
    hooks, *_ = hooks_for(tmp_path)
    record = {"secret": SECRET, "cookie_name": COOKIE, "kernel_port": 1}

    assert hooks.admit(Request("/stage", cookies={COOKIE: "v"}), record) is RELAY
    assert hooks.admit(Request("/stage", cookies={"siyuan": "v"}), record).status == 401
    assert hooks.admit(Request("/stage"), record).status == 401
    assert hooks.page_cookie == "siyuan"


def test_the_kernels_login_is_asked_with_the_browsers_host_and_no_origin():
    kernel = Kernel()
    try:
        status, body, headers = kernel_login(kernel.port, "127.0.0.1:24200", CODE)
    finally:
        kernel.shutdown()

    assert (status, body) == (200, {"code": 0})
    assert ("Set-Cookie", "siyuan=kernel-login; Path=/; Max-Age=2592000; HttpOnly") in (
        headers
    )
    assert kernel.logins[0][1]["Host"] == "127.0.0.1:24200"


def test_a_kernel_that_does_not_answer_is_an_os_error():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(OSError):
        kernel_login(port, "127.0.0.1", CODE)


def test_the_version_is_the_builds_own(tmp_path):
    hooks, *_ = hooks_for(tmp_path)
    package = os.path.join(hooks.resources_dir, "app", "package.json")

    assert hooks.module_details() == {"version": ""}
    os.makedirs(os.path.dirname(package))
    with open(package, "w") as stream:
        json.dump({"name": "SiYuan", "version": "3.8.8"}, stream)
    assert hooks.module_details() == {"version": "3.8.8"}
