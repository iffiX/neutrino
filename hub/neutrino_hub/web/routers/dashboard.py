"""The Dashboard tab: live summary, traffic history, and the DNS log."""

from fastapi import APIRouter, Depends

from neutrino_hub.system.vnstat_history import VnstatHistoryReader
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.dns_log import DnsLogReader
from neutrino_hub.web.models import (
    DashboardSummary,
    DnsLogEntry,
    TrafficHistory,
    TrafficSample,
)
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.stats_collector import PanelStatsCollector

router = APIRouter(
    prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_session)]
)


@router.get("/summary", response_model=DashboardSummary)
def summary(runtime: PanelRuntime = Depends(get_runtime)) -> DashboardSummary:
    """Read everything the dashboard needs on first paint.

    Args:
        runtime: The shared runtime.

    Returns:
        The current stats frame plus the counts shown beside it.
    """
    collector = PanelStatsCollector(runtime=runtime)
    frame = collector.collect()
    return DashboardSummary(
        stats=frame,
        active_exit_tags=collector.active_exit_tags(frame),
        dns_query_count=DnsLogReader().query_count(),
        lan_device_count=frame.lan_device_count,
    )


@router.get("/history", response_model=TrafficHistory)
def history(
    days: int = 30, runtime: PanelRuntime = Depends(get_runtime)
) -> TrafficHistory:
    """Read long-term WAN traffic history from vnstat.

    Args:
        days: How many days to return.
        runtime: The shared runtime.

    Returns:
        Daily totals, oldest first.
    """
    uplinks = runtime.network().wan_device_names
    reader = VnstatHistoryReader(interface=uplinks[0] if uplinks else "")
    return TrafficHistory(
        samples=[
            TrafficSample(
                label=sample.label,
                received_bytes=sample.received_bytes,
                sent_bytes=sample.sent_bytes,
            )
            for sample in reader.daily(day_count=days)
        ]
    )


@router.get("/dns_log", response_model=list[DnsLogEntry])
def dns_log(tail: int = 200) -> list[DnsLogEntry]:
    """Read the most recent DNS queries.

    Args:
        tail: How many entries to return.

    Returns:
        Newest first.
    """
    return DnsLogReader().tail(entry_limit=tail)
