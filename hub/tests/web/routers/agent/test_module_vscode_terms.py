"""The terms route: the person's acceptance of Microsoft's terms for one machine.

What these pin: the press records the acceptance once with its time and
pushes nothing, a false withdraws it and keeps the instances, an unknown
device is refused by code, and a device directory that cannot be written is
a coded refusal.
"""

import json

import pytest

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.web.routers.agent import module_instances, module_vscode_terms
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, module_box

BASE = "/api/agent/module/vscode"
ACCEPTED_AT = "2026-10-05T08:00:00+00:00"


@pytest.fixture
def bare(monkeypatch, tmp_path):
    """The terms route beside the block, on a machine nobody accepted for yet."""
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(
        monkeypatch,
        tmp_path,
        [module_instances.ROUTERS["vscode"], module_vscode_terms.router],
    )
    with client:
        yield client, runtime


@pytest.fixture
def api(bare):
    """The same, on a machine whose terms the person accepted."""
    DesiredStateStore().write(DEVICE, "vscode", {"terms_accepted_at": ACCEPTED_AT})
    return bare


def stored_file(tmp_path) -> dict:
    return json.loads((tmp_path / "devices" / DEVICE / "vscode.json").read_text())


def test_the_press_records_the_acceptance_once_with_its_time(bare, tmp_path):
    client, runtime = bare

    first = client.post(
        f"{BASE}/terms/set", json={"device_id": DEVICE, "is_accepted": True}
    )
    recorded = stored_file(tmp_path)["terms_accepted_at"]
    again = client.post(
        f"{BASE}/terms/set", json={"device_id": DEVICE, "is_accepted": True}
    )

    assert first.status_code == 200 and first.json()["is_terms_accepted"] is True
    assert again.json()["is_terms_accepted"] is True
    assert stored_file(tmp_path)["terms_accepted_at"] == recorded
    assert recorded.endswith("+00:00")
    assert runtime.agent_sessions.pushes == []


def test_false_withdraws_the_acceptance_and_keeps_the_instances(api, tmp_path):
    client, _ = api
    client.post(
        f"{BASE}/set",
        json={"device_id": DEVICE, "instances": [{"account": "alice", "port": 8000}]},
    )

    answer = client.post(
        f"{BASE}/terms/set", json={"device_id": DEVICE, "is_accepted": False}
    )

    assert answer.json()["is_terms_accepted"] is False
    assert "terms_accepted_at" not in stored_file(tmp_path)
    assert stored_file(tmp_path)["instances"][0]["account"] == "alice"


def test_the_terms_of_an_unknown_device_are_refused(bare):
    client, _ = bare

    answer = client.post(
        f"{BASE}/terms/set", json={"device_id": "nope", "is_accepted": True}
    )

    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "device_unknown"


def test_a_device_directory_that_cannot_be_written_is_a_coded_refusal(
    bare, monkeypatch
):
    client, _ = bare

    def unwritable(self, key, module, config):
        raise PermissionError(1, "Operation not permitted", "devices/x/.tmp")

    monkeypatch.setattr(DesiredStateStore, "write", unwritable)

    answer = client.post(
        f"{BASE}/terms/set", json={"device_id": DEVICE, "is_accepted": True}
    )

    assert answer.status_code == 500
    assert answer.json()["detail"]["code"] == "config_unwritable"
    assert "Operation not permitted" in answer.json()["detail"]["params"]["detail"]
