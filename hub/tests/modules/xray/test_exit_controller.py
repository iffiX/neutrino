"""What moves the exit, and the four things that must never move it.

A node a millisecond faster, a node nobody has measured, an uplink that is
down, and an xray that is not answering: each of them used to be a reason to
re-pick, and each of them is a reason to hold still.
"""

from datetime import datetime, timedelta, timezone

import pytest

from neutrino_hub.modules.xray import exit_controller
from neutrino_hub.modules.xray.constants import (
    XRAY_DIRECT_TAG,
    XRAY_EXIT_DWELL_S,
    XRAY_EXIT_REASSERT_TRIES,
)
from neutrino_hub.modules.xray.exit_controller import XrayExitController
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.modules.xray.node_health import XrayNodeHealthStore
from neutrino_hub.modules.xray.node_probe import XrayNodeMeasurement

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
PROBE_URL = "http://probe.example.net/generate_204"
REFERENCE_URL = "http://reference.example.net/connecttest"
RENDERED = {
    "outbounds": [
        {"tag": "node_a"},
        {"tag": "node_b"},
        {"tag": XRAY_DIRECT_TAG},
    ]
}


def node_list(*, is_b_enabled: bool = True) -> XrayNodeList:
    """Two Shadowsocks nodes, the second switchable."""
    return XrayNodeList.from_dict(
        {
            "nodes": [
                {
                    "id": "a",
                    "name": "A",
                    "address": "203.0.113.10",
                    "is_enabled": True,
                    "protocol": "shadowsocks",
                    "shadowsocks": {"port": 5800, "method": "aes-256-gcm"},
                },
                {
                    "id": "b",
                    "name": "B",
                    "address": "203.0.113.11",
                    "is_enabled": is_b_enabled,
                    "protocol": "shadowsocks",
                    "shadowsocks": {"port": 5800, "method": "aes-256-gcm"},
                },
            ],
            "balancer": {
                "strategy": "roundRobin",
                "probe_url": PROBE_URL,
                "reference_url": REFERENCE_URL,
                "probe_interval_s": 60,
            },
        }
    )


def measured(tag: str, request_ms: "int | None", *, is_xray_reachable: bool = True):
    """One measurement as the probe would hand it back."""
    return XrayNodeMeasurement(
        tag=tag,
        connect_ms=10 if request_ms is not None else None,
        request_ms=request_ms,
        is_xray_reachable=is_xray_reachable,
    )


class _StubProbe:
    """A probe whose answer per node a test writes down."""

    def __init__(self, answers: dict, *, reference_ms: "int | None" = 12):
        self.probed: list = []
        self.reference_calls = 0
        self._answers = {tag: list(value) for tag, value in answers.items()}
        self._reference_ms = reference_ms

    def probe(self, node, *, url: str):
        assert url == PROBE_URL
        self.probed.append(node.tag)
        answers = self._answers[node.tag]
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def probe_reference(self, url: str) -> "int | None":
        assert url == REFERENCE_URL
        self.reference_calls += 1
        return self._reference_ms


class _StubApi:
    """xray as the controller drives it: the override and the two listings."""

    def __init__(
        self,
        *,
        override: str = "",
        outbounds=("node_a", "node_b", XRAY_DIRECT_TAG),
        is_reachable: bool = True,
        refusals: int = 0,
    ):
        self.override = override
        self.set_calls: list = []
        self.clear_calls = 0
        self.outbounds = list(outbounds)
        self.is_reachable = is_reachable
        self.refusals = refusals

    def override_target(self) -> str:
        self._answer_or_refuse()
        return self.override

    def set_override(self, tag: str) -> None:
        self._answer_or_refuse()
        self.set_calls.append(tag)
        self.override = tag

    def clear_override(self) -> None:
        self._answer_or_refuse()
        self.clear_calls += 1
        self.override = ""

    def inbound_tags(self) -> list:
        self._answer_or_refuse()
        return ["api_in", "socks_probe_in"]

    def outbound_tags(self) -> list:
        self._answer_or_refuse()
        return list(self.outbounds)

    def _answer_or_refuse(self) -> None:
        if self.refusals > 0:
            self.refusals -= 1
            raise ConnectionError("xray api bi exited 1: connection refused")
        if not self.is_reachable:
            raise ConnectionError("xray api bi exited 1: connection refused")


class _Box:
    """One controller and everything it is wired to."""

    def __init__(
        self,
        tmp_path,
        *,
        probe,
        api,
        nodes: "XrayNodeList | None" = None,
        routing: "dict | None" = None,
        rendered: "dict | None" = None,
    ):
        self.probe = probe
        self.api = api
        self.store = XrayNodeHealthStore(path=tmp_path / "xray_node_health.json")
        self.nodes = nodes if nodes is not None else node_list()
        self.routing = routing if routing is not None else {}
        self.rendered = rendered if rendered is not None else RENDERED
        self.changes: list = []
        self.mismatches: list = []
        self.controller = XrayExitController(
            probe=probe,
            store=self.store,
            api=api,
            node_list_of=self._node_list,
            routing_of=self._routing,
            rendered_config_of=self._rendered,
            on_change=self.changes.append,
            on_out_of_sync=self.mismatches.append,
        )

    def seed(self, tag: str, *values: "int | None") -> None:
        """Put a window behind a node without measuring anything."""
        for request_ms in values:
            self.store.record(
                tag,
                connect_ms=10 if request_ms is not None else None,
                request_ms=request_ms,
                now=datetime.now(timezone.utc),
            )

    def pin(self, tag: str, *, held_s: float = 0.0) -> None:
        """Say the exit is already on one node, and for how long."""
        self.store.set_exit(
            tag, now=datetime.now(timezone.utc) - timedelta(seconds=held_s)
        )
        self.api.override = tag

    def _node_list(self) -> XrayNodeList:
        return self.nodes

    def _routing(self) -> dict:
        return self.routing

    def _rendered(self) -> dict:
        return self.rendered


def test_the_first_round_pins_the_faster_node(tmp_path):
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {"node_a": [measured("node_a", 40)], "node_b": [measured("node_b", 300)]}
        ),
        api=_StubApi(),
    )

    status = box.controller.refresh()

    assert box.api.set_calls == ["node_a"]
    assert status.exit_tag == "node_a"
    assert box.store.exit_tag == "node_a"
    assert [change.exit_tag for change in box.changes] == ["node_a"]


def test_a_node_barely_faster_never_takes_the_exit(tmp_path):
    """Two nodes a millisecond apart would otherwise trade the exit every
    round, and every trade drops the connections that were on the old one."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {"node_a": [measured("node_a", 100)], "node_b": [measured("node_b", 95)]}
        ),
        api=_StubApi(),
    )
    box.seed("node_a", 100, 100, 100)
    box.seed("node_b", 95, 95, 95)
    box.pin("node_a", held_s=XRAY_EXIT_DWELL_S + 60)

    status = box.controller.refresh()

    assert status.exit_tag == "node_a"
    assert box.api.set_calls == []


def test_a_much_faster_node_waits_out_the_dwell_time(tmp_path):
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {"node_a": [measured("node_a", 400)], "node_b": [measured("node_b", 40)]}
        ),
        api=_StubApi(),
    )
    box.seed("node_a", 400, 400, 400)
    box.seed("node_b", 40, 40, 40)
    box.pin("node_a", held_s=10)

    status = box.controller.refresh()

    assert status.exit_tag == "node_a"
    assert box.api.set_calls == []


def test_a_much_faster_node_takes_the_exit_once_all_three_agree(tmp_path):
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {"node_a": [measured("node_a", 400)], "node_b": [measured("node_b", 40)]}
        ),
        api=_StubApi(),
    )
    box.seed("node_a", 400, 400, 400)
    box.seed("node_b", 40, 40, 40)
    box.pin("node_a", held_s=XRAY_EXIT_DWELL_S + 60)

    status = box.controller.refresh()

    assert status.exit_tag == "node_b"
    assert box.api.set_calls == ["node_b"]


def test_an_exit_that_stopped_answering_is_left_at_once(tmp_path):
    """The dwell time holds a working exit, never a dead one."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {
                "node_a": [measured("node_a", None), measured("node_a", None)],
                "node_b": [measured("node_b", 300)],
            }
        ),
        api=_StubApi(),
    )
    box.seed("node_a", 40, 40, 40)
    box.seed("node_b", 300, 300, 300)
    box.pin("node_a", held_s=1)

    status = box.controller.refresh()

    assert status.exit_tag == "node_b"
    assert box.api.set_calls == ["node_b"]


def test_the_pinned_node_is_measured_twice_before_it_loses_the_exit(tmp_path):
    """One dropped connection is not an exit that is gone."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {
                "node_a": [measured("node_a", None), measured("node_a", 45)],
                "node_b": [measured("node_b", 300)],
            }
        ),
        api=_StubApi(),
    )
    box.seed("node_a", 40, 40, 40)
    box.pin("node_a", held_s=1)

    status = box.controller.refresh()

    assert box.probe.probed.count("node_a") == 2
    assert status.exit_tag == "node_a"
    assert box.api.set_calls == []
    health = box.store.health_of("node_a")
    assert health.is_down is False
    assert [sample.request_ms for sample in health.samples[-2:]] == [None, 45]


def test_a_node_nobody_measured_keeps_the_pin_where_it_is(tmp_path):
    """Ignorance is not evidence: the one node that answered may be the one
    nobody has asked yet."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {"node_a": [measured("node_a", None), measured("node_a", None)]}
        ),
        api=_StubApi(),
    )
    box.seed("node_a", 40, 40)
    box.pin("node_a", held_s=XRAY_EXIT_DWELL_S + 60)

    status = box.controller.refresh(only="a")

    assert box.probe.probed == ["node_a", "node_a"]
    assert status.exit_tag == "node_a"
    assert box.api.set_calls == []


def test_a_switched_off_node_is_still_measured(tmp_path):
    """The render gives it an outbound and a probe account of its own, on or
    off, so its card can say what switching it back on would cost. Skipping it
    would leave that card showing a reading from whenever it was last on."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {"node_a": [measured("node_a", 400)], "node_b": [measured("node_b", 40)]}
        ),
        api=_StubApi(),
        nodes=node_list(is_b_enabled=False),
    )

    box.controller.refresh()

    assert sorted(box.probe.probed) == ["node_a", "node_b"]
    health = box.store.health_of("node_b")
    assert health.sample_count == 1
    assert health.samples[0].request_ms == 40
    assert health.probed_at is not None


def test_a_switched_off_node_is_never_pinned(tmp_path):
    """Switched off says the hub may not choose it, and nothing else. This one
    is ten times faster than the exit and has waited out the dwell time, so
    every other rule says switch."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {"node_a": [measured("node_a", 400)], "node_b": [measured("node_b", 40)]}
        ),
        api=_StubApi(),
        nodes=node_list(is_b_enabled=False),
    )
    box.seed("node_a", 400, 400, 400)
    box.seed("node_b", 40, 40, 40)
    box.pin("node_a", held_s=XRAY_EXIT_DWELL_S + 60)

    status = box.controller.refresh()

    assert box.store.health_of("node_b").is_alive
    assert status.exit_tag == "node_a"
    assert box.api.set_calls == []


def test_every_node_down_goes_direct_when_the_fallback_is_on(tmp_path):
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {
                "node_a": [measured("node_a", None)],
                "node_b": [measured("node_b", None)],
            }
        ),
        api=_StubApi(),
        routing={"is_direct_fallback_enabled": True},
    )
    box.seed("node_a", 40)
    box.seed("node_b", 40)

    status = box.controller.refresh()

    assert status.exit_tag == XRAY_DIRECT_TAG
    assert box.api.set_calls == [XRAY_DIRECT_TAG]


def test_every_node_down_holds_the_exit_when_the_fallback_is_off(tmp_path):
    """Off, what was sent to the proxy does not go. Sending it out the WAN
    instead is the one thing the proxy was there to prevent."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {
                "node_a": [measured("node_a", None)],
                "node_b": [measured("node_b", None)],
            }
        ),
        api=_StubApi(),
        routing={"is_direct_fallback_enabled": False},
    )
    box.seed("node_a", 40)
    box.seed("node_b", 40)
    box.pin("node_a", held_s=10)

    status = box.controller.refresh()

    assert status.exit_tag == "node_a"
    assert box.api.set_calls == []


def test_a_round_that_found_the_uplink_down_records_nothing(tmp_path):
    """A node cannot be blamed for a WAN that is not there, and a window full
    of that blame would take days of good measurements to clear."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {
                "node_a": [measured("node_a", None)],
                "node_b": [measured("node_b", None)],
            },
            reference_ms=None,
        ),
        api=_StubApi(),
    )
    box.pin("node_a", held_s=10)

    status = box.controller.refresh()

    assert status.is_wan_reachable is False
    assert box.store.health() == {}
    assert status.exit_tag == "node_a"


def test_a_nodes_success_is_recorded_whatever_the_reference_said(tmp_path):
    """A working exit is evidence: the reference itself may be the host that
    is down."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {
                "node_a": [measured("node_a", 50)],
                "node_b": [measured("node_b", None)],
            },
            reference_ms=None,
        ),
        api=_StubApi(),
    )

    box.controller.refresh()

    assert box.store.health_of("node_a").sample_count == 1
    assert box.store.health_of("node_b").sample_count == 0


def test_a_refused_probe_inbound_records_nothing_about_any_node(tmp_path):
    """xray restarting refuses every measurement at once."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {
                "node_a": [measured("node_a", None, is_xray_reachable=False)],
                "node_b": [measured("node_b", None, is_xray_reachable=False)],
            }
        ),
        api=_StubApi(),
    )
    box.pin("node_a", held_s=10)

    status = box.controller.refresh()

    assert status.is_xray_reachable is False
    assert box.store.health() == {}
    assert box.probe.reference_calls == 0


def test_an_xray_that_does_not_answer_its_api_measures_nothing(tmp_path):
    box = _Box(
        tmp_path,
        probe=_StubProbe({"node_a": [measured("node_a", 40)]}),
        api=_StubApi(is_reachable=False),
    )
    box.pin("node_a", held_s=10)
    box.api.is_reachable = False

    status = box.controller.refresh()

    assert status.is_xray_reachable is False
    assert box.probe.probed == []
    assert status.exit_tag == "node_a"


def test_an_outbound_xray_does_not_carry_is_not_a_candidate(tmp_path):
    """The render names it and xray does not have it, so a connection sent
    there would go nowhere."""
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {"node_a": [measured("node_a", 40)], "node_b": [measured("node_b", 300)]}
        ),
        api=_StubApi(outbounds=("node_b", XRAY_DIRECT_TAG)),
    )

    status = box.controller.refresh()

    assert status.is_in_sync is False
    assert status.missing_tags == ["node_a"]
    assert status.exit_tag == "node_b"
    assert len(box.mismatches) == 1


def test_a_mismatch_is_said_once_and_not_every_round(tmp_path):
    box = _Box(
        tmp_path,
        probe=_StubProbe(
            {"node_a": [measured("node_a", 40)], "node_b": [measured("node_b", 300)]}
        ),
        api=_StubApi(outbounds=("node_b", XRAY_DIRECT_TAG)),
    )

    box.controller.refresh()
    box.controller.refresh()

    assert len(box.mismatches) == 1


def test_an_xray_that_came_back_without_an_override_is_pinned_again(tmp_path):
    """The unit is Type=simple, so systemd reports the restart before the API
    inbound is listening; an empty override with a tag in the store is that."""
    box = _Box(
        tmp_path,
        probe=_StubProbe({"node_a": [measured("node_a", 40)]}),
        api=_StubApi(override=""),
    )
    box.store.set_exit("node_a", now=NOW)

    assert box.controller.reassert() is True
    assert box.api.set_calls == ["node_a"]


def test_an_xray_already_holding_the_stored_exit_is_left_alone(tmp_path):
    box = _Box(
        tmp_path,
        probe=_StubProbe({"node_a": [measured("node_a", 40)]}),
        api=_StubApi(override="node_a"),
    )
    box.store.set_exit("node_a", now=NOW)

    assert box.controller.reassert() is True
    assert box.api.set_calls == []


def test_the_pin_is_tried_again_while_the_api_is_still_coming_up(tmp_path, monkeypatch):
    slept: list = []
    monkeypatch.setattr(exit_controller.time, "sleep", slept.append)
    box = _Box(
        tmp_path,
        probe=_StubProbe({"node_a": [measured("node_a", 40)]}),
        api=_StubApi(refusals=2),
    )
    box.store.set_exit("node_a", now=NOW)

    assert box.controller.reassert() is True
    assert box.api.set_calls == ["node_a"]
    assert len(slept) == 2


def test_an_api_that_never_comes_up_stops_after_its_tries(tmp_path, monkeypatch):
    slept: list = []
    monkeypatch.setattr(exit_controller.time, "sleep", slept.append)
    box = _Box(
        tmp_path,
        probe=_StubProbe({"node_a": [measured("node_a", 40)]}),
        api=_StubApi(is_reachable=False),
    )
    box.store.set_exit("node_a", now=NOW)

    assert box.controller.reassert() is False
    assert len(slept) == XRAY_EXIT_REASSERT_TRIES - 1


def test_reselect_pins_from_what_is_stored_without_measuring(tmp_path):
    """Switching a node off is not a reason to open a connection through
    every other one."""
    box = _Box(
        tmp_path,
        probe=_StubProbe({}),
        api=_StubApi(),
    )
    box.seed("node_a", 400, 400, 400)
    box.seed("node_b", 40, 40, 40)

    status = box.controller.reselect()

    assert box.probe.probed == []
    assert status.exit_tag == "node_b"
    assert box.api.set_calls == ["node_b"]


def test_a_test_of_one_node_runs_while_a_round_holds_the_round_lock(tmp_path):
    """A Test takes the short state lock alone, so the person pressing it is
    not waiting on a round that is already measuring six nodes."""
    box = _Box(
        tmp_path,
        probe=_StubProbe({"node_b": [measured("node_b", 55)]}),
        api=_StubApi(),
    )
    box.controller._round_lock.acquire()
    try:
        status = box.controller.refresh(only="b")
    finally:
        box.controller._round_lock.release()

    assert box.probe.probed == ["node_b"]
    assert box.store.health_of("node_b").sample_count == 1
    assert status.exit_tag == "node_b"


def test_the_loop_skips_a_tick_that_would_overlap_a_round(tmp_path):
    """Two rounds at once would measure every node twice and rank on half of
    each."""
    box = _Box(
        tmp_path,
        probe=_StubProbe({"node_a": [measured("node_a", 40)]}),
        api=_StubApi(),
    )
    box.controller._round_lock.acquire()
    try:
        box.controller._tick()
    finally:
        box.controller._round_lock.release()

    assert box.probe.probed == []


def test_a_test_of_a_node_the_list_does_not_name_is_refused(tmp_path):
    box = _Box(tmp_path, probe=_StubProbe({}), api=_StubApi())

    with pytest.raises(KeyError):
        box.controller.refresh(only="gone")


def test_the_interval_is_read_from_the_node_list_each_tick(tmp_path):
    box = _Box(tmp_path, probe=_StubProbe({}), api=_StubApi())

    assert box.controller._interval_s() == 60
    box.nodes.probe_interval_s = 900
    assert box.controller._interval_s() == 900
