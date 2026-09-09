"""What the Modules block on a device is told, and what it can act on.

The bug these came from: a device showed its remote desktop running in the
remote-desktop block and "not installed, waiting for the agent" in the module
list above it. Management is a completed handshake — a token the agent has
authenticated with — so a failed install or a forgotten device never reads
managed here.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.devices.agent_module_cache import AgentModuleArtifact
from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice
from neutrino_hub.web.events import PanelEventBus
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import devices as devices_router
from tests.conftest import FakeAgentSessions, holding_dispatch

MAC = "aa:bb:cc:dd:ee:ff"
FINGERPRINT = "ab" * 32


class FakeRegistry:
    device: ManagedDevice

    def get(self, mac_address: str) -> ManagedDevice:
        return FakeRegistry.device

    def annotate(self, mac_address: str, payload: dict) -> ManagedDevice:
        if "name" in payload:
            FakeRegistry.device.name = payload["name"]
        return FakeRegistry.device


class StubModuleCache:
    """A cache that answers at once and never reaches a vendor."""

    def artifact(self, *, name, manifest, platform):
        return AgentModuleArtifact(
            key=f"{name}-key", path=Path("/nonexistent"), digest="d", package_kind="deb"
        )


class FakeRuntime:
    def __init__(self):
        self.events = PanelEventBus()
        self.client_modules = {}
        self.client_platform = {}
        self.client_hostname = {}
        self.client_metrics = {}
        self.client_address = {}
        self.client_last_error = {}
        self.pending = {}
        self.enrollments = {}
        self.agent_sessions = FakeAgentSessions()
        self.agent_modules = StubModuleCache()
        self.device_install_locks = DeviceInstallLocks()
        # A dispatch that holds each order open briefly and never answers:
        # the row shows the step, and no worker sits on a lock for long.
        self.agent_module_orders = AgentModuleController(
            cache=self.agent_modules,
            locks=self.device_install_locks,
            dispatch=holding_dispatch,
        )

    def forget_client_state(self, mac_address: str) -> None:
        key = mac_address.lower()
        for held in (
            self.client_modules,
            self.client_platform,
            self.client_metrics,
            self.client_address,
            self.client_last_error,
            self.pending,
        ):
            held.pop(key, None)
        self.agent_module_orders.forget(key)


def beating(seconds_ago: float) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return stamp.isoformat()


@pytest.fixture
def api(monkeypatch):
    FakeRegistry.device = ManagedDevice(
        mac_address=MAC,
        name="testbox",
        client=DeviceClientInfo(token_sha256="t" * 64),
    )
    monkeypatch.setattr(devices_router, "DeviceRegistry", FakeRegistry)
    monkeypatch.setattr(devices_router, "certificate_fingerprint", lambda: FINGERPRINT)
    monkeypatch.setattr(
        devices_router,
        "load_module_manifests",
        lambda: {
            "fakedesk": {
                "title": "FakeDesk",
                "installer": "hub",
                "platforms": {"debian": {}},
            }
        },
    )
    app = FastAPI()
    app.include_router(devices_router.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


def test_an_agent_with_no_socket_is_not_online(api):
    client, _ = api

    answer = client.get(f"/api/devices/{MAC}/modules").json()

    assert answer["is_agent_managed"]
    assert not answer["is_agent_online"]


def test_an_agent_holding_a_socket_is_online(api):
    client, runtime = api
    runtime.agent_sessions.online.add(MAC)

    answer = client.get(f"/api/devices/{MAC}/modules").json()

    assert answer["is_agent_online"]


def test_an_agent_whose_socket_closed_is_not_online(api):
    """Which is the reported bug: the install flag stays true for ever, so
    this device drew every module as absent while its remote desktop was
    plainly running."""
    client, runtime = api
    runtime.agent_sessions.online.add(MAC)
    runtime.agent_sessions.online.discard(MAC)

    answer = client.get(f"/api/devices/{MAC}/modules").json()

    assert answer["is_agent_managed"]
    assert not answer["is_agent_online"]


def test_what_the_agent_reported_is_found_whatever_case_the_MAC_is_asked_in(api):
    """Everything else keys by the lowercased address; looking the runtime up
    by the raw path segment finds nothing, and every module then reads as
    waiting for an agent that is in fact answering."""
    client, runtime = api
    runtime.agent_sessions.online.add(MAC)
    runtime.client_modules[MAC] = {"fakedesk": {"state": "installed"}}

    answer = client.get(f"/api/devices/{MAC.upper()}/modules").json()

    assert answer["modules"][0]["state"] == "installed"


def test_the_manifest_kind_reaches_the_row_for_the_ssh_confirm(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(
        devices_router,
        "load_module_manifests",
        lambda: {
            "ssh_server": {
                "title": "SSH server",
                "kind": "openssh",
                "platforms": {"linux-debian": {"service": "ssh"}},
            }
        },
    )

    answer = client.get(f"/api/devices/{MAC}/modules").json()

    assert answer["modules"][0]["kind"] == "openssh"


def test_a_native_module_offers_nothing_where_the_platform_carries_it(api, monkeypatch):
    client, runtime = api
    monkeypatch.setattr(
        devices_router,
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

    runtime.client_platform[MAC] = {"os": "windows", "family": "", "arch": "amd64"}
    native = client.get(f"/api/devices/{MAC}/modules").json()["modules"][0]
    assert native["is_native"] is True

    runtime.client_platform[MAC] = {"os": "linux", "family": "debian", "arch": "amd64"}
    package = client.get(f"/api/devices/{MAC}/modules").json()["modules"][0]
    assert package["is_native"] is False


def test_the_installer_tier_reaches_the_row(api):
    client, _ = api

    answer = client.get(f"/api/devices/{MAC}/modules").json()

    assert answer["modules"][0]["installer"] == "hub"


def test_a_user_tier_click_queues_nothing_and_the_row_keeps_its_state(api, monkeypatch):
    """user-tier rows never offer install or uninstall; a request arriving
    anyway — an old page, a hand-built call — must order nothing."""
    client, runtime = api
    monkeypatch.setattr(
        devices_router,
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
    runtime.client_modules[MAC] = {"teamviewer": {"state": "absent"}}

    answer = client.put(
        f"/api/devices/{MAC}/modules/teamviewer", json={"is_enabled": True}
    ).json()

    assert answer["modules"][0]["installer"] == "user"
    assert answer["modules"][0]["state"] == "absent"
    assert runtime.agent_module_orders.open_order_for(MAC, "teamviewer") is None


def test_a_click_queues_one_order_and_the_row_shows_the_step(api):
    client, runtime = api

    answer = client.put(
        f"/api/devices/{MAC}/modules/fakedesk", json={"is_enabled": True}
    ).json()

    assert answer["modules"][0]["state"] == "installing"
    order = runtime.agent_module_orders.open_order_for(MAC, "fakedesk")
    assert order is not None and order.action == "install"
    unknown = client.put(
        f"/api/devices/{MAC}/modules/nonsense", json={"is_enabled": True}
    )
    assert unknown.status_code == 404


def test_forgetting_a_device_drops_what_was_queued_for_it(api, monkeypatch):
    """A command queued for a device that is forgotten would be delivered to
    whatever machine turns up on that MAC next: enrol a rebuilt box and its
    first heartbeat drains a shutdown nobody asked it for."""
    client, runtime = api
    monkeypatch.setattr(FakeRegistry, "forget", lambda self, mac: None, raising=False)
    runtime.pending[MAC] = ["shutdown"]
    runtime.client_modules[MAC] = {"fakedesk": {"state": "installed"}}

    assert client.delete(f"/api/devices/{MAC}").status_code == 200

    assert runtime.pending == {}
    assert runtime.client_modules == {}


@pytest.mark.parametrize(
    "address", ["hello", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "", "12345"]
)
def test_a_device_has_to_be_addressed_by_a_MAC(api, address):
    """Every part of a device is keyed by its address — the registry, the host
    key store, the command queue, the magic packet — so a record stored under
    something else is one none of them can act on."""
    client, _ = api

    response = client.put(f"/api/devices/{address}", json={"name": "nonsense"})

    assert response.status_code in (400, 404, 405)


def test_an_unknown_remote_desktop_product_is_refused_at_once(api):
    """`set_password_stream` is an async generator, so calling it runs none of
    its body: the refusal it documents used to surface minutes later as a
    failed task rather than as this answer."""
    client, _ = api
    FakeRegistry.device.ssh = {"host": "10.0.0.5", "username": "me"}

    response = client.post(
        f"/api/devices/{MAC}/remote_desktop/anydsk/password",
        json={"password": "hunter2hunter2"},  # scan: allow
    )

    assert response.status_code == 400


def test_renaming_a_device_keeps_its_monitor_alive(api):
    """The page redraws the tile from this answer. Built with no metrics, it
    reads as a machine that went offline the moment somebody renamed it."""
    client, runtime = api
    runtime.agent_sessions.online.add(MAC)
    runtime.client_metrics[MAC] = {"cpu_percent": 12.5, "memory_percent": 40.0}

    answer = client.put(f"/api/devices/{MAC}", json={"name": "renamed"}).json()

    assert answer["name"] == "renamed"
    assert answer["client"]["cpu_percent"] == 12.5


def test_a_link_that_cannot_be_built_generates_no_ticket(api, monkeypatch):
    """The ticket is a join secret. One nobody was ever shown is one lying
    around until the panel restarts."""
    client, runtime = api
    monkeypatch.setattr(devices_router, "_agent_urls", lambda runtime: [])

    response = client.post("/api/devices/enrollment", json={"name": "laptop"})

    assert response.status_code == 400
    assert runtime.enrollments == {}


def test_a_link_generated_for_a_device_binds_to_that_device(api, monkeypatch):
    """The per-device link on an unmanaged card. Bound to the MAC, the machine
    that pastes it joins as the device already on the page rather than as a
    second record keyed by its own machine id."""
    client, runtime = api
    monkeypatch.setattr(
        devices_router, "_agent_urls", lambda runtime: ["http://192.168.8.1:8080"]
    )

    response = client.post(
        "/api/devices/enrollment",
        json={"name": "xenode", "mac_address": MAC.upper()},
    )

    assert response.status_code == 200
    ticket = runtime.enrollments[response.json()["token"]]
    assert ticket["mac_address"] == MAC
    assert ticket["name"] == "xenode"


def test_the_link_is_one_shell_safe_token(api, monkeypatch):
    """base64url end to end: no character a shell splits or a URL escapes,
    and the payload decodes to every address plus the ticket."""
    client, runtime = api
    monkeypatch.setattr(
        devices_router,
        "_agent_urls",
        lambda runtime: ["http://192.168.8.1:8080", "http://10.0.0.1:8080"],
    )

    answer = client.post("/api/devices/enrollment", json={"name": "laptop"}).json()

    link = answer["link"]
    assert link.startswith("neutrino://enroll/")
    payload_text = link.removeprefix("neutrino://enroll/")
    assert not any(character in payload_text for character in "?&%#;|<> '\"=")
    padded = payload_text + "=" * (-len(payload_text) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    assert payload["urls"] == ["http://192.168.8.1:8080", "http://10.0.0.1:8080"]
    assert payload["token"] == answer["token"]
    assert payload["fp"] == FINGERPRINT


def test_a_lapsed_ticket_is_swept_when_the_next_one_is_generated(api, monkeypatch):
    client, runtime = api
    monkeypatch.setattr(
        devices_router, "_agent_urls", lambda runtime: ["http://192.168.8.1:8080"]
    )
    runtime.enrollments["stale"] = {"expires_at": 0.0}

    response = client.post("/api/devices/enrollment", json={"name": "laptop"})

    assert response.status_code == 200
    assert "stale" not in runtime.enrollments
    assert len(runtime.enrollments) == 1


def test_forgetting_a_device_revokes_its_account_keys(api, monkeypatch, tmp_path):
    """The cascade: every (device, account) gateway key dies with the record,
    so a forgotten machine cannot keep spending against the gateway."""
    from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
    from neutrino_hub.modules.cliproxyapi.config import CliproxyApiClientKey
    from neutrino_hub.modules.cliproxyapi.ops import (
        CliproxyApiConfigApplier,
        load_config,
        save_config,
    )
    from tests.conftest import unlock_vault

    client, _ = api
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    monkeypatch.setattr(FakeRegistry, "forget", lambda self, mac: None, raising=False)
    mine = CliproxyApiClientKey.generated("testbox/alice")
    theirs = CliproxyApiClientKey.generated("other/bob")
    config = load_config()
    config.client_keys = [mine, theirs]
    save_config(config)
    FakeRegistry.device.client.ai_key_ids = {"alice": mine.id}

    assert client.delete(f"/api/devices/{MAC}").status_code == 200

    assert [key.id for key in load_config().client_keys] == [theirs.id]
