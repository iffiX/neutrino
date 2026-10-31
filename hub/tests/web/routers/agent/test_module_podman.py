"""The Containers page's per-device API, with the agent underneath replaced.

The Run settings: ``machine/set`` refuses a Linux machine, an account that
is not available, a Windows account with no login and a Windows disk limit
of 0 before the agent is asked, and takes a macOS disk of 0; the agent
checks the settings as the state carries them, with the login's password on
Windows alone and never the login's id; the view holds the stored settings
on Windows and macOS, the reported machine, the accounts, and the memory
the container modules need past the machine's.
"""

import json

import pytest

from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.accounts import DeviceAccount, DeviceAccountStore
from neutrino_hub.web.routers.agent import module_podman as podman_router
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, HOST, OFFLINE, module_box

BASE = "/api/agent/module/podman"
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}
DARWIN = {"os": "darwin", "family": "", "arch": "arm64", "version": "15.3.1"}
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
RUN_SETTINGS = {"account": "lab", "cpus": 4, "memory_gib": 8, "disk_gib": 120}


def login(name: str) -> str:
    return (
        SecretVault()
        .add(
            kind="login", name=name, secret={"username": name, "password": f"pw-{name}"}
        )
        .id
    )


def available(
    runtime, name: str, *, device_id: str = DEVICE, login_id: str = ""
) -> None:
    DeviceAccountStore(runtime.desired_states).add(
        device_id, DeviceAccount(account=name, login_id=login_id)
    )


@pytest.fixture
def box(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    client, runtime = module_box(monkeypatch, tmp_path, podman_router.router)
    runtime.desired_states.write(
        DEVICE,
        "podman",
        {
            "containers": [{"name": "web", "image": "nginx", "ports": ["8080:80"]}],
            "mirrors": [],
        },
    )
    runtime.report(
        DEVICE,
        "podman",
        "installed",
        is_active=True,
        version="4.9.3",
        containers=[
            {
                "name": "web",
                "image": "nginx",
                "status": "Up",
                "is_running": True,
                "source": "declared",
                "host_ports": [8080],
            },
            {
                "name": "adhoc",
                "image": "alpine",
                "status": "Exited",
                "is_running": False,
                "source": "manual",
                "host_ports": [],
            },
        ],
    )
    with client:
        yield client, runtime


def test_import_declares_the_containers_the_machine_runs(box):
    """What podman inspect reported becomes a declaration; a container a unit
    already stands for comes up with the machine, one started by hand does
    not."""
    client, runtime = box
    runtime.desired_states.forget(DEVICE)
    runtime.report(
        DEVICE,
        "podman",
        "installed",
        mirrors=["https://mirror.example/v2"],
        containers=[
            {
                "name": "web",
                "image": "docker.io/library/nginx:1.27",
                "status": "Up",
                "is_running": True,
                "source": "manual",
                "host_ports": [8080],
                "ports": ["8080:80"],
                "volumes": ["/srv/web:/usr/share/nginx/html"],
                "environment": ["NGINX_PORT=80"],
                "has_unit": True,
            },
            {
                "name": "adhoc",
                "image": "alpine",
                "status": "Exited",
                "is_running": False,
                "source": "manual",
                "host_ports": [],
                "has_unit": False,
            },
        ],
    )

    response = client.post(f"{BASE}/import", json={"device_id": DEVICE})

    assert response.status_code == 200
    assert runtime.desired_states.read(DEVICE, "podman") == {
        "containers": [
            {
                "name": "web",
                "image": "docker.io/library/nginx:1.27",
                "ports": ["8080:80"],
                "volumes": ["/srv/web:/usr/share/nginx/html"],
                "environment": ["NGINX_PORT=80"],
                "command": "",
                "is_autostart": True,
            },
            {
                "name": "adhoc",
                "image": "alpine",
                "ports": [],
                "volumes": [],
                "environment": [],
                "command": "",
                "is_autostart": False,
            },
        ],
        "mirrors": ["https://mirror.example/v2"],
    }
    assert [c["name"] for c in response.json()["containers"]] == ["web", "adhoc"]


def test_a_running_engine_reads_as_installed(box):
    client, runtime = box
    runtime.report(DEVICE, "podman", "running", is_active=True, containers=[])

    payload = client.get(BASE, params={"device_id": DEVICE}).json()

    assert payload["is_installed"] is True
    assert payload["state"] == "running"


def test_the_view_separates_declared_from_manual(box):
    client, _ = box

    payload = client.get(BASE, params={"device_id": DEVICE}).json()

    assert [c["name"] for c in payload["containers"]] == ["web"]
    by_name = {c["name"]: c for c in payload["running"]}
    assert by_name["web"]["source"] == "declared"
    assert by_name["adhoc"]["source"] == "manual"
    assert payload["hub_containers"] == []
    assert payload["is_installed"] is True
    assert payload["is_active"] is True
    assert payload["version"] == "4.9.3"
    assert (payload["device_id"], payload["host"]) == (DEVICE, HOST)


def test_saving_containers_checks_stores_and_pushes(box):
    client, runtime = box

    response = client.post(
        f"{BASE}/container/set",
        json={
            "device_id": DEVICE,
            "containers": [{"name": "redis", "image": "redis:7"}],
        },
    )

    assert response.status_code == 200
    key, module, checked = runtime.agent_sessions.validations[0]
    assert (key, module) == (DEVICE, "podman")
    assert [c["name"] for c in checked["containers"]] == ["redis"]
    assert (
        runtime.desired_states.read(DEVICE, "podman")["containers"][0]["name"]
        == "redis"
    )
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE]


def test_a_bad_declaration_is_refused_and_nothing_stored(box):
    client, runtime = box
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "container_name_invalid",
        "params": {"name": "Bad"},
    }

    response = client.post(
        f"{BASE}/container/set",
        json={"device_id": DEVICE, "containers": [{"name": "Bad", "image": "x"}]},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "container_name_invalid"
    assert (
        runtime.desired_states.read(DEVICE, "podman")["containers"][0]["name"] == "web"
    )


def test_a_port_with_no_protocol_is_refused_with_the_agents_code(box):
    client, runtime = box
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "service_protocol_none",
        "params": {"port": 53},
    }

    response = client.post(
        f"{BASE}/container/set",
        json={
            "device_id": DEVICE,
            "containers": [
                {
                    "name": "dns",
                    "image": "coredns",
                    "ports": ["53:53"],
                    "services": [{"port": 53, "kind": "port", "protocols": []}],
                }
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "service_protocol_none"
    assert response.json()["detail"]["params"] == {"port": 53}


def test_the_view_holds_what_the_machine_detected_on_each_port(box):
    client, runtime = box
    runtime.report(
        DEVICE,
        "podman",
        "running",
        is_active=True,
        containers=[
            {
                "name": "web",
                "image": "nginx",
                "status": "Up",
                "is_running": True,
                "source": "declared",
                "host_ports": [8080, 5353],
                "host_bindings": [
                    {
                        "address": "",
                        "port": 8080,
                        "protocol": "tcp",
                        "detected": "http",
                    },
                    {"address": "", "port": 5353, "protocol": "udp", "detected": ""},
                ],
            }
        ],
    )

    payload = client.get(BASE, params={"device_id": DEVICE}).json()

    assert payload["running"][0]["host_bindings"] == [
        {"address": "", "port": 8080, "protocol": "tcp", "detected": "http"},
        {"address": "", "port": 5353, "protocol": "udp", "detected": ""},
    ]
    assert payload["containers"][0]["services"] == []


def test_saving_mirrors_keeps_the_containers(box):
    client, runtime = box

    response = client.post(
        f"{BASE}/mirror/set",
        json={"device_id": DEVICE, "mirrors": ["mirror.example"]},
    )

    assert response.status_code == 200
    stored = runtime.desired_states.read(DEVICE, "podman")
    assert stored["mirrors"] == ["mirror.example"]
    assert stored["containers"][0]["name"] == "web"
    assert response.json()["mirrors"] == ["mirror.example"]


def test_a_container_is_driven_on_the_device_and_the_view_answers(box):
    client, runtime = box

    response = client.post(
        f"{BASE}/container/restart", json={"device_id": DEVICE, "name": "web"}
    )

    assert response.status_code == 200
    assert runtime.agent_sessions.commands == [
        (DEVICE, "podman", "control", {"name": "web", "action": "restart"})
    ]
    assert response.json()["device_id"] == DEVICE


def test_a_container_the_agent_does_not_know_is_answered_with_its_code(box):
    client, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 1,
        "code": "container_unknown",
        "params": {"name": "ghost"},
        "output": "",
    }

    response = client.post(
        f"{BASE}/container/start", json={"device_id": DEVICE, "name": "ghost"}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "container_unknown",
        "params": {"name": "ghost"},
    }


def test_the_journal_is_read_on_the_device(box):
    client, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 0,
        "code": "",
        "params": {},
        "output": "one\ntwo\nthree",
    }

    response = client.get(
        f"{BASE}/container/journal",
        params={"device_id": DEVICE, "name": "web", "lines": 2},
    )

    assert response.json() == {"text": "two\nthree"}
    assert runtime.agent_sessions.commands == [
        (DEVICE, "podman", "journal", {"name": "web"})
    ]


def test_a_container_journal_read_waits_for_no_report(box):
    client, runtime = box
    runtime.agent_sessions.outcome = {
        "exit_code": 0,
        "code": "",
        "params": {},
        "output": "one",
    }

    response = client.get(
        f"{BASE}/container/journal", params={"device_id": DEVICE, "name": "web"}
    )

    assert response.status_code == 200
    assert runtime.agent_sessions.waited == []


def test_an_offline_device_takes_no_verb(box):
    client, runtime = box

    started = client.post(
        f"{BASE}/container/start", json={"device_id": OFFLINE, "name": "web"}
    )
    journal = client.get(
        f"{BASE}/container/journal", params={"device_id": OFFLINE, "name": "web"}
    )

    assert started.status_code == 409
    assert journal.status_code == 409
    assert runtime.agent_sessions.commands == []


def test_hub_urls_resolve_and_foreign_registries_decline():
    assert "repositories/library/python/tags" in podman_router.hub_tags_url("python")
    assert "repositories/library/redis/tags" in podman_router.hub_tags_url(
        "docker.io/library/redis:7"
    )
    assert "repositories/ann/tool/tags" in podman_router.hub_tags_url(
        "docker.io/ann/tool"
    )
    assert podman_router.hub_tags_url("ghcr.io/owner/thing") is None
    assert podman_router.hub_tags_url("quay.io/owner/thing:1") is None


def test_tags_come_from_docker_hub_best_effort(box, monkeypatch):
    client, _ = box
    monkeypatch.setattr(
        podman_router,
        "list_image_tags",
        lambda image: ["3.12", "3.11"] if image == "python" else [],
    )

    python = client.get(f"{BASE}/tag", params={"device_id": DEVICE, "image": "python"})
    foreign = client.get(
        f"{BASE}/tag", params={"device_id": DEVICE, "image": "ghcr.io/x/y"}
    )

    assert python.json() == {"tags": ["3.12", "3.11"]}
    assert foreign.json() == {"tags": []}


def test_saving_containers_keeps_each_ones_services(box):
    client, runtime = box
    services = [
        {"port": 8080, "kind": "web", "scheme": "https", "protocols": []},
        {"port": 5353, "kind": "port", "scheme": "http", "protocols": ["tcp", "udp"]},
    ]
    container = {
        "name": "web",
        "image": "nginx",
        "ports": ["8080:80", "5353:53"],
        "services": services,
    }

    response = client.post(
        f"{BASE}/container/set", json={"device_id": DEVICE, "containers": [container]}
    )

    assert response.status_code == 200
    checked = runtime.agent_sessions.validations[0][2]
    assert checked["containers"][0]["services"] == services
    stored = runtime.desired_states.read(DEVICE, "podman")
    assert stored["containers"][0]["services"] == services
    assert response.json()["containers"][0]["services"] == services


# --- the Run settings ---


@pytest.mark.parametrize("platform", [LINUX, {}])
def test_run_settings_are_refused_for_a_machine_that_is_not_windows_or_macos(
    box, platform
):
    client, runtime = box
    if platform:
        runtime.device_platform[DEVICE] = platform

    response = client.post(
        f"{BASE}/machine/set", json={"device_id": DEVICE, **RUN_SETTINGS}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "unsupported_platform", "params": {}}
    assert runtime.agent_sessions.validations == []
    assert "machine" not in runtime.desired_states.read(DEVICE, "podman")


def test_an_account_not_available_and_a_windows_account_with_no_login_are_refused(
    box,
):
    client, runtime = box
    runtime.device_platform[DEVICE] = WINDOWS
    body = {"device_id": DEVICE, **RUN_SETTINGS}

    unknown = client.post(f"{BASE}/machine/set", json=body)
    available(runtime, "lab")
    missing = client.post(f"{BASE}/machine/set", json=body)

    assert unknown.status_code == missing.status_code == 400
    assert unknown.json()["detail"] == {
        "code": "account_unknown",
        "params": {"account": "lab"},
    }
    assert missing.json()["detail"] == {
        "code": "credential_missing",
        "params": {"account": "lab"},
    }
    assert runtime.agent_sessions.validations == []
    assert "machine" not in runtime.desired_states.read(DEVICE, "podman")


def test_a_windows_disk_limit_of_0_is_refused_before_the_agent_is_asked(box):
    client, runtime = box
    runtime.device_platform[DEVICE] = WINDOWS
    available(runtime, "lab", login_id=login("lab"))

    response = client.post(
        f"{BASE}/machine/set", json={"device_id": DEVICE, **RUN_SETTINGS, "disk_gib": 0}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "machine_disk_invalid",
        "params": {"disk_gib": 0},
    }
    assert runtime.agent_sessions.validations == []
    assert "machine" not in runtime.desired_states.read(DEVICE, "podman")


def test_a_macos_disk_limit_of_0_is_podmans_default(box):
    client, runtime = box
    runtime.device_platform[DEVICE] = DARWIN
    available(runtime, "lab")

    response = client.post(
        f"{BASE}/machine/set", json={"device_id": DEVICE, **RUN_SETTINGS, "disk_gib": 0}
    )

    assert response.status_code == 200
    assert runtime.agent_sessions.validations[0][2]["machine"]["disk_gib"] == 0


def test_windows_run_settings_are_checked_with_the_password_and_stored_without_it(
    box,
):
    client, runtime = box
    runtime.device_platform[DEVICE] = WINDOWS
    available(runtime, "lab", login_id=login("lab"))

    response = client.post(
        f"{BASE}/machine/set", json={"device_id": DEVICE, **RUN_SETTINGS}
    )

    assert response.status_code == 200
    key, module, checked = runtime.agent_sessions.validations[0]
    assert (key, module) == (DEVICE, "podman")
    assert checked["machine"] == {**RUN_SETTINGS, "password": "pw-lab"}
    assert [c["name"] for c in checked["containers"]] == ["web"]
    stored = runtime.desired_states.read(DEVICE, "podman")
    assert stored["machine"] == RUN_SETTINGS
    assert [c["name"] for c in stored["containers"]] == ["web"]
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE]
    assert response.json()["machine"] == RUN_SETTINGS
    assert "pw-lab" not in response.text


def test_macos_run_settings_take_no_login_and_send_no_password(box):
    client, runtime = box
    runtime.device_platform[DEVICE] = DARWIN
    available(runtime, "lab")

    response = client.post(
        f"{BASE}/machine/set", json={"device_id": DEVICE, **RUN_SETTINGS}
    )

    assert response.status_code == 200
    assert runtime.agent_sessions.validations[0][2]["machine"] == RUN_SETTINGS
    assert runtime.desired_states.read(DEVICE, "podman")["machine"] == RUN_SETTINGS


def test_the_agents_refusal_of_run_settings_is_answered_and_nothing_stored(box):
    client, runtime = box
    runtime.device_platform[DEVICE] = DARWIN
    available(runtime, "lab")
    runtime.agent_sessions.verdict = {
        "is_valid": False,
        "code": "machine_disk_shrink",
        "params": {"disk_gib": 50, "current_gib": 100},
    }

    response = client.post(
        f"{BASE}/machine/set",
        json={"device_id": DEVICE, **RUN_SETTINGS, "disk_gib": 50},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "machine_disk_shrink",
        "params": {"disk_gib": 50, "current_gib": 100},
    }
    assert "machine" not in runtime.desired_states.read(DEVICE, "podman")
    assert runtime.agent_sessions.pushes == []


def test_run_settings_for_a_machine_with_no_socket_are_refused(box):
    client, runtime = box
    runtime.device_platform[OFFLINE] = DARWIN
    available(runtime, "lab", device_id=OFFLINE)

    response = client.post(
        f"{BASE}/machine/set", json={"device_id": OFFLINE, **RUN_SETTINGS}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent_offline"


def test_a_negative_resource_is_refused_before_the_agent_is_asked(box):
    client, runtime = box
    runtime.device_platform[DEVICE] = DARWIN

    response = client.post(
        f"{BASE}/machine/set", json={"device_id": DEVICE, **RUN_SETTINGS, "cpus": -1}
    )

    assert response.status_code == 422
    assert runtime.agent_sessions.validations == []


def test_the_view_holds_the_run_settings_the_reported_machine_and_the_accounts(box):
    client, runtime = box
    runtime.device_platform[DEVICE] = WINDOWS
    runtime.device_accounts[DEVICE] = ["lab", "ann", "kim"]
    available(runtime, "lab")
    available(runtime, "ann")
    runtime.desired_states.write(
        DEVICE,
        "podman",
        {
            "containers": [],
            "mirrors": [],
            "machine": RUN_SETTINGS,
        },
    )
    reported = {
        "account": "lab",
        "is_running": True,
        "cpus": 4,
        "memory_gib": 7.5,
        "disk_gib": 120,
        "default_memory_gib": 4,
    }
    runtime.report(
        DEVICE, "podman", "running", is_active=True, containers=[], machine=reported
    )

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert view["accounts"] == ["lab", "ann"]
    assert view["machine"] == RUN_SETTINGS
    assert view["machine_state"] == reported
    assert view["memory_need"] is None


def test_the_view_advises_memory_past_the_run_settings(box, demo_container_module):
    client, runtime = box
    demo = json.loads((demo_container_module / "demo.json").read_text())
    (demo_container_module / "demo.json").write_text(
        json.dumps(dict(demo, memory_mib=3000))
    )
    runtime.device_platform[DEVICE] = DARWIN
    runtime.desired_states.set_want(DEVICE, "demo", "installed")
    runtime.desired_states.write(
        DEVICE,
        "podman",
        {"containers": [], "mirrors": [], "machine": dict(RUN_SETTINGS, memory_gib=2)},
    )

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert view["memory_need"] == {"need_gib": 3, "memory_gib": 2}


def test_the_run_settings_are_empty_on_windows_and_macos_until_stored_and_none_on_linux(
    box,
):
    client, runtime = box

    runtime.device_platform[DEVICE] = DARWIN
    darwin = client.get(BASE, params={"device_id": DEVICE}).json()
    runtime.device_platform[DEVICE] = LINUX
    linux = client.get(BASE, params={"device_id": DEVICE}).json()

    assert darwin["machine"] == {
        "account": "",
        "cpus": 0,
        "memory_gib": 0,
        "disk_gib": 0,
    }
    assert darwin["machine_state"] is None
    assert linux["machine"] is None
    assert linux["machine_state"] is None


# --- owners and hub containers ---


@pytest.fixture
def hub_box(box, demo_container_module):
    """The box with the test-only container module wanted running, and its
    container reported with its label."""
    client, runtime = box
    runtime.device_platform[DEVICE] = LINUX
    runtime.desired_states.set_want(DEVICE, "demo", "running")
    held = runtime.device_modules[DEVICE]["podman"]["details"]["containers"]
    held.append(
        {
            "name": "neutrino_demo",
            "image": "ghcr.io/acme/demo@sha256:" + "d" * 64,
            "status": "Up",
            "is_running": True,
            "source": "hub",
            "module": "demo",
            "host_ports": [41000],
        }
    )
    return client, runtime


def test_each_running_container_names_where_it_comes_from(hub_box):
    client, _ = hub_box

    payload = client.get(BASE, params={"device_id": DEVICE}).json()

    by_name = {c["name"]: (c["source"], c["module"]) for c in payload["running"]}
    assert by_name == {
        "web": ("declared", ""),
        "adhoc": ("manual", ""),
        "neutrino_demo": ("hub", "demo"),
    }


def test_the_view_holds_the_hub_containers_the_modules_compose(hub_box):
    client, _ = hub_box

    payload = client.get(BASE, params={"device_id": DEVICE}).json()

    assert [(c["module"], c["name"]) for c in payload["hub_containers"]] == [
        ("demo", "neutrino_demo_worker"),
        ("demo", "neutrino_demo"),
    ]
    assert payload["hub_containers"][1]["image"]["sources"][0] == "ghcr.io/acme/demo"
    assert payload["hub_containers"][0]["volumes"] == ["neutrino_demo_data:/data"]


def test_a_new_declared_name_may_not_start_with_neutrino(box):
    client, runtime = box

    refused = client.post(
        f"{BASE}/container/set",
        json={
            "device_id": DEVICE,
            "containers": [
                {"name": "web", "image": "nginx"},
                {"name": "neutrino_mine", "image": "alpine"},
            ],
        },
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "container_name_reserved",
        "params": {"name": "neutrino_mine"},
    }
    assert runtime.agent_sessions.validations == []


def test_a_declared_container_from_an_import_keeps_its_name(box):
    client, runtime = box
    runtime.desired_states.write(
        DEVICE,
        "podman",
        {"containers": [{"name": "neutrino_old", "image": "alpine"}], "mirrors": []},
    )

    kept = client.post(
        f"{BASE}/container/set",
        json={
            "device_id": DEVICE,
            "containers": [{"name": "neutrino_old", "image": "alpine:3"}],
        },
    )

    assert kept.status_code == 200


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
@pytest.mark.parametrize("name", ["neutrino_demo", "neutrino_demo_worker"])
def test_a_hub_container_takes_no_press_of_its_own(hub_box, action, name):
    client, runtime = hub_box

    refused = client.post(
        f"{BASE}/container/{action}", json={"device_id": DEVICE, "name": name}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "container_hub_owned",
        "params": {"name": name},
    }
    assert runtime.agent_sessions.commands == []


def test_a_hub_container_s_journal_is_read_as_any_container_s(hub_box):
    client, _ = hub_box

    answer = client.get(
        f"{BASE}/container/journal",
        params={"device_id": DEVICE, "name": "neutrino_demo"},
    )

    assert answer.status_code == 200
