"""Serving the setup wizard to a browser.

The same questions the terminal asks, on a machine that has no panel yet. It
is deliberately thin: the browser reads the facts the terminal gathered, posts
back the same answers document ``nhub setup --stdin`` takes, and watches the
steps run. Nothing here decides anything — deciding is the wizard's, and
acting is setup's.

The port is the panel's own, because that is the one the firewall opens and
the one whoever set the box up already has in their address bar. It follows
that the panel cannot start while this is serving, so setup starts it last and
this steps aside first.
"""

import secrets
import threading
import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.requests import Request
from starlette.staticfiles import StaticFiles

from neutrino_hub.modules.xray.node_config import parse_share_link
from neutrino_hub.web.constants import (
    WEB_FRONTEND_DIST_DIR,
    WEB_SETUP_STATE_ASKING,
    WEB_SETUP_STATE_DONE,
    WEB_SETUP_STATE_FAILED,
    WEB_SETUP_STATE_REJECTED,
    WEB_SETUP_STATE_RUNNING,
    WEB_SETUP_STEP_FAILED,
    WEB_SETUP_STEP_RUNNING,
    WEB_SETUP_START_POLL_S,
    WEB_SETUP_START_TIMEOUT_S,
    WEB_SETUP_STOP_TIMEOUT_S,
    WEB_SETUP_TOKEN_BYTES,
)


class WebSetupSession:
    """What the browser and the terminal both look at.

    One setup run: the questions to ask, the answers that came back, and how
    far the steps have got. Both sides touch it from their own thread, so
    every read and write takes the lock.
    """

    def __init__(self, *, context: dict):
        """
        Args:
            context: The facts the questions are asked against — this
                machine's ports, the modes they allow, the modules it could
                install. The terminal gathers them; this only serves them.
        """
        self.token = secrets.token_urlsafe(WEB_SETUP_TOKEN_BYTES)
        self._lock = threading.Lock()
        self._context = context
        self._answered = threading.Event()
        self._document: dict = {}
        self._state = WEB_SETUP_STATE_ASKING
        self._steps: list = []
        self._notes: list = []
        self._message = ""
        self._panel_url = ""

    # --- what the browser reads ---

    def context(self) -> dict:
        """The facts the questions are asked against."""
        return self._context

    def state(self) -> dict:
        """Where this run has got to.

        Returns:
            The state name, every step reported so far, and the panel's
            address once there is one.
        """
        with self._lock:
            return {
                "state": self._state,
                "message": self._message,
                "panel_url": self._panel_url,
                "steps": list(self._steps),
                "notes": list(self._notes),
            }

    # --- what the browser writes ---

    def answer(self, document: dict) -> None:
        """Hand the terminal what the browser filled in.

        Args:
            document: The answers document, unchecked. Whether it can be used
                is the wizard's to say, and it says so through
                :meth:`reject`.
        """
        with self._lock:
            self._document = document
            self._state = WEB_SETUP_STATE_RUNNING
        self._answered.set()

    # --- what the terminal reads and writes ---

    def wait(self, timeout_s: float) -> dict:
        """Block until the browser answers.

        Args:
            timeout_s: How long to wait before giving up on this call.

        Returns:
            The posted document, empty when nothing arrived in time.
        """
        if not self._answered.wait(timeout_s):
            return {}
        with self._lock:
            return dict(self._document)

    def reject(self, message: str) -> None:
        """Say the document cannot be used, and ask again.

        Args:
            message: What is wrong with it, in the wizard's words.
        """
        with self._lock:
            self._document = {}
            self._state = WEB_SETUP_STATE_REJECTED
            self._message = message
        self._answered.clear()

    def step(self, description: str, status: str, note: str = "") -> None:
        """Record where the steps have got to.

        A step already listed is updated in place, so the browser sees one
        line move from running to its outcome rather than two lines.

        Args:
            description: The step's name, as the terminal prints it.
            status: One of the ``WEB_SETUP_STEP_`` states.
            note: Short detail, the same one the terminal shows.
        """
        with self._lock:
            for entry in self._steps:
                if entry["description"] == description:
                    entry["status"] = status
                    entry["note"] = note
                    break
            else:
                self._steps.append(
                    {"description": description, "status": status, "note": note}
                )
            if status == WEB_SETUP_STEP_FAILED:
                self._state = WEB_SETUP_STATE_FAILED
                self._message = note

    def note(self, text: str) -> None:
        """Record an aside the terminal printed between steps.

        Args:
            text: The message.
        """
        with self._lock:
            self._notes.append(text)

    def finish(self, *, panel_url: str) -> None:
        """Say the box is set up and where its panel will answer.

        Args:
            panel_url: Where to send the browser once the panel is up.
        """
        with self._lock:
            self._state = WEB_SETUP_STATE_DONE
            self._panel_url = panel_url
            for entry in self._steps:
                if entry["status"] == WEB_SETUP_STEP_RUNNING:
                    entry["status"] = WEB_SETUP_STEP_FAILED


class WebSetupServer:
    """The wizard's server, for as long as there is no panel to be one.

    It holds the panel's port, so it has to let go of it before the panel
    starts: :meth:`stop` is what setup calls once there is nothing left to
    tell the browser.
    """

    def __init__(self, *, session: WebSetupSession, host: str, port: int):
        """
        Args:
            session: The run this serves.
            host: The address to listen on.
            port: The port to ask for — the panel's own, or 0 for whichever
                one is free. :attr:`port` says what was actually taken.
        """
        self.session = session
        self.port = port
        config = uvicorn.Config(
            create_setup_app(session),
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> bool:
        """Begin serving, and say whether the port was there to be had.

        Waits for the socket rather than assuming it: something else already
        listening on the port would otherwise leave the terminal waiting for a
        browser that can never connect, with the reason in a line of uvicorn
        output above it.

        Returns:
            True once it is listening, False when it never got a port.
        """
        self._thread.start()
        deadline = time.monotonic() + WEB_SETUP_START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._server.started:
                self.port = self._bound_port()
                return True
            if not self._thread.is_alive():
                return False
            time.sleep(WEB_SETUP_START_POLL_S)
        return False

    def stop(self) -> None:
        """Stop serving and give the port back."""
        self._server.should_exit = True
        self._thread.join(timeout=WEB_SETUP_STOP_TIMEOUT_S)

    def _bound_port(self) -> int:
        """Which port it is actually on.

        Asking for 0 is how the operating system is asked for whichever port
        is free, and then the only way to know which one that was is to look.

        Returns:
            The port it is listening on, or the one it asked for when the
            socket cannot be read.
        """
        for served in getattr(self._server, "servers", []):
            for held in getattr(served, "sockets", []):
                return int(held.getsockname()[1])
        return self.port

    def _serve(self) -> None:
        """Serve until asked to stop.

        A port it cannot bind makes uvicorn exit the process. In a thread
        that is an unhandled exception and nothing else; what it means here
        is that :meth:`start` says no.
        """
        try:
            self._server.run()
        except SystemExit:
            pass


def create_setup_app(session: WebSetupSession) -> FastAPI:
    """Build the application the browser wizard runs on.

    Every route is behind the one-time token: this serves before there is a
    password to ask for, so the token is the whole of the access control and
    whoever reads the terminal is the only one who has it.

    Args:
        session: The run this serves.

    Returns:
        The configured application.
    """
    app = FastAPI(title="Neutrino Hub setup", docs_url=None, redoc_url=None)

    def _guard(request: Request):
        """Whether this request carries the token the terminal printed."""
        given = request.query_params.get("token", "")
        return secrets.compare_digest(given, session.token)

    @app.get("/api/setup/context")
    def read_context(request: Request):
        if not _guard(request):
            return _denied()
        return session.context()

    @app.get("/api/setup/state")
    def read_state(request: Request):
        if not _guard(request):
            return _denied()
        return session.state()

    @app.post("/api/setup/link")
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

    @app.post("/api/setup/answers")
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

    @app.get("/api/{path:path}", include_in_schema=False)
    def unknown_api(path: str):
        """Anything else under /api is missing, not the app shell."""
        return JSONResponse(
            status_code=404, content={"detail": f"no such route: {path}"}
        )

    _mount_frontend(app)
    return app


def _denied():
    """The answer to a request with no token, or the wrong one."""
    return JSONResponse(status_code=403, content={"detail": "setup token required"})


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built panel, which carries the wizard's screens too."""
    assets_dir = WEB_FRONTEND_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str):
        index_path = WEB_FRONTEND_DIST_DIR / "index.html"
        candidate = (WEB_FRONTEND_DIST_DIR / path).resolve()
        if (
            path
            and candidate.is_file()
            and candidate.is_relative_to(WEB_FRONTEND_DIST_DIR.resolve())
        ):
            return FileResponse(candidate)
        if index_path.is_file():
            return FileResponse(index_path, headers={"cache-control": "no-store"})
        return JSONResponse(
            status_code=503,
            content={"detail": "frontend not built; set this box up in the terminal"},
        )
