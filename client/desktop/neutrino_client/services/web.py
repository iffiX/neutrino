"""The web service type: a published page the person opens through a forward.

Every web entry opens through a forward of the local port table: the
entry's address is carried as ``connect`` streams through the hub from the
loopback port the table gives it, and the browser opens the forward on the
entry's own ``.localhost`` name, so each instance keeps its own cookie. An
entry whose payload says ``is_token_required`` takes a fresh token from the
``service`` stream on every open and opens with it in the address. The
forwards are runtime state and end with the client.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import re
import urllib.parse

from neutrino_client.services.base import (
    ServiceTypeHandler,
    channel_refusal,
    find_entry,
)
from neutrino_client.services.forward import FORWARD_BIND_HOST, forward_refusal

# The query parameter a token page takes its token in.
WEB_TOKEN_PARAMETER = "tkn"
# The characters a slug keeps; every other one becomes a hyphen.
WEB_SLUG_OUTSIDE = re.compile(r"[^A-Za-z0-9-]")
# The platform whose browser resolves no ``.localhost`` name.
WEB_NO_LOCALHOST_NAMES_OS = "darwin"
# The port a url without one answers on, by its scheme.
WEB_DEFAULT_PORTS = {"http": 80, "https": 443}


def slug(name: str) -> str:
    """A name with every character outside letters, digits and hyphens a hyphen.

    Args:
        name: An entry's or a hub's id.

    Returns:
        The slug.
    """
    return WEB_SLUG_OUTSIDE.sub("-", name)


def loopback_host(name: str, os_name: str) -> str:
    """The host a forward opens on in the browser.

    Args:
        name: The forward's own name, before the slug rule.
        os_name: The machine's system, as the platform names it.

    Returns:
        ``<slug>.localhost``; ``127.0.0.1`` on macOS.
    """
    if os_name == WEB_NO_LOCALHOST_NAMES_OS:
        return FORWARD_BIND_HOST
    return slug(name) + ".localhost"


def local_url(url: str, entry_id: str, port: int, token: str, os_name: str) -> str:
    """The address a forwarded page opens on.

    Args:
        url: The entry's own address, whose scheme, path and query are kept.
        entry_id: The entry's id, which names the page's own host.
        port: The loopback port the forward listens on.
        token: The entry's token; empty for an entry without one.
        os_name: The machine's system, as the platform names it.

    Returns:
        ``<scheme>://<slug>.localhost:<port><path>``, with ``tkn=<token>``
        added to the query for a token; on macOS the host is ``127.0.0.1``.
    """
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if token:
        query.append((WEB_TOKEN_PARAMETER, token))
    return urllib.parse.urlunsplit(
        (
            parts.scheme or "http",
            f"{loopback_host(entry_id, os_name)}:{port}",
            parts.path or "/",
            urllib.parse.urlencode(query),
            "",
        )
    )


def url_port(url: str) -> int:
    """The port an entry's address answers on.

    Args:
        url: The entry's address.

    Returns:
        The url's own port, else 80 or 443 by its scheme, else 0.

    Raises:
        ValueError: When the url names a port that is not a number.
    """
    parts = urllib.parse.urlsplit(url)
    return parts.port or WEB_DEFAULT_PORTS.get(parts.scheme, 0)


class WebServiceHandler(ServiceTypeHandler):
    """Opens a published page in the person's browser, through its forward."""

    service_type = "web"

    def __init__(self, *, platform, forwards, open_service=None, log=print):
        """
        Args:
            platform: The machine's platform, behind the contract.
            forwards: The
                :class:`~neutrino_client.services.forward.ForwardListenerRegistry`
                the forwards live in.
            open_service: Callable ``(hub_id, entry_id) -> dict`` opening
                the ``service`` stream for one entry and returning its
                material; None where no entry takes a token.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._forwards = forwards
        self._open_service = open_service
        self._log = log

    def act(self, *, entries: list, body: dict):
        """Open one published page, or end its forward.

        Args:
            entries: The merged service list.
            body: ``{"hub_id", "id", "is_enabled"}``; ``is_enabled`` false
                ends the entry's forward, and is optional otherwise.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        hub_id = str(body.get("hub_id", ""))
        entry_id = str(body.get("id", ""))
        entry = find_entry(entries, self.service_type, hub_id, entry_id)
        if entry is None:
            return {"code": "unknown_request", "params": {}}
        if body.get("is_enabled") is False:
            return self.stop(hub_id=hub_id, entry_id=entry_id)
        payload = entry.get("payload") or {}
        url = str(payload.get("url", ""))
        try:
            own_port = url_port(url)
        except ValueError:
            return {"code": "unknown_request", "params": {}}
        if not url or not own_port:
            return {"code": "unknown_request", "params": {}}
        try:
            port = self._forwards.ensure(
                hub_id=hub_id,
                entry_id=entry_id,
                own_port=own_port,
                kind=self.service_type,
            )
        except OSError as error:
            return forward_refusal(error)
        token = ""
        if payload.get("is_token_required") is True:
            if self._open_service is None:
                return {"code": "unknown_request", "params": {}}
            try:
                material = self._open_service(hub_id, entry_id)
            except Exception as error:  # noqa: BLE001 - a refusal, never a crash
                return channel_refusal(error)
            token = str((material or {}).get("token", "") or "")
            if not token:
                return {"code": "web_token_missing", "params": {}}
        self._platform.open_url(
            local_url(url, entry_id, port, token, self._platform.os_name)
        )
        return {}

    def stop(self, *, hub_id: str, entry_id: str) -> dict:
        """End one entry's forward.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry whose forward to end.

        Returns:
            Empty; ending what is not running is nothing.
        """
        self._forwards.stop(hub_id, entry_id)
        return {}
