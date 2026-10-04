"""The first run's questions and the steps that answer them, served by the
setup wizard before the panel starts.

Every route is behind the one-time token: this serves before there is a
password to ask for, so the token is the whole of the access control, and it
is readable by root alone. Answers that arrive while another process runs
the steps are refused with ``setup_in_progress``.
"""

import secrets
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.requests import Request

from neutrino_hub.modules.router.constants import ROUTER_MODE_SERVER
from neutrino_hub.modules.xray.node_config import parse_share_link
from neutrino_hub.platforms.constants import PLATFORM_OS_LINUX
from neutrino_hub.platforms.detect import hub_os
from neutrino_hub.web.constants import WEB_CODE_SETUP_IN_PROGRESS


def setup_router(session) -> APIRouter:
    """The routes the browser wizard talks to, bound to one setup run.

    Args:
        session: The run this serves, a ``WebSetupSession``: its token, the
            facts the questions are asked against, and where the steps have
            got to.

    Returns:
        The router.
    """
    router = APIRouter(prefix="/api/hub/setup", tags=["setup"])

    def _guard(request: Request) -> bool:
        """Whether this request carries the setup token."""
        given = request.query_params.get("token", "")
        return secrets.compare_digest(given, session.token)

    @router.get("/context")
    def read_context(request: Request):
        if not _guard(request):
            return _denied()
        return _context_for_system(session.context())

    @router.get("/state")
    def read_state(request: Request):
        if not _guard(request):
            return _denied()
        return _state_for_origin(
            session.state(), request.url.scheme, request.url.netloc
        )

    @router.post("/link/create")
    async def read_link(request: Request):
        """What the hub makes of one share link.

        The browser has no parser of its own and must not grow one: a second
        reading of the same link is a second thing to keep in step. It asks
        instead, and gets back either the node's name or the reason there
        isn't one.
        """
        if not _guard(request):
            return _denied()
        body = await request.json()
        try:
            node = parse_share_link(str(body.get("link", "")))
        except (ValueError, TypeError) as error:
            # A link somebody mistyped is an answer to give back, not a fault.
            return {"name": "", "detail": str(error)}
        return {"name": node.name or node.id, "detail": ""}

    @router.post("/answer/set")
    async def write_answers(request: Request):
        if not _guard(request):
            return _denied()
        document = await request.json()
        if not isinstance(document, dict):
            return JSONResponse(
                status_code=400, content={"detail": "answers must be an object"}
            )
        if not session.answer(document):
            return JSONResponse(
                status_code=409,
                content={"detail": {"code": WEB_CODE_SETUP_IN_PROGRESS, "params": {}}},
            )
        return JSONResponse(status_code=202, content=session.state())

    return router


def _context_for_system(context: dict) -> dict:
    """The wizard's facts, with the system the hub runs on.

    Args:
        context: What the terminal gathered.

    Returns:
        The same facts with ``hub_os`` added, and ``modes`` cut to ``server``
        alone outside Linux.
    """
    system = hub_os()
    served = {**context, "hub_os": system}
    if system != PLATFORM_OS_LINUX:
        served["modes"] = [
            mode
            for mode in context.get("modes", [])
            if mode.get("key") == ROUTER_MODE_SERVER
        ]
    return served


def _state_for_origin(state: dict, scheme: str, netloc: str) -> dict:
    """The run's state, with every address on the origin the browser used.

    Args:
        state: What the session reports.
        scheme: The scheme of the request's own origin.
        netloc: The host and port of the request's own origin, as the
            browser sent them; empty keeps the addresses as they are.

    Returns:
        The same state, ``panel_url`` and the authority's ``url`` on the
        browser's origin where they share its scheme, and on its host with
        their own port where they do not.
    """
    if not netloc:
        return state
    served = {
        **state,
        "panel_url": _on_origin(state.get("panel_url", ""), scheme, netloc),
    }
    authority = state.get("authority")
    if authority:
        served["authority"] = {
            **authority,
            "url": _on_origin(authority.get("url", ""), scheme, netloc),
        }
    return served


def _on_origin(url: str, scheme: str, netloc: str) -> str:
    """``url`` moved onto the browser's origin, its path kept.

    A url of the browser's scheme takes the browser's host and port whole;
    one of another scheme takes the host and keeps its own port.
    """
    if not url:
        return url
    parts = urlsplit(url)
    if parts.scheme == scheme:
        return urlunsplit(parts._replace(netloc=netloc))
    host = urlsplit(f"//{netloc}").hostname or ""
    name = f"[{host}]" if ":" in host else host
    moved = name if parts.port is None else f"{name}:{parts.port}"
    return urlunsplit(parts._replace(netloc=moved))


def _denied() -> JSONResponse:
    """The answer to a request with no token, or the wrong one."""
    return JSONResponse(status_code=403, content={"detail": "setup token required"})
