"""Assembling the live statistics frame the dashboard shows.

Pulls together the uplink's own byte counters and the host's load, the WAN
address, and, from the proxy's part in the edition table, xray's traffic
counters and what the exit controller measured and pinned. Nothing here
probes or reaches xray for a reading, and a frame is built once a second per
open socket.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import psutil

from neutrino_hub import edition
from neutrino_hub.web.models import OutboundTrafficView, StatsFrame
from neutrino_hub.modules.devices.lan_scan import count_lan_neighbours
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.system.interface_traffic import interface_counters, traffic_interface
from neutrino_hub.web.constants import WEB_PROXY_SCOPE_OFF, WEB_PROXY_SCOPE_UNUSED
from neutrino_hub.web.panel_runtime import PanelRuntime


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
        readings = edition.hook("stats_readings")
        proxy = readings(self._runtime) if readings is not None else {}
        outbounds = proxy.get("outbounds", [])
        scope = self._runtime.proxy_scope()
        network = self._runtime.network()
        interface_name, rx_bytes_per_s, tx_bytes_per_s = self._interface_rates(network)

        return StatsFrame(
            **proxy,
            timestamp=datetime.now(timezone.utc).isoformat(),
            cpu_percent=psutil.cpu_percent(interval=None),
            memory_percent=psutil.virtual_memory().percent,
            uptime_s=int(time.time() - psutil.boot_time()),
            wan_address=self._runtime.uplink_address(),
            total_uplink_bytes=sum(entry.uplink_bytes for entry in outbounds),
            total_downlink_bytes=sum(entry.downlink_bytes for entry in outbounds),
            interface_name=interface_name,
            interface_rx_bytes_per_s=rx_bytes_per_s,
            interface_tx_bytes_per_s=tx_bytes_per_s,
            proxy_scope=scope,
            network_mode=network.mode,
            agent_device_count=len(self._runtime.agent_sessions.keys()),
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
        is_exit_tag = edition.hook("exit_tag_filter")
        if is_exit_tag is None:
            return []
        if frame.proxy_scope in (WEB_PROXY_SCOPE_OFF, WEB_PROXY_SCOPE_UNUSED):
            return []
        used = [
            entry
            for entry in frame.outbounds
            if entry.uplink_bytes + entry.downlink_bytes > 0 and is_exit_tag(entry.tag)
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
