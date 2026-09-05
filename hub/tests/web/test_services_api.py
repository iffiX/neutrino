"""The Services API: the typed list, declarations, and coded errors.

The published-list cache is real here, over a fresh config dir and stubbed
unit states, so what is exercised is the whole read path — declaration to
entry, probe health folded in, hub-self hosts resolved for the asking
browser — and the contract that no English sentence ever crosses.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.services.ops import SambaShareListing
from neutrino_hub.modules.services.probe import DeclaredServiceHealth
from neutrino_hub.modules.services.published import PublishedServiceCache
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.utils.json_file import write_config
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import services


class RecordingProbe:
    """Answers from a dictionary and remembers what was probed."""

    def __init__(self):
        self.health: dict[str, DeclaredServiceHealth] = {}
        self.probed: list[str] = []

    def results(self, records):
        return [
            self.health.get(r.id, DeclaredServiceHealth(r.id, None, None, None))
            for r in records
        ]

    def probe(self, record):
        fresh = DeclaredServiceHealth(
            record.id, True, "2026-01-01T00:00:00+00:00", None
        )
        self.health[record.id] = fresh
        self.probed.append(record.id)
        return fresh


class StubServedModels:
    def served(self, *, port, client_key):
        return True, []


class StubUnits:
    def __init__(self, active: dict[str, bool] | None = None):
        self.active = active or {}

    def status(self, name):
        is_active = self.active.get(name, False)
        return ServiceStatus(
            name=name,
            unit=f"{name}.service",
            is_installed=name in self.active,
            is_active=is_active,
            is_enabled=is_active,
        )


class FakeRuntime:
    def __init__(self, units: StubUnits):
        self.declared_probe = RecordingProbe()
        self.published_services = PublishedServiceCache(
            declared_probe=self.declared_probe,
            served_models=StubServedModels(),
            units=units,
        )


@pytest.fixture
def box(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state)
    app = FastAPI()
    app.include_router(services.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime(StubUnits({"samba": True}))
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def declare(client, **fields) -> list[dict]:
    body = {
        "name": "forge",
        "kind": "port",
        "host": "10.0.0.5",
        "port": 9000,
        "description": "the forge box",
    }
    response = client.post("/api/services/declared", json={**body, **fields})
    assert response.status_code == 201, response.text
    return response.json()["services"]


def test_each_form_kind_lands_as_its_own_type(box):
    client, _ = box

    declare(client, name="wiki", kind="web", port=8080, scheme="https")
    declare(
        client,
        name="nas",
        kind="file",
        host="192.168.100.7",
        port=None,
        shares=["media"],
    )
    entries = declare(client)

    by_type = {entry["type"]: entry for entry in entries}
    assert by_type["web"]["payload"]["url"] == "https://10.0.0.5:8080/"
    assert by_type["port"]["payload"] == {"host": "10.0.0.5", "port": 9000}
    assert by_type["file"]["payload"] == {
        "protocol": "smb",
        "host": "192.168.100.7",
        "share": "media",
    }
    assert all(entry["source"] == "declared" for entry in entries)
    assert by_type["port"]["description"] == "the forge box"
    # Stored, probed and republished under a record id the rows can act on.
    assert all(entry["record_id"] for entry in entries)
    # Every entry names the device modules it cannot work without.
    assert by_type["file"]["modules"] == ["samba_mount"]
    assert by_type["web"]["modules"] == [] and by_type["port"]["modules"] == []


def test_the_list_folds_the_probe_health_in(box):
    client, runtime = box
    entries = declare(client)
    record_id = entries[0]["record_id"]
    runtime.declared_probe.health[record_id] = DeclaredServiceHealth(
        record_id, False, "2026-01-01T00:00:00+00:00", "connect_failed"
    )
    runtime.published_services.expire()

    payload = client.get("/api/services").json()

    assert payload["services"][0]["is_healthy"] is False


def test_a_hub_module_share_is_a_read_only_row(box):
    client, _ = box
    write_config(
        "samba/samba.json", {"shares": [{"name": "media", "path": "/srv"}], "users": []}
    )

    payload = client.get("/api/services").json()

    entry = payload["services"][0]
    assert entry["id"] == "samba_media"
    assert entry["source"] == "module"
    assert entry["record_id"] is None
    assert entry["is_healthy"] is True


def test_a_hub_self_host_is_shown_as_the_panel_host(box):
    client, _ = box
    declare(client, host="127.0.0.1")

    payload = client.get("/api/services").json()

    # The TestClient reaches the panel as "testserver".
    assert payload["services"][0]["payload"]["host"] == "testserver"


def test_delete_removes_every_entry_of_the_record(box):
    client, _ = box
    entries = declare(client, name="nas", kind="file", port=None, shares=["media"])
    record_id = entries[0]["record_id"]

    removed = client.delete(f"/api/services/declared/{record_id}")

    assert removed.status_code == 200
    assert removed.json()["services"] == []
    second = client.delete(f"/api/services/declared/{record_id}")
    assert second.status_code == 404
    assert second.json()["detail"] == {"code": "declared_service_unknown"}


def test_probe_now_answers_the_refreshed_list(box):
    client, runtime = box
    record_id = declare(client)[0]["record_id"]

    response = client.post(f"/api/services/declared/{record_id}/probe")

    assert response.status_code == 200
    assert runtime.declared_probe.probed == [record_id]
    assert response.json()["services"][0]["is_healthy"] is True

    missing = client.post("/api/services/declared/missing/probe")
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "declared_service_unknown"}


@pytest.mark.parametrize(
    "fields, refused",
    [
        ({"kind": "docker_engine"}, "kind"),
        ({"kind": "ai"}, "kind"),
        ({"name": ""}, "name"),
        ({"host": " "}, "host"),
        ({"port": None}, "port"),
        ({"port": 70000}, "port"),
        ({"kind": "file", "port": None, "shares": []}, "shares"),
    ],
)
def test_a_refused_field_is_named_in_the_error(box, fields, refused):
    client, _ = box
    body = {"name": "a", "kind": "port", "host": "h", "port": 1, **fields}

    response = client.post("/api/services/declared", json=body)

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "declared_service_invalid",
        "params": {"field": refused},
    }


def answer(monkeypatch, listing: SambaShareListing) -> None:
    """Make every scan answer with one listing."""
    monkeypatch.setattr(services, "list_shares", lambda host, **options: listing)


def test_a_scan_lists_what_the_server_exports(box, monkeypatch):
    client, _ = box
    answer(monkeypatch, SambaShareListing(names=["media", "backup"]))

    response = client.get("/api/services/shares", params={"host": "192.168.100.7"})

    assert response.status_code == 200
    assert response.json() == {"shares": ["media", "backup"]}


@pytest.mark.parametrize("reason", ["connect_failed", "tool_missing"])
def test_a_scan_that_lists_nothing_says_which_reason(box, monkeypatch, reason):
    """A server that did not answer and a hub without the client differ."""
    client, _ = box
    answer(monkeypatch, SambaShareListing(error_code=reason))

    response = client.get("/api/services/shares", params={"host": "10.0.0.9"})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "share_scan_failed",
        "params": {"reason": reason},
    }


def test_a_scan_without_a_host_is_refused_on_the_host_field(box):
    client, _ = box

    response = client.get("/api/services/shares", params={"host": " "})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "declared_service_invalid",
        "params": {"field": "host"},
    }


def test_a_file_declaration_publishes_one_row_per_share(box):
    """Taking every export a scan found declares them in one record."""
    client, _ = box

    entries = declare(
        client,
        name="nas",
        kind="file",
        host="192.168.100.7",
        port=None,
        shares=["media", "backup"],
    )

    assert [entry["payload"]["share"] for entry in entries] == ["media", "backup"]
    assert len({entry["record_id"] for entry in entries}) == 1


def test_the_list_carries_what_the_probe_measured(box):
    """The page words the code; the API never sends a sentence."""
    client, runtime = box
    record_id = declare(client)[0]["record_id"]
    runtime.declared_probe.health[record_id] = DeclaredServiceHealth(
        record_id, False, "2026-01-01T00:00:00+00:00", "share_missing"
    )
    runtime.published_services.expire()

    payload = client.get("/api/services").json()

    assert payload["services"][0]["detail_code"] == "share_missing"
