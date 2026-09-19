"""Assembling the live statistics frame the status strip and dashboard read."""

from datetime import datetime, timezone

import pytest

from tests.conftest import FakeChannelSessions

from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.xray.exit_controller import XrayExitStatus
from neutrino_hub.modules.xray.node_config import XrayNodeConfig
from neutrino_hub.modules.xray.node_health import XrayNodeHealth, XrayNodeSample
from neutrino_hub.modules.xray.stats_client import OutboundTraffic
from neutrino_hub.web import stats_collector
from neutrino_hub.web.models import NodeProbeView, OutboundTrafficView, StatsFrame
from neutrino_hub.web.stats_collector import PanelStatsCollector

BEATING_DEVICE = "device-one"
UPLINK = "enp2s0"
PINNED_AT = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
NODE = XrayNodeConfig(
    id="hk1",
    name="Tokyo",
    address="203.0.113.10",
    is_enabled=True,
    protocol="shadowsocks",
    port=5800,
    method="aes-256-gcm",
)


class StubStats:
    def outbound_traffic(self) -> list:
        return [OutboundTraffic(tag="node_hk1", uplink_bytes=11, downlink_bytes=22)]


class StubNodeList:
    nodes: list = [NODE]
    enabled_nodes: list = [NODE]


class StubExitController:
    """The controller as the collector reads it: a status and the windows."""

    def __init__(self, *, status=None, healths=None):
        self.status = status or XrayExitStatus(exit_tag="node_hk1", since=PINNED_AT)
        self._healths = healths or {}

    def healths(self) -> dict:
        return dict(self._healths)


class StubNetwork:
    mode = "gateway"
    lan_device_names: list = []
    wan_device_names: list = [UPLINK]


class StubClock:
    """The clock the collector rates against, stepped by hand."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now


class StubUplink:
    """The uplink as ``/proc`` would report it, under the test's control."""

    def __init__(self):
        self.name = UPLINK
        self.counters: tuple[int, int] | None = (1_000_000, 200_000)
        self.clock = StubClock()

    def resolve(self, *, network) -> str:
        del network
        return self.name

    def read(self, name: str) -> tuple[int, int] | None:
        del name
        return self.counters


class StubRuntime:
    """The runtime as the panel holds it: built once, at startup."""

    def __init__(self, online=(), controller=None):
        self.stats = StubStats()
        self.exit_controller = controller or StubExitController()
        self.agent_sessions = FakeChannelSessions(online)
        # Every node reading this collector published, newest last.
        self.node_readings: list = []

    def publish_node_readings(self, readings: dict) -> None:
        self.node_readings.append(readings)

    def node_list(self) -> StubNodeList:
        return StubNodeList()

    def proxy_scope(self) -> str:
        return "off"

    def network(self) -> StubNetwork:
        return StubNetwork()

    def uplink_address(self) -> None:
        return None


def frame(*, proxy_scope: str, exit_tag: str = "node_hk1") -> StatsFrame:
    return StatsFrame(
        timestamp="2026-08-28T00:00:00+00:00",
        outbounds=[
            OutboundTrafficView(tag="node_hk1", uplink_bytes=100, downlink_bytes=200),
            OutboundTrafficView(tag="direct", uplink_bytes=5, downlink_bytes=5),
        ],
        proxy_scope=proxy_scope,
        exit_tag=exit_tag,
    )


def test_the_busiest_exits_are_named_while_the_proxy_carries_traffic():
    collector = PanelStatsCollector(runtime=StubRuntime())

    assert collector.active_exit_tags(frame(proxy_scope="lan")) == [
        "node_hk1",
        "direct",
    ]


def test_the_pinned_exit_is_named_even_before_it_has_carried_a_byte():
    """A freshly pinned node is where the next request goes, and a gateway
    that names nothing until traffic flows reads as unconfigured."""
    collector = PanelStatsCollector(runtime=StubRuntime())

    assert collector.active_exit_tags(frame(proxy_scope="lan", exit_tag="direct")) == [
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


def test_an_agent_holding_a_socket_counts_in_the_strip(config_dir):
    """The strip's DEVICES chip counts the agents with a live channel."""
    runtime = StubRuntime(online=[BEATING_DEVICE])

    assert PanelStatsCollector(runtime=runtime).collect().agent_device_count == 1


def test_an_agent_without_a_socket_leaves_the_count(config_dir):
    """A token alone is an offer, and a closed socket is not a live agent."""
    registry = DeviceRegistry()
    registry.issue_token(registry.create("box").id)

    assert PanelStatsCollector(runtime=StubRuntime()).collect().agent_device_count == 0


@pytest.fixture
def uplink(monkeypatch, config_dir) -> StubUplink:
    """An uplink and a clock the test moves, in place of ``/proc``."""
    del config_dir
    stub = StubUplink()
    monkeypatch.setattr(stats_collector, "traffic_interface", stub.resolve)
    monkeypatch.setattr(stats_collector, "interface_counters", stub.read)
    monkeypatch.setattr(stats_collector, "time", stub.clock)
    return stub


def test_the_first_frame_of_a_socket_has_no_rate_to_report(uplink):
    """The counters are cumulative, so the first one has nothing to subtract."""
    pushed = PanelStatsCollector(runtime=StubRuntime()).collect()

    assert pushed.interface_name == UPLINK
    assert (pushed.interface_rx_bytes_per_s, pushed.interface_tx_bytes_per_s) == (0, 0)


def test_the_uplink_reports_what_it_moved_between_two_frames(uplink):
    collector = PanelStatsCollector(runtime=StubRuntime())
    collector.collect()
    uplink.clock.now += 2.0
    uplink.counters = (1_000_000 + 2_400, 200_000 + 800)

    pushed = collector.collect()

    assert (pushed.interface_rx_bytes_per_s, pushed.interface_tx_bytes_per_s) == (
        1_200,
        400,
    )


def test_a_counter_that_went_backwards_reports_no_rate(uplink):
    """A reboot or a driver reload restarts the counters at zero."""
    collector = PanelStatsCollector(runtime=StubRuntime())
    collector.collect()
    uplink.clock.now += 2.0
    uplink.counters = (0, 0)

    pushed = collector.collect()

    assert (pushed.interface_rx_bytes_per_s, pushed.interface_tx_bytes_per_s) == (0, 0)


def test_a_changed_uplink_reports_no_rate_for_that_tick(uplink):
    """Two interfaces' counters have nothing to do with each other."""
    collector = PanelStatsCollector(runtime=StubRuntime())
    collector.collect()
    uplink.clock.now += 2.0
    uplink.name = "wlp3s0"
    uplink.counters = (5, 5)

    pushed = collector.collect()

    assert pushed.interface_name == "wlp3s0"
    assert (pushed.interface_rx_bytes_per_s, pushed.interface_tx_bytes_per_s) == (0, 0)


def test_an_uplink_with_no_counters_reports_no_rate(uplink):
    """A box with neither a WAN role nor a default route names no interface."""
    uplink.name = ""
    uplink.counters = None

    pushed = PanelStatsCollector(runtime=StubRuntime()).collect()

    assert pushed.interface_name == ""
    assert (pushed.interface_rx_bytes_per_s, pushed.interface_tx_bytes_per_s) == (0, 0)


def test_the_proxy_totals_are_left_alone(uplink):
    """The Proxy page's story is xray's own counters, and they still add up."""
    pushed = PanelStatsCollector(runtime=StubRuntime()).collect()

    assert (pushed.total_uplink_bytes, pushed.total_downlink_bytes) == (11, 22)


def test_each_cycle_hands_on_what_the_nodes_panel_draws(uplink):
    """The panel has no other source for a node's latency or its traffic."""
    del uplink
    runtime = StubRuntime()

    PanelStatsCollector(runtime=runtime).collect()

    assert runtime.node_readings == [
        {
            "node_hk1": (
                (11, 22),
                NodeProbeView(
                    tag="node_hk1",
                    is_alive=False,
                    is_enabled=True,
                    is_selected=True,
                ).model_dump(),
            )
        }
    ]


def test_a_measured_node_reaches_the_frame_with_what_it_measured(uplink):
    """The nodes panel reads these off the frame rather than asking again."""
    del uplink
    health = XrayNodeHealth(
        tag="node_hk1",
        samples=[XrayNodeSample(at=PINNED_AT, connect_ms=12, request_ms=140)],
        probed_at=PINNED_AT,
        succeeded_at=PINNED_AT,
    )
    runtime = StubRuntime(controller=StubExitController(healths={"node_hk1": health}))

    pushed = PanelStatsCollector(runtime=runtime).collect()

    assert pushed.nodes == [
        NodeProbeView(
            tag="node_hk1",
            is_alive=True,
            is_enabled=True,
            is_selected=True,
            connect_ms=12,
            request_ms=140,
            probed_at=PINNED_AT.isoformat(),
            success_rate=1.0,
        )
    ]


def test_the_frame_carries_the_pinned_exit_and_when_it_was_pinned(uplink):
    """The strip names one exit, and it is the hub's pin rather than a guess
    from the counters."""
    del uplink

    pushed = PanelStatsCollector(runtime=StubRuntime()).collect()

    assert pushed.exit_tag == "node_hk1"
    assert pushed.exit_since == PINNED_AT.isoformat()


def test_a_round_that_found_nothing_answering_says_so_on_the_frame(uplink):
    """A node cannot be blamed for a WAN that is down or an xray that is not
    answering, so the strip is told which of the two it is."""
    del uplink
    controller = StubExitController(
        status=XrayExitStatus(
            exit_tag="",
            is_wan_reachable=False,
            is_xray_reachable=False,
            is_in_sync=False,
        )
    )

    pushed = PanelStatsCollector(runtime=StubRuntime(controller=controller)).collect()

    assert (
        pushed.exit_tag,
        pushed.exit_since,
        pushed.is_wan_reachable,
        pushed.is_xray_reachable,
        pushed.is_in_sync,
    ) == ("", "", False, False, False)
