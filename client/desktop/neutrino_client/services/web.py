"""The web service type: a published link the person opens.

The rows render straight from the typed entries, and the platform's browser
is what opens the payload's url. An entry whose payload says
``is_local_only`` opens only from localhost: its token comes down the
``service`` stream, its address is forwarded as bytes to the loopback port
the local port table gives it, and the browser opens the forward on the
entry's own ``.localhost`` name with the token in the address, so each
instance keeps its own cookie. The forwards are runtime state and end with
the client. An entry whose payload says ``is_token_required`` opens at its
own address with a token the ``service`` stream hands for that one open.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import re
import threading
import urllib.parse

from neutrino_client.services.base import (
    ServiceTypeHandler,
    channel_refusal,
    find_entry,
    hub_of_key,
    service_key,
)
from neutrino_client.services.port import (
    FORWARD_BIND_HOST,
    PortLocalTable,
    _ForwardRelay,
)

# The query parameter a local-only page takes its token in.
WEB_TOKEN_PARAMETER = "tkn"
# The characters a slug keeps; every other one becomes a hyphen.
WEB_SLUG_OUTSIDE = re.compile(r"[^A-Za-z0-9-]")
# The platform whose browser resolves no ``.localhost`` name.
WEB_NO_LOCALHOST_NAMES_OS = "darwin"


def token_url(url: str, token: str) -> str:
    """An entry's own address with the token it opens with.

    Args:
        url: The entry's address.
        token: The token the hub handed for this open.

    Returns:
        The address with ``tkn=<token>`` added to its query.
    """
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.append((WEB_TOKEN_PARAMETER, token))
    return urllib.parse.urlunsplit(
        parts._replace(path=parts.path or "/", query=urllib.parse.urlencode(query))
    )


def local_url(entry_id: str, port: int, path: str, token: str, os_name: str) -> str:
    """The address a forwarded local-only page opens on.

    Args:
        entry_id: The entry's id, which names the page's own host.
        port: The loopback port the forward listens on.
        path: The page's path; empty for the root.
        token: The entry's token.
        os_name: The machine's system, as the platform names it.

    Returns:
        ``http://<slug>.localhost:<port><path>?tkn=<token>``, the slug the id
        with every character outside letters, digits and hyphens a hyphen;
        on macOS the host is ``127.0.0.1``.
    """
    if os_name == WEB_NO_LOCALHOST_NAMES_OS:
        host = FORWARD_BIND_HOST
    else:
        host = WEB_SLUG_OUTSIDE.sub("-", entry_id) + ".localhost"
    query = urllib.parse.urlencode({WEB_TOKEN_PARAMETER: token})
    return f"http://{host}:{port}{path or '/'}?{query}"


class WebServiceHandler(ServiceTypeHandler):
    """Opens a published link in the person's browser, through a forward when it must."""

    service_type = "web"

    def __init__(self, *, platform, open_service=None, log=print, ports=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            open_service: Callable ``(hub_id, entry_id) -> dict`` opening
                the ``service`` stream for one entry and returning its
                material; None where no entry is local-only.
            log: Callable used for progress messages.
            ports: The :class:`~neutrino_client.services.port.PortLocalTable`
                the forwards take their port from; None keeps one in memory.
        """
        self._platform = platform
        self._open_service = open_service
        self._log = log
        self._ports = ports if ports is not None else PortLocalTable()
        self._lock = threading.Lock()
        # The forwards of the local-only entries, by service key.
        self._relays: dict = {}

    def act(self, *, entries: list, body: dict):
        """Open one published link, or end a local-only entry's forward.

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
        if not url:
            return {"code": "unknown_request", "params": {}}
        if payload.get("is_token_required") is True:
            return self._open_with_token(entry, url)
        if payload.get("is_local_only") is True:
            return self._open_local(entry, url)
        self._platform.open_url(url)
        return {}

    def state(self) -> dict:
        """The forwards of the local-only entries, for the state payload.

        Returns:
            ``{"web_forwards": {service_key: {"local_port", "is_active"}}}``.
        """
        with self._lock:
            return {
                "web_forwards": {
                    key: {"local_port": relay.local_port, "is_active": relay.is_active}
                    for key, relay in self._relays.items()
                }
            }

    def stop(self, *, hub_id: str, entry_id: str) -> dict:
        """End one local-only entry's forward.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry whose forward to end.

        Returns:
            Empty; ending what is not running is nothing.
        """
        with self._lock:
            relay = self._relays.pop(service_key(hub_id, entry_id), None)
        if relay is not None:
            relay.close()
            self._log(f"stopped forwarding to {relay.host}:{relay.port}")
        return {}

    def release(self) -> int:
        """Close every forward.

        Returns:
            How many forwards were closed.
        """
        with self._lock:
            relays, self._relays = self._relays, {}
        for relay in relays.values():
            relay.close()
        return len(relays)

    def release_hub(self, hub_id: str) -> int:
        """Close the forwards of one hub's entries.

        Args:
            hub_id: The hub whose forwards are closed.

        Returns:
            How many forwards were closed.
        """
        with self._lock:
            keys = [key for key in self._relays if hub_of_key(key) == hub_id]
            relays = [self._relays.pop(key) for key in keys]
        for relay in relays:
            relay.close()
        return len(relays)

    def _open_with_token(self, entry: dict, url: str) -> dict:
        """Take a fresh token for an entry and open its own address with it."""
        if self._open_service is None:
            return {"code": "unknown_request", "params": {}}
        try:
            material = self._open_service(
                str(entry.get("hub_id", "")), str(entry.get("id", ""))
            )
        except Exception as error:  # noqa: BLE001 - a refusal, never a crash
            return channel_refusal(error)
        token = str((material or {}).get("token", "") or "")
        if not token:
            return {"code": "web_token_missing", "params": {}}
        self._platform.open_url(token_url(url, token))
        return {}

    def _open_local(self, entry: dict, url: str) -> dict:
        """Take a local-only entry's token, forward it to the loopback, open it."""
        parts = urllib.parse.urlsplit(url)
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            return {"code": "unknown_request", "params": {}}
        if not parts.hostname or self._open_service is None:
            return {"code": "unknown_request", "params": {}}
        hub_id = str(entry.get("hub_id", ""))
        entry_id = str(entry.get("id", ""))
        try:
            material = self._open_service(hub_id, entry_id)
        except Exception as error:  # noqa: BLE001 - a refusal, never a crash
            return channel_refusal(error)
        token = str((material or {}).get("token", "") or "")
        if not token:
            return {"code": "web_token_missing", "params": {}}
        key = service_key(hub_id, entry_id)
        with self._lock:
            relay = self._relays.get(key)
            if relay is None or not relay.is_active:
                try:
                    relay = _ForwardRelay(
                        host=parts.hostname,
                        port=port,
                        local_port=self._ports.take(key, port),
                    )
                    relay.start()
                except OSError as error:
                    return {
                        "code": "forward_failed",
                        "params": {"detail": str(error)[:200]},
                    }
                self._relays[key] = relay
                self._log(
                    f"forwarding {FORWARD_BIND_HOST}:{relay.local_port} "
                    f"to {parts.hostname}:{port}"
                )
        self._platform.open_url(
            local_url(
                entry_id,
                relay.local_port,
                parts.path,
                token,
                self._platform.os_name,
            )
        )
        return {}
