"""What the EasyTier daemon keeps this machine joined to, and what it answers.

The daemon holds two kinds of membership in one root-owned directory: a
manual network is one file under ``networks/``, which the core reads through
``--config-dir``; the console is ``console.json``, whose address the core
takes as ``ET_CONFIG_SERVER`` in its environment, so the account's token is
on no argument vector. What is in the directory is the whole state: a start
reads it back and runs the core to match, and a request changes it and
restarts the core.

One request is one JSON object with a ``verb``:

    {"verb": "join", "network_name", "network_secret", "peer", "hostname"}
    {"verb": "join_console", "config_server", "is_secure_mode"}
    {"verb": "leave", "network_name"}
    {"verb": "leave_console"}
    {"verb": "status"}

Every accepted request is answered with the status, ``{"networks",
"console", "is_running"}``, ``console`` being ``{"digest",
"is_secure_mode"}`` or None; a refusal is ``{"code", "params"}``. Neither
ever carries a secret or a console's address.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import hashlib
import json
import os
import threading

from neutrino_client.constants import (
    CLIENT_EASYTIER_CONFIG_SUFFIX,
    CLIENT_EASYTIER_CONSOLE_FILE_NAME,
    CLIENT_EASYTIER_NETWORKS_DIR_NAME,
    CLIENT_EASYTIER_RPC_PORTAL,
)
from neutrino_client.core import files
from neutrino_client.core.easytier_config import (
    is_console_address,
    is_hostname,
    is_network_name,
    is_peer_uri,
    render_easytier_config,
)

VERB_JOIN = "join"
VERB_JOIN_CONSOLE = "join_console"
VERB_LEAVE = "leave"
VERB_LEAVE_CONSOLE = "leave_console"
VERB_STATUS = "status"
# The environment the core takes a console from; any other of its own
# variables the daemon inherited is dropped, so none configures the core.
CORE_ENV_PREFIX = "ET_"
CORE_ENV_CONFIG_SERVER = "ET_CONFIG_SERVER"
CORE_ENV_SECURE_MODE = "ET_SECURE_MODE"
# What the core prints: warnings and worse.
CORE_LOG_LEVEL = "warn"
# The most a network's secret may be.
SECRET_LIMIT_CHARS = 4096


def console_digest(config_server: str) -> str:
    """A console's address as a status may name it.

    Args:
        config_server: The address, token included.

    Returns:
        Its SHA-256, in hex.
    """
    return hashlib.sha256(config_server.encode("utf-8")).hexdigest()


def _refusal(code: str, params: "dict | None" = None) -> dict:
    return {"code": code, "params": dict(params or {})}


def _text(request: dict, key: str) -> "str | None":
    """One string field of a request, stripped; None when it is not a string."""
    value = request.get(key)
    return value.strip() if isinstance(value, str) else None


class EasytierDaemon:
    """The daemon's state and the requests that change it."""

    def __init__(self, *, state_dir: str, core_path: str, supervisor=None, log=print):
        """
        Args:
            state_dir: The root-owned directory the state lives in.
            core_path: The carried easytier-core, empty when this install
                carries none.
            supervisor: What runs the core; its ``apply()`` is called after
                every change and ``is_running`` read for a status. None runs
                nothing.
            log: Callable used for progress messages; it never sees a
                secret or a console's address.
        """
        self._state_dir = state_dir
        self._networks_dir = os.path.join(state_dir, CLIENT_EASYTIER_NETWORKS_DIR_NAME)
        self._console_path = os.path.join(state_dir, CLIENT_EASYTIER_CONSOLE_FILE_NAME)
        self._core_path = core_path
        self._supervisor = supervisor
        self._log = log
        self._lock = threading.Lock()

    @property
    def networks_dir(self) -> str:
        """The directory the core reads the manual networks from."""
        return self._networks_dir

    def restore(self) -> None:
        """Run the core to match what the state directory holds.

        Raises:
            OSError: When the networks' directory cannot be made.
        """
        os.makedirs(self._networks_dir, mode=0o700, exist_ok=True)
        networks = self.networks()
        console = self.console()
        self._log(
            f"restored {len(networks)} network(s)"
            + (" and a console" if console else "")
        )
        self._apply()

    def networks(self) -> list:
        """The manual networks configured, by name.

        Returns:
            The names, sorted.
        """
        try:
            names = os.listdir(self._networks_dir)
        except OSError:
            return []
        return sorted(
            name[: -len(CLIENT_EASYTIER_CONFIG_SUFFIX)]
            for name in names
            if name.endswith(CLIENT_EASYTIER_CONFIG_SUFFIX)
            and is_network_name(name[: -len(CLIENT_EASYTIER_CONFIG_SUFFIX)])
        )

    def console(self) -> "dict | None":
        """The console configured.

        Returns:
            ``{"config_server", "is_secure_mode"}``, or None when there is
            none or its file is not one the daemon wrote.
        """
        data = files.read_json(self._console_path)
        address = data.get("config_server")
        if not isinstance(address, str) or not is_console_address(address):
            return None
        return {
            "config_server": address,
            "is_secure_mode": data.get("is_secure_mode") is True,
        }

    def core_command(self) -> "tuple[list, dict] | None":
        """The core's argument vector and environment for what is configured.

        Returns:
            ``(argv, env)``; None when nothing is configured or this install
            carries no core, since a core with neither a network nor a
            console runs a default network of its own.
        """
        networks = self.networks()
        console = self.console()
        if not self._core_path or (not networks and console is None):
            return None
        argv = [
            self._core_path,
            "--rpc-portal",
            CLIENT_EASYTIER_RPC_PORTAL,
            "--console-log-level",
            CORE_LOG_LEVEL,
        ]
        if networks:
            argv += ["--config-dir", self._networks_dir]
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith(CORE_ENV_PREFIX)
        }
        if console is not None:
            env[CORE_ENV_CONFIG_SERVER] = console["config_server"]
            if console["is_secure_mode"]:
                env[CORE_ENV_SECURE_MODE] = "true"
        return argv, env

    def status(self) -> dict:
        """What is configured and whether the core runs.

        Returns:
            ``{"networks", "console", "is_running"}``.
        """
        console = self.console()
        return {
            "networks": self.networks(),
            "console": (
                {
                    "digest": console_digest(console["config_server"]),
                    "is_secure_mode": console["is_secure_mode"],
                }
                if console is not None
                else None
            ),
            "is_running": bool(
                self._supervisor is not None and self._supervisor.is_running
            ),
        }

    def handle(self, request) -> dict:
        """Answer one request.

        Args:
            request: The decoded request.

        Returns:
            The status after it, or ``{"code", "params"}``.
        """
        if not isinstance(request, dict):
            return _refusal("overlay_request_invalid")
        verb = request.get("verb")
        handlers = {
            VERB_JOIN: self._join,
            VERB_JOIN_CONSOLE: self._join_console,
            VERB_LEAVE: self._leave,
            VERB_LEAVE_CONSOLE: self._leave_console,
            VERB_STATUS: lambda _request: None,
        }
        handler = handlers.get(verb) if isinstance(verb, str) else None
        if handler is None:
            return _refusal("overlay_request_invalid")
        with self._lock:
            try:
                refusal = handler(request)
            except OSError as error:
                self._log(f"{verb}: {error.strerror or error}")
                return _refusal(
                    "overlay_restart_failed",
                    {"detail": str(error.strerror or error)[:200]},
                )
            if refusal is not None:
                return refusal
            return self.status()

    def _join(self, request: dict) -> "dict | None":
        name = _text(request, "network_name")
        secret = _text(request, "network_secret")
        peer = _text(request, "peer")
        hostname = _text(request, "hostname")
        if name is None or not is_network_name(name):
            return _refusal("overlay_network_invalid")
        if peer is None or not is_peer_uri(peer):
            return _refusal("overlay_peer_invalid")
        if not secret or len(secret) > SECRET_LIMIT_CHARS:
            return _refusal("overlay_secret_missing")
        if hostname is None or not is_hostname(hostname):
            return _refusal("overlay_request_invalid")
        if not self._core_path:
            return _refusal("bundle_missing", {"binary": "easytier-core"})
        text = render_easytier_config(
            network_name=name, network_secret=secret, peer=peer, hostname=hostname
        )
        path = self._network_path(name)
        if files.read_text(path) == text:
            return None
        os.makedirs(self._networks_dir, mode=0o700, exist_ok=True)
        files.write_text(path, text, mode=0o600)
        self._log(f"joined network {name}")
        self._apply()
        return None

    def _join_console(self, request: dict) -> "dict | None":
        address = _text(request, "config_server")
        is_secure_mode = request.get("is_secure_mode", False)
        if address is None or not is_console_address(address):
            return _refusal("overlay_console_invalid")
        if not isinstance(is_secure_mode, bool):
            return _refusal("overlay_request_invalid")
        if not self._core_path:
            return _refusal("bundle_missing", {"binary": "easytier-core"})
        current = self.console()
        if current is not None and current["config_server"] != address:
            return _refusal("overlay_other_network")
        wanted = {"config_server": address, "is_secure_mode": is_secure_mode}
        if current == wanted:
            return None
        files.write_text(self._console_path, json.dumps(wanted) + "\n", mode=0o600)
        self._log("joined a console")
        self._apply()
        return None

    def _leave(self, request: dict) -> "dict | None":
        name = _text(request, "network_name")
        if name is None or not is_network_name(name):
            return _refusal("overlay_network_invalid")
        path = self._network_path(name)
        if not os.path.exists(path):
            return None
        os.unlink(path)
        self._log(f"left network {name}")
        self._apply()
        return None

    def _leave_console(self, _request: dict) -> "dict | None":
        if not os.path.exists(self._console_path):
            return None
        os.unlink(self._console_path)
        self._log("left the console")
        self._apply()
        return None

    def _network_path(self, name: str) -> str:
        return os.path.join(self._networks_dir, name + CLIENT_EASYTIER_CONFIG_SUFFIX)

    def _apply(self) -> None:
        if self._supervisor is not None:
            self._supervisor.apply()
