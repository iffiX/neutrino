"""What Hermes WebUI adds to the ``container`` runner: the page's forwarder, the gateway keys, the health read.

The forwarder listens on ``127.0.0.1`` at a port the agent takes from 8787
up at the first start and keeps in the module's record, and passes
requests on to the webui's 8787, published on loopback at the port the
Containers runner picked. A request with a token that verifies is traded for
the webui's own login: the forwarder posts the password to
``/api/auth/login``, hands the browser the login cookie the webui sets,
under the name the hub gives this device, and redirects to ``/``. A request
with that cookie is passed on with ``Host`` and ``Origin`` as the browser
sent them; every other request, and the browser's own login request, is
401.

Once ``config.yaml`` exists in ``home`` the agent writes ``model.provider``,
``model.base_url``, ``model.key_env`` and ``model.api_key``, the last two
naming the key's variable, with ``hermes config set`` in the agent container, and again whenever the base URL differs from the one the
record holds. From the install, and after a version change, the module
reads ``installing`` until the keys hold the current base URL and the
webui's ``/health`` first answers 200; meanwhile its start waits, and the
state is applied again. Then the agent signs in and turns the webui's own
update check off through its settings route, at each start until it took. A version change stops both containers and makes
the ``agent`` and ``app`` volumes again. The record keeps what the
forwarder needs, so it listens again after the agent restarts.

Not pure: runs podman, opens sockets, writes the record.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import http.client
import json
import os
import posixpath
import socket
import subprocess
import threading
import urllib.parse

from neutrino_agent.constants import (
    AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
    AGENT_REPORT_INTERVAL_S,
)
from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.hermes_webui.config import HermesWebuiConfig
from neutrino_agent.modules.hermes_webui.constants import (
    HERMES_WEBUI_AGENT_CONTAINER,
    HERMES_WEBUI_BASE_PORT,
    HERMES_WEBUI_BASE_URL_SUFFIX,
    HERMES_WEBUI_CACHE_VOLUMES,
    HERMES_WEBUI_CONFIG_COMMAND,
    HERMES_WEBUI_CONFIG_FILE,
    HERMES_WEBUI_COOKIE,
    HERMES_WEBUI_EXEC_HOME,
    HERMES_WEBUI_EXEC_USER,
    HERMES_WEBUI_FORWARDER_FIELDS,
    HERMES_WEBUI_GATEWAY_KEY_REFERENCE,
    HERMES_WEBUI_GATEWAY_KEY_VARIABLE,
    HERMES_WEBUI_GATEWAY_URL_VARIABLE,
    HERMES_WEBUI_HEALTH_PATH,
    HERMES_WEBUI_HEALTH_TIMEOUT_S,
    HERMES_WEBUI_LOGIN_PATH,
    HERMES_WEBUI_PENDING,
    HERMES_WEBUI_PODMAN_TIMEOUT_S,
    HERMES_WEBUI_PROVIDER,
    HERMES_WEBUI_RECORD_FIELDS,
    HERMES_WEBUI_SETTINGS_PATH,
    HERMES_WEBUI_UPDATE_CHECK_OFF,
    HERMES_WEBUI_UPSTREAM_HOST,
    HERMES_WEBUI_WEBUI_CONTAINER,
)
from neutrino_agent.modules.podman.container_runner import ContainerHooks
from neutrino_agent.modules.shared.http_forward import (
    RELAY,
    ForwardDecision,
    InstanceForwarder,
    answered,
    refused,
)
from neutrino_agent.modules.shared.loopback_port import is_port_free, pick_port
from neutrino_agent.modules.shared.record_store import InstanceRecordStore
from neutrino_agent.modules.shared.subprocess_run import command_detail, run

# How much of a failed command's words a log line keeps.
DETAIL_CHARS = 200


def normal_path(path: str) -> str:
    """A path as the webui's router matches it: decoded, slashes collapsed, dot segments resolved.

    Args:
        path: The request's path, without the query.

    Returns:
        The path, ``/`` for an empty one.
    """
    decoded = urllib.parse.unquote(path)
    while "//" in decoded:
        decoded = decoded.replace("//", "/")
    resolved = posixpath.normpath("/" + decoded.lstrip("/"))
    return resolved.rstrip("/") or "/"


def gateway_keys(base_url: str) -> list:
    """The four keys the agent writes into ``config.yaml``, in order.

    Args:
        base_url: The gateway's address with ``/v1`` after it.

    Returns:
        ``(key, value)`` for ``model.provider``, ``model.base_url`` and
        ``model.key_env`` and ``model.api_key``, both naming the key's
        variable and neither holding the key; ``model.default`` is the
        person's.
    """
    return [
        ("model.provider", HERMES_WEBUI_PROVIDER),
        ("model.base_url", base_url),
        ("model.key_env", HERMES_WEBUI_GATEWAY_KEY_VARIABLE),
        ("model.api_key", HERMES_WEBUI_GATEWAY_KEY_REFERENCE),
    ]


def session_cookie(headers: list, cookie_name: str = HERMES_WEBUI_COOKIE) -> str:
    """The ``Set-Cookie`` value that carries the webui's login, as it sent it.

    Args:
        headers: ``(name, value)`` of the login's answer.
        cookie_name: The name of the webui's login cookie.

    Returns:
        The header's value; empty when the answer sets no such cookie.
    """
    for name, value in headers:
        if name.lower() != "set-cookie":
            continue
        if value.split("=", 1)[0].strip() == cookie_name:
            return value
    return ""


def health_status(port: int) -> int:
    """The status the webui's ``/health`` answers with at its published port.

    Args:
        port: The loopback port the webui is published at.

    Returns:
        The HTTP status; 0 when nothing answers.
    """
    connection = http.client.HTTPConnection(
        HERMES_WEBUI_UPSTREAM_HOST, port, timeout=HERMES_WEBUI_HEALTH_TIMEOUT_S
    )
    try:
        connection.request("GET", HERMES_WEBUI_HEALTH_PATH)
        response = connection.getresponse()
        response.read()
        return int(response.status)
    except (OSError, http.client.HTTPException):
        return 0
    finally:
        connection.close()


def webui_login(port: int, password: str) -> tuple:
    """The webui's answer to the forwarder's own login request.

    Args:
        port: The loopback port the webui is published at.
        password: The webui's password.

    Returns:
        ``(status, headers)``, the headers as ``(name, value)`` pairs.

    Raises:
        OSError: When the webui does not answer.
    """
    connection = http.client.HTTPConnection(
        HERMES_WEBUI_UPSTREAM_HOST, port, timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S
    )
    try:
        connection.request(
            "POST",
            HERMES_WEBUI_LOGIN_PATH,
            body=json.dumps({"password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        return int(response.status), list(response.getheaders())
    except http.client.HTTPException as error:
        raise ConnectionError(str(error)) from error
    finally:
        connection.close()


def webui_settings(port: int, cookie: str, settings: dict) -> int:
    """Save some of the webui's own settings, signed in with its cookie.

    Args:
        port: The loopback port the webui is published at.
        cookie: The login cookie as ``name=value``.
        settings: The settings to save, by key.

    Returns:
        The HTTP status the webui answers with.

    Raises:
        OSError: When the webui does not answer.
    """
    connection = http.client.HTTPConnection(
        HERMES_WEBUI_UPSTREAM_HOST, port, timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S
    )
    try:
        connection.request(
            "POST",
            HERMES_WEBUI_SETTINGS_PATH,
            body=json.dumps(settings).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": cookie},
        )
        response = connection.getresponse()
        response.read()
        return int(response.status)
    except http.client.HTTPException as error:
        raise ConnectionError(str(error)) from error
    finally:
        connection.close()


def _cookie_name(record: dict) -> str:
    """The name of the webui's login cookie the record holds, the webui's default when it holds none."""
    return str(record.get("cookie_name", "") or "") or HERMES_WEBUI_COOKIE


def _forwarder(*, name: str, record: dict, hooks, log) -> InstanceForwarder:
    """The page's forwarder, trying a port another program holds every report interval."""
    return InstanceForwarder(
        name=name,
        record={**record, "account": ""},
        hooks=hooks,
        log=log,
        retry_s=AGENT_REPORT_INTERVAL_S,
    )


class HermesWebuiHooks(ContainerHooks):
    """Hermes WebUI's forwarder, gateway keys, health read and version change."""

    # What the forwarder reads of the record.
    secret_field = "secret"
    forwarder_fields = HERMES_WEBUI_FORWARDER_FIELDS

    def __init__(
        self,
        *,
        platform,
        name: str,
        containers,
        log=print,
        run_command=run,
        health=health_status,
        login=webui_login,
        save_settings=webui_settings,
        forwarder_factory=None,
        record_dir: str = "",
        is_port_free=is_port_free,
    ):
        """
        Args:
            platform: The machine's platform.
            name: The module's name.
            containers: The Containers runner, which reaches Podman and
                keeps the webui's published port.
            log: Called with each progress line.
            run_command: Runs one command, as :func:`subprocess_run.run`.
            health: Returns the status ``/health`` answers with at a port.
            login: Returns the webui's answer to a login at a port with a
                password, as :func:`webui_login`.
            save_settings: Saves the webui's own settings at a port with a
                login cookie, as :func:`webui_settings`.
            forwarder_factory: Called with ``name``, ``record``, ``hooks``
                and ``log``; returns a forwarder. None makes an
                :class:`InstanceForwarder` that tries a held port again every
                report interval.
            record_dir: Where the record lives; empty is the module's
                directory under ``platform.agent_data_dir()``.
            is_port_free: Answers whether a loopback port can be bound now.
        """
        super().__init__(platform=platform, name=name, containers=containers, log=log)
        self._run = run_command
        self._health = health
        self._login = login
        self._save_settings = save_settings
        self._forwarder_factory = forwarder_factory or _forwarder
        self._is_port_free = is_port_free
        self._records = InstanceRecordStore(
            directory=record_dir or os.path.join(platform.agent_data_dir(), name),
            fields=HERMES_WEBUI_RECORD_FIELDS,
        )
        self._lock = threading.Lock()
        self._config: "HermesWebuiConfig | None" = None
        self._forwarder = None
        self._is_resumed = False
        self._is_starting = False

    # --- what the container runner calls ---

    def apply(self, config: dict) -> None:
        """Take the module's configuration.

        Args:
            config: ``{secret, password, cookie_name, local_name}``.
        """
        self._config = HermesWebuiConfig.from_dict(config)

    def installed(self, version: str) -> None:
        """Note the pair the install pulled; a new one makes ``agent`` and ``app`` again.

        Args:
            version: The version the recipe names.
        """
        record = self._record()
        held = str(record.get("version", "") or "")
        if held and held != version:
            self._log(f"{self._name}: {held} to {version}, agent and app made again")
            self._reset_caches()
        if held != version:
            self._keep(
                {
                    **record,
                    "version": version,
                    "base_url": "",
                    "is_ready": False,
                    "is_update_check_off": False,
                }
            )

    def start(self) -> None:
        """Serve the page, write the gateway keys once the first start allows, then turn the update check off.

        Raises:
            ModuleInstallPending: Until the keys hold the current base URL
                and ``/health`` has answered 200 once.
            ModuleApplyError: When the Containers runner cannot keep the
                webui's published port.
        """
        record = self._started_record()
        self._sync_forwarder(record)
        if not record.get("is_ready"):
            with self._lock:
                self._is_starting = True
        base_url = self._base_url()
        if base_url and base_url != record.get("base_url") and self._has_config_file():
            if self._write_keys(base_url):
                record = self._keep({**record, "base_url": base_url})
        if record.get("is_ready"):
            self._turn_update_check_off(record)
            return
        is_written = bool(base_url) and record.get("base_url") == base_url
        if is_written and self._health(int(record["upstream_port"])) == 200:
            record = self._keep({**record, "is_ready": True})
            self._log(f"{self._name}: the first start has ended")
            with self._lock:
                self._is_starting = False
            self._turn_update_check_off(record)
            return
        raise ModuleInstallPending(HERMES_WEBUI_PENDING)

    def stop(self) -> None:
        """Stop serving the page."""
        with self._lock:
            self._is_starting = False
        record = self._record()
        if record:
            self._keep({**record, "is_stopped": True})
        self._close_forwarder()

    def is_running(self) -> bool:
        """Whether the webui's ``/health`` answers 200 at its published port.

        Returns:
            False before the webui has a published port.
        """
        record = self._resume()
        port = int(record.get("upstream_port", 0) or 0)
        return bool(port) and self._health(port) == 200

    def is_installing(self) -> bool:
        """Whether the module's start waits on the first start, after the install or a version change."""
        with self._lock:
            is_starting = self._is_starting
        return is_starting and not self._record().get("is_ready")

    def details(self) -> dict:
        """The forwarder's port, the one the agent took.

        Returns:
            ``{"port"}``, 0 before the first start took one.
        """
        record = self._resume()
        return {"port": int(record.get("port", 0) or 0)}

    def remove(self) -> None:
        """Stop serving the page and forget the record, with its directory when nothing else is in it."""
        with self._lock:
            self._is_starting = False
        self._close_forwarder()
        self._records.remove(self._name)
        with contextlib.suppress(OSError):
            os.rmdir(self._records.directory)

    # --- what the forwarder asks ---

    def on_first_start(self, record: dict) -> str:
        """Nothing to wait for: the forwarder listens at once.

        Args:
            record: The module's record.

        Returns:
            Empty.
        """
        return ""

    def admit(self, request, record: dict) -> ForwardDecision:
        """The forwarder's rule for one request.

        Args:
            request: The request.
            record: The module's record.

        Returns:
            401 for ``/api/auth/login`` whatever it holds, for a token that
            does not verify and for a request with neither a token nor the
            webui's cookie under the record's name; a redirect to ``/`` carrying the webui's cookie
            for a token that verifies, 502 when the webui refuses the
            password or does not answer; the relay for a request with the
            cookie.
        """
        if normal_path(request.path) == HERMES_WEBUI_LOGIN_PATH:
            return refused()
        if request.token:
            if not record.get("secret") or not request.take_token():
                return refused()
            cookie = self._signed_in(record)
            if not cookie:
                return answered(502)
            return answered(
                302,
                headers=(
                    ("Location", "/"),
                    ("Set-Cookie", cookie),
                    ("Cache-Control", "no-store"),
                    ("Referrer-Policy", "no-referrer"),
                ),
            )
        if request.cookie_values(_cookie_name(record)):
            return RELAY
        return refused()

    def connect(self, record: dict) -> socket.socket:
        """A connection to the webui at its published port.

        Args:
            record: The module's record.

        Returns:
            The connected socket.

        Raises:
            OSError: When the webui does not answer.
        """
        return socket.create_connection(
            (HERMES_WEBUI_UPSTREAM_HOST, int(record.get("upstream_port", 0) or 0)),
            timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
        )

    # --- the module's own steps ---

    def _signed_in(self, record: dict) -> str:
        """The webui's ``Set-Cookie`` for the password; empty when it refuses or does not answer."""
        try:
            status, headers = self._login(
                int(record.get("upstream_port", 0) or 0),
                str(record.get("password", "") or ""),
            )
        except OSError:
            return ""
        if status != 200:
            return ""
        return session_cookie(headers, _cookie_name(record))

    def _turn_update_check_off(self, record: dict) -> None:
        """Save the webui's ``check_for_updates`` off once; a failure is a line in the log."""
        if record.get("is_update_check_off"):
            return
        cookie = self._signed_in(record).split(";", 1)[0].strip()
        status = 0
        if cookie:
            try:
                status = self._save_settings(
                    int(record.get("upstream_port", 0) or 0),
                    cookie,
                    dict(HERMES_WEBUI_UPDATE_CHECK_OFF),
                )
            except OSError as error:
                self._log(f"{self._name}: the update check stays on: {error}")
                return
        if status != 200:
            self._log(f"{self._name}: the update check stays on: status {status}")
            return
        self._keep({**record, "is_update_check_off": True})
        self._log(f"{self._name}: the webui's update check is off")

    def _started_record(self) -> dict:
        """The record as this start serves it: the configuration, the ports, running.

        Raises:
            ModuleApplyError: When the published port cannot be kept, or
                no port from 8787 up is free for the forwarder.
        """
        record = self._record()
        config = self._config or HermesWebuiConfig.from_dict(record)
        try:
            upstream = self._containers.page_port(
                self._name, HERMES_WEBUI_WEBUI_CONTAINER
            )
            port = int(record.get("port", 0) or 0) or pick_port(
                HERMES_WEBUI_BASE_PORT,
                taken=[upstream],
                is_free=self._is_port_free,
            )
        except OSError as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": str(error)[:DETAIL_CHARS]}
            ) from error
        return self._keep(
            {
                **record,
                "port": port,
                "secret": config.secret,
                "password": config.password,
                "cookie_name": config.cookie_name,
                "local_name": config.local_name,
                "upstream_port": upstream,
                "is_stopped": False,
            }
        )

    def _base_url(self) -> str:
        """The base URL the agent container's environment names, empty while it does not run."""
        command = self._command()
        if not command:
            return ""
        try:
            done = self._run(
                [*command, "inspect", "--format", "json", HERMES_WEBUI_AGENT_CONTAINER],
                is_checked=False,
                timeout_s=HERMES_WEBUI_PODMAN_TIMEOUT_S,
            )
            found = json.loads(done.stdout or "[]") if done.is_success else []
        except (OSError, subprocess.SubprocessError, ValueError):
            return ""
        entry = found[0] if isinstance(found, list) and found else {}
        if not isinstance(entry, dict):
            return ""
        state = entry.get("State") if isinstance(entry.get("State"), dict) else {}
        if state.get("Running") is not True:
            return ""
        config = entry.get("Config") if isinstance(entry.get("Config"), dict) else {}
        prefix = HERMES_WEBUI_GATEWAY_URL_VARIABLE + "="
        for line in config.get("Env") or []:
            if isinstance(line, str) and line.startswith(prefix):
                url = line[len(prefix) :].rstrip("/")
                return url + HERMES_WEBUI_BASE_URL_SUFFIX if url else ""
        return ""

    def _has_config_file(self) -> bool:
        """Whether the agent image has written ``config.yaml`` into ``home``."""
        done = self._quietly(
            [
                "exec",
                HERMES_WEBUI_AGENT_CONTAINER,
                "test",
                "-f",
                HERMES_WEBUI_CONFIG_FILE,
            ]
        )
        return done is not None and done.is_success

    def _write_keys(self, base_url: str) -> bool:
        """Write the four keys with ``hermes config set``; False at the first that fails."""
        for key, value in gateway_keys(base_url):
            done = self._quietly(
                [
                    "exec",
                    "-u",
                    HERMES_WEBUI_EXEC_USER,
                    "-e",
                    HERMES_WEBUI_EXEC_HOME,
                    HERMES_WEBUI_AGENT_CONTAINER,
                    *HERMES_WEBUI_CONFIG_COMMAND,
                    key,
                    value,
                ]
            )
            if done is None or not done.is_success:
                said = (done.stderr or done.stdout or "").strip() if done else ""
                self._log(f"{self._name}: {key} not written: {said[:DETAIL_CHARS]}")
                return False
        self._log(f"{self._name}: the gateway keys name {base_url}")
        return True

    def _reset_caches(self) -> None:
        """Stop both containers, and make the ``agent`` and ``app`` volumes again."""
        names = list(self._containers.hub_names().get(self._name, []))
        if names:
            try:
                self._containers.drive_hub_containers(names, "stop")
            except (OSError, subprocess.SubprocessError) as error:
                self._log(f"{self._name}: stop: {command_detail(error)[:DETAIL_CHARS]}")
        for volume in HERMES_WEBUI_CACHE_VOLUMES:
            self._quietly(["volume", "rm", "-f", volume])
            self._quietly(["volume", "create", volume])

    def _quietly(self, arguments: list):
        """Run one podman command; None when it cannot run, its result otherwise."""
        command = self._command()
        if not command:
            return None
        try:
            return self._run(
                [*command, *arguments],
                is_checked=False,
                timeout_s=HERMES_WEBUI_PODMAN_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as error:
            self._log(f"{self._name}: {arguments[0]}: {error}")
            return None

    def _command(self) -> tuple:
        """Containers' podman command; empty while it has none or cannot reach it."""
        try:
            return tuple(self._containers.podman_command())
        except (ModuleApplyError, KeyError):
            return ()

    def _record(self) -> dict:
        """The module's record, empty when none is kept."""
        return self._records.read(self._name)

    def _keep(self, record: dict) -> dict:
        """Write the record whole and answer it; a failed write is a line in the log."""
        kept = {**record, "account": self._name}
        try:
            self._records.write(kept)
        except OSError as error:
            self._log(f"{self._name}: the record was not kept: {error}")
        return kept

    def _resume(self) -> dict:
        """Start the forwarder the record names, once, after the agent starts."""
        record = self._record()
        with self._lock:
            if self._is_resumed:
                return record
            self._is_resumed = True
        if record and not record.get("is_stopped"):
            self._sync_forwarder(record)
        return record

    def _sync_forwarder(self, record: dict) -> None:
        """Run one forwarder for the record as it stands."""
        with self._lock:
            self._is_resumed = True
            current = self._forwarder
            if current is not None and current.matches(record):
                return
            self._forwarder = None
        if current is not None:
            current.close()
        if not record.get("port") or not record.get("upstream_port"):
            return
        forwarder = self._forwarder_factory(
            name=self._name, record=record, hooks=self, log=self._log
        )
        with self._lock:
            self._forwarder = forwarder
        forwarder.start()

    def _close_forwarder(self) -> None:
        with self._lock:
            forwarder, self._forwarder = self._forwarder, None
        if forwarder is not None:
            forwarder.close()
