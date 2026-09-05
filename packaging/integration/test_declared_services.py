"""Manual declarations against a live box, with real listeners to point at.

These run on the box itself, so a listener this test opens on loopback is one
the panel's probes can reach. One declaration of each type is made against
those listeners, the published list is watched until health turns green, and
records are probed against a dead port and deleted.
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


def _declared(services: list) -> list:
    return [entry for entry in services if entry["source"] == "declared"]


def _declare(panel, body: dict) -> dict:
    """Create one declaration and return its published row."""
    before = {
        entry["record_id"] for entry in _declared(panel.read("/services")["services"])
    }
    status, listed = panel.call("POST", "/services/declared", body)
    assert status == 201, listed
    fresh = [
        entry
        for entry in _declared(listed["services"])
        if entry["record_id"] not in before
    ]
    assert len(fresh) == 1, (body["name"], fresh)
    return fresh[0]


def _delete(panel, record_id: str) -> None:
    panel.call("DELETE", f"/services/declared/{record_id}")


def _wait_until_healthy(panel, record_ids: list) -> dict:
    """Poll the published list until every id reads healthy, or fail."""
    waited = 0.0
    rows: dict = {}
    while waited <= HEALTH_DEADLINE_S:
        rows = {
            entry["record_id"]: entry
            for entry in _declared(panel.read("/services")["services"])
        }
        if all(rows.get(rid, {}).get("is_healthy") is True for rid in record_ids):
            return rows
        time.sleep(HEALTH_POLL_S)
        waited += HEALTH_POLL_S
    states = {rid: rows.get(rid, {}).get("is_healthy") for rid in record_ids}
    raise AssertionError(f"not healthy within {HEALTH_DEADLINE_S}s: {states}")


def test_the_published_list_answers_typed(panel):
    services = panel.read("/services")["services"]
    for entry in services:
        assert entry["type"] in ("web", "port", "ai", "file"), entry
        assert entry["source"] in ("module", "declared"), entry
        assert "payload" in entry and "is_healthy" in entry, entry


def test_web_and_port_turn_healthy_against_real_listeners(panel, tcp_port, http_port):
    run = _suffix()
    created = []
    try:
        created.append(
            _declare(
                panel,
                {
                    "name": f"itest web {run}",
                    "kind": "web",
                    "host": "127.0.0.1",
                    "port": http_port,
                    "scheme": "http",
                    "path": "/",
                },
            )
        )
        created.append(
            _declare(
                panel,
                {
                    "name": f"itest tcp {run}",
                    "kind": "port",
                    "host": "127.0.0.1",
                    "port": tcp_port,
                },
            )
        )

        rows = _wait_until_healthy(panel, [entry["record_id"] for entry in created])
        for entry in created:
            assert rows[entry["record_id"]]["type"] == entry["type"]
    finally:
        for entry in created:
            _delete(panel, entry["record_id"])


def test_a_file_service_is_judged_by_the_server_not_the_port(panel, tcp_port):
    """A share is healthy only when the server exports it. A port that
    answers proves nothing: the old probe called this green."""
    run = _suffix()
    record = _declare(
        panel,
        {
            "name": f"itest nas {run}",
            "kind": "file",
            "host": "127.0.0.1",
            "port": tcp_port,
            "shares": ["media"],
        },
    )
    try:
        waited = 0.0
        row = {}
        while waited <= HEALTH_DEADLINE_S:
            rows = {
                entry["record_id"]: entry
                for entry in _declared(panel.read("/services")["services"])
            }
            row = rows.get(record["record_id"], {})
            if row.get("is_healthy") is not None:
                break
            time.sleep(HEALTH_POLL_S)
            waited += HEALTH_POLL_S

        assert row.get("is_healthy") is False, row
        assert row.get("detail_code") in ("connect_failed", "share_missing"), row
    finally:
        _delete(panel, record["record_id"])


def test_scanning_a_host_that_answers_nothing_is_refused_with_a_code(panel):
    status, answer = panel.call("GET", "/services/shares?host=127.0.0.1")

    assert status == 400, answer
    assert answer["detail"]["code"] == "share_scan_failed"


def test_probe_and_delete_walk_one_record(panel, tcp_port):
    run = _suffix()
    record = _declare(
        panel,
        {
            "name": f"itest probe {run}",
            "kind": "port",
            "host": "127.0.0.1",
            "port": tcp_port,
        },
    )
    dead = _declare(
        panel,
        {
            "name": f"itest dead {run}",
            "kind": "port",
            "host": "127.0.0.1",
            "port": _closed_port(),
        },
    )
    try:
        status, listed = panel.call(
            "POST", f"/services/declared/{record['record_id']}/probe"
        )
        assert status == 200, listed
        rows = {e["record_id"]: e for e in _declared(listed["services"])}
        assert rows[record["record_id"]]["is_healthy"] is True

        status, listed = panel.call(
            "POST", f"/services/declared/{dead['record_id']}/probe"
        )
        assert status == 200, listed
        rows = {e["record_id"]: e for e in _declared(listed["services"])}
        assert rows[dead["record_id"]]["is_healthy"] is False
    finally:
        assert (
            panel.status("DELETE", f"/services/declared/{record['record_id']}") == 200
        )
        assert panel.status("DELETE", f"/services/declared/{dead['record_id']}") == 200

    remaining = {
        entry["record_id"] for entry in _declared(panel.read("/services")["services"])
    }
    assert record["record_id"] not in remaining
    assert panel.status("DELETE", f"/services/declared/{record['record_id']}") == 404


def test_a_bad_record_is_refused_with_a_code(panel):
    status, answer = panel.call(
        "POST",
        "/services/declared",
        {"name": "itest bad", "kind": "ai_endpoint", "host": "h", "port": 1},
    )
    assert status == 400, answer
    assert answer["detail"] == {
        "code": "declared_service_invalid",
        "params": {"field": "kind"},
    }
