"""A client's sign-in to the panel, and the end of the sessions it opened.

A client that holds the ``panel`` permission asks the hub for a token on a
``service {is_panel: true}`` stream and opens its panel forward with
``?tkn=<token>``. The forward reaches the panel's HTTP port from loopback, so
a request there that carries ``tkn`` and comes from loopback is a sign-in: a
token that spends, for a client still switched on and still holding
``panel``, opens a session marked with the client's id. Every request that
carries ``tkn`` is answered 302 to the same address without it, whatever the
token was worth, and a ``tkn`` from any other peer is never looked up.
"""

import logging

from neutrino_hub.modules.clients.constants import CLIENT_PERMISSION_PANEL
from neutrino_hub.modules.clients.permissions import permitted_kinds
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web.constants import WEB_PANEL_TOKEN_PARAM
from neutrino_hub.web.dependencies import session_cookie
from neutrino_hub.web.https_redirect import SECURE_SCHEMES, is_loopback_peer

LOGGER = logging.getLogger(__name__)

SIGN_IN_REDIRECT_STATUS = 302
# Why a client's panel session ends, as the hub's log says it.
SESSION_END_DISABLED = "disabled"
SESSION_END_REMOVED = "removed"
SESSION_END_LEFT = "left the hub"
SESSION_END_PERMISSION = "permission taken"


class PanelSignInMiddleware:
    """Turns a loopback request carrying ``tkn`` into a session, and drops
    ``tkn`` from every request that carries it."""

    def __init__(self, app, *, runtime):
        """
        Args:
            app: The wrapped ASGI application.
            runtime: The shared runtime, which holds the tokens, the sessions
                and the settings that name the session cookie.
        """
        self._app = app
        self._runtime = runtime

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        query = scope.get("query_string", b"").decode("latin-1")
        token, remaining = split_token(query)
        if token is None:
            await self._app(scope, receive, send)
            return
        raw_path = scope.get("raw_path") or scope.get("path", "/").encode("utf-8")
        location = raw_path.decode("latin-1") or "/"
        if remaining:
            location = f"{location}?{remaining}"
        headers = [(b"location", location.encode("latin-1"))]
        is_secure = scope.get("scheme") in SECURE_SCHEMES
        if not is_secure and is_loopback_peer(scope):
            session = self._sign_in(token)
            if session:
                headers.append((b"set-cookie", self._cookie(session).encode("latin-1")))
        headers.append((b"content-length", b"0"))
        await send(
            {
                "type": "http.response.start",
                "status": SIGN_IN_REDIRECT_STATUS,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": b""})

    def _sign_in(self, token: str) -> str:
        """The session a token opens, empty when it opens none."""
        client_id, reason = self._runtime.panel_tokens.spend(token)
        client = ClientRegistry().get(client_id) if client_id else None
        if not reason:
            if client is None:
                reason = "client unknown"
            elif not may_open_panel(client):
                reason = "client may not open the panel"
        if reason:
            LOGGER.info("panel: a sign-in token opened nothing (%s)", reason)
            return ""
        LOGGER.info("panel: signed in by client %s", client.name)
        return self._runtime.sessions.open_for_client(client.id)

    def _cookie(self, session: str) -> str:
        """The header that hands the browser its session."""
        max_age = int(self._runtime.settings.get("session_ttl_hours", 168)) * 3600
        return (
            f"{session_cookie(self._runtime)}={session}; Max-Age={max_age}; "
            "Path=/; HttpOnly; SameSite=lax"
        )


def split_token(query: str) -> tuple:
    """The ``tkn`` a query carries, and the query without it.

    Args:
        query: The raw query string, without its ``?``.

    Returns:
        ``(token, remaining)``: the first ``tkn`` value, None when there is
        none, and every other parameter as it arrived, in its order.
    """
    token = None
    kept = []
    for part in query.split("&") if query else []:
        name, _, value = part.partition("=")
        if name == WEB_PANEL_TOKEN_PARAM:
            if token is None:
                token = value
            continue
        kept.append(part)
    return token, "&".join(kept)


def may_open_panel(client) -> bool:
    """Whether a client may sign in to the panel now.

    Args:
        client: The client's record.

    Returns:
        True while it is switched on and its permission, its own or the
        default it follows, holds ``panel``.
    """
    if client.is_disabled:
        return False
    return CLIENT_PERMISSION_PANEL in permitted_kinds(ClientRegistry(), client)


def end_client_panel_sessions(runtime, *, why: str) -> list:
    """End every panel session whose client may no longer open the panel.

    Called after a client is switched off, removed, leaves, or a permission
    changes; a client that still may open the panel keeps its sessions.

    Args:
        runtime: The shared runtime, which holds the sessions.
        why: What the hub's log says ended them.

    Returns:
        The ids of the clients whose sessions ended.
    """
    registry = ClientRegistry()
    ended = []
    for token, client_id in runtime.sessions.client_sessions():
        client = registry.get(client_id)
        if client is not None and may_open_panel(client):
            continue
        runtime.sessions.logout(token)
        name = client.name if client is not None else client_id
        LOGGER.info("panel: session of client %s ended (%s)", name, why)
        ended.append(client_id)
    return ended
