"""Reading traffic counters and probe results out of the running xray.

The ``xray api`` command-line client is used rather than generated gRPC stubs:
the panel polls a handful of counters every couple of seconds, and shelling out
keeps the repo free of protobuf build steps.
"""

import json
from dataclasses import dataclass

from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.xray.constants import (
    XRAY_API_LISTEN,
    XRAY_API_PORT,
    XRAY_BALANCER_TAG,
    XRAY_BINARY,
    XRAY_NODE_TAG_PREFIX,
)


@dataclass
class OutboundTraffic:
    """Cumulative byte counters for one outbound.

    Attributes:
        tag: Outbound tag, for example ``node_hk1``.
        uplink_bytes: Bytes sent through it since xray started.
        downlink_bytes: Bytes received through it since xray started.
    """

    tag: str
    uplink_bytes: int
    downlink_bytes: int


class XrayStatsClient:
    """Queries the xray statistics and observatory APIs."""

    def __init__(self, *, server: str | None = None):
        """
        Args:
            server: ``host:port`` of the API inbound. Defaults to the loopback
                endpoint the renderer configures.
        """
        self._server = server or f"{XRAY_API_LISTEN}:{XRAY_API_PORT}"

    def outbound_traffic(self) -> list[OutboundTraffic]:
        """Read per-outbound byte counters.

        Returns:
            One entry per outbound that has moved traffic, node outbounds and
            the direct outbound alike. Empty when xray is not reachable.
        """
        statistics = self._query_stats()
        totals: dict[str, dict[str, int]] = {}
        for name, value in statistics.items():
            parts = name.split(">>>")
            if len(parts) != 4 or parts[0] != "outbound":
                continue
            tag, direction = parts[1], parts[3]
            totals.setdefault(tag, {"uplink": 0, "downlink": 0})[direction] = value
        return [
            OutboundTraffic(
                tag=tag,
                uplink_bytes=counters.get("uplink", 0),
                downlink_bytes=counters.get("downlink", 0),
            )
            for tag, counters in sorted(totals.items())
        ]

    def selected_node_tags(self) -> list[str]:
        """Read which node outbounds the balancer is currently selecting.

        Parses the text ``xray api bi`` prints — it has no JSON mode, and the
        observatory results behind the choice are not exposed by the API at
        all, so this reports the balancer's decision rather than a measurement.
        Per-node latency comes from :mod:`neutrino_hub.modules.xray.node_probe` instead.

        Returns:
            The selected node tags, best first. Empty when xray is unreachable
            or the balancer has not chosen yet.
        """
        result = run(
            [
                XRAY_BINARY,
                "api",
                "bi",
                f"--server={self._server}",
                XRAY_BALANCER_TAG,
            ],
            is_checked=False,
            timeout_s=10,
        )
        if not result.is_success:
            return []
        return self._parse_selects(result.stdout)

    def _parse_selects(self, output: str) -> list[str]:
        tags: list[str] = []
        is_in_selects = False
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                is_in_selects = stripped.rstrip(":").endswith("Selects")
                continue
            if not is_in_selects or not stripped:
                continue
            # Rows read "<index><whitespace><tag>".
            fields = stripped.split()
            tag = fields[-1]
            if tag.startswith(XRAY_NODE_TAG_PREFIX):
                tags.append(tag)
        return tags

    def _query_stats(self) -> dict[str, int]:
        result = run(
            [XRAY_BINARY, "api", "statsquery", f"--server={self._server}"],
            is_checked=False,
            timeout_s=10,
        )
        if not result.is_success or not result.stdout.strip():
            return {}
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}
        return {
            entry["name"]: int(entry.get("value", 0))
            for entry in payload.get("stat", [])
            if "name" in entry
        }
