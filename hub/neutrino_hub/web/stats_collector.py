"""Assembling the live statistics frame the dashboard shows.

Pulls together four sources: xray's traffic counters, what the exit controller
measured and pinned, the uplink's own byte counters and the host's load, and
the WAN address. Nothing here probes or reaches xray for a reading: the
controller's windows and its status are already in memory, and a frame is
built once a second per open socket.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import psutil

from neutrino_hub.web.models import (
    NodeProbeView,
    OutboundTrafficView,
    StatsFrame,
)
from neutrino_hub.modules.devices.lan_scan import count_lan_neighbours
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.system.interface_traffic import interface_counters, traffic_interface
from neutrino_hub.web.constants import WEB_PROXY_SCOPE_OFF, WEB_PROXY_SCOPE_UNUSED
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.modules.xray.constants import XRAY_DIRECT_TAG, XRAY_NODE_TAG_PREFIX
from neutrino_hub.modules.xray.node_health import XrayNodeHealth


def _node_readings(outbounds: list, probes: list) -> dict:
    """What the nodes panel draws per node, by outbound tag.

    Args:
        outbounds: The traffic counters this cycle read.
        probes: The measurements this cycle read.

    Returns:
        Tag to ``(traffic, measurement)``, either of which is None where this
        cycle has nothing for that tag.
    """
    traffic = {
        entry.tag: (entry.uplink_bytes, entry.downlink_bytes) for entry in outbounds
    }
    probed = {probe.tag: probe.model_dump() for probe in probes}
    return {
        tag: (traffic.get(tag), probed.get(tag))
        for tag in sorted(set(traffic) | set(probed))
    }


def _node_probe_views(node_list, healths: dict, exit_tag: str) -> list:
    """Every node's latest measurement, in the order the list holds them.

    Args:
        node_list: The nodes as ``config/`` holds them.
        healths: Each node's window, keyed by outbound tag.
        exit_tag: The outbound the hub has pinned.

    Returns:
        One view per node, switched on or not.
    """
    views = []
    for node in node_list.nodes:
        # A node nobody has measured reads as an empty window, which is what
        # it is: no number at all rather than a zero.
        health = healths.get(node.tag) or XrayNodeHealth(tag=node.tag)
        views.append(
            NodeProbeView(
                tag=node.tag,
                is_alive=health.is_alive,
                is_enabled=node.is_enabled,
                is_selected=node.tag == exit_tag,
                connect_ms=health.connect_ms,
                request_ms=health.request_ms,
                probed_at=health.probed_at.isoformat() if health.probed_at else "",
                success_rate=health.success_rate,
            )
        )
    return views


def _moved_bytes(entry: OutboundTrafficView) -> int:
    """How much one outbound carried, for ordering the busiest first."""
    return entry.uplink_bytes + entry.downlink_bytes


@dataclass
class InterfaceSample:
    """One reading of an interface's counters, kept to rate the next one.

    Attributes:
        interface_name: The interface the counters were read from.
        received_bytes: Its receive counter at that moment.
        sent_bytes: Its transmit counter at that moment.
        taken_at: A monotonic stamp, so a clock the box corrects mid-stream
            cannot produce a negative interval.
    """

    interface_name: str
    received_bytes: int
    sent_bytes: int
    taken_at: float


class PanelStatsCollector:
    """Builds one :class:`StatsFrame` per call."""

    def __init__(self, *, runtime: PanelRuntime):
        """
        Args:
            runtime: The shared runtime, for the stats client and WAN reader.
        """
        self._runtime = runtime
        # The uplink's counters are cumulative, so a rate needs the frame
        # before it. One collector lives as long as one open socket, and the
        # first frame it sends therefore has nothing to subtract.
        self._previous_sample: InterfaceSample | None = None

    def collect(self) -> StatsFrame:
        """Read every source and assemble a frame.

        Returns:
            The current frame. Sources that fail contribute zeros rather than
            raising, so a stopped xray still leaves a usable dashboard.
        """
        outbounds = self._runtime.stats.outbound_traffic()
        node_list = self._runtime.node_list()
        controller = self._runtime.exit_controller
        exit_status = controller.status
        probes = _node_probe_views(
            node_list, controller.healths(), exit_status.exit_tag
        )

        total_uplink = sum(entry.uplink_bytes for entry in outbounds)
        total_downlink = sum(entry.downlink_bytes for entry in outbounds)
        scope = self._runtime.proxy_scope()
        network = self._runtime.network()
        interface_name, rx_bytes_per_s, tx_bytes_per_s = self._interface_rates(network)
        # The nodes panel draws these readings and nothing else refreshes
        # them, so this cycle is what tells it they moved.
        self._runtime.publish_node_readings(_node_readings(outbounds, probes))

        return StatsFrame(
            timestamp=datetime.now(timezone.utc).isoformat(),
            outbounds=[
                OutboundTrafficView(
                    tag=entry.tag,
                    uplink_bytes=entry.uplink_bytes,
                    downlink_bytes=entry.downlink_bytes,
                )
                for entry in outbounds
            ],
            nodes=probes,
            cpu_percent=psutil.cpu_percent(interval=None),
            memory_percent=psutil.virtual_memory().percent,
            uptime_s=int(time.time() - psutil.boot_time()),
            wan_address=self._runtime.uplink_address(),
            total_uplink_bytes=total_uplink,
            total_downlink_bytes=total_downlink,
            interface_name=interface_name,
            interface_rx_bytes_per_s=rx_bytes_per_s,
            interface_tx_bytes_per_s=tx_bytes_per_s,
            proxy_scope=scope,
            network_mode=network.mode,
            agent_device_count=len(self._runtime.agent_sessions.keys()),
            exit_tag=exit_status.exit_tag,
            exit_since=(exit_status.since.isoformat() if exit_status.since else ""),
            is_wan_reachable=exit_status.is_wan_reachable,
            is_xray_reachable=exit_status.is_xray_reachable,
            is_in_sync=exit_status.is_in_sync,
            enabled_node_count=len(node_list.enabled_nodes),
            lan_device_count=count_lan_neighbours(network.lan_device_names),
        )

    def active_exit_tags(self, frame: StatsFrame) -> list[str]:
        """Report which exits are in use, busiest first.

        Two sources are combined. Outbounds that have moved bytes are certainly
        in use. The pinned exit is added even at zero bytes, since it is the
        one the next request will take.

        Args:
            frame: A collected frame.

        Returns:
            Node tags, plus the direct outbound when it has carried traffic.
            Nothing at all while the proxy is off or nothing is sent to it:
            there is no exit then, and naming the last one used would be a
            stale answer to "where is my traffic going".
        """
        if frame.proxy_scope in (WEB_PROXY_SCOPE_OFF, WEB_PROXY_SCOPE_UNUSED):
            return []
        used = [
            entry
            for entry in frame.outbounds
            if entry.uplink_bytes + entry.downlink_bytes > 0
            and (
                entry.tag.startswith(XRAY_NODE_TAG_PREFIX)
                or entry.tag == XRAY_DIRECT_TAG
            )
        ]
        used.sort(key=_moved_bytes, reverse=True)
        tags = [entry.tag for entry in used]
        if frame.exit_tag and frame.exit_tag not in tags:
            tags.append(frame.exit_tag)
        return tags

    def _interface_rates(self, network: RouterNetworkConfig) -> tuple[str, int, int]:
        """Rate the uplink's counters against the previous frame's.

        Args:
            network: The parsed router configuration, for which interface to
                read.

        Returns:
            The interface name and its receive and transmit rates in bytes per
            second. Zero rates whenever there is nothing honest to divide: the
            first frame, an interface that has changed under the socket, a
            counter that went backwards over a reboot or a driver reload, and
            an interface with no counters to read at all.
        """
        name = traffic_interface(network=network)
        previous = self._previous_sample
        counters = interface_counters(name)
        if counters is None:
            self._previous_sample = None
            return name, 0, 0
        received_bytes, sent_bytes = counters
        self._previous_sample = InterfaceSample(
            interface_name=name,
            received_bytes=received_bytes,
            sent_bytes=sent_bytes,
            taken_at=time.monotonic(),
        )
        if (
            previous is None
            or previous.interface_name != name
            or received_bytes < previous.received_bytes
            or sent_bytes < previous.sent_bytes
        ):
            return name, 0, 0
        elapsed_s = self._previous_sample.taken_at - previous.taken_at
        if elapsed_s <= 0:
            return name, 0, 0
        return (
            name,
            int((received_bytes - previous.received_bytes) / elapsed_s),
            int((sent_bytes - previous.sent_bytes) / elapsed_s),
        )
