"""Measuring whether each node is reachable, and how fast.

xray's own observatory drives the balancer, but its API only reports which node
the balancer currently selects — there is no per-node latency to read back. The
panel needs a number for every node, so it measures them here instead: a TCP
connect to the node's own address and port, timed.

That measures the path to the node endpoint rather than a full proxy round
trip. It is the right thing to show anyway, because it answers the question the
Nodes tab is actually asking — can this box reach this node from where it is
sitting, and how far away is it.
"""

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from neutrino_hub.modules.xray.node_config import XrayNodeConfig

PROBE_TIMEOUT_S = 5.0
PROBE_CACHE_TTL_S = 30.0
PROBE_WORKER_LIMIT = 8


@dataclass
class NodeProbeResult:
    """One node's measured reachability.

    Attributes:
        tag: The node's outbound tag.
        is_alive: Whether the connect succeeded within the timeout.
        delay_ms: Connect time in milliseconds, or None when it failed.
    """

    tag: str
    is_alive: bool
    delay_ms: int | None


class XrayNodeProbe:
    """Probes nodes and caches the results for a short while.

    The cache matters: the dashboard pushes a frame every two seconds, and
    opening six TCP connections that often would be both wasteful and, on a
    metered upstream, rude.
    """

    def __init__(self, *, timeout_s: float = PROBE_TIMEOUT_S):
        """
        Args:
            timeout_s: How long to wait for a connect before calling the node
                unreachable.
        """
        self._timeout_s = timeout_s
        self._cache: dict[str, NodeProbeResult] = {}
        # None, not zero: `time.monotonic()` on Linux counts from boot, so a
        # panel that starts early in one is younger than the cache's own age
        # and never probes at all — every node reads unreachable until the
        # machine has been up for longer than the window.
        self._probed_at: float | None = None

    def results(self, nodes: list[XrayNodeConfig]) -> list[NodeProbeResult]:
        """Read every node's reachability, probing only when the cache is stale.

        Args:
            nodes: The nodes to report on.

        Returns:
            One result per node, in the order given.
        """
        if (
            self._probed_at is None
            or time.monotonic() - self._probed_at > PROBE_CACHE_TTL_S
        ):
            self.refresh(nodes)
        return [
            self._cache.get(node.tag, NodeProbeResult(node.tag, False, None))
            for node in nodes
        ]

    def refresh(self, nodes: list[XrayNodeConfig]) -> list[NodeProbeResult]:
        """Probe every node now, ignoring the cache.

        Args:
            nodes: The nodes to probe.

        Returns:
            One fresh result per node.
        """
        if not nodes:
            self._probed_at = time.monotonic()
            return []
        worker_count = min(PROBE_WORKER_LIMIT, len(nodes))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(self.probe, nodes))
        self._cache = {result.tag: result for result in results}
        self._probed_at = time.monotonic()
        return results

    def probe(self, node: XrayNodeConfig) -> NodeProbeResult:
        """Time a TCP connect to one node.

        Args:
            node: The node to reach.

        Returns:
            The measurement. A refused connection, a timeout, and a name that
            does not resolve all read as unreachable rather than raising, since
            every one of them means the same thing to the operator.
        """
        started_at = time.monotonic()
        try:
            with socket.create_connection(
                (node.address, node.port), timeout=self._timeout_s
            ):
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
        except OSError:
            return NodeProbeResult(tag=node.tag, is_alive=False, delay_ms=None)
        return NodeProbeResult(tag=node.tag, is_alive=True, delay_ms=elapsed_ms)
