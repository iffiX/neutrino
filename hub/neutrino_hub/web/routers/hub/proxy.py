"""The Proxy tab: the GeoIP split and the gateway's own routing.

The switches here are the proxy's scopes, and each stands alone.
``is_proxy_enabled`` sends the traffic this box forwards for the networks it
serves through the exit nodes; ``is_overlay_proxy_enabled`` does the same for
the overlay members using this box as their exit node;
``is_local_proxy_enabled`` sends the box's own traffic — including netbird,
which is the way back in when the overlay cannot reach its management plane
directly; ``is_geoip_split_enabled`` decides whether Chinese destinations
skip the proxy for whatever is sent to it.

The databases that split reads are here too: which release of each the box
holds, and taking the newest one published.
"""

import asyncio
import ipaddress
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.xray import geodata
from neutrino_hub.modules.xray.apply import XrayConfigApplier
from neutrino_hub.modules.xray.constants import (
    XRAY_BINARY_NAME,
    XRAY_GEODATA_GEOIP_FILE,
    XRAY_GEODATA_GEOSITE_FILE,
)
from neutrino_hub.modules.xray.geodata import XrayGeodataState
from neutrino_hub.modules.xray.routing_rules import (
    check_direct_address,
    check_direct_domain,
)
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.utils.subprocess_run import command_failure_text
from neutrino_hub.web.constants import WEB_PORT_MAX, WEB_PORT_MIN
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    ApplyResult,
    GeodataReleaseView,
    GeodataView,
    ProxySettings,
    ProxyView,
    TaskStarted,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

# One update at a time: both jobs write the same two files.
GEODATA_TASK_LABEL = "geodata_update"

router = APIRouter(
    prefix="/api/hub/proxy", tags=["proxy"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=ProxyView)
def read_settings(runtime: PanelRuntime = Depends(get_runtime)) -> ProxyView:
    """Read the current routing options.

    Args:
        runtime: The shared runtime.

    Returns:
        The stored options, and the release of each database the split runs
        on.
    """
    return ProxyView(**runtime.routing(), geodata=_geodata_view(geodata.installed()))


@router.post("/set", response_model=ProxyView)
def update_settings(
    settings: ProxySettings, runtime: PanelRuntime = Depends(get_runtime)
) -> ProxyView:
    """Change the routing options.

    Args:
        settings: The new options.
        runtime: The shared runtime.

    Returns:
        The stored options, as the page reads them. Flipping either switch
        re-renders both the xray
        config and the nftables ruleset, so it takes effect on the next Apply.

    Raises:
        HTTPException: 400 when a proxied scope is switched on with nothing
            to go out through, when a resolver is not an address, when two listeners
            want one port, when a listener wants a port something on the box
            already holds, or when a direct list holds a line xray will not
            load. Each of these reaches the xray config, where a bad value is a
            proxy that will not start rather than a setting that does nothing.
    """
    # The scopes that divert, not the listeners. A proxied port with no exit
    # is simply not published — the renderer already declines it — and that is
    # a listener waiting for a node, not a contradiction to refuse.
    is_exit_needed = (
        settings.is_proxy_enabled
        or settings.is_overlay_proxy_enabled
        or settings.is_local_proxy_enabled
    )
    if is_exit_needed and not runtime.node_list().enabled_nodes:
        raise _refusal("no_exit_node_enabled")
    for resolver in (settings.remote_dns, settings.direct_dns):
        try:
            ipaddress.ip_address(resolver.address)
        except ValueError as error:
            raise _refusal(
                "resolver_address_invalid", address=resolver.address
            ) from error
        if not WEB_PORT_MIN <= resolver.port <= WEB_PORT_MAX:
            raise _refusal(
                "port_out_of_range",
                minimum=WEB_PORT_MIN,
                maximum=WEB_PORT_MAX,
                value=resolver.port,
            )
    seen = [entry.port for entry in settings.socks_ports]
    if len(set(seen)) != len(seen):
        raise _refusal("socks_ports_share_a_port")
    for entry in settings.socks_ports:
        if not WEB_PORT_MIN <= entry.port <= WEB_PORT_MAX:
            raise _refusal(
                "port_out_of_range",
                minimum=WEB_PORT_MIN,
                maximum=WEB_PORT_MAX,
                value=entry.port,
            )
    # xray's own listeners are excluded: they are the ports this file already
    # asked for, and counting them would make every second save a conflict.
    held = runtime.listening_ports.ports(ignoring=XRAY_BINARY_NAME)
    for entry in settings.socks_ports:
        if entry.port in held:
            raise _refusal("port_already_in_use", value=entry.port)
    for entries, check in (
        (settings.direct_domains, check_direct_domain),
        (settings.direct_ips, check_direct_address),
    ):
        for entry in entries:
            try:
                check(entry)
            except ValueError as error:
                raise _refusal(
                    "direct_rule_invalid", value=entry, detail=str(error)
                ) from error
    write_config("xray/routing.json", settings.model_dump())
    runtime.is_config_dirty = True
    return ProxyView(
        **settings.model_dump(), geodata=_geodata_view(geodata.installed())
    )


@router.post("/apply", response_model=ApplyResult)
async def apply(runtime: PanelRuntime = Depends(get_runtime)) -> ApplyResult:
    """Render everything from ``config/`` and load it.

    Named here rather than under nodes, which is where it used to live: what it
    does is neither about nodes nor only about the proxy — it re-renders the
    xray config, the firewall and dnsmasq together and restarts what needs it.
    Every group of settings on the Proxy page ends by calling this, so saving
    and taking effect are one action rather than two.

    Args:
        runtime: The shared runtime.

    Returns:
        Whether the apply succeeded and a message describing the outcome. A
        failure is reported rather than raised, so the panel can show the
        reason beside the button that caused it.
    """
    try:
        message = await runtime.apply_all()
    except (subprocess.SubprocessError, OSError, RuntimeError, ValueError) as error:
        return ApplyResult(is_applied=False, message=command_failure_text(error))
    # A restarted xray holds no override. Pinning the stored exit again here
    # puts it back within a second instead of at the next round.
    await asyncio.to_thread(runtime.exit_controller.reassert)
    runtime.exit_controller.wake()
    return ApplyResult(is_applied=True, message=message)


@router.post("/geodata/scan", response_model=GeodataView)
async def scan_geodata() -> GeodataView:
    """Read what release each database's repository publishes now.

    Returns:
        What the box holds, with ``latest`` naming what is out there.

    Raises:
        HTTPException: 502 with ``geodata_unreachable`` when a repository
            cannot be read, which is the usual answer on a box whose own
            uplink is down.
    """
    try:
        newest = await asyncio.to_thread(geodata.latest)
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "geodata_unreachable", "params": {}},
        ) from error
    return _geodata_view(geodata.installed(), latest=newest)


@router.post("/geodata/update", response_model=TaskStarted)
async def update_geodata(runtime: PanelRuntime = Depends(get_runtime)) -> TaskStarted:
    """Take the newest release of both databases and load it.

    Args:
        runtime: The shared runtime.

    Returns:
        The job whose output ``/ws/hub/task`` streams. A job already running
        is handed back rather than started twice.
    """
    running = runtime.tasks.running(GEODATA_TASK_LABEL)
    if running is not None:
        return TaskStarted(task_id=running.id)
    stream = runtime.tasks.start(
        label=GEODATA_TASK_LABEL, source=_geodata_update_source()
    )
    return TaskStarted(task_id=stream.id)


async def _geodata_update_source():
    """Fetch both databases and restart xray onto them.

    xray reads its databases once, at start, so the files on the disk are not
    what the box is splitting on until the service has been restarted.

    Yields:
        Progress lines for the task stream.
    """
    yield "reading the newest release of each database\n"
    newest = await asyncio.to_thread(geodata.latest)
    for file_name, release in sorted(newest.items()):
        yield f"{file_name} {release}\n"
    state = await asyncio.to_thread(geodata.fetch, newest)
    yield "both files check against their published digests\n"
    yield "restarting xray\n"
    applier = XrayConfigApplier()
    await asyncio.to_thread(applier.restart)
    await asyncio.to_thread(applier.confirm_running)
    yield f"the split now runs on {_geodata_line(state)}\n"


def _geodata_line(state: XrayGeodataState) -> str:
    """One line naming the release behind each database.

    Args:
        state: What the box holds.

    Returns:
        A ``database release`` pair per file, in name order.
    """
    return " · ".join(
        f"{name.removesuffix('.dat')} {release}"
        for name, release in sorted(state.releases.items())
    )


def _geodata_view(
    state: XrayGeodataState, *, latest: dict[str, str] | None = None
) -> GeodataView:
    """The geodata block of the Proxy page.

    Args:
        state: What the box holds.
        latest: What the repositories publish now, where that was asked.

    Returns:
        The block, with ``latest`` empty unless it was asked for.
    """
    return GeodataView(
        geoip_version=state.releases[XRAY_GEODATA_GEOIP_FILE],
        geosite_version=state.releases[XRAY_GEODATA_GEOSITE_FILE],
        source=state.source,
        latest=(
            None
            if latest is None
            else GeodataReleaseView(
                geoip_version=latest[XRAY_GEODATA_GEOIP_FILE],
                geosite_version=latest[XRAY_GEODATA_GEOSITE_FILE],
            )
        ),
    )


def _refusal(code: str, **params) -> HTTPException:
    """One 400 carrying the name of what was refused.

    Args:
        code: What was refused.
        params: The values the panel's sentence names.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": params},
    )
