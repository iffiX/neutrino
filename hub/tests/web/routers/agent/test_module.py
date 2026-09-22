"""A device's Modules page, and the one door every module block goes through.

The page: management is a completed handshake, so a failed install or a
forgotten device never reads managed here; each row is what the agent last
reported beside what the hub asks of it; the four presses write one
``want`` each and push it, refuse an offline device before writing, and a
user-tier module takes none; the task carrying a module's install lines is
named on its row. The door: the per-device read carrying the module's own
fields beside the shared ones, an import that writes what the machine
reports only where the hub holds no configuration yet, a configuration
checked on the agent as the module's ``validate`` verb before it is stored
and pushed, and a module verb run on the agent and answering the fresh
view.
"""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.channel_serve import module_task_label
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import ModuleDeviceFields
from neutrino_hub.web.routers.agent import module as device_modules
from tests.conftest import FakeDeviceRegistry, FakeModuleRuntime, managed_device
from tests.web.device_api_box import DEVICE, device_box

MODULE_PATH = "/api/agent/module"


# --- the Modules page of a device: what it is told, and what it can act on ---


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    client, runtime = device_box(monkeypatch, device_modules)
    with client:
        yield client, runtime


def modules_file(tmp_path) -> dict:
    path = tmp_path / "devices" / DEVICE / "modules.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())["modules"]


def test_an_agent_with_no_socket_is_not_online(api):
    client, _ = api

    answer = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()

    assert answer["is_agent_managed"]
    assert not answer["is_agent_online"]


def test_an_agent_holding_a_socket_is_online(api):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)

    answer = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()

    assert answer["is_agent_online"]


def test_an_agent_whose_socket_closed_is_not_online(api):
    """Which is the reported bug: the install flag stays true for ever, so
    this device drew every module as absent while its remote desktop was
    plainly running."""
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.agent_sessions.online.discard(DEVICE)

    answer = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()

    assert answer["is_agent_managed"]
    assert not answer["is_agent_online"]


def test_the_journal_is_read_on_the_agent_under_the_modules_name(api):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.agent_sessions.outcome = {
        "exit_code": 0,
        "code": "",
        "params": {},
        "output": "one\ntwo\nthree\n",
    }

    answer = client.get(
        f"{MODULE_PATH}/journal",
        params={"device_id": DEVICE, "module": "fakedesk", "lines": 2},
    )

    assert answer.status_code == 200
    assert answer.json() == {"text": "two\nthree"}
    assert runtime.agent_sessions.commands == [
        (DEVICE, "fakedesk", "journal", {"lines": 2})
    ]


def test_a_journal_of_a_module_nobody_ships_is_refused_by_name(api):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)

    answer = client.get(
        f"{MODULE_PATH}/journal", params={"device_id": DEVICE, "module": "nope"}
    )

    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "module_unknown"
    assert runtime.agent_sessions.commands == []


def test_a_row_is_what_the_agent_reported_beside_what_the_hub_asks(api):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_modules[DEVICE] = {
        "fakedesk": {
            "state": "running",
            "is_active": True,
            "code": "",
            "params": {},
            "details": {"port": 21118},
        }
    }
    runtime.desired_states.set_want(DEVICE, "fakedesk", "running")

    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]

    assert row["state"] == "running"
    assert row["is_active"] is True
    assert row["details"] == {"port": 21118}
    assert row["want"] == "running"
    assert row["task_id"] == ""


def test_an_uninstall_the_machine_confirmed_reads_absent_on_both_halves(api):
    """The row after an uninstall the machine carried out: what was asked
    and what the machine reports are the same word, which is how a page or
    a walk knows the press is done."""
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.desired_states.set_want(DEVICE, "fakedesk", "absent")
    runtime.device_modules[DEVICE] = {"fakedesk": {"state": "absent"}}
    runtime.desired_states.settle_want(DEVICE, "fakedesk")

    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]

    assert (row["want"], row["state"]) == ("absent", "absent")


def test_a_module_nobody_touched_reads_unknown_with_no_want(api):
    client, _ = api

    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]

    assert (row["state"], row["want"], row["is_active"]) == ("unknown", "", False)


def test_the_manifest_kind_reaches_the_row_for_the_ssh_confirm(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(
        device_modules,
        "load_module_manifests",
        lambda: {
            "ssh_server": {
                "title": "SSH server",
                "kind": "openssh",
                "platforms": {"linux-debian": {"service": "ssh"}},
            }
        },
    )

    answer = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()

    assert answer["modules"][0]["kind"] == "openssh"


def test_a_native_module_offers_nothing_where_the_platform_carries_it(api, monkeypatch):
    client, runtime = api
    monkeypatch.setattr(
        device_modules,
        "load_module_manifests",
        lambda: {
            "samba_mount": {
                "title": "Samba mount",
                "kind": "system_package",
                "platforms": {
                    "linux-debian": {"packages": ["cifs-utils"]},
                    "windows": {},
                },
            }
        },
    )

    runtime.device_platform[DEVICE] = {"os": "windows", "family": "", "arch": "amd64"}
    native = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]
    assert native["is_native"] is True

    runtime.device_platform[DEVICE] = {
        "os": "linux",
        "family": "debian",
        "arch": "amd64",
    }
    package = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]
    assert package["is_native"] is False


def test_whether_an_uninstall_keeps_the_data_reaches_the_row(api, monkeypatch):
    """The confirmation says which, so the row carries the branch's word."""
    client, runtime = api
    monkeypatch.setattr(
        device_modules,
        "load_module_manifests",
        lambda: {
            "sample": {
                "title": "Sample",
                "kind": "system_package",
                "platforms": {
                    "linux-debian": {
                        "packages": ["sample"],
                        "verify": "sample --version",
                        "uninstall": {
                            "packages": ["sample"],
                            "post_uninstall": [],
                            "is_data_kept": False,
                        },
                    },
                    "linux-rhel": {"packages": ["sample"], "verify": "sample -v"},
                },
            }
        },
    )

    runtime.device_platform[DEVICE] = {
        "os": "linux",
        "family": "debian",
        "arch": "amd64",
    }
    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]
    assert row["is_data_kept"] is False

    runtime.device_platform[DEVICE] = {"os": "linux", "family": "rhel", "arch": "amd64"}
    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]
    assert row["is_data_kept"] is True


def test_the_installer_tier_reaches_the_row(api):
    client, _ = api

    answer = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()

    assert answer["modules"][0]["installer"] == "hub"


def test_a_user_tier_press_writes_nothing(api, monkeypatch, tmp_path):
    """user-tier rows never offer install or uninstall; a request arriving
    anyway, from an old page or a hand-built call, must write no want."""
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    monkeypatch.setattr(
        device_modules,
        "load_module_manifests",
        lambda: {
            "teamviewer": {
                "title": "TeamViewer",
                "kind": "package",
                "installer": "user",
                "platforms": {"linux": {"verify": "command -v teamviewer"}},
            }
        },
    )

    refused = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "teamviewer"}
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "module_not_optional",
        "params": {"name": "teamviewer"},
    }
    assert modules_file(tmp_path) == {}
    assert runtime.agent_sessions.pushes == []


@pytest.mark.parametrize(
    "press, want",
    [
        ("install", "installed"),
        ("start", "running"),
        ("stop", "stopped"),
        ("uninstall", "absent"),
    ],
)
def test_each_press_writes_its_want_and_pushes_the_state(api, tmp_path, press, want):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)

    answer = client.post(
        f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "fakedesk"}
    )

    assert answer.status_code == 200
    assert answer.json()["modules"][0]["want"] == want
    assert modules_file(tmp_path) == {"fakedesk": {"want": want, "is_settled": False}}
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE]


def test_a_press_on_an_offline_device_is_refused_before_anything_is_written(
    api, tmp_path
):
    client, runtime = api

    refused = client.post(
        f"{MODULE_PATH}/start", json={"device_id": DEVICE, "module": "fakedesk"}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "agent_offline"
    assert modules_file(tmp_path) == {}


def test_a_module_with_no_manifest_is_refused(api):
    client, _ = api

    refused = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "nonsense"}
    )

    assert refused.status_code == 404
    assert refused.json()["detail"]["code"] == "module_unknown"


def test_a_module_with_no_build_for_the_platform_is_refused(api, tmp_path):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_platform[DEVICE] = {"os": "linux", "family": "arch", "arch": "x"}

    refused = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "fakedesk"}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "no_platform_build"
    assert modules_file(tmp_path) == {}


def test_the_row_names_the_newest_task_carrying_the_modules_lines(api):
    client, runtime = api
    label = module_task_label(DEVICE, "fakedesk")

    async def two_tasks():
        async def one_line():
            yield "installing\n"

        runtime.tasks.start(label=label, source=one_line())
        newest = runtime.tasks.start(label=label, source=one_line())
        for _ in range(3):
            await asyncio.sleep(0)
        return newest.id

    newest_id = asyncio.run(two_tasks())

    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]

    assert row["task_id"] == newest_id


# --- the one door every module block goes through ---


HUB_BOX = "1" * 32
LAPTOP = "2" * 32
OFFLINE = "3" * 32
HUB_MACHINE = "machine-of-the-hub"
MODULE = "samba"
BLOCK_PATH = f"/api/agent/module/{MODULE}"


class SampleView(ModuleDeviceFields):
    users: list = []
    sessions: int = 0


def sample_view(runtime, context) -> SampleView:
    return SampleView(
        **context.fields(),
        users=list(context.config.get("users", [])),
        sessions=len(context.details.get("sessions", [])),
    )


def sample_import(details: dict) -> dict:
    return {"users": [entry["username"] for entry in details.get("sessions", [])]}


@pytest.fixture
def box(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    runtime = FakeModuleRuntime(
        devices=[
            managed_device("zed laptop", device_id=LAPTOP),
            managed_device("hub box", device_id=HUB_BOX, machine_id=HUB_MACHINE),
            managed_device("attic", device_id=OFFLINE),
        ],
        online=[HUB_BOX, LAPTOP],
        lan_addresses=["192.168.100.1"],
    )
    runtime.device_address = {
        HUB_BOX: "192.168.100.1",
        LAPTOP: "192.168.100.7",
        OFFLINE: "192.168.100.9",
    }
    runtime.device_platform = {
        key: {"os": "linux", "family": "debian", "arch": "amd64"}
        for key in (HUB_BOX, LAPTOP, OFFLINE)
    }
    FakeDeviceRegistry.runtime = runtime
    monkeypatch.setattr(device_modules, "DeviceRegistry", FakeDeviceRegistry)
    router = device_modules.module_router(
        MODULE,
        view_model=SampleView,
        build_view=sample_view,
        import_config=sample_import,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


# --- the per-device read ---


def test_the_device_read_carries_the_shared_fields_beside_the_modules_own(box):
    client, runtime = box
    runtime.desired_states.write(LAPTOP, MODULE, {"users": ["ann"]})
    runtime.report(LAPTOP, MODULE, "running", sessions=[{"username": "ann"}])

    payload = client.get(BLOCK_PATH, params={"device_id": LAPTOP}).json()

    assert payload == {
        "device_id": LAPTOP,
        "host": "192.168.100.7",
        "is_online": True,
        "state": "running",
        "code": "",
        "params": {},
        "users": ["ann"],
        "sessions": 1,
    }


def test_an_offline_device_reads_its_configuration_with_the_flag_down(box):
    client, runtime = box
    runtime.desired_states.write(OFFLINE, MODULE, {"users": ["bob"]})

    payload = client.get(BLOCK_PATH, params={"device_id": OFFLINE}).json()

    assert payload["is_online"] is False
    assert payload["users"] == ["bob"]
    assert payload["sessions"] == 0


def test_a_failure_the_agent_reported_reads_on_the_row(box):
    client, runtime = box
    runtime.device_modules[LAPTOP] = {
        MODULE: {
            "state": "failed",
            "is_active": False,
            "code": "install_failed",
            "params": {"detail": "apt refused"},
            "details": {},
        }
    }

    payload = client.get(BLOCK_PATH, params={"device_id": LAPTOP}).json()

    assert payload["state"] == "failed"
    assert (payload["code"], payload["params"]) == (
        "install_failed",
        {"detail": "apt refused"},
    )


def test_an_unknown_device_is_refused_typed(box):
    client, _ = box

    response = client.get(BLOCK_PATH, params={"device_id": "nonsense"})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "device_unknown"


# --- the import ---


def test_import_writes_what_the_machine_reports_where_the_hub_holds_nothing(box):
    client, runtime = box
    runtime.report(LAPTOP, MODULE, "installed", sessions=[{"username": "ann"}])

    response = client.post(f"{BLOCK_PATH}/import", json={"device_id": LAPTOP})

    assert response.status_code == 200
    assert response.json()["users"] == ["ann"]
    assert runtime.desired_states.read(LAPTOP, MODULE) == {"users": ["ann"]}
    # Nothing is wanted of the module yet, so nothing is pushed.
    assert runtime.agent_sessions.pushes == []
    assert runtime.published_services.refreshes == 1


def test_import_pushes_where_the_module_is_already_wanted_configured(box):
    client, runtime = box
    runtime.desired_states.set_want(LAPTOP, MODULE, "running")
    runtime.report(LAPTOP, MODULE, "running", sessions=[{"username": "ann"}])

    client.post(f"{BLOCK_PATH}/import", json={"device_id": LAPTOP})

    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]


def test_import_refuses_to_overwrite_a_configuration_the_hub_holds(box):
    client, runtime = box
    runtime.desired_states.write(LAPTOP, MODULE, {"users": ["bob"]})
    runtime.report(LAPTOP, MODULE, "running", sessions=[{"username": "ann"}])

    response = client.post(f"{BLOCK_PATH}/import", json={"device_id": LAPTOP})

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "module_configured",
        "params": {"device_id": LAPTOP, "module": MODULE},
    }
    assert runtime.desired_states.read(LAPTOP, MODULE) == {"users": ["bob"]}


def test_import_on_an_offline_device_writes_nothing(box):
    client, runtime = box

    response = client.post(f"{BLOCK_PATH}/import", json={"device_id": OFFLINE})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent_offline"
    assert runtime.desired_states.read(OFFLINE, MODULE) == {}


def test_a_module_that_imports_nothing_has_no_import_route(monkeypatch, tmp_path):
    router = device_modules.module_router(
        MODULE, view_model=SampleView, build_view=sample_view
    )

    assert [route.path for route in router.routes] == [
        f"{BLOCK_PATH}",
        f"{BLOCK_PATH}/apply",
    ]


# --- the helpers the sub-routes share ---


def test_a_configuration_is_checked_on_the_agent_then_stored_then_pushed(box):
    _, runtime = box
    context = device_modules.device_context(runtime, MODULE, LAPTOP)

    device_modules.store_config(runtime, context, {"users": ["ann"]})

    assert runtime.agent_sessions.validations == [(LAPTOP, MODULE, {"users": ["ann"]})]
    assert runtime.desired_states.read(LAPTOP, MODULE) == {"users": ["ann"]}
    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]
    assert context.config == {"users": ["ann"]}
    # What a machine shares is what the published list reads.
    assert runtime.published_services.refreshes == 1


def test_a_configuration_the_agent_refuses_is_neither_stored_nor_pushed(box):
    _, runtime = box
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "share_name_reserved",
        "params": {"name": "global"},
    }
    context = device_modules.device_context(runtime, MODULE, LAPTOP)

    with pytest.raises(device_modules.HTTPException) as refused:
        device_modules.store_config(runtime, context, {"users": ["ann"]})

    assert refused.value.status_code == 400
    assert refused.value.detail == {
        "code": "share_name_reserved",
        "params": {"name": "global"},
    }
    assert runtime.desired_states.read(LAPTOP, MODULE) == {}
    assert runtime.agent_sessions.pushes == []
    assert runtime.published_services.refreshes == 0


def test_an_offline_device_cannot_be_edited(box):
    _, runtime = box
    context = device_modules.device_context(runtime, MODULE, OFFLINE)

    with pytest.raises(device_modules.HTTPException) as refused:
        device_modules.store_config(runtime, context, {"users": []})

    assert refused.value.status_code == 409
    assert refused.value.detail == {
        "code": "agent_offline",
        "params": {"device_id": OFFLINE},
    }
    assert runtime.agent_sessions.validations == []


def test_a_verb_runs_on_the_agent_under_the_modules_name_to_its_close(box):
    _, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 0,
        "code": "",
        "params": {},
        "output": "ok\n",
    }
    context = device_modules.device_context(runtime, MODULE, LAPTOP)

    info = device_modules.run_command(runtime, context, "set_password", {"name": "ann"})

    assert runtime.agent_sessions.commands == [
        (LAPTOP, MODULE, "set_password", {"name": "ann"})
    ]
    assert info["output"] == "ok\n"


def test_a_verb_the_agent_fails_is_answered_with_its_code(box):
    _, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 1,
        "code": "user_unknown",
        "params": {"user": "ghost"},
        "output": "",
    }
    context = device_modules.device_context(runtime, MODULE, LAPTOP)

    with pytest.raises(device_modules.HTTPException) as refused:
        device_modules.run_command(runtime, context, "set_password", {})

    assert refused.value.status_code == 502
    assert refused.value.detail == {"code": "user_unknown", "params": {"user": "ghost"}}


def test_a_failed_verb_with_only_output_names_it_in_the_detail(box):
    _, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 2,
        "code": "",
        "params": {},
        "output": "zpool: no\n",
    }
    context = device_modules.device_context(runtime, MODULE, LAPTOP)

    with pytest.raises(device_modules.HTTPException) as refused:
        device_modules.run_command(runtime, context, "op", {})

    assert refused.value.detail == {
        "code": "command_failed",
        "params": {"detail": "zpool: no"},
    }


def test_a_verb_on_an_offline_device_is_refused_before_it_is_sent(box):
    _, runtime = box
    context = device_modules.device_context(runtime, MODULE, OFFLINE)

    with pytest.raises(device_modules.HTTPException) as refused:
        device_modules.run_command(runtime, context, "set_password", {})

    assert refused.value.status_code == 409
    assert runtime.agent_sessions.commands == []


def test_apply_pushes_the_state_again(box):
    client, runtime = box

    response = client.post(f"{BLOCK_PATH}/apply", json={"device_id": LAPTOP})

    assert response.json() == {"is_applied": True, "message": "pushed"}
    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]
    assert (
        client.post(f"{BLOCK_PATH}/apply", json={"device_id": OFFLINE}).status_code
        == 409
    )
