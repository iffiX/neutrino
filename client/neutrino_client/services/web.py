"""The web service type: a published link the person opens.

There is no state to keep; the rows render straight from the typed entries,
and the platform's browser is what opens the payload's url.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.services.base import ServiceTypeHandler, find_entry


class WebServiceHandler(ServiceTypeHandler):
    """Opens a published link in the person's browser."""

    service_type = "web"

    def __init__(self, *, platform):
        """
        Args:
            platform: The machine's platform, behind the contract.
        """
        self._platform = platform

    def act(self, *, entries: list, body: dict):
        """Open one published link.

        Args:
            entries: The catalog's service list.
            body: ``{"id"}``.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        entry = find_entry(entries, self.service_type, str(body.get("id", "")))
        if entry is None:
            return {"code": "unknown_request", "params": {}}
        url = str((entry.get("payload") or {}).get("url", ""))
        if not url:
            return {"code": "unknown_request", "params": {}}
        self._platform.open_url(url)
        return {}
