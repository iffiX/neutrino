"""The declared-services API: full-record CRUD, coded errors, and the
Services view carrying each entry's cached health.

The probe is a recorder here — what a real one measures is covered beside the
module — so what this file checks is the contract: what the panel sends, what
comes back, and that no English sentence ever does.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neutrino_hub.utils.json_file
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.services.probe import DeclaredServiceHealth
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import declared_services, service_control
from tests.conftest import unlock_vault


class RecordingProbe:
    """Answers from a dictionary and remembers what was probed."""

    def __init__(self):
        self.health: dict[str, DeclaredServiceHealth] = {}
        self.probed: list[str] = []

    def results(self, services):
        return [
            self.health.get(s.id, DeclaredServiceHealth(s.id, None, None, None))
            for s in services
        ]

    def probe(self, service):
        self.probed.append(service.id)
        return self.health.get(
            service.id,
            DeclaredServiceHealth(service.id, True, "2026-01-01T00:00:00+00:00", None),
        )

    def cached(self, service_id):
        return self.health.get(service_id)


class StubServices:
    """One managed unit, so the Services view has something beside declared."""

    def status_all(self):
        return [
            ServiceStatus(
                name="xray",
                unit="xray.service",
                is_installed=True,
                is_active=True,
                is_enabled=True,
            )
        ]


class FakeRuntime:
    def __init__(self):
        self.services = StubServices()
        self.declared_probe = RecordingProbe()


@pytest.fixture
def box(monkeypatch, tmp_path):
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(service_control.router)
    app.include_router(declared_services.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def declare(client, **fields) -> dict:
    body = {"name": "engine", "kind": "generic_tcp", "host": "10.0.0.5", "port": 9000}
    response = client.post("/api/services/declared", json={**body, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_each_kind_declares_and_answers_its_own_fields(box):
    client, runtime = box

    samba = declare(
        client,
        name="nas",
        kind="samba",
        host="192.168.100.7",
        port=None,
        shares=[{"name": "media", "service_account_id": None}],
    )
    assert samba["port"] == 445
    assert samba["shares"] == [{"name": "media", "service_account_id": None}]
    assert samba["probe"] == {
        "is_healthy": None,
        "checked_at": None,
        "detail_code": None,
    }

    http = declare(client, name="wiki", kind="http", port=8080, scheme="https")
    assert (http["scheme"], http["path"]) == ("https", "/")

    docker = declare(client, name="build box", kind="docker_engine", port=2375)
    assert docker["scheme"] is None and docker["shares"] == []

    tcp = declare(client)
    assert len({samba["id"], http["id"], docker["id"], tcp["id"]}) == 4


def test_the_services_view_carries_each_entry_with_its_cached_health(box):
    client, runtime = box
    healthy = declare(client, name="up")
    unknown = declare(client, name="new")
    runtime.declared_probe.health[healthy["id"]] = DeclaredServiceHealth(
        healthy["id"], False, "2026-01-01T00:00:00+00:00", "connect_failed"
    )

    payload = client.get("/api/services").json()

    assert {entry["name"] for entry in payload["services"]} == {"xray"}
    declared = {entry["id"]: entry for entry in payload["declared"]}
    assert declared[healthy["id"]]["probe"]["is_healthy"] is False
    assert declared[healthy["id"]]["probe"]["detail_code"] == "connect_failed"
    assert declared[unknown["id"]]["probe"]["is_healthy"] is None


def test_a_full_record_update_answers_the_new_record(box):
    client, runtime = box
    record = declare(client)

    response = client.put(
        f"/api/services/declared/{record['id']}",
        json={
            "name": "renamed",
            "kind": "http",
            "host": "web.lan",
            "port": 8443,
            "scheme": "https",
            "path": "/status",
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["id"] == record["id"]
    assert (updated["name"], updated["kind"]) == ("renamed", "http")
    assert (updated["scheme"], updated["path"]) == ("https", "/status")


def test_delete_removes_the_entry_from_the_view(box):
    client, runtime = box
    record = declare(client)

    assert client.delete(f"/api/services/declared/{record['id']}").json() == {}

    assert client.get("/api/services").json()["declared"] == []
    second = client.delete(f"/api/services/declared/{record['id']}")
    assert second.status_code == 404
    assert second.json()["detail"] == {"code": "declared_service_unknown"}


def test_an_unknown_id_answers_a_code_not_a_sentence(box):
    client, runtime = box
    response = client.put(
        "/api/services/declared/missing",
        json={"name": "a", "kind": "generic_tcp", "host": "h", "port": 1},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "declared_service_unknown"}


@pytest.mark.parametrize(
    "fields, refused",
    [
        ({"kind": "ai_endpoint"}, "kind"),
        ({"name": ""}, "name"),
        ({"host": " "}, "host"),
        ({"port": None}, "port"),
        ({"port": 70000}, "port"),
    ],
)
def test_a_refused_field_is_named_in_the_error(box, fields, refused):
    client, runtime = box
    body = {"name": "a", "kind": "generic_tcp", "host": "h", "port": 1, **fields}

    response = client.post("/api/services/declared", json=body)

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "declared_service_invalid",
        "params": {"field": refused},
    }


def test_a_share_naming_an_unknown_account_is_refused(box):
    client, runtime = box
    response = client.post(
        "/api/services/declared",
        json={
            "name": "nas",
            "kind": "samba",
            "host": "h",
            "shares": [{"name": "media", "service_account_id": "0" * 32}],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "declared_service_invalid",
        "params": {"field": "service_account_id"},
    }


def test_a_share_naming_a_stored_account_is_accepted(box):
    client, runtime = box
    account = SecretVault().add(
        kind="service_account",
        name="nas login",
        secret={"password": "pw"},  # scan: allow
        meta={"username": "nas"},
    )

    record = declare(
        client,
        name="nas",
        kind="samba",
        host="h",
        port=None,
        shares=[{"name": "media", "service_account_id": account.id}],
    )

    assert record["shares"][0]["service_account_id"] == account.id


def test_probe_now_answers_fresh_and_is_a_probe_not_a_read(box):
    client, runtime = box
    record = declare(client)
    runtime.declared_probe.health[record["id"]] = DeclaredServiceHealth(
        record["id"], True, "2026-01-01T00:00:00+00:00", None
    )

    response = client.post(f"/api/services/declared/{record['id']}/probe")

    assert response.status_code == 200
    assert response.json() == {
        "is_healthy": True,
        "checked_at": "2026-01-01T00:00:00+00:00",
        "detail_code": None,
    }
    assert runtime.declared_probe.probed == [record["id"]]

    missing = client.post("/api/services/declared/missing/probe")
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "declared_service_unknown"}
