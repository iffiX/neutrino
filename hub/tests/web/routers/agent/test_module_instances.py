"""The shared router of the programs run as a person's account.

What these pin: one router per row of that kind and none for any other
module, each serving the module's read, apply and set at the module's own
path; a set on each module stores the fields its row seals and no other
module's; and the three views carry their own fields, VS Code's terms and
code-server's release, from the one builder.
"""

import json

import pytest

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.web.routers.agent import module_instances
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, module_box

ACCEPTED_AT = "2026-10-05T08:00:00+00:00"


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(
        monkeypatch, tmp_path, list(module_instances.ROUTERS.values())
    )
    DesiredStateStore().write(DEVICE, "vscode", {"terms_accepted_at": ACCEPTED_AT})
    with client:
        yield client, runtime


def stored(tmp_path, module: str) -> list:
    path = tmp_path / "devices" / DEVICE / f"{module}.json"
    return json.loads(path.read_text())["instances"]


def test_the_table_resolves_the_three_programs_and_no_other_module():
    assert list(module_instances.ROUTERS) == ["vscode", "code_server", "cloudcli"]
    assert "samba" not in module_instances.ROUTERS
    assert "terminal" not in module_instances.ROUTERS
    assert "gitea" not in module_instances.ROUTERS


@pytest.mark.parametrize("module", ["vscode", "code_server", "cloudcli"])
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


@pytest.mark.parametrize(
    "module, port, sealed",
    [
        ("vscode", 8000, {"login_id", "token_sealed"}),
        ("code_server", 8443, {"secret_sealed"}),
        ("cloudcli", 3001, {"login_id", "web_password_sealed", "token_secret_sealed"}),
    ],
)
def test_a_set_stores_the_fields_the_modules_row_seals_and_no_others(
    api, tmp_path, module, port, sealed
):
    client, _runtime = api

    answer = client.post(
        f"/api/agent/module/{module}/set",
        json={"device_id": DEVICE, "instances": [{"account": "alice", "port": port}]},
    )

    assert answer.status_code == 200
    (instance,) = stored(tmp_path, module)
    assert set(instance) == {"account", "port"} | sealed
    for name in ("vscode", "code_server", "cloudcli"):
        if name != module:
            assert not (tmp_path / "devices" / DEVICE / f"{name}.json").exists() or (
                name == "vscode"
            )


def test_each_view_carries_its_own_fields_from_the_one_builder(api):
    client, runtime = api
    runtime.report(DEVICE, "code_server", state="running", version="4.140.0")

    vscode = client.get("/api/agent/module/vscode", params={"device_id": DEVICE})
    code_server = client.get(
        "/api/agent/module/code_server", params={"device_id": DEVICE}
    )
    cloudcli = client.get("/api/agent/module/cloudcli", params={"device_id": DEVICE})

    assert vscode.json()["is_terms_accepted"] is True
    assert vscode.json()["terms_url"] == "https://aka.ms/vscode-server-license"
    assert "version" not in vscode.json()
    assert code_server.json()["version"] == "4.140.0"
    assert "is_terms_accepted" not in code_server.json()
    assert "version" not in cloudcli.json()
    assert "is_terms_accepted" not in cloudcli.json()
    for view in (vscode, code_server, cloudcli):
        assert view.json()["instances"] == []
        assert view.json()["device_id"] == DEVICE
