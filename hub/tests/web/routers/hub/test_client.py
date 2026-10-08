"""The Clients page's routes: the list, the link, the switch, the delete.

The registry and the gateway config are real over a config root of their
own, so what is exercised is the whole write path — a link creating the
row before the program joins, a disable revoking the client's gateway key
and an enable minting one again, a delete taking key, record and socket —
and that every change says ``clients`` on the event bus.
"""

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.channel.tickets import ChannelTicketRegistry
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.cliproxyapi import ops as cliproxyapi_ops
from neutrino_hub.modules.cliproxyapi.ops import CliproxyApiConfigApplier, load_config
from neutrino_hub.modules.channel.constants import CHANNEL_ROLE_CLIENT
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.web.auth import SessionStore
from neutrino_hub.web import channel_addresses, channel_state
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import client as clients_router
from tests.conftest import unlock_vault

FINGERPRINT = "SHA256:" + "ab" * 32


class RecordingEvents:
    def __init__(self):
        self.published: list = []

    def publish(self, event_type, key="", data=None):
        self.published.append(event_type)


class RecordingSessions(ChannelSessionRegistry):
    """The client registry, remembering what was refused."""

    def __init__(self):
        super().__init__(CHANNEL_ROLE_CLIENT)
        self.refused: list = []

    def refuse_from_thread(self, key, code, params=None):
        self.refused.append((key, code, dict(params or {})))


class FakeRuntime:
    def __init__(self):
        self.enrollments = ChannelTicketRegistry()
        self.events = RecordingEvents()
        self.client_sessions = RecordingSessions()
        self.client_catalog_host = {}
        self.pushed: list = []
        self.overlays: list = []
        self.scopes: list = []
        self.sessions = SessionStore(password_hash="", session_ttl_hours=1)

    def host_scopes(self) -> list:
        return self.scopes

    def forget_client(self, client_id: str) -> None:
        self.client_catalog_host.pop(client_id, None)
        self.client_sessions.refuse_from_thread(client_id, "binding_unknown")


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(cliproxyapi_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        CliproxyApiConfigApplier, "is_installed", property(lambda self: False)
    )
    monkeypatch.setattr(
        channel_addresses,
        "channel_urls",
        lambda runtime: ["https://192.168.100.1:8443"],
    )
    monkeypatch.setattr(
        channel_addresses, "certificate_fingerprint", lambda: FINGERPRINT
    )
    runtime = FakeRuntime()
    monkeypatch.setattr(
        "neutrino_hub.web.channel_overlay.overlay_materials",
        lambda given: given.overlays,
    )
    monkeypatch.setattr(
        channel_state,
        "push_state",
        lambda given, role, client_id: given.pushed.append(client_id),
    )
    monkeypatch.setattr(
        channel_state,
        "push_states",
        lambda given, role: given.pushed.append(role),
    )
    app = FastAPI()
    app.include_router(clients_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), runtime


def decoded_link(link: str) -> dict:
    import base64
    import json
    import zlib

    payload = link.removeprefix("neutrino://enroll/")
    packed = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    return json.loads(zlib.decompress(packed))


def test_an_empty_hub_lists_no_clients(api):
    client, _ = api

    response = client.get("/api/hub/client")

    assert response.status_code == 200 and response.json()["clients"] == []


def test_a_link_creates_the_row_and_carries_the_client_role(api):
    client, runtime = api

    response = client.post(
        "/api/hub/client/enrollment/create", json={"name": " alice "}
    )

    assert response.status_code == 200
    body = response.json()
    payload = decoded_link(body["link"])
    assert payload["role"] == "client" and payload["fp"] == FINGERPRINT
    assert payload["urls"] == ["https://192.168.100.1:8443"]
    ticket = runtime.enrollments.get(payload["token"])
    rows = client.get("/api/hub/client").json()["clients"]
    assert len(rows) == 1
    assert ticket == {
        "token_sha256": hashlib.sha256(payload["token"].encode()).hexdigest(),
        "kind": "client",
        "name": "alice",
        "device_id": None,
        "client_id": rows[0]["id"],
        "expires_at": ticket["expires_at"],
    }
    assert body["expires_at"].endswith("+00:00")
    # The page shows this number, not a difference against its own clock.
    assert body["expires_in_s"] == 30 * 60
    assert rows[0] == {
        "id": rows[0]["id"],
        "name": "alice",
        "hostname": "",
        "platform_os": "",
        "version": "",
        "is_online": False,
        "last_seen": None,
        "is_disabled": False,
        "permission": None,
        "permission_devices": {},
    }
    assert runtime.events.published == ["clients"]


def test_a_blank_name_is_refused_and_a_new_link_replaces_only_client_tickets(api):
    client, runtime = api
    runtime.enrollments.put("dev", kind="agent", expires_at=9e12)

    refused = client.post("/api/hub/client/enrollment/create", json={"name": "  "})
    first = decoded_link(
        client.post("/api/hub/client/enrollment/create", json={"name": "a"}).json()[
            "link"
        ]
    )
    second = decoded_link(
        client.post("/api/hub/client/enrollment/create", json={"name": "b"}).json()[
            "link"
        ]
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == {"code": "client_name_required", "params": {}}
    assert runtime.enrollments.get("dev") is not None
    assert runtime.enrollments.get(first["token"]) is None
    assert runtime.enrollments.get(second["token"]) is not None
    assert len(runtime.enrollments.entries()) == 2
    assert first["token"] != second["token"]


def test_disabling_revokes_the_key_and_enabling_mints_one_again(api):
    client, runtime = api
    client_id = ClientRegistry().create("alice")
    from neutrino_hub.modules.clients.ai_keys import ensure_client_key

    ensure_client_key(ClientRegistry(), ClientRegistry().get(client_id))
    first = load_config().client_keys[0].id
    runtime.events.published.clear()

    off = client.post("/api/hub/client/disable", json={"client_id": client_id})

    assert off.status_code == 200
    assert off.json()["clients"][0]["is_disabled"] is True
    assert load_config().client_keys == []
    assert ClientRegistry().get(client_id).ai_key_id is None

    on = client.post("/api/hub/client/enable", json={"client_id": client_id})

    assert on.json()["clients"][0]["is_disabled"] is False
    keys = load_config().client_keys
    assert len(keys) == 1 and keys[0].id != first
    assert ClientRegistry().get(client_id).ai_key_id == keys[0].id
    assert runtime.pushed == [client_id, client_id]
    assert runtime.events.published == ["clients", "clients"]


def test_renaming_keeps_everything_else(api):
    client, runtime = api
    client_id = ClientRegistry().create("alice")
    runtime.events.published.clear()

    renamed = client.post(
        "/api/hub/client/set", json={"client_id": client_id, "name": " bob "}
    )
    blank = client.post(
        "/api/hub/client/set", json={"client_id": client_id, "name": " "}
    )
    nobody = client.post(
        "/api/hub/client/set", json={"client_id": "nobody", "name": "x"}
    )

    assert renamed.status_code == 200
    assert renamed.json()["clients"][0]["name"] == "bob"
    assert ClientRegistry().get(client_id).name == "bob"
    assert blank.status_code == 400
    assert blank.json()["detail"]["code"] == "client_name_required"
    assert nobody.status_code == 404
    assert runtime.events.published == ["clients"]


def test_deleting_takes_the_key_the_record_and_the_socket(api):
    client, runtime = api
    client_id = ClientRegistry().create("alice")
    from neutrino_hub.modules.clients.ai_keys import ensure_client_key

    ensure_client_key(ClientRegistry(), ClientRegistry().get(client_id))
    runtime.client_catalog_host[client_id] = "192.168.100.1"
    runtime.events.published.clear()

    response = client.post("/api/hub/client/remove", json={"client_id": client_id})

    assert response.status_code == 200 and response.json()["clients"] == []
    assert load_config().client_keys == []
    assert ClientRegistry().get(client_id) is None
    assert runtime.client_sessions.refused == [(client_id, "binding_unknown", {})]
    assert client_id not in runtime.client_catalog_host
    assert runtime.events.published == ["clients"]


def test_an_unknown_client_is_a_coded_404(api):
    client, _ = api

    updated = client.post("/api/hub/client/disable", json={"client_id": "nobody"})
    deleted = client.post("/api/hub/client/remove", json={"client_id": "nobody"})

    assert updated.status_code == 404 and deleted.status_code == 404
    assert updated.json()["detail"] == {
        "code": "client_unknown",
        "params": {"client_id": "nobody"},
    }


def test_the_list_prefers_the_live_session_over_the_record(api):
    import asyncio

    from neutrino_hub.modules.channel.sessions import ChannelSession

    client, runtime = api
    registry = ClientRegistry()
    client_id = registry.create("alice")
    registry.record_seen(
        client_id, hostname="laptop", platform={"os": "linux"}, version="0.1.0"
    )

    async def attach():
        await runtime.client_sessions.attach(
            ChannelSession(
                key=client_id,
                role=CHANNEL_ROLE_CLIENT,
                websocket=None,
                loop=asyncio.get_running_loop(),
                software="neutrino_client/0.2.0",
            )
        )

    asyncio.run(attach())

    row = client.get("/api/hub/client").json()["clients"][0]

    assert row["is_online"] is True
    assert (row["hostname"], row["platform_os"], row["version"]) == (
        "laptop",
        "linux",
        "0.2.0",
    )


ALL_KINDS = [
    "web",
    "port",
    "ai",
    "file",
    "rdp",
    "overlay",
    "terminal",
    "exec",
    "panel",
]


def test_the_list_carries_the_default_and_every_kind(api):
    client, _ = api
    client_id = ClientRegistry().create("alice")

    payload = client.get("/api/hub/client").json()

    assert payload["default_permission"] == ALL_KINDS[:-2]
    assert payload["permission_kinds"] == ALL_KINDS
    assert payload["clients"][0]["id"] == client_id
    assert payload["clients"][0]["permission"] is None


def test_setting_the_default_stores_it_and_pushes_every_client(api):
    client, runtime = api
    ClientRegistry().create("alice")

    reply = client.post(
        "/api/hub/client/default_permission/set", json={"kinds": ["web", "overlay"]}
    )

    assert reply.status_code == 200
    assert reply.json()["default_permission"] == ["web", "overlay"]
    assert ClientRegistry().default_permission() == ["web", "overlay"]
    assert runtime.pushed == ["client"]
    assert runtime.events.published == ["clients"]


def test_an_unknown_kind_is_a_coded_400(api):
    client, runtime = api
    client_id = ClientRegistry().create("alice")

    default = client.post(
        "/api/hub/client/default_permission/set", json={"kinds": ["web", "ssh"]}
    )
    own = client.post(
        "/api/hub/client/permission/set",
        json={"client_id": client_id, "kinds": ["telnet"]},
    )

    for reply, kind in ((default, "ssh"), (own, "telnet")):
        assert reply.status_code == 400
        assert reply.json()["detail"] == {
            "code": "permission_kind_unknown",
            "params": {"kind": kind},
        }
    assert runtime.pushed == []


def test_setting_one_clients_kinds_pushes_only_that_client(api):
    client, runtime = api
    registry = ClientRegistry()
    alice = registry.create("alice")
    registry.create("bob")

    reply = client.post(
        "/api/hub/client/permission/set",
        json={"client_id": alice, "kinds": ["terminal", "web"]},
    )

    rows = {row["id"]: row for row in reply.json()["clients"]}
    assert rows[alice]["permission"] == ["web", "terminal"]
    assert runtime.pushed == [alice]


def test_null_kinds_put_a_client_back_on_the_default(api):
    client, runtime = api
    registry = ClientRegistry()
    alice = registry.create("alice")
    registry.set_permission(alice, ["web"])

    reply = client.post(
        "/api/hub/client/permission/set", json={"client_id": alice, "kinds": None}
    )

    assert reply.json()["clients"][0]["permission"] is None
    assert ClientRegistry().get(alice).permission is None
    assert runtime.pushed == [alice]


def test_a_device_filter_is_stored_and_listed_for_the_default_and_one_client(api):
    client, runtime = api
    alice = ClientRegistry().create("alice")
    device = DeviceRegistry().create("argon")

    default = client.post(
        "/api/hub/client/default_permission/set",
        json={"kinds": ["web", "terminal"], "devices": {"web": [device.id]}},
    )
    own = client.post(
        "/api/hub/client/permission/set",
        json={
            "client_id": alice,
            "kinds": ["terminal"],
            "devices": {"terminal": [device.id]},
        },
    )

    assert default.json()["default_permission_devices"] == {"web": [device.id]}
    assert own.json()["clients"][0]["permission_devices"] == {"terminal": [device.id]}
    assert runtime.pushed == ["client", alice]


def test_a_filter_on_a_kind_that_takes_none_or_an_unknown_device_is_a_coded_400(
    api,
):
    client, runtime = api
    alice = ClientRegistry().create("alice")

    overlay = client.post(
        "/api/hub/client/default_permission/set",
        json={"kinds": ["overlay"], "devices": {"overlay": []}},
    )
    panel = client.post(
        "/api/hub/client/permission/set",
        json={"client_id": alice, "kinds": ["panel"], "devices": {"panel": ["d1"]}},
    )
    unknown = client.post(
        "/api/hub/client/permission/set",
        json={"client_id": alice, "kinds": ["web"], "devices": {"web": ["gone"]}},
    )

    assert overlay.status_code == 400
    assert overlay.json()["detail"] == {
        "code": "permission_kind_unknown",
        "params": {"kind": "overlay"},
    }
    assert panel.status_code == 400
    assert panel.json()["detail"] == {
        "code": "permission_kind_unknown",
        "params": {"kind": "panel"},
    }
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == {
        "code": "permission_device_unknown",
        "params": {"device_id": "gone"},
    }
    assert runtime.pushed == []


def test_taking_ai_away_revokes_the_clients_gateway_key(api):
    client, _ = api
    client_id = ClientRegistry().create("alice")
    from neutrino_hub.modules.clients.ai_keys import ensure_client_key

    ensure_client_key(ClientRegistry(), ClientRegistry().get(client_id))

    client.post(
        "/api/hub/client/permission/set",
        json={"client_id": client_id, "kinds": ["web"]},
    )

    assert load_config().client_keys == []
    assert ClientRegistry().get(client_id).ai_key_id is None


NETBIRD_OVERLAY = {
    "provider": "netbird",
    "setup_key": "A1B2C3D4-0000-4000-8000-000000000000",  # scan: allow
    "management_url": "",
    "fqdn": "hub.netbird.cloud",
}


def test_a_client_link_carries_the_overlays_while_the_default_allows_it(api):
    client, runtime = api
    runtime.overlays = [NETBIRD_OVERLAY]

    with_overlay = client.post("/api/hub/client/enrollment/create", json={"name": "a"})
    ClientRegistry().set_default_permission(["web"])
    without = client.post("/api/hub/client/enrollment/create", json={"name": "b"})

    assert decoded_link(with_overlay.json()["link"])["overlays"] == [NETBIRD_OVERLAY]
    assert decoded_link(without.json()["link"])["overlays"] == []


def test_a_client_link_with_no_overlay_to_join_carries_an_empty_list(api):
    client, _ = api

    reply = client.post("/api/hub/client/enrollment/create", json={"name": "a"})

    payload = decoded_link(reply.json()["link"])
    assert payload["overlays"] == []
    assert "overlay" not in payload


def test_the_enrollment_view_carries_one_link_and_no_qr_link(api):
    client, _ = api

    reply = client.post("/api/hub/client/enrollment/create", json={"name": "a"})

    assert set(reply.json()) == {"link", "expires_at", "expires_in_s"}


# --- the panel sessions a client's sign-in opened ---


def signed_in(runtime, name: str = "laptop") -> tuple:
    """A client holding the panel permission, signed in to the panel."""
    registry = ClientRegistry()
    client_id = registry.create(name)
    registry.set_permission(client_id, ["web", "panel"])
    return client_id, runtime.sessions.open_for_client(client_id)


def test_disabling_a_client_ends_its_panel_session(api):
    client, runtime = api
    client_id, session = signed_in(runtime)

    client.post("/api/hub/client/disable", json={"client_id": client_id})

    assert not runtime.sessions.is_valid(session)


def test_removing_a_client_ends_its_panel_session(api):
    client, runtime = api
    client_id, session = signed_in(runtime)

    client.post("/api/hub/client/remove", json={"client_id": client_id})

    assert not runtime.sessions.is_valid(session)


def test_taking_the_panel_from_a_client_ends_its_session_and_no_others(api):
    client, runtime = api
    client_id, session = signed_in(runtime)
    other_id, other_session = signed_in(runtime, "desk")

    client.post(
        "/api/hub/client/permission/set",
        json={"client_id": client_id, "kinds": ["web"]},
    )

    assert not runtime.sessions.is_valid(session)
    assert runtime.sessions.is_valid(other_session)


def test_taking_the_panel_from_the_default_ends_its_followers_sessions(api):
    client, runtime = api
    registry = ClientRegistry()
    follower = registry.create("laptop")
    registry.set_default_permission(["web", "panel"])
    session = runtime.sessions.open_for_client(follower)
    own_id, own_session = signed_in(runtime, "desk")

    client.post("/api/hub/client/default_permission/set", json={"kinds": ["web"]})

    assert not runtime.sessions.is_valid(session)
    assert runtime.sessions.is_valid(own_session)
