"""Assembling the live statistics frame the status strip and dashboard read."""

from datetime import datetime, timezone

import pytest

from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.models import OutboundTrafficView, StatsFrame
from neutrino_hub.web.stats_collector import PanelStatsCollector

BEATING_MAC = "aa:bb:cc:dd:ee:01"


class StubStats:
    def selected_node_tags(self) -> list[str]:
        return ["node_hk1"]

    def outbound_traffic(self) -> list:
        return []


class StubNodeList:
    enabled_nodes: list = []
    strategy = "leastPing"


class StubNodeProbe:
    def results(self, nodes) -> list:
        del nodes
        return []


class StubNetwork:
    mode = "gateway"
    lan_device_names: list = []


class StubRuntime:
    """The runtime as the panel holds it: built once, at startup.

    It carries a ``devices`` registry the collector used to count from. Kept
    here deliberately: the count must not come back from a registry built
    before the heartbeat it is meant to see.
    """

    def __init__(self):
        self.stats = StubStats()
        self.node_probe = StubNodeProbe()
        self.devices = DeviceRegistry()

    def node_list(self) -> StubNodeList:
        return StubNodeList()

    def proxy_scope(self) -> str:
        return "off"

    def network(self) -> StubNetwork:
        return StubNetwork()

    def uplink_address(self) -> None:
        return None


def frame(*, proxy_scope: str) -> StatsFrame:
    return StatsFrame(
        timestamp="2026-08-28T00:00:00+00:00",
        outbounds=[
            OutboundTrafficView(tag="node_hk1", uplink_bytes=100, downlink_bytes=200),
            OutboundTrafficView(tag="direct", uplink_bytes=5, downlink_bytes=5),
        ],
        proxy_scope=proxy_scope,
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


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` of this test's own, so nothing reads the real one."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def test_an_agent_that_has_just_beaten_counts_in_the_strip(config_dir):
    """The strip's DEVICES chip counted zero on a box whose agent was beating.

    A heartbeat is recorded by the registry serving that request, and the
    collector was counting from one the panel built at startup — which
    answers with the file as it was then, before any agent had beaten.
    """
    DeviceRegistry().issue_client_token(BEATING_MAC)
    runtime = StubRuntime()

    DeviceRegistry().record_heartbeat(
        BEATING_MAC,
        version="0.1.0",
        seen_at=datetime.now(timezone.utc).isoformat(),
    )

    assert PanelStatsCollector(runtime=runtime).collect().agent_device_count == 1


def test_an_agent_that_stopped_beating_leaves_the_count(config_dir):
    """A token alone is an offer, and a stale beat is not a live agent."""
    DeviceRegistry().issue_client_token(BEATING_MAC)
    DeviceRegistry().record_heartbeat(
        BEATING_MAC, version="0.1.0", seen_at="2020-01-01T00:00:00+00:00"
    )

    assert PanelStatsCollector(runtime=StubRuntime()).collect().agent_device_count == 0
