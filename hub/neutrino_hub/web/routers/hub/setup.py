"""The first run's questions and the steps that answer them, served by the
setup wizard before the panel starts.

Every route is behind the one-time token the terminal printed: this serves
before there is a password to ask for, so the token is the whole of the
access control and whoever reads the terminal is the only one who has it.
"""

import secrets

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.requests import Request

from neutrino_hub.modules.xray.node_config import parse_share_link


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
        """Whether this request carries the token the terminal printed."""
        given = request.query_params.get("token", "")
        return secrets.compare_digest(given, session.token)

    @router.get("/context")
    def read_context(request: Request):
        if not _guard(request):
            return _denied()
        return session.context()

    @router.get("/state")
    def read_state(request: Request):
        if not _guard(request):
            return _denied()
        return session.state()

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
        session.answer(document)
        return JSONResponse(status_code=202, content=session.state())

    return router


def _denied() -> JSONResponse:
    """The answer to a request with no token, or the wrong one."""
    return JSONResponse(status_code=403, content={"detail": "setup token required"})
