"""The Dashboard tab: live summary, traffic history, and the DNS log."""

from fastapi import APIRouter, Depends, HTTPException, status

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

# The windows the history chart offers, the same four the AI usage block has.
HISTORY_RANGE_DAY = "day"
HISTORY_RANGE_WEEK = "week"
HISTORY_RANGE_MONTH = "month"
HISTORY_RANGE_YEAR = "year"
HISTORY_RANGES = (
    HISTORY_RANGE_DAY,
    HISTORY_RANGE_WEEK,
    HISTORY_RANGE_MONTH,
    HISTORY_RANGE_YEAR,
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
    range: str = HISTORY_RANGE_MONTH, runtime: PanelRuntime = Depends(get_runtime)
) -> TrafficHistory:
    """Read long-term WAN traffic history from vnstat.

    Args:
        range: One of ``day`` (24 hours), ``week`` (7 days), ``month`` (30
            days) or ``year`` (12 months).
        runtime: The shared runtime.

    Returns:
        The range's buckets oldest first, and today's total beside them.

    Raises:
        HTTPException: 400 when the range is not one of the four.
    """
    if range not in HISTORY_RANGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_range", "params": {"range": range}},
        )
    uplinks = runtime.network().wan_device_names
    reader = VnstatHistoryReader(interface=uplinks[0] if uplinks else "")
    today = reader.daily(day_count=1)
    return TrafficHistory(
        range=range,
        samples=[_to_view(sample) for sample in _buckets(reader, range)],
        today=_to_view(today[-1]) if today else None,
    )


def _buckets(reader: VnstatHistoryReader, range: str) -> list:
    if range == HISTORY_RANGE_DAY:
        return reader.hourly(hour_count=24)
    if range == HISTORY_RANGE_WEEK:
        return reader.daily(day_count=7)
    if range == HISTORY_RANGE_YEAR:
        return reader.monthly(month_count=12)
    return reader.daily(day_count=30)


def _to_view(sample) -> TrafficSample:
    return TrafficSample(
        label=sample.label,
        received_bytes=sample.received_bytes,
        sent_bytes=sample.sent_bytes,
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
