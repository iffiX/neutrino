"""The web service type: a published link the person opens.

The rows render straight from the typed entries, and the platform's browser
is what opens the payload's url. An entry whose payload says
``is_local_only`` opens only from localhost: its address is forwarded to
``127.0.0.1`` first, its token comes down the ``service`` stream, and the
browser opens the forward with the token. The forwards are runtime state
and end with the client.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import threading
import urllib.parse

from neutrino_client.services.base import (
    ServiceTypeHandler,
    channel_refusal,
    find_entry,
    hub_of_key,
    service_key,
)
from neutrino_client.services.port import FORWARD_BIND_HOST, _ForwardRelay

# The query parameter a local-only page takes its token in.
WEB_TOKEN_PARAMETER = "tkn"


class WebServiceHandler(ServiceTypeHandler):
    """Opens a published link in the person's browser, through a forward when it must."""

    service_type = "web"

    def __init__(self, *, platform, open_service=None, log=print):
        """
        Args:
            platform: The machine's platform, behind the contract.
            open_service: Callable ``(hub_id, entry_id) -> dict`` opening
                the ``service`` stream for one entry and returning its
                material; None where no entry is local-only.
            log: Callable used for progress messages.
        """
        self._platform = platform
        self._open_service = open_service
        self._log = log
        self._lock = threading.Lock()
        # The forwards of the local-only entries, by service key.
        self._relays: dict = {}

    def act(self, *, entries: list, body: dict):
        """Open one published link.

        Args:
            entries: The merged service list.
            body: ``{"hub_id", "id"}``.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        entry = find_entry(
            entries,
            self.service_type,
            str(body.get("hub_id", "")),
            str(body.get("id", "")),
        )
        if entry is None:
            return {"code": "unknown_request", "params": {}}
        payload = entry.get("payload") or {}
        url = str(payload.get("url", ""))
        if not url:
            return {"code": "unknown_request", "params": {}}
        if payload.get("is_local_only") is True:
            return self._open_local(entry, url)
        self._platform.open_url(url)
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

    def _open_local(self, entry: dict, url: str) -> dict:
        """Forward a local-only entry to the loopback, take its token, open it."""
        parts = urllib.parse.urlsplit(url)
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            return {"code": "unknown_request", "params": {}}
        if not parts.hostname or self._open_service is None:
            return {"code": "unknown_request", "params": {}}
        hub_id = str(entry.get("hub_id", ""))
        entry_id = str(entry.get("id", ""))
        key = service_key(hub_id, entry_id)
        with self._lock:
            relay = self._relays.get(key)
            if relay is None or not relay.is_active:
                relay = _ForwardRelay(host=parts.hostname, port=port, local_port=port)
                try:
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
        try:
            material = self._open_service(hub_id, entry_id)
        except Exception as error:  # noqa: BLE001 - a refusal, never a crash
            return channel_refusal(error)
        token = str((material or {}).get("token", "") or "")
        if not token:
            return {"code": "web_token_missing", "params": {}}
        query = urllib.parse.urlencode({WEB_TOKEN_PARAMETER: token})
        self._platform.open_url(
            f"http://{FORWARD_BIND_HOST}:{relay.local_port}"
            f"{parts.path or '/'}?{query}"
        )
        return {}
