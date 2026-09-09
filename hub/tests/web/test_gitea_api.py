"""The Gitea page's per-device API, with the agent underneath replaced."""

import pytest

from neutrino_hub.web.routers import gitea as gitea_router
from tests.web.module_api_box import DEVICE, HOST, OFFLINE, module_box

BASE = f"/api/gitea/devices/{DEVICE}"


@pytest.fixture
def box(monkeypatch, tmp_path):
    client, runtime = module_box(monkeypatch, tmp_path, gitea_router.router)
    runtime.desired_states.write(
        DEVICE,
        "gitea",
        {"listen_port": 3000, "root_url": "", "is_registration_enabled": False},
    )
    runtime.report(
        DEVICE,
        "gitea",
        "installed",
        is_running=True,
        url=f"http://{HOST}:3000/",
        version="1.27.3",
        admins=[],
    )
    with client:
        yield client, runtime


def test_the_view_reports_config_beside_reality(box):
    client, _ = box

    payload = client.get(BASE).json()

    assert payload["listen_port"] == 3000
    assert payload["is_installed"] is True
    assert payload["is_active"] is True
    assert payload["version"] == "1.27.3"
    assert payload["has_admin"] is False
    assert payload["admin_usernames"] == []
    assert payload["url"] == f"http://{HOST}:3000/"
    assert (payload["device_id"], payload["host"], payload["is_online"]) == (
        DEVICE,
        HOST,
        True,
    )


def test_a_device_that_never_reported_reads_as_not_installed(box):
    client, _ = box

    payload = client.get(f"/api/gitea/devices/{OFFLINE}").json()

    assert payload["is_installed"] is False
    assert payload["is_online"] is False
    assert payload["listen_port"] == 3000


def test_saving_settings_checks_stores_and_pushes(box):
    client, runtime = box

    response = client.put(
        BASE,
        json={
            "listen_port": 3100,
            "root_url": "http://box:3100/",
            "is_registration_enabled": True,
        },
    )

    assert response.status_code == 200
    assert runtime.agent_sessions.validations == [
        (
            DEVICE,
            "gitea",
            {
                "listen_port": 3100,
                "root_url": "http://box:3100/",
                "is_registration_enabled": True,
            },
        )
    ]
    assert runtime.desired_states.read(DEVICE, "gitea")["listen_port"] == 3100
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE]
    assert response.json()["root_url"] == "http://box:3100/"


def test_a_port_the_agent_refuses_is_refused_and_nothing_stored(box):
    client, runtime = box
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "port_reserved",
        "params": {"port": 80},
    }

    response = client.put(BASE, json={"listen_port": 80})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "port_reserved",
        "params": {"port": 80},
    }
    assert runtime.desired_states.read(DEVICE, "gitea")["listen_port"] == 3000


def test_the_first_admin_is_made_on_the_device(box):
    client, runtime = box

    response = client.post(
        f"{BASE}/admin",
        json={"username": "ann", "password": "pw", "email": "a@x"},  # scan: allow
    )

    assert response.status_code == 200
    assert runtime.agent_sessions.commands == [
        (DEVICE, "gitea_admin", {"username": "ann", "password": "pw", "email": "a@x"})
    ]
    assert response.json()["device_id"] == DEVICE


def test_a_second_admin_the_agent_refuses_is_answered_with_its_code(box):
    client, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 1,
        "code": "admin_exists",
        "params": {},
        "output": "",
    }

    response = client.post(
        f"{BASE}/admin", json={"username": "bob", "password": "pw", "email": "b@x"}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {"code": "admin_exists", "params": {}}


def test_a_password_reset_rides_the_command(box):
    client, runtime = box

    response = client.post(f"{BASE}/admin/ann/password", json={"password": "pw2"})

    assert response.status_code == 200
    assert runtime.agent_sessions.commands == [
        (DEVICE, "gitea_password", {"username": "ann", "password": "pw2"})
    ]


def test_an_offline_device_takes_no_verb(box):
    client, runtime = box

    edit = client.put(f"/api/gitea/devices/{OFFLINE}", json={"listen_port": 3000})
    admin = client.post(
        f"/api/gitea/devices/{OFFLINE}/admin",
        json={"username": "ann", "password": "pw", "email": "a@x"},
    )

    assert edit.status_code == 409 and admin.status_code == 409
    assert runtime.agent_sessions.commands == []
