"""Manual declarations against a live box, with real listeners to point at.

These run on the box itself, so a listener this test opens on loopback is one
the panel's probes can reach. An app with an entry of each type is declared
against those listeners, the published list is watched until health turns
green, and apps are probed against a dead port and removed.
"""

import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HEALTH_DEADLINE_S = 45.0
HEALTH_POLL_S = 1.0


def _suffix() -> str:
    return secrets.token_hex(3)


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"hello"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *arguments):
        return


@pytest.fixture(scope="module")
def tcp_port():
    """A loopback port that accepts connections for the module's lifetime."""
    server = socket.create_server(("127.0.0.1", 0))
    try:
        yield server.getsockname()[1]
    finally:
        server.close()


@pytest.fixture(scope="module")
def http_port():
    """A loopback HTTP server answering every GET."""
    server = HTTPServer(("127.0.0.1", 0), _OkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _closed_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as server:
        return server.getsockname()[1]


def _declared(listed: dict) -> list:
    """The declared apps of a service list."""
    return [app for app in listed["apps"] if app["source"] == "declared"]


def _declare(panel, body: dict) -> dict:
    """Declare one app and return its published row."""
    before = {app["id"] for app in _declared(panel.read("/hub/service"))}
    status, listed = panel.call("POST", "/hub/service/declaration/add", body)
    assert status == 200, listed
    fresh = [app for app in _declared(listed) if app["id"] not in before]
    assert len(fresh) == 1, (body["name"], fresh)
    return fresh[0]


def _delete(panel, app_id: str) -> None:
    panel.call("POST", "/hub/service/declaration/remove", {"app_id": app_id})


def _entries(panel) -> dict:
    """Every entry of every declared app, by entry id."""
    return {
        entry["id"]: entry
        for app in _declared(panel.read("/hub/service"))
        for entry in app["entries"]
    }


def _wait_until_healthy(panel, entry_ids: list) -> dict:
    """Poll the published list until every entry reads healthy, or fail."""
    waited = 0.0
    rows: dict = {}
    while waited <= HEALTH_DEADLINE_S:
        rows = _entries(panel)
        if all(rows.get(rid, {}).get("is_healthy") is True for rid in entry_ids):
            return rows
        time.sleep(HEALTH_POLL_S)
        waited += HEALTH_POLL_S
    states = {rid: rows.get(rid, {}).get("is_healthy") for rid in entry_ids}
    raise AssertionError(f"not healthy within {HEALTH_DEADLINE_S}s: {states}")


def test_the_published_list_answers_typed(panel):
    listed = panel.read("/hub/service")
    for app in listed["apps"]:
        assert app["source"] in ("module", "declared", "manual"), app
        for entry in app["entries"]:
            assert entry["type"] in ("web", "port", "file"), entry
            assert "payload" in entry and "is_healthy" in entry, entry
    for entry in listed["services"]:
        assert entry["type"] in ("web", "port", "ai", "file", "rdp"), entry
        assert "payload" in entry and "is_healthy" in entry, entry


def test_web_and_port_turn_healthy_against_real_listeners(panel, tcp_port, http_port):
    app = _declare(
        panel,
        {
            "name": f"itest web {_suffix()}",
            "host": "127.0.0.1",
            "entries": [
                {"type": "web", "port": http_port, "scheme": "http", "path": "/"},
                {"type": "port", "port": tcp_port},
            ],
        },
    )
    try:
        rows = _wait_until_healthy(panel, [entry["id"] for entry in app["entries"]])
        assert sorted(rows[entry["id"]]["type"] for entry in app["entries"]) == [
            "port",
            "web",
        ]
    finally:
        _delete(panel, app["id"])


def test_a_file_service_is_judged_by_the_server_not_the_port(panel, tcp_port):
    """A share is healthy only when the server exports it. A port that
    answers proves nothing: the old probe called this green."""
    app = _declare(
        panel,
        {
            "name": f"itest nas {_suffix()}",
            "host": "127.0.0.1",
            "entries": [{"type": "file", "port": tcp_port, "share": "media"}],
        },
    )
    entry_id = app["entries"][0]["id"]
    try:
        waited = 0.0
        row = {}
        while waited <= HEALTH_DEADLINE_S:
            row = _entries(panel).get(entry_id, {})
            if row.get("is_healthy") is not None:
                break
            time.sleep(HEALTH_POLL_S)
            waited += HEALTH_POLL_S

        assert row.get("is_healthy") is False, row
        assert row.get("detail_code") in ("connect_failed", "share_missing"), row
    finally:
        _delete(panel, app["id"])


def test_scanning_a_host_that_answers_nothing_is_refused_with_a_code(panel):
    status, answer = panel.call("GET", "/hub/service/share?host=127.0.0.1")

    assert status == 400, answer
    assert answer["detail"]["code"] == "share_scan_failed"


def test_probe_and_delete_walk_one_app(panel, tcp_port):
    live = _declare(
        panel,
        {
            "name": f"itest probe {_suffix()}",
            "host": "127.0.0.1",
            "entries": [{"type": "port", "port": tcp_port}],
        },
    )
    dead = _declare(
        panel,
        {
            "name": f"itest dead {_suffix()}",
            "host": "127.0.0.1",
            "entries": [{"type": "port", "port": _closed_port()}],
        },
    )
    try:
        for app, is_healthy in ((live, True), (dead, False)):
            status, listed = panel.call(
                "POST", "/hub/service/declaration/probe", {"app_id": app["id"]}
            )
            assert status == 200, listed
            rows = {
                entry["id"]: entry
                for row in _declared(listed)
                for entry in row["entries"]
            }
            assert rows[app["entries"][0]["id"]]["is_healthy"] is is_healthy
    finally:
        for app in (live, dead):
            assert (
                panel.status(
                    "POST", "/hub/service/declaration/remove", {"app_id": app["id"]}
                )
                == 200
            )

    remaining = {app["id"] for app in _declared(panel.read("/hub/service"))}
    assert live["id"] not in remaining
    assert (
        panel.status("POST", "/hub/service/declaration/remove", {"app_id": live["id"]})
        == 404
    )


def test_an_entry_of_an_unknown_type_is_refused_with_a_code(panel):
    status, answer = panel.call(
        "POST",
        "/hub/service/declaration/add",
        {
            "name": "itest bad",
            "host": "h",
            "entries": [{"type": "ai_endpoint", "port": 1}],
        },
    )
    assert status == 400, answer
    assert answer["detail"] == {
        "code": "declared_service_invalid",
        "params": {"field": "entries.0.type"},
    }
