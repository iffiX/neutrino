"""The file share's folder share routes.

What these pin: the list answers the folder shares in the order they were
added with the file share's enabled accounts; an add checks the name, the
folder and the accounts in that order, has the agent check the section the
state will carry, stores ``{name, path, accounts}`` with the accounts in the
file share's order, wants the module running and pushes; a set keeps the
name; a remove takes the share and its permission row away and pushes; and
the Home shares' set refuses an account a folder share's name takes.
"""

import json

import pytest

from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.web.routers.agent import module_instances, module_samba
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, OFFLINE, module_box

PATH = "/api/agent/module/samba/folder_share"


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(
        monkeypatch,
        tmp_path,
        [module_samba.router, module_instances.ROUTERS["samba"]],
    )
    store = DesiredStateStore()
    accounts = DeviceAccountStore(store)
    for name in ("alice", "bob", "carol"):
        accounts.add(DEVICE, DeviceAccount(account=name, share_path=f"/home/{name}"))
    store.set_enabled_accounts(DEVICE, "samba", ["bob", "alice"])
    runtime.device_platform[DEVICE] = {
        "os": "linux",
        "family": "debian",
        "arch": "amd64",
    }
    with client:
        yield client, runtime


def stored(tmp_path) -> dict:
    path = tmp_path / "devices" / DEVICE / "samba.json"
    return json.loads(path.read_text())


def add(client, name="lab", path="/srv/lab", accounts=("alice", "bob")):
    return client.post(
        f"{PATH}/add",
        json={
            "device_id": DEVICE,
            "name": name,
            "path": path,
            "accounts": list(accounts),
        },
    )


def test_an_add_stores_the_share_with_its_accounts_in_the_file_shares_order(
    api, tmp_path
):
    client, runtime = api

    answer = add(client)

    assert answer.status_code == 200
    assert answer.json() == {
        "shares": [{"name": "lab", "path": "/srv/lab", "accounts": ["bob", "alice"]}],
        "accounts": ["bob", "alice"],
    }
    assert stored(tmp_path)["shares"] == [
        {"name": "lab", "path": "/srv/lab", "accounts": ["bob", "alice"]}
    ]
    (validated,) = runtime.agent_sessions.validations
    assert validated[1] == "samba"
    assert validated[2]["shares"][-1] == {
        "name": "lab",
        "path": "/srv/lab",
        "comment": "",
        "is_read_only": False,
        "valid_users": ["neutrino-bob", "neutrino-alice"],
    }
    assert runtime.desired_states.want_of(DEVICE, "samba") == "running"
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE]
    assert client.get(PATH, params={"device_id": DEVICE}).json() == answer.json()


@pytest.mark.parametrize(
    "fields, code, params",
    [
        ({"name": "has space"}, "share_name_invalid", {"name": "has space"}),
        ({"name": "x" * 65}, "share_name_invalid", {"name": "x" * 65}),
        ({"name": "Homes"}, "share_name_invalid", {"name": "Homes"}),
        ({"name": "Carol"}, "share_name_taken", {"name": "Carol"}),
        ({"name": "ALICE"}, "share_name_taken", {"name": "ALICE"}),
        ({"path": "srv/lab"}, "path_invalid", {"path": "srv/lab"}),
        ({"accounts": ["carol"]}, "share_account_not_enabled", {"account": "carol"}),
        ({"accounts": []}, "", None),
    ],
)
def test_an_add_is_refused_before_anything_is_written(
    api, tmp_path, fields, code, params
):
    client, runtime = api
    body = {
        "device_id": DEVICE,
        "name": "lab",
        "path": "/srv/lab",
        "accounts": ["alice"],
        **fields,
    }

    answer = client.post(f"{PATH}/add", json=body)

    # The models refuse an empty list. The panel's app words it body_invalid.
    assert answer.status_code == (400 if code else 422)
    if params is not None:
        assert answer.json()["detail"] == {"code": code, "params": params}
    assert "shares" not in stored(tmp_path)
    assert runtime.agent_sessions.pushes == []


def test_a_name_another_folder_share_has_or_whose_entry_ids_meet_is_taken(api):
    """``a_b`` for bob and ``a`` for ``b_bob`` would both give the entry
    ``samba_folder_<device>_a_b_bob``; names are compared without case."""
    client, runtime = api
    DeviceAccountStore(runtime.desired_states).add(
        DEVICE, DeviceAccount(account="b_bob", share_path="/home/b_bob")
    )
    runtime.desired_states.set_enabled_accounts(
        DEVICE, "samba", ["bob", "alice", "b_bob"]
    )
    assert add(client, name="a_b", accounts=["bob"]).status_code == 200

    same = add(client, name="A_B", accounts=["alice"])
    meeting = add(client, name="a", accounts=["b_bob"])

    assert same.json()["detail"] == {
        "code": "share_name_taken",
        "params": {"name": "A_B"},
    }
    assert meeting.json()["detail"] == {
        "code": "share_name_taken",
        "params": {"name": "a"},
    }


def test_a_refusal_of_the_agent_stores_nothing(api, tmp_path):
    client, runtime = api
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "share_path_relative",
        "params": {"name": "lab", "path": "/srv/lab"},
    }

    answer = add(client)

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "share_path_relative"
    assert "shares" not in stored(tmp_path)
    assert runtime.agent_sessions.pushes == []


def test_a_set_replaces_the_folder_and_the_accounts_and_keeps_the_name(api, tmp_path):
    client, _ = api
    add(client)
    add(client, name="other", path="/srv/other", accounts=["alice"])

    answer = client.post(
        f"{PATH}/set",
        json={
            "device_id": DEVICE,
            "name": "lab",
            "path": "/srv/lab2",
            "accounts": ["alice"],
        },
    )
    unknown = client.post(
        f"{PATH}/set",
        json={"device_id": DEVICE, "name": "gone", "path": "/x", "accounts": ["bob"]},
    )

    assert answer.status_code == 200
    assert stored(tmp_path)["shares"] == [
        {"name": "lab", "path": "/srv/lab2", "accounts": ["alice"]},
        {"name": "other", "path": "/srv/other", "accounts": ["alice"]},
    ]
    assert (unknown.status_code, unknown.json()["detail"]) == (
        404,
        {"code": "folder_share_unknown", "params": {"name": "gone"}},
    )


def test_a_remove_takes_the_share_and_its_permission_row_away(api, tmp_path):
    client, runtime = api
    add(client)
    clients = tmp_path / "clients" / "clients.json"
    clients.parent.mkdir(parents=True, exist_ok=True)
    clients.write_text(
        json.dumps(
            {
                "default_permission": {
                    "kinds": ["file"],
                    "entries": {f"samba_folder_{DEVICE}_lab": True},
                },
                "clients": {},
            }
        )
    )

    answer = client.post(f"{PATH}/remove", json={"device_id": DEVICE, "name": "lab"})
    again = client.post(f"{PATH}/remove", json={"device_id": DEVICE, "name": "lab"})

    assert answer.status_code == 200
    assert answer.json()["shares"] == []
    assert stored(tmp_path)["shares"] == []
    assert json.loads(clients.read_text())["default_permission"] == {"kinds": ["file"]}
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE, DEVICE]
    assert again.status_code == 404


def test_an_offline_machine_is_refused_before_anything_is_written(api, tmp_path):
    client, runtime = api
    DeviceAccountStore(runtime.desired_states).add(
        OFFLINE, DeviceAccount(account="alice", share_path="/home/alice")
    )
    runtime.desired_states.set_enabled_accounts(OFFLINE, "samba", ["alice"])
    held = runtime.desired_states.read(OFFLINE, "samba")
    held["shares"] = [{"name": "lab", "path": "/srv/lab", "accounts": ["alice"]}]
    runtime.desired_states.write(OFFLINE, "samba", held)

    added = client.post(
        f"{PATH}/add",
        json={
            "device_id": OFFLINE,
            "name": "more",
            "path": "/srv/more",
            "accounts": ["alice"],
        },
    )
    removed = client.post(f"{PATH}/remove", json={"device_id": OFFLINE, "name": "lab"})

    assert (added.status_code, added.json()["detail"]["code"]) == (
        409,
        "agent_offline",
    )
    assert (removed.status_code, removed.json()["detail"]["code"]) == (
        409,
        "agent_offline",
    )
    assert runtime.desired_states.read(OFFLINE, "samba")["shares"] == held["shares"]


def test_the_home_shares_refuse_an_account_a_folder_shares_name_takes(api):
    """Dave, made available after the folder share ``DAVE``, is refused when
    enabled, naming the folder share; disabling bob takes him out of the
    folder share in the same write."""
    client, runtime = api
    assert add(client, name="DAVE", accounts=["alice", "bob"]).status_code == 200
    DeviceAccountStore(runtime.desired_states).add(
        DEVICE, DeviceAccount(account="dave", share_path="/home/dave")
    )

    refused = client.post(
        "/api/agent/module/samba/set",
        json={"device_id": DEVICE, "accounts": ["bob", "alice", "dave"]},
    )
    narrowed = client.post(
        "/api/agent/module/samba/set",
        json={"device_id": DEVICE, "accounts": ["alice"]},
    )

    assert refused.json()["detail"] == {
        "code": "share_name_taken",
        "params": {"name": "DAVE"},
    }
    assert narrowed.status_code == 200
    assert client.get(PATH, params={"device_id": DEVICE}).json()["shares"] == [
        {"name": "DAVE", "path": "/srv/lab", "accounts": ["alice"]}
    ]
