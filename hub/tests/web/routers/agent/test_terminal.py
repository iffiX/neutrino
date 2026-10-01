"""The Terminals page's session list and the session stop.

What these pin: every online machine's reported sessions listed oldest
first with the machine's name, whoever owns them, each saying whether the
panel owns it; an entry naming no id dropped and one whose stamp is not a
number listed at 0; a stop sent
as the agent's ``stop_session`` verb and answered with the list read after
the machine's next report; an unknown device, an offline one, and a session
the machine does not hold each refused with its own code.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web import shell_bridge
from neutrino_hub.web.routers.agent import terminal
from tests.conftest import FakeDeviceRegistry, FakeModuleRuntime, managed_device

DEVICE = "d1"
OTHER = "d2"
PATH = "/api/agent/terminal/session"


def session(session_id: str, started_at: int, **fields) -> dict:
    return {"session_id": session_id, "started_at": started_at, **fields}


@pytest.fixture
def api(monkeypatch):
    devices = [
        managed_device("argon", device_id=DEVICE),
        managed_device("xenon", device_id=OTHER),
    ]
    runtime = FakeModuleRuntime(devices=devices, online=[DEVICE, OTHER])
    FakeDeviceRegistry.runtime = runtime
    monkeypatch.setattr(terminal, "DeviceRegistry", FakeDeviceRegistry)
    monkeypatch.setattr(shell_bridge, "DeviceRegistry", FakeDeviceRegistry)
    reports = {
        DEVICE: {
            "machine": {
                "sessions": [
                    session(
                        "b",
                        1790762400,
                        account="root",
                        title="htop",
                        owner="hub",
                        is_persistent=True,
                        attached_count=2,
                    ),
                    {"account": "root"},
                ]
            }
        },
        OTHER: {
            "machine": {
                "sessions": [
                    session(
                        "a",
                        1790758800,
                        owner="client:c1",
                        is_attached=True,
                        is_shared=False,
                    ),
                    {"session_id": "c", "started_at": "not a stamp"},
                ]
            }
        },
    }
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)
    app = FastAPI()
    app.include_router(terminal.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime, reports


def test_every_reported_session_is_listed_oldest_first(api):
    client, _, _ = api

    listed = client.get(PATH).json()["sessions"]

    assert [(row["device_id"], row["session_id"]) for row in listed] == [
        (OTHER, "c"),
        (OTHER, "a"),
        (DEVICE, "b"),
    ]
    assert listed[0]["started_at"] == 0
    assert listed[1]["device_name"] == "xenon"
    assert listed[1]["is_attached"] is True
    assert listed[1]["attached_count"] == 1
    assert (listed[1]["owner"], listed[1]["is_owned"]) == ("client:c1", False)
    assert listed[2] == {
        "device_id": DEVICE,
        "device_name": "argon",
        "session_id": "b",
        "account": "root",
        "started_at": 1790762400,
        "title": "htop",
        "owner": "hub",
        "owner_name": "hub",
        "is_owned": True,
        "is_attached": False,
        "is_persistent": True,
        "is_shared": False,
        "attached_count": 2,
    }


def test_a_stop_is_the_agents_stop_session_and_answers_the_fresh_list(api):
    client, runtime, reports = api

    def ended(key, module, verb, args):
        reports[DEVICE]["machine"]["sessions"] = []

    runtime.agent_sessions.after_command = ended

    answer = client.post(f"{PATH}/stop", json={"device_id": DEVICE, "session_id": "b"})

    assert answer.status_code == 200
    assert runtime.agent_sessions.commands == [
        (DEVICE, "agent", "stop_session", {"session_id": "b"})
    ]
    assert runtime.agent_sessions.waited[0][0] == DEVICE
    assert [row["session_id"] for row in answer.json()["sessions"]] == ["c", "a"]


def test_a_stop_on_an_unknown_or_offline_device_is_refused(api):
    client, runtime, _ = api

    unknown = client.post(f"{PATH}/stop", json={"device_id": "nope", "session_id": "b"})
    runtime.agent_sessions.online.discard(DEVICE)
    offline = client.post(f"{PATH}/stop", json={"device_id": DEVICE, "session_id": "b"})

    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (
        404,
        "device_unknown",
    )
    assert (offline.status_code, offline.json()["detail"]["code"]) == (
        409,
        "agent_offline",
    )
    assert runtime.agent_sessions.commands == []


def test_a_session_the_machine_does_not_hold_is_session_unknown(api):
    client, runtime, _ = api
    runtime.agent_sessions.outcomes["stop_session"] = {
        "exit_code": 0,
        "code": "session_unknown",
        "params": {},
    }

    answer = client.post(f"{PATH}/stop", json={"device_id": DEVICE, "session_id": "z"})

    assert answer.status_code == 404
    assert answer.json()["detail"] == {
        "code": "session_unknown",
        "params": {"session_id": "z"},
    }
