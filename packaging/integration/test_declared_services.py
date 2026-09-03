"""The Declared section against a live box, with real listeners to point at.

These run on the box itself, so a listener this test opens on loopback is one
the panel's probes can reach. One service of each kind is declared against
those listeners, the Services view is watched until its cached health turns
green, and the record is edited, probed against a dead port, and deleted.
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


class _PingHandler(BaseHTTPRequestHandler):
    """Answers /_ping the way a Docker engine does, and everything else 200."""

    def do_GET(self):
        body = b"OK" if self.path == "/_ping" else b"hello"
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
    """A loopback HTTP server answering /_ping like Docker does."""
    server = HTTPServer(("127.0.0.1", 0), _PingHandler)
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


def _declare(panel, body: dict) -> dict:
    status, created = panel.call("POST", "/services/declared", body)
    assert status == 201, created
    return created


def _delete(panel, service_id: str) -> None:
    panel.call("DELETE", f"/services/declared/{service_id}")


def _wait_until_healthy(panel, service_ids: list) -> dict:
    """Poll the Services view until every id reads healthy, or fail."""
    waited = 0.0
    declared: dict = {}
    while waited <= HEALTH_DEADLINE_S:
        declared = {entry["id"]: entry for entry in panel.read("/services")["declared"]}
        if all(
            declared.get(sid, {}).get("probe", {}).get("is_healthy") is True
            for sid in service_ids
        ):
            return declared
        time.sleep(HEALTH_POLL_S)
        waited += HEALTH_POLL_S
    states = {sid: declared.get(sid, {}).get("probe") for sid in service_ids}
    raise AssertionError(f"not healthy within {HEALTH_DEADLINE_S}s: {states}")


def test_one_of_each_kind_declares_and_turns_healthy(panel, tcp_port, http_port):
    run = _suffix()
    created = []
    try:
        created.append(
            _declare(
                panel,
                {
                    "name": f"itest nas {run}",
                    "kind": "samba",
                    "host": "127.0.0.1",
                    "port": tcp_port,
                    "shares": [{"name": "media", "login_id": None}],
                },
            )
        )
        created.append(
            _declare(
                panel,
                {
                    "name": f"itest web {run}",
                    "kind": "http",
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
                    "name": f"itest engine {run}",
                    "kind": "docker_engine",
                    "host": "127.0.0.1",
                    "port": http_port,
                },
            )
        )
        created.append(
            _declare(
                panel,
                {
                    "name": f"itest tcp {run}",
                    "kind": "generic_tcp",
                    "host": "127.0.0.1",
                    "port": tcp_port,
                },
            )
        )

        entries = _wait_until_healthy(panel, [entry["id"] for entry in created])
        for entry in created:
            listed = entries[entry["id"]]
            assert listed["kind"] == entry["kind"]
            assert listed["probe"]["detail_code"] is None
            assert listed["probe"]["checked_at"]
    finally:
        for entry in created:
            _delete(panel, entry["id"])


def test_edit_probe_and_delete_walk_one_record(panel, tcp_port):
    run = _suffix()
    record = _declare(
        panel,
        {
            "name": f"itest edit {run}",
            "kind": "generic_tcp",
            "host": "127.0.0.1",
            "port": tcp_port,
        },
    )
    try:
        status, fresh = panel.call("POST", f"/services/declared/{record['id']}/probe")
        assert status == 200 and fresh["is_healthy"] is True

        status, updated = panel.call(
            "PUT",
            f"/services/declared/{record['id']}",
            {
                "name": f"itest edited {run}",
                "kind": "generic_tcp",
                "host": "127.0.0.1",
                "port": _closed_port(),
            },
        )
        assert status == 200, updated
        assert updated["id"] == record["id"]
        assert updated["name"] == f"itest edited {run}"

        status, fresh = panel.call("POST", f"/services/declared/{record['id']}/probe")
        assert status == 200
        assert fresh["is_healthy"] is False
        assert fresh["detail_code"] == "connect_failed"
    finally:
        assert panel.status("DELETE", f"/services/declared/{record['id']}") == 200

    listed = {entry["id"] for entry in panel.read("/services")["declared"]}
    assert record["id"] not in listed
    assert panel.status("DELETE", f"/services/declared/{record['id']}") == 404


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

    status, answer = panel.call(
        "PUT",
        "/services/declared/missing",
        {"name": "a", "kind": "generic_tcp", "host": "h", "port": 1},
    )
    assert status == 404
    assert answer["detail"] == {"code": "declared_service_unknown"}


def test_a_share_account_is_counted_and_cleared_by_its_delete(panel, tcp_port):
    run = _suffix()
    status, account = panel.call(
        "POST",
        "/credentials/logins",
        {
            "name": f"itest nas login {run}",
            "username": "nas",
            "password": "pw-nas",  # scan: allow
        },
    )
    assert status == 200, account

    record = _declare(
        panel,
        {
            "name": f"itest nas {run}",
            "kind": "samba",
            "host": "127.0.0.1",
            "port": tcp_port,
            "shares": [{"name": "media", "login_id": account["id"]}],
        },
    )
    try:
        accounts = panel.read("/credentials/logins")["logins"]
        listed = next(entry for entry in accounts if entry["id"] == account["id"])
        assert listed["service_count"] == 1

        status, cleared = panel.call("DELETE", f"/credentials/logins/{account['id']}")
        assert status == 200, cleared
        assert cleared == {"cleared": {"device_count": 0, "service_count": 1}}

        declared = panel.read("/services")["declared"]
        stored = next(entry for entry in declared if entry["id"] == record["id"])
        assert stored["shares"] == [{"name": "media", "login_id": None}]
    finally:
        _delete(panel, record["id"])
        panel.call("DELETE", f"/credentials/logins/{account['id']}")

    status, answer = panel.call(
        "POST",
        "/services/declared",
        {
            "name": f"itest nas {run} again",
            "kind": "samba",
            "host": "127.0.0.1",
            "shares": [{"name": "media", "login_id": account["id"]}],
        },
    )
    assert status == 400
    assert answer["detail"]["params"] == {"field": "login_id"}
