"""What CloudCLI adds to the shared runner: Node.js, each account's npm install, the login.

Node.js comes from the hub's package stream as the archive nodejs.org
publishes, the module's ``node`` artifact, which the shared unpack puts
under ``node`` in the module's own directory, never on a ``PATH``.
Before an instance first runs, its account's ``npm {account}`` step
installs the recipe's npm artifact into its own app directory with that
Node.js: as a transient service on Linux, so a kill for want of memory ends
it and not the agent, its output in a log systemd opens, since SELinux on
Rocky 9 rejects the agent's pipes that ``--pipe`` passes; as the account's
own process on macOS; as a task of its own on Windows, left running and
judged when the step runs again. The registries of the state's ``npm``
source set that name the pinned integrity are tried fastest first, each with
the hosts of the npm settings fastest first, until one install takes. Each instance runs Node.js with the account's server script,
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
import contextlib
import hashlib
import hmac
import http.client
import json
import ntpath
import os
import socket
import subprocess
import time
import urllib.parse

from neutrino_agent.constants import AGENT_FORWARD_UPSTREAM_TIMEOUT_S, AGENT_STEP_NPM
from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.cloudcli.config import (
    CloudcliConfig,
    CloudcliInstance,
    jwt_secret,
    username_of,
)
from neutrino_agent.modules.cloudcli.constants import (
    CLOUDCLI_BASE_PORT,
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
    CLOUDCLI_INSTALL_POLL_S,
    CLOUDCLI_INSTALL_RUNNING_STATES,
    CLOUDCLI_INSTALL_SCRIPT_PATTERN,
    CLOUDCLI_INSTALL_TASK_PREFIX,
    CLOUDCLI_INSTALL_TIMEOUT_S,
    CLOUDCLI_INSTALL_UNIT_PREFIX,
    CLOUDCLI_RUNNER,
    CLOUDCLI_LOGIN_LIFETIME_S,
    CLOUDCLI_LOGIN_PATH,
    CLOUDCLI_LOOKUP_TIMEOUT_S,
    CLOUDCLI_NAME,
    CLOUDCLI_NATIVE_MODULES,
    CLOUDCLI_NODE_DIR_NAME,
    CLOUDCLI_NODE_PARTS,
    CLOUDCLI_NODE_PREFIX,
    CLOUDCLI_NPM_CACHE_NAME,
    CLOUDCLI_NPM_PARTS,
    CLOUDCLI_NPM_USERCONFIG_NAME,
    CLOUDCLI_OOM_RESULT,
    CLOUDCLI_SYSTEM_STOPPING,
    CLOUDCLI_UNIT_LOADED_TEXT,
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
    CLOUDCLI_WINDOWS_INSTALL_LIMIT_S,
    CLOUDCLI_INSTALL_OUTPUT_CHARS,
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
from neutrino_agent.modules.shared.account_service.windows import (
    remove_path,
    task_arguments,
    write_text,
)
from neutrino_agent.modules.shared.http_forward import (
    RELAY,
    ForwardDecision,
    answered,
    refused,
    unpadded_decode,
)
from neutrino_agent.modules.shared.instances import InstanceHooks
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.modules.shared import source_fetch
from neutrino_agent.modules.shared.package import npm_artifact, params_of
from neutrino_agent.modules.shared.unpacked_tree import remove_tree
from neutrino_agent.modules.shared.windows_acl import grant_account_alone

# The words in npm's output that say a native module could not get its
# binary: prebuild-install gave up, and node-gyp could not build it either.
NATIVE_FAILURE_WORDS = ("gyp", "prebuild")
# The lines of npm's output that are its tools' own account of a failure.
FAILURE_LINE_WORDS = ("prebuild-install", "gyp err", "npm error", "npm err!")
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
# module's failure exits with the native check's own status. The variable
# the script keeps the last attempt's result in, and the label each attempt
# starts at, numbered from 0.
NPM_FAILED_EXIT = 1
INSTALL_RESULT_VARIABLE = "NEUTRINO_INSTALL_RESULT"
INSTALL_ATTEMPT_LABEL = "attempt_"
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


def node_dir(root: str) -> str:
    """The Node.js directory under the module's root, the ``node`` artifact.

    Args:
        root: The module's directory.

    Returns:
        Its path, empty when none is there.
    """
    directory = os.path.join(root, CLOUDCLI_NODE_DIR_NAME)
    return directory if os.path.isdir(directory) else ""


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


def is_app_ready(app: str, version: str) -> bool:
    """Whether an app directory holds CloudCLI at a version and its native modules.

    Args:
        app: The app directory.
        version: The version the recipe names.

    Returns:
        True when the package names the version and every native module
        has its ``package.json`` beside it or inside it.
    """
    if not version or installed_version(app) != version:
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
    app: str, join=os.path.join, *, extra: "dict | None" = None
) -> dict:
    """What npm runs with besides ``PATH`` and the account's own names.

    Args:
        app: The app directory.
        join: How the system joins a path.
        extra: The ``npm_config_*`` settings the recipe's hosts name, each
            set to the host this install tries.

    Returns:
        npm's cache inside the app directory, an empty file as the
        account's configuration, no audit, funding or update notes, and
        the settings.
    """
    environment = {
        "npm_config_cache": join(app, CLOUDCLI_NPM_CACHE_NAME),
        "npm_config_userconfig": join(app, CLOUDCLI_NPM_USERCONFIG_NAME),
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
    }
    for name, value in (extra or {}).items():
        environment.setdefault(name, value)
    return environment


def npm_arguments(app: str, *, package: str, version: str, registry: str) -> list:
    """npm's own arguments for one app directory.

    Args:
        app: The app directory.
        package: The npm package.
        version: The version the recipe names.
        registry: The registry this install runs against.

    Returns:
        ``install <package>@<version> --prefix <app> --registry <registry>``.
    """
    return [
        "install",
        f"{package}@{version}",
        "--prefix",
        app,
        "--registry",
        registry,
    ]


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


def install_output(log_file: str) -> str:
    """The end of an install's output, as its log holds it.

    Args:
        log_file: The install's log.

    Returns:
        Its last characters; empty when the log is not there.
    """
    try:
        with open(log_file, "rb") as stream:
            text = stream.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return text.lstrip("\ufeff")[-CLOUDCLI_INSTALL_OUTPUT_CHARS:]


def registry_host(registry: str) -> str:
    """The host npm fetches from, for the install's log line.

    Args:
        registry: The registry this install runs against.

    Returns:
        The registry's host name, the registry itself when it names none.
    """
    return urllib.parse.urlsplit(registry).hostname or registry


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
    *, app: str, node: str, npm: str, package: str, version: str, attempts: list
) -> str:
    """The script an account's Windows install task runs.

    Args:
        app: The account's app directory.
        node: The Node.js interpreter.
        npm: npm's script.
        package: The npm package.
        version: The version the recipe names.
        attempts: ``(registry, settings)`` pairs, tried in order until one
            install takes.

    Returns:
        The ``.cmd`` text, CRLF line ends: the app directory and the empty
        npm configuration made, Node's directory leading ``PATH``, then per
        attempt its settings, npm and the native check, ending 0 at the
        first that takes and with the last one's failure otherwise: npm's,
        or the check's.
    """
    environment = {
        "PATH": ";".join([ntpath.dirname(node), *CLOUDCLI_WINDOWS_NPM_PATH]),
        **npm_environment(app, join=ntpath.join),
    }
    lines = ["@echo off", f'if not exist "{app}" mkdir "{app}"']
    lines.append(f'type nul > "{environment["npm_config_userconfig"]}"')
    lines += [f'set "{name}={value}"' for name, value in environment.items()]
    for index, (registry, settings) in enumerate(attempts):
        following = f":{INSTALL_ATTEMPT_LABEL}{index + 1}"
        lines.append(f":{INSTALL_ATTEMPT_LABEL}{index}")
        lines += [f'set "{name}={value}"' for name, value in settings.items()]
        lines.append(f'set "{INSTALL_RESULT_VARIABLE}={NPM_FAILED_EXIT}"')
        lines.append(
            subprocess.list2cmdline(
                [
                    node,
                    npm,
                    *npm_arguments(
                        app, package=package, version=version, registry=registry
                    ),
                ]
            )
            + f" || goto {following}"
        )
        lines.append(f'cd /d "{app}"')
        lines.append(f'"{node}" -e "{NATIVE_CHECK_SCRIPT}" && exit /b 0')
        lines.append(f'set "{INSTALL_RESULT_VARIABLE}={NATIVE_CHECK_EXIT}"')
    lines.append(f":{INSTALL_ATTEMPT_LABEL}{len(attempts)}")
    lines.append(f"exit /b %{INSTALL_RESULT_VARIABLE}%")
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


def cookie_name(record: dict) -> str:
    """The cookie one instance's forwarder keeps CloudCLI's login in.

    Args:
        record: The instance's record.

    Returns:
        The record's ``cookie_name``, else the module's prefix and the port.
    """
    named = str(record.get("cookie_name", "") or "")
    return named or f"{CLOUDCLI_COOKIE_PREFIX}{int(record.get('port', 0) or 0)}"


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
    runner = CLOUDCLI_RUNNER
    instance_class = CloudcliInstance
    record_fields = CLOUDCLI_RECORD_FIELDS
    forwarder_fields = CLOUDCLI_FORWARDER_FIELDS
    secret_field = "token_secret"
    base_port = CLOUDCLI_BASE_PORT
    prepare_step = AGENT_STEP_NPM

    def __init__(
        self,
        *,
        platform,
        log=print,
        run_as=None,
        pick_port=None,
        clock=time.time,
        probe=None,
        sleep=time.sleep,
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
            probe: Probes one source, as :func:`source_fetch.probe`; None
                probes over the network.
            sleep: Waits between two asks about an install left running.
        """
        super().__init__(platform=platform, log=log)
        self._run_as = run_as if run_as is not None else _run_as_account
        self._pick_port = pick_port if pick_port is not None else free_loopback_port
        self._clock = clock
        self._sleep = sleep
        self._probe = probe if probe is not None else source_fetch.probe
        # The accounts whose CloudCLI refused this hub's password and were
        # told to start afresh.
        self._refused: set = set()
        # The install tasks Windows holds, read at each account's npm step.
        self._install_tasks: dict = {}
        # The version and the npm artifact the recipe names, and the state's
        # source sets, whose ``npm`` set holds the registries.
        self._version = ""
        self._npm: dict = {}
        self._source_sets: dict = {}

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

    def take_recipe(self, recipe: dict) -> None:
        """Take the version and the npm artifact the recipe names.

        Args:
            recipe: ``{runner, method, params}``.
        """
        self._version = str(params_of(recipe).get("version", "") or "")
        self._npm = npm_artifact(recipe)

    def take_source_sets(self, source_sets: dict) -> None:
        """Take the state's source sets, the npm artifact's set among them.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """
        self._source_sets = dict(source_sets)

    def after_install(self) -> None:
        """Remove the Node.js directory an older build kept under its own name.

        Raises:
            OSError: When a directory cannot be listed.
        """
        self._remove_old_node()

    def _remove_old_node(self) -> None:
        """Remove every ``node-v*`` directory under the module directory.

        A directory whose files are still open, as the old Node is on
        Windows while an instance runs on it, stays until the next apply
        tries again.

        Raises:
            OSError: When the module directory cannot be listed.
        """
        root = self.machine.module_dir
        try:
            names = os.listdir(root)
        except OSError:
            return
        for name in names:
            if name.startswith(CLOUDCLI_NODE_PREFIX):
                remove_tree(os.path.join(root, name))

    def prepare_module(self) -> list:
        """Remove an old Node.js directory left behind, and on Windows forget
        which installs ran.

        Returns:
            Nothing changed.
        """
        self._remove_old_node()
        if self._os_name == "windows":
            self.installing = frozenset()
        return []

    def prepare(
        self, parsed: CloudcliConfig, instance: CloudcliInstance, entry: AccountEntry
    ) -> list:
        """Install CloudCLI into the account's app directory unless it is there.

        Args:
            parsed: The configuration.
            instance: The instance.
            entry: Its account.

        Returns:
            One note when CloudCLI was installed.

        Raises:
            ModuleApplyError: ``download_failed {file, sources}`` when no
                registry names the pinned integrity; else the last
                attempt's ``cloudcli_npm_install_failed``,
                ``cloudcli_native_module_failed``, or
                ``cloudcli_install_out_of_memory`` and ``credential_invalid``
                at once, each naming the account.
            ModuleInstallPending: On Linux while a service of the install's
                name is still loaded or the machine is shutting down.
            OSError: When a command cannot run, a file cannot be written, or
                the PowerShell host fails.
            subprocess.SubprocessError: When a command does not finish.
        """
        account = instance.account
        if self._os_name == "windows":
            self._read_install_tasks()
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
        if self._os_name == "linux":
            self._wait_for_install_left(account)
        if self._version and installed_version(app) == self._version:
            return []
        attempts = self._attempts()
        self.installing = frozenset({account})
        try:
            self._install_attempts(account, entry, app, attempts)
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
            held: The record held before, with the port the runner took;
                its loopback port and its database are kept.

        Returns:
            The record.
        """
        return {
            "account": instance.account,
            "port": int(held.get("port") or 0),
            "upstream_port": int(held.get("upstream_port") or 0) or self._pick_port(),
            "web_password": instance.web_password,
            "token_secret": instance.token_secret,
            "database": str(held.get("database") or CLOUDCLI_DATABASE_NAME),
            "local_name": instance.local_name,
            "cookie_name": instance.cookie_name,
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
            cookie = (
                f"{cookie_name(record)}={login}; Path=/; HttpOnly; "
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

    def _attempts(self) -> list:
        """Each ``(registry, settings)`` an account's install tries, in order.

        The registries of the artifact's source set that name the pinned
        integrity, fastest first, each with every host of the npm settings,
        fastest first.

        Returns:
            The attempts.

        Raises:
            ModuleApplyError: ``download_failed {file, sources}`` when no
                registry names the pinned integrity, or the recipe names no
                npm package or a set the state does not hold.
        """
        package = str(self._npm.get("package", "") or "")
        held = self._source_sets.get(str(self._npm.get("source_set", "") or ""))
        registries = [
            str(source)
            for source in (held.get("sources") if isinstance(held, dict) else None)
            or []
        ]
        named = f"{package}@{self._version}"
        if not package or not self._version or not registries:
            raise ModuleApplyError("download_failed", {"file": named, "sources": []})
        chosen, failures = source_fetch.rank_registries(
            registries,
            package=package,
            version=self._version,
            integrity=str(self._npm.get("digest", "") or ""),
            probe_one=self._probe,
        )
        if not chosen:
            raise ModuleApplyError(
                "download_failed", {"file": named, "sources": failures}
            )
        held = self._npm.get("hosts")
        orders = {
            str(name): source_fetch.rank_hosts(
                [str(host) for host in hosts], probe_one=self._probe
            )
            for name, hosts in (held.items() if isinstance(held, dict) else ())
            if isinstance(hosts, list) and hosts
        }
        rounds = max((len(order) for order in orders.values()), default=1)
        return [
            (
                registry,
                {
                    name: order[min(index, len(order) - 1)]
                    for name, order in orders.items()
                },
            )
            for registry in chosen
            for index in range(rounds)
        ]

    def _install_attempts(
        self, account: str, entry: AccountEntry, app: str, attempts: list
    ) -> None:
        """Run the install with each attempt in turn until one takes.

        Raises:
            ModuleApplyError: The last attempt's failure; a kill for want of
                memory at once.
        """
        failure = None
        for registry, settings in attempts:
            try:
                if self._os_name == "linux":
                    self._install_linux(account, entry.home, app, registry, settings)
                else:
                    self._install_darwin(account, entry, app, registry, settings)
                return
            except ModuleApplyError as error:
                if error.code == "cloudcli_install_out_of_memory":
                    raise
                self._log(
                    f"{self.name}: the install for {account} from "
                    f"{registry_host(registry)} failed: {error.code}"
                )
                failure = error
        if failure is not None:
            raise failure

    def _install_linux(
        self, account: str, home: str, app: str, registry: str, settings: dict
    ) -> None:
        """Run npm as the account in a transient service, then check the native modules.

        Raises:
            ModuleApplyError: npm's or the native modules' failure.
            ModuleInstallPending: While a service of the install's name is
                still loaded, or the machine is shutting down and stopped it.
        """
        node = self.node
        node_bin = os.path.dirname(node)
        environment = {
            "HOME": home,
            "USER": account,
            "LOGNAME": account,
            "PATH": ":".join([node_bin, *CLOUDCLI_INSTALL_PATH["linux"]]),
            **npm_environment(app, extra=settings),
        }
        prefix = ["runuser", "-u", account, "--", "env", "-i"] + [
            f"{name}={value}" for name, value in environment.items()
        ]
        npm = npm_path(os.path.dirname(node_bin), "linux")
        self._log_install(account, registry)
        unit = f"{CLOUDCLI_INSTALL_UNIT_PREFIX}{account}.service"
        log_file = self._install_log_path(account)
        os.makedirs(os.path.dirname(log_file), mode=0o700, exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(log_file)
        run = self.machine.run
        run(["systemctl", "reset-failed", unit], is_checked=False)
        result = run(
            [
                "systemd-run",
                f"--unit={unit}",
                "--quiet",
                "--wait",
                "-p",
                "OOMPolicy=stop",
                "-p",
                f"StandardOutput=file:{log_file}",
                "-p",
                f"StandardError=file:{log_file}",
                "--",
            ]
            + prefix
            + ["sh", "-c", INSTALL_SHELL, app, node, npm]
            + self._npm_arguments(app, registry),
            is_checked=False,
            timeout_s=CLOUDCLI_INSTALL_TIMEOUT_S,
        )
        logged = install_output(log_file)
        with contextlib.suppress(OSError):
            os.unlink(log_file)
        if not result.is_success:
            output = "\n".join([logged, result.stdout, result.stderr]).strip()
            self._log(f"{self.name}: npm for {account}: {output[-2000:]}")
            if CLOUDCLI_UNIT_LOADED_TEXT in output or self._is_machine_stopping():
                raise ModuleInstallPending(account)
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

    def _wait_for_install_left(self, account: str) -> None:
        """Wait at most the install's time for an install service left running, then stop it."""
        unit = f"{CLOUDCLI_INSTALL_UNIT_PREFIX}{account}.service"
        run = self.machine.run
        try:
            for turn in range(CLOUDCLI_INSTALL_TIMEOUT_S // CLOUDCLI_INSTALL_POLL_S):
                shown = run(
                    ["systemctl", "show", "-p", "ActiveState", "--value", unit],
                    is_checked=False,
                )
                if shown.stdout.strip() not in CLOUDCLI_INSTALL_RUNNING_STATES:
                    return
                if turn == 0:
                    self.installing = frozenset({account})
                    self._log(
                        f"{self.name}: waiting for the install for {account} "
                        "that is already running"
                    )
                self._sleep(CLOUDCLI_INSTALL_POLL_S)
            self._log(f"{self.name}: stopping the install for {account} past its time")
            run(["systemctl", "stop", unit], is_checked=False)
        finally:
            self.installing = frozenset()

    def _install_darwin(
        self, account: str, entry: AccountEntry, app: str, registry: str, settings: dict
    ) -> None:
        """Run npm as the account, then check the native modules."""
        node = self.node
        node_bin = os.path.dirname(node)
        environment = {
            "HOME": entry.home,
            "USER": account,
            "LOGNAME": account,
            "PATH": ":".join([node_bin, *CLOUDCLI_INSTALL_PATH["darwin"]]),
            **npm_environment(app, extra=settings),
        }
        npm = npm_path(os.path.dirname(node_bin), "darwin")
        self._log_install(account, registry)
        result = self._run_as(
            entry,
            ["/bin/sh", "-c", INSTALL_SHELL, app, node, npm]
            + self._npm_arguments(app, registry),
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

    def _read_install_tasks(self) -> None:
        """Read every install task Windows holds.

        Raises:
            OSError: When the PowerShell host fails.
        """
        read = self.machine.powershell.call(
            "task_states", {"prefix": CLOUDCLI_INSTALL_TASK_PREFIX}
        )
        self._install_tasks = {
            str(entry.get("name", "")): entry
            for entry in read.get("tasks") or []
            if isinstance(entry, dict)
        }

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
        if is_app_ready(app, self._version):
            return INSTALL_READY
        attempts = self._attempts()
        node = self.node
        npm = npm_path(ntpath.dirname(node), "windows", ntpath.join)
        write_text(
            script,
            render_install_script(
                app=app,
                node=node,
                npm=npm,
                package=str(self._npm.get("package", "") or ""),
                version=self._version,
                attempts=attempts,
            ),
        )
        write_text(log_file, "")
        for path in (script, log_file):
            grant_account_alone(self.machine.run, path, account, "M", is_tree=False)
        batch_logon = self.machine.batch_logon
        if batch_logon is not None:
            batch_logon.hold(account, name, instance.password)
        try:
            self.machine.powershell.call(
                "task_run_once",
                {
                    "task": name,
                    "program": ACCOUNT_SERVICE_WINDOWS_SHELL,
                    "arguments": task_arguments(script, [], log_file),
                    "account": account,
                    "password": instance.password,
                    "timeout_s": CLOUDCLI_WINDOWS_INSTALL_LIMIT_S,
                },
            )
        except (OSError, ModuleApplyError):
            if batch_logon is not None:
                batch_logon.release(account, name)
            raise
        self._log(f"{self.name}: installing CloudCLI for {account}")
        return INSTALL_RUNNING

    def _judge_install(
        self, task: dict, app: str, name: str, script: str, log_file: str, account: str
    ) -> None:
        """Unregister an ended install task and raise the step it failed at."""
        self.machine.powershell.call("task_remove", {"task": name})
        if self.machine.batch_logon is not None:
            self.machine.batch_logon.release(account, name)
        remove_path(script)
        output = install_output(log_file)
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
        if result != 0 or not is_app_ready(app, self._version):
            raise npm_failure(output, account)

    def _install_script_path(self, account: str) -> str:
        return ntpath.join(
            self.machine.module_dir,
            ACCOUNT_SERVICE_WINDOWS_SCRIPT_DIR_NAME,
            CLOUDCLI_INSTALL_SCRIPT_PATTERN.format(account=account),
        )

    def _install_log_path(self, account: str) -> str:
        return self._join(
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

    def _is_machine_stopping(self) -> bool:
        """Whether the machine is shutting down, which stops an install's service."""
        shown = self.machine.run(["systemctl", "is-system-running"], is_checked=False)
        return shown.stdout.strip() == CLOUDCLI_SYSTEM_STOPPING

    def _is_out_of_memory(self, unit: str) -> bool:
        """Whether the kernel killed an install's service for want of memory; forgets the unit."""
        run = self.machine.run
        shown = run(
            ["systemctl", "show", "-p", "Result", "--value", unit], is_checked=False
        )
        run(["systemctl", "reset-failed", unit], is_checked=False)
        return shown.stdout.strip() == CLOUDCLI_OOM_RESULT

    def _npm_arguments(self, app: str, registry: str) -> list:
        return npm_arguments(
            app,
            package=str(self._npm.get("package", "") or ""),
            version=self._version,
            registry=registry,
        )

    def _log_install(self, account: str, registry: str) -> None:
        self._log(
            f"{self.name}: installing CloudCLI for {account} "
            f"from {registry_host(registry)}"
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
        candidates += request.cookie_values(cookie_name(record))
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
