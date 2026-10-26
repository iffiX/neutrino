"""The Services API: the apps, the entries of no app, declarations and codes.

What these pin: ``GET /api/hub/service`` answers ``apps``, a module's first,
then the declared, then the manual, each by title, with each entry's
``local_port`` and ``detail_code``, and ``services``, the entries of no
app; declaring an app with its entries answers the list with it, a bad
field ``declared_service_invalid {field}``; removing and probing name the
app by ``app_id``, an unknown one ``declared_service_unknown``.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.services.config import DeclaredAppRegistry
from neutrino_hub.modules.services.host_scope import HostScope
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import service as services

DEVICE = "d1"
LAN = HostScope(
    id="192.168.100.0/24", cidr="192.168.100.0/24", hub_address="192.168.100.1"
)


class StubPublished:
    def __init__(self):
        self.expired = 0
        self.held_apps = [
            {
                "id": "zzz",
                "title": "Zed",
                "source": "manual",
                "device_id": DEVICE,
                "device_name": "argon",
                "local_name": "zed.argon.localhost",
                "description": "",
            },
            {
                "id": "gitea_d1",
                "title": "Gitea",
                "source": "module",
                "device_id": DEVICE,
                "device_name": "argon",
                "local_name": "gitea.argon.localhost",
                "description": "",
            },
        ]
        self.held_entries = [
            {
                "id": "gitea_d1_web",
                "type": "web",
                "title": "Gitea",
                "payload": {"url": "http://192.168.100.7:3000/"},
                "is_healthy": True,
                "source": "module",
                "description": "d",
                "description_code": "gitea_module",
                "description_params": {},
                "detail_code": None,
                "device_id": DEVICE,
                "app_id": "gitea_d1",
                "name": "web",
                "local_port": 25000,
            },
            {
                "id": "zzz_25565",
                "type": "port",
                "title": "Zed",
                "payload": {"host": "192.168.100.7", "port": 25565, "protocol": "tcp"},
                "is_healthy": False,
                "source": "manual",
                "description": "",
                "description_code": "container",
                "description_params": {},
                "detail_code": None,
                "device_id": DEVICE,
                "app_id": "zzz",
                "name": "25565",
                "local_port": 25001,
            },
            {
                "id": "ai",
                "type": "ai",
                "title": "AI",
                "payload": {
                    "endpoint": "http://192.168.100.1:8317",
                    "protocol": "openai",
                    "models": [],
                },
                "is_healthy": True,
                "source": "module",
                "description": "",
                "description_code": "ai_gateway",
                "description_params": {},
                "detail_code": None,
                "device_id": "",
                "app_id": "",
                "name": "",
                "local_port": 0,
            },
        ]

    def entries_for(self, scope):
        return list(self.held_entries)

    def apps(self):
        return list(self.held_apps)

    def expire(self):
        self.expired += 1


class Probe:
    def __init__(self):
        self.probed: list = []

    def probe(self, app):
        self.probed.append(app.id)
        return []


class Runtime:
    def __init__(self):
        self.published_services = StubPublished()
        self.declared_probe = Probe()

    def host_scopes(self):
        return [LAN]

    def device_names(self):
        return {DEVICE: "argon"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    app = FastAPI()
    app.include_router(services.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = Runtime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_the_list_is_the_apps_in_order_and_the_entries_of_no_app(api):
    client, _ = api

    body = client.get("/api/hub/service").json()

    assert [app["id"] for app in body["apps"]] == ["gitea_d1", "zzz"]
    assert body["apps"][0]["entries"] == [
        {
            "id": "gitea_d1_web",
            "name": "web",
            "type": "web",
            "payload": {"url": "http://192.168.100.7:3000/"},
            "is_healthy": True,
            "local_port": 25000,
            "detail_code": None,
        }
    ]
    assert body["apps"][0]["local_name"] == "gitea.argon.localhost"
    assert [entry["id"] for entry in body["services"]] == ["ai"]
    assert body["services"][0]["app_id"] == ""


def test_declaring_an_app_stores_it_and_answers_the_list(api):
    client, runtime = api

    answer = client.post(
        "/api/hub/service/declaration/add",
        json={
            "name": "NAS",
            "host": "192.168.100.50",
            "description": "",
            "entries": [
                {"type": "web", "port": 443, "scheme": "https"},
                {"type": "file", "share": "media"},
            ],
        },
    )

    assert answer.status_code == 200, answer.text
    (app,) = DeclaredAppRegistry().list_apps()
    assert [entry.name for entry in app.entries] == ["web_443", "file_media"]
    assert runtime.published_services.expired == 1


def test_a_bad_declaration_is_refused_by_field(api):
    client, _ = api

    answer = client.post(
        "/api/hub/service/declaration/add",
        json={"name": "x", "host": "h", "entries": [{"type": "web"}]},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == {
        "code": "declared_service_invalid",
        "params": {"field": "entries.0.port"},
    }


def test_removing_and_probing_name_the_app(api):
    client, runtime = api
    app = DeclaredAppRegistry().add(
        name="NAS", host="h", entries=[{"type": "port", "port": 22}], description=""
    )

    probed = client.post("/api/hub/service/declaration/probe", json={"app_id": app.id})
    removed = client.post(
        "/api/hub/service/declaration/remove", json={"app_id": app.id}
    )
    unknown = client.post(
        "/api/hub/service/declaration/remove", json={"app_id": app.id}
    )

    assert probed.status_code == 200
    assert runtime.declared_probe.probed == [app.id]
    assert removed.status_code == 200
    assert DeclaredAppRegistry().list_apps() == []
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "declared_service_unknown"
