"""The dashboard's DNS log socket, driven through the test client.

What is pinned here is what the socket sends, and that it stops reading the
log once the browser leaves: a socket nobody reads otherwise holds the
panel's stop for its whole grace period.
"""

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web import ws
from neutrino_hub.web.dependencies import session_cookie
from neutrino_hub.web.models import DnsLogEntry

SESSION_TOKEN = "panel-session"
SESSION_COOKIE = session_cookie(SimpleNamespace(settings={}))
POLL_S = 0.01


class StubSessions:
    def is_valid(self, token) -> bool:
        return token == SESSION_TOKEN


class StubReader:
    """The log: two recent queries, then one more on the first look."""

    looks = 0

    def tail(self):
        return [
            DnsLogEntry(timestamp="t2", domain="b.example", client="10.0.0.2"),
            DnsLogEntry(timestamp="t1", domain="a.example", client="10.0.0.1"),
        ]

    def follow(self):
        StubReader.looks += 1
        if StubReader.looks == 1:
            return [DnsLogEntry(timestamp="t3", domain="c.example", client="10.0.0.3")]
        return []


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ws, "DnsLogReader", StubReader)
    monkeypatch.setattr(ws, "DNS_LOG_POLL_INTERVAL_S", POLL_S)
    StubReader.looks = 0
    app = FastAPI()
    app.include_router(ws.router)
    app.state.runtime = SimpleNamespace(settings={}, sessions=StubSessions())
    with TestClient(app) as test_client:
        test_client.cookies.set(SESSION_COOKIE, SESSION_TOKEN)
        yield test_client


def test_the_socket_sends_the_recent_queries_oldest_first_then_each_new_one(client):
    with client.websocket_connect("/ws/hub/dashboard/dns_log") as socket:
        first = socket.receive_json()
        second = socket.receive_json()

    assert [entry["domain"] for entry in first["entries"]] == [
        "a.example",
        "b.example",
    ]
    assert [entry["domain"] for entry in second["entries"]] == ["c.example"]


def test_the_log_is_no_longer_read_once_the_browser_leaves(client):
    with client.websocket_connect("/ws/hub/dashboard/dns_log") as socket:
        socket.receive_json()
        socket.receive_json()
        socket.close()
        time.sleep(POLL_S * 20)
        looked = StubReader.looks
        time.sleep(POLL_S * 20)

        assert StubReader.looks == looked
