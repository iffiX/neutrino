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

The hub's service serves it from the install, behind the token kept in
``setup_token`` under the state root, until the box is set up. Whichever
process starts the steps first holds the setup lock.

Not pure: reads and writes the token file and the lock file.
"""

import asyncio
import os
import secrets
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from neutrino_hub.web.constants import (
    WEB_FRONTEND_DIST_DIR,
    WEB_SETUP_LOCK_PATH,
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
    WEB_SETUP_TOKEN_MODE,
    WEB_SETUP_TOKEN_PATH,
)
from neutrino_hub.web.routers.hub.setup import setup_router


def ensure_setup_token(path: "Path | None" = None) -> str:
    """The token the service serves the wizard behind, made when missing.

    Args:
        path: The token file; None is :data:`WEB_SETUP_TOKEN_PATH`.

    Returns:
        The token.

    Raises:
        OSError: When the file can be neither read nor written.
    """
    path = path or WEB_SETUP_TOKEN_PATH
    try:
        token = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        token = ""
    if token:
        return token
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(WEB_SETUP_TOKEN_BYTES)
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, WEB_SETUP_TOKEN_MODE
        )
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(token + "\n")
    return token


def remove_setup_token(path: "Path | None" = None) -> None:
    """Remove the token once the box is set up.

    Args:
        path: The token file; None is :data:`WEB_SETUP_TOKEN_PATH`.

    Raises:
        OSError: When the file is there and cannot be removed.
    """
    (path or WEB_SETUP_TOKEN_PATH).unlink(missing_ok=True)


class SetupLock:
    """The lock whichever process runs the first run's steps holds.

    Taken without waiting, held until :meth:`release` or the process ends.
    """

    def __init__(self, *, path: "Path | None" = None, platform=None):
        """
        Args:
            path: The lock file; None is :data:`WEB_SETUP_LOCK_PATH`.
            platform: The :class:`HubPlatform` that locks a file; None is
                this system's.
        """
        self._path = Path(path or WEB_SETUP_LOCK_PATH)
        self._platform = platform
        self._descriptor = None
        self._guard = threading.Lock()

    def acquire(self) -> bool:
        """Take the lock, or say another process holds it.

        Returns:
            True when this process holds it now, taken here or before.

        Raises:
            OSError: When the lock file cannot be opened or locked at all.
        """
        with self._guard:
            if self._descriptor is not None:
                return True
            if self._platform is None:
                from neutrino_hub.platforms.detect import hub_platform

                self._platform = hub_platform()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
            if not self._platform.try_lock(descriptor):
                os.close(descriptor)
                return False
            self._descriptor = descriptor
            return True

    def release(self) -> None:
        """Let go of the lock when this process holds it.

        Raises:
            OSError: When the lock cannot be released.
        """
        with self._guard:
            if self._descriptor is None:
                return
            try:
                self._platform.unlock(self._descriptor)
            finally:
                os.close(self._descriptor)
                self._descriptor = None


class WebSetupSession:
    """What the browser and the terminal both look at.

    One setup run: the questions to ask, the answers that came back, and how
    far the steps have got. Both sides touch it from their own thread, so
    every read and write takes the lock.
    """

    def __init__(
        self, *, context: dict, token: str = "", setup_lock: "SetupLock | None" = None
    ):
        """
        Args:
            context: The facts the questions are asked against — this
                machine's ports, the modes they allow, the modules it could
                install. The terminal gathers them; this only serves them.
            token: The token the browser carries; empty makes one for this
                run.
            setup_lock: The lock answers take before the steps run; None
                takes none.
        """
        self.token = token or secrets.token_urlsafe(WEB_SETUP_TOKEN_BYTES)
        self._setup_lock = setup_lock
        self._lock = threading.Lock()
        self._context = context
        self._answered = threading.Event()
        self._is_done_served = threading.Event()
        self._document: dict = {}
        self._state = WEB_SETUP_STATE_ASKING
        self._steps: list = []
        self._notes: list = []
        self._message = ""
        self._panel_url = ""
        self._authority: "dict | None" = None

    # --- what the browser reads ---

    def context(self) -> dict:
        """The facts the questions are asked against."""
        return self._context

    def state(self) -> dict:
        """Where this run has got to.

        Returns:
            The state name, every step reported so far, the panel's address
            once there is one, and the certificate authority to install
            before opening it, None when the panel speaks HTTP.
        """
        with self._lock:
            reply = {
                "state": self._state,
                "message": self._message,
                "panel_url": self._panel_url,
                "authority": self._authority,
                "steps": list(self._steps),
                "notes": list(self._notes),
            }
        if reply["state"] == WEB_SETUP_STATE_DONE:
            # The page has now been told the run finished, which is what the
            # hand-over waits for before it takes this server away.
            self._is_done_served.set()
        return reply

    # --- what the browser writes ---

    def answer(self, document: dict) -> bool:
        """Hand the terminal what the browser filled in.

        Args:
            document: The answers document, unchecked. Whether it can be used
                is the wizard's to say, and it says so through
                :meth:`reject`.

        Returns:
            False when another process holds the setup lock, and the answers
            are not taken.

        Raises:
            OSError: When the setup lock cannot be taken at all.
        """
        if self._setup_lock is not None and not self._setup_lock.acquire():
            return False
        with self._lock:
            self._document = document
            self._state = WEB_SETUP_STATE_RUNNING
            self._steps = []
            self._notes = []
            self._message = ""
        self._answered.set()
        return True

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

    def forget_answers(self) -> None:
        """Take the next answers after a run that failed, keeping its state."""
        with self._lock:
            self._document = {}
        self._answered.clear()

    def step(
        self, step_id: str, status: str, note: str = "", params: dict | None = None
    ) -> None:
        """Record where the steps have got to.

        A step already listed is updated in place, so the browser sees one
        line move from running to its outcome rather than two lines.

        Args:
            step_id: The step's name, which the page words for itself.
            status: One of the ``WEB_SETUP_STEP_`` states.
            note: Short detail, the same one the terminal shows.
            params: The values the page's wording names.
        """
        values = dict(params or {})
        with self._lock:
            for entry in self._steps:
                if entry["id"] == step_id and entry["params"] == values:
                    entry["status"] = status
                    entry["note"] = note
                    break
            else:
                self._steps.append(
                    {
                        "id": step_id,
                        "params": values,
                        "status": status,
                        "note": note,
                    }
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

    def finish(self, *, panel_url: str, authority: "dict | None" = None) -> None:
        """Say the box is set up and where its panel will answer.

        Args:
            panel_url: Where to send the browser once the panel is up.
            authority: The certificate authority the page offers to install
                first: ``url``, ``file_name``, ``fingerprint`` and ``der`` in
                base64. None when the panel speaks HTTP.
        """
        with self._lock:
            self._state = WEB_SETUP_STATE_DONE
            self._panel_url = panel_url
            self._authority = authority
            for entry in self._steps:
                if entry["status"] == WEB_SETUP_STEP_RUNNING:
                    entry["status"] = WEB_SETUP_STEP_FAILED

    def wait_done_served(self, timeout_s: float) -> bool:
        """Block until one poll has read the finished state.

        The browser's closing screen — the countdown, the hand-over
        animation — exists only if a poll lands after :meth:`finish`;
        stopping the server on a timer races that poll and sometimes wins.

        Args:
            timeout_s: How long to wait for a page that may be closed.

        Returns:
            Whether a poll read it in time.
        """
        return self._is_done_served.wait(timeout_s)


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
            asyncio.run(self._serve_quietly())
        except SystemExit:
            pass

    async def _serve_quietly(self) -> None:
        """Serve, with a closed connection on Windows kept out of the log."""
        from neutrino_hub.platforms.windows import quiet_connection_resets

        quiet_connection_resets(asyncio.get_running_loop())
        await self._server.serve()


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
    app.include_router(setup_router(session))

    @app.get("/api/{path:path}", include_in_schema=False)
    def unknown_api(path: str):
        """Anything else under /api is missing, not the app shell."""
        return JSONResponse(
            status_code=404, content={"detail": f"no such route: {path}"}
        )

    _mount_frontend(app)
    return app


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
