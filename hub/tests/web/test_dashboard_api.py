"""The traffic history route: which vnstat buckets each range reads, and
today's total beside them."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.system.vnstat_history import TrafficSample
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import dashboard as dashboard_router


class FakeReader:
    asked: list = []

    def __init__(self, *, interface):
        self.interface = interface

    def hourly(self, *, hour_count):
        FakeReader.asked.append(("h", hour_count))
        return [TrafficSample("2026-09-12 07:00", 1, 2)]

    def daily(self, *, day_count):
        FakeReader.asked.append(("d", day_count))
        return [TrafficSample("2026-09-12", 30, 40)]

    def monthly(self, *, month_count):
        FakeReader.asked.append(("m", month_count))
        return [TrafficSample("2026-09", 300, 400)]


class FakeRuntime:
    def network(self):
        class _Network:
            wan_device_names = ["enp2s0"]

        return _Network()


@pytest.fixture
def client(monkeypatch):
    FakeReader.asked = []
    monkeypatch.setattr(dashboard_router, "VnstatHistoryReader", FakeReader)
    app = FastAPI()
    app.include_router(dashboard_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: FakeRuntime()
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "range_name, asked, label",
    [
        ("day", ("h", 24), "2026-09-12 07:00"),
        ("week", ("d", 7), "2026-09-12"),
        ("month", ("d", 30), "2026-09-12"),
        ("year", ("m", 12), "2026-09"),
    ],
)
def test_each_range_reads_its_own_buckets(client, range_name, asked, label):
    payload = client.get(f"/api/dashboard/history?range={range_name}").json()

    assert payload["range"] == range_name
    assert payload["samples"][0]["label"] == label
    assert asked in FakeReader.asked


def test_today_is_read_whatever_the_range(client):
    payload = client.get("/api/dashboard/history?range=year").json()

    assert ("d", 1) in FakeReader.asked
    assert payload["today"] == {
        "label": "2026-09-12",
        "received_bytes": 30,
        "sent_bytes": 40,
    }


def test_the_default_range_is_the_month(client):
    assert client.get("/api/dashboard/history").json()["range"] == "month"


def test_an_unknown_range_is_a_400(client):
    response = client.get("/api/dashboard/history?range=decade")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_range"
