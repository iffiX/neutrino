"""The proxy's exit nodes: enabling them, measuring them, testing one.

A file of its own rather than a section of ``proxy.py`` because the nodes
are a collection with a life of their own — added from a share link,
renamed, tested, deleted — where the module's own settings are two
switches. Both answer under ``/api/hub/proxy``.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.utils.json_file import write_config
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    BalancerSettings,
    NodeCreate,
    NodeListView,
    NodeRequest,
    NodeTestRequest,
    NodeUpdate,
    NodeView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.modules.xray.constants import (
    XRAY_SCOPE_SWITCHES,
    XRAY_PROBE_INTERVAL_MAX_S,
    XRAY_PROBE_INTERVAL_MIN_S,
)
from neutrino_hub.modules.xray.node_config import (
    XrayNodeConfig,
    XrayNodeList,
    parse_share_link,
)
from neutrino_hub.modules.xray.node_health import XrayNodeHealth
from neutrino_hub.modules.xray.node_secrets import (
    delete_node_secret,
    store_node_secret,
)
from neutrino_hub.modules.xray.stats_client import OutboundTraffic

router = APIRouter(
    prefix="/api/hub/proxy", tags=["proxy"], dependencies=[Depends(require_session)]
)


@router.get("/node", response_model=NodeListView)
def list_nodes(runtime: PanelRuntime = Depends(get_runtime)) -> NodeListView:
    """Read every node with its live traffic and its latest measurement.

    Every node is reported, switched on or not, from what the exit controller
    already holds in memory. Nothing here probes or reaches xray for a reading.

    Args:
        runtime: The shared runtime.

    Returns:
        The node list, the measurement settings, and whether changes are
        waiting to be applied.
    """
    node_list = runtime.node_list()
    traffic = {entry.tag: entry for entry in runtime.stats.outbound_traffic()}
    healths = runtime.exit_controller.healths()
    exit_tag = runtime.exit_controller.status.exit_tag
    return NodeListView(
        nodes=[
            _node_view(
                node,
                health=healths.get(node.tag),
                counters=traffic.get(node.tag),
                exit_tag=exit_tag,
            )
            for node in node_list.nodes
        ],
        balancer=BalancerSettings(
            probe_url=node_list.probe_url,
            reference_url=node_list.reference_url,
            probe_interval_s=node_list.probe_interval_s,
        ),
        is_dirty=runtime.is_config_dirty,
    )


@router.post("/balancer/set", response_model=BalancerSettings)
def update_balancer(
    settings: BalancerSettings, runtime: PanelRuntime = Depends(get_runtime)
) -> BalancerSettings:
    """Change how the hub measures the nodes it picks the exit from.

    None of the three reaches the xray configuration, so the next round takes
    them and nothing waits for an Apply.

    Args:
        settings: The new measurement settings.
        runtime: The shared runtime.

    Returns:
        The stored settings.

    Raises:
        HTTPException: 400 when the interval is outside the range a round can
            keep, or when either address is not an http or https URL.
    """
    if not (
        XRAY_PROBE_INTERVAL_MIN_S
        <= settings.probe_interval_s
        <= XRAY_PROBE_INTERVAL_MAX_S
    ):
        raise _refusal(
            "probe_interval_out_of_range",
            minimum=XRAY_PROBE_INTERVAL_MIN_S,
            maximum=XRAY_PROBE_INTERVAL_MAX_S,
        )
    if not settings.probe_url.startswith(("http://", "https://")):
        raise _refusal("probe_url_invalid")
    if not settings.reference_url.startswith(("http://", "https://")):
        raise _refusal("reference_url_invalid")
    node_list = runtime.node_list()
    node_list.probe_url = settings.probe_url
    node_list.reference_url = settings.reference_url
    node_list.probe_interval_s = settings.probe_interval_s
    write_config("xray/nodes.json", node_list.to_dict())
    runtime.exit_controller.wake()
    return settings


@router.post("/node/add", response_model=NodeView, status_code=status.HTTP_201_CREATED)
def add_node(
    request: NodeCreate, runtime: PanelRuntime = Depends(get_runtime)
) -> NodeView:
    """Add a node from a share link.

    Args:
        request: The ``ss://`` or ``vless://`` link, as copied from the
            provider's dashboard.
        runtime: The shared runtime.

    Returns:
        The node as added, enabled and waiting for the next Apply.

    Raises:
        HTTPException: 400 when the link cannot be parsed, or when it names a
            node already in the list.
    """
    try:
        node = parse_share_link(request.link)
    except ValueError as error:
        raise _refusal("share_link_unreadable", detail=str(error)) from error

    node_list = runtime.node_list()
    if any(existing.id == node.id for existing in node_list.nodes):
        raise _refusal("node_already_listed", node=node.id)
    # Sealed before the reference is written, so the file never names an
    # object that does not exist.
    store_node_secret(node)
    node_list.nodes.append(node)
    write_config("xray/nodes.json", node_list.to_dict())
    _follow_the_nodes(node_list, runtime)
    runtime.is_config_dirty = True
    return _node_view(node)


@router.post("/node/remove", response_model=NodeListView)
def remove_node(
    request: NodeRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> NodeListView:
    """Remove a node from the list.

    The pair to adding one: a list that can only grow turns one mistyped link
    into a permanent entry.

    Args:
        request: The node's id.
        runtime: The shared runtime.

    Returns:
        The remaining nodes.

    Raises:
        HTTPException: 404 when no node has that id.
    """
    node_id = request.node_id
    node_list = runtime.node_list()
    remaining = [node for node in node_list.nodes if node.id != node_id]
    if len(remaining) == len(node_list.nodes):
        raise _node_unknown(node_id)
    for node in node_list.nodes:
        if node.id == node_id:
            delete_node_secret(node)
    node_list.nodes = remaining
    write_config("xray/nodes.json", node_list.to_dict())
    _follow_the_nodes(node_list, runtime)
    runtime.exit_controller.reselect()
    runtime.is_config_dirty = True
    return list_nodes(runtime)


@router.post("/node/set", response_model=NodeView)
def update_node(
    update: NodeUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> NodeView:
    """Enable, disable, or rename one node.

    Every node is resident in xray, so switching one on or off changes which
    node may be chosen as the exit and nothing that has to be rendered. Both
    take effect at once; only the last enabled node going leaves something to
    apply, and that is what :func:`_follow_the_nodes` writes.

    Args:
        update: The node's identifier and the fields to change.
        runtime: The shared runtime.

    Returns:
        The node after the change.

    Raises:
        HTTPException: 404 when the node is unknown.
    """
    node_list = runtime.node_list()
    node = _find_node(node_list, update.node_id)
    if update.name is not None:
        node.name = update.name
    if update.is_enabled is not None:
        node.is_enabled = update.is_enabled
    write_config("xray/nodes.json", node_list.to_dict())
    _follow_the_nodes(node_list, runtime)
    runtime.exit_controller.reselect()
    return _node_view(
        node,
        health=runtime.exit_controller.healths().get(node.tag),
        exit_tag=runtime.exit_controller.status.exit_tag,
    )


@router.post("/node/test", response_model=NodeListView)
async def test_node(
    request: NodeTestRequest, runtime: PanelRuntime = Depends(get_runtime)
) -> NodeListView:
    """Measure one node now, or every enabled node in one call.

    The list serves what the last round measured; pressing Test asks for a
    fresh one, so this runs a round and then reads it back. One call rather
    than one per node: a measurement holds a thread for its whole timeout.

    Args:
        request: The node's id, or nothing to measure every enabled node.
        runtime: The shared runtime.

    Returns:
        Every node, as the list reads it once the round has finished.

    Raises:
        HTTPException: 404 when the node is unknown.
    """
    try:
        await asyncio.to_thread(runtime.exit_controller.refresh, only=request.node_id)
    except KeyError as error:
        raise _node_unknown(request.node_id or "") from error
    return list_nodes(runtime)


def _node_view(
    node: XrayNodeConfig,
    *,
    health: XrayNodeHealth | None = None,
    counters: OutboundTraffic | None = None,
    exit_tag: str = "",
) -> NodeView:
    """One node as the Nodes tab draws it.

    Args:
        node: The stored node.
        health: Its measurement window; None for a node nobody has measured.
        counters: Its byte counters; None when xray reported none for it.
        exit_tag: The outbound the hub has pinned.

    Returns:
        The view.
    """
    # A node nobody has measured reads as an empty window, which is what it
    # is: no number at all rather than a zero.
    reading = health or XrayNodeHealth(tag=node.tag)
    return NodeView(
        id=node.id,
        name=node.name,
        address=node.address,
        protocol=node.protocol,
        port=node.port,
        is_enabled=node.is_enabled,
        has_reality=node.has_reality,
        is_alive=reading.is_alive,
        is_selected=node.tag == exit_tag,
        connect_ms=reading.connect_ms,
        request_ms=reading.request_ms,
        probed_at=reading.probed_at.isoformat() if reading.probed_at else "",
        success_rate=reading.success_rate,
        score_ms=None if reading.score_ms is None else round(reading.score_ms),
        uplink_bytes=counters.uplink_bytes if counters else 0,
        downlink_bytes=counters.downlink_bytes if counters else 0,
    )


def _follow_the_nodes(node_list: XrayNodeList, runtime: PanelRuntime) -> None:
    """Switch the proxied scopes off once nothing is left to go out through.

    A scope with no enabled node is not a setting, it is a configuration that
    cannot be rendered. It is written into `config/` rather than worked around
    at render time, so the panel shows the state the box is in, and it is the
    one node change that leaves something to apply.

    Args:
        node_list: The nodes as they are now.
        runtime: The shared runtime, whose dirty flag is set where the
            switches moved.
    """
    if node_list.enabled_nodes:
        return
    routing = runtime.routing()
    if not any(routing.get(switch, False) for switch in XRAY_SCOPE_SWITCHES):
        return
    for switch in XRAY_SCOPE_SWITCHES:
        routing[switch] = False
    write_config("xray/routing.json", routing)
    runtime.is_config_dirty = True


def _find_node(node_list: XrayNodeList, node_id: str) -> XrayNodeConfig:
    for node in node_list.nodes:
        if node.id == node_id:
            return node
    raise _node_unknown(node_id)


def _node_unknown(node_id: str) -> HTTPException:
    """One 404 naming the node that is not in the list.

    Args:
        node_id: The id that was asked for.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "node_unknown", "params": {"node": node_id}},
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
