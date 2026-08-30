"""The Proxy tab: the GeoIP split and the gateway's own routing.

The two switches here are the ones that change what leaves the box and how.
``is_geoip_split_enabled`` decides whether Chinese destinations skip the proxy;
``is_local_proxy_enabled`` decides whether the gateway's own traffic — including
netbird — goes through it, which is the way back in when the overlay cannot
reach its management plane directly.
"""

from fastapi import APIRouter, Depends

from neutrino_hub.utils.json_file import write_config
from neutrino_hub.utils.subprocess_run import CommandError
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
    """
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
