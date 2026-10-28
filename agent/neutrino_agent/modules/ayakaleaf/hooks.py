"""What Ayakaleaf adds to the ``container`` runner: the first start, the page's forwarder, the guests, the health read.

The forwarder listens on ``127.0.0.1`` at a port the agent takes from 8900
up at the first start and keeps in the module's record, and passes requests
on to the app's 80, published on loopback at the port the Containers runner
picked. A request with a token that verifies under the module's secret is
traded for the app's own login as the administrator, and one under a
guest's secret for that guest's login: the forwarder asks ``/login`` for a
session and its CSRF token, posts the e-mail and the password, accepts
every invitation waiting for a guest, hands the browser the session cookie
under the name the hub gives this device, and redirects to ``/project``. A
request with that cookie is passed on with ``Host`` and ``Origin`` as the
browser sent them; every other request, the browser's own ``POST /login``
and every path under ``/launchpad`` is 401.

The first start runs three steps once per install and keeps each one done
in the record: the replica set, with ``rs.initiate`` in the mongo
container; the administrator, through ``/launchpad``; and the Chinese TeX
set, ``tlmgr`` in the app container updating itself and then installing
from the fastest source of the ``ctan`` set. Until all three are done and
``/status`` answers 200, the module reads ``installing`` and its start
waits; a step that fails ends the install. A version change makes the TeX
volume again and runs the TeX step again.

Once the first start has ended, each start makes the guest of every live
Web share the record does not hold, through the app's own routes as the
administrator, and deletes every guest the state no longer names. The
record keeps what the forwarder needs, so it listens again after the agent
restarts.

Not pure: runs podman, opens sockets, writes the record.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import functools
import html
import http.client
import json
import os
import posixpath
import re
import socket
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass

from neutrino_agent.constants import (
    AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
    AGENT_REPORT_INTERVAL_S,
)
from neutrino_agent.exceptions import (
    ModuleApplyError,
    ModuleInstallPending,
    ModuleSetupError,
)
from neutrino_agent.modules.ayakaleaf.config import AyakaleafConfig, AyakaleafGuest
from neutrino_agent.modules.ayakaleaf.constants import (
    AYAKALEAF_ACTIVATE_PATH,
    AYAKALEAF_ADMIN_EMAIL,
    AYAKALEAF_ADMIN_REGISTER_PATH,
    AYAKALEAF_APP_CONTAINER,
    AYAKALEAF_BASE_PORT,
    AYAKALEAF_COOKIE,
    AYAKALEAF_DELETE_USER_PATH,
    AYAKALEAF_FORWARDER_FIELDS,
    AYAKALEAF_GUEST_FAILED,
    AYAKALEAF_GUEST_STEP_ADMIN_LOGIN,
    AYAKALEAF_GUEST_STEP_NAME,
    AYAKALEAF_GUEST_STEP_PASSWORD,
    AYAKALEAF_GUEST_STEP_REGISTER,
    AYAKALEAF_GUESTS_PENDING,
    AYAKALEAF_INVITE_PATH,
    AYAKALEAF_INVITE_TEMPLATE,
    AYAKALEAF_LAUNCHPAD_PATH,
    AYAKALEAF_LOGIN_PATH,
    AYAKALEAF_MONGO_CONTAINER,
    AYAKALEAF_MONGO_SHELL,
    AYAKALEAF_PASSWORD_SET_PATH,
    AYAKALEAF_PENDING,
    AYAKALEAF_PODMAN_TIMEOUT_S,
    AYAKALEAF_PROJECT_PATH,
    AYAKALEAF_RECORD_FIELDS,
    AYAKALEAF_REGISTER_ADMIN_PATH,
    AYAKALEAF_REPLICA_SET_INITIATE,
    AYAKALEAF_REPLICA_SET_WAIT_S,
    AYAKALEAF_SETTINGS_PATH,
    AYAKALEAF_SETUP_FAILED,
    AYAKALEAF_STATUS_PATH,
    AYAKALEAF_STATUS_TIMEOUT_S,
    AYAKALEAF_STEP_ADMIN,
    AYAKALEAF_STEP_REPLICA_SET,
    AYAKALEAF_STEP_TEX,
    AYAKALEAF_TEX_COLLECTIONS,
    AYAKALEAF_TEX_REPOSITORY_PATH,
    AYAKALEAF_TEX_SET,
    AYAKALEAF_TEX_TIMEOUT_S,
    AYAKALEAF_TEX_VERBS,
    AYAKALEAF_TEX_VOLUME,
    AYAKALEAF_UPSTREAM_HOST,
)
from neutrino_agent.modules.podman.container_runner import ContainerHooks
from neutrino_agent.modules.shared import source_fetch
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

# How much of a failed step's words a detail keeps.
DETAIL_CHARS = 200
# The CSRF token a page of the app holds, and the JSON a ``<meta>`` holds.
CSRF_PATTERN = re.compile(r'<meta name="ol-csrfToken" content="([^"]*)"')
META_PATTERN = '<meta name="{name}"[^>]*content="([^"]*)"'
# The statuses that send the browser elsewhere.
REDIRECT_STATUSES = (301, 302, 303, 307, 308)


def route_path(path: str) -> str:
    """A path as the app's router matches it: decoded, slashes collapsed, dot segments resolved, lower case.

    Args:
        path: The request's path, without the query.

    Returns:
        The path, ``/`` for an empty one.
    """
    decoded = urllib.parse.unquote(path)
    while "//" in decoded:
        decoded = decoded.replace("//", "/")
    resolved = posixpath.normpath("/" + decoded.lstrip("/"))
    return (resolved.rstrip("/") or "/").lower()


def is_login_route(method: str, path: str) -> bool:
    """Whether a request is one the browser never sends the app: its own login, or the launchpad.

    Args:
        method: The request's method.
        path: Its path, without the query.

    Returns:
        True for ``POST /login`` and for every path under ``/launchpad``.
    """
    route = route_path(path)
    if route == AYAKALEAF_LAUNCHPAD_PATH or route.startswith(
        AYAKALEAF_LAUNCHPAD_PATH + "/"
    ):
        return True
    return method.upper() == "POST" and route == AYAKALEAF_LOGIN_PATH


def meta_json(text: str, name: str):
    """The JSON one ``<meta>`` of a page holds.

    Args:
        text: The page.
        name: The ``<meta>``'s name, such as ``ol-notifications``.

    Returns:
        The value; None when the page holds no such ``<meta>`` or it holds
        no JSON.
    """
    found = re.search(META_PATTERN.format(name=re.escape(name)), text)
    if found is None:
        return None
    try:
        return json.loads(html.unescape(found.group(1)))
    except ValueError:
        return None


def invitations(text: str) -> list:
    """The invitations waiting on the project list a guest signed in to.

    Args:
        text: The ``/project`` page.

    Returns:
        ``(project_id, token)`` of each invitation its ``ol-notifications``
        names, in order.
    """
    held = meta_json(text, "ol-notifications")
    found = []
    for notification in held if isinstance(held, list) else []:
        if not isinstance(notification, dict):
            continue
        if notification.get("templateKey") != AYAKALEAF_INVITE_TEMPLATE:
            continue
        options = notification.get("messageOpts")
        if not isinstance(options, dict):
            continue
        project = str(options.get("projectId", "") or "")
        token = str(options.get("token", "") or "")
        if re.fullmatch(r"[0-9a-f]{24}", project) and re.fullmatch(
            r"[A-Za-z0-9_-]+", token
        ):
            found.append((project, token))
    return found


def activation(url: str) -> tuple:
    """The ``user_id`` and the ``token`` a new account's activation address holds.

    Args:
        url: ``setNewPasswordUrl`` as ``/admin/register`` answers it.

    Returns:
        ``(user_id, token)``; empty strings for an address that holds
        neither.
    """
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    user_id = (query.get("user_id") or [""])[0]
    token = (query.get("token") or [""])[0]
    if not re.fullmatch(r"[0-9a-f]{24}", user_id) or not token:
        return "", ""
    return user_id, token


def last_line(text: str) -> str:
    """The last line a tool wrote that holds anything, cut to the detail's length."""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return (lines[-1] if lines else "")[:DETAIL_CHARS]


def status_code(port: int) -> int:
    """The status the app's ``/status`` answers with at its published port.

    Args:
        port: The loopback port the app is published at.

    Returns:
        The HTTP status; 0 when nothing answers.
    """
    connection = http.client.HTTPConnection(
        AYAKALEAF_UPSTREAM_HOST, port, timeout=AYAKALEAF_STATUS_TIMEOUT_S
    )
    try:
        connection.request("GET", AYAKALEAF_STATUS_PATH)
        response = connection.getresponse()
        response.read()
        return int(response.status)
    except (OSError, http.client.HTTPException):
        return 0
    finally:
        connection.close()


@dataclass(frozen=True)
class AppAnswer:
    """One answer of the app.

    Attributes:
        status: The HTTP status.
        text: The body, decoded.
        headers: ``(name, value)`` pairs as the app sent them.
    """

    status: int
    text: str
    headers: tuple

    @property
    def location(self) -> str:
        """Where a redirect points; empty for none."""
        for name, value in self.headers:
            if name.lower() == "location":
                return value
        return ""


class AppBrowser:
    """One browser of the app at its published port: its cookies and the CSRF token of its last page.

    Each request goes on a connection of its own to the published port,
    with the ``Host`` given, the cookies the app set so far and no
    ``Origin``.

    Attributes:
        csrf: The CSRF token of the last page that held one.
        session_header: The last ``Set-Cookie`` of the session cookie, as
            the app sent it; empty before one.
    """

    def __init__(
        self,
        *,
        port: int,
        cookie_name: str = AYAKALEAF_COOKIE,
        host: str = "",
        timeout_s: float = AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
    ):
        """
        Args:
            port: The loopback port the app is published at.
            cookie_name: The name of the app's session cookie.
            host: The ``Host`` every request names; empty names the
                published port's own.
            timeout_s: How long one request may take.
        """
        self._port = int(port)
        self._cookie_name = cookie_name
        self._host = host or f"{AYAKALEAF_UPSTREAM_HOST}:{self._port}"
        self._timeout_s = timeout_s
        # Each cookie the app set, by name, the last value kept.
        self._cookies: dict = {}
        self.csrf = ""
        self.session_header = ""

    def get(self, path: str) -> AppAnswer:
        """Ask for one page.

        Args:
            path: The path and its query.

        Returns:
            The answer.

        Raises:
            OSError: When the app does not answer.
        """
        return self._send("GET", path, None)

    def post(self, path: str, fields: dict) -> AppAnswer:
        """Post JSON to one route with the CSRF token of the last page.

        Args:
            path: The route.
            fields: The body's fields, ``_csrf`` added.

        Returns:
            The answer.

        Raises:
            OSError: When the app does not answer.
        """
        return self._send("POST", path, {**fields, "_csrf": self.csrf})

    def _send(self, method: str, path: str, body: "dict | None") -> AppAnswer:
        connection = http.client.HTTPConnection(
            AYAKALEAF_UPSTREAM_HOST, self._port, timeout=self._timeout_s
        )
        headers = {"Host": self._host}
        if self._cookies:
            headers["Cookie"] = "; ".join(
                f"{name}={value}" for name, value in self._cookies.items()
            )
        data = None
        if body is None:
            headers["Accept"] = "text/html"
        else:
            data = json.dumps(body).encode("utf-8")
            headers["Accept"] = "application/json"
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            text = response.read().decode("utf-8", "replace")
            answer = AppAnswer(int(response.status), text, tuple(response.getheaders()))
        except http.client.HTTPException as error:
            raise ConnectionError(f"{path}: {error}") from error
        finally:
            connection.close()
        for name, value in answer.headers:
            if name.lower() != "set-cookie":
                continue
            cookie, _, held = value.split(";", 1)[0].partition("=")
            self._cookies[cookie.strip()] = held.strip()
            if cookie.strip() == self._cookie_name:
                self.session_header = value
        found = CSRF_PATTERN.search(answer.text)
        if found is not None:
            self.csrf = html.unescape(found.group(1))
        return answer


def refusal(answer: AppAnswer, path: str) -> str:
    """The words for an answer a step did not want."""
    said = last_line(answer.text) if len(answer.text) < 500 else ""
    return f"{path} answered {answer.status}" + (f": {said}" if said else "")


def sign_in(browser: AppBrowser, email: str, password: str) -> AppAnswer:
    """Sign a browser in as an account, as the app's login page does.

    ``GET /login`` gives the session and its CSRF token, ``POST /login``
    signs in, and ``GET /project`` gives the CSRF token of the new session.

    Args:
        browser: The browser.
        email: The account's e-mail.
        password: Its password.

    Returns:
        The project list's answer.

    Raises:
        ConnectionError: When a step's answer is not the one it wants.
        OSError: When the app does not answer.
    """
    page = browser.get(AYAKALEAF_LOGIN_PATH)
    if page.status != 200 or not browser.csrf:
        raise ConnectionError(refusal(page, AYAKALEAF_LOGIN_PATH))
    answer = browser.post(AYAKALEAF_LOGIN_PATH, {"email": email, "password": password})
    if answer.status != 200:
        raise ConnectionError(refusal(answer, AYAKALEAF_LOGIN_PATH))
    projects = browser.get(AYAKALEAF_PROJECT_PATH)
    if projects.status != 200:
        raise ConnectionError(refusal(projects, AYAKALEAF_PROJECT_PATH))
    return projects


def accept_invitations(browser: AppBrowser, projects: AppAnswer, log=print) -> int:
    """Accept every invitation waiting for a signed-in guest.

    Args:
        browser: The guest's browser.
        projects: The project list's answer at its sign-in.
        log: Called with each failure.

    Returns:
        How many invitations the app accepted.

    Raises:
        OSError: When the app does not answer.
    """
    accepted = 0
    for project, token in invitations(projects.text):
        path = AYAKALEAF_INVITE_PATH.format(project_id=project, token=token)
        browser.get(path)
        answer = browser.post(path + "/accept", {})
        if answer.status in (200, *REDIRECT_STATUSES):
            accepted += 1
        else:
            log(f"ayakaleaf: an invitation stays waiting: {refusal(answer, path)}")
    return accepted


def register_admin(browser: AppBrowser, email: str, password: str) -> None:
    """Make the app's first administrator through ``/launchpad``.

    Args:
        browser: A browser with no session.
        email: The administrator's e-mail.
        password: Its password.

    Raises:
        ConnectionError: When ``/launchpad`` sends the browser to
            ``/login``, since an administrator exists, or a step's answer is
            not the one it wants.
        OSError: When the app does not answer.
    """
    page = browser.get(AYAKALEAF_LAUNCHPAD_PATH)
    if page.status in REDIRECT_STATUSES and AYAKALEAF_LOGIN_PATH in page.location:
        raise ConnectionError(
            f"{AYAKALEAF_LAUNCHPAD_PATH} sends to {AYAKALEAF_LOGIN_PATH}:"
            " an administrator exists"
        )
    if page.status != 200 or not browser.csrf:
        raise ConnectionError(refusal(page, AYAKALEAF_LAUNCHPAD_PATH))
    answer = browser.post(
        AYAKALEAF_REGISTER_ADMIN_PATH, {"email": email, "password": password}
    )
    if answer.status != 200:
        raise ConnectionError(refusal(answer, AYAKALEAF_REGISTER_ADMIN_PATH))


def _guest_failed(step: str, error: BaseException) -> ModuleApplyError:
    """A guest's failure at one step, its detail the error's words."""
    return ModuleApplyError(
        AYAKALEAF_GUEST_FAILED, {"step": step, "detail": str(error)[:DETAIL_CHARS]}
    )


def make_guest(admin: AppBrowser, guest: AyakaleafGuest, browser) -> str:
    """Make one guest account through the app's own routes.

    The administrator registers the e-mail, the guest's activation sets its
    password, and the guest names its account.

    Args:
        admin: A browser signed in as the administrator.
        guest: The guest.
        browser: Called with no arguments; returns a new browser with no
            session.

    Returns:
        The account's ``user_id``.

    Raises:
        ModuleApplyError: ``ayakaleaf_guest_failed {step, detail}``,
            ``step`` being ``register``, ``password`` or ``name``.
    """
    try:
        answer = admin.post(AYAKALEAF_ADMIN_REGISTER_PATH, {"email": guest.email})
        if answer.status != 200:
            raise ConnectionError(refusal(answer, AYAKALEAF_ADMIN_REGISTER_PATH))
        try:
            url = str(json.loads(answer.text).get("setNewPasswordUrl", "") or "")
        except (ValueError, AttributeError):
            url = ""
        user_id, token = activation(url)
        if not user_id:
            raise ConnectionError(
                f"{AYAKALEAF_ADMIN_REGISTER_PATH} named no activation address"
            )
    except OSError as error:
        raise _guest_failed(AYAKALEAF_GUEST_STEP_REGISTER, error) from error
    try:
        activating = browser()
        query = urllib.parse.urlencode({"token": token, "user_id": user_id})
        page = activating.get(f"{AYAKALEAF_ACTIVATE_PATH}?{query}")
        if page.status != 200 or not activating.csrf:
            raise ConnectionError(refusal(page, AYAKALEAF_ACTIVATE_PATH))
        answer = activating.post(
            AYAKALEAF_PASSWORD_SET_PATH,
            {"passwordResetToken": token, "password": guest.password},
        )
        if answer.status != 200:
            raise ConnectionError(refusal(answer, AYAKALEAF_PASSWORD_SET_PATH))
    except OSError as error:
        raise _guest_failed(AYAKALEAF_GUEST_STEP_PASSWORD, error) from error
    try:
        naming = browser()
        sign_in(naming, guest.email, guest.password)
        answer = naming.post(
            AYAKALEAF_SETTINGS_PATH, {"first_name": guest.account, "last_name": ""}
        )
        if not 200 <= answer.status < 300:
            raise ConnectionError(refusal(answer, AYAKALEAF_SETTINGS_PATH))
    except OSError as error:
        raise _guest_failed(AYAKALEAF_GUEST_STEP_NAME, error) from error
    return user_id


def delete_guest(admin: AppBrowser, user_id: str) -> bool:
    """Delete one guest account through the administrator's route.

    Args:
        admin: A browser signed in as the administrator.
        user_id: The account's ``user_id``.

    Returns:
        True once the account is gone: deleted now, or 422 for one the app
        no longer holds.

    Raises:
        OSError: When the app does not answer.
    """
    path = AYAKALEAF_DELETE_USER_PATH.format(user_id=user_id)
    answer = admin.post(path, {})
    return answer.status in (200, 422)


def _forwarder(*, name: str, record: dict, hooks, log) -> InstanceForwarder:
    """The page's forwarder, trying a port another program holds every report interval."""
    return InstanceForwarder(
        name=name,
        record={**record, "account": ""},
        hooks=hooks,
        log=log,
        retry_s=AGENT_REPORT_INTERVAL_S,
    )


def _browser(*, port: int, cookie_name: str, host: str = "") -> AppBrowser:
    return AppBrowser(port=port, cookie_name=cookie_name, host=host)


class AyakaleafHooks(ContainerHooks):
    """Ayakaleaf's first start, forwarder, guests, health read and version change."""

    # What the forwarder reads of the record.
    secret_field = "secret"
    forwarder_fields = AYAKALEAF_FORWARDER_FIELDS

    def __init__(
        self,
        *,
        platform,
        name: str,
        containers,
        log=print,
        run_command=run,
        status=status_code,
        browser_factory=_browser,
        forwarder_factory=None,
        record_dir: str = "",
        is_port_free=is_port_free,
        probe_one=source_fetch.probe,
        clock=time.monotonic,
    ):
        """
        Args:
            platform: The machine's platform.
            name: The module's name.
            containers: The Containers runner, which reaches Podman and
                keeps the app's published port.
            log: Called with each progress line.
            run_command: Runs one command, as :func:`subprocess_run.run`.
            status: Returns the status ``/status`` answers with at a port.
            browser_factory: Called with ``port``, ``cookie_name`` and
                ``host``; returns an :class:`AppBrowser`.
            forwarder_factory: Called with ``name``, ``record``, ``hooks``
                and ``log``; returns a forwarder. None makes an
                :class:`InstanceForwarder` that tries a held port again every
                report interval.
            record_dir: Where the record lives; empty is the module's
                directory under ``platform.agent_var_dir()``.
            is_port_free: Answers whether a loopback port can be bound now.
            probe_one: Probes one source, as :func:`source_fetch.probe`.
            clock: Seconds that only go forward, for the replica set's wait.
        """
        super().__init__(platform=platform, name=name, containers=containers, log=log)
        self._run = run_command
        self._status = status
        self._browser_factory = browser_factory
        self._forwarder_factory = forwarder_factory or _forwarder
        self._is_port_free = is_port_free
        self._probe_one = probe_one
        self._clock = clock
        self._records = InstanceRecordStore(
            directory=record_dir or os.path.join(platform.agent_var_dir(), name),
            fields=AYAKALEAF_RECORD_FIELDS,
        )
        self._lock = threading.Lock()
        self._config: "AyakaleafConfig | None" = None
        self._source_sets: dict = {}
        self._forwarder = None
        # The guests made, as the record keeps them, which the forwarder
        # signs a visitor in as.
        self._guests: tuple = ()
        self._replica_since: "float | None" = None
        self._is_resumed = False
        self._is_starting = False

    # --- what the container runner calls ---

    def take_source_sets(self, source_sets: dict) -> None:
        """Take the state's source sets, the ``ctan`` set the TeX step reads among them.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """
        self._source_sets = dict(source_sets)

    def apply(self, config: dict) -> None:
        """Take the module's configuration.

        Args:
            config: ``{secret, password, cookie_name, local_name, guests}``.
        """
        self._config = AyakaleafConfig.from_dict(config)

    def installed(self, version: str) -> None:
        """Note the recipe's version, at the install and at each start; a new one makes the TeX volume again.

        Args:
            version: The version the recipe names.
        """
        record = self._record()
        held = str(record.get("version", "") or "")
        if held == version:
            return
        steps = list(record.get("steps") or [])
        if held:
            self._log(f"{self._name}: {held} to {version}, the TeX volume made again")
            self._reset_tex()
            steps = [step for step in steps if step != AYAKALEAF_STEP_TEX]
        self._keep({**record, "version": version, "steps": steps, "is_ready": False})

    def start(self) -> None:
        """Serve the page, run the first start's steps the record does not hold, then settle the guests.

        Raises:
            ModuleInstallPending: Until the steps are done and ``/status``
                answers 200, and while a guest is owed and the app does not
                answer.
            ModuleSetupError: ``ayakaleaf_setup_failed {step, detail}``
                when a step of the first start fails.
            ModuleApplyError: When the Containers runner cannot keep the
                app's published port.
        """
        record = self._started_record()
        self._sync_forwarder(record)
        if not record.get("is_ready"):
            with self._lock:
                self._is_starting = True
            try:
                record = self._first_start(record)
            except ModuleSetupError:
                with self._lock:
                    self._is_starting = False
                raise
            with self._lock:
                self._is_starting = False
        self._settle_guests(record)

    def stop(self) -> None:
        """Stop serving the page."""
        with self._lock:
            self._is_starting = False
        record = self._record()
        if record:
            self._keep({**record, "is_stopped": True})
        self._close_forwarder()

    def is_running(self) -> bool:
        """Whether the app's ``/status`` answers 200 at its published port.

        Returns:
            False before the app has a published port.
        """
        record = self._resume()
        port = int(record.get("upstream_port", 0) or 0)
        return bool(port) and self._status(port) == 200

    def is_installing(self) -> bool:
        """Whether the module's start waits on its first start, after the install or a version change."""
        with self._lock:
            is_starting = self._is_starting
        return is_starting and not self._record().get("is_ready")

    def details(self) -> dict:
        """The forwarder's port, and each guest the hooks made or tried.

        Returns:
            ``{"port", "guests"}``: the port 0 before the first start took
            one; each guest the record holds as ``{account, code,
            params}``, ``code`` empty once made and
            ``ayakaleaf_guest_failed`` while a step fails.
        """
        record = self._resume()
        guests = [
            {"account": str(guest["account"]), "code": "", "params": {}}
            for guest in record.get("guests") or []
            if isinstance(guest, dict) and guest.get("account")
        ]
        failures = record.get("guest_failures")
        for account, failure in (
            failures.items() if isinstance(failures, dict) else ()
        ):
            if isinstance(failure, dict):
                guests.append(
                    {
                        "account": str(account),
                        "code": AYAKALEAF_GUEST_FAILED,
                        "params": dict(failure),
                    }
                )
        return {"port": int(record.get("port", 0) or 0), "guests": guests}

    def remove(self) -> None:
        """Stop serving the page and forget the record, with its directory when nothing else is in it."""
        with self._lock:
            self._is_starting = False
            self._guests = ()
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
            401 for ``POST /login`` and every path under ``/launchpad``
            whatever it holds, for a token that verifies under no secret
            and for a request with neither a token nor the session cookie
            under the record's name; a redirect to ``/project`` carrying the
            app's cookie for a token under the module's secret, signed in as
            the administrator, or under a made guest's secret, signed in as
            that guest, 502 when the app refuses the login or does not
            answer; the relay for a request with the cookie.
        """
        if is_login_route(request.method, request.path):
            return refused()
        if request.token:
            host = request.header("host")
            if request.take_token():
                cookie = self._signed_in(
                    record,
                    AYAKALEAF_ADMIN_EMAIL,
                    str(record.get("password", "") or ""),
                    host,
                )
            else:
                guest = self._token_guest(request)
                if guest is None:
                    return refused()
                cookie = self._signed_in(
                    record,
                    str(guest.get("email", "") or ""),
                    str(guest.get("password", "") or ""),
                    host,
                    is_guest=True,
                )
            if not cookie:
                return answered(502)
            return answered(
                302,
                headers=(
                    ("Location", AYAKALEAF_PROJECT_PATH),
                    ("Set-Cookie", cookie),
                    ("Cache-Control", "no-store"),
                    ("Referrer-Policy", "no-referrer"),
                ),
            )
        if request.cookie_values(_cookie_name(record)):
            return RELAY
        return refused()

    def connect(self, record: dict) -> socket.socket:
        """A connection to the app at its published port.

        Args:
            record: The module's record.

        Returns:
            The connected socket.

        Raises:
            OSError: When the app does not answer.
        """
        return socket.create_connection(
            (AYAKALEAF_UPSTREAM_HOST, int(record.get("upstream_port", 0) or 0)),
            timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
        )

    # --- the module's own steps ---

    def _token_guest(self, request) -> "dict | None":
        """The made guest whose secret the request's token verifies under, spent; None for none."""
        with self._lock:
            guests = self._guests
        for guest in guests:
            secret = str(guest.get("secret", "") or "")
            if secret and request.take_token(secret=secret):
                return guest
        return None

    def _signed_in(
        self,
        record: dict,
        email: str,
        password: str,
        host: str,
        *,
        is_guest: bool = False,
    ) -> str:
        """The app's ``Set-Cookie`` of the session an account signed in to; empty when the app refuses or does not answer.

        A guest's waiting invitations are accepted before the cookie is
        handed back.
        """
        browser = self._browser_factory(
            port=int(record.get("upstream_port", 0) or 0),
            cookie_name=_cookie_name(record),
            host=host,
        )
        try:
            projects = sign_in(browser, email, password)
            if is_guest:
                accept_invitations(browser, projects, log=self._log)
        except OSError as error:
            self._log(f"{self._name}: the sign-in failed: {str(error)[:DETAIL_CHARS]}")
            return ""
        return browser.session_header

    def _first_start(self, record: dict) -> dict:
        """Run the steps the record does not hold, then wait for ``/status``; the record with ``is_ready``.

        Raises:
            ModuleInstallPending: While mongo or the app does not answer
                yet.
            ModuleSetupError: When a step fails.
        """
        steps = list(record.get("steps") or [])
        port = int(record.get("upstream_port", 0) or 0)
        if AYAKALEAF_STEP_REPLICA_SET not in steps:
            self._initiate_replica_set()
            steps.append(AYAKALEAF_STEP_REPLICA_SET)
            record = self._keep({**record, "steps": steps})
            self._log(f"{self._name}: the replica set exists")
        if self._status(port) != 200:
            raise ModuleInstallPending(AYAKALEAF_PENDING)
        if AYAKALEAF_STEP_ADMIN not in steps:
            try:
                register_admin(
                    self._browser_factory(port=port, cookie_name=_cookie_name(record)),
                    AYAKALEAF_ADMIN_EMAIL,
                    str(record.get("password", "") or ""),
                )
            except OSError as error:
                raise _setup_failed(AYAKALEAF_STEP_ADMIN, str(error)) from error
            steps.append(AYAKALEAF_STEP_ADMIN)
            record = self._keep({**record, "steps": steps})
            self._log(f"{self._name}: the administrator is made")
        if AYAKALEAF_STEP_TEX not in steps:
            self._install_tex()
            steps.append(AYAKALEAF_STEP_TEX)
            record = self._keep({**record, "steps": steps})
            self._log(f"{self._name}: the Chinese TeX set is installed")
        if self._status(port) != 200:
            raise ModuleInstallPending(AYAKALEAF_PENDING)
        self._log(f"{self._name}: the first start has ended")
        return self._keep({**record, "is_ready": True})

    def _initiate_replica_set(self) -> None:
        """Initiate the replica set in the mongo container, trying again while mongod starts.

        Raises:
            ModuleInstallPending: While mongosh fails within the wait.
            ModuleSetupError: When it still fails after the wait.
        """
        done = self._podman(
            [
                "exec",
                AYAKALEAF_MONGO_CONTAINER,
                *AYAKALEAF_MONGO_SHELL,
                AYAKALEAF_REPLICA_SET_INITIATE,
            ]
        )
        if done is not None and done.is_success:
            self._replica_since = None
            return
        detail = last_line(done.stderr or done.stdout) if done is not None else ""
        now = self._clock()
        if self._replica_since is None:
            self._replica_since = now
        if now - self._replica_since < AYAKALEAF_REPLICA_SET_WAIT_S:
            self._log(f"{self._name}: the replica set waits on mongo: {detail}")
            raise ModuleInstallPending(AYAKALEAF_PENDING)
        self._replica_since = None
        raise _setup_failed(AYAKALEAF_STEP_REPLICA_SET, detail or "mongosh failed")

    def _install_tex(self) -> None:
        """Install the Chinese TeX set with ``tlmgr``, from each source of the ``ctan`` set fastest first.

        Raises:
            ModuleSetupError: When no source serves it.
        """
        held = self._source_sets.get(AYAKALEAF_TEX_SET)
        held = held if isinstance(held, dict) else {}
        sources = [str(source) for source in held.get("sources") or []]
        if not sources:
            raise _setup_failed(
                AYAKALEAF_STEP_TEX, f"the state names no {AYAKALEAF_TEX_SET} source"
            )
        order = source_fetch.rank_set(
            sources,
            probe_path=str(held.get("probe", "") or "/"),
            probe_one=self._probe_one,
        )
        detail = ""
        for source in order:
            repository = source.rstrip("/") + AYAKALEAF_TEX_REPOSITORY_PATH
            self._log(f"{self._name}: tlmgr installs from {repository}")
            for verb in AYAKALEAF_TEX_VERBS:
                done = self._podman(
                    [
                        "exec",
                        AYAKALEAF_APP_CONTAINER,
                        "tlmgr",
                        "--repository",
                        repository,
                        *verb,
                    ],
                    timeout_s=AYAKALEAF_TEX_TIMEOUT_S,
                )
                if done is None or not done.is_success:
                    break
            else:
                return
            detail = (
                last_line(done.stderr or done.stdout) if done is not None else ""
            ) or "tlmgr failed"
            self._log(f"{self._name}: tlmgr from {source}: {detail}")
        raise _setup_failed(AYAKALEAF_STEP_TEX, detail)

    def _settle_guests(self, record: dict) -> dict:
        """Make each guest the state names and the record does not hold, and delete each one it no longer names.

        Raises:
            ModuleInstallPending: While a guest is owed and the app does
                not answer.
        """
        config = self._config or AyakaleafConfig.from_dict(record)
        wanted = {guest.account: guest for guest in config.guests}
        made = {}
        for held in record.get("guests") or []:
            if isinstance(held, dict) and held.get("account"):
                made[str(held["account"])] = dict(held)
        for account, guest in wanted.items():
            if account in made:
                made[account]["secret"] = guest.secret
        held_failures = record.get("guest_failures")
        failures = {
            account: dict(failure)
            for account, failure in (
                held_failures.items() if isinstance(held_failures, dict) else ()
            )
            if account in wanted and account not in made and isinstance(failure, dict)
        }
        owed = [guest for account, guest in wanted.items() if account not in made]
        gone = [account for account in made if account not in wanted]
        if owed or gone:
            port = int(record.get("upstream_port", 0) or 0)
            if self._status(port) != 200:
                self._keep_guests(record, made, failures)
                raise ModuleInstallPending(AYAKALEAF_GUESTS_PENDING)
            admin = self._browser_factory(port=port, cookie_name=_cookie_name(record))
            try:
                sign_in(
                    admin, AYAKALEAF_ADMIN_EMAIL, str(record.get("password", "") or "")
                )
            except OSError as error:
                for guest in owed:
                    failures[guest.account] = {
                        "step": AYAKALEAF_GUEST_STEP_ADMIN_LOGIN,
                        "detail": str(error)[:DETAIL_CHARS],
                    }
                self._log(f"{self._name}: guests wait: {str(error)[:DETAIL_CHARS]}")
                return self._keep_guests(record, made, failures)
            for guest in owed:
                try:
                    user_id = make_guest(
                        admin,
                        guest,
                        functools.partial(
                            self._browser_factory,
                            port=port,
                            cookie_name=_cookie_name(record),
                        ),
                    )
                except ModuleApplyError as error:
                    failures[guest.account] = dict(error.params)
                    self._log(f"{self._name}: {guest.account}: {error.params}")
                    continue
                made[guest.account] = {**guest.to_dict(), "user_id": user_id}
                failures.pop(guest.account, None)
                self._log(f"{self._name}: the guest {guest.account} is made")
            for account in gone:
                try:
                    is_gone = delete_guest(admin, str(made[account].get("user_id", "")))
                except OSError as error:
                    is_gone = False
                    self._log(f"{self._name}: {account} stays: {error}")
                if is_gone:
                    del made[account]
                    self._log(f"{self._name}: the guest {account} is deleted")
        return self._keep_guests(record, made, failures)

    def _keep_guests(self, record: dict, made: dict, failures: dict) -> dict:
        """Write the guests made and the failures into the record, and hand the made ones to the forwarder."""
        kept = self._keep(
            {**record, "guests": list(made.values()), "guest_failures": failures}
        )
        self._take_guests(kept)
        return kept

    def _take_guests(self, record: dict) -> None:
        """Take the guests a record holds as the ones the forwarder signs visitors in as."""
        guests = tuple(
            dict(guest)
            for guest in record.get("guests") or []
            if isinstance(guest, dict)
        )
        with self._lock:
            self._guests = guests

    def _started_record(self) -> dict:
        """The record as this start serves it: the configuration, the ports, running.

        Raises:
            ModuleApplyError: When the published port cannot be kept, or
                no port from 8900 up is free for the forwarder.
        """
        record = self._record()
        config = self._config or AyakaleafConfig.from_dict(record)
        try:
            upstream = self._containers.page_port(self._name, AYAKALEAF_APP_CONTAINER)
            port = int(record.get("port", 0) or 0) or pick_port(
                AYAKALEAF_BASE_PORT,
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

    def _reset_tex(self) -> None:
        """Stop the app, and make the TeX volume again."""
        names = list(self._containers.hub_names().get(self._name, []))
        if AYAKALEAF_APP_CONTAINER in names:
            try:
                self._containers.drive_hub_containers([AYAKALEAF_APP_CONTAINER], "stop")
            except (OSError, subprocess.SubprocessError) as error:
                self._log(f"{self._name}: stop: {command_detail(error)[:DETAIL_CHARS]}")
        self._podman(["volume", "rm", "-f", AYAKALEAF_TEX_VOLUME])
        self._podman(["volume", "create", AYAKALEAF_TEX_VOLUME])

    def _podman(self, arguments: list, *, timeout_s: int = AYAKALEAF_PODMAN_TIMEOUT_S):
        """Run one podman command; None when it cannot run, its result otherwise."""
        command = self._command()
        if not command:
            return None
        try:
            return self._run(
                [*command, *arguments], is_checked=False, timeout_s=timeout_s
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
        self._take_guests(record)
        if record and not record.get("is_stopped"):
            self._sync_forwarder(record)
        return record

    def _sync_forwarder(self, record: dict) -> None:
        """Run one forwarder for the record as it stands."""
        with self._lock:
            is_first = not self._is_resumed
            self._is_resumed = True
            current = self._forwarder
            if current is not None and current.matches(record):
                return
            self._forwarder = None
        if is_first:
            self._take_guests(record)
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


def _cookie_name(record: dict) -> str:
    """The name of the app's session cookie the record holds, the app's default when it holds none."""
    return str(record.get("cookie_name", "") or "") or AYAKALEAF_COOKIE


def _setup_failed(step: str, detail: str) -> ModuleSetupError:
    """A first-start step's failure, ``ayakaleaf_setup_failed {step, detail}``."""
    return ModuleSetupError(
        AYAKALEAF_SETUP_FAILED, {"step": step, "detail": str(detail)[:DETAIL_CHARS]}
    )
