"""What AstrBot adds to the ``container`` runner: the settings file, the page's forwarder, the gateway's provider, the health read.

The step ``settings`` runs before Containers renders the container at an
install or a version change, and before ``start`` while the record holds
another password than the state's. It makes the volume when it is missing,
writes ``cmd_config.json`` into a volume that holds none, with the dashboard
user's password, a new ``jwt_secret``, the gateway's source, the default
model's provider and the default, ``pypi_index_url`` and metrics off, and
makes the requirements folder of the image's Python. A volume that holds the
file keeps it, apart from the ``dashboard`` keys after a new password, which
are written with the container stopped. Each file is written whole under a
temporary name and renamed into place.

The forwarder listens on ``127.0.0.1`` at a port the agent takes from 6185
up and keeps in the module's record, and passes requests on to AstrBot's
6185, published on loopback at the port the Containers runner picked. A
request with a token that verifies sets the forwarder's own login cookie
and is redirected to ``/neutrino_login``, a page that signs in to AstrBot
with the password and stores its token in the browser. A request with the
cookie is passed on unchanged, apart from the refused routes and a settings
save that turns SSL or TOTP on or moves the dashboard; every other request
is 401.

From the install, after a version change and after a new password, the
module reads ``installing`` until AstrBot's ``/`` first answers 200: the
step ``first_start`` checks every 30 seconds meanwhile. Once it has ended,
and at each later start, the agent gives AstrBot a new gateway address, a
new default model or a new context length of the agent's provider through
AstrBot's API, and leaves a default the person picked as it is.

Not pure: runs podman, opens sockets, writes the record.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import binascii
import contextlib
import copy
import hashlib
import http.client
import json
import os
import posixpath
import secrets
import socket
import subprocess
import threading
import time
import urllib.parse

from neutrino_agent.constants import (
    AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
    AGENT_REPORT_INTERVAL_S,
    AGENT_STEP_SETTINGS,
)
from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.astrbot.config import AstrbotConfig, cookie_key
from neutrino_agent.modules.astrbot.constants import (
    ASTRBOT_API_TIMEOUT_S,
    ASTRBOT_BASE_PORT,
    ASTRBOT_BASE_URL_SUFFIX,
    ASTRBOT_CONFIG_FILE,
    ASTRBOT_CONTAINER,
    ASTRBOT_DASHBOARD_HOST,
    ASTRBOT_DASHBOARD_PORT,
    ASTRBOT_FORWARDER_FIELDS,
    ASTRBOT_GATEWAY_KEY_REFERENCE,
    ASTRBOT_GATEWAY_URL_VARIABLE,
    ASTRBOT_HEALTH_PATH,
    ASTRBOT_HEALTH_TIMEOUT_S,
    ASTRBOT_JWT_SECRET_BYTES,
    ASTRBOT_KEEP_LOGIN_PATH,
    ASTRBOT_LEGACY_SAVE_PATH,
    ASTRBOT_LOGIN_LIFETIME_S,
    ASTRBOT_LOGIN_PAGE,
    ASTRBOT_LOGIN_PATH,
    ASTRBOT_PBKDF2_ITERATIONS,
    ASTRBOT_PBKDF2_SALT_BYTES,
    ASTRBOT_PENDING,
    ASTRBOT_PROFILE_PATH,
    ASTRBOT_PROFILE_PROVIDER_PATH,
    ASTRBOT_PROFILES_PREFIX,
    ASTRBOT_PROVIDERS_PATH,
    ASTRBOT_PYTHON_VARIABLE,
    ASTRBOT_RECORD_FIELDS,
    ASTRBOT_REFUSED_PATHS,
    ASTRBOT_SOURCE_ID,
    ASTRBOT_SOURCE_PROVIDERS_PATH,
    ASTRBOT_SOURCE_TIMEOUT_S,
    ASTRBOT_SOURCES_PATH,
    ASTRBOT_START_POLL_S,
    ASTRBOT_START_WAIT_S,
    ASTRBOT_STEP_FIRST_START,
    ASTRBOT_SYSTEM_CONFIG_PATH,
    ASTRBOT_UPSTREAM_HOST,
    ASTRBOT_USER_SITE,
    ASTRBOT_USERNAME,
    ASTRBOT_VOLUME,
    ASTRBOT_WINDOW_KEY,
)
from neutrino_agent.modules.podman.applier import stored_reference
from neutrino_agent.modules.podman.container_runner import (
    ContainerHooks,
    first_start_step,
    recipe_images,
)
from neutrino_agent.modules.podman.renderer import (
    volume_read_script,
    volume_write_script,
)
from neutrino_agent.modules.shared import source_fetch
from neutrino_agent.modules.shared.http_forward import (
    RELAY,
    ForwardDecision,
    InstanceForwarder,
    answered,
    is_login_valid,
    mint_login,
    refused,
)
from neutrino_agent.modules.shared.loopback_port import is_port_free, pick_port
from neutrino_agent.modules.shared.record_store import InstanceRecordStore
from neutrino_agent.modules.shared.step_locks import CONTAINERS_SHARED_LOCKS
from neutrino_agent.modules.shared.subprocess_run import command_detail, run

# How much of a failed command's words a log line or a step's detail keeps.
DETAIL_CHARS = 200
# The source set AstrBot's pip reads its index from.
PYPI_SET = "pypi"


def normal_path(path: str) -> str:
    """A path as AstrBot's router matches it: decoded, slashes collapsed, dot segments resolved.

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


def provider_id(model: str) -> str:
    """The id of the agent's provider for one model.

    Args:
        model: The model's name.

    Returns:
        ``neutrino_gateway/<model>``.
    """
    return f"{ASTRBOT_SOURCE_ID}/{model}"


def gateway_source(base_url: str) -> dict:
    """The gateway's provider source, its key the variable's name.

    Args:
        base_url: The gateway's address with ``/v1`` after it.

    Returns:
        The source as AstrBot keeps it in ``provider_sources``.
    """
    return {
        "id": ASTRBOT_SOURCE_ID,
        "provider": "openai",
        "type": "openai_chat_completion",
        "provider_type": "chat_completion",
        "enable": True,
        "key": [ASTRBOT_GATEWAY_KEY_REFERENCE],
        "api_base": base_url,
        "timeout": ASTRBOT_SOURCE_TIMEOUT_S,
        "proxy": "",
        "custom_headers": {},
    }


def gateway_provider(model: str, context_length: int = 0) -> dict:
    """The chat provider of one model on the gateway's source.

    Args:
        model: The model's name.
        context_length: The model's context length, written as
            ``max_context_tokens``; 0 writes none.

    Returns:
        The provider as AstrBot keeps it in ``provider``.
    """
    provider = {
        "id": provider_id(model),
        "model": model,
        "enable": True,
        "provider_type": "chat_completion",
        "provider_source_id": ASTRBOT_SOURCE_ID,
    }
    if context_length > 0:
        provider[ASTRBOT_WINDOW_KEY] = context_length
    return provider


def dashboard_keys(
    password: str, *, salt: "bytes | None" = None, jwt_secret: str = ""
) -> dict:
    """The ``dashboard`` keys that set the dashboard user's password.

    Args:
        password: The password.
        salt: The PBKDF2 salt; None draws 16 random bytes.
        jwt_secret: The secret AstrBot signs its login tokens with; empty
            draws 32 random bytes in hex.

    Returns:
        ``username``, ``pbkdf2_password`` and ``password`` as AstrBot hashes
        them, both change flags settled, and ``jwt_secret``.
    """
    salt = salt if salt is not None else secrets.token_bytes(ASTRBOT_PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, ASTRBOT_PBKDF2_ITERATIONS
    ).hex()
    return {
        "username": ASTRBOT_USERNAME,
        "pbkdf2_password": (
            f"pbkdf2_sha256${ASTRBOT_PBKDF2_ITERATIONS}${salt.hex()}${digest}"
        ),
        "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
        "password_storage_upgraded": True,
        "password_change_required": False,
        "jwt_secret": jwt_secret or secrets.token_hex(ASTRBOT_JWT_SECRET_BYTES),
    }


def settings_document(
    *,
    password: str,
    base_url: str,
    model: str,
    index_url: str,
    context_length: int = 0,
    **hashing,
) -> dict:
    """The settings file the agent writes into an empty volume.

    Args:
        password: The dashboard user's password.
        base_url: The gateway's address with ``/v1`` after it.
        model: The default model; empty while the gateway serves none.
        index_url: The first ranked source of the ``pypi`` set; empty
            leaves AstrBot's own.
        context_length: The default model's context length; 0 for none.
        **hashing: ``salt`` and ``jwt_secret``, as :func:`dashboard_keys`
            takes them.

    Returns:
        ``dashboard``, ``provider_sources``, and ``provider`` and
        ``agent_runner`` while a model is named, ``pypi_index_url`` and
        ``disable_metrics``.
    """
    document = {
        "dashboard": dashboard_keys(password, **hashing),
        "provider_sources": [gateway_source(base_url)],
    }
    if model:
        document["provider"] = [gateway_provider(model, context_length)]
        document["agent_runner"] = {
            "runner_type": "local",
            "config": {"model": {"provider_id": provider_id(model)}},
        }
    if index_url:
        document["pypi_index_url"] = index_url
    document["disable_metrics"] = True
    return document


def python_version(environment) -> str:
    """The major and minor version of the image's Python, from its environment.

    Args:
        environment: The image's ``KEY=value`` lines.

    Returns:
        Such as ``3.12``; empty when no line names it.
    """
    prefix = ASTRBOT_PYTHON_VARIABLE + "="
    for line in environment or []:
        if isinstance(line, str) and line.startswith(prefix):
            parts = line[len(prefix) :].split(".")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                return f"{parts[0]}.{parts[1]}"
    return ""


def dashboard_of(path: str, body: bytes):
    """The ``dashboard`` a settings save names.

    Args:
        path: The save's normal path.
        body: Its body.

    Returns:
        The ``dashboard`` object, an empty one when the save names none;
        None for a body that is no JSON object.
    """
    try:
        document = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    if path == ASTRBOT_LEGACY_SAVE_PATH:
        document = document.get("config")
        if not isinstance(document, dict):
            return {}
    dashboard = document.get("dashboard")
    return dashboard if isinstance(dashboard, dict) else {}


def is_dashboard_kept(dashboard: dict) -> bool:
    """Whether a save leaves the dashboard as the forwarder reaches it.

    Args:
        dashboard: The save's ``dashboard``.

    Returns:
        False when it turns ``ssl.enable`` or ``totp.enable`` on, or names a
        ``port`` other than 6185 or a ``host`` other than ``0.0.0.0``.
    """
    for section in ("ssl", "totp"):
        held = dashboard.get(section)
        if isinstance(held, dict) and held.get("enable"):
            return False
    if "port" in dashboard and str(dashboard["port"]) != str(ASTRBOT_DASHBOARD_PORT):
        return False
    if "host" in dashboard and dashboard["host"] != ASTRBOT_DASHBOARD_HOST:
        return False
    return True


def login_page(token: str, username: str) -> bytes:
    """The page that stores AstrBot's login in the browser and opens AstrBot.

    Args:
        token: AstrBot's login token.
        username: The dashboard user's name.

    Returns:
        The page, UTF-8.
    """
    return (ASTRBOT_LOGIN_PAGE % (json.dumps(token), json.dumps(username))).encode(
        "utf-8"
    )


def health_status(port: int) -> int:
    """The status AstrBot's ``/`` answers with at its published port.

    Args:
        port: The loopback port AstrBot is published at.

    Returns:
        The HTTP status; 0 when nothing answers.
    """
    connection = http.client.HTTPConnection(
        ASTRBOT_UPSTREAM_HOST, port, timeout=ASTRBOT_HEALTH_TIMEOUT_S
    )
    try:
        connection.request("GET", ASTRBOT_HEALTH_PATH)
        response = connection.getresponse()
        response.read()
        return int(response.status)
    except (OSError, http.client.HTTPException):
        return 0
    finally:
        connection.close()


def astrbot_call(
    port: int, method: str, path: str, *, body=None, token: str = ""
) -> tuple:
    """One call to AstrBot's API at its published port, as a program, with no ``Origin``.

    Args:
        port: The loopback port AstrBot is published at.
        method: The HTTP method.
        path: The route.
        body: What is sent as JSON; None sends nothing.
        token: AstrBot's login token, sent as ``Authorization: Bearer``;
            empty sends none.

    Returns:
        ``(status, document)``, the document empty when the answer is no
        JSON object.

    Raises:
        OSError: When AstrBot does not answer.
    """
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection = http.client.HTTPConnection(
        ASTRBOT_UPSTREAM_HOST, port, timeout=ASTRBOT_API_TIMEOUT_S
    )
    try:
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        raw = response.read()
    except http.client.HTTPException as error:
        raise ConnectionError(str(error)) from error
    finally:
        connection.close()
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        document = {}
    return int(response.status), document if isinstance(document, dict) else {}


def is_ok(status: int, document: dict) -> bool:
    """Whether one of AstrBot's answers took.

    Args:
        status: The HTTP status.
        document: The answer's JSON.

    Returns:
        True for 200 with ``status`` ``ok``.
    """
    return status == 200 and document.get("status") == "ok"


def _forwarder(*, name: str, record: dict, hooks, log) -> InstanceForwarder:
    """The page's forwarder, trying a port another program holds every report interval."""
    return InstanceForwarder(
        name=name,
        record={**record, "account": ""},
        hooks=hooks,
        log=log,
        retry_s=AGENT_REPORT_INTERVAL_S,
    )


class AstrbotHooks(ContainerHooks):
    """AstrBot's settings file, forwarder, gateway provider, health read and version change."""

    # What the forwarder reads of the record.
    secret_field = "secret"
    forwarder_fields = ASTRBOT_FORWARDER_FIELDS

    def __init__(
        self,
        *,
        platform,
        name: str,
        containers,
        log=print,
        run_command=run,
        health=health_status,
        call=astrbot_call,
        probe_one=source_fetch.probe,
        forwarder_factory=None,
        record_dir: str = "",
        is_port_free=is_port_free,
        clock=time.time,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ):
        """
        Args:
            platform: The machine's platform.
            name: The module's name.
            containers: The Containers runner, which reaches Podman, keeps
                AstrBot's published port, names the container's environment
                and runs the volume's scripts.
            log: Called with each progress line.
            run_command: Runs one command, as :func:`subprocess_run.run`.
            health: Returns the status ``/`` answers with at a port.
            call: Makes one call to AstrBot's API, as :func:`astrbot_call`.
            probe_one: Probes one source, as :func:`source_fetch.probe`.
            forwarder_factory: Called with ``name``, ``record``, ``hooks``
                and ``log``; returns a forwarder. None makes an
                :class:`InstanceForwarder` that tries a held port again every
                report interval.
            record_dir: Where the record lives; empty is the module's
                directory under ``platform.agent_var_dir()``.
            is_port_free: Answers whether a loopback port can be bound now.
            clock: The time a login cookie's expiry is counted by.
            monotonic: The time a start's wait for ``/`` is counted by.
            sleep: Waits between two reads of ``/`` at a start.
        """
        super().__init__(platform=platform, name=name, containers=containers, log=log)
        self._run = run_command
        self._health = health
        self._call = call
        self._probe_one = probe_one
        self._forwarder_factory = forwarder_factory or _forwarder
        self._is_port_free = is_port_free
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        self._records = InstanceRecordStore(
            directory=record_dir or os.path.join(platform.agent_var_dir(), name),
            fields=ASTRBOT_RECORD_FIELDS,
        )
        self._lock = threading.Lock()
        self._config: "AstrbotConfig | None" = None
        self._images: list = []
        self._source_sets: dict = {}
        self._forwarder = None
        self._is_resumed = False
        self._is_starting = False

    # --- what the container runner calls ---

    def take_config(self, config: dict) -> None:
        """Take the configuration the state names, which the step ``settings`` writes.

        Args:
            config: ``{secret, password, cookie_name, local_name, model,
                context_length}``.
        """
        self._config = AstrbotConfig.from_dict(config)

    def take_recipe(self, recipe: dict) -> None:
        """Take the image the recipe pins, whose Python the step ``settings`` reads.

        Args:
            recipe: ``{runner, method, params}``.
        """
        self._images = recipe_images(recipe)

    def take_source_sets(self, source_sets: dict) -> None:
        """Take the state's ``source_sets`` section, whose ``pypi`` set names AstrBot's index.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """
        self._source_sets = dict(source_sets)

    def apply(self, config: dict) -> None:
        """Take the module's configuration.

        Args:
            config: ``{secret, password, cookie_name, local_name, model}``.
        """
        self._config = AstrbotConfig.from_dict(config)

    def install_steps(self, version: str) -> list:
        """``settings``, before Containers renders the container.

        Args:
            version: The version the recipe names.

        Returns:
            The one step.
        """
        return [self._settings_step()]

    def before_start_steps(self, config: dict) -> list:
        """``settings`` while the record holds another password than the state's.

        Args:
            config: The module's configuration the task's entry carries.

        Returns:
            The step, or none.
        """
        password = AstrbotConfig.from_dict(config).password
        if not password or self._record().get("written_password") == password:
            return []
        return [self._settings_step()]

    def installed(self, version: str) -> None:
        """Note the version the recipe names; a new one waits for the first start again.

        Args:
            version: The version the recipe names.
        """
        record = self._record()
        held = str(record.get("version", "") or "")
        if held != version:
            if held:
                self._log(f"{self._name}: {held} to {version}")
            self._keep({**record, "version": version, "is_ready": False})

    def start(self) -> None:
        """Serve the page, and once the first start has ended give AstrBot a new gateway address, a new default model or a new context length.

        Raises:
            ModuleApplyError: When the Containers runner cannot keep
                AstrBot's published port.
        """
        record = self._started_record()
        self._sync_forwarder(record)
        if not record.get("is_ready"):
            with self._lock:
                self._is_starting = True
            return
        self._gateway_synced(record)

    def start_steps(self, config: dict, version: str) -> list:
        """``first_start`` while the first start has not ended for this version and this password.

        Args:
            config: The module's configuration the task's entry carries.
            version: The version the recipe names.

        Returns:
            :class:`ModuleStep` each.
        """
        record = self._record()
        is_new = bool(version) and str(record.get("version", "") or "") != version
        password = AstrbotConfig.from_dict(config).password
        is_new_password = bool(password) and record.get("written_password") != password
        if not (is_new or is_new_password or not record.get("is_ready")):
            return []
        return [first_start_step(ASTRBOT_STEP_FIRST_START, self._run_first_start)]

    def stop(self) -> None:
        """Stop serving the page."""
        with self._lock:
            self._is_starting = False
        record = self._record()
        if record:
            self._keep({**record, "is_stopped": True})
        self._close_forwarder()

    def is_running(self) -> bool:
        """Whether AstrBot's ``/`` answers 200 at its published port.

        Returns:
            False before AstrBot has a published port, and while the record
            keeps the stopped mark.
        """
        record = self._resume()
        port = int(record.get("upstream_port", 0) or 0)
        if not port or record.get("is_stopped"):
            return False
        return self._health(port) == 200

    def upstream_port(self) -> int:
        """The published port the record names.

        Returns:
            0 before the first start.
        """
        return int(self._record().get("upstream_port", 0) or 0)

    def is_installing(self) -> bool:
        """Whether the module's start waits on the first start, after the install, a version change or a new password."""
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
            401 for a refused route whatever the request holds, for a token
            that does not verify and for a request with neither a token
            nor the forwarder's cookie; a redirect to ``/neutrino_login``
            setting the cookie for a token that verifies; the page that
            stores AstrBot's login for ``/neutrino_login`` with the cookie,
            502 when AstrBot refuses the password or does not answer; the
            relay for any other request with the cookie.
        """
        path = normal_path(request.path)
        if path in ASTRBOT_REFUSED_PATHS:
            return refused()
        secret = str(record.get("secret", "") or "")
        name = str(record.get("cookie_name", "") or "")
        if not secret or not name:
            return refused()
        key = cookie_key(secret)
        if request.token:
            if not request.take_token():
                return refused()
            expiry = int(self._clock()) + ASTRBOT_LOGIN_LIFETIME_S
            cookie = (
                f"{name}={mint_login(key, expiry)}; Path=/; "
                f"HttpOnly; SameSite=Lax; Max-Age={ASTRBOT_LOGIN_LIFETIME_S}"
            )
            return answered(
                302,
                headers=(
                    ("Location", ASTRBOT_KEEP_LOGIN_PATH),
                    ("Set-Cookie", cookie),
                    ("Cache-Control", "no-store"),
                    ("Referrer-Policy", "no-referrer"),
                ),
            )
        now = self._clock()
        if not any(
            is_login_valid(value, key, now) for value in request.cookie_values(name)
        ):
            return refused()
        if path != ASTRBOT_KEEP_LOGIN_PATH:
            return RELAY
        token = self._signed_in(record)
        if not token:
            return answered(502)
        return answered(
            200,
            login_page(token, ASTRBOT_USERNAME),
            content_type="text/html; charset=utf-8",
            headers=(
                ("Cache-Control", "no-store"),
                ("Referrer-Policy", "no-referrer"),
            ),
        )

    def is_body_judged(self, request) -> bool:
        """Whether a request is a save of AstrBot's settings, whose body the forwarder reads.

        Args:
            request: The request, already admitted.

        Returns:
            True for ``PUT /api/v1/system-config``, ``PUT
            /api/v1/config-profiles/<id>`` and ``POST
            /api/config/astrbot/update``.
        """
        path = normal_path(request.path)
        method = request.method.upper()
        if method == "POST":
            return path == ASTRBOT_LEGACY_SAVE_PATH
        if method != "PUT":
            return False
        if path == ASTRBOT_SYSTEM_CONFIG_PATH:
            return True
        profile = path[len(ASTRBOT_PROFILES_PREFIX) :]
        return path.startswith(ASTRBOT_PROFILES_PREFIX) and "/" not in profile

    def admit_body(self, request, body: bytes, record: dict) -> ForwardDecision:
        """The forwarder's rule for a save of AstrBot's settings.

        Args:
            request: The request.
            body: Its whole body.
            record: The module's record.

        Returns:
            401 for a body that is no JSON object and for a save whose
            ``dashboard`` turns SSL or TOTP on, or names another port or
            host; the relay otherwise.
        """
        dashboard = dashboard_of(normal_path(request.path), body)
        if dashboard is None or not is_dashboard_kept(dashboard):
            return refused()
        return RELAY

    def connect(self, record: dict) -> socket.socket:
        """A connection to AstrBot at its published port.

        Args:
            record: The module's record.

        Returns:
            The connected socket.

        Raises:
            OSError: When AstrBot does not answer.
        """
        return socket.create_connection(
            (ASTRBOT_UPSTREAM_HOST, int(record.get("upstream_port", 0) or 0)),
            timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
        )

    # --- the module's own steps ---

    def _settings_step(self):
        """The step ``settings``, which takes ``containers`` shared."""
        return first_start_step(
            AGENT_STEP_SETTINGS, self._run_settings, CONTAINERS_SHARED_LOCKS
        )

    def _run_settings(self, context) -> None:
        """The ``settings`` step: the volume, the settings file or its ``dashboard`` keys, the requirements folder.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when the state
                names no password, the image's Python cannot be read, or a
                volume's script fails.
        """
        config = self._config
        if config is None or not config.password:
            raise _settings_failed("the state names no dashboard password")
        python = self._image_python()
        folder = ASTRBOT_USER_SITE.format(version=python)
        held = self._settings_text()
        record = self._record()
        if held is None:
            self._write_first_settings(config, folder, python, context)
            return
        self._write_volume({}, (folder,))
        if record.get("written_password") == config.password:
            if record.get("python") != python:
                self._keep({**record, "python": python})
            return
        try:
            document = json.loads(held)
        except ValueError as error:
            raise _settings_failed(f"{ASTRBOT_CONFIG_FILE}: {error}") from error
        if not isinstance(document, dict):
            raise _settings_failed(f"{ASTRBOT_CONFIG_FILE} holds no object")
        dashboard = document.get("dashboard")
        document["dashboard"] = {
            **(dashboard if isinstance(dashboard, dict) else {}),
            **dashboard_keys(config.password),
        }
        is_running = self._is_container_running()
        if is_running:
            self._drive("stop")
        self._write_volume({ASTRBOT_CONFIG_FILE: _settings_json(document)}, ())
        if is_running:
            self._drive("start")
        if self._is_stopping(context, "written_password"):
            return
        self._keep(
            {
                **record,
                "written_password": config.password,
                "python": python,
                "is_ready": False,
            }
        )
        self._log(f"{self._name}: the dashboard's password is written")

    def _write_first_settings(
        self, config: AstrbotConfig, folder: str, python: str, context
    ) -> None:
        """Write the settings file into a volume that holds none, and the requirements folder.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when the state
                names no gateway address or the volume's script fails.
        """
        base_url = self._base_url()
        if not base_url:
            raise _settings_failed(
                f"the state names no {ASTRBOT_GATEWAY_URL_VARIABLE} for {ASTRBOT_CONTAINER}"
            )
        document = settings_document(
            password=config.password,
            base_url=base_url,
            model=config.model,
            index_url=self._index_url(),
            context_length=config.context_length,
        )
        self._write_volume({ASTRBOT_CONFIG_FILE: _settings_json(document)}, (folder,))
        if self._is_stopping(context, "written_password"):
            return
        self._keep(
            {
                **self._record(),
                "written_password": config.password,
                "python": python,
                "base_url": base_url,
                "model": config.model,
                "context_length": config.context_length if config.model else 0,
                "provider": provider_id(config.model) if config.model else "",
                "is_provider_own": bool(config.model),
                "added_provider": "",
                "is_ready": False,
            }
        )
        self._log(f"{self._name}: {ASTRBOT_CONFIG_FILE} is written")

    def _run_first_start(self, context) -> None:
        """The ``first_start`` step: ``/`` waited for, then a model or an address the settings file missed given through the API.

        Raises:
            ModuleInstallPending: Until ``/`` has answered 200 once.
        """
        record = self._record()
        if record.get("is_ready"):
            return
        with self._lock:
            self._is_starting = True
        port = int(record.get("upstream_port", 0) or 0)
        if not port or self._health(port) != 200:
            raise ModuleInstallPending(ASTRBOT_PENDING)
        if self._is_stopping(context, "is_ready"):
            return
        record = self._keep({**record, "is_ready": True})
        self._log(f"{self._name}: the first start has ended")
        with self._lock:
            self._is_starting = False
        self._gateway_synced(record)

    def _gateway_synced(self, record: dict) -> dict:
        """The record after AstrBot is given a new gateway address, a new default model and a new context length through its API.

        A call that fails is a line in the log, and the record keeps what it
        held, so the next start tries again.

        Args:
            record: The module's record, its first start ended.

        Returns:
            The record as it stands afterwards.
        """
        config = self._config or AstrbotConfig()
        base_url = self._base_url()
        is_new_url = bool(base_url) and base_url != record.get("base_url")
        is_new_model = bool(config.model) and config.model != record.get("model")
        if not is_new_url and not is_new_model and not _is_new_length(record, config):
            return record
        port = int(record.get("upstream_port", 0) or 0)
        token = self._api_token(port, str(record.get("written_password", "") or ""))
        if not token:
            return record
        if is_new_url:
            if not self._took(
                "the gateway's source",
                port,
                "POST",
                ASTRBOT_SOURCES_PATH,
                {"config": gateway_source(base_url)},
                token,
            ):
                return record
            record = self._keep({**record, "base_url": base_url})
            self._log(f"{self._name}: the gateway's source names {base_url}")
        if is_new_model:
            record = self._model_synced(record, config, port, token)
        if _is_new_length(record, config):
            record = self._length_synced(record, config.context_length, port, token)
        return record

    def _model_synced(
        self, record: dict, config: AstrbotConfig, port: int, token: str
    ) -> dict:
        """The record after the agent's provider follows a new default model.

        A provider the agent adds holds the model's context length.

        Args:
            record: The module's record.
            config: The configuration, with its model.
            port: AstrBot's published port.
            token: AstrBot's login token.

        Returns:
            The record, with the new model and provider once every call took.
        """
        model = config.model
        length = int(record.get("context_length", 0) or 0)
        new = provider_id(model)
        earlier = str(record.get("provider", "") or "")
        held = self._provider_ids(port, token)
        if held is None:
            return record
        is_own = new not in held or record.get("added_provider") == new
        if new not in held:
            if not self._took(
                f"provider {new}",
                port,
                "POST",
                ASTRBOT_SOURCE_PROVIDERS_PATH,
                {"config": gateway_provider(model, config.context_length)},
                token,
            ):
                return record
            length = config.context_length
            record = self._keep({**record, "added_provider": new})
        if not self._default_followed(port, token, earlier, new):
            return record
        if earlier and earlier != new and record.get("is_provider_own"):
            if not self._took(
                f"the deletion of provider {earlier}",
                port,
                "DELETE",
                ASTRBOT_PROVIDERS_PATH + "/" + urllib.parse.quote(earlier, safe="/:"),
                None,
                token,
            ):
                return record
        self._log(f"{self._name}: the agent's provider is {new}")
        return self._keep(
            {
                **record,
                "model": model,
                "context_length": length,
                "provider": new,
                "is_provider_own": is_own,
                "added_provider": "",
            }
        )

    def _length_synced(self, record: dict, length: int, port: int, token: str) -> dict:
        """The record after the agent's provider holds a new context length.

        The provider as AstrBot returns it is written back with its
        ``max_context_tokens`` changed, and AstrBot loads it at once.

        Args:
            record: The module's record, the agent's provider its own.
            length: The configuration's context length.
            port: AstrBot's published port.
            token: AstrBot's login token.

        Returns:
            The record, with the new length once both calls took.
        """
        held = str(record.get("provider", "") or "")
        path = ASTRBOT_PROVIDERS_PATH + "/" + urllib.parse.quote(held, safe="/:")
        status, document = self._api(port, "GET", path, None, token)
        data = document.get("data") if is_ok(status, document) else None
        provider = data.get("provider") if isinstance(data, dict) else None
        if not isinstance(provider, dict):
            self._log(f"{self._name}: provider {held} was not read: {status}")
            return record
        changed = {**provider, ASTRBOT_WINDOW_KEY: length}
        if not self._took(
            f"the context length of provider {held}",
            port,
            "PUT",
            path,
            {"config": changed},
            token,
        ):
            return record
        self._log(f"{self._name}: provider {held} holds {length} tokens")
        return self._keep({**record, "context_length": length})

    def _default_followed(self, port: int, token: str, earlier: str, new: str) -> bool:
        """Whether the ``default`` profile's provider names the new provider, or a provider the person picked.

        Returns:
            False when a call fails.
        """
        status, document = self._api(port, "GET", ASTRBOT_PROFILE_PATH, None, token)
        data = document.get("data") if is_ok(status, document) else None
        profile = data.get("config") if isinstance(data, dict) else None
        if not isinstance(profile, dict):
            self._log(f"{self._name}: the default profile was not read: {status}")
            return False
        current = _nested(profile, ASTRBOT_PROFILE_PROVIDER_PATH)
        if current == new or current not in ("", earlier):
            return True
        changed = copy.deepcopy(profile)
        _set_nested(changed, ASTRBOT_PROFILE_PROVIDER_PATH, new)
        return self._took(
            "the default model", port, "PUT", ASTRBOT_PROFILE_PATH, changed, token
        )

    def _provider_ids(self, port: int, token: str) -> "set | None":
        """The ids of every provider AstrBot holds; None when the list cannot be read."""
        status, document = self._api(port, "GET", ASTRBOT_PROVIDERS_PATH, None, token)
        data = document.get("data") if is_ok(status, document) else None
        providers = data.get("providers") if isinstance(data, dict) else None
        if not isinstance(providers, list):
            self._log(f"{self._name}: the providers were not read: {status}")
            return None
        return {
            str(provider.get("id", ""))
            for provider in providers
            if isinstance(provider, dict)
        }

    def _api_token(self, port: int, password: str) -> str:
        """AstrBot's login token once AstrBot answers, waited for at most 90 seconds; empty after a line in the log."""
        deadline = self._monotonic() + ASTRBOT_START_WAIT_S
        while self._health(port) != 200:
            if self._monotonic() >= deadline:
                self._log(f"{self._name}: AstrBot did not answer, its provider stays")
                return ""
            self._sleep(ASTRBOT_START_POLL_S)
        token = self._login_token(port, password)
        if not token:
            self._log(f"{self._name}: AstrBot refused the login, its provider stays")
        return token

    def _took(
        self, what: str, port: int, method: str, path: str, body, token: str
    ) -> bool:
        """Whether one call to AstrBot's API took; a failure is a line in the log."""
        status, document = self._api(port, method, path, body, token)
        if is_ok(status, document):
            return True
        said = str(document.get("message", "") or "")[:DETAIL_CHARS]
        self._log(f"{self._name}: {what} did not take: {status} {said}".rstrip())
        return False

    def _api(self, port: int, method: str, path: str, body, token: str) -> tuple:
        """One call to AstrBot's API; ``(0, {})`` when AstrBot does not answer."""
        try:
            return self._call(port, method, path, body=body, token=token)
        except OSError as error:
            self._log(f"{self._name}: {method} {path}: {error}")
            return 0, {}

    def _signed_in(self, record: dict) -> str:
        """AstrBot's login token for the record's password; empty when it refuses or does not answer."""
        return self._login_token(
            int(record.get("upstream_port", 0) or 0),
            str(record.get("password", "") or ""),
        )

    def _login_token(self, port: int, password: str) -> str:
        """AstrBot's answer to a login with the dashboard user and a password; empty when it refuses."""
        if not port or not password:
            return ""
        try:
            status, document = self._call(
                port,
                "POST",
                ASTRBOT_LOGIN_PATH,
                body={"username": ASTRBOT_USERNAME, "password": password},
            )
        except OSError:
            return ""
        data = document.get("data") if is_ok(status, document) else None
        token = data.get("token") if isinstance(data, dict) else ""
        return token if isinstance(token, str) else ""

    def _started_record(self) -> dict:
        """The record as this start serves it: the configuration, the ports, running.

        Raises:
            ModuleApplyError: When the published port cannot be kept, or
                no port from 6185 up is free for the forwarder.
        """
        record = self._record()
        config = self._config or AstrbotConfig.from_dict(record)
        try:
            upstream = self._containers.page_port(self._name, ASTRBOT_CONTAINER)
            port = int(record.get("port", 0) or 0) or pick_port(
                ASTRBOT_BASE_PORT,
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
        """The gateway's address with ``/v1`` after it, as the state names it for the container; empty while it names none."""
        try:
            environment = self._containers.hub_environment(ASTRBOT_CONTAINER)
        except (AttributeError, KeyError):
            return ""
        prefix = ASTRBOT_GATEWAY_URL_VARIABLE + "="
        for line in environment:
            if isinstance(line, str) and line.startswith(prefix):
                url = line[len(prefix) :].rstrip("/")
                return url + ASTRBOT_BASE_URL_SUFFIX if url else ""
        return ""

    def _index_url(self) -> str:
        """The first ranked source of the ``pypi`` set; empty while the state names none."""
        held = self._source_sets.get(PYPI_SET)
        held = held if isinstance(held, dict) else {}
        sources = [str(source) for source in held.get("sources") or []]
        if not sources:
            return ""
        order = source_fetch.rank_set(
            sources,
            probe_path=str(held.get("probe", "") or "/"),
            probe_one=self._probe_one,
            latency_paths=held.get("latency_probes") or (),
            log=self._log,
            name=f"{self._name}: source set {PYPI_SET}",
        )
        return order[0] if order else ""

    def _image_python(self) -> str:
        """The major and minor version of the Python in the image the recipe pins.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when the store holds
                no such image or its environment names no Python.
        """
        command = self._command()
        references = self._containers.image_references() if command else set()
        reference = ""
        for image in self._images:
            reference = stored_reference(image["digest"], image["sources"], references)
            if reference:
                break
        if not reference:
            raise _settings_failed("the store holds no image of the recipe")
        try:
            done = self._run(
                [*command, "image", "inspect", "--format", "json", reference],
                is_checked=False,
                timeout_s=60,
            )
            found = json.loads(done.stdout or "[]") if done.is_success else []
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise _settings_failed(f"podman image inspect: {error}") from error
        entry = found[0] if isinstance(found, list) and found else {}
        held = entry.get("Config") if isinstance(entry, dict) else None
        version = python_version((held or {}).get("Env") or [])
        if not version:
            raise _settings_failed(f"{reference} names no {ASTRBOT_PYTHON_VARIABLE}")
        return version

    def _settings_text(self) -> "str | None":
        """The settings file in the volume; None while the volume or the file is missing.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when the volume
                cannot be read.
        """
        done = self._volume(volume_read_script(ASTRBOT_VOLUME, ASTRBOT_CONFIG_FILE))
        lines = (done.stdout or "").splitlines()
        if done.is_success and lines and lines[0].strip() == "missing":
            return None
        if not done.is_success or not lines or lines[0].strip() != "present":
            said = (done.stderr or done.stdout or "").strip()
            raise _settings_failed(f"the volume was not read: {said[:DETAIL_CHARS]}")
        encoded = lines[1].strip() if len(lines) > 1 else ""
        try:
            return base64.b64decode(encoded).decode("utf-8-sig")
        except (binascii.Error, UnicodeDecodeError) as error:
            raise _settings_failed(f"{ASTRBOT_CONFIG_FILE}: {error}") from error

    def _write_volume(self, files: dict, folders: tuple) -> None:
        """Make the volume when missing, its folders, and write each file whole.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when the script
                fails.
        """
        done = self._volume(
            volume_write_script(ASTRBOT_VOLUME, files=files, folders=folders)
        )
        if not done.is_success:
            said = (done.stderr or done.stdout or "").strip()
            raise _settings_failed(f"the volume was not written: {said[:DETAIL_CHARS]}")

    def _volume(self, script: str):
        """Run one of the volume's scripts through the Containers runner.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when it cannot run;
                the machine's own code when it cannot be reached.
        """
        try:
            return self._containers.volume_script(script)
        except (OSError, subprocess.SubprocessError) as error:
            raise _settings_failed(command_detail(error)[:DETAIL_CHARS]) from error

    def _is_container_running(self) -> bool:
        """Whether the container runs now, as ``podman inspect`` reads it."""
        command = self._command()
        if not command:
            return False
        try:
            done = self._run(
                [*command, "inspect", "--format", "json", ASTRBOT_CONTAINER],
                is_checked=False,
                timeout_s=60,
            )
            found = json.loads(done.stdout or "[]") if done.is_success else []
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
        entry = found[0] if isinstance(found, list) and found else {}
        state = entry.get("State") if isinstance(entry, dict) else None
        return isinstance(state, dict) and state.get("Running") is True

    def _drive(self, action: str) -> None:
        """Start or stop the container's unit.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when systemd
                refuses it; the machine's own code when it cannot be
                reached.
        """
        try:
            self._containers.drive_hub_containers([ASTRBOT_CONTAINER], action)
        except (OSError, subprocess.SubprocessError) as error:
            raise _settings_failed(
                f"{action}: {command_detail(error)[:DETAIL_CHARS]}"
            ) from error

    def _command(self) -> tuple:
        """Containers' podman command; empty while it has none or cannot reach it."""
        try:
            return tuple(self._containers.podman_command())
        except (ModuleApplyError, KeyError):
            return ()

    def _record(self) -> dict:
        """The module's record, empty when none is kept."""
        return self._records.read(self._name)

    def _is_stopping(self, context, kept: str) -> bool:
        """Whether the agent began to stop, after a line naming what the record does not keep."""
        if not context.is_stopping():
            return False
        self._log(f"{self._name}: the agent stops, so the record does not keep {kept}")
        return True

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


def _is_new_length(record: dict, config: AstrbotConfig) -> bool:
    """Whether the agent's own provider of the record's model holds another context length than the configuration's."""
    return (
        bool(config.model)
        and config.context_length > 0
        and record.get("model") == config.model
        and bool(record.get("is_provider_own"))
        and int(record.get("context_length", 0) or 0) != config.context_length
    )


def _settings_failed(detail: str) -> ModuleApplyError:
    """The failure of the step ``settings``, ``install_failed {detail}``."""
    return ModuleApplyError("install_failed", {"detail": detail})


def _settings_json(document: dict) -> str:
    """A settings file's text as the agent writes it."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _nested(document: dict, path: tuple) -> str:
    """The text one path of keys names in a document; empty when a level is missing."""
    held = document
    for key in path:
        if not isinstance(held, dict):
            return ""
        held = held.get(key)
    return held if isinstance(held, str) else ""


def _set_nested(document: dict, path: tuple, value: str) -> None:
    """Set one path of keys in a document, making each missing level."""
    held = document
    for key in path[:-1]:
        if not isinstance(held.get(key), dict):
            held[key] = {}
        held = held[key]
    held[path[-1]] = value
