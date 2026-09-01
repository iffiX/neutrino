"""The Proxy tab: the GeoIP split and the gateway's own routing.

The two switches here are the ones that change what leaves the box and how.
``is_geoip_split_enabled`` decides whether Chinese destinations skip the proxy;
``is_local_proxy_enabled`` decides whether the gateway's own traffic — including
netbird — goes through it, which is the way back in when the overlay cannot
reach its management plane directly.
"""

import ipaddress

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.xray.constants import XRAY_BINARY_NAME
from neutrino_hub.modules.xray.routing_rules import (
    check_direct_address,
    check_direct_domain,
)
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.utils.subprocess_run import CommandError
from neutrino_hub.web.constants import WEB_PORT_MAX, WEB_PORT_MIN
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import ApplyResult, ProxySettings
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/proxy", tags=["proxy"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=ProxySettings)
def read_settings(runtime: PanelRuntime = Depends(get_runtime)) -> ProxySettings:
    """Read the current routing options.

    Args:
        runtime: The shared runtime.

    Returns:
        The stored options.
    """
    return ProxySettings(**runtime.routing())


@router.put("", response_model=ProxySettings)
def update_settings(
    settings: ProxySettings, runtime: PanelRuntime = Depends(get_runtime)
) -> ProxySettings:
    """Change the routing options.

    Args:
        settings: The new options.
        runtime: The shared runtime.

    Returns:
        The stored options. Flipping either switch re-renders both the xray
        config and the nftables ruleset, so it takes effect on the next Apply.

    Raises:
        HTTPException: 400 when the proxy is switched on with nothing to go
            out through, when a resolver is not an address, when two listeners
            want one port, when a listener wants a port something on the box
            already holds, or when a direct list holds a line xray will not
            load. Each of these reaches the xray config, where a bad value is a
            proxy that will not start rather than a setting that does nothing.
    """
    if settings.is_proxy_enabled and not runtime.node_list().enabled_nodes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no exit node is enabled, so there is nothing to proxy through",
        )
    for name, resolver in (
        ("remote resolver", settings.remote_dns),
        ("direct resolver", settings.direct_dns),
    ):
        try:
            ipaddress.ip_address(resolver.address)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{name}: {error}",
            ) from error
        if not WEB_PORT_MIN <= resolver.port <= WEB_PORT_MAX:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{name}: a port is {WEB_PORT_MIN} to {WEB_PORT_MAX}",
            )
    seen = [entry.port for entry in settings.socks_ports]
    if len(set(seen)) != len(seen):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="two listeners cannot share a port",
        )
    for entry in settings.socks_ports:
        if not WEB_PORT_MIN <= entry.port <= WEB_PORT_MAX:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"a port is {WEB_PORT_MIN} to {WEB_PORT_MAX}; "
                f"{entry.port} is not",
            )
    # xray's own listeners are excluded: they are the ports this file already
    # asked for, and counting them would make every second save a conflict.
    held = runtime.listening_ports.ports(ignoring=XRAY_BINARY_NAME)
    for entry in settings.socks_ports:
        if entry.port in held:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"port {entry.port} is already in use on this box",
            )
    for entries, check in (
        (settings.direct_domains, check_direct_domain),
        (settings.direct_ips, check_direct_address),
    ):
        for entry in entries:
            try:
                check(entry)
            except ValueError as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
                ) from error
    write_config("xray/routing.json", settings.model_dump())
    runtime.is_config_dirty = True
    return settings


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
    except (CommandError, ValueError) as error:
        return ApplyResult(is_applied=False, message=str(error))
    return ApplyResult(is_applied=True, message=message)
