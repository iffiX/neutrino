"""What CloudCLI adds to the shared runner: Node.js, each account's npm install, the login.

Node.js comes from the hub's package stream as the archive nodejs.org
publishes and lands under the module's own directory, never on a ``PATH``.
Before an instance first runs, its account installs CloudCLI into its own
app directory with that Node.js: as a transient service on Linux, so a kill
for want of memory ends it and not the agent; as the account's own process
on macOS; as a task of its own on Windows, left running and judged by the
next apply. Each instance runs Node.js with the account's server script,
from an environment written from scratch, on a loopback port the agent
picks and keeps in the record. The forwarder registers CloudCLI's
administrator on the first start, trades the hub's token for CloudCLI's
login, and passes a request on only with that login.

Not pure: writes files, runs npm as the account, and talks to CloudCLI.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import binascii
import hashlib
import hmac
import http.client
import json
import ntpath
import os
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import zipfile

from neutrino_agent.constants import AGENT_FORWARD_UPSTREAM_TIMEOUT_S
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli.config import (
    CloudcliConfig,
    CloudcliInstance,
    jwt_secret,
    username_of,
)
from neutrino_agent.modules.cloudcli.constants import (
    CLOUDCLI_ACCOUNT_PARTS,
    CLOUDCLI_ACCOUNT_PATH_PARTS,
    CLOUDCLI_APP_DIR_NAME,
    CLOUDCLI_BLOCKED_PATHS,
    CLOUDCLI_COOKIE_PREFIX,
    CLOUDCLI_DATABASE_NAME,
    CLOUDCLI_FAILURE_DETAIL_CHARS,
    CLOUDCLI_FAILURE_LINES,
    CLOUDCLI_FORWARDER_FIELDS,
    CLOUDCLI_FRESH_DATABASE_PATTERN,
    CLOUDCLI_FRESH_STAMP_FORMAT,
    CLOUDCLI_INSTALL_LOG_PATTERN,
    CLOUDCLI_INSTALL_PATH,
    CLOUDCLI_INSTALL_SCRIPT_PATTERN,
    CLOUDCLI_INSTALL_TASK_PREFIX,
    CLOUDCLI_INSTALL_TIMEOUT_S,
    CLOUDCLI_INSTALL_UNIT_PREFIX,
    CLOUDCLI_KIND,
    CLOUDCLI_LOGIN_LIFETIME_S,
    CLOUDCLI_LOGIN_PATH,
    CLOUDCLI_LOOKUP_TIMEOUT_S,
    CLOUDCLI_NAME,
    CLOUDCLI_NATIVE_MODULES,
    CLOUDCLI_NODE_DOWNLOAD_FAILED,
    CLOUDCLI_NODE_PARTS,
    CLOUDCLI_NODE_PREFIX,
    CLOUDCLI_NPM_CACHE_NAME,
    CLOUDCLI_NPM_PARTS,
    CLOUDCLI_NPM_USERCONFIG_NAME,
    CLOUDCLI_OOM_RESULT,
    CLOUDCLI_PACKAGE,
    CLOUDCLI_PACKAGE_PARTS,
    CLOUDCLI_QUERY_TOKEN,
    CLOUDCLI_RECORD_FIELDS,
    CLOUDCLI_REGISTER_FAILED,
    CLOUDCLI_REGISTER_PATH,
    CLOUDCLI_SERVER_PARTS,
    CLOUDCLI_SERVER_VARIABLE,
    CLOUDCLI_STATUS_PATH,
    CLOUDCLI_STORAGE_KEY,
    CLOUDCLI_SYSTEM_PATH,
    CLOUDCLI_TITLE,
    CLOUDCLI_UPSTREAM_HOST,
    CLOUDCLI_VERSION,
    CLOUDCLI_WINDOWS_INSTALL_LIMIT_S,
    CLOUDCLI_WINDOWS_NPM_PATH,
    CLOUDCLI_WINDOWS_SERVICE_PATH,
)
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
)
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_LOGON_FAILURES,
    ACCOUNT_SERVICE_WINDOWS_SCRIPT_DIR_NAME,
    ACCOUNT_SERVICE_WINDOWS_SHELL,
)
from neutrino_agent.modules.shared.account_service.windows import task_arguments
from neutrino_agent.modules.shared.http_forward import (
    RELAY,
    ForwardDecision,
    answered,
    refused,
    unpadded_decode,
)
from neutrino_agent.modules.shared.instances import InstanceHooks
from neutrino_agent.modules.shared.powershell_run import listed
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.modules.shared.unpacked_tree import (
    extract_archive,
    remove_tree,
    seal_tree,
)

# The words in npm's output that say a native module could not get its
# binary: prebuild-install gave up, and node-gyp could not build it either.
NATIVE_FAILURE_WORDS = ("gyp", "prebuild")
# The lines of npm's output that are its tools' own account of a failure.
FAILURE_LINE_WORDS = ("prebuild-install", "gyp err", "npm error", "npm err!")
# The registry npm uses when the state names none.
NPM_DEFAULT_REGISTRY_HOST = "registry.npmjs.org"
# The exit status the native check ends with, the module's name printed.
NATIVE_CHECK_EXIT = 3
NATIVE_CHECK_SCRIPT = (
    "const load = require('module').createRequire(process.cwd() + '/'); "
    "for (const name of [%s]) { try { load(name) } catch (error) "
    "{ console.log(name); process.exit(%d) } }"
    % (",".join("'%s'" % name for name in CLOUDCLI_NATIVE_MODULES), NATIVE_CHECK_EXIT)
)
# What an account's install runs under ``sh``: the app directory and the
# empty npm configuration made as the account, then npm.
INSTALL_SHELL = (
    'mkdir -p "$0" && rm -rf "$0/node_modules" && : > "$0/.npmrc" && exec "$@"'
)
CHECK_SHELL = 'cd "$0" && exec "$@"'
# What a Windows install script exits with when npm failed; a native
# module's failure exits with the native check's own status.
NPM_FAILED_EXIT = 1
# The task states of an install that has not ended.
INSTALL_RUNNING_STATES = ("Running", "Queued")
# What one account's install step found: CloudCLI already there, installed
# by a task that just ended, or a task still running.
INSTALL_READY = "ready"
INSTALL_FINISHED = "finished"
INSTALL_RUNNING = "running"
# The page that keeps CloudCLI's login and goes to CloudCLI's own.
EXCHANGE_PAGE = (
    '<!doctype html><meta charset="utf-8"><title>CloudCLI</title>'
    "<script>localStorage.setItem(%s, %s);location.replace('/');</script>"
)

# Writes an account's install script and starts it as a task with the
# account's login, leaving it to run.
INSTALL_SCRIPT = """
$dir = Split-Path -Parent $d.script
if (-not (Test-Path -LiteralPath $dir)) {
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
[IO.File]::WriteAllText($d.script, $d.script_text)
[IO.File]::WriteAllText($d.log, '')
foreach ($file in @($d.script, $d.log)) {
  $code = Invoke-Icacls $file /inheritance:r /grant:r "$($d.account):M" `
    '*S-1-5-18:F' '*S-1-5-32-544:F'
  if ($code -ne 0) { throw "icacls refused $file" }
}
$action = New-ScheduledTaskAction -Execute $d.program -Argument $d.arguments
$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Seconds $d.timeout_s) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
try {
  Register-ScheduledTask -TaskName $d.task -Action $action -Settings $settings `
    -User $d.account -Password $d.password -RunLevel Limited -Force | Out-Null
} catch {
  if (Test-LogonRefused $_) {
    Send-Refusal 'credential_invalid' @{account = $d.account}
  }
  throw
}
Start-ScheduledTask -TaskName $d.task
'{}'
"""

# Unregisters an account's ended install task, deletes its script, and
# answers the end of its output.
FINISH_INSTALL_SCRIPT = """
Unregister-ScheduledTask -TaskName $d.task -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $d.script -Force -ErrorAction SilentlyContinue
$output = ''
if (Test-Path -LiteralPath $d.log) { $output = [IO.File]::ReadAllText($d.log) }
if ($output.Length -gt 8000) { $output = $output.Substring($output.Length - 8000) }
@{output = $output} | ConvertTo-Json -Compress -Depth 4
"""

# Each install task: its state and its last result.
INSTALL_STATUS_SCRIPT = """
$tasks = @()
foreach ($task in @(Get-ScheduledTask -TaskName "$($d.prefix)*" -ErrorAction SilentlyContinue)) {
  $info = Get-ScheduledTaskInfo -TaskName $task.TaskName
  $tasks += @{name = $task.TaskName; state = "$($task.State)";
    last_result = [int64]$info.LastTaskResult}
}
@{tasks = $tasks} | ConvertTo-Json -Compress -Depth 4
"""


def unpack_node(path: str, *, package_kind: str, root: str) -> str:
    """Put the Node.js archive's one directory under the module's root.

    Any other Node.js the root holds is removed, and what lands is owned by
    the agent's own account and read-only.

    Args:
        path: The archive on disk.
        package_kind: ``tar`` or ``zip``.
        root: The module's directory.

    Returns:
        The Node.js directory.

    Raises:
        ModuleApplyError: ``cloudcli_node_download_failed`` when the kind is
            unknown, the archive cannot be read, or it holds no Node.js.
        OSError: When the root cannot be written.
    """
    os.makedirs(root, mode=0o755, exist_ok=True)
    os.chmod(root, 0o755)
    staging = tempfile.mkdtemp(prefix=".unpack_", dir=root)
    try:
        try:
            extract_archive(path, package_kind, staging)
        except (OSError, tarfile.TarError, zipfile.BadZipFile, ValueError) as error:
            raise ModuleApplyError(
                CLOUDCLI_NODE_DOWNLOAD_FAILED, {"detail": str(error)[:200]}
            ) from error
        names = [
            name
            for name in os.listdir(staging)
            if name.startswith(CLOUDCLI_NODE_PREFIX)
            and os.path.isdir(os.path.join(staging, name))
        ]
        if len(names) != 1:
            raise ModuleApplyError(
                CLOUDCLI_NODE_DOWNLOAD_FAILED,
                {"detail": "the archive holds no single Node.js directory"},
            )
        for held in os.listdir(root):
            if held.startswith(CLOUDCLI_NODE_PREFIX):
                remove_tree(os.path.join(root, held))
        target = os.path.join(root, names[0])
        os.replace(os.path.join(staging, names[0]), target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    seal_tree(target)
    return target


def node_dir(root: str) -> str:
    """The Node.js directory under the module's root.

    Args:
        root: The module's directory.

    Returns:
        Its path, empty when none is there.
    """
    try:
        names = sorted(
            name for name in os.listdir(root) if name.startswith(CLOUDCLI_NODE_PREFIX)
        )
    except OSError:
        return ""
    return os.path.join(root, names[-1]) if names else ""


def node_path(directory: str, os_name: str, join=os.path.join) -> str:
    """The interpreter inside one Node.js directory."""
    return join(directory, *CLOUDCLI_NODE_PARTS[os_name])


def npm_path(directory: str, os_name: str, join=os.path.join) -> str:
    """npm's script inside one Node.js directory."""
    return join(directory, *CLOUDCLI_NPM_PARTS[os_name])


def account_dir(home: str, os_name: str, join=os.path.join) -> str:
    """One account's CloudCLI directory, under its home.

    Args:
        home: The account's home.
        os_name: The system.
        join: How the system joins a path.

    Returns:
        The directory the app directory and the database live in.
    """
    return join(home, *CLOUDCLI_ACCOUNT_PARTS[os_name])


def app_dir(home: str, os_name: str, join=os.path.join) -> str:
    """One account's app directory, which npm installs CloudCLI into."""
    return join(account_dir(home, os_name, join), CLOUDCLI_APP_DIR_NAME)


def database_path(
    home: str, os_name: str, join=os.path.join, name: str = CLOUDCLI_DATABASE_NAME
) -> str:
    """Where one account's CloudCLI keeps its database, ``auth.db`` unless named."""
    return join(account_dir(home, os_name, join), name)


def server_path(app: str, join=os.path.join) -> str:
    """The server script an app directory runs."""
    return join(app, *CLOUDCLI_PACKAGE_PARTS, *CLOUDCLI_SERVER_PARTS)


def installed_version(app: str) -> str:
    """The CloudCLI version an app directory holds.

    Args:
        app: The app directory.

    Returns:
        The version its ``package.json`` names, empty when there is none.
    """
    path = os.path.join(app, *CLOUDCLI_PACKAGE_PARTS, "package.json")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return str(json.load(stream).get("version", "") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def is_app_ready(app: str) -> bool:
    """Whether an app directory holds CloudCLI at its pinned version and its native modules.

    Args:
        app: The app directory.

    Returns:
        True when the package names the pinned version and every native
        module has its ``package.json`` beside it or inside it.
    """
    if installed_version(app) != CLOUDCLI_VERSION:
        return False
    package = os.path.join(app, *CLOUDCLI_PACKAGE_PARTS)
    places = (os.path.join(app, "node_modules"), os.path.join(package, "node_modules"))
    return all(
        any(
            os.path.isfile(os.path.join(place, name, "package.json"))
            for place in places
        )
        for name in CLOUDCLI_NATIVE_MODULES
    )


def npm_environment(
    app: str, join=os.path.join, *, registry: str = "", extra: "dict | None" = None
) -> dict:
    """What npm runs with besides ``PATH`` and the account's own names.

    Args:
        app: The app directory.
        join: How the system joins a path.
        registry: The registry the hub's state names; empty for npm's own.
        extra: More ``npm_config_*`` settings the hub's state names.

    Returns:
        npm's cache inside the app directory, an empty file as the
        account's configuration, no audit, funding or update notes, the
        registry when one is named, and the state's other settings.
    """
    environment = {
        "npm_config_cache": join(app, CLOUDCLI_NPM_CACHE_NAME),
        "npm_config_userconfig": join(app, CLOUDCLI_NPM_USERCONFIG_NAME),
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
    }
    if registry:
        environment["npm_config_registry"] = registry
    for name, value in (extra or {}).items():
        environment.setdefault(name, value)
    return environment


def npm_arguments(app: str) -> list:
    """npm's own arguments for one app directory."""
    return ["install", f"{CLOUDCLI_PACKAGE}@{CLOUDCLI_VERSION}", "--prefix", app]


def npm_failure(output: str, account: str) -> ModuleApplyError:
    """Which step an install that failed failed at, in the tools' own words.

    Args:
        output: What npm printed.
        account: The account it ran as.

    Returns:
        ``cloudcli_native_module_failed {account, module, detail}`` when a
        native module could not get its binary, else
        ``cloudcli_npm_install_failed {account, detail}``; ``detail`` is the
        last lines prebuild-install, node-gyp and npm wrote about it.
    """
    detail = failure_detail(output)
    lowered = output.lower()
    if any(word in lowered for word in NATIVE_FAILURE_WORDS):
        for name in CLOUDCLI_NATIVE_MODULES:
            if name in lowered:
                return ModuleApplyError(
                    "cloudcli_native_module_failed",
                    {"account": account, "module": name, "detail": detail},
                )
    return ModuleApplyError(
        "cloudcli_npm_install_failed", {"account": account, "detail": detail}
    )


def failure_detail(output: str) -> str:
    """The last lines an installer's tools wrote about a failure.

    Args:
        output: What npm printed.

    Returns:
        Up to four lines naming prebuild-install, node-gyp or npm's own
        errors, joined by `` | ``; the output's last line when none does.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    named = [
        line
        for line in lines
        if any(word in line.lower() for word in FAILURE_LINE_WORDS)
    ]
    kept = named[-CLOUDCLI_FAILURE_LINES:] or lines[-1:]
    return " | ".join(kept)[-CLOUDCLI_FAILURE_DETAIL_CHARS:]


def registry_host(registry: str) -> str:
    """The host npm fetches from, for the install's log line.

    Args:
        registry: The registry the state names; empty for npm's own.

    Returns:
        The registry's host name.
    """
    return urllib.parse.urlsplit(registry).hostname or NPM_DEFAULT_REGISTRY_HOST


def service_environment(
    instance,
    *,
    upstream_port: int,
    home: str,
    os_name: str,
    node_dir: str = "",
    join=os.path.join,
    database_name: str = CLOUDCLI_DATABASE_NAME,
) -> dict:
    """The environment one instance's CloudCLI runs with, written from scratch.

    Args:
        instance: The :class:`CloudcliInstance`.
        upstream_port: The loopback port CloudCLI listens on.
        home: The account's home.
        os_name: The system.
        node_dir: The directory Node.js is in; it leads ``PATH``.
        join: How the system joins a path.
        database_name: The database file the instance runs on.

    Returns:
        ``HOST``, ``SERVER_PORT``, ``JWT_SECRET``, ``DATABASE_PATH``, and
        ``PATH``; on Linux and macOS also ``HOME``. On Windows ``PATH`` is
        set only with a Node directory. Nothing names the gateway.
    """
    environment = {
        "HOST": CLOUDCLI_UPSTREAM_HOST,
        "SERVER_PORT": str(int(upstream_port)),
        "JWT_SECRET": jwt_secret(instance.token_secret),
        "DATABASE_PATH": database_path(home, os_name, join, database_name),
    }
    if os_name == "windows":
        if node_dir:
            environment["PATH"] = ";".join([node_dir, *CLOUDCLI_WINDOWS_SERVICE_PATH])
        return environment
    environment["HOME"] = home
    environment["PATH"] = ":".join(
        ([node_dir] if node_dir else [])
        + [os.path.join(home, part) for part in CLOUDCLI_ACCOUNT_PATH_PARTS]
        + list(CLOUDCLI_SYSTEM_PATH.get(os_name, ()))
    )
    return environment


def render_install_script(
    *, app: str, node: str, npm: str, registry: str = "", extra: "dict | None" = None
) -> str:
    """The script an account's Windows install task runs.

    Args:
        app: The account's app directory.
        node: The Node.js interpreter.
        npm: npm's script.
        registry: The registry npm installs from; empty for npm's own.
        extra: More ``npm_config_*`` settings the hub's state names.

    Returns:
        The ``.cmd`` text, CRLF line ends: the app directory and the empty
        npm configuration made, Node's directory leading ``PATH``, npm run,
        then the native check, exiting with npm's failure or the check's.
    """
    environment = {
        "PATH": ";".join([ntpath.dirname(node), *CLOUDCLI_WINDOWS_NPM_PATH]),
        **npm_environment(app, join=ntpath.join, registry=registry, extra=extra),
    }
    lines = ["@echo off", f'if not exist "{app}" mkdir "{app}"']
    lines.append(f'type nul > "{environment["npm_config_userconfig"]}"')
    lines += [f'set "{name}={value}"' for name, value in environment.items()]
    lines.append(
        subprocess.list2cmdline([node, npm, *npm_arguments(app)])
        + f" || exit /b {NPM_FAILED_EXIT}"
    )
    lines.append(f'cd /d "{app}"')
    lines.append(f'"{node}" -e "{NATIVE_CHECK_SCRIPT}"')
    return "\r\n".join(lines) + "\r\n"


def is_login_valid(login: str, secret: str, now: float) -> bool:
    """Whether a CloudCLI login is signed with the secret and still current.

    Args:
        login: The JWT.
        secret: The secret CloudCLI signs with, from :func:`jwt_secret`.
        now: Seconds since the epoch.

    Returns:
        True for an HS256 JWT whose signature matches and whose ``exp`` is
        ahead.
    """
    parts = login.split(".")
    if len(parts) != 3:
        return False
    try:
        header = json.loads(unpadded_decode(parts[0]))
        payload = json.loads(unpadded_decode(parts[1]))
        signature = unpadded_decode(parts[2])
    except (ValueError, binascii.Error):
        return False
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{parts[0]}.{parts[1]}".encode("ascii", "replace"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, signature):
        return False
    expiry = payload.get("exp") if isinstance(payload, dict) else None
    return isinstance(expiry, (int, float)) and expiry > now


def cookie_name(port: int) -> str:
    """The cookie the forwarder of one port keeps CloudCLI's login in."""
    return f"{CLOUDCLI_COOKIE_PREFIX}{int(port)}"


def free_loopback_port() -> int:
    """A port nothing listens on at the loopback address, as the system picks one.

    Returns:
        The port.

    Raises:
        OSError: When the system gives none.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((CLOUDCLI_UPSTREAM_HOST, 0))
        return int(probe.getsockname()[1])


def _normal_path(path: str) -> str:
    """A path as CloudCLI's router matches it: decoded, lower case, slashes collapsed."""
    decoded = urllib.parse.unquote(path).lower()
    while "//" in decoded:
        decoded = decoded.replace("//", "/")
    return decoded.rstrip("/") or "/"


def _run_as_account(
    entry: AccountEntry, command: list, *, environment: dict, timeout_s
):
    """Run one command as an account on a Mac, in its home, with this environment alone."""
    completed = subprocess.run(
        command,
        user=entry.uid,
        group=entry.gid,
        extra_groups=[],
        cwd=entry.home,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return CommandResult(
        list(command), completed.returncode, completed.stdout, completed.stderr
    )


class CloudcliHooks(InstanceHooks):
    """CloudCLI's part of the shared runner."""

    name = CLOUDCLI_NAME
    title = CLOUDCLI_TITLE
    kind = CLOUDCLI_KIND
    download_failure_code = CLOUDCLI_NODE_DOWNLOAD_FAILED
    instance_class = CloudcliInstance
    record_fields = CLOUDCLI_RECORD_FIELDS
    forwarder_fields = CLOUDCLI_FORWARDER_FIELDS
    secret_field = "token_secret"

    def __init__(
        self, *, platform, log=print, run_as=None, pick_port=None, clock=time.time
    ):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            run_as: Called with ``(entry, command, environment=,
                timeout_s=)`` on a Mac; runs a command as the account and
                returns a ``CommandResult``. None runs it.
            pick_port: Returns a free loopback port for a new instance; None
                asks the system.
            clock: Seconds since the epoch, which a login is judged by.
        """
        super().__init__(platform=platform, log=log)
        self._run_as = run_as if run_as is not None else _run_as_account
        self._pick_port = pick_port if pick_port is not None else free_loopback_port
        self._clock = clock
        # The accounts whose CloudCLI refused this hub's password and were
        # told to start afresh.
        self._refused: set = set()
        # The install tasks Windows holds, read once per apply.
        self._install_tasks: dict = {}
        # The npm registry and settings of the configuration being applied.
        self._registry = ""
        self._npm_extra: dict = {}

    @property
    def node(self) -> str:
        """The Node.js interpreter, empty when none is unpacked."""
        directory = node_dir(self.machine.module_dir)
        return node_path(directory, self._os_name, self._join) if directory else ""

    def parse(self, config: dict) -> CloudcliConfig:
        """The configuration parsed and checked for this system.

        Args:
            config: The module's desired configuration.

        Returns:
            The configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        parsed = CloudcliConfig.from_dict(config)
        parsed.validate(os_name=self._os_name)
        return parsed

    def verify(self) -> bool:
        """Whether the interpreter's file exists."""
        node = self.node
        return bool(node) and os.path.isfile(node)

    def install(self, package_path: str, package_kind: str) -> None:
        """Unpack the Node.js the hub handed down.

        Args:
            package_path: The archive on local disk.
            package_kind: ``tar`` or ``zip``.

        Raises:
            ModuleApplyError: ``cloudcli_node_download_failed`` when the
                archive is not one Node.js comes in.
            OSError: When the module's directory cannot be written.
        """
        unpack_node(
            package_path, package_kind=package_kind, root=self.machine.module_dir
        )

    def prepare_module(self) -> list:
        """On Windows, read every install task once for this apply.

        Returns:
            Nothing changed.

        Raises:
            OSError: When PowerShell fails.
        """
        if self._os_name == "windows":
            read = self.machine.powershell(
                INSTALL_STATUS_SCRIPT, {"prefix": CLOUDCLI_INSTALL_TASK_PREFIX}
            )
            self._install_tasks = {
                str(entry.get("name", "")): entry
                for entry in listed(read.get("tasks"))
                if isinstance(entry, dict)
            }
            self.installing = frozenset()
        return []

    def prepare(
        self, parsed: CloudcliConfig, instance: CloudcliInstance, entry: AccountEntry
    ) -> list:
        """Install CloudCLI into the account's app directory unless it is there.

        Args:
            parsed: The configuration, whose npm registry and settings npm runs with.
            instance: The instance.
            entry: Its account.

        Returns:
            One note when CloudCLI was installed.

        Raises:
            ModuleApplyError: ``cloudcli_npm_install_failed``,
                ``cloudcli_install_out_of_memory``,
                ``cloudcli_native_module_failed`` or ``credential_invalid``,
                each naming the account.
            OSError: When a command cannot run, or PowerShell fails.
            subprocess.SubprocessError: When a command does not finish.
        """
        account = instance.account
        self._registry = parsed.npm_registry
        self._npm_extra = dict(parsed.npm_environment)
        if self._os_name == "windows":
            step = self._install_windows(instance, entry.home)
            if step == INSTALL_RUNNING:
                self.installing = frozenset(self.installing | {account})
                return []
            self.installing = frozenset(self.installing - {account})
            return (
                [f"installed CloudCLI for {account}"]
                if step == INSTALL_FINISHED
                else []
            )
        app = app_dir(entry.home, self._os_name)
        if installed_version(app) == CLOUDCLI_VERSION:
            return []
        self.installing = frozenset({account})
        try:
            if self._os_name == "linux":
                self._install_linux(account, entry.home, app)
            else:
                self._install_darwin(account, entry, app)
        finally:
            self.installing = frozenset()
        return [f"installed CloudCLI for {account}"]

    def record(
        self, parsed: CloudcliConfig, instance: CloudcliInstance, held: dict
    ) -> dict:
        """One instance's record: its ports, its secrets and the database it runs on.

        Args:
            parsed: The configuration.
            instance: The instance.
            held: The record held before; its loopback port and its
                database are kept.

        Returns:
            The record.
        """
        return {
            "account": instance.account,
            "port": instance.port,
            "upstream_port": int(held.get("upstream_port") or 0) or self._pick_port(),
            "web_password": instance.web_password,
            "token_secret": instance.token_secret,
            "database": str(held.get("database") or CLOUDCLI_DATABASE_NAME),
        }

    def service(
        self, instance: CloudcliInstance, entry: AccountEntry, record: dict
    ) -> AccountService:
        """Node.js with the account's server script, from an environment written from scratch.

        Args:
            instance: The instance.
            entry: Its account.
            record: Its record, whose loopback port and database the
                environment names.

        Returns:
            The service, its environment root-only.
        """
        node = self.node
        join = self._join
        environment = service_environment(
            instance,
            upstream_port=int(record.get("upstream_port") or 0),
            home=entry.home,
            os_name=self._os_name,
            node_dir=self._dirname(node),
            join=join,
            database_name=str(record.get("database") or CLOUDCLI_DATABASE_NAME),
        )
        server = server_path(app_dir(entry.home, self._os_name, join), join)
        if self._os_name == "linux":
            environment[CLOUDCLI_SERVER_VARIABLE] = server
            command = (node, f"${{{CLOUDCLI_SERVER_VARIABLE}}}")
        else:
            command = (node, server)
        return AccountService(
            name=self.name,
            title=self.title,
            account=instance.account,
            command=command,
            environment=environment,
            working_directory="~",
            password=instance.password,
            is_environment_secret=True,
        )

    def on_first_start(self, record: dict) -> str:
        """Register CloudCLI's administrator when it has none, and sign in.

        A CloudCLI that has its administrator and refuses the hub's password
        was set up for another hub: the instance is told once to start
        afresh on a new database.

        Args:
            record: The instance's record.

        Returns:
            Empty when the account signs in with the hub's password, else
            ``cloudcli_register_failed``.

        Raises:
            OSError: When CloudCLI does not answer.
        """
        account = str(record.get("account", "") or "")
        status, answer = self._call(record, "GET", CLOUDCLI_STATUS_PATH)
        if status != 200:
            raise ConnectionError(f"CloudCLI answered {status}")
        is_new = answer.get("needsSetup") is True
        if is_new:
            status, _ = self._call(
                record, "POST", CLOUDCLI_REGISTER_PATH, self._credentials(record)
            )
            if status == 200:
                self._log(f"{self.name}: registered the administrator of {account}")
        if self._login(record):
            self._refused.discard(account)
            return ""
        if not is_new and account not in self._refused and self._reapply is not None:
            self._refused.add(account)
            stamp = time.strftime(CLOUDCLI_FRESH_STAMP_FORMAT, time.gmtime())
            database = CLOUDCLI_FRESH_DATABASE_PATTERN.format(stamp=stamp)
            self._log(
                f"{self.name}: {account}'s CloudCLI refuses this hub's password; "
                f"it starts afresh on {database}"
            )
            self._reapply(account, database=database)
        return CLOUDCLI_REGISTER_FAILED

    def admit(self, request, record: dict) -> ForwardDecision:
        """The forwarder's rule: the auth routes are blocked, a token trades for CloudCLI's login, the login passes.

        Args:
            request: The request.
            record: The instance's record.

        Returns:
            401 for CloudCLI's register and login routes and for a request
            with neither a token nor a login; the page that keeps CloudCLI's
            login for a token that verifies, 502 when CloudCLI refuses it;
            the relay for a login CloudCLI issued.
        """
        if _normal_path(request.path) in CLOUDCLI_BLOCKED_PATHS:
            return refused()
        if request.token:
            if not request.take_token():
                return refused()
            try:
                login = self._login(record)
            except OSError:
                login = ""
            if not login:
                return answered(502)
            page = EXCHANGE_PAGE % (json.dumps(CLOUDCLI_STORAGE_KEY), json.dumps(login))
            port = int(record.get("port", 0) or 0)
            cookie = (
                f"{cookie_name(port)}={login}; Path=/; HttpOnly; "
                f"SameSite=Lax; Max-Age={CLOUDCLI_LOGIN_LIFETIME_S}"
            )
            return answered(
                200,
                page.encode("utf-8"),
                content_type="text/html; charset=utf-8",
                headers=(
                    ("Set-Cookie", cookie),
                    ("Cache-Control", "no-store"),
                    ("Referrer-Policy", "no-referrer"),
                ),
            )
        if self._has_login(request, record):
            return RELAY
        return refused()

    def connect(self, record: dict) -> socket.socket:
        """A connection to CloudCLI on loopback.

        Args:
            record: The instance's record.

        Returns:
            The connected socket.

        Raises:
            OSError: When CloudCLI does not answer.
        """
        return socket.create_connection(
            (CLOUDCLI_UPSTREAM_HOST, int(record.get("upstream_port", 0) or 0)),
            timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
        )

    def install_log(self, account: str) -> str:
        """The log of the Windows install task that runs for one account.

        Args:
            account: The account.

        Returns:
            The file's path while the task runs, else empty.
        """
        if self._os_name != "windows" or account not in self.installing:
            return ""
        return self._install_log_path(account)

    @property
    def _os_name(self) -> str:
        return self._platform.os_name

    def _join(self, *parts: str) -> str:
        return (ntpath.join if self._os_name == "windows" else os.path.join)(*parts)

    def _dirname(self, path: str) -> str:
        return (ntpath.dirname if self._os_name == "windows" else os.path.dirname)(path)

    def _install_linux(self, account: str, home: str, app: str) -> None:
        """Run npm as the account in a transient service, then check the native modules."""
        node = self.node
        node_bin = os.path.dirname(node)
        environment = {
            "HOME": home,
            "USER": account,
            "LOGNAME": account,
            "PATH": ":".join([node_bin, *CLOUDCLI_INSTALL_PATH["linux"]]),
            **self._npm_environment(app),
        }
        prefix = ["runuser", "-u", account, "--", "env", "-i"] + [
            f"{name}={value}" for name, value in environment.items()
        ]
        npm = npm_path(os.path.dirname(node_bin), "linux")
        self._log_install(account)
        unit = f"{CLOUDCLI_INSTALL_UNIT_PREFIX}{account}.service"
        run = self.machine.run
        run(["systemctl", "reset-failed", unit], is_checked=False)
        result = run(
            [
                "systemd-run",
                f"--unit={unit}",
                "--quiet",
                "--wait",
                "--pipe",
                "-p",
                "OOMPolicy=stop",
                "--",
            ]
            + prefix
            + ["sh", "-c", INSTALL_SHELL, app, node, npm]
            + npm_arguments(app),
            is_checked=False,
            timeout_s=CLOUDCLI_INSTALL_TIMEOUT_S,
        )
        if not result.is_success:
            output = (result.stdout + "\n" + result.stderr).strip()
            self._log(f"{self.name}: npm for {account}: {output[-2000:]}")
            if self._is_out_of_memory(unit):
                raise ModuleApplyError(
                    "cloudcli_install_out_of_memory", {"account": account}
                )
            raise npm_failure(output, account)
        check = run(
            prefix + ["sh", "-c", CHECK_SHELL, app, node, "-e", NATIVE_CHECK_SCRIPT],
            is_checked=False,
            timeout_s=CLOUDCLI_LOOKUP_TIMEOUT_S,
        )
        self._check_native(check, account)

    def _install_darwin(self, account: str, entry: AccountEntry, app: str) -> None:
        """Run npm as the account, then check the native modules."""
        node = self.node
        node_bin = os.path.dirname(node)
        environment = {
            "HOME": entry.home,
            "USER": account,
            "LOGNAME": account,
            "PATH": ":".join([node_bin, *CLOUDCLI_INSTALL_PATH["darwin"]]),
            **self._npm_environment(app),
        }
        npm = npm_path(os.path.dirname(node_bin), "darwin")
        self._log_install(account)
        result = self._run_as(
            entry,
            ["/bin/sh", "-c", INSTALL_SHELL, app, node, npm] + npm_arguments(app),
            environment=environment,
            timeout_s=CLOUDCLI_INSTALL_TIMEOUT_S,
        )
        if not result.is_success:
            output = (result.stdout + "\n" + result.stderr).strip()
            self._log(f"{self.name}: npm for {account}: {output[-2000:]}")
            raise npm_failure(output, account)
        check = self._run_as(
            entry,
            ["/bin/sh", "-c", CHECK_SHELL, app, node, "-e", NATIVE_CHECK_SCRIPT],
            environment=environment,
            timeout_s=CLOUDCLI_LOOKUP_TIMEOUT_S,
        )
        self._check_native(check, account)

    def _install_windows(self, instance: CloudcliInstance, home: str) -> str:
        """Judge an account's install task, or start one when CloudCLI is not there.

        Returns:
            ``INSTALL_READY``, ``INSTALL_FINISHED`` or ``INSTALL_RUNNING``.

        Raises:
            ModuleApplyError: The step an ended install failed at.
        """
        account = instance.account
        app = app_dir(home, "windows", join=ntpath.join)
        name = CLOUDCLI_INSTALL_TASK_PREFIX + account
        script = self._install_script_path(account)
        log_file = self._install_log_path(account)
        task = self._install_tasks.get(name)
        if task is not None:
            if str(task.get("state", "")) in INSTALL_RUNNING_STATES:
                return INSTALL_RUNNING
            self._judge_install(task, app, name, script, log_file, account)
            return INSTALL_FINISHED
        if is_app_ready(app):
            return INSTALL_READY
        node = self.node
        npm = npm_path(ntpath.dirname(node), "windows", ntpath.join)
        self.machine.powershell(
            INSTALL_SCRIPT,
            {
                "account": account,
                "password": instance.password,
                "task": name,
                "script": script,
                "script_text": render_install_script(
                    app=app,
                    node=node,
                    npm=npm,
                    registry=self._registry,
                    extra=self._npm_extra,
                ),
                "log": log_file,
                "program": ACCOUNT_SERVICE_WINDOWS_SHELL,
                "arguments": task_arguments(script, [], log_file),
                "timeout_s": CLOUDCLI_WINDOWS_INSTALL_LIMIT_S,
            },
        )
        self._log(f"{self.name}: installing CloudCLI for {account}")
        return INSTALL_RUNNING

    def _judge_install(
        self, task: dict, app: str, name: str, script: str, log_file: str, account: str
    ) -> None:
        """Unregister an ended install task and raise the step it failed at."""
        answer = self.machine.powershell(
            FINISH_INSTALL_SCRIPT, {"task": name, "script": script, "log": log_file}
        )
        output = str(answer.get("output", "") or "")
        result = int(task.get("last_result", 0) or 0) & 0xFFFFFFFF
        if result in ACCOUNT_SERVICE_LOGON_FAILURES:
            raise ModuleApplyError("credential_invalid", {"account": account})
        if result == NATIVE_CHECK_EXIT:
            lines = output.strip().splitlines()
            raise ModuleApplyError(
                "cloudcli_native_module_failed",
                {
                    "account": account,
                    "module": lines[-1] if lines else "",
                    "detail": failure_detail(output),
                },
            )
        if result != 0 or not is_app_ready(app):
            raise npm_failure(output, account)

    def _install_script_path(self, account: str) -> str:
        return ntpath.join(
            self.machine.module_dir,
            ACCOUNT_SERVICE_WINDOWS_SCRIPT_DIR_NAME,
            CLOUDCLI_INSTALL_SCRIPT_PATTERN.format(account=account),
        )

    def _install_log_path(self, account: str) -> str:
        return ntpath.join(
            self.machine.module_dir,
            ACCOUNT_SERVICE_WINDOWS_SCRIPT_DIR_NAME,
            CLOUDCLI_INSTALL_LOG_PATTERN.format(account=account),
        )

    def _check_native(self, check, account: str) -> None:
        """Raise the native module the check found without its binary."""
        if check.exit_code == NATIVE_CHECK_EXIT:
            raise ModuleApplyError(
                "cloudcli_native_module_failed",
                {
                    "account": account,
                    "module": check.stdout.strip(),
                    "detail": failure_detail(check.stderr),
                },
            )

    def _is_out_of_memory(self, unit: str) -> bool:
        """Whether the kernel killed an install's service for want of memory; forgets the unit."""
        run = self.machine.run
        shown = run(
            ["systemctl", "show", "-p", "Result", "--value", unit], is_checked=False
        )
        run(["systemctl", "reset-failed", unit], is_checked=False)
        return shown.stdout.strip() == CLOUDCLI_OOM_RESULT

    def _npm_environment(self, app: str) -> dict:
        return npm_environment(app, registry=self._registry, extra=self._npm_extra)

    def _log_install(self, account: str) -> None:
        self._log(
            f"{self.name}: installing CloudCLI for {account} "
            f"from {registry_host(self._registry)}"
        )

    def _credentials(self, record: dict) -> dict:
        return {
            "username": username_of(str(record.get("account", "") or "")),
            "password": str(record.get("web_password", "") or ""),
        }

    def _has_login(self, request, record: dict) -> bool:
        """Whether a request carries a login CloudCLI issued and still honours."""
        secret = jwt_secret(str(record.get("token_secret", "") or ""))
        now = self._clock()
        candidates = list(request.query.get(CLOUDCLI_QUERY_TOKEN, []))
        for name, value in request.headers:
            if name.lower() == "authorization":
                scheme, _, credential = value.strip().partition(" ")
                if scheme.lower() == "bearer":
                    candidates.append(credential.strip())
        candidates += request.cookie_values(
            cookie_name(int(record.get("port", 0) or 0))
        )
        return any(is_login_valid(candidate, secret, now) for candidate in candidates)

    def _login(self, record: dict) -> str:
        """CloudCLI's login for the administrator, empty when it refuses; OSError when it does not answer."""
        status, answer = self._call(
            record, "POST", CLOUDCLI_LOGIN_PATH, self._credentials(record)
        )
        if status != 200:
            return ""
        return str(answer.get("token", "") or "")

    def _call(
        self, record: dict, method: str, path: str, body: "dict | None" = None
    ) -> tuple:
        """``(status, answer)`` of one call to CloudCLI's JSON API; OSError when it does not answer."""
        connection = http.client.HTTPConnection(
            CLOUDCLI_UPSTREAM_HOST,
            int(record.get("upstream_port", 0) or 0),
            timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
        )
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            connection.request(
                method,
                path,
                body=payload,
                headers={"Content-Type": "application/json"} if payload else {},
            )
            response = connection.getresponse()
            text = response.read()
            status = response.status
        except http.client.HTTPException as error:
            raise ConnectionError(str(error)) from error
        finally:
            connection.close()
        try:
            answer = json.loads(text.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            answer = {}
        return status, answer if isinstance(answer, dict) else {}
