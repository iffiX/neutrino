"""The Samba page's per-device API, with the agent underneath replaced.

What is exercised is the request path: the view composed from the stored
configuration and the last report, each save checked on the agent before
it lands and is pushed, the one rule with teeth, removing a user scrubs it
from every share that named it, and the password as the one imperative
verb answering the user's state.
"""

import pytest

from neutrino_hub.web.routers import samba as samba_router
from tests.web.module_api_box import DEVICE, HOST, OFFLINE, module_box

BASE = f"/api/samba/devices/{DEVICE}"
CONFIG = {
    "shares": [
        {"name": "share", "path": "/srv/share", "valid_users": []},
        {"name": "mine", "path": "/srv/mine", "valid_users": ["ann"]},
    ],
    "users": ["ann", "bob"],
}


@pytest.fixture
def box(monkeypatch, tmp_path):
    client, runtime = module_box(monkeypatch, tmp_path, samba_router.router)
    runtime.desired_states.write(DEVICE, "samba", CONFIG)
    runtime.desired_states.write(OFFLINE, "samba", CONFIG)
    runtime.report(
        DEVICE,
        "samba",
        "installed",
        is_active=True,
        sessions=[
            {
                "username": "ann",
                "hostname": "pc",
                "remote_address": "10.0.0.2",
                "shares": ["share"],
            }
        ],
        disk_usage=[{"share": "share", "total_bytes": 10, "free_bytes": 4}],
        users=[
            {"name": "ann", "is_present": True, "has_password": True},
            {"name": "bob", "is_present": True, "has_password": False},
        ],
    )
    with client:
        yield client, runtime


def test_the_view_reports_shares_surveyed_users_and_the_live_parts(box):
    client, _ = box

    payload = client.get(BASE).json()

    assert [share["name"] for share in payload["shares"]] == ["share", "mine"]
    assert payload["shares"][1]["valid_users"] == ["ann"]
    assert [user["name"] for user in payload["users"]] == ["ann", "bob"]
    assert payload["users"][0]["has_password"] is True
    assert payload["users"][1]["has_password"] is False
    assert payload["is_active"] is True
    assert payload["sessions"][0]["username"] == "ann"
    assert payload["disks"] == [{"share": "share", "total_bytes": 10, "free_bytes": 4}]
    assert (payload["device_id"], payload["host"]) == (DEVICE, HOST)
    assert (payload["is_online"], payload["state"]) == (True, "installed")


def test_the_status_route_carries_the_live_parts_alone(box):
    client, _ = box

    payload = client.get(f"{BASE}/status").json()

    assert set(payload) == {"is_active", "sessions", "disks"}
    assert payload["is_active"] is True


def test_an_offline_device_reads_but_its_users_have_no_state(box):
    client, _ = box

    payload = client.get(f"/api/samba/devices/{OFFLINE}").json()

    assert payload["is_online"] is False
    assert [share["name"] for share in payload["shares"]] == ["share", "mine"]
    assert all(not user["is_present"] for user in payload["users"])


def test_saving_shares_checks_on_the_agent_stores_and_pushes(box):
    client, runtime = box

    response = client.put(
        f"{BASE}/shares", json={"shares": [{"name": "media", "path": "/srv/media"}]}
    )

    assert response.status_code == 200
    key, module, checked = runtime.agent_sessions.validations[0]
    assert (key, module) == (DEVICE, "samba")
    assert [share["name"] for share in checked["shares"]] == ["media"]
    assert checked["users"] == ["ann", "bob"]
    stored = runtime.desired_states.read(DEVICE, "samba")
    assert [share["name"] for share in stored["shares"]] == ["media"]
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE]
    assert [share["name"] for share in response.json()["shares"]] == ["media"]


def test_a_share_the_agent_refuses_is_refused_and_nothing_is_stored(box):
    client, runtime = box
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "share_name_reserved",
        "params": {"name": "global"},
    }

    response = client.put(
        f"{BASE}/shares", json={"shares": [{"name": "global", "path": "/srv/x"}]}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "share_name_reserved",
        "params": {"name": "global"},
    }
    stored = runtime.desired_states.read(DEVICE, "samba")
    assert [share["name"] for share in stored["shares"]] == ["share", "mine"]


def test_removing_a_user_scrubs_it_from_the_shares_that_named_it(box):
    client, runtime = box

    response = client.put(f"{BASE}/users", json={"users": ["bob"]})

    assert response.status_code == 200
    stored = runtime.desired_states.read(DEVICE, "samba")
    assert stored["users"] == ["bob"]
    restricted = next(share for share in stored["shares"] if share["name"] == "mine")
    assert restricted["valid_users"] == []


def test_an_offline_device_cannot_be_edited(box):
    client, runtime = box

    response = client.put(f"/api/samba/devices/{OFFLINE}/users", json={"users": []})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent_offline"
    assert runtime.desired_states.read(OFFLINE, "samba")["users"] == ["ann", "bob"]


def test_a_password_lands_only_on_a_configured_user(box):
    client, runtime = box

    good = client.post(f"{BASE}/users/ann/password", json={"password": "s3cret"})
    bad = client.post(f"{BASE}/users/ghost/password", json={"password": "x"})

    assert good.status_code == 200
    assert good.json() == {"name": "ann", "is_present": True, "has_password": True}
    assert bad.status_code == 404
    assert bad.json()["detail"]["code"] == "user_unknown"
    assert runtime.agent_sessions.commands == [
        (DEVICE, "samba_set_password", {"name": "ann", "password": "s3cret"})
    ]


def test_a_password_samba_refuses_is_answered_with_the_agents_code(box):
    client, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 1,
        "code": "command_failed",
        "params": {"detail": "no such account"},
        "output": "",
    }

    response = client.post(f"{BASE}/users/ann/password", json={"password": "x"})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "command_failed"


def test_apply_pushes_the_state_again(box):
    client, runtime = box

    payload = client.post(f"{BASE}/apply").json()

    assert payload["is_applied"] is True
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE]
