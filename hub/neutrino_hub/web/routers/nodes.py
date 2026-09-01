"""The proxy's exit nodes: enabling them, ranking them, testing one.

A file of its own rather than a section of ``proxy.py`` because the nodes
are a collection with a life of their own — added from a share link,
renamed, tested, deleted — where the module's own settings are two
switches. Both answer under ``/api/proxy``.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.utils.json_file import write_config
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    BalancerSettings,
    NodeCreate,
    NodeListView,
    NodeTestResult,
    NodeUpdate,
    NodeView,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.modules.xray.constants import XRAY_BALANCER_STRATEGIES
from neutrino_hub.modules.xray.node_config import (
    XrayNodeConfig,
    XrayNodeList,
    parse_share_link,
)

router = APIRouter(
    prefix="/api/proxy", tags=["proxy"], dependencies=[Depends(require_session)]
)


@router.get("/nodes", response_model=NodeListView)
def list_nodes(runtime: PanelRuntime = Depends(get_runtime)) -> NodeListView:
    """Read every node with its live traffic and latency.

    Args:
        runtime: The shared runtime.

    Returns:
        The node list, the balancer settings, and whether changes are waiting
        to be applied.
    """
    node_list = runtime.node_list()
    traffic = {entry.tag: entry for entry in runtime.stats.outbound_traffic()}
    probes = {
        probe.tag: probe
        for probe in runtime.node_probe.results(node_list.enabled_nodes)
    }
    views = []
    for node in node_list.nodes:
        counters = traffic.get(node.tag)
        probe = probes.get(node.tag)
        views.append(
            NodeView(
                id=node.id,
                name=node.name,
                address=node.address,
                protocol=node.protocol,
                port=node.port,
                is_enabled=node.is_enabled,
                has_reality=node.has_reality,
                is_alive=probe.is_alive if probe else False,
                delay_ms=probe.delay_ms if probe else None,
                uplink_bytes=counters.uplink_bytes if counters else 0,
                downlink_bytes=counters.downlink_bytes if counters else 0,
            )
        )
    return NodeListView(
        nodes=views,
        balancer=BalancerSettings(
            strategy=node_list.strategy,
            probe_url=node_list.probe_url,
            probe_interval_s=node_list.probe_interval_s,
        ),
        is_dirty=runtime.is_config_dirty,
    )


@router.put("/balancer", response_model=BalancerSettings)
def update_balancer(
    settings: BalancerSettings, runtime: PanelRuntime = Depends(get_runtime)
) -> BalancerSettings:
    """Change how the balancer picks between nodes.

    Args:
        settings: The new balancer settings.
        runtime: The shared runtime.

    Returns:
        The stored settings.

    Raises:
        HTTPException: 400 when the strategy is not one xray supports.
    """
    if settings.strategy not in XRAY_BALANCER_STRATEGIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown strategy {settings.strategy!r}",
        )
    node_list = runtime.node_list()
    node_list.strategy = settings.strategy
    node_list.probe_url = settings.probe_url
    node_list.probe_interval_s = settings.probe_interval_s
    write_config("xray/nodes.json", node_list.to_dict())
    runtime.is_config_dirty = True
    return settings


@router.post("/nodes", response_model=NodeView, status_code=status.HTTP_201_CREATED)
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    node_list = runtime.node_list()
    if any(existing.id == node.id for existing in node_list.nodes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{node.id} is already in the list",
        )
    node_list.nodes.append(node)
    write_config("xray/nodes.json", node_list.to_dict())
    _follow_the_nodes(node_list, runtime)
    runtime.is_config_dirty = True
    return NodeView(
        id=node.id,
        name=node.name,
        address=node.address,
        protocol=node.protocol,
        port=node.port,
        is_enabled=node.is_enabled,
        has_reality=node.has_reality,
    )


@router.delete("/nodes/{node_id}", response_model=NodeListView)
def remove_node(
    node_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> NodeListView:
    """Remove a node from the list.

    The pair to adding one: a list that can only grow turns one mistyped link
    into a permanent entry.

    Args:
        node_id: The node's id.
        runtime: The shared runtime.

    Returns:
        The remaining nodes.

    Raises:
        HTTPException: 404 when no node has that id.
    """
    node_list = runtime.node_list()
    remaining = [node for node in node_list.nodes if node.id != node_id]
    if len(remaining) == len(node_list.nodes):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no node {node_id!r}"
        )
    node_list.nodes = remaining
    write_config("xray/nodes.json", node_list.to_dict())
    _follow_the_nodes(node_list, runtime)
    runtime.is_config_dirty = True
    return list_nodes(runtime)


@router.put("/nodes/{node_id}", response_model=NodeView)
def update_node(
    node_id: str, update: NodeUpdate, runtime: PanelRuntime = Depends(get_runtime)
) -> NodeView:
    """Enable, disable, or rename one node.

    Args:
        node_id: The node's identifier.
        update: The fields to change.
        runtime: The shared runtime.

    Returns:
        The node after the change. It does not take effect until Apply.

    Raises:
        HTTPException: 404 when the node is unknown.
    """
    node_list = runtime.node_list()
    node = _find_node(node_list, node_id)
    if update.name is not None:
        node.name = update.name
    if update.is_enabled is not None:
        node.is_enabled = update.is_enabled
    write_config("xray/nodes.json", node_list.to_dict())
    _follow_the_nodes(node_list, runtime)
    runtime.is_config_dirty = True
    return NodeView(
        id=node.id,
        name=node.name,
        address=node.address,
        protocol=node.protocol,
        port=node.port,
        is_enabled=node.is_enabled,
        has_reality=node.has_reality,
    )


@router.post("/nodes/{node_id}/test", response_model=NodeTestResult)
def test_node(
    node_id: str, runtime: PanelRuntime = Depends(get_runtime)
) -> NodeTestResult:
    """Measure one node now, bypassing the cache.

    The list view serves cached measurements; pressing Test is a request for a
    fresh one, so this probes rather than reading.

    Args:
        node_id: The node's identifier.
        runtime: The shared runtime.

    Returns:
        The node's liveness and connect latency.

    Raises:
        HTTPException: 404 when the node is unknown.
    """
    node = _find_node(runtime.node_list(), node_id)
    probe = runtime.node_probe.probe(node)
    return NodeTestResult(
        tag=probe.tag, is_alive=probe.is_alive, delay_ms=probe.delay_ms
    )


def _follow_the_nodes(node_list: XrayNodeList, runtime: PanelRuntime) -> None:
    """Switch the proxy off once nothing is left to go out through.

    A proxy with no enabled node is not a setting, it is a configuration that
    cannot be rendered: the balancer would have nothing to select. Leaving the
    switch on made every Apply fail with that in it, and the one way out —
    turning the switch off — was something the page never said.

    Written into `config/` rather than worked around at render time, so the
    panel shows the state the box is actually in.

    Args:
        node_list: The nodes as they are now.
        runtime: The shared runtime.
    """
    if node_list.enabled_nodes:
        return
    routing = runtime.routing()
    if not routing.get("is_proxy_enabled", True):
        return
    routing["is_proxy_enabled"] = False
    write_config("xray/routing.json", routing)


def _find_node(node_list: XrayNodeList, node_id: str) -> XrayNodeConfig:
    for node in node_list.nodes:
        if node.id == node_id:
            return node
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown node {node_id!r}"
    )
