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

The proxy's live objects and its part of the panel's converge step live
here as well, as :class:`ProxyPanelPart`, which the panel's runtime takes
from the edition table; so do the About card's versions and credits of what
the proxy carries.
"""

import asyncio
import json
import subprocess

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.router.network_resolvers import resolver_refusal
from neutrino_hub.modules.router.routes import rendered_network_resolvers
from neutrino_hub.modules.tun.constants import TUN_VERSION
from neutrino_hub.modules.xray import geodata
from neutrino_hub.modules.xray.apply import XrayConfigApplier
from neutrino_hub.modules.xray.apply_part import XrayApplyComponent
from neutrino_hub.modules.xray.constants import (
    XRAY_BINARY,
    XRAY_BINARY_NAME,
    XRAY_CONFIG_PATH,
    XRAY_DIRECT_DNS_FIELD,
    XRAY_GEODATA,
    XRAY_GEODATA_GEOIP_FILE,
    XRAY_GEODATA_GEOSITE_FILE,
    XRAY_NODES_FILE,
    XRAY_REMOTE_DNS_FIELD,
    XRAY_ROUTING_FILE,
    XRAY_SCOPE_SWITCHES,
    XRAY_VERSION,
)
from neutrino_hub.modules.xray.exit_controller import XrayExitController
from neutrino_hub.modules.xray.geodata import XrayGeodataState
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.node_health import XrayNodeHealthStore
from neutrino_hub.modules.xray.node_probe import XrayNodeProbe
from neutrino_hub.modules.xray.resolvers import (
    direct_resolvers,
    read_resolvers,
    with_resolver_lists,
)
from neutrino_hub.modules.xray.routing_rules import (
    check_direct_address,
    check_direct_domain,
)
from neutrino_hub.modules.xray.stats_client import XrayStatsClient
from neutrino_hub.platforms.constants import PLATFORM_OS_DARWIN, PLATFORM_OS_WINDOWS
from neutrino_hub.utils.json_file import read_config, write_config
from neutrino_hub.utils.subprocess_run import command_failure_text, run
from neutrino_hub.web.constants import WEB_PORT_MAX, WEB_PORT_MIN
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.exceptions import NetworkApplyError
from neutrino_hub.web.models import (
    ApplyChange,
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
# What the hub package carries for the proxy, credited on the About card with
# the exact tag each was built from, and the systems whose package carries
# it: None for every system.
PROXY_ABOUT_COMPONENTS = (
    (
        "Xray-core",
        XRAY_VERSION,
        "MPL-2.0",
        "https://github.com/XTLS/Xray-core/tree/v{}",
        None,
    ),
    (
        "tun2socks",
        TUN_VERSION,
        "MIT",
        "https://github.com/xjasonlyu/tun2socks/tree/v{}",
        (PLATFORM_OS_DARWIN, PLATFORM_OS_WINDOWS),
    ),
    (
        "v2fly geoip",
        XRAY_GEODATA[XRAY_GEODATA_GEOIP_FILE]["url"].split("/")[-2],
        "CC-BY-SA-4.0",
        "https://github.com/v2fly/geoip/tree/{}",
        None,
    ),
    (
        "v2fly domain-list-community",
        XRAY_GEODATA[XRAY_GEODATA_GEOSITE_FILE]["url"].split("/")[-2],
        "MIT",
        "https://github.com/v2fly/domain-list-community/tree/{}",
        None,
    ),
)

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
        HTTPException: 400 when a proxied scope is switched on with
            nothing to go out through, when the remote resolver list is
            empty, when a resolver is not an address, when two listeners
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
    if not settings.remote_dns:
        raise _refusal("resolver_required", field=XRAY_REMOTE_DNS_FIELD)
    refusal = resolver_refusal(
        [row.model_dump() for row in settings.remote_dns + settings.direct_dns],
        port_min=WEB_PORT_MIN,
        port_max=WEB_PORT_MAX,
    )
    if refusal is not None:
        code, params = refusal
        raise _refusal(code, **params)
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
    write_config(XRAY_ROUTING_FILE, settings.model_dump())
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
        Whether the apply succeeded, the codes of what it changed, and the
        codes of what failed. A failure is reported rather than raised, so
        the panel can show the reason beside the button that caused it.
    """
    try:
        changes = await runtime.converge_network()
    except NetworkApplyError as error:
        return ApplyResult(is_applied=False, failures=error.failures)
    except (
        subprocess.SubprocessError,
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
    ) as error:
        return ApplyResult(
            is_applied=False,
            failures=[
                ApplyChange(
                    code="apply_failed", params={"detail": command_failure_text(error)}
                )
            ],
        )
    # A restarted xray holds no override. Pinning the stored exit again here
    # puts it back within a second instead of at the next round.
    await asyncio.to_thread(runtime.exit_controller.reassert)
    runtime.exit_controller.wake()
    return ApplyResult(is_applied=True, changes=changes)


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


def about_versions() -> dict:
    """The About card's versions of what the proxy carries.

    Returns:
        ``xray_version``, the first line ``xray version`` prints or ``not
        installed``, and ``geodata_version``, one ``database release`` pair
        per file in name order.
    """
    printed = run([XRAY_BINARY, "version"], is_checked=False).stdout
    return {
        "xray_version": (printed.splitlines() or ["not installed"])[0],
        "geodata_version": _geodata_line(geodata.installed()),
    }


class ProxyPanelPart:
    """The proxy's live objects and its part of the panel's converge step.

    The panel's runtime holds one, from the edition table: the stats client,
    the probe, the measurements and the exit controller, built here and
    started with the application; and the render and the restart of xray
    each converge runs.

    Attributes:
        stats: Reads xray's traffic counters.
        node_probe: Measures one exit node.
        node_health: Every node's measurement window.
        exit_controller: Measures the nodes and pins the exit.
    """

    def __init__(self, *, on_change, on_out_of_sync):
        """
        Args:
            on_change: Called with the round's status when the pinned exit
                moved.
            on_out_of_sync: Called with the round's status when xray does
                not carry the exits the render names.
        """
        self.stats = XrayStatsClient()
        self.node_probe = XrayNodeProbe(resolver_of=self.direct_resolver)
        self.node_health = XrayNodeHealthStore()
        self.exit_controller = XrayExitController(
            probe=self.node_probe,
            store=self.node_health,
            api=self.stats,
            node_list_of=self.node_list,
            routing_of=self.routing,
            rendered_config_of=self.rendered_config,
            on_change=on_change,
            on_out_of_sync=on_out_of_sync,
        )

    def start(self) -> None:
        """Start measuring the nodes, as the application starts."""
        self.exit_controller.start()

    def routing(self) -> dict:
        """Read the current routing options.

        Returns:
            Parsed ``config/xray/routing.json``, its two resolver fields read
            as lists.

        Raises:
            FileNotFoundError: When the box is not set up.
            ValueError: When the file is not valid JSON.
        """
        return with_resolver_lists(read_config(XRAY_ROUTING_FILE))

    def node_list(self) -> XrayNodeList:
        """Read the current node list.

        Returns:
            Parsed ``config/xray/nodes.json``.

        Raises:
            FileNotFoundError: When the box is not set up.
            ValueError: When the file is not valid JSON.
        """
        return XrayNodeList.from_dict(read_config(XRAY_NODES_FILE))

    def rendered_config(self) -> dict:
        """Read the xray configuration the last apply installed.

        Returns:
            The parsed generated file. Only its outbound tags are read by the
            exit controller; the file itself carries every node's secret.

        Raises:
            OSError: If the generated file cannot be read.
            ValueError: If it does not parse as JSON.
        """
        return json.loads(XRAY_CONFIG_PATH.read_text(encoding="utf-8"))

    def direct_resolver(self) -> tuple:
        """The first direct resolver, for the lookups the proxy makes for itself.

        Returns:
            ``(address, port)`` of the first row of ``direct_dns``, else of
            the network's resolvers the last render used.
        """
        first = direct_resolvers(self.routing(), rendered_network_resolvers())[0]
        return str(first["address"]), int(first["port"])

    def has_direct_resolvers(self, routing: dict) -> bool:
        """Whether the proxy names direct resolvers of its own.

        Args:
            routing: The routing options.

        Returns:
            True when ``direct_dns`` lists any row.
        """
        return bool(read_resolvers(routing, XRAY_DIRECT_DNS_FIELD))

    def settled_routing(self, node_list: "XrayNodeList | None" = None) -> dict:
        """The routing options, with the scopes switched off if they cannot run.

        A scope with no enabled node has nothing to leave through and renders
        as off. Writing that back means the panel and the box agree about it
        rather than the page showing switches that do nothing.

        Args:
            node_list: The nodes as they are now; None reads them.

        Returns:
            The routing options as they will be rendered.

        Raises:
            FileNotFoundError: When the box is not set up.
            ValueError: When a file is not valid JSON.
        """
        node_list = node_list if node_list is not None else self.node_list()
        routing = self.routing()
        is_scoped = any(routing.get(switch, False) for switch in XRAY_SCOPE_SWITCHES)
        if is_scoped and not node_list.enabled_nodes:
            for switch in XRAY_SCOPE_SWITCHES:
                routing[switch] = False
            write_config(XRAY_ROUTING_FILE, routing)
        return routing

    def render(self, network_resolvers: list) -> dict:
        """Render xray's configuration for one converge.

        Args:
            network_resolvers: The network's resolvers, as read for this
                apply.

        Returns:
            The configuration, the outbounds measured down left out.

        Raises:
            FileNotFoundError: When the box is not set up.
            ValueError: When a file is not valid JSON.
        """
        node_list = self.node_list()
        return XrayApplyComponent().render(
            routing=self.settled_routing(node_list),
            network_resolvers=network_resolvers,
            node_list=node_list,
            down_tags={
                tag
                for tag, health in self.exit_controller.healths().items()
                if health.is_down
            },
        )

    def apply(self, config: dict) -> tuple:
        """Install the rendered configuration and restart xray when it changed.

        Args:
            config: What :meth:`render` returned.

        Returns:
            ``(changes, failed, sentences)``: ``xray_restarted`` among the
            changes when it restarted; ``xray_refused {detail}`` among the
            failed, and its sentence, when xray would not take it. A refused
            configuration stops none of the other steps.
        """
        try:
            if XrayApplyComponent().apply_if_changed(config):
                return [{"code": "xray_restarted", "params": {}}], [], []
        except (subprocess.SubprocessError, OSError, RuntimeError) as error:
            detail = command_failure_text(error)
            return (
                [],
                [{"code": "xray_refused", "params": {"detail": detail}}],
                [f"xray: {detail}"],
            )
        return [], [], []
