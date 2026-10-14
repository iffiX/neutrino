"""The traffic history route: the buckets each range reads from the hub's own
count, of the interface the card draws, and today's total beside them, on
Linux, macOS and Windows alike."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.router import traffic_history
from neutrino_hub.modules.router.traffic_history import RouterTrafficHistory
from neutrino_hub.system import interface_traffic
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import dashboard as dashboard_router
from tests.conftest import FakePsutil, lan_entry, network_config, wan_entry

NOW = datetime(2026, 10, 15, 14, 30)


class FixedClock(datetime):
    """The history's clock, standing at :data:`NOW`."""

    @classmethod
    def now(cls, tz=None):
        return NOW


class FakeRuntime:
    def __init__(self, network, history):
        self._network = network
        self.traffic_history = history

    def network(self):
        return self._network


def _counted(monkeypatch, tmp_path, readings: dict) -> RouterTrafficHistory:
    """A history that read ``readings``, name to counters per moment, in order."""
    monkeypatch.setattr(traffic_history, "datetime", FixedClock)
    monkeypatch.setattr(
        traffic_history, "psutil", SimpleNamespace(boot_time=lambda: 1760500000.0)
    )
    history = RouterTrafficHistory(path=tmp_path / "traffic_history.json")
    history.load()
    for moment, counters in readings:
        monkeypatch.setattr(
            traffic_history, "all_interface_counters", lambda: dict(counters)
        )
        history.count(now=moment)
    return history


def _client(network, history) -> TestClient:
    app = FastAPI()
    app.include_router(dashboard_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: FakeRuntime(network, history)
    return TestClient(app)


@pytest.fixture
def client(monkeypatch, tmp_path):
    history = _counted(
        monkeypatch,
        tmp_path,
        [
            (NOW, {"enp2s0": (1000, 500), "enp1s0": (0, 0)}),
            (NOW, {"enp2s0": (1300, 900), "enp1s0": (7777, 7777)}),
        ],
    )
    network = network_config(
        wan_entry("enp2s0"), lan_entry("enp1s0", address="192.168.100.1")
    )
    with _client(network, history) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "range_name, label",
    [
        ("day", "2026-10-15 14:00"),
        ("week", "2026-10-15"),
        ("month", "2026-10-15"),
        ("year", "2026-10"),
    ],
)
def test_each_range_reads_its_own_buckets(client, range_name, label):
    payload = client.get(f"/api/hub/dashboard/history?range={range_name}").json()

    assert payload["range"] == range_name
    assert payload["samples"] == [
        {"label": label, "received_bytes": 300, "sent_bytes": 400}
    ]


def test_today_is_read_whatever_the_range(client):
    payload = client.get("/api/hub/dashboard/history?range=year").json()

    assert payload["today"] == {
        "label": "2026-10-15",
        "received_bytes": 300,
        "sent_bytes": 400,
    }


def test_a_range_older_than_its_window_is_left_out(monkeypatch, tmp_path):
    long_ago = NOW - timedelta(days=40)
    history = _counted(
        monkeypatch,
        tmp_path,
        [(long_ago, {"enp2s0": (0, 0)}), (long_ago, {"enp2s0": (10, 10)})],
    )
    with _client(network_config(wan_entry("enp2s0")), history) as client:
        payload = client.get("/api/hub/dashboard/history?range=month").json()

    assert payload == {"range": "month", "samples": [], "today": None}


def test_the_default_range_is_the_month(client):
    assert client.get("/api/hub/dashboard/history").json()["range"] == "month"


def test_an_unknown_range_is_a_400(client):
    response = client.get("/api/hub/dashboard/history?range=decade")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_range"


def test_elsewhere_the_history_is_the_default_route_interface(
    elsewhere, monkeypatch, tmp_path
):
    system = FakePsutil()
    monkeypatch.setattr(interface_traffic, "psutil", system)
    monkeypatch.setattr(
        interface_traffic, "system_default_routes", lambda: [{"dev": "Ethernet"}]
    )
    history = _counted(monkeypatch, tmp_path, [])
    for counters in ((1000, 500), (1250, 600)):
        system.counters = {"Ethernet": counters, "Wi-Fi": counters}
        history.count()

    with _client(network_config(mode="server"), history) as client:
        payload = client.get("/api/hub/dashboard/history?range=week").json()

    assert payload["samples"] == [
        {"label": "2026-10-15", "received_bytes": 250, "sent_bytes": 100}
    ]
    assert payload["today"]["received_bytes"] == 250
