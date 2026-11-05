"""What Codeg adds to the shared runner: each account's service, the token.

The server bundle and Node.js come down the hub's package stream as the
module's ``server`` and ``node`` artifacts and land under those directories
in the module's own, never on a ``PATH``. Each instance runs ``codeg-server``
as its account, from an environment written from scratch, on a loopback
port the agent picks and keeps in the record, with its data directory
under the account's home, made as the account, and its output discarded on
every system; its daily log there is read as the account too. The
forwarder trades the hub's token for its own login cookie, named by the
instance's ``cookie_name``, and a redirect to a page that keeps the instance
token in the browser, and passes on a request carrying that token as its Bearer header or as the
subprotocol of Codeg's WebSocket, or carrying a good cookie.

Not pure: makes the data directory as the account and talks to Codeg.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hmac
import json
import ntpath
import os
import socket
import subprocess
import time

from neutrino_agent.constants import AGENT_FORWARD_UPSTREAM_TIMEOUT_S
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.codeg.config import (
    CodegConfig,
    CodegInstance,
    cookie_key,
    instance_token,
    subprotocol_of,
)
from neutrino_agent.modules.codeg.constants import (
    CODEG_BASE_PORT,
    CODEG_ACCOUNT_PATH_PARTS,
    CODEG_BRIDGE_PORTS_OFF,
    CODEG_COOKIE_PREFIX,
    CODEG_DATA_PARTS,
    CODEG_ENV_BRIDGE_PORTS,
    CODEG_ENV_DATA_DIR,
    CODEG_ENV_HOST,
    CODEG_ENV_NPM_CACHE,
    CODEG_ENV_NPM_PREFIX,
    CODEG_ENV_PORT,
    CODEG_ENV_STATIC_DIR,
    CODEG_ENV_TOKEN,
    CODEG_KEEP_TOKEN_PATH,
    CODEG_RUNNER,
    CODEG_LOG_DIR_NAME,
    CODEG_LOG_PREFIX,
    CODEG_LOG_SUFFIX,
    CODEG_LOGIN_LIFETIME_S,
    CODEG_LOGIN_PAGE,
    CODEG_NAME,
    CODEG_NODE_BIN_PARTS,
    CODEG_NODE_DIR_NAME,
    CODEG_NPM_CACHE_NAME,
    CODEG_NPM_PREFIX_NAME,
    CODEG_RECORD_FIELDS,
    CODEG_SERVER_DIR_NAME,
    CODEG_SERVER_NAMES,
    CODEG_STORAGE_KEY,
    CODEG_SYSTEM_PATH,
    CODEG_TITLE,
    CODEG_UMASK,
    CODEG_UPSTREAM_HOST,
    CODEG_VERSION_ARGUMENT,
    CODEG_VERSION_TIMEOUT_S,
    CODEG_WEB_DIR_NAME,
    CODEG_WINDOWS_SERVICE_PATH,
    CODEG_WORKSPACE_PATH,
)
from neutrino_agent.modules.shared.account_files import AccountFiles
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
)
from neutrino_agent.modules.shared.http_forward import (
    RELAY,
    ForwardDecision,
    answered,
    is_login_valid,
    mint_login,
    refused,
)
from neutrino_agent.modules.shared.instances import InstanceHooks
from neutrino_agent.modules.shared.log_tail import account_file_tail, file_tail

# The header a request carries the instance token in, and its scheme.
AUTHORIZATION_HEADER = "authorization"
BEARER_SCHEME = "bearer"
# The headers a WebSocket upgrade carries its subprotocols in.
UPGRADE_HEADER = "upgrade"
WEBSOCKET_UPGRADE = "websocket"
SUBPROTOCOL_HEADER = "sec-websocket-protocol"


def data_dir(home: str, os_name: str, join=os.path.join) -> str:
    """One account's Codeg data directory, under its home.

    Args:
        home: The account's home.
        os_name: The system.
        join: How the system joins a path.

    Returns:
        The directory ``CODEG_DATA_DIR`` names.
    """
    return join(home, *CODEG_DATA_PARTS[os_name])


def service_environment(
    token: str,
    *,
    upstream_port: int,
    home: str,
    os_name: str,
    node_dir: str,
    static_dir: str,
    join=os.path.join,
) -> dict:
    """The environment one instance's Codeg runs with, written from scratch.

    Args:
        token: The instance token, from :func:`instance_token`.
        upstream_port: The loopback port Codeg listens on.
        home: The account's home.
        os_name: The system.
        node_dir: The directory Node's interpreter is in; it leads ``PATH``.
        static_dir: The web UI inside the server artifact.
        join: How the system joins a path.

    Returns:
        Codeg's host, port, token, data directory, static directory and
        port bridge switch, npm's prefix and cache under the data
        directory, and ``PATH``; on Linux and macOS also ``HOME``. On
        Windows ``PATH`` is Node's directory, the account's npm directory
        and its own ``PATH``.
    """
    data = data_dir(home, os_name, join)
    environment = {
        CODEG_ENV_HOST: CODEG_UPSTREAM_HOST,
        CODEG_ENV_PORT: str(int(upstream_port)),
        CODEG_ENV_TOKEN: token,
        CODEG_ENV_DATA_DIR: data,
        CODEG_ENV_STATIC_DIR: static_dir,
        CODEG_ENV_BRIDGE_PORTS: CODEG_BRIDGE_PORTS_OFF,
        CODEG_ENV_NPM_PREFIX: join(data, CODEG_NPM_PREFIX_NAME),
        CODEG_ENV_NPM_CACHE: join(data, CODEG_NPM_CACHE_NAME),
    }
    if os_name == "windows":
        environment["PATH"] = ";".join([node_dir, *CODEG_WINDOWS_SERVICE_PATH])
        return environment
    environment["HOME"] = home
    environment["PATH"] = ":".join(
        [node_dir]
        + [join(home, *parts) for parts in CODEG_ACCOUNT_PATH_PARTS]
        + list(CODEG_SYSTEM_PATH[os_name])
    )
    return environment


def newest_log(directory: str, names, join=os.path.join) -> str:
    """Codeg's newest daily log in its log directory. Pure.

    Args:
        directory: The ``logs`` directory under the data directory.
        names: The names the directory holds; None when it is not there.
        join: How the system joins a path.

    Returns:
        The file's path, empty when there is none yet.
    """
    logs = sorted(
        name
        for name in names or []
        if name.startswith(CODEG_LOG_PREFIX) and name.endswith(CODEG_LOG_SUFFIX)
    )
    return join(directory, logs[-1]) if logs else ""


def has_bearer(request, token: str) -> bool:
    """Whether a request's ``Authorization`` header carries the token as Bearer.

    Args:
        request: The :class:`ForwardRequest`.
        token: The instance token.

    Returns:
        True when one such header equals the token, compared in constant
        time.
    """
    expected = token.encode("utf-8")
    for name, value in request.headers:
        if name.lower() != AUTHORIZATION_HEADER:
            continue
        scheme, _, credential = value.strip().partition(" ")
        if scheme.lower() == BEARER_SCHEME and hmac.compare_digest(
            credential.strip().encode("utf-8"), expected
        ):
            return True
    return False


def has_subprotocol(request, token: str) -> bool:
    """Whether a WebSocket upgrade carries the token's subprotocol.

    Args:
        request: The :class:`ForwardRequest`.
        token: The instance token.

    Returns:
        True for an upgrade to a WebSocket whose ``Sec-WebSocket-Protocol``
        headers name ``codeg-token.<base64url(token)>``, compared in
        constant time.
    """
    if request.header(UPGRADE_HEADER).strip().lower() != WEBSOCKET_UPGRADE:
        return False
    expected = subprotocol_of(token).encode("utf-8")
    for name, value in request.headers:
        if name.lower() != SUBPROTOCOL_HEADER:
            continue
        for protocol in value.split(","):
            if hmac.compare_digest(protocol.strip().encode("utf-8"), expected):
                return True
    return False


def cookie_name(record: dict) -> str:
    """The cookie one instance's forwarder keeps its login in.

    Args:
        record: The instance's record.

    Returns:
        The record's ``cookie_name``, else the module's prefix and the port.
    """
    named = str(record.get("cookie_name", "") or "")
    return named or f"{CODEG_COOKIE_PREFIX}{int(record.get('port', 0) or 0)}"


def login_page(token: str) -> bytes:
    """The page that keeps the instance token in the browser and opens the workspace.

    Args:
        token: The instance token.

    Returns:
        The page, UTF-8.
    """
    page = CODEG_LOGIN_PAGE % (
        json.dumps(CODEG_STORAGE_KEY),
        json.dumps(token),
        json.dumps(CODEG_WORKSPACE_PATH),
    )
    return page.encode("utf-8")


class CodegHooks(InstanceHooks):
    """Codeg's part of the shared runner."""

    name = CODEG_NAME
    title = CODEG_TITLE
    runner = CODEG_RUNNER
    instance_class = CodegInstance
    record_fields = CODEG_RECORD_FIELDS
    secret_field = "secret"
    base_port = CODEG_BASE_PORT
    page_port_field = "upstream_port"

    def __init__(self, *, platform, log=print, clock=time.time):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            clock: Seconds since the epoch, which the login cookie is judged by.
        """
        super().__init__(platform=platform, log=log)
        self._clock = clock
        # The server binary's size and time, and the version it printed.
        self._version: tuple = ((), "")
        # Each account's login the last apply named, which Windows reads
        # its log under.
        self._passwords: dict = {}

    @property
    def server_path(self) -> str:
        """The server inside the ``server`` artifact."""
        return self._join(
            self.machine.module_dir,
            CODEG_SERVER_DIR_NAME,
            CODEG_SERVER_NAMES[self._os_name],
        )

    @property
    def static_dir(self) -> str:
        """The web UI inside the ``server`` artifact."""
        return self._join(
            self.machine.module_dir, CODEG_SERVER_DIR_NAME, CODEG_WEB_DIR_NAME
        )

    @property
    def node_dir(self) -> str:
        """The directory Node's interpreter is in, inside the ``node`` artifact."""
        return self._join(
            self.machine.module_dir,
            CODEG_NODE_DIR_NAME,
            *CODEG_NODE_BIN_PARTS[self._os_name],
        )

    def parse(self, config: dict) -> CodegConfig:
        """The configuration parsed and checked for this system.

        Args:
            config: The module's desired configuration.

        Returns:
            The configuration.

        Raises:
            ModuleApplyError: ``account_invalid``, ``account_duplicate``,
                ``port_invalid``, ``port_duplicate`` or ``secret_missing``,
                naming the first problem found, and on Windows
                ``credential_missing``.
        """
        parsed = CodegConfig.from_dict(config)
        parsed.validate(os_name=self._os_name)
        return parsed

    def verify(self) -> bool:
        """Whether the server's file exists."""
        return os.path.isfile(self.server_path)

    def prepare(
        self, parsed: CodegConfig, instance: CodegInstance, entry: AccountEntry
    ) -> list:
        """Make the account's data directory, the account's own, unless it is there.

        Args:
            parsed: The configuration.
            instance: The instance.
            entry: Its account.

        Returns:
            One note when the directory was made.

        Raises:
            OSError: When the directory cannot be made as the account.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        self._passwords[instance.account] = instance.password
        directory = data_dir(entry.home, self._os_name, self._join)
        if os.path.isdir(directory):
            return []
        if not self._files(instance.account).make_dir(directory):
            return []
        return [f"made the data directory of {instance.account}"]

    def record(self, parsed: CodegConfig, instance: CodegInstance, held: dict) -> dict:
        """One instance's record: its ports and its secret.

        Args:
            parsed: The configuration.
            instance: The instance.
            held: The record held before, with the ports the runner took.

        Returns:
            The record.
        """
        return {
            "account": instance.account,
            "port": int(held.get("port") or 0),
            "upstream_port": int(held.get("upstream_port") or 0),
            "secret": instance.secret,
            "local_name": instance.local_name,
            "cookie_name": instance.cookie_name,
        }

    def service(
        self, instance: CodegInstance, entry: AccountEntry, record: dict
    ) -> AccountService:
        """``codeg-server`` as the account, from an environment written from scratch.

        Args:
            instance: The instance.
            entry: Its account.
            record: Its record, whose loopback port the environment names.

        Returns:
            The service: its environment root-only, its umask 077, its
            output discarded.
        """
        upstream_port = int(record.get("upstream_port") or 0)
        environment = service_environment(
            instance_token(instance.secret),
            upstream_port=upstream_port,
            home=entry.home,
            os_name=self._os_name,
            node_dir=self.node_dir,
            static_dir=self.static_dir,
            join=self._join,
        )
        return AccountService(
            name=self.name,
            title=self.title,
            account=instance.account,
            command=(self.server_path,),
            environment=environment,
            working_directory="~",
            umask=CODEG_UMASK,
            password=instance.password,
            listen_port=upstream_port,
            is_environment_secret=True,
            is_output_discarded=True,
        )

    def admit(self, request, record: dict) -> ForwardDecision:
        """The forwarder's rule: a token trades for the login cookie and a redirect to the page; the instance token or the cookie passes.

        An App share's shell reads the head of the token's answer alone and
        opens the app where it redirects, so the page has its own path.

        Args:
            request: The request.
            record: The instance's record.

        Returns:
            A redirect to the page for a token that verifies, setting the
            cookie; the relay for a request whose Bearer header is the
            instance token, whose WebSocket upgrade carries its subprotocol,
            or whose cookie verifies; the page for such a cookie at the
            page's path; 401 otherwise.
        """
        secret = str(record.get("secret", "") or "")
        token = instance_token(secret)
        key = cookie_key(secret)
        name = cookie_name(record)
        if request.token:
            if not request.take_token():
                return refused()
            expiry = int(self._clock()) + CODEG_LOGIN_LIFETIME_S
            cookie = (
                f"{name}={mint_login(key, expiry)}; Path=/; "
                f"HttpOnly; SameSite=Lax; Max-Age={CODEG_LOGIN_LIFETIME_S}"
            )
            return answered(
                302,
                headers=(
                    ("Location", CODEG_KEEP_TOKEN_PATH),
                    ("Set-Cookie", cookie),
                    ("Cache-Control", "no-store"),
                    ("Referrer-Policy", "no-referrer"),
                ),
            )
        if has_bearer(request, token) or has_subprotocol(request, token):
            return RELAY
        now = self._clock()
        if not any(
            is_login_valid(value, key, now) for value in request.cookie_values(name)
        ):
            return refused()
        if request.path != CODEG_KEEP_TOKEN_PATH:
            return RELAY
        return answered(
            200,
            login_page(token),
            content_type="text/html; charset=utf-8",
            headers=(
                ("Cache-Control", "no-store"),
                ("Referrer-Policy", "no-referrer"),
            ),
        )

    def connect(self, record: dict) -> socket.socket:
        """A connection to Codeg on loopback.

        Args:
            record: The instance's record.

        Returns:
            The connected socket.

        Raises:
            OSError: When Codeg does not answer.
        """
        return socket.create_connection(
            (CODEG_UPSTREAM_HOST, int(record.get("upstream_port", 0) or 0)),
            timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
        )

    def module_details(self) -> dict:
        """The server installed.

        Returns:
            ``{"version"}``, what the server prints for ``--version``.
        """
        return {"version": self._installed_version()}

    def journal_log(self, record: dict) -> str:
        """Codeg's newest daily log under the instance's data directory.

        Args:
            record: The instance's record.

        Returns:
            The file's path, empty when there is none yet or the machine no
            longer has the account.
        """
        account = str(record.get("account", "") or "")
        directory = self._log_dir(account)
        if not directory:
            return ""
        try:
            names = self._files(account).names(directory)
        except (OSError, ModuleApplyError):
            return ""
        return newest_log(directory, names, self._join)

    def read_journal(self, account: str, path: str, lines: int) -> list:
        """The last lines of one log file: a daily log under the account's data directory read as the account, any other as root.

        Raises:
            OSError: When the file exists and cannot be read.
            ModuleApplyError: When it cannot be read as the account.
        """
        directory = self._log_dir(account)
        if not directory or self._dirname(path) != directory:
            return file_tail(path, lines)
        return account_file_tail(self._files(account), path, lines)

    def _log_dir(self, account: str) -> str:
        """The account's Codeg log directory; empty for an account the machine lacks."""
        try:
            entry = self.machine.lookup_account(account)
        except KeyError:
            return ""
        return self._join(
            data_dir(entry.home, self._os_name, self._join), CODEG_LOG_DIR_NAME
        )

    def _files(self, account: str) -> AccountFiles:
        """The account's places, reached as the account."""
        return AccountFiles(
            platform=self._platform,
            account=account,
            password=self._passwords.get(account, ""),
        )

    def _dirname(self, path: str) -> str:
        return (ntpath.dirname if self._os_name == "windows" else os.path.dirname)(path)

    @property
    def _os_name(self) -> str:
        return self._platform.os_name

    def _join(self, *parts: str) -> str:
        return (ntpath.join if self._os_name == "windows" else os.path.join)(*parts)

    def _installed_version(self) -> str:
        """What the server prints for ``--version``, read once per binary."""
        server = self.server_path
        try:
            found = os.stat(server)
        except OSError:
            return ""
        stamp = (found.st_mtime_ns, found.st_size)
        if self._version[0] != stamp:
            try:
                result = self.machine.run(
                    [server, CODEG_VERSION_ARGUMENT],
                    is_checked=False,
                    timeout_s=CODEG_VERSION_TIMEOUT_S,
                )
                printed = result.stdout.strip() if result.is_success else ""
            except (OSError, subprocess.SubprocessError):
                printed = ""
            self._version = (stamp, printed)
        return self._version[1]
