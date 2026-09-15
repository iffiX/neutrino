"""What a service type handler is.

Every hub publishes one typed service list; every entry is
``{"id", "type", "title", "payload", "is_healthy", "source", "description"}``
and the types are closed. The resident merges the lists and stamps each
entry with the ``hub_id`` it came from, so an entry is addressed by hub and
id together: the service key. One handler per type lives in this package,
dispatched by ``type``.

Every refusal a handler returns is ``{"code", "params"}``; each surface does
its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)

SERVICE_KEY_SEPARATOR = "/"


def channel_refusal(error: Exception) -> dict:
    """The typed refusal a handler answers when the hub did not.

    Args:
        error: What opening a stream to the hub raised.

    Returns:
        ``{"code", "params"}``: the hub's own code when it closed the stream
        with one, ``hub_untrusted``, ``hub_unreachable`` with the detail,
        or ``hub_refused`` naming the exception's kind for anything else.
    """
    if isinstance(error, GatewayRefusedDetail):
        return {"code": error.code, "params": dict(error.params)}
    if isinstance(error, GatewayUntrusted):
        return {"code": "hub_untrusted", "params": {}}
    if isinstance(error, GatewayUnreachable):
        return {"code": "hub_unreachable", "params": {"detail": str(error)}}
    return {"code": "hub_refused", "params": {"detail": type(error).__name__}}


def service_key(hub_id: str, entry_id: str) -> str:
    """The one key an entry is held under, across every hub.

    Args:
        hub_id: The hub the entry came from.
        entry_id: The entry's id in that hub's list.

    Returns:
        ``"<hub_id>/<entry_id>"``.
    """
    return f"{hub_id}{SERVICE_KEY_SEPARATOR}{entry_id}"


def hub_of_key(key: str) -> str:
    """The hub a service key names.

    Args:
        key: A key from :func:`service_key`.

    Returns:
        The hub id before the separator.
    """
    return key.partition(SERVICE_KEY_SEPARATOR)[0]


def find_entry(
    entries: list, service_type: str, hub_id: str, entry_id: str
) -> "dict | None":
    """One typed entry of one hub by id, or None.

    Args:
        entries: The merged service list, each entry stamped with ``hub_id``.
        service_type: The type the entry must carry.
        hub_id: The hub the entry must come from.
        entry_id: The entry's id.

    Returns:
        The entry, or None when the list holds no such entry of that type
        from that hub.
    """
    for entry in entries or []:
        if (
            isinstance(entry, dict)
            and entry.get("type") == service_type
            and entry.get("hub_id") == hub_id
            and entry.get("id") == entry_id
        ):
            return entry
    return None


class ServiceTypeHandler:
    """One service type's behavior on this machine."""

    service_type = ""

    def act(self, *, entries: list, body: dict):
        """Perform one page action on this type.

        Args:
            entries: The merged service list.
            body: The action's own fields; ``hub_id`` names the hub.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        return {"code": "unknown_request", "params": {}}

    def state(self) -> dict:
        """This type's state for the page payload.

        Returns:
            Keys merged into the state payload; empty when the type keeps
            none.
        """
        return {}

    def start(self) -> None:
        """Begin any background reconcile this type keeps running."""

    def release(self) -> None:
        """Undo everything this type holds on the machine. Idempotent."""

    def release_hub(self, hub_id: str) -> None:
        """Undo what this type holds for one hub. Idempotent.

        Args:
            hub_id: The hub whose entries are let go of.
        """
