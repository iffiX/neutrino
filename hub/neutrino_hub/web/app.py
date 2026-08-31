"""Assembling the FastAPI application.

The panel serves both the API and the built frontend, so one process and one
port cover the whole thing. The frontend is a single-page app: any path that is
not an API route, a websocket, or a real file falls through to ``index.html``.
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from neutrino_hub.web import ws
from neutrino_hub.web.constants import WEB_FRONTEND_DIST_DIR
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers import (
    agent,
    auth,
    cliproxyapi,
    credentials,
    dashboard,
    device_files,
    devices,
    keys,
    gitea,
    netbird,
    network,
    nodes,
    podman,
    proxy,
    samba,
    service_control,
    settings,
    zfs,
)

API_ROUTERS = (
    auth.router,
    dashboard.router,
    nodes.router,
    network.router,
    proxy.router,
    devices.router,
    device_files.router,
    keys.router,
    credentials.router,
    cliproxyapi.router,
    samba.router,
    gitea.router,
    podman.router,
    netbird.router,
    zfs.router,
    service_control.router,
    settings.router,
    agent.router,
)


def create_app() -> FastAPI:
    """Build the application with its routes and static files.

    Returns:
        The configured application.
    """
    app = FastAPI(title="Neutrino Hub", docs_url=None, redoc_url=None)
    app.state.runtime = PanelRuntime()

    for router in API_ROUTERS:
        app.include_router(router)
    app.include_router(ws.router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    assets_dir = WEB_FRONTEND_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(request: Request, path: str):
        """Serve the built single-page app.

        Args:
            request: The incoming request.
            path: Whatever was asked for below the root.

        Returns:
            The requested file when it exists, ``index.html`` for any other
            path so client-side routing works, or a short JSON hint when the
            frontend has not been built yet.
        """
        del request
        index_path = WEB_FRONTEND_DIST_DIR / "index.html"
        candidate = (WEB_FRONTEND_DIST_DIR / path).resolve()
        if (
            path
            and candidate.is_file()
            and candidate.is_relative_to(WEB_FRONTEND_DIST_DIR.resolve())
        ):
            return FileResponse(candidate)
        if index_path.is_file():
            # The shell names the hashed bundle to load, so a cached copy of
            # it is a cached copy of the whole panel — someone would keep
            # running yesterday's build without knowing why it misbehaves.
            # The assets it names are content-addressed and cache freely.
            return FileResponse(index_path, headers={"cache-control": "no-store"})
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "frontend not built; run "
                    "npm install && npm run build in hub/frontend"
                )
            },
        )
