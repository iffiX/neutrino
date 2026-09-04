"""Assembling the live statistics frame the dashboard shows.

Pulls together three sources: xray's traffic counters and latency probes, the
host's own load, and the WAN address.
"""

import time
from datetime import datetime, timezone

import psutil

from neutrino_hub.web.models import (
    NodeProbeView,
    OutboundTrafficView,
    StatsFrame,
)
from neutrino_hub.modules.devices.lan_scan import count_lan_neighbours
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.constants import WEB_PROXY_SCOPE_OFF, WEB_PROXY_SCOPE_UNUSED
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.modules.xray.constants import XRAY_DIRECT_TAG, XRAY_NODE_TAG_PREFIX


class PanelStatsCollector:
    """Builds one :class:`StatsFrame` per call."""

    def __init__(self, *, runtime: PanelRuntime):
        """
        Args:
            runtime: The shared runtime, for the stats client and WAN reader.
        """
        self._runtime = runtime

    def collect(self) -> StatsFrame:
        """Read every source and assemble a frame.

        Returns:
            The current frame. Sources that fail contribute zeros rather than
            raising, so a stopped xray still leaves a usable dashboard.
        """
        # Read here rather than held on the runtime: a registry answers from
        # the file as it was when it was built, and the heartbeats that set
        # last-seen are written by the registry serving each agent request.
        devices = DeviceRegistry().all_stored()
        outbounds = self._runtime.stats.outbound_traffic()
        node_list = self._runtime.node_list()
        nodes = node_list.enabled_nodes
        probes = self._runtime.node_probe.results(nodes)

        total_uplink = sum(entry.uplink_bytes for entry in outbounds)
        total_downlink = sum(entry.downlink_bytes for entry in outbounds)
        scope = self._runtime.proxy_scope()
        network = self._runtime.network()

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
            nodes=[
                NodeProbeView(
                    tag=probe.tag, is_alive=probe.is_alive, delay_ms=probe.delay_ms
                )
                for probe in probes
            ],
            cpu_percent=psutil.cpu_percent(interval=None),
            memory_percent=psutil.virtual_memory().percent,
            uptime_s=int(time.time() - psutil.boot_time()),
            wan_address=self._runtime.uplink_address(),
            total_uplink_bytes=total_uplink,
            total_downlink_bytes=total_downlink,
            proxy_scope=scope,
            network_mode=network.mode,
            agent_device_count=sum(1 for device in devices if device.is_agent_online),
            balancer_strategy=node_list.strategy,
            enabled_node_count=len(nodes),
            lan_device_count=count_lan_neighbours(network.lan_device_names),
        )

    def active_exit_tags(self, frame: StatsFrame) -> list[str]:
        """Report which exits are in use, busiest first.

        Two sources are combined. Outbounds that have moved bytes are certainly
        in use. The balancer's current selection is added even at zero bytes,
        because a freshly chosen node is the exit the next request will take —
        showing nothing until traffic flows would make an idle gateway look
        unconfigured.

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
        used.sort(
            key=lambda entry: entry.uplink_bytes + entry.downlink_bytes, reverse=True
        )
        tags = [entry.tag for entry in used]
        for tag in self._runtime.stats.selected_node_tags():
            if tag not in tags:
                tags.append(tag)
        return tags
