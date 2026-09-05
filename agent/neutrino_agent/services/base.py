"""What a service type handler is.

The hub publishes one typed service list; every entry is
``{"id", "type", "title", "payload", "is_healthy", "source", "description"}``
and the four types are closed until a fifth earns its place. One handler per
type lives in this package, dispatched by ``type`` — a fifth type is one new
file here plus a section on the page.

Every refusal a handler returns is ``{"code", "params"}``; each surface does
its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations


def find_entry(entries: list, service_type: str, entry_id: str) -> "dict | None":
    """One typed entry by id, or None.

    Args:
        entries: The catalog's service list.
        service_type: The type the entry must carry.
        entry_id: The entry's id.

    Returns:
        The entry, or None when the list holds no such entry of that type.
    """
    for entry in entries or []:
        if (
            isinstance(entry, dict)
            and entry.get("type") == service_type
            and entry.get("id") == entry_id
        ):
            return entry
    return None


class ServiceTypeHandler:
    """One service type's behavior on this machine."""

    service_type = ""

    def act(self, *, entries: list, account: str, is_privileged: bool, body: dict):
        """Perform one page action on this type.

        Args:
            entries: The catalog's service list.
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
            body: The action's own fields.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        return {"code": "unknown_request", "params": {}}

    def state(self) -> dict:
        """This type's machine state for the page payload.

        Returns:
            Keys merged into the state payload; empty when the type keeps
            none.
        """
        return {}

    def start(self) -> None:
        """Begin any background reconcile this type keeps running."""
