"""Assembling the FastAPI applications.

One process, two applications: the panel serves its API, grouped as the
sidebar is under ``/api/hub`` and ``/api/agent``, and the built frontend on
its HTTP port and its HTTPS port, and the legacy listener serves
``/api/channel`` alone over the agent TLS pair on loopback, for a 0.5
agent's own update. Both share one runtime, which the transport's local
channel also drives.

The frontend is a single-page app: any panel path that is not an API route, a
websocket, or a real file falls through to ``index.html``.
"""

import logging
import subprocess

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from neutrino_hub import edition
from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.clients.ai_keys import settle_device_keys
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier, load_config
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.legacy_files import move_legacy_device_files
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.hub_update.installer import retire_finished_job
from neutrino_hub.web import ws
from neutrino_hub.web.legacy_listener import ChannelRequestLimitMiddleware
from neutrino_hub.web.constants import WEB_CODE_BODY_INVALID, WEB_FRONTEND_DIST_DIR
from neutrino_hub.web.https_redirect import PanelHttpsRedirectMiddleware
from neutrino_hub.web.origin_guard import OriginGuardMiddleware
from neutrino_hub.web.panel_sign_in import PanelSignInMiddleware
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.usage_collector import PanelUsageCollector
from neutrino_hub.web.routers import channel
from neutrino_hub.web.routers.agent import (
    file,
    module,
    module_account,
    module_ayakaleaf,
    module_gitea,
    module_hermes_webui,
    module_instances,
    module_podman,
    module_remote_desktop,
    module_samba,
    module_vscode_terms,
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
    overlay_direct,
    overlay_easytier,
    overlay_netbird,
    overlay_openfrp,
    overlay_relay,
    overlay_sakurafrp,
    service,
    setting,
)
from neutrino_hub.web.routers.hub import client as hub_client
from neutrino_hub.web.routers.hub import web_share as hub_web_share

# The hub group in sidebar order, then the agent group. The proxy's routers
# come from the edition table.
API_ROUTERS = (
    auth.router,
    display.router,
    dashboard.router,
    network.router,
    overlay.router,
    overlay_direct.router,
    overlay_easytier.router,
    overlay_relay.router,
    overlay_sakurafrp.router,
    overlay_openfrp.router,
    overlay_netbird.router,
    *edition.hooks("api_routers"),
    ai.router,
    ai_gateway.router,
    device.router,
    hub_client.router,
    hub_web_share.router,
    service.router,
    credential.router,
    setting.router,
    setting.authority_router,
    file.router,
    module.router,
    module_account.router,
    module_samba.router,
    module_remote_desktop.router,
    module_gitea.router,
    module_podman.router,
    module_hermes_webui.router,
    module_ayakaleaf.router,
    *module_instances.ROUTERS.values(),
    module_vscode_terms.router,
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
    app.state.runtime = shared_runtime()
    app.add_exception_handler(VaultLockedError, _vault_locked)
    app.add_exception_handler(RequestValidationError, _body_invalid)
    app.add_middleware(PanelSignInMiddleware, runtime=app.state.runtime)
    app.add_middleware(OriginGuardMiddleware)
    app.add_middleware(PanelHttpsRedirectMiddleware, runtime=app.state.runtime)
    _move_legacy_files()
    _grant_ssh_once()
    _settle_gateway_key()
    _settle_device_keys()
    _retire_update_job()
    _start_samplers()

    for router in API_ROUTERS:
        app.include_router(router)
    app.include_router(ws.router)

    _mount_frontend(app)
    return app


def create_agent_app() -> FastAPI:
    """Build the legacy listener: the ``/api/channel`` routes and nothing
    else, no API description among them, with each body held to the
    listener's limit.

    Returns:
        The configured application, sharing the panel's runtime.
    """
    app = FastAPI(
        title="Neutrino Hub Legacy Listener",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime = shared_runtime()
    app.add_exception_handler(VaultLockedError, _vault_locked)
    app.add_exception_handler(RequestValidationError, _body_invalid)
    app.add_middleware(ChannelRequestLimitMiddleware)
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


def _body_invalid(request: Request, error: RequestValidationError) -> JSONResponse:
    """Answer a body, query or path that does not validate, in the one shape.

    FastAPI's own answer is a 422 carrying a list; every refusal here is
    ``{code, params}``, and a body that does not validate is the 400 class.

    Args:
        request: The request whose input did not validate.
        error: What did not validate, field by field.

    Returns:
        A 400 carrying ``body_invalid`` and the fields named.
    """
    del request
    fields = []
    for problem in error.errors():
        location = problem.get("loc", ())
        field = ".".join(str(part) for part in location if part not in ("body",))
        if field and field not in fields:
            fields.append(field)
    return JSONResponse(
        status_code=400,
        content={
            "detail": {
                "code": WEB_CODE_BODY_INVALID,
                "params": {"fields": ", ".join(fields)},
            }
        },
    )


def shared_runtime() -> PanelRuntime:
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


def _move_legacy_files() -> None:
    """Move every machine's 0.5 files into the account layer, at the panel's start.

    A hub upgraded from 0.5 holds each module's accounts inside the module's
    file; they go into ``accounts.json`` here, once per machine.
    """
    try:
        moved = move_legacy_device_files(
            DesiredStateStore(),
            [device.id for device in DeviceRegistry().all_stored()],
        )
    except (ValueError, OSError) as error:
        LOGGER.warning("the 0.5 device files were not moved: %s", error)
        return
    if moved:
        LOGGER.info("devices: the 0.5 files of %s moved", ", ".join(moved))


def _grant_ssh_once() -> None:
    """Add ``ssh`` beside ``terminal`` in every stored permission, once.

    The grant is written at the hub's first 0.6.0 start and marked in the
    clients file, so a permission the person narrows afterwards stays
    narrowed (protocol.md, "The codes 0.6.0 adds and removes").
    """
    try:
        granted = ClientRegistry().grant_ssh_once()
    except (ValueError, OSError) as error:
        LOGGER.warning("ssh was not granted to the clients: %s", error)
        return
    if granted:
        LOGGER.info("clients: ssh granted beside terminal, once")


def _settle_device_keys() -> None:
    """Revoke the device keys no AI tools setting holds on, at the panel's start.

    A device key follows its machine's AI tools setting. A hub upgraded from
    a build that minted one for every device with CloudCLI holds keys no
    setting asks for; they go here, once, and the gateway reloads its list.
    """
    store = DesiredStateStore()
    try:
        enabled = [
            device.id
            for device in DeviceRegistry().all_stored()
            if store.is_ai_tools_enabled(device.id)
        ]
        dropped = settle_device_keys(enabled)
    except (VaultLockedError, ValueError, OSError, subprocess.SubprocessError) as error:
        LOGGER.warning("device keys not settled: %s", error)
        return
    if dropped:
        LOGGER.info("gateway: revoked the keys of %s", ", ".join(dropped))


def _retire_update_job() -> None:
    """On macOS, end the update job an earlier hub submitted, at the panel's start.

    launchd runs a submitted job again each time it exits; once the update's
    record is final, the job's script is replaced by one that removes the job.
    """
    try:
        if retire_finished_job():
            LOGGER.info("hub update: the finished launchd job removes itself next")
    except OSError as error:
        LOGGER.warning(
            "hub update: the finished launchd job was not retired: %s", error
        )


def _start_samplers() -> None:
    """The process-wide background readers, started with the panel application.

    Each watches something no write announces: what the gateway metered, what
    the interfaces are doing, what each module's publisher released, and,
    with the proxy, what every exit node measures. Each publishes an event
    when its reading moves, so no page has to ask on a timer. The traffic
    history counts every interface's bytes beside them.
    """
    global _usage_collector
    runtime = shared_runtime()
    if _usage_collector is None:
        _usage_collector = PanelUsageCollector(
            served_models=runtime.served_models,
            on_change=runtime.publish_ai_usage,
        )
        _usage_collector.start()
    runtime.link_sampler.start()
    runtime.address_sampler.start()
    runtime.release_sampler.start()
    runtime.enrollment_sweeper.start()
    runtime.web_share_sweeper.start()
    runtime.traffic_history.start()
    if runtime.proxy is not None:
        runtime.proxy.start()
    runtime.relay_monitor.start()
    for monitor in runtime.frp_monitors.values():
        monitor.start()


def stop_samplers() -> None:
    """Write the traffic history, as the panel stops."""
    if _shared_runtime is not None:
        _shared_runtime.traffic_history.stop()


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
