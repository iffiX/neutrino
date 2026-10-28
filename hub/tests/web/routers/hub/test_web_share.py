"""The Clients page's Web shares: the list fields, the make and the revoke.

The shares file and the vault are real over a config root of their own; the
published list, the machines' sessions and the transport are played by the
test. What these pin, by protocol.md's ``/api/hub/client`` and "Web shares":
a make refuses an empty name, a ``days`` outside the four, a site that is
not listed or an ``https://`` origin, an entry no share can offer, a hub
with no certificate or no address, and a locked vault; it returns the link
once and stores no copy of it; the link names the public address first; a
guest account's app gets a guest, and its module's state holds the guest;
the machine's ``details.guests`` moves the share from preparing to failed or
active; the list draws each share's state and count; a revoke ends the share
and closes its pages; and each end pushes a guest's machine its state.
"""

import base64
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
)
from neutrino_hub.modules.channel.sessions import ChannelSessionRegistry
from neutrino_hub.modules.clients import web_shares
from neutrino_hub.modules.clients.web_shares import WebShareRegistry
from neutrino_hub.modules.devices import desired_state as desired_state_module
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.module_table import (
    DEVICE_MODULE_ROWS,
    DeviceModuleRow,
)
from neutrino_hub.web import web_share_access
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import client as clients_router
from neutrino_hub.web.routers.hub import web_share as web_share_router
from neutrino_hub.web.web_share_access import (
    PanelWebShareSweeper,
    WebShareGuestSessions,
    share_site,
)
from tests.conftest import unlock_vault

FINGERPRINT = ":".join(["AB"] * 32)
DEVICE = "d" * 32
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}
APPS = [
    {
        "id": f"ayakaleaf_{DEVICE}",
        "title": "Ayakaleaf",
        "source": "module",
        "device_id": DEVICE,
        "device_name": "box",
        "local_name": "",
        "description": "",
    },
    {
        "id": f"code_server_{DEVICE}_alice",
        "title": "code-server (alice)",
        "source": "module",
        "device_id": DEVICE,
        "device_name": "box",
        "local_name": "",
        "description": "",
    },
    {
        "id": "declared_nas",
        "title": "NAS",
        "source": "declared",
        "device_id": "",
        "device_name": "",
        "local_name": "",
        "description": "",
    },
]
ENTRIES = [
    {
        "id": f"ayakaleaf_{DEVICE}_web",
        "app_id": f"ayakaleaf_{DEVICE}",
        "type": "web",
        "source": "module",
        "description_code": "ayakaleaf_module",
        "description_params": {},
        "payload": {"url": "http://192.168.100.7:8900/", "is_token_required": True},
        "device_id": DEVICE,
    },
    {
        "id": f"code_server_{DEVICE}_alice_web",
        "app_id": f"code_server_{DEVICE}_alice",
        "type": "web",
        "source": "module",
        "description_code": "code_server_module",
        "description_params": {"account": "alice"},
        "payload": {"url": "http://192.168.100.7:8901/", "is_token_required": True},
        "device_id": DEVICE,
    },
    {
        "id": "declared_nas_web",
        "app_id": "declared_nas",
        "type": "web",
        "source": "declared",
        "description_code": "declared",
        "description_params": {},
        "payload": {"url": "http://192.168.100.9:5000/admin"},
        "device_id": "",
    },
    {
        "id": "declared_nas_port",
        "app_id": "declared_nas",
        "type": "port",
        "source": "declared",
        "description_code": "declared",
        "description_params": {},
        "payload": {"host": "192.168.100.9", "port": 22},
        "device_id": "",
    },
]
MANIFESTS = {
    "ayakaleaf": {"web_share": {"guest_login": "guest_account"}},
    "code_server": {"web_share": {"guest_login": "run_account"}},
}


class RecordingEvents:
    def __init__(self):
        self.published: list = []

    def publish(self, event_type, key="", data=None):
        self.published.append(event_type)


class FakePublished:
    def __init__(self):
        self.listed = list(ENTRIES)

    def entries(self) -> tuple:
        return list(self.listed), "f"

    def apps(self) -> list:
        return list(APPS)


class FakeAgents(ChannelSessionRegistry):
    def __init__(self):
        super().__init__(CHANNEL_ROLE_AGENT)
        self.online: set = {DEVICE}
        self.reported: dict = {}

    def is_online(self, key: str) -> bool:
        return key in self.online

    def reports(self) -> dict:
        return dict(self.reported)


class FakeChannel:
    loop = None
    is_connected = False

    async def send_command(self, command, **fields):
        return {}


class FakeSession:
    def __init__(self, session_id):
        self.session_id = session_id
        self.is_ended = False

    def mark_ended(self):
        self.is_ended = True


class FakeRuntime:
    def __init__(self):
        self.events = RecordingEvents()
        self.published_services = FakePublished()
        self.agent_sessions = FakeAgents()
        self.client_sessions = ChannelSessionRegistry(CHANNEL_ROLE_CLIENT)
        self.web_share_guests = WebShareGuestSessions()
        self.channel = FakeChannel()
        self.device_address: dict = {}
        self.pushed: list = []

    def device_names(self) -> dict:
        return {DEVICE: "box"}

    def push_desired_state(self, key: str) -> None:
        self.pushed.append(key)


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(
        web_share_access,
        "channel_urls",
        lambda runtime: ["tcp://192.168.100.1:8443", "tcp://frp.example:31234"],
    )
    monkeypatch.setattr(web_share_access, "_direct_url", lambda: "")
    monkeypatch.setattr(
        web_share_access,
        "frp_url",
        lambda vendor: "tcp://frp.example:31234" if vendor == "sakurafrp" else "",
    )
    monkeypatch.setattr(web_share_access, "relay_url", lambda: "")
    monkeypatch.setattr(
        web_share_access.socket,
        "getaddrinfo",
        lambda host, port, **_: [(2, 1, 6, "", ("203.0.113.7", port))],
    )
    monkeypatch.setattr(
        web_share_access, "load_module_manifests", lambda: dict(MANIFESTS)
    )
    monkeypatch.setattr(
        web_share_access,
        "DEVICE_MODULE_ROWS",
        DEVICE_MODULE_ROWS
        + (
            DeviceModuleRow(
                name="ayakaleaf",
                kind="container",
                config_file="ayakaleaf.json",
                description_code="ayakaleaf_module",
            ),
        ),
    )
    monkeypatch.setattr(web_share_router, "read_dtls_fingerprint", lambda: FINGERPRINT)
    runtime = FakeRuntime()
    sent: list = []
    monkeypatch.setattr(
        web_share_access, "push_shares_from_thread", lambda given: sent.append("set")
    )
    monkeypatch.setattr(
        web_share_router, "push_shares_from_thread", lambda given: sent.append("set")
    )
    runtime.sent = sent
    app = FastAPI()
    app.include_router(clients_router.router)
    app.include_router(web_share_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), runtime


def decoded(link: str) -> dict:
    fragment = link.split("#", 1)[1]
    return json.loads(base64.urlsafe_b64decode(fragment + "=" * (-len(fragment) % 4)))


def create(client, **fields):
    body = {
        "name": "paper",
        "entry_id": f"ayakaleaf_{DEVICE}_web",
        "days": 7,
        "site": "https://neutrino-share.pages.dev",
    }
    body.update(fields)
    return client.post("/api/hub/client/web_share/create", json=body)


def test_the_list_offers_each_web_entry_with_its_guest_login(api):
    client, _ = api

    body = client.get("/api/hub/client").json()

    assert body["web_shares"] == []
    assert body["web_share_sites"][0]["url"] == "https://neutrino-share.pages.dev"
    assert [
        (entry["entry_id"], entry["guest_login"], entry["visitor_account"])
        for entry in body["web_share_entries"]
    ] == [
        (f"ayakaleaf_{DEVICE}_web", "guest_account", ""),
        (f"code_server_{DEVICE}_alice_web", "run_account", "alice"),
        ("declared_nas_web", "app", ""),
    ]


def test_a_share_returns_its_link_once_and_keeps_a_hash_of_its_ticket(api, tmp_path):
    client, runtime = api

    response = create(client)

    assert response.status_code == 200
    body = response.json()
    facts = decoded(body["link"])
    assert body["link"].startswith("https://neutrino-share.pages.dev/__neutrino/#")
    assert facts["hub"] == {"ip": "203.0.113.7", "port": 31234, "fp": FINGERPRINT}
    assert facts["app"] == {"entry": f"ayakaleaf_{DEVICE}_web", "title": "Ayakaleaf"}
    stored_text = (tmp_path / "clients" / "web_shares.json").read_text()
    assert facts["ticket"] not in stored_text and facts["ice"]["pwd"] not in stored_text
    stored = WebShareRegistry().all()[0]
    assert stored.ticket_sha256 == hashlib.sha256(facts["ticket"].encode()).hexdigest()
    assert stored.device_id == DEVICE and stored.module == "ayakaleaf"
    share = body["share"]
    assert share["state"] == "preparing" and share["online_count"] == 0
    assert share["guest_email"] == f"{stored.guest.account}@share.neutrino"
    assert runtime.sent == ["set"] and runtime.pushed == [DEVICE]


def test_a_declared_app_has_no_guest_and_opens_at_its_path(api):
    client, runtime = api

    body = create(client, entry_id="declared_nas_web", days=None).json()

    assert decoded(body["link"])["app"]["path"] == "/admin"
    assert body["share"]["guest_email"] == "" and body["share"]["state"] == "active"
    assert body["share"]["expires_at"] is None and runtime.pushed == []


@pytest.mark.parametrize(
    "fields, status, code",
    [
        ({"name": " "}, 400, "body_invalid"),
        ({"days": 3}, 400, "body_invalid"),
        ({"site": "http://share.example"}, 400, "web_share_site_invalid"),
        ({"entry_id": "declared_nas_port"}, 400, "web_share_entry_invalid"),
    ],
)
def test_a_make_refuses_what_the_standard_names(api, fields, status, code):
    client, _ = api

    response = create(client, **fields)

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert WebShareRegistry().all() == []


def test_a_make_refuses_a_hub_with_no_certificate_or_no_address(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(
        web_share_router,
        "read_dtls_fingerprint",
        lambda: (_ for _ in ()).throw(FileNotFoundError()),
    )

    assert create(client).json()["detail"]["code"] == "transport_key_missing"

    monkeypatch.setattr(web_share_router, "read_dtls_fingerprint", lambda: FINGERPRINT)
    monkeypatch.setattr(web_share_access, "channel_urls", lambda runtime: [])

    assert create(client).json()["detail"]["code"] == "no_reachable_address"


def test_a_make_refuses_a_locked_vault(api, monkeypatch):
    client, _ = api

    def locked(data, aad):
        raise VaultLockedError()

    monkeypatch.setattr(web_shares, "seal_bytes", locked)

    response = create(client)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vault_locked"


def test_the_list_draws_a_shares_state_and_its_visitors(api):
    client, runtime = api
    share_id = create(client).json()["share"]["id"]
    account = WebShareRegistry().get(share_id).guest.account
    runtime.web_share_guests.add(share_id, FakeSession("g1"))
    runtime.web_share_guests.add(share_id, FakeSession("g2"))
    runtime.agent_sessions.reported = {
        DEVICE: {
            "modules": {
                "ayakaleaf": {"details": {"guests": [{"account": account, "code": ""}]}}
            }
        }
    }

    shown = client.get("/api/hub/client").json()["web_shares"][0]

    assert shown["state"] == "active" and shown["online_count"] == 2
    assert shown["app_title"] == "Ayakaleaf" and shown["device_name"] == "box"
    assert 0 < shown["expires_in_s"] <= 7 * 86400

    runtime.agent_sessions.online = set()
    runtime.published_services.listed = []

    shown = client.get("/api/hub/client").json()["web_shares"][0]
    assert shown["state"] == "unavailable" and shown["app_title"] == "Ayakaleaf"


def test_a_guest_account_share_puts_its_guest_in_the_module_s_state(
    api, monkeypatch, tmp_path
):
    client, runtime = api
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    share_id = create(client).json()["share"]["id"]
    guest = WebShareRegistry().get(share_id).guest

    config = DesiredStateStore().agent_config(DEVICE, "ayakaleaf", {}, PLATFORM)

    assert config["guests"] == [guest.opened()]
    assert config["guests"][0]["email"] == f"{guest.account}@share.neutrino"
    assert config["guests"][0]["password"] and config["guests"][0]["secret"]

    def drawn(reported: list) -> tuple:
        runtime.agent_sessions.reported = {
            DEVICE: {"modules": {"ayakaleaf": {"details": {"guests": reported}}}}
        }
        shown = client.get("/api/hub/client").json()["web_shares"][0]
        return shown["state"], shown["code"], shown["params"]

    failure = {"step": "register", "detail": "500"}
    made = {"account": guest.account, "code": "", "params": {}}
    other = {**made, "account": "guest-other"}
    failed = {**made, "code": "ayakaleaf_guest_failed", "params": failure}
    assert drawn([]) == ("preparing", "", {})
    assert drawn([other]) == ("preparing", "", {})
    assert drawn([failed]) == ("failed", "ayakaleaf_guest_failed", failure)
    assert drawn([made]) == ("active", "", {})


def test_a_revoke_ends_the_share_and_closes_its_pages(api, monkeypatch):
    client, runtime = api
    share_id = create(client).json()["share"]["id"]
    runtime.web_share_guests.add(share_id, FakeSession("g1"))
    closed: list = []
    monkeypatch.setattr(
        web_share_access,
        "_on_loop",
        lambda given, coroutine: closed.append(coroutine.cr_frame.f_locals)
        or coroutine.close(),
    )
    runtime.pushed.clear()

    response = client.post(
        "/api/hub/client/web_share/revoke", json={"share_id": share_id}
    )

    assert response.status_code == 200 and response.json()["web_shares"] == []
    assert WebShareRegistry().all() == []
    assert closed[0]["fields"] == {
        "session": "g1",
        "code": "share_unknown",
        "params": {},
    }
    assert runtime.pushed == [DEVICE]
    missing = client.post(
        "/api/hub/client/web_share/revoke", json={"share_id": share_id}
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "web_share_unknown"


def test_the_sweep_ends_the_expired_shares(api):
    client, runtime = api
    share_id = create(client, days=1).json()["share"]["id"]
    expires_at = WebShareRegistry().get(share_id).expires_at

    assert PanelWebShareSweeper(runtime=runtime).sweep_once(now=expires_at - 1) == []
    ended = PanelWebShareSweeper(runtime=runtime).sweep_once(now=expires_at)

    assert [share.id for share in ended] == [share_id]
    assert WebShareRegistry().all() == []


def test_the_link_names_direct_first_then_the_frp_vendors_then_the_relay(
    api, monkeypatch
):
    _, runtime = api
    urls = ["tcp://192.168.100.1:8443", "tcp://relay.example:20022"]
    monkeypatch.setattr(web_share_access, "channel_urls", lambda given: list(urls))
    monkeypatch.setattr(web_share_access, "frp_url", lambda vendor: "")
    monkeypatch.setattr(
        web_share_access, "relay_url", lambda: "tcp://relay.example:20022"
    )

    assert web_share_access.share_address(runtime) == ("203.0.113.7", 20022)

    urls.insert(1, "tcp://198.51.100.2:8443")
    monkeypatch.setattr(
        web_share_access, "_direct_url", lambda: "tcp://198.51.100.2:8443"
    )

    assert web_share_access.share_address(runtime)[1] == 8443

    monkeypatch.setattr(web_share_access, "_direct_url", lambda: "")
    monkeypatch.setattr(web_share_access, "relay_url", lambda: "")

    assert web_share_access.share_address(runtime) == ("203.0.113.7", 8443)


@pytest.mark.parametrize(
    "site, expected",
    [
        ("https://neutrino-share.pages.dev/", "https://neutrino-share.pages.dev"),
        ("https://share.example", "https://share.example"),
        ("https://share.example/copy", ""),
        ("http://share.example", ""),
        ("share.example", ""),
        ("https://share.example/#x", ""),
    ],
)
def test_a_site_is_listed_or_an_https_origin(site, expected):
    assert share_site(site) == expected


def test_a_machine_a_module_and_a_declared_app_take_their_shares_with_them(api):
    client, runtime = api
    ayakaleaf = create(client).json()["share"]["id"]
    code = create(client, entry_id=f"code_server_{DEVICE}_alice_web").json()
    nas = create(client, entry_id="declared_nas_web").json()["share"]["id"]

    ended = web_share_access.end_device_shares(runtime, DEVICE, "ayakaleaf")

    assert [share.id for share in ended] == [ayakaleaf]
    assert [share.id for share in web_share_access.end_app_shares(runtime, "x")] == []
    assert [
        share.id for share in web_share_access.end_app_shares(runtime, "declared_nas")
    ] == [nas]
    ended = web_share_access.end_device_shares(runtime, DEVICE)
    assert [share.id for share in ended] == [code["share"]["id"]]
    assert WebShareRegistry().all() == []


def test_a_share_whose_app_stopped_is_unavailable_and_kept(api):
    client, runtime = api
    create(client, entry_id=f"code_server_{DEVICE}_alice_web")
    runtime.published_services.listed = [
        entry for entry in ENTRIES if not entry["id"].startswith("code_server")
    ]

    shown = client.get("/api/hub/client").json()

    assert shown["web_shares"][0]["state"] == "unavailable"
    assert f"code_server_{DEVICE}_alice_web" not in [
        entry["entry_id"] for entry in shown["web_share_entries"]
    ]
