"""The window's channel: the route table, in this same process.

The window lives in the resident, so its requests need no socket: the
bridge hands method, path and body to the route table directly, as this
person.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.control import routes


class InProcessChannel:
    """Answers the page from the route table without a transport."""

    def __init__(self, *, session):
        """
        Args:
            session: The running :class:`~neutrino_client.core.session.ClientSession`.
        """
        self._session = session

    def request(
        self, *, method: str, path: str, body: "dict | None" = None
    ) -> "tuple[int, dict]":
        """One request against the route table.

        Args:
            method: The HTTP method.
            path: The request path.
            body: The JSON body of a POST.

        Returns:
            The status code and the reply object.
        """
        return routes.dispatch(method, path, body, self._session)
