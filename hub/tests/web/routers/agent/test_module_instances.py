"""The shared router of the account-layer modules.

What these pin: one router per account-layer row and none for any other
module, each serving the module's read, apply and set at the module's own
path; the view lists every available account with whether the module
enables it and what the machine reports of its instance, with each
module's own field; a set replaces the enabled accounts, generates each
newly enabled account's secrets once and keeps them across a disable,
checks the section on the agent as the state will carry it, wants the
module running and pushes; an account that is not available or named
twice is refused; VS Code's set waits for its terms; and the terms route
answers the same view.
"""

import json

import pytest

from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.web.routers.agent import module_instances, module_vscode_terms
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, OFFLINE, module_box

ACCEPTED_AT = "2026-10-05T08:00:00+00:00"
EIGHT = [
    "samba",
    "terminal",
    "ssh_server",
    "vscode",
    "code_server",
    "cloudcli",
    "codeg",
    "siyuan",
]


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(
        monkeypatch,
        tmp_path,
        [*module_instances.ROUTERS.values(), module_vscode_terms.router],
    )
    store = DesiredStateStore()
    accounts = DeviceAccountStore(store)
    accounts.add(DEVICE, DeviceAccount(account="alice", shell_path="/bin/zsh"))
    accounts.add(DEVICE, DeviceAccount(account="bob", share_path="/srv/bob"))
    store.write(DEVICE, "vscode", {"terms_accepted_at": ACCEPTED_AT})
    runtime.device_platform[DEVICE] = {
        "os": "linux",
        "family": "debian",
        "arch": "amd64",
    }
    with client:
        yield client, runtime


def stored(tmp_path, module: str) -> dict:
    path = tmp_path / "devices" / DEVICE / f"{module}.json"
    return json.loads(path.read_text())


def test_the_table_gives_the_eight_account_layer_modules_a_router_and_no_other():
    assert list(module_instances.ROUTERS) == EIGHT
    assert "gitea" not in module_instances.ROUTERS
    assert "remote_desktop" not in module_instances.ROUTERS


@pytest.mark.parametrize("module", EIGHT)
def test_each_router_serves_the_read_the_apply_and_the_set_at_its_own_path(module):
    paths = sorted(
        (sorted(route.methods - {"HEAD", "OPTIONS"})[0], route.path)
        for route in module_instances.ROUTERS[module].routes
    )

    assert paths == [
        ("GET", f"/api/agent/module/{module}"),
        ("POST", f"/api/agent/module/{module}/apply"),
        ("POST", f"/api/agent/module/{module}/set"),
    ]


def test_the_view_lists_every_available_account_with_the_modules_own_field(api):
    client, runtime = api
    runtime.report(
        DEVICE,
        "ssh_server",
        state="running",
        host_key_fingerprint="SHA256:abc",
        instances=[{"account": "alice", "port": 22001, "is_running": True}],
    )
    client.post(
        "/api/agent/module/ssh_server/set",
        json={"device_id": DEVICE, "accounts": ["alice"]},
    )

    view = client.get("/api/agent/module/ssh_server", params={"device_id": DEVICE})

    assert view.status_code == 200
    body = view.json()
    assert body["host_key_fingerprint"] == "SHA256:abc"
    assert [
        (
            row["account"],
            row["is_enabled"],
            row["port"],
            row["is_running"],
            row["shell_path"],
        )
        for row in body["accounts"]
    ] == [("alice", True, 22001, True, "/bin/zsh"), ("bob", False, 0, False, "")]


def test_the_file_shares_rows_carry_the_share_path_and_the_smb_user(api):
    client, runtime = api
    runtime.device_platform[DEVICE] = {"os": "windows", "family": "", "arch": "amd64"}

    body = client.get("/api/agent/module/samba", params={"device_id": DEVICE}).json()

    assert [
        (row["account"], row["share_path"], row["user"]) for row in body["accounts"]
    ] == [
        ("alice", "", "neutrino-alice"),
        ("bob", "/srv/bob", "neutrino-bob"),
    ]


@pytest.mark.parametrize(
    "module, sealed",
    [
        ("samba", {"password_sealed"}),
        ("ssh_server", {"private_key_sealed"}),
        ("vscode", {"token_sealed"}),
        ("code_server", {"secret_sealed"}),
        ("cloudcli", {"web_password_sealed", "token_secret_sealed"}),
        ("codeg", {"secret_sealed"}),
        ("terminal", set()),
    ],
)
def test_a_set_enables_the_accounts_and_seals_each_ones_fields_once(
    api, tmp_path, module, sealed
):
    client, runtime = api

    first = client.post(
        f"/api/agent/module/{module}/set",
        json={"device_id": DEVICE, "accounts": ["bob", "alice"]},
    )
    held = stored(tmp_path, module)
    client.post(
        f"/api/agent/module/{module}/set", json={"device_id": DEVICE, "accounts": []}
    )
    again = client.post(
        f"/api/agent/module/{module}/set",
        json={"device_id": DEVICE, "accounts": ["bob"]},
    )

    assert first.status_code == 200, first.text
    assert [row["account"] for row in held["accounts"]] == ["bob", "alice"]
    assert set(held["accounts"][0]) == {"account", *sealed}
    assert again.status_code == 200
    kept = stored(tmp_path, module)["accounts"][0]
    assert kept == held["accounts"][0]
    assert [row["is_enabled"] for row in again.json()["accounts"]] == [False, True]
    assert [(key, mod) for key, mod, _ in runtime.agent_sessions.validations] == [
        (DEVICE, module)
    ] * 3
    assert runtime.desired_states.want_of(DEVICE, module) == (
        "" if module in ("terminal", "ssh_server") else "running"
    )
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE] * 3


def test_a_siyuan_account_gets_a_gateway_key_while_it_is_enabled(
    api, tmp_path, monkeypatch
):
    from neutrino_hub.modules.clients import ai_keys

    applied: list = []
    monkeypatch.setattr(ai_keys, "_apply", lambda **kwargs: applied.append(kwargs))
    client, runtime = api

    first = client.post(
        "/api/agent/module/siyuan/set",
        json={"device_id": DEVICE, "accounts": ["bob", "alice"]},
    )
    held = stored(tmp_path, "siyuan")["accounts"]
    client.post(
        "/api/agent/module/siyuan/set", json={"device_id": DEVICE, "accounts": []}
    )
    disabled = stored(tmp_path, "siyuan")["disabled"]
    client.post(
        "/api/agent/module/siyuan/set", json={"device_id": DEVICE, "accounts": ["bob"]}
    )
    again = stored(tmp_path, "siyuan")["accounts"][0]

    assert first.status_code == 200, first.text
    assert set(held[0]) == {
        "account",
        "secret_sealed",
        "access_code_sealed",
        "gateway_key_sealed",
    }
    assert held[0]["gateway_key_sealed"]["name"].endswith("/siyuan/bob")
    assert all("gateway_key_sealed" not in record for record in disabled)
    assert again["secret_sealed"] == held[0]["secret_sealed"]
    assert again["access_code_sealed"] == held[0]["access_code_sealed"]
    assert again["gateway_key_sealed"]["id"] != held[0]["gateway_key_sealed"]["id"]
    assert len(applied) == 3
    _, module, section = runtime.agent_sessions.validations[0]
    assert module == "siyuan"
    assert [instance["account"] for instance in section["instances"]] == [
        "bob",
        "alice",
    ]
    assert all(instance["gateway_key"] for instance in section["instances"])
    assert section["gateway_url"] == "http://127.0.0.1:8317"


def test_the_agent_checks_the_section_the_state_will_carry(api):
    client, runtime = api

    client.post(
        "/api/agent/module/terminal/set",
        json={"device_id": DEVICE, "accounts": ["alice"]},
    )

    assert runtime.agent_sessions.validations == [
        (
            DEVICE,
            "terminal",
            {"accounts": [{"account": "alice", "shell_path": "/bin/zsh"}]},
        )
    ]


def test_an_account_that_is_not_available_or_named_twice_is_refused(api, tmp_path):
    client, runtime = api

    unknown = client.post(
        "/api/agent/module/samba/set", json={"device_id": DEVICE, "accounts": ["eve"]}
    )
    twice = client.post(
        "/api/agent/module/samba/set",
        json={"device_id": DEVICE, "accounts": ["alice", "alice"]},
    )

    assert unknown.status_code == 400
    assert unknown.json()["detail"] == {
        "code": "account_unknown",
        "params": {"account": "eve"},
    }
    assert twice.json()["detail"] == {
        "code": "account_duplicate",
        "params": {"account": "alice"},
    }
    assert not (tmp_path / "devices" / DEVICE / "samba.json").exists()
    assert runtime.agent_sessions.pushes == []


def test_a_section_the_agent_refuses_is_put_back_and_not_pushed(api, tmp_path):
    client, runtime = api
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "account_invalid",
        "params": {"account": "alice"},
    }

    answer = client.post(
        "/api/agent/module/codeg/set", json={"device_id": DEVICE, "accounts": ["alice"]}
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "account_invalid"
    assert runtime.desired_states.enabled_accounts(DEVICE, "codeg") == []
    assert runtime.agent_sessions.pushes == []


def test_a_share_account_with_no_path_and_no_reported_home_reads_home_unknown(api):
    client, runtime = api
    runtime.device_platform[DEVICE] = {"os": "windows", "family": "", "arch": "amd64"}
    runtime.device_account_details[DEVICE] = {"alice": {"home": "", "shell": ""}}
    client.post(
        "/api/agent/module/samba/set",
        json={"device_id": DEVICE, "accounts": ["alice", "bob"]},
    )

    rows = {
        row["account"]: row
        for row in client.get(
            "/api/agent/module/samba", params={"device_id": DEVICE}
        ).json()["accounts"]
    }
    runtime.device_account_details[DEVICE] = {
        "alice": {"home": "C:\\Users\\alice", "shell": ""}
    }
    later = {
        row["account"]: row
        for row in client.get(
            "/api/agent/module/samba", params={"device_id": DEVICE}
        ).json()["accounts"]
    }

    assert (rows["alice"]["code"], rows["alice"]["params"]) == (
        "account_home_unknown",
        {"account": "alice"},
    )
    assert rows["bob"]["code"] == ""
    assert later["alice"]["code"] == ""
    pushed = runtime.agent_sessions.validations[-1][2]
    assert [share["name"] for share in pushed["shares"]] == ["bob"]


def test_an_offline_machine_is_refused_before_anything_is_written(api, tmp_path):
    client, _ = api

    answer = client.post(
        "/api/agent/module/samba/set", json={"device_id": OFFLINE, "accounts": []}
    )

    assert (answer.status_code, answer.json()["detail"]["code"]) == (
        409,
        "agent_offline",
    )


def test_vscode_waits_for_its_terms_and_the_terms_route_answers_the_view(api, tmp_path):
    client, _ = api
    client.post(
        "/api/agent/module/vscode/terms/set",
        json={"device_id": DEVICE, "is_accepted": False},
    )

    refused = client.post(
        "/api/agent/module/vscode/set",
        json={"device_id": DEVICE, "accounts": ["alice"]},
    )
    accepted = client.post(
        "/api/agent/module/vscode/terms/set",
        json={"device_id": DEVICE, "is_accepted": True},
    )
    allowed = client.post(
        "/api/agent/module/vscode/set",
        json={"device_id": DEVICE, "accounts": ["alice"]},
    )

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "terms_not_accepted"
    assert accepted.json()["is_terms_accepted"] is True
    assert accepted.json()["terms_url"]
    assert allowed.status_code == 200
    assert "terms_accepted_at" in stored(tmp_path, "vscode")


def test_a_file_share_row_runs_while_the_machine_serves_its_home_share(api):
    client, runtime = api
    client.post(
        "/api/agent/module/samba/set",
        json={"device_id": DEVICE, "accounts": ["alice", "bob"]},
    )
    runtime.report(
        DEVICE,
        "samba",
        state="running",
        is_active=True,
        shares=[{"name": "alice", "path": "/home/alice", "params": {}}],
    )

    rows = {
        row["account"]: row
        for row in client.get(
            "/api/agent/module/samba", params={"device_id": DEVICE}
        ).json()["accounts"]
    }

    assert (rows["alice"]["is_running"], rows["bob"]["is_running"]) == (True, False)
