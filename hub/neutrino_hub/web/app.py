"""Assembling the FastAPI applications.

One process, two applications: the panel serves its API, grouped as the
sidebar is under ``/api/hub`` and ``/api/agent``, and the built frontend on
plain HTTP, and the agent channel serves ``/api/channel`` alone on its own
TLS port. Both share one runtime, which is where a ticket the panel
generates is spent by the peer that joins with it.

The frontend is a single-page app: any panel path that is not an API route, a
websocket, or a real file falls through to ``index.html``.
"""

import logging
import subprocess

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier, load_config
from neutrino_hub.web import ws
from neutrino_hub.web.constants import WEB_FRONTEND_DIST_DIR
from neutrino_hub.web.origin_guard import OriginGuardMiddleware
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.usage_collector import PanelUsageCollector
from neutrino_hub.web.routers import channel
from neutrino_hub.web.routers.agent import (
    file,
    module,
    module_gitea,
    module_podman,
    module_samba,
    module_zfs,
)
from neutrino_hub.web.routers.hub import (
    ai,
    ai_gateway,
    auth,
    credential,
    dashboard,
    device,
    display,
    network,
    overlay,
    overlay_easytier,
    overlay_netbird,
    proxy,
    proxy_node,
    service,
    setting,
)
from neutrino_hub.web.routers.hub import client as hub_client

# The hub group in sidebar order, then the agent group.
API_ROUTERS = (
    auth.router,
    display.router,
    dashboard.router,
    network.router,
    overlay.router,
    overlay_netbird.router,
    overlay_easytier.router,
    proxy.router,
    proxy_node.router,
    ai.router,
    ai_gateway.router,
    device.router,
    hub_client.router,
    service.router,
    credential.router,
    setting.router,
    file.router,
    module.router,
    module_samba.router,
    module_gitea.router,
    module_podman.router,
    module_zfs.router,
)

LOGGER = logging.getLogger(__name__)
_shared_runtime = None
_usage_collector = None


def create_app() -> FastAPI:
    """Build the panel application with its routes and static files.

    Returns:
        The configured application.
    """
    app = FastAPI(title="Neutrino Hub", docs_url=None, redoc_url=None)
    app.state.runtime = _runtime()
    app.add_exception_handler(VaultLockedError, _vault_locked)
    app.add_middleware(OriginGuardMiddleware)
    _settle_gateway_key()
    _start_samplers()

    for router in API_ROUTERS:
        app.include_router(router)
    app.include_router(ws.router)

    _mount_frontend(app)
    return app


def create_agent_app() -> FastAPI:
    """Build the agent channel: the ``/api/channel`` routes and nothing else.

    Returns:
        The configured application, sharing the panel's runtime.
    """
    app = FastAPI(title="Neutrino Hub Agent Channel", docs_url=None, redoc_url=None)
    app.state.runtime = _runtime()
    app.add_exception_handler(VaultLockedError, _vault_locked)
    app.include_router(channel.router)
    return app


def _vault_locked(request: Request, error: VaultLockedError) -> JSONResponse:
    """Answer any route the locked vault stopped, with the one code.

    Args:
        request: The request that hit the lock.
        error: The refusal.

    Returns:
        A 400 carrying ``vault_locked``.
    """
    del request, error
    return JSONResponse(
        status_code=400,
        content={"detail": {"code": VaultLockedError.code, "params": {}}},
    )


def _runtime() -> PanelRuntime:
    """The one runtime both applications hand their routes.

    Returns:
        The process-wide instance, built on first use.
    """
    global _shared_runtime
    if _shared_runtime is None:
        _shared_runtime = PanelRuntime()
    return _shared_runtime


def _settle_gateway_key() -> None:
    """The hub's own gateway key, made true when the panel starts.

    Setup and every apply mint it, so a box set up on this hub always has
    one. A box set up before the hub held a key of its own has a gateway
    running on an empty key list, which asks nobody for a key; it converges
    here, once, and the gateway restarts on the list with the hub's key in
    it.
    """
    applier = CliproxyApiConfigApplier()
    if not applier.is_installed or load_config().hub_key is not None:
        return
    try:
        LOGGER.info("gateway: %s", applier.apply())
    except (VaultLockedError, ValueError, OSError, subprocess.SubprocessError) as error:
        LOGGER.warning("gateway key not minted: %s", error)


def _start_samplers() -> None:
    """The process-wide background readers, started with the panel application.

    Each watches something no write announces: what the gateway metered, what
    the interfaces are doing, and what every exit node measures. Each
    publishes an event when its reading moves, so no page has to ask on a
    timer.
    """
    global _usage_collector
    runtime = _runtime()
    if _usage_collector is None:
        _usage_collector = PanelUsageCollector(
            served_models=runtime.served_models,
            on_change=runtime.publish_ai_usage,
        )
        _usage_collector.start()
    runtime.link_sampler.start()
    runtime.exit_controller.start()


def _mount_frontend(app: FastAPI) -> None:
    assets_dir = WEB_FRONTEND_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/api/{path:path}", include_in_schema=False)
    def unknown_api(path: str):
        """Anything under /api that no router claims is missing.

        Without this the shell below answers it: a page asking whether a
        route exists would be handed the app itself, with a 200 on it.

        Args:
            path: What was asked for.

        Returns:
            A 404 naming it.
        """
        return JSONResponse(
            status_code=404, content={"detail": f"no such route: {path}"}
        )

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
