"""The Proxy tab: the GeoIP split and the gateway's own routing.

The switches here are the proxy's scopes, and each stands alone.
``is_proxy_enabled`` sends the traffic this box forwards through the exit
nodes; ``is_local_proxy_enabled`` sends the box's own traffic — including
netbird, which is the way back in when the overlay cannot reach its management
plane directly; ``is_geoip_split_enabled`` decides whether Chinese
destinations skip the proxy for whatever is sent to it.
"""

import ipaddress
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.xray.constants import XRAY_BINARY_NAME
from neutrino_hub.modules.xray.routing_rules import (
    check_direct_address,
    check_direct_domain,
)
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.utils.subprocess_run import command_failure_text
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
    is_exit_needed = settings.is_proxy_enabled or settings.is_local_proxy_enabled
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
    except (subprocess.SubprocessError, OSError, RuntimeError, ValueError) as error:
        return ApplyResult(is_applied=False, message=command_failure_text(error))
    return ApplyResult(is_applied=True, message=message)


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
