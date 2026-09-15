"""A device's Modules page, and the one door every module block goes through.

The page: management is a completed handshake, so a failed install or a
forgotten device never reads managed here, and a click is one order. The
door: the device list carrying every stored device with an agent and the hub
box's own first, a selection installing what is newly on and uninstalling
what is dropped, a changed device with no socket refusing the whole
selection before anything is written, the per-device read carrying the
module's own fields beside the shared ones, a configuration checked on the
agent before it is stored and pushed, and an imperative verb run on the
agent and answering the fresh view.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import ModuleDeviceFields
from neutrino_hub.web.routers.agent import module as device_modules
from tests.conftest import FakeDeviceRegistry, FakeModuleRuntime, managed_device
from tests.web.device_api_box import DEVICE, device_box

MODULE_PATH = "/api/agent/module"


# --- the Modules page of a device: what it is told, and what it can act on ---


@pytest.fixture
def api(monkeypatch):
    client, runtime = device_box(monkeypatch, device_modules)
    with client:
        yield client, runtime


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


def test_what_the_agent_reported_is_found_by_the_devices_id(api):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_modules[DEVICE] = {"fakedesk": {"state": "installed"}}

    answer = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()

    assert answer["modules"][0]["state"] == "installed"


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


def test_the_installer_tier_reaches_the_row(api):
    client, _ = api

    answer = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()

    assert answer["modules"][0]["installer"] == "hub"


def test_a_user_tier_click_queues_nothing_and_the_row_keeps_its_state(api, monkeypatch):
    """user-tier rows never offer install or uninstall; a request arriving
    anyway — an old page, a hand-built call — must order nothing."""
    client, runtime = api
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
    runtime.device_modules[DEVICE] = {"teamviewer": {"state": "absent"}}

    answer = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "teamviewer"}
    ).json()

    assert answer["modules"][0]["installer"] == "user"
    assert answer["modules"][0]["state"] == "absent"
    assert runtime.agent_module_orders.open_order_for(DEVICE, "teamviewer") is None


def test_a_click_queues_one_order_and_the_row_shows_the_step(api):
    client, runtime = api

    answer = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "fakedesk"}
    ).json()

    assert answer["modules"][0]["state"] == "installing"
    order = runtime.agent_module_orders.open_order_for(DEVICE, "fakedesk")
    assert order is not None and order.action == "install"
    unknown = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "nonsense"}
    )
    assert unknown.status_code == 404


def test_an_uninstall_queues_the_paired_order(api):
    client, runtime = api
    runtime.device_modules[DEVICE] = {"fakedesk": {"state": "installed"}}

    answer = client.post(
        f"{MODULE_PATH}/uninstall", json={"device_id": DEVICE, "module": "fakedesk"}
    ).json()

    assert answer["modules"][0]["state"] == "uninstalling"
    order = runtime.agent_module_orders.open_order_for(DEVICE, "fakedesk")
    assert order is not None and order.action == "uninstall"


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
    monkeypatch.setattr(device_modules, "machine_id", lambda: HUB_MACHINE)
    router = device_modules.module_router(
        MODULE, view_model=SampleView, build_view=sample_view
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


# --- the device list ---


def test_the_list_carries_every_stored_device_with_an_agent_hub_box_first(box):
    client, runtime = box
    runtime.report(LAPTOP, MODULE, "installed")
    runtime.report(OFFLINE, MODULE, "absent")
    runtime.desired_states.set_enabled(LAPTOP, MODULE, True)

    rows = client.get(f"{BLOCK_PATH}/device").json()["devices"]

    assert [row["device_id"] for row in rows] == [HUB_BOX, OFFLINE, LAPTOP]
    by_id = {row["device_id"]: row for row in rows}
    assert by_id[LAPTOP] == {
        "device_id": LAPTOP,
        "name": "zed laptop",
        "hostname": "",
        "is_online": True,
        "is_enabled": True,
        "state": "installed",
        "code": "",
        "params": {},
    }
    assert by_id[OFFLINE]["is_online"] is False
    assert by_id[OFFLINE]["state"] == "absent"
    assert by_id[HUB_BOX]["state"] == "unknown"


def test_a_device_that_never_completed_its_handshake_is_not_listed(box):
    client, runtime = box
    from neutrino_hub.modules.devices.registry import ManagedDevice

    runtime.devices["9" * 32] = ManagedDevice(id="9" * 32)

    rows = client.get(f"{BLOCK_PATH}/device").json()["devices"]

    assert "9" * 32 not in [row["device_id"] for row in rows]


# --- the selection ---


def test_selecting_devices_switches_them_orders_installs_and_pushes(box):
    client, runtime = box
    runtime.report(LAPTOP, MODULE, "absent")

    response = client.post(f"{BLOCK_PATH}/device/set", json={"device_ids": [LAPTOP]})

    assert response.status_code == 200
    assert runtime.desired_states.is_enabled(LAPTOP, MODULE) is True
    assert runtime.desired_states.is_enabled(HUB_BOX, MODULE) is False
    order = runtime.agent_module_orders.open_order_for(LAPTOP, MODULE)
    assert order is not None and order.action == "install"
    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]
    row = next(r for r in response.json()["devices"] if r["device_id"] == LAPTOP)
    assert row["is_enabled"] is True
    assert row["state"] == "installing"
    assert runtime.published_services.refreshes == 1


def test_dropping_a_device_orders_an_uninstall(box):
    client, runtime = box
    runtime.desired_states.set_enabled(LAPTOP, MODULE, True)
    runtime.report(LAPTOP, MODULE, "installed")

    client.post(f"{BLOCK_PATH}/device/set", json={"device_ids": []})

    assert runtime.desired_states.is_enabled(LAPTOP, MODULE) is False
    order = runtime.agent_module_orders.open_order_for(LAPTOP, MODULE)
    assert order is not None and order.action == "uninstall"


def test_a_changed_device_with_no_socket_refuses_the_whole_selection(box):
    client, runtime = box

    response = client.post(
        f"{BLOCK_PATH}/device/set", json={"device_ids": [LAPTOP, OFFLINE]}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "agent_offline",
        "params": {"device_id": OFFLINE},
    }
    assert runtime.desired_states.is_enabled(LAPTOP, MODULE) is False
    assert runtime.agent_module_orders.open_order_for(LAPTOP, MODULE) is None
    assert runtime.agent_sessions.pushes == []


def test_an_offline_device_already_on_stays_on_untouched(box):
    client, runtime = box
    runtime.desired_states.set_enabled(OFFLINE, MODULE, True)

    response = client.post(
        f"{BLOCK_PATH}/device/set", json={"device_ids": [OFFLINE, LAPTOP]}
    )

    assert response.status_code == 200
    assert runtime.desired_states.is_enabled(OFFLINE, MODULE) is True
    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]


def test_an_id_no_managed_device_answers_to_is_refused(box):
    client, _ = box

    response = client.post(
        f"{BLOCK_PATH}/device/set", json={"device_ids": ["nonsense"]}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "device_unknown"


# --- the per-device read ---


def test_the_device_read_carries_the_shared_fields_beside_the_modules_own(box):
    client, runtime = box
    runtime.desired_states.write(LAPTOP, MODULE, {"users": ["ann"]})
    runtime.report(LAPTOP, MODULE, "installed", sessions=[{"username": "ann"}])

    payload = client.get(BLOCK_PATH, params={"device_id": LAPTOP}).json()

    assert payload == {
        "device_id": LAPTOP,
        "host": "192.168.100.7",
        "is_online": True,
        "state": "installed",
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


def test_a_standing_failure_of_the_last_order_reads_on_the_row(box):
    client, runtime = box
    runtime.report(LAPTOP, MODULE, "absent")
    runtime.agent_module_orders.ask(
        device_id=LAPTOP,
        module=MODULE,
        manifest={"installer": "platform"},
        platform={},
        action="install",
    )
    order = runtime.agent_module_orders.open_order_for(LAPTOP, MODULE)
    runtime.agent_module_orders.record_result(
        device_id=LAPTOP,
        order_id=order.id,
        state="failed",
        code="install_failed",
        params={"detail": "apt refused"},
    )

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


def test_a_command_runs_on_the_agent_to_its_close(box):
    _, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 0,
        "code": "",
        "params": {},
        "output": "ok\n",
    }
    context = device_modules.device_context(runtime, MODULE, LAPTOP)

    info = device_modules.run_command(
        runtime, context, "samba_set_password", {"name": "ann"}
    )

    assert runtime.agent_sessions.commands == [
        (LAPTOP, "samba_set_password", {"name": "ann"})
    ]
    assert info["output"] == "ok\n"


def test_a_command_the_agent_fails_is_answered_with_its_code(box):
    _, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 1,
        "code": "user_unknown",
        "params": {"user": "ghost"},
        "output": "",
    }
    context = device_modules.device_context(runtime, MODULE, LAPTOP)

    with pytest.raises(device_modules.HTTPException) as refused:
        device_modules.run_command(runtime, context, "samba_set_password", {})

    assert refused.value.status_code == 502
    assert refused.value.detail == {"code": "user_unknown", "params": {"user": "ghost"}}


def test_a_failed_command_with_only_output_names_it_in_the_detail(box):
    _, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 2,
        "code": "",
        "params": {},
        "output": "zpool: no\n",
    }
    context = device_modules.device_context(runtime, MODULE, LAPTOP)

    with pytest.raises(device_modules.HTTPException) as refused:
        device_modules.run_command(runtime, context, "zfs_op", {})

    assert refused.value.detail == {
        "code": "command_failed",
        "params": {"detail": "zpool: no"},
    }


def test_a_command_on_an_offline_device_is_refused_before_it_is_sent(box):
    _, runtime = box
    context = device_modules.device_context(runtime, MODULE, OFFLINE)

    with pytest.raises(device_modules.HTTPException) as refused:
        device_modules.run_command(runtime, context, "samba_set_password", {})

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
