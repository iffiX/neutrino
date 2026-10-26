"""What code-server adds to the shared runner: the release, each instance's socket, the cookie.

The release comes from the hub's package stream as the tarball coder
publishes, which carries its own Node.js, and the shared unpack puts it
under ``release`` in the module's directory. Each instance runs the
launcher as its account on a socket in that account's run directory, with
code-server's own login off, so root and the account alone can open it.
The forwarder admits a browser by its own login cookie, named by the
instance's ``cookie_name``, traded once for the token the hub minted.

Not pure: opens the socket.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import socket
import time
import urllib.parse

from neutrino_agent.constants import (
    AGENT_FORWARD_TOKEN_PARAMETER,
    AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
)
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server.config import (
    CodeServerConfig,
    CodeServerInstance,
    cookie_key,
)
from neutrino_agent.modules.code_server.constants import (
    CODE_SERVER_BASE_PORT,
    CODE_SERVER_COOKIE_PREFIX,
    CODE_SERVER_DARWIN_PATH,
    CODE_SERVER_DARWIN_SHELL,
    CODE_SERVER_FLAGS,
    CODE_SERVER_RUNNER,
    CODE_SERVER_LAUNCHER_PARTS,
    CODE_SERVER_LOGIN_LIFETIME_S,
    CODE_SERVER_NAME,
    CODE_SERVER_NODE_PARTS,
    CODE_SERVER_PACKAGE_JSON,
    CODE_SERVER_RECORD_FIELDS,
    CODE_SERVER_RELEASE_DIR_NAME,
    CODE_SERVER_RUN_DIR_NAME,
    CODE_SERVER_SOCKET_NAME,
    CODE_SERVER_SOCKET_PATH_MAX,
    CODE_SERVER_TITLE,
)
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


def release_dir(root: str) -> str:
    """The release directory under the module's root."""
    return os.path.join(root, CODE_SERVER_RELEASE_DIR_NAME)


def launcher_path(root: str) -> str:
    """The ``code-server`` launcher of the release under the module's root."""
    return os.path.join(release_dir(root), *CODE_SERVER_LAUNCHER_PARTS)


def node_path(root: str) -> str:
    """The Node.js the release carries."""
    return os.path.join(release_dir(root), *CODE_SERVER_NODE_PARTS)


def installed_version(root: str) -> str:
    """The code-server version the release under the module's root is.

    Args:
        root: The module's directory.

    Returns:
        The version its ``package.json`` names, empty when there is none.
    """
    path = os.path.join(release_dir(root), CODE_SERVER_PACKAGE_JSON)
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return str(json.load(stream).get("version", "") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def run_dir(root: str, account: str) -> str:
    """One account's run directory, which holds its socket."""
    return os.path.join(root, CODE_SERVER_RUN_DIR_NAME, account)


def socket_path(root: str, account: str) -> str:
    """The socket one account's code-server listens on."""
    return os.path.join(run_dir(root, account), CODE_SERVER_SOCKET_NAME)


def check_socket_path(root: str, account: str, os_name: str) -> None:
    """Refuse an account whose socket path the system cannot bind.

    Args:
        root: The module's directory.
        account: The account.
        os_name: ``linux`` or ``darwin``.

    Raises:
        ModuleApplyError: ``account_invalid {account}`` when the path is
            longer than the system's socket address holds.
    """
    limit = CODE_SERVER_SOCKET_PATH_MAX.get(os_name, 0)
    if limit and len(os.fsencode(socket_path(root, account))) > limit:
        raise ModuleApplyError("account_invalid", {"account": account})


def server_arguments(root: str, account: str) -> list:
    """What one account's code-server is started with.

    Args:
        root: The module's directory.
        account: The account.

    Returns:
        The launcher, ``--socket`` with the account's socket, and the flags
        every instance runs with.
    """
    return [
        launcher_path(root),
        "--socket",
        socket_path(root, account),
        *CODE_SERVER_FLAGS,
    ]


def cookie_name(record: dict) -> str:
    """The cookie one instance's forwarder keeps its login in.

    Args:
        record: The instance's record.

    Returns:
        The record's ``cookie_name``, else the module's prefix and the port.
    """
    named = str(record.get("cookie_name", "") or "")
    return named or f"{CODE_SERVER_COOKIE_PREFIX}{int(record.get('port', 0) or 0)}"


def address_without_token(path: str, query: dict) -> str:
    """The address a token's redirect goes to: the same, its token taken out.

    Args:
        path: The request's path.
        query: The request's query, name to values.

    Returns:
        The path, and the query's other fields in their order.
    """
    kept = [
        (name, value)
        for name, values in query.items()
        if name != AGENT_FORWARD_TOKEN_PARAMETER
        for value in values
    ]
    if not kept:
        return path or "/"
    return f"{path or '/'}?{urllib.parse.urlencode(kept)}"


class CodeServerHooks(InstanceHooks):
    """code-server's part of the shared runner."""

    name = CODE_SERVER_NAME
    title = CODE_SERVER_TITLE
    runner = CODE_SERVER_RUNNER
    instance_class = CodeServerInstance
    record_fields = CODE_SERVER_RECORD_FIELDS
    secret_field = "secret"
    base_port = CODE_SERVER_BASE_PORT

    def __init__(self, *, platform, log=print, clock=time.time):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            clock: Seconds since the epoch, which the login cookie is judged by.
        """
        super().__init__(platform=platform, log=log)
        self._clock = clock

    def parse(self, config: dict) -> CodeServerConfig:
        """The configuration parsed and checked, every socket path bindable.

        Args:
            config: The module's desired configuration.

        Returns:
            The configuration.

        Raises:
            ModuleApplyError: ``account_invalid``, ``account_duplicate`` or
                ``secret_missing``, naming the first problem found;
                ``account_invalid`` as well for an account whose socket
                path is too long.
        """
        parsed = CodeServerConfig.from_dict(config)
        parsed.validate()
        for instance in parsed.instances:
            check_socket_path(
                self.machine.module_dir, instance.account, self._platform.os_name
            )
        return parsed

    def verify(self) -> bool:
        """Whether the release's launcher exists."""
        return os.path.isfile(launcher_path(self.machine.module_dir))

    def service(
        self, instance: CodeServerInstance, entry: AccountEntry, record: dict
    ) -> AccountService:
        """One account's code-server on its socket, in its home.

        Args:
            instance: The instance.
            entry: Its account, whose home and shell a Mac's job carries.
            record: Its record.

        Returns:
            The service.
        """
        root = self.machine.module_dir
        environment = {}
        if self._platform.os_name == "darwin":
            environment = {
                "HOME": entry.home,
                "USER": instance.account,
                "LOGNAME": instance.account,
                "SHELL": entry.shell or CODE_SERVER_DARWIN_SHELL,
                "PATH": CODE_SERVER_DARWIN_PATH,
            }
        return AccountService(
            name=self.name,
            title=self.title,
            account=instance.account,
            command=tuple(server_arguments(root, instance.account)),
            environment=environment,
            working_directory="~",
            directories=(run_dir(root, instance.account),),
        )

    def admit(self, request, record: dict) -> ForwardDecision:
        """The forwarder's rule: a token trades for the login cookie, the cookie passes.

        Args:
            request: The request.
            record: The instance's record.

        Returns:
            A redirect setting the cookie for a token that verifies, the
            relay for a good cookie, 401 otherwise.
        """
        key = cookie_key(str(record.get("secret", "") or ""))
        name = cookie_name(record)
        if request.token:
            if not request.take_token():
                return refused()
            expiry = int(self._clock()) + CODE_SERVER_LOGIN_LIFETIME_S
            cookie = (
                f"{name}={mint_login(key, expiry)}; Path=/; "
                f"HttpOnly; SameSite=Lax; Max-Age={CODE_SERVER_LOGIN_LIFETIME_S}"
            )
            return answered(
                302,
                headers=(
                    ("Location", address_without_token(request.path, request.query)),
                    ("Set-Cookie", cookie),
                    ("Cache-Control", "no-store"),
                    ("Referrer-Policy", "no-referrer"),
                ),
            )
        now = self._clock()
        if any(
            is_login_valid(value, key, now) for value in request.cookie_values(name)
        ):
            return RELAY
        return refused()

    def connect(self, record: dict) -> socket.socket:
        """A connection to the instance's socket.

        Args:
            record: The instance's record.

        Returns:
            The connected socket.

        Raises:
            OSError: When code-server does not answer.
        """
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.settimeout(AGENT_FORWARD_UPSTREAM_TIMEOUT_S)
        try:
            upstream.connect(
                socket_path(self.machine.module_dir, str(record.get("account", "")))
            )
        except OSError:
            upstream.close()
            raise
        return upstream

    def module_details(self) -> dict:
        """The release installed.

        Returns:
            ``{"version"}``.
        """
        return {"version": installed_version(self.machine.module_dir)}
