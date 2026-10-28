"""A device's Modules page, and the one door every module block goes through.

The page: management is a completed handshake, so a failed install or a
forgotten device never reads managed here; each row is what the agent last
reported beside what the hub asks of it; the four presses write one
``want`` each and push it, refuse an offline device before writing, and a
module the agent carries takes none; a press on a module whose last report is
``failed`` or ``install_failed`` puts a fresh retry mark, and one on any other
module puts none; a failed install reads its code beside the want it keeps;
the task carrying a module's install lines is
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

from neutrino_hub.modules.devices.manifests import (
    load_module_manifests as shipped_manifests,
)
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


def test_a_failed_install_reads_install_failed_with_its_code_beside_its_want(api):
    """The row is the machine's report: the want stays, and the code with it."""
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.desired_states.set_want(DEVICE, "fakedesk", "installed")
    runtime.device_modules[DEVICE] = {
        "fakedesk": {
            "state": "install_failed",
            "code": "download_failed",
            "params": {"file": "fake.tar.gz", "sources": []},
        }
    }

    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]

    assert (row["state"], row["want"], row["code"], row["params"]) == (
        "install_failed",
        "installed",
        "download_failed",
        {"file": "fake.tar.gz", "sources": []},
    )


def test_a_module_nobody_touched_reads_unknown_with_no_want(api):
    client, _ = api

    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]

    assert (row["state"], row["want"], row["is_active"]) == ("unknown", "", False)


def test_a_containers_environment_reaches_the_row_as_names_alone(api):
    """The values stay in the report the hub keeps, where the import reads them."""
    client, runtime = api
    containers = [
        {"name": "web", "environment": ["TOKEN=mine", "EMPTY=", "A=b=c"]},
        {"name": "neutrino_demo", "module": "demo", "environment": []},
        {"name": "old", "image": "alpine"},
    ]
    runtime.device_modules[DEVICE] = {
        "fakedesk": {"state": "running", "details": {"containers": containers}}
    }

    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]

    assert row["details"]["containers"] == [
        {"name": "web", "environment": ["TOKEN", "EMPTY", "A"]},
        {"name": "neutrino_demo", "module": "demo", "environment": []},
        {"name": "old", "image": "alpine"},
    ]
    held = runtime.device_modules[DEVICE]["fakedesk"]["details"]["containers"]
    assert held[0]["environment"] == ["TOKEN=mine", "EMPTY=", "A=b=c"]


def system_entry(runner: str, packages: list, **uninstall) -> dict:
    """A ``system`` platform entry naming its packages."""
    return {
        "runner": runner,
        "install": {
            "method": "system",
            "params": {
                "version": "system",
                "packages": packages,
                "verify": f"{runner} --version",
                "uninstall": {"packages": packages, "post_uninstall": [], **uninstall},
            },
        },
    }


def test_the_runner_and_the_method_of_the_platforms_entry_reach_the_row(
    api, monkeypatch
):
    client, runtime = api
    monkeypatch.setattr(
        device_modules,
        "load_module_manifests",
        lambda: {
            "ssh_server": {
                "title": "SSH server",
                "publisher": "OpenSSH",
                "platforms": {
                    "linux-debian": system_entry("openssh", ["openssh-server"])
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

    assert (row["runner"], row["method"], row["publisher"]) == (
        "openssh",
        "system",
        "OpenSSH",
    )
    assert (row["license"], row["corresponding_source"]) == ("", "")


def test_a_builtin_entry_reads_builtin_where_the_system_holds_the_software(
    api, monkeypatch
):
    client, runtime = api
    monkeypatch.setattr(
        device_modules,
        "load_module_manifests",
        lambda: {
            "samba_mount": {
                "title": "Samba mount",
                "platforms": {
                    "linux-debian": system_entry("samba_mount", ["cifs-utils"]),
                    "windows": {
                        "runner": "samba_mount_native",
                        "install": {"method": "builtin", "params": {}},
                    },
                },
            }
        },
    )

    runtime.device_platform[DEVICE] = {"os": "windows", "family": "", "arch": "amd64"}
    native = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]
    assert (native["method"], native["runner"]) == ("builtin", "samba_mount_native")

    runtime.device_platform[DEVICE] = {
        "os": "linux",
        "family": "debian",
        "arch": "amd64",
    }
    package = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]
    assert package["method"] == "system"


def test_whether_an_uninstall_keeps_the_data_reaches_the_row(api, monkeypatch):
    """The confirmation says which, so the row carries the entry's word; a
    ``system`` entry keeps the data."""
    client, runtime = api
    hub_entry = {
        "runner": "sample",
        "install": {
            "method": "hub",
            "params": {
                "version": "1.0",
                "releases": [],
                "artifacts": [],
                "verify": "sample --version",
                "uninstall": {"post_uninstall": [], "is_data_kept": False},
            },
        },
    }
    monkeypatch.setattr(
        device_modules,
        "load_module_manifests",
        lambda: {
            "sample": {
                "title": "Sample",
                "platforms": {
                    "linux-debian": hub_entry,
                    "linux-rhel": system_entry("sample", ["sample"]),
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


def test_the_method_reaches_the_row(api):
    client, runtime = api
    runtime.device_platform[DEVICE] = {
        "os": "linux",
        "family": "debian",
        "arch": "amd64",
    }

    answer = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()

    assert answer["modules"][0]["method"] == "hub"


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
    assert modules_file(tmp_path) == {
        "fakedesk": {"want": want, "is_settled": False, "version": ""}
    }
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


@pytest.mark.parametrize("press", ["install", "start"])
def test_vscode_is_not_installed_or_started_before_its_terms_are_accepted(
    api, monkeypatch, tmp_path, press
):
    client, runtime = api
    monkeypatch.setattr(device_modules, "load_module_manifests", shipped_manifests)
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_platform[DEVICE] = WINDOWS

    refused = client.post(
        f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "vscode"}
    )
    (tmp_path / "devices" / DEVICE).mkdir(parents=True, exist_ok=True)
    (tmp_path / "devices" / DEVICE / "vscode.json").write_text(
        json.dumps({"terms_accepted_at": "2026-10-05T08:00:00+00:00"})
    )
    taken = client.post(
        f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "vscode"}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "terms_not_accepted",
        "params": {"module": "vscode"},
    }
    assert taken.status_code == 200
    assert list(modules_file(tmp_path)) == ["vscode"]


def test_vscode_is_stopped_and_uninstalled_without_its_terms(api, monkeypatch):
    client, runtime = api
    monkeypatch.setattr(device_modules, "load_module_manifests", shipped_manifests)
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_platform[DEVICE] = WINDOWS

    for press in ("stop", "uninstall"):
        answer = client.post(
            f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "vscode"}
        )
        assert answer.status_code == 200, press


# What each shipped manifest offers a Windows machine and a Mac: the modules
# the picker lets a person choose there.
SUPPORTED_OFF_LINUX = {
    "remote_desktop": (True, True),
    "ssh_server": (True, True),
    "terminal": (True, True),
    "cloudcli": (True, True),
    "code_server": (False, True),
    "codeg": (True, True),
    "siyuan": (True, True),
    "gitea": (True, True),
    "podman": (True, True),
    "samba": (True, True),
    "vscode": (True, True),
    "hermes_webui": (True, True),
}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}
DARWIN = {"os": "darwin", "family": "", "arch": "arm64", "version": "15.3.1"}


def test_each_shipped_module_is_supported_off_linux_as_its_manifest_says(
    api, monkeypatch
):
    client, runtime = api
    monkeypatch.setattr(device_modules, "load_module_manifests", shipped_manifests)

    seen = {}
    for platform in (WINDOWS, DARWIN):
        runtime.device_platform[DEVICE] = platform
        rows = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()
        for row in rows["modules"]:
            seen.setdefault(row["name"], []).append(row["is_supported"])

    assert {name: tuple(flags) for name, flags in seen.items()} == (SUPPORTED_OFF_LINUX)


@pytest.mark.parametrize(
    ("platform", "identity"),
    [
        (
            {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"},
            ("podman", "system", "podman-container-tools/podman", "", ""),
        ),
        (
            WINDOWS,
            (
                "podman_machine",
                "hub",
                "podman-container-tools/podman",
                "Apache-2.0",
                "https://github.com/podman-container-tools/podman/tree/v6.1.4",
            ),
        ),
        (
            {**DARWIN, "arch": "amd64"},
            (
                "podman_machine",
                "hub",
                "podman-container-tools/podman",
                "Apache-2.0",
                "https://github.com/podman-container-tools/podman/tree/v5.8.9",
            ),
        ),
    ],
)
def test_the_containers_row_carries_the_runner_and_method_of_the_platforms_entry(
    api, monkeypatch, platform, identity
):
    client, runtime = api
    monkeypatch.setattr(device_modules, "load_module_manifests", shipped_manifests)
    runtime.device_platform[DEVICE] = platform

    rows = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()

    row = {entry["name"]: entry for entry in rows["modules"]}["podman"]
    assert (
        row["runner"],
        row["method"],
        row["publisher"],
        row["license"],
        row["corresponding_source"],
    ) == identity
    assert row["is_supported"] is True


def test_a_windows_machine_takes_the_file_share_as_its_own_server(
    api, monkeypatch, tmp_path
):
    client, runtime = api
    monkeypatch.setattr(device_modules, "load_module_manifests", shipped_manifests)
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_platform[DEVICE] = WINDOWS

    answer = client.post(
        f"{MODULE_PATH}/start", json={"device_id": DEVICE, "module": "samba"}
    )

    assert answer.status_code == 200
    assert modules_file(tmp_path)["samba"]["want"] == "running"


def test_a_machine_below_the_entry_floor_cannot_run_the_module(api, monkeypatch):
    client, runtime = api
    monkeypatch.setattr(
        device_modules,
        "load_module_manifests",
        lambda: {
            "floored": {
                "title": "Floored",
                "platforms": {
                    "linux-amd64": {
                        **system_entry("floored", ["floored"]),
                        "min_version": "2.28",
                    }
                },
            }
        },
    )
    runtime.agent_sessions.online.add(DEVICE)
    old = {"os": "linux", "family": "rhel", "arch": "amd64", "version": "2.17"}
    new = {**old, "version": "2.34"}

    runtime.device_platform[DEVICE] = old
    row = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]
    refused = client.post(
        f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "floored"}
    )
    runtime.device_platform[DEVICE] = new
    newer = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"][0]

    assert row["is_supported"] is False
    assert refused.json()["detail"]["code"] == "no_platform_build"
    assert newer["is_supported"] is True


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

    device_modules.store_config(runtime, context, {"accounts": []})

    # The agent checks the section the state will carry, not the file.
    assert runtime.agent_sessions.validations == [
        (LAPTOP, MODULE, {"shares": [], "users": [], "passwords": {}})
    ]
    assert runtime.desired_states.read(LAPTOP, MODULE) == {"accounts": []}
    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]
    assert context.config == {"accounts": []}
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

    assert response.json() == {"is_applied": True, "changes": [], "failures": []}
    assert [push[0] for push in runtime.agent_sessions.pushes] == [LAPTOP]
    assert (
        client.post(f"{BLOCK_PATH}/apply", json={"device_id": OFFLINE}).status_code
        == 409
    )


@pytest.mark.parametrize(
    ("state", "is_marked"),
    [("installed", True), ("stopped", True), ("failed", True), ("running", False)],
)
def test_apply_marks_a_module_whose_state_is_not_its_want(box, state, is_marked):
    from neutrino_hub.modules.devices.retry_marks import DeviceRetryMarks

    client, runtime = box
    runtime.desired_states.set_want(LAPTOP, MODULE, "running")
    runtime.report(LAPTOP, MODULE, state)

    client.post(f"{BLOCK_PATH}/apply", json={"device_id": LAPTOP})

    assert (MODULE in DeviceRetryMarks().marks(LAPTOP)) is is_marked


# --- a press on a failed module tries again ---


def retry_marks() -> dict:
    from neutrino_hub.modules.devices.retry_marks import DeviceRetryMarks

    return DeviceRetryMarks().marks(DEVICE)


@pytest.mark.parametrize("state", ["failed", "install_failed"])
@pytest.mark.parametrize("press", ["install", "start", "stop", "uninstall"])
def test_a_press_on_a_failed_module_puts_a_fresh_retry_mark(api, press, state):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_modules[DEVICE] = {
        "fakedesk": {"state": state, "code": "download_failed", "params": {}}
    }

    client.post(
        f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "fakedesk"}
    )
    first = retry_marks()
    client.post(
        f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "fakedesk"}
    )
    second = retry_marks()

    assert set(first) == {"fakedesk"}
    assert first["fakedesk"] != second["fakedesk"]
    assert len(runtime.agent_sessions.pushes) == 2


@pytest.mark.parametrize(
    ("press", "state"),
    [
        ("install", "installed"),
        ("start", "running"),
        ("stop", "stopped"),
        ("uninstall", "absent"),
        ("install", "installing"),
        ("start", "queued"),
        ("start", "unsupported"),
        ("install", "unknown"),
    ],
)
def test_a_press_on_a_module_that_reads_its_want_or_moves_puts_no_mark(
    api, press, state
):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_modules[DEVICE] = {"fakedesk": {"state": state}}

    client.post(
        f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "fakedesk"}
    )

    assert retry_marks() == {}


@pytest.mark.parametrize(
    ("press", "state"),
    [
        ("start", "installed"),
        ("start", "stopped"),
        ("start", "absent"),
        ("stop", "running"),
        ("install", "absent"),
        ("uninstall", "installed"),
    ],
)
def test_a_press_on_a_module_whose_state_is_not_its_want_puts_a_mark(api, press, state):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_modules[DEVICE] = {"fakedesk": {"state": state}}

    client.post(
        f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "fakedesk"}
    )

    assert set(retry_marks()) == {"fakedesk"}


def test_start_again_on_a_module_left_installed_under_running_asks_again(api):
    """The want is already running and the machine reads installed: the
    want alone would change nothing in the state, the mark does."""
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    runtime.desired_states.set_want(DEVICE, "fakedesk", "running")
    runtime.device_modules[DEVICE] = {"fakedesk": {"state": "installed"}}

    client.post(
        f"{MODULE_PATH}/start", json={"device_id": DEVICE, "module": "fakedesk"}
    )
    first = retry_marks()
    client.post(
        f"{MODULE_PATH}/start", json={"device_id": DEVICE, "module": "fakedesk"}
    )

    assert set(first) == {"fakedesk"}
    assert retry_marks()["fakedesk"] != first["fakedesk"]
    assert len(runtime.agent_sessions.pushes) == 2


# --- the two modules the agent carries ---


@pytest.mark.parametrize("name", ["terminal", "remote_desktop"])
def test_a_module_the_agent_carries_is_a_row_on_every_system_with_its_want(
    api, monkeypatch, name
):
    client, runtime = api
    monkeypatch.setattr(device_modules, "load_module_manifests", shipped_manifests)
    for platform in (WINDOWS, DARWIN, {"os": "linux", "family": "arch"}):
        runtime.device_platform[DEVICE] = platform
        rows = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()
        row = {entry["name"]: entry for entry in rows["modules"]}[name]
        assert (row["method"], row["runner"], row["is_supported"]) == (
            "agent",
            name,
            True,
        )
    assert row["want"] == ("running" if name == "terminal" else "stopped")


@pytest.mark.parametrize("press", ["install", "start", "stop", "uninstall"])
@pytest.mark.parametrize("name", ["terminal", "remote_desktop"])
def test_no_press_applies_to_a_module_the_agent_carries(
    api, monkeypatch, tmp_path, press, name
):
    client, runtime = api
    runtime.agent_sessions.online.add(DEVICE)
    monkeypatch.setattr(device_modules, "load_module_manifests", shipped_manifests)

    refused = client.post(
        f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": name}
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "module_not_optional",
        "params": {"name": name},
    }
    assert modules_file(tmp_path) == {}


# --- container modules depend on Containers alone ---


@pytest.fixture
def containers_api(api, monkeypatch, demo_container_module):
    """The page over the shipped manifests and the test-only container module."""
    client, runtime = api
    monkeypatch.setattr(device_modules, "load_module_manifests", shipped_manifests)
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_platform[DEVICE] = {
        "os": "linux",
        "family": "debian",
        "arch": "amd64",
        "version": "2.36",
    }
    return client, runtime


@pytest.mark.parametrize(
    "press, want", [("install", "installed"), ("start", "running")]
)
def test_a_container_module_s_install_or_start_wants_containers_running_first(
    containers_api, tmp_path, press, want
):
    client, runtime = containers_api
    runtime.device_modules[DEVICE] = {"podman": {"state": "stopped"}}

    answer = client.post(
        f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "demo"}
    )

    assert answer.status_code == 200
    assert modules_file(tmp_path) == {
        "podman": {"want": "running", "is_settled": False, "version": ""},
        "demo": {"want": want, "is_settled": False, "version": ""},
    }
    # The report leaves demo out, so it reads absent and its press marks it.
    assert set(retry_marks()) == {"podman", "demo"}
    assert len(runtime.agent_sessions.pushes) == 1


def test_containers_already_wanted_running_is_left_as_it_is(containers_api, tmp_path):
    client, runtime = containers_api
    runtime.desired_states.set_want(DEVICE, "podman", "running")
    runtime.device_modules[DEVICE] = {"podman": {"state": "running"}}

    client.post(f"{MODULE_PATH}/install", json={"device_id": DEVICE, "module": "demo"})

    assert modules_file(tmp_path)["podman"] == {
        "want": "running",
        "is_settled": False,
        "version": "",
    }
    assert "podman" not in retry_marks()


def test_stopping_a_container_module_leaves_containers_as_it_is(
    containers_api, tmp_path
):
    client, _runtime = containers_api

    client.post(f"{MODULE_PATH}/stop", json={"device_id": DEVICE, "module": "demo"})

    assert "podman" not in modules_file(tmp_path)


def test_containers_cannot_be_uninstalled_while_a_container_module_is_installed(
    containers_api, tmp_path
):
    client, runtime = containers_api
    runtime.desired_states.set_want(DEVICE, "podman", "running")
    runtime.desired_states.set_want(DEVICE, "demo", "stopped")

    refused = client.post(
        f"{MODULE_PATH}/uninstall", json={"device_id": DEVICE, "module": "podman"}
    )
    runtime.desired_states.set_want(DEVICE, "demo", "absent")
    taken = client.post(
        f"{MODULE_PATH}/uninstall", json={"device_id": DEVICE, "module": "podman"}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "module_in_use",
        "params": {"modules": ["demo"]},
    }
    assert taken.status_code == 200
    assert modules_file(tmp_path)["podman"]["want"] == "absent"


def test_a_container_module_a_report_leaves_out_reads_absent(containers_api):
    """The agent has a runner for a container module only once a state names it."""
    client, runtime = containers_api
    runtime.device_modules[DEVICE] = {"podman": {"state": "running"}}

    rows = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"]

    by_name = {row["name"]: row for row in rows}
    assert by_name["demo"]["state"] == "absent"
    assert by_name["hermes_webui"]["state"] == "absent"
    assert by_name["samba"]["state"] == "unknown"


def test_a_container_module_reads_unknown_until_the_device_reports(containers_api):
    client, _runtime = containers_api

    rows = client.get(MODULE_PATH, params={"device_id": DEVICE}).json()["modules"]

    assert {row["name"]: row["state"] for row in rows}["demo"] == "unknown"


def test_siyuans_uninstall_voids_its_keys_and_its_install_settles_them(
    api, monkeypatch
):
    client, runtime = api
    monkeypatch.setattr(device_modules, "load_module_manifests", shipped_manifests)
    runtime.agent_sessions.online.add(DEVICE)
    runtime.device_platform[DEVICE] = WINDOWS
    called: list = []
    monkeypatch.setattr(
        device_modules,
        "revoke_instance_keys",
        lambda store, key, module: called.append(("revoke", key, module)),
    )
    monkeypatch.setattr(
        device_modules,
        "settle_instance_keys",
        lambda store, key, module, name: called.append(("settle", key, module)),
    )

    for press in ("install", "uninstall"):
        answer = client.post(
            f"{MODULE_PATH}/{press}", json={"device_id": DEVICE, "module": "siyuan"}
        )
        assert answer.status_code == 200, press

    assert called == [("settle", DEVICE, "siyuan"), ("revoke", DEVICE, "siyuan")]
