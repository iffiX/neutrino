"""The Containers page's per-device API, with the agent underneath replaced."""

import pytest

from neutrino_hub.web.routers import podman as podman_router
from tests.web.module_api_box import DEVICE, HOST, OFFLINE, module_box

BASE = f"/api/podman/devices/{DEVICE}"


@pytest.fixture
def box(monkeypatch, tmp_path):
    client, runtime = module_box(monkeypatch, tmp_path, podman_router.router)
    runtime.desired_states.write(
        DEVICE,
        "podman",
        {
            "containers": [{"name": "web", "image": "nginx", "ports": ["8080:80"]}],
            "mirrors": [],
        },
    )
    runtime.report(
        DEVICE,
        "podman",
        "installed",
        is_active=True,
        version="4.9.3",
        containers=[
            {
                "name": "web",
                "image": "nginx",
                "status": "Up",
                "is_running": True,
                "is_declared": True,
                "host_ports": [8080],
            },
            {
                "name": "adhoc",
                "image": "alpine",
                "status": "Exited",
                "is_running": False,
                "is_declared": False,
                "host_ports": [],
            },
        ],
    )
    with client:
        yield client, runtime


def test_the_view_separates_declared_from_ad_hoc(box):
    client, _ = box

    payload = client.get(BASE).json()

    assert [c["name"] for c in payload["containers"]] == ["web"]
    by_name = {c["name"]: c for c in payload["running"]}
    assert by_name["web"]["is_declared"] is True
    assert by_name["adhoc"]["is_declared"] is False
    assert payload["is_installed"] is True
    assert payload["is_active"] is True
    assert payload["version"] == "4.9.3"
    assert (payload["device_id"], payload["host"]) == (DEVICE, HOST)


def test_saving_containers_checks_stores_and_pushes(box):
    client, runtime = box

    response = client.put(
        f"{BASE}/containers",
        json={"containers": [{"name": "redis", "image": "redis:7"}]},
    )

    assert response.status_code == 200
    key, module, checked = runtime.agent_sessions.validations[0]
    assert (key, module) == (DEVICE, "podman")
    assert [c["name"] for c in checked["containers"]] == ["redis"]
    assert (
        runtime.desired_states.read(DEVICE, "podman")["containers"][0]["name"]
        == "redis"
    )
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE]


def test_a_bad_declaration_is_refused_and_nothing_stored(box):
    client, runtime = box
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "container_name_invalid",
        "params": {"name": "Bad"},
    }

    response = client.put(
        f"{BASE}/containers", json={"containers": [{"name": "Bad", "image": "x"}]}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "container_name_invalid"
    assert (
        runtime.desired_states.read(DEVICE, "podman")["containers"][0]["name"] == "web"
    )


def test_saving_mirrors_keeps_the_containers(box):
    client, runtime = box

    response = client.put(f"{BASE}/mirrors", json={"mirrors": ["mirror.example"]})

    assert response.status_code == 200
    stored = runtime.desired_states.read(DEVICE, "podman")
    assert stored["mirrors"] == ["mirror.example"]
    assert stored["containers"][0]["name"] == "web"
    assert response.json()["mirrors"] == ["mirror.example"]


def test_a_container_is_driven_on_the_device_and_the_view_answers(box):
    client, runtime = box

    response = client.post(f"{BASE}/containers/web/restart")

    assert response.status_code == 200
    assert runtime.agent_sessions.commands == [
        (DEVICE, "podman_control", {"name": "web", "action": "restart"})
    ]
    assert response.json()["device_id"] == DEVICE


def test_a_container_the_agent_does_not_know_is_answered_with_its_code(box):
    client, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 1,
        "code": "container_unknown",
        "params": {"name": "ghost"},
        "output": "",
    }

    response = client.post(f"{BASE}/containers/ghost/start")

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "container_unknown",
        "params": {"name": "ghost"},
    }


def test_the_journal_is_read_on_the_device(box):
    client, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 0,
        "code": "",
        "params": {},
        "output": "one\ntwo\nthree",
    }

    response = client.get(f"{BASE}/containers/web/journal?lines=2")

    assert response.json() == {"text": "two\nthree"}
    assert runtime.agent_sessions.commands == [
        (DEVICE, "podman_journal", {"name": "web"})
    ]


def test_an_offline_device_takes_no_verb(box):
    client, runtime = box

    assert (
        client.post(f"/api/podman/devices/{OFFLINE}/containers/web/start").status_code
        == 409
    )
    assert (
        client.get(f"/api/podman/devices/{OFFLINE}/containers/web/journal").status_code
        == 409
    )
    assert runtime.agent_sessions.commands == []


def test_hub_urls_resolve_and_foreign_registries_decline():
    assert "repositories/library/python/tags" in podman_router.hub_tags_url("python")
    assert "repositories/library/redis/tags" in podman_router.hub_tags_url(
        "docker.io/library/redis:7"
    )
    assert "repositories/ann/tool/tags" in podman_router.hub_tags_url(
        "docker.io/ann/tool"
    )
    assert podman_router.hub_tags_url("ghcr.io/owner/thing") is None
    assert podman_router.hub_tags_url("quay.io/owner/thing:1") is None


def test_tags_come_from_docker_hub_best_effort(box, monkeypatch):
    client, _ = box
    monkeypatch.setattr(
        podman_router,
        "list_image_tags",
        lambda image: ["3.12", "3.11"] if image == "python" else [],
    )

    assert client.get(f"{BASE}/tags?image=python").json() == {"tags": ["3.12", "3.11"]}
    assert client.get(f"{BASE}/tags?image=ghcr.io/x/y").json() == {"tags": []}
