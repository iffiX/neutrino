"""Assembling the live statistics frame the status strip and dashboard read."""

from neutrino_hub.web.models import OutboundTrafficView, StatsFrame
from neutrino_hub.web.stats_collector import PanelStatsCollector


class StubStats:
    def selected_node_tags(self) -> list[str]:
        return ["node_hk1"]


class StubRuntime:
    def __init__(self):
        self.stats = StubStats()


def frame(*, proxy_scope: str) -> StatsFrame:
    return StatsFrame(
        timestamp="2026-08-28T00:00:00+00:00",
        outbounds=[
            OutboundTrafficView(tag="node_hk1", uplink_bytes=100, downlink_bytes=200),
            OutboundTrafficView(tag="direct", uplink_bytes=5, downlink_bytes=5),
        ],
        proxy_scope=proxy_scope,
        is_proxy_enabled=proxy_scope != "off",
    )


def test_the_busiest_exits_are_named_while_the_proxy_carries_traffic():
    collector = PanelStatsCollector(runtime=StubRuntime())

    assert collector.active_exit_tags(frame(proxy_scope="lan")) == [
        "node_hk1",
        "direct",
    ]


def test_no_exit_is_named_while_the_proxy_is_out_of_the_path():
    """The counters are cumulative, so the last exit used is still in them.

    Reporting it would answer "where is my traffic going" with somewhere it is
    demonstrably not going: the firewall has stopped diverting.
    """
    collector = PanelStatsCollector(runtime=StubRuntime())

    assert collector.active_exit_tags(frame(proxy_scope="off")) == []


def test_no_exit_is_named_while_nothing_is_sent_to_the_proxy():
    """On but unused is a proxy with no traffic to have an exit for."""
    collector = PanelStatsCollector(runtime=StubRuntime())

    assert collector.active_exit_tags(frame(proxy_scope="unused")) == []
