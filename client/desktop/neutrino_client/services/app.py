"""The apps: what a person uses as one thing, each entry forwarded at its fixed number.

An app is one program on one machine, with one or more ``web``, ``port`` and
``ssh`` entries. **Use** forwards every entry the app has not got at its
fixed local port, the person's number or else the hub's ``local_port``, and
opens nothing; an entry with no number, the hub having sent none and the
person set none, gets no forward until one comes. A failure is the first
refusal; the forwards that started stay up. **Open**, on an app in use,
opens the system browser at the app's first ``http`` or ``https`` entry, in
the order the hub lists them, at ``<scheme>://<local name>:<local
port><path>``; an entry with ``is_token_required`` takes a fresh token from
the ``service`` frame and opens with ``?tkn=<token>``. On macOS, whose
browser resolves no ``.localhost`` name, the host is ``127.0.0.1``.
**Stop** ends every forward of the app.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import urllib.parse

from neutrino_client.services.base import channel_refusal, is_unhealthy, service_key
from neutrino_client.services.forward import (
    FORWARD_BIND_HOST,
    FORWARD_PROTOCOL_TCP,
    FORWARD_PROTOCOL_UDP,
    forward_refusal,
    is_app_kind,
)

# The query parameter a token page takes its token in.
APP_TOKEN_PARAMETER = "tkn"
# The platform whose browser resolves no ``.localhost`` name.
APP_NO_LOCALHOST_NAMES_OS = "darwin"
# The schemes a browser opens.
APP_BROWSER_SCHEMES = ("http", "https")
# The host the hub's panel opens on, before the hub's id.
APP_PANEL_HOST_PREFIX = "panel-"
APP_LOCALHOST_SUFFIX = ".localhost"


def entry_protocol(entry: dict) -> str:
    """The protocol an entry is forwarded on.

    Args:
        entry: The entry.

    Returns:
        ``udp`` for a ``port`` entry whose payload says so, ``tcp``
        otherwise.
    """
    payload = entry.get("payload") or {}
    if entry.get("type") == "port" and payload.get("protocol") == FORWARD_PROTOCOL_UDP:
        return FORWARD_PROTOCOL_UDP
    return FORWARD_PROTOCOL_TCP


def browser_host(local_name: str, os_name: str) -> str:
    """The host a forwarded page opens on in the browser.

    Args:
        local_name: The app's local name.
        os_name: The machine's system, as the platform names it.

    Returns:
        The local name; ``127.0.0.1`` on macOS, or when it names none.
    """
    if os_name == APP_NO_LOCALHOST_NAMES_OS or not local_name:
        return FORWARD_BIND_HOST
    return local_name


def local_url(url: str, host: str, port: int, token: str) -> str:
    """The address a forwarded page opens on.

    Args:
        url: The entry's own address, whose scheme, path and query are kept.
        host: The host it opens on.
        port: The loopback port the forward listens on.
        token: The entry's token; empty for an entry without one.

    Returns:
        ``<scheme>://<host>:<port><path>``, with ``tkn=<token>`` added to
        the query for a token.
    """
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if token:
        query.append((APP_TOKEN_PARAMETER, token))
    return urllib.parse.urlunsplit(
        (
            parts.scheme or "http",
            f"{host}:{port}",
            parts.path or "/",
            urllib.parse.urlencode(query),
            "",
        )
    )


def panel_url(hub_id: str, port: int, token: str, os_name: str) -> str:
    """The address the hub's panel opens on, signed in.

    Args:
        hub_id: The hub's id, which names the panel's own host.
        port: The loopback port the panel's forward listens on.
        token: The sign-in token.
        os_name: The machine's system, as the platform names it.

    Returns:
        ``http://panel-<hub-id>.localhost:<port>/?tkn=<token>``; on macOS
        the host is ``127.0.0.1``.
    """
    host = browser_host(APP_PANEL_HOST_PREFIX + hub_id + APP_LOCALHOST_SUFFIX, os_name)
    return local_url("http://panel/", host, port, token)


def app_entries(app: dict, entries: list) -> list:
    """One app's entries the client forwards, in the hub's order.

    Args:
        app: The app, stamped with its ``hub_id``.
        entries: The merged service list.

    Returns:
        Its ``web``, ``port`` and ``ssh`` entries.
    """
    return [
        entry
        for entry in entries
        if entry.get("hub_id") == app.get("hub_id")
        and entry.get("app_id") == app.get("id")
        and is_app_kind(str(entry.get("type", "")))
    ]


def _nobody(*_args) -> None:
    """Nobody listening."""


class AppServiceHandler:
    """Uses and stops an app: its forwards, and the browser at its first page."""

    def __init__(self, *, platform, forwards, open_service=None, log=print):
        """
        Args:
            platform: The machine's platform, behind the contract.
            forwards: The
                :class:`~neutrino_client.services.forward.ForwardListenerRegistry`
                the forwards live in.
            open_service: ``open_service(hub_id, entry_id) -> dict`` takes one
                entry's material from the hub; None where no page takes a
                token.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._forwards = forwards
        self._open_service = open_service
        self._log = log

    def use(self, *, app: dict, entries: list) -> dict:
        """Forward every entry of an app.

        Args:
            app: The app, stamped with its ``hub_id``.
            entries: The merged service list.

        Returns:
            Empty on success; the first refusal otherwise, ``port_taken
            {port}`` among them, the forwards that started staying up.
        """
        hub_id = str(app.get("hub_id", ""))
        failure: dict = {}
        for entry in app_entries(app, entries):
            key = service_key(hub_id, str(entry.get("id", "")))
            if not self._forwards.ports.app_port(key, _number(entry.get("local_port"))):
                continue
            try:
                self._forwards.ensure(
                    hub_id=hub_id,
                    entry_id=str(entry.get("id", "")),
                    kind=str(entry.get("type", "")),
                    own_port=_number(entry.get("local_port")),
                    protocol=entry_protocol(entry),
                )
            except OSError as error:
                failure = failure or forward_refusal(error)
        return failure

    def open_page(self, *, app: dict, entries: list) -> dict:
        """Open the browser at an app's first page, through its forward.

        Args:
            app: The app, stamped with its ``hub_id``.
            entries: The merged service list.

        Returns:
            Empty once the browser was told to open; ``app_no_page`` for an
            app with no ``http`` or ``https`` entry, ``app_not_in_use`` while
            that entry has no forward, or the token's refusal.
        """
        page = self.page_entry(app=app, entries=entries)
        if page is None:
            return {"code": "app_no_page", "params": {}}
        port = self._forwards.port_of(
            str(app.get("hub_id", "")), str(page.get("id", ""))
        )
        if not port:
            return {"code": "app_not_in_use", "params": {}}
        return self._open_page(app, page, port)

    def page_entry(self, *, app: dict, entries: list) -> "dict | None":
        """An app's first ``http`` or ``https`` entry, in the order the hub lists them.

        Args:
            app: The app, stamped with its ``hub_id``.
            entries: The merged service list.

        Returns:
            The entry, or None for an app with none.
        """
        return next(
            (entry for entry in app_entries(app, entries) if _is_page(entry)), None
        )

    def stop(self, *, app: dict, entries: list) -> int:
        """End every forward of an app.

        Args:
            app: The app, stamped with its ``hub_id``.
            entries: The merged service list.

        Returns:
            How many forwards ended.
        """
        hub_id = str(app.get("hub_id", ""))
        ended = 0
        for entry in app_entries(app, entries):
            if self._forwards.stop(hub_id, str(entry.get("id", ""))):
                ended += 1
        return ended

    def is_in_use(self, *, app: dict, entries: list) -> bool:
        """Whether some forward of an app listens.

        Args:
            app: The app, stamped with its ``hub_id``.
            entries: The merged service list.

        Returns:
            True from the first forward Use made until Stop.
        """
        forwards = self._forwards.forwards()
        hub_id = str(app.get("hub_id", ""))
        return any(
            service_key(hub_id, str(entry.get("id", ""))) in forwards
            for entry in app_entries(app, entries)
        )

    def is_usable(self, *, app: dict, entries: list) -> bool:
        """Whether some entry of an app is not unhealthy.

        Args:
            app: The app, stamped with its ``hub_id``.
            entries: The merged service list.

        Returns:
            True when one entry's health is not ``false``.
        """
        return any(not is_unhealthy(entry) for entry in app_entries(app, entries))

    def _open_page(self, app: dict, entry: dict, port: int) -> dict:
        """Open the browser at one page entry's forward, with its token when it takes one."""
        payload = entry.get("payload") or {}
        token = ""
        if payload.get("is_token_required") is True:
            if self._open_service is None:
                return {"code": "web_token_missing", "params": {}}
            try:
                material = self._open_service(
                    str(app.get("hub_id", "")), str(entry.get("id", ""))
                )
            except Exception as error:  # noqa: BLE001 - a refusal, never a crash
                return channel_refusal(error)
            token = str((material or {}).get("token", "") or "")
            if not token:
                return {"code": "web_token_missing", "params": {}}
        host = browser_host(str(app.get("local_name", "")), self._platform.os_name)
        self._platform.open_url(
            local_url(str(payload.get("url", "")), host, port, token)
        )
        token = ""
        return {}


def _is_page(entry: dict) -> bool:
    """Whether an entry is a page a browser opens."""
    if entry.get("type") != "web":
        return False
    url = str((entry.get("payload") or {}).get("url", "") or "")
    return urllib.parse.urlsplit(url).scheme in APP_BROWSER_SCHEMES


def _number(value) -> int:
    """A port as the hub sent it, 0 for anything else."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value
