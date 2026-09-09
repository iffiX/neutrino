"""The one door every device-hosted module page goes through.

What these pin: the device list carrying every stored device with an agent
and the hub box's own first, a selection installing what is newly on and
uninstalling what is dropped, a changed device with no socket refusing the
whole selection before anything is written, the per-device read carrying
the module's own fields beside the shared ones, a configuration checked on
the agent before it is stored and pushed, and an imperative verb run on
the agent and answering the fresh view.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import ModuleDeviceFields
from neutrino_hub.web.routers import device_modules
from tests.conftest import FakeDeviceRegistry, FakeModuleRuntime, managed_device

HUB_BOX = "aa:bb:cc:dd:ee:01"
LAPTOP = "aa:bb:cc:dd:ee:02"
OFFLINE = "aa:bb:cc:dd:ee:03"
MODULE = "samba"


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
            managed_device(LAPTOP, "zed laptop"),
            managed_device(HUB_BOX, "hub box"),
            managed_device(OFFLINE, "attic"),
        ],
        online=[HUB_BOX, LAPTOP],
        lan_addresses=["192.168.100.1"],
    )
    runtime.client_address = {
        HUB_BOX: "192.168.100.1",
        LAPTOP: "192.168.100.7",
        OFFLINE: "192.168.100.9",
    }
    runtime.client_platform = {
        key: {"os": "linux", "family": "debian", "arch": "amd64"}
        for key in (HUB_BOX, LAPTOP, OFFLINE)
    }
    FakeDeviceRegistry.runtime = runtime
    monkeypatch.setattr(device_modules, "DeviceRegistry", FakeDeviceRegistry)
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

    rows = client.get(f"/api/{MODULE}").json()["devices"]

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

    runtime.devices["aa:bb:cc:dd:ee:09"] = ManagedDevice(
        mac_address="aa:bb:cc:dd:ee:09"
    )

    rows = client.get(f"/api/{MODULE}").json()["devices"]

    assert "aa:bb:cc:dd:ee:09" not in [row["device_id"] for row in rows]


# --- the selection ---


def test_selecting_devices_switches_them_orders_installs_and_pushes(box):
    client, runtime = box
    runtime.report(LAPTOP, MODULE, "absent")

    response = client.put(f"/api/{MODULE}/devices", json={"device_ids": [LAPTOP]})

    assert response.status_code == 200
    assert runtime.desired_states.is_enabled(LAPTOP, MODULE) is True
    assert runtime.desired_states.is_enabled(HUB_BOX, MODULE) is False
    order = runtime.agent_module_orders.open_order_for(LAPTOP, MODULE)
    assert order is not None and order.action == "install"
    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]
    row = next(r for r in response.json()["devices"] if r["device_id"] == LAPTOP)
    assert row["is_enabled"] is True
    assert row["state"] == "installing"


def test_dropping_a_device_orders_an_uninstall(box):
    client, runtime = box
    runtime.desired_states.set_enabled(LAPTOP, MODULE, True)
    runtime.report(LAPTOP, MODULE, "installed")

    client.put(f"/api/{MODULE}/devices", json={"device_ids": []})

    assert runtime.desired_states.is_enabled(LAPTOP, MODULE) is False
    order = runtime.agent_module_orders.open_order_for(LAPTOP, MODULE)
    assert order is not None and order.action == "uninstall"


def test_a_changed_device_with_no_socket_refuses_the_whole_selection(box):
    client, runtime = box

    response = client.put(
        f"/api/{MODULE}/devices", json={"device_ids": [LAPTOP, OFFLINE]}
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

    response = client.put(
        f"/api/{MODULE}/devices", json={"device_ids": [OFFLINE, LAPTOP]}
    )

    assert response.status_code == 200
    assert runtime.desired_states.is_enabled(OFFLINE, MODULE) is True
    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]


def test_an_id_no_managed_device_answers_to_is_refused(box):
    client, _ = box

    response = client.put(
        f"/api/{MODULE}/devices", json={"device_ids": ["11:22:33:44:55:66"]}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "device_unknown"


# --- the per-device read ---


def test_the_device_read_carries_the_shared_fields_beside_the_modules_own(box):
    client, runtime = box
    runtime.desired_states.write(LAPTOP, MODULE, {"users": ["ann"]})
    runtime.report(LAPTOP, MODULE, "installed", sessions=[{"username": "ann"}])

    payload = client.get(f"/api/{MODULE}/devices/{LAPTOP}").json()

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

    payload = client.get(f"/api/{MODULE}/devices/{OFFLINE}").json()

    assert payload["is_online"] is False
    assert payload["users"] == ["bob"]
    assert payload["sessions"] == 0


def test_a_standing_failure_of_the_last_order_reads_on_the_row(box):
    client, runtime = box
    runtime.report(LAPTOP, MODULE, "absent")
    runtime.agent_module_orders.ask(
        mac_address=LAPTOP,
        module=MODULE,
        manifest={"installer": "platform"},
        platform={},
        action="install",
    )
    order = runtime.agent_module_orders.open_order_for(LAPTOP, MODULE)
    runtime.agent_module_orders.record_result(
        mac_address=LAPTOP,
        order_id=order.id,
        state="failed",
        code="install_failed",
        params={"detail": "apt refused"},
    )

    payload = client.get(f"/api/{MODULE}/devices/{LAPTOP}").json()

    assert payload["state"] == "failed"
    assert (payload["code"], payload["params"]) == (
        "install_failed",
        {"detail": "apt refused"},
    )


def test_an_unknown_device_is_refused_typed(box):
    client, _ = box

    response = client.get(f"/api/{MODULE}/devices/11:22:33:44:55:66")

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

    response = client.post(f"/api/{MODULE}/devices/{LAPTOP}/apply")

    assert response.json() == {"is_applied": True, "message": "pushed"}
    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]
    assert client.post(f"/api/{MODULE}/devices/{OFFLINE}/apply").status_code == 409
