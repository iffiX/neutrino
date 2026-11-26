"""The forwarder in front of ComfyUI's page: its rule for each request and its way to the page.

ComfyUI has no login of its own, so the forwarder's own login cookie admits
a browser. A ``?tkn=`` that verifies sets the cookie, named by the entry's
``cookie_name``, and redirects to the same path without the token; a token
that does not verify answers 401. A request with a good cookie is passed on
unchanged, its ``Host`` and ``Origin`` as the browser sent them, a WebSocket
included. Anything else answers 401. The cookie is ``base64url(expiry ||
HMAC-SHA256(key, expiry))`` with the key derived from the module's secret,
HttpOnly and SameSite=Lax, and lasts seven days.

Not pure: opens a connection to ComfyUI.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import socket
import time
import urllib.parse

from neutrino_agent.constants import (
    AGENT_FORWARD_TOKEN_PARAMETER,
    AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
    AGENT_REPORT_INTERVAL_S,
)
from neutrino_agent.modules.comfyui.config import cookie_key
from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_FORWARDER_FIELDS,
    COMFYUI_HOST,
    COMFYUI_LOGIN_LIFETIME_S,
    COMFYUI_NAME,
)
from neutrino_agent.modules.shared.http_forward import (
    RELAY,
    ForwardDecision,
    InstanceForwarder,
    answered,
    is_login_valid,
    mint_login,
    refused,
)


def without_token(path: str, query: dict) -> str:
    """The address a token's redirect goes to: the same path and query, the token left out. Pure.

    Args:
        path: The request's path.
        query: Its query, name to the values in their order.

    Returns:
        The path, with what is left of the query after a ``?``.
    """
    kept = [
        (name, value)
        for name, values in query.items()
        if name != AGENT_FORWARD_TOKEN_PARAMETER
        for value in values
    ]
    if not kept:
        return path or "/"
    return f"{path or '/'}?{urllib.parse.urlencode(kept)}"


def page_forwarder(*, record: dict, hooks, log) -> InstanceForwarder:
    """The page's forwarder, trying a port another program holds every report interval.

    Args:
        record: The module's record.
        hooks: The forwarder's rule, :class:`ComfyuiForwarderHooks`.
        log: Called with each progress line.

    Returns:
        The forwarder, not started.
    """
    return InstanceForwarder(
        name=COMFYUI_NAME,
        record={**record, "account": ""},
        hooks=hooks,
        log=log,
        retry_s=AGENT_REPORT_INTERVAL_S,
    )


class ComfyuiForwarderHooks:
    """What the forwarder asks of ComfyUI's module: the rule for a request and the way to the page."""

    # What the forwarder reads of the record.
    secret_field = "secret"
    forwarder_fields = COMFYUI_FORWARDER_FIELDS

    def __init__(self, *, clock=time.time):
        """
        Args:
            clock: The time a login cookie's expiry is counted by.
        """
        self._clock = clock

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
            A redirect to the same address without the token, setting the
            login cookie, for a token that verifies; 401 for a token that
            does not and for a request with neither a token nor a good
            cookie; the relay for a request with a good cookie.
        """
        secret = str(record.get("secret", "") or "")
        name = str(record.get("cookie_name", "") or "")
        if not secret or not name:
            return refused()
        key = cookie_key(secret)
        if request.token:
            if not request.take_token():
                return refused()
            expiry = int(self._clock()) + COMFYUI_LOGIN_LIFETIME_S
            cookie = (
                f"{name}={mint_login(key, expiry)}; Path=/; "
                f"HttpOnly; SameSite=Lax; Max-Age={COMFYUI_LOGIN_LIFETIME_S}"
            )
            return answered(
                302,
                headers=(
                    ("Location", without_token(request.path, request.query)),
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
        return RELAY

    def connect(self, record: dict) -> socket.socket:
        """A connection to ComfyUI at its own port.

        Args:
            record: The module's record.

        Returns:
            The connected socket.

        Raises:
            OSError: When ComfyUI does not answer.
        """
        return socket.create_connection(
            (COMFYUI_HOST, int(record.get("upstream_port", 0) or 0)),
            timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
        )
